"""
backend/geometry/parting_line_v2/regions.py
-------------------------------------------
Gate H3 (surface separation) and the core/cavity classification it produces
(plan §7 H3, §9).

The central idea
----------------
**Core/cavity classification is a byproduct of the feasibility test, not an
independent computation.** H3 asks whether ``Γ`` partitions ``∂S`` into exactly
two connected regions — the Jordan-curve condition C4. If it does, those two
regions *are* the cavity and core sets, and the classification is consistent
with the parting line by construction.

v1 instead classifies each face independently by the sign of one normal
sample::

        sdot = dot3(face.normal, pull_direction)      # core_cavity.py:149
        cavity if sdot > 0.05, core if < -0.05, else "parting"

That never looks at the parting line at all (audit RC-8), so a face can be
labelled ``core`` while sitting on the cavity side of the actual loop and
nothing detects the contradiction. It also forces a face that *straddles* the
loop onto one side, which is wrong exactly for the large curved flanks where
it matters most.

Level 0 scope
-------------
Loops run along B-Rep edges only (Track B lands in P2), so no face is cut by
``Γ`` and the cheap **face-adjacency** form of H3 is not an approximation —
it is **exact**. The full UV face-splitting form is P3's job, needed only once
face-interior curves exist.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterator

from backend.geometry.parting_line_v2.contracts import (
    CorePinEligibility,
    DelegatedSecondaryAction,
    DelegationEligibility,
)
from backend.geometry.parting_line_v2.types import EdgeBacking, FaceClassification, PartingLoopCandidate
from backend.models.geometry_models import PartGeometry, Vec3, dot3

try:
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
    from OCC.Core.BRepBndLib import brepbndlib
    from OCC.Core.BRepTools import breptools
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.GeomAbs import GeomAbs_Cylinder
    from OCC.Core.GeomLProp import GeomLProp_SLProps

    from backend.geometry.step_loader import _face_normal_at_uv

    _OCC_AVAILABLE = True
except Exception:  # pragma: no cover
    _OCC_AVAILABLE = False


__all__ = [
    "SeparationResult", "separate_surface", "classify_regions", "mean_abs_g",
    "check_core_pin_eligibility", "find_bridge_faces", "resolve_primary_split_param",
    "validate_delegation",
]


def mean_abs_g(face: object, pull_direction: Vec3, grid: int) -> float:
    """
    ``(1/A)·∫_f |n̂·d̂| dA``, by **area-weighted** ``M × M`` quadrature.

    This is the per-face factor in the Cauchy projected-area bound (plan §8.1),
    and it has to be right twice over:

    **1. It must be an integral, not a point sample.** Replacing
    ``∫_f |n̂·d̂| dA`` with ``A_f·|n̂(centroid)·d̂|`` has no bounding property at
    all — measured on F7 it yielded coverage 104.4%, a loop apparently
    covering more than the whole part.

    **2. It must be weighted by the area element**, not uniform in ``(u,v)``::

            ⟨|g|⟩ = Σ_i |g_i|·J_i  /  Σ_i J_i ,      J = ‖S_u × S_v‖

    Uniform ``(u,v)`` sampling is only correct where the Jacobian is constant.
    On a sphere it oversamples the poles: it returns
    ``⟨|sin v|⟩_uniform = 2/π ≈ 0.637`` against the true area-weighted
    ``0.5`` — a **27% overestimate** of the denominator, which showed up as
    F4's great circle scoring 80.7% coverage when the correct answer is 100%.
    """
    stored = abs(dot3(face.normal, pull_direction)) if face.normal_valid else 0.0
    if not _OCC_AVAILABLE or grid < 2:
        return stored
    try:
        surface = BRep_Tool.Surface(face.occ_face)
        u_min, u_max, v_min, v_max = breptools.UVBounds(face.occ_face)
    except Exception:
        return stored
    if not all(math.isfinite(x) for x in (u_min, u_max, v_min, v_max)):
        return stored

    weighted = 0.0
    total_weight = 0.0
    for i in range(grid):
        for j in range(grid):
            u = u_min + (u_max - u_min) * (i + 0.5) / grid
            v = v_min + (v_max - v_min) * (j + 0.5) / grid
            normal = _face_normal_at_uv(face.occ_face, u, v)
            if normal is None:
                continue
            try:
                props = GeomLProp_SLProps(surface, u, v, 1, 1e-9)
                du, dv = props.D1U(), props.D1V()
                jacobian = math.sqrt(
                    (du.Y() * dv.Z() - du.Z() * dv.Y()) ** 2
                    + (du.Z() * dv.X() - du.X() * dv.Z()) ** 2
                    + (du.X() * dv.Y() - du.Y() * dv.X()) ** 2
                )
            except Exception:
                jacobian = 1.0
            if jacobian <= 0.0:
                continue
            weighted += abs(dot3(normal, pull_direction)) * jacobian
            total_weight += jacobian
    return weighted / total_weight if total_weight > 0 else stored


@dataclass(frozen=True)
class SeparationResult:
    """Outcome of H3 for one candidate loop."""

    component_count: int
    components: tuple[frozenset[int], ...] = ()
    #: Faces with no valid normal, excluded from the adjacency graph.
    skipped_face_ids: frozenset[int] = frozenset()
    #: Faces the loop passes THROUGH, split into two nodes by sign(g).
    split_face_ids: frozenset[int] = frozenset()

    @property
    def separates(self) -> bool:
        return self.component_count == 2

    def to_dict(self) -> dict:
        return {
            "component_count": self.component_count,
            "component_sizes": [len(c) for c in self.components],
            "skipped_face_count": len(self.skipped_face_ids),
            "split_face_ids": sorted(self.split_face_ids),
        }


def _uncovered_parameter(
    edge: object, intervals: list[tuple[float, float]]
) -> float | None:
    """
    A parameter on ``edge`` NOT covered by ``Γ``, or ``None`` if fully covered.

    ``Γ`` covers parameter *intervals* of an edge, not whole edges. On F3's
    cap rim it covers only the upper semicircle; the lower semicircle still
    genuinely joins the cap to the lower half of the lateral face. Treating
    coverage as per-edge would sever that connection and reject the correct
    answer.
    """
    if not _OCC_AVAILABLE:
        return None
    try:
        adaptor = BRepAdaptor_Curve(edge)
        first, last = adaptor.FirstParameter(), adaptor.LastParameter()
    except Exception:
        return None
    if not (math.isfinite(first) and math.isfinite(last)) or last <= first:
        return None

    merged: list[tuple[float, float]] = []
    for lo, hi in sorted((min(a, b), max(a, b)) for a, b in intervals):
        if merged and lo <= merged[-1][1] + 1e-12:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))

    cursor = first
    for lo, hi in merged:
        if lo - cursor > 1e-9 * (last - first):
            return 0.5 * (cursor + lo)
        cursor = max(cursor, hi)
    if last - cursor > 1e-9 * (last - first):
        return 0.5 * (cursor + last)
    return None


def _g_at_edge_on_face(
    face: object, edge: object, pull_direction: Vec3, parameter: float | None = None
) -> float | None:
    """
    ``g`` on ``face`` at a given parameter of ``edge``'s pcurve (default: mid).

    Used to decide WHICH sub-region of a split face a shared edge attaches to.
    The parameter must be taken in the edge's **uncovered** portion — that is
    the part still doing the connecting.
    """
    if not _OCC_AVAILABLE:
        return None
    try:
        pcurve, first, last = BRep_Tool.CurveOnSurface(edge, face)
        if pcurve is None:
            return None
        t = 0.5 * (first + last) if parameter is None else min(max(parameter, first), last)
        uv = pcurve.Value(t)
        normal = _face_normal_at_uv(face, uv.X(), uv.Y())
    except Exception:
        return None
    return dot3(normal, pull_direction) if normal is not None else None


def _axial_position_at_edge(edge_occ: object, pull_direction: Vec3) -> float | None:
    """Projection of an edge's midpoint onto the pull axis."""
    if not _OCC_AVAILABLE:
        return None
    try:
        adaptor = BRepAdaptor_Curve(edge_occ)
        t_mid = 0.5 * (adaptor.FirstParameter() + adaptor.LastParameter())
        p = adaptor.Value(t_mid)
        return dot3((p.X(), p.Y(), p.Z()), pull_direction)
    except Exception:
        return None


def _tooling_split_positive_share(
    face: object, pull_direction: Vec3, split_param: float, grid: int
) -> float:
    """
    Area-weighted fraction of ``face`` whose axial position (projected onto
    ``pull_direction``) is ``>= split_param`` (plan Phase 3A, D-043 area
    reporting fix).

    A coaxial tooling-split face has ``g ~ 0`` everywhere on its own
    surface — that is the entire reason D-043 exists (``_g_at_edge_on_face``
    cannot distinguish its two ends either). So unlike a genuine Track-B
    split face, ``mean_g``'s sign/magnitude carries no information about
    where the split actually falls; this samples the face's own AXIAL
    POSITION instead, using the exact same area-weighted ``M x M`` Jacobian
    quadrature as ``mean_abs_g``.
    """
    if not _OCC_AVAILABLE or grid < 2:
        return 0.5
    try:
        surface = BRep_Tool.Surface(face.occ_face)
        u_min, u_max, v_min, v_max = breptools.UVBounds(face.occ_face)
    except Exception:
        return 0.5
    if not all(math.isfinite(x) for x in (u_min, u_max, v_min, v_max)):
        return 0.5

    positive_weight = 0.0
    total_weight = 0.0
    for i in range(grid):
        for j in range(grid):
            u = u_min + (u_max - u_min) * (i + 0.5) / grid
            v = v_min + (v_max - v_min) * (j + 0.5) / grid
            try:
                props = GeomLProp_SLProps(surface, u, v, 1, 1e-9)
                point = props.Value()
                du, dv = props.D1U(), props.D1V()
                jacobian = math.sqrt(
                    (du.Y() * dv.Z() - du.Z() * dv.Y()) ** 2
                    + (du.Z() * dv.X() - du.X() * dv.Z()) ** 2
                    + (du.X() * dv.Y() - du.Y() * dv.X()) ** 2
                )
            except Exception:
                continue
            if jacobian <= 0.0:
                continue
            axial = dot3((point.X(), point.Y(), point.Z()), pull_direction)
            if axial >= split_param:
                positive_weight += jacobian
            total_weight += jacobian
    return positive_weight / total_weight if total_weight > 0 else 0.5


def _tooling_split_cavity_share(
    part: PartGeometry,
    face_id: int,
    split_param: float,
    pull_direction: Vec3,
    cavity_component: frozenset[int],
    core_component: frozenset[int],
    grid: int,
) -> float | None:
    """
    Fraction of a tooling-split face's area to attribute to the CAVITY side
    (plan Phase 3A).

    ``SeparationResult.components`` stores plain face-id sets, not
    ``(face_id, side)`` pairs, so which axial side of a split face ended up
    in which region is not directly recorded. This recovers it read-only,
    without touching H3/``separate_surface``: find one neighbouring face
    that is NOT itself tooling-split (so its region membership is
    unambiguous), read the shared edge's axial position exactly the way
    ``separate_surface`` itself decided that neighbour's side, and use that
    single reference to map "axial >= split_param" to whichever region the
    neighbour is actually in. Returns ``None`` if no usable reference edge
    exists, so the caller can fall back to the previous behaviour.
    """
    faces_by_id = {f.face_id: f for f in part.faces}
    edges_by_id = {e.edge_id: e for e in part.edges}
    face = faces_by_id.get(face_id)
    if face is None:
        return None

    for edge_id in part.face_to_edges.get(face_id, []):
        neighbours = [fid for fid in part.edge_to_faces.get(edge_id, []) if fid != face_id]
        if not neighbours:
            continue
        neighbour_id = neighbours[0]
        if neighbour_id not in cavity_component and neighbour_id not in core_component:
            continue
        edge = edges_by_id.get(edge_id)
        if edge is None:
            continue
        axial = _axial_position_at_edge(edge.occ_edge, pull_direction)
        if axial is None:
            continue
        neighbour_in_cavity = neighbour_id in cavity_component
        positive_side_is_cavity = (axial >= split_param) == neighbour_in_cavity
        positive_share = _tooling_split_positive_share(face, pull_direction, split_param, grid)
        return positive_share if positive_side_is_cavity else (1.0 - positive_share)
    return None


def separate_surface(
    part: PartGeometry,
    loop_edge_ids: frozenset[int],
    *,
    split_face_ids: frozenset[int] = frozenset(),
    tooling_split_face_ids: dict[int, float] | None = None,
    pull_direction: Vec3 | None = None,
    loop_edge_intervals: dict[int, list[tuple[float, float]]] | None = None,
) -> SeparationResult:
    """
    Cut the face-adjacency graph along ``Γ`` and count connected components.

    **The adjacency rule that matters:** two faces remain adjacent iff they
    share **at least one edge that is not on Γ**. Two faces can share several
    edges; cutting the pair because *one* of them lies on the loop would
    over-partition and reject valid loops.

    **Face splitting (plan §7 H3 step 1).** Once Track B exists, ``Γ`` can run
    through a face INTERIOR, and the cheap edge-only form stops being exact —
    a sphere's great circle cuts its single face in two, but that face is one
    node with no link to cut, so the edge-only test reports 1 region and
    rejects the correct answer.

    Faces in ``split_face_ids`` are therefore split into **two** nodes. The
    split is by the **sign of g**, which is exact here: the cutting curve IS
    the level set ``g = 0``, so its two sides are precisely ``{g > 0}`` and
    ``{g < 0}``. A neighbouring face attaches to whichever side its shared
    edge lies on, decided by evaluating ``g`` at that edge's pcurve midpoint.

    ⚠ **Documented limitation:** this is exact when ``{g>0}`` and ``{g<0}`` are
    each *connected* on the face — true for a single monotone crossing, which
    covers every case in the corpus (sphere: one great circle; barrel: one
    circle; cylinder ⟂ pull: two rulings splitting the lateral face in two).
    A face crossed several times could have a disconnected side, which this
    would under-count. Building the full UV partition is only worth it if a
    real part is ever measured to need it.

    **Tooling splits (2026-08-15, D-043).** Faces in ``tooling_split_face_ids``
    (a ``face_id -> split_param`` map, disjoint from ``split_face_ids`` by
    construction) are ALSO split into two nodes, but by comparing each
    neighbouring edge's own axial position (projected onto ``pull_direction``)
    against ``split_param`` — never by sign of ``g``. This exists because a
    face exactly coaxial with the pull direction has ``g ≡ 0`` everywhere, so
    ``_g_at_edge_on_face`` cannot distinguish its two ends (both edges would
    evaluate to ~0.0 and collapse onto the same node) — the mechanism a
    Track-B split face uses does not apply here. See
    ``docs/DECISIONS_AND_ALGORITHMS.md`` D-043 for the full derivation and the
    validated proof this branch does not change behaviour when
    ``tooling_split_face_ids`` is empty (the default, and every caller before
    this milestone).

    ==================  ==========================================
    ``count == 2``      PASS — the two components are cavity/core
    ``count == 1``      REJECT — the loop does not separate the part
    ``count > 2``       REJECT — the loop over-partitions
    ==================  ==========================================
    """
    tooling = tooling_split_face_ids or {}
    assert split_face_ids.isdisjoint(tooling), (
        "a face may not use both split_face_ids (sign-of-g) and "
        "tooling_split_face_ids (axial-parameter) at once"
    )

    usable = {f.face_id for f in part.faces if f.normal_valid}
    skipped = frozenset(f.face_id for f in part.faces if not f.normal_valid)
    faces_by_id = {f.face_id: f for f in part.faces}
    edges_by_id = {e.edge_id: e for e in part.edges}
    split = split_face_ids & usable
    tooling_ids = set(tooling.keys()) & usable

    def node_of(face_id: int, side: float | None) -> tuple[int, int]:
        """(face_id, side) where side is 0 for unsplit, +1/-1 for a split face."""
        if face_id not in split and face_id not in tooling_ids:
            return (face_id, 0)
        return (face_id, 1 if (side is not None and side >= 0.0) else -1)

    shared: dict[tuple[int, int], set[int]] = {}
    for edge_id, face_ids in part.edge_to_faces.items():
        if len(face_ids) != 2:
            continue
        a, b = sorted(face_ids)
        if a not in usable or b not in usable:
            continue
        shared.setdefault((a, b), set()).add(edge_id)

    nodes: set[tuple[int, int]] = set()
    for face_id in usable:
        if face_id in split or face_id in tooling_ids:
            nodes.add((face_id, 1))
            nodes.add((face_id, -1))
        else:
            nodes.add((face_id, 0))

    adjacency: dict[tuple[int, int], set[tuple[int, int]]] = {n: set() for n in nodes}
    intervals_by_edge = loop_edge_intervals or {}
    for (a, b), edge_ids in shared.items():
        for edge_id in sorted(edge_ids):
            edge = edges_by_id.get(edge_id)
            # Sub-edge granularity: an edge counts as cut only where Γ actually
            # covers it. `free_parameter` is a point on the edge Γ does NOT
            # cover — if there is none, the edge is fully cut.
            if edge_id in intervals_by_edge:
                free_parameter = (
                    _uncovered_parameter(edge.occ_edge, intervals_by_edge[edge_id])
                    if edge is not None else None
                )
                if free_parameter is None:
                    continue
            elif edge_id in loop_edge_ids:
                continue
            else:
                free_parameter = None

            side_a = side_b = None
            if edge is not None and pull_direction is not None:
                if a in split:
                    side_a = _g_at_edge_on_face(
                        faces_by_id[a].occ_face, edge.occ_edge, pull_direction,
                        free_parameter,
                    )
                elif a in tooling_ids:
                    pos = _axial_position_at_edge(edge.occ_edge, pull_direction)
                    side_a = None if pos is None else (pos - tooling[a])
                if b in split:
                    side_b = _g_at_edge_on_face(
                        faces_by_id[b].occ_face, edge.occ_edge, pull_direction,
                        free_parameter,
                    )
                elif b in tooling_ids:
                    pos = _axial_position_at_edge(edge.occ_edge, pull_direction)
                    side_b = None if pos is None else (pos - tooling[b])
            node_a, node_b = node_of(a, side_a), node_of(b, side_b)
            adjacency[node_a].add(node_b)
            adjacency[node_b].add(node_a)

    seen: set[tuple[int, int]] = set()
    components: list[frozenset[int]] = []
    for start in sorted(adjacency):
        if start in seen:
            continue
        stack, group = [start], set()
        seen.add(start)
        while stack:
            node = stack.pop()
            group.add(node[0])
            for neighbour in sorted(adjacency[node]):
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        components.append(frozenset(group))

    components.sort(key=lambda c: (-len(c), min(c) if c else -1))
    return SeparationResult(
        component_count=len(components),
        components=tuple(components),
        skipped_face_ids=skipped,
        split_face_ids=frozenset(split),
    )


# ---------------------------------------------------------------------------
# Core-pin / tooling-split mechanism (2026-08-15, plan D-043)
#
# Two INDEPENDENT questions, kept structurally separate per the design:
#   1. `find_bridge_faces`            -- WHICH face(s), if any, are the
#                                         graph-theoretic cause of an H3
#                                         under-separation. Pure topology,
#                                         localization only, NOT a validity
#                                         test.
#   2. `check_core_pin_eligibility`   -- is a SPECIFIC face actually a
#                                         legitimate core-pin surface. The
#                                         independent geometric/manufacturing
#                                         gate, always run, never skipped.
# `resolve_primary_split_param` is the single canonical source of "where
# does this candidate's real boundary sit" -- every consumer of a split
# parameter must receive this same computed value, never resample it.
# ---------------------------------------------------------------------------

def _plain_face_adjacency(part: PartGeometry, loop_edge_ids: frozenset[int]) -> dict[int, set[int]]:
    """
    The plain (no split/tooling faces) face-adjacency graph, built by the
    SAME edge-cutting rule ``separate_surface`` uses for an unsplit graph:
    an edge counts as cut iff it is in ``loop_edge_ids``; two usable faces
    sharing any OTHER edge stay adjacent. Factored out so bridge
    localization can never silently diverge from what H3 itself computes.
    """
    usable = {f.face_id for f in part.faces if f.normal_valid}
    adjacency: dict[int, set[int]] = {fid: set() for fid in usable}
    for edge_id, face_ids in part.edge_to_faces.items():
        if len(face_ids) != 2 or edge_id in loop_edge_ids:
            continue
        a, b = face_ids
        if a not in usable or b not in usable:
            continue
        adjacency[a].add(b)
        adjacency[b].add(a)
    return adjacency


def _components(adjacency: dict[int, set[int]], exclude: int | None = None) -> list[frozenset[int]]:
    """Connected components of ``adjacency``, optionally with one node removed."""
    remaining = set(adjacency.keys())
    if exclude is not None:
        remaining.discard(exclude)
    seen: set[int] = set()
    components: list[frozenset[int]] = []
    for start in sorted(remaining):
        if start in seen:
            continue
        stack, group = [start], set()
        seen.add(start)
        while stack:
            node = stack.pop()
            group.add(node)
            for neighbour in adjacency.get(node, ()):
                if neighbour == exclude or neighbour in seen:
                    continue
                seen.add(neighbour)
                stack.append(neighbour)
        components.append(frozenset(group))
    return components


def _articulation_points(adjacency: dict[int, set[int]]) -> set[int]:
    """
    Iterative Tarjan low-link articulation-point algorithm (recursion-free,
    so it is safe on a part with hundreds of faces). Standard algorithm,
    unmodified: a node is an articulation point if removing it increases the
    number of connected components of its own connected subgraph.
    """
    disc: dict[int, int] = {}
    low: dict[int, int] = {}
    parent: dict[int, int | None] = {}
    ap: set[int] = set()
    timer = 0

    for root in sorted(adjacency):
        if root in disc:
            continue
        parent[root] = None
        disc[root] = low[root] = timer
        timer += 1
        root_children = 0
        stack: list[tuple[int, Iterator[int]]] = [(root, iter(sorted(adjacency[root])))]
        while stack:
            u, it = stack[-1]
            advanced = False
            for v in it:
                if v not in disc:
                    parent[v] = u
                    disc[v] = low[v] = timer
                    timer += 1
                    if u == root:
                        root_children += 1
                    stack.append((v, iter(sorted(adjacency[v]))))
                    advanced = True
                    break
                elif v != parent.get(u):
                    low[u] = min(low[u], disc[v])
            if not advanced:
                stack.pop()
                if stack:
                    p = stack[-1][0]
                    low[p] = min(low[p], low[u])
                    if p != root and low[u] >= disc[p]:
                        ap.add(p)
        if root_children > 1:
            ap.add(root)

    return ap


def find_bridge_faces(part: PartGeometry, loop_edge_ids: frozenset[int]) -> frozenset[int]:
    """
    Deterministic, candidate-LOCALIZATION-only bridge identification (plan
    D-043). Answers exactly one question: "if this specific face were split
    into two nodes here, would the plain edge-cut graph resolve to exactly
    two clean components, with the face's own neighbours dividing
    one-to-each-side." Pure topology — no geometric/manufacturing judgement
    is made here.

    **This is not proof that a face is valid for tooling splitting.** A face
    returned here may still fail ``check_core_pin_eligibility`` (wrong
    surface type, non-uniform g, etc.), and eligibility must always run
    afterward on any face this function returns — never skipped, and never
    used as a reason to widen the search to other faces.

    Returns an empty set whenever there is nothing to localize: the plain
    graph already separates (H3 would pass without any tooling mechanism),
    already over-partitions, or no single face's removal cleanly produces
    exactly two components with a clean one-to-each-side neighbour split.
    """
    adjacency = _plain_face_adjacency(part, loop_edge_ids)
    if not adjacency or len(_components(adjacency)) != 1:
        return frozenset()

    bridges: set[int] = set()
    for face_id in _articulation_points(adjacency):
        parts_without = _components(adjacency, exclude=face_id)
        if len(parts_without) != 2:
            continue
        neighbours = adjacency.get(face_id, set())
        side0 = {n for n in neighbours if n in parts_without[0]}
        side1 = {n for n in neighbours if n in parts_without[1]}
        if side0 and side1 and not (side0 & side1) and (side0 | side1) == neighbours:
            bridges.add(face_id)
    return frozenset(bridges)


def resolve_primary_split_param(
    part: PartGeometry, loop_edge_ids: frozenset[int], pull_direction: Vec3, *, tol: float = 1e-6,
) -> float:
    """
    THE single canonical source of "where does this candidate's real
    boundary sit" along the pull axis (plan D-043). Every consumer —
    ``check_core_pin_eligibility``, ``PartingLoopCandidate.
    tooling_split_face_ids``, ``CorePinInterface``, and the
    ``tooling_split_face_ids`` argument to ``separate_surface`` — must
    receive this EXACT value, never an independently resampled one. This
    guards against the class of defect already chased once in this project
    (two code paths silently disagreeing on "the same" geometric value at
    the sub-millimetre level).

    Raises ``ValueError`` if the boundary's edges do not agree on a single
    axial position within ``tol`` — such a boundary is not a candidate for
    core-pin closure at all, and that must fail loudly rather than average
    over a real disagreement.
    """
    edges_by_id = {e.edge_id: e for e in part.edges}
    positions: list[float] = []
    for edge_id in loop_edge_ids:
        edge = edges_by_id.get(edge_id)
        if edge is None:
            continue
        pos = _axial_position_at_edge(edge.occ_edge, pull_direction)
        if pos is not None:
            positions.append(pos)
    if not positions:
        raise ValueError("no real boundary edge with a resolvable axial position")
    lo, hi = min(positions), max(positions)
    if hi - lo > tol:
        raise ValueError(
            f"real boundary is not at a single consistent axial position: spread "
            f"{hi - lo:.9g} exceeds tolerance {tol:.3g} (min={lo!r}, max={hi!r})"
        )
    return sum(positions) / len(positions)


def check_core_pin_eligibility(
    part: PartGeometry, face_id: int, pull_direction: Vec3, cfg: object, split_param: float,
) -> CorePinEligibility:
    """
    The independent geometric/manufacturing gate (plan D-043). ``
    find_bridge_faces`` only says WHICH face is causally implicated in an H3
    failure; it makes no claim about whether that face is a legitimate
    core-pin surface. This is that separate check, and it must always run —
    even on a face ``find_bridge_faces`` returned.

    Five conditions, ALL required:
      (a) cylindrical surface;
      (b) cylinder axis parallel/antiparallel to the pull direction
          (``cfg.core_pin_axis_angle_tol``);
      (c) uniformly near-zero ``g`` (per-point, ``cfg.core_pin_uniform_g_max``
          — deliberately NOT H4's ``orientation_epsilon``/
          ``orientation_violation_max``, an area-fraction slack meant for a
          different purpose) over the ENTIRE face;
      (d) exactly two distinct neighbouring faces — a clean through-passage.
          This is what actually excludes an ordinary rib-lattice cylinder
          segment: such a face independently satisfies (a)-(c) (it is also
          exactly coaxial with uniform g on its own sub-face), but is always
          sandwiched among 4+ neighbours, never exactly 2;
      (e) ``split_param`` strictly inside this face's own longitudinal
          extent — a face entirely on one side of the candidate split needs
          no tooling treatment at all.
    """
    faces_by_id = {f.face_id: f for f in part.faces}
    face = faces_by_id.get(face_id)
    if face is None:
        return CorePinEligibility(face_id, False, f"face {face_id} does not exist on this part")
    if not _OCC_AVAILABLE:
        return CorePinEligibility(face_id, False, "OCC not available")

    surf = BRepAdaptor_Surface(face.occ_face)
    if surf.GetType() != GeomAbs_Cylinder:
        return CorePinEligibility(
            face_id, False, f"surface type is not Cylinder (type={surf.GetType()})"
        )

    axis_angle_tol = getattr(cfg, "core_pin_axis_angle_tol", 1e-6)
    cyl = surf.Cylinder()
    axis_dir = cyl.Axis().Direction()
    axis_vec = (axis_dir.X(), axis_dir.Y(), axis_dir.Z())
    cos_angle = abs(dot3(axis_vec, pull_direction))
    if cos_angle < 1.0 - axis_angle_tol:
        return CorePinEligibility(
            face_id, False,
            f"axis not parallel/antiparallel to pull direction (|cos|={cos_angle:.9f})",
        )

    eps_uniform = getattr(cfg, "core_pin_uniform_g_max", 1e-6)
    grid = getattr(cfg, "face_sample_grid", 11)
    mean_g, min_g, max_g, _ = _sample_face_g(face, pull_direction, grid)
    if max(abs(min_g), abs(max_g)) > eps_uniform:
        return CorePinEligibility(
            face_id, False,
            f"not uniformly zero-draft (min_g={min_g:.6g}, max_g={max_g:.6g}, "
            f"limit={eps_uniform:.3g})",
        )

    neighbours = set(part.face_adjacency.get(face_id, []))
    if len(neighbours) != 2:
        return CorePinEligibility(
            face_id, False,
            f"has {len(neighbours)} distinct neighbouring face(s), require exactly 2: "
            f"{sorted(neighbours)}",
        )

    box = Bnd_Box()
    brepbndlib.Add(face.occ_face, box)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    corners = [(x, y, z) for x in (xmin, xmax) for y in (ymin, ymax) for z in (zmin, zmax)]
    projections = [dot3(c, pull_direction) for c in corners]
    face_lo, face_hi = min(projections), max(projections)
    if not (face_lo < split_param < face_hi):
        return CorePinEligibility(
            face_id, False,
            f"split_param={split_param:.6g} not strictly inside face's longitudinal "
            f"extent [{face_lo:.6g}, {face_hi:.6g}]",
        )

    return CorePinEligibility(
        face_id, True,
        f"eligible: cylinder, axis-aligned (|cos|={cos_angle:.9f}), uniform g "
        f"(max|g|={max(abs(min_g), abs(max_g)):.3g}), exactly 2 neighbours {sorted(neighbours)}",
    )


# ---------------------------------------------------------------------------
# Secondary-action delegation (D-044, frozen semantics)
#
# `validate_delegation` proves ONLY: "this explicitly authorized secondary-
# action claim is structurally self-consistent for this candidate." It is
# NOT, and must never be read as, a geometric release/sweep verification --
# no such mechanism exists in this codebase (D-042 documents why the one
# candidate approach, Boolean sweep, is unreliable for exactly this class of
# geometry). `DelegationEvidence.geometric_verification` stays "unverified"
# regardless of this function's result.
# ---------------------------------------------------------------------------

def _is_connected_subgraph(face_ids: frozenset[int], face_adjacency: dict) -> bool:
    """
    True iff `face_ids`, restricted to edges BETWEEN members of `face_ids`,
    forms one connected component. This proves only that the claimed set is
    not an arbitrary disconnected collection -- it does NOT prove one
    physical secondary movement is mechanically sufficient to release it
    (a connected group can still require multiple independent movements).
    """
    if not face_ids:
        return False
    start = next(iter(face_ids))
    seen = {start}
    stack = [start]
    while stack:
        node = stack.pop()
        for neighbour in face_adjacency.get(node, ()):
            if neighbour in face_ids and neighbour not in seen:
                seen.add(neighbour)
                stack.append(neighbour)
    return seen == set(face_ids)


def validate_delegation(
    part: PartGeometry,
    candidate: PartingLoopCandidate,
    delegation: DelegatedSecondaryAction,
    primary_pull_direction: Vec3,
    cfg: object,
) -> DelegationEligibility:
    """
    Hard contract validation, then structural sanity -- both required,
    neither sufficient on its own, and passing both is NOT a claim that the
    secondary mechanism has been geometrically proven to release the
    delegated faces (D-044).

    Hard requirements (fail -> reject, delegation entirely unused):
      - `delegation.evidence.source` non-empty
      - `delegation.evidence.note` non-empty
      - `delegation.face_ids` non-empty and every id exists on `part`
      - `movement_direction` is a valid unit vector
      - `movement_direction` is meaningfully non-parallel to
        `primary_pull_direction` (`cfg.delegation_max_parallel_cos`)
      - `delegation.face_ids` does not intersect this candidate's
        `loop_face_ids` (derived from `candidate.segments`, same
        `EdgeBacking`-only rule `gates.py` itself uses)

    Structural sanity (fail -> reject; pass -> NOT proof of feasibility):
      - `delegation.face_ids` forms one connected component of
        `part.face_adjacency`

    Deliberately absent: any face-count or area threshold (small,
    legitimate side-action features must remain representable), and any
    geometric release/sweep/interference test (not available in this
    codebase today -- see module docstring above).
    """
    if not delegation.evidence.source:
        return DelegationEligibility(False, "evidence.source is empty")
    if not delegation.evidence.note:
        return DelegationEligibility(False, "evidence.note is empty")

    if not delegation.face_ids:
        return DelegationEligibility(False, "face_ids is empty")
    known_face_ids = {f.face_id for f in part.faces}
    unknown = delegation.face_ids - known_face_ids
    if unknown:
        return DelegationEligibility(False, f"face_ids reference unknown faces: {sorted(unknown)}")

    direction = delegation.movement_direction
    magnitude = math.sqrt(sum(c * c for c in direction))
    if abs(magnitude - 1.0) > 1e-6:
        return DelegationEligibility(False, f"movement_direction is not a unit vector (|v|={magnitude:.6g})")

    cos_angle = abs(dot3(direction, primary_pull_direction))
    max_parallel_cos = getattr(cfg, "delegation_max_parallel_cos", 0.99)
    if cos_angle > max_parallel_cos:
        return DelegationEligibility(
            False,
            f"movement_direction is not meaningfully distinct from the primary pull "
            f"direction (|cos|={cos_angle:.6f}, limit {max_parallel_cos:.6f})",
        )

    loop_edge_ids = frozenset(
        s.backing.edge_id for s in candidate.segments if isinstance(s.backing, EdgeBacking)
    )
    loop_face_ids = frozenset(
        face_id for edge_id in loop_edge_ids for face_id in part.edge_to_faces.get(edge_id, ())
    )
    overlap = delegation.face_ids & loop_face_ids
    if overlap:
        return DelegationEligibility(
            False, f"delegated faces intersect the primary parting line: {sorted(overlap)}"
        )

    if not _is_connected_subgraph(delegation.face_ids, part.face_adjacency):
        return DelegationEligibility(
            False, "delegated face set is not one connected feature (structural sanity check)"
        )

    return DelegationEligibility(
        True,
        "structurally self-consistent: authorized, non-parallel movement, disjoint from "
        "the primary loop, connected face set. NOT a proof of physical release.",
    )


@dataclass(frozen=True)
class RegionClassification:
    """Cavity/core assignment derived from H3's two regions (plan §9)."""

    cavity_face_ids: frozenset[int]
    core_face_ids: frozenset[int]
    faces: tuple[FaceClassification, ...] = ()
    cavity_area_mm2: float = 0.0
    core_area_mm2: float = 0.0
    ambiguous_area_mm2: float = 0.0
    total_area_mm2: float = 0.0
    inconsistent_face_ids: tuple[int, ...] = ()
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ambiguous_area_fraction(self) -> float:
        return self.ambiguous_area_mm2 / self.total_area_mm2 if self.total_area_mm2 > 0 else 0.0

    # -----------------------------------------------------------------------
    # Region-balance / meaningfulness signal (plan Phase 3A).
    #
    # Purely diagnostic — derived from areas `classify_regions` already
    # computes, nothing new is measured. NOT a feasibility gate: H3/H4 never
    # read these, and a small `smaller_region_area_fraction` does not by
    # itself make a candidate invalid (Part3 +Z candidate 110's core is only
    # ~39.8% of confident area by a handful of faces yet is a real,
    # physically coherent feature; +X/+Y's degenerate cores are under 1-6%).
    # Deliberately NO "meaningful"/"degenerate" label: the investigation
    # that motivated this only has three data points (one genuine, two
    # degenerate) — not enough to defend a specific cutoff, and inventing
    # one here would be exactly the arbitrary threshold this phase was
    # explicitly told not to add. Callers get the raw numbers and judge.
    # -----------------------------------------------------------------------

    @property
    def confident_area_mm2(self) -> float:
        """Cavity + core area — the part of the surface NOT left ambiguous."""
        return self.cavity_area_mm2 + self.core_area_mm2

    @property
    def cavity_area_fraction_of_confident(self) -> float:
        confident = self.confident_area_mm2
        return self.cavity_area_mm2 / confident if confident > 0 else 0.0

    @property
    def core_area_fraction_of_confident(self) -> float:
        confident = self.confident_area_mm2
        return self.core_area_mm2 / confident if confident > 0 else 0.0

    @property
    def smaller_region_area_fraction(self) -> float:
        """min(cavity, core) as a fraction of confident area — the signal
        that actually distinguishes a real second mold half from a
        degenerate sliver, unlike face COUNT (see module docstring context
        in D-043/Phase 3 investigation: a 5-face region can be 40% of area;
        a 24-face region can be 6%)."""
        return min(self.cavity_area_fraction_of_confident, self.core_area_fraction_of_confident)

    def to_dict(self) -> dict:
        return {
            "cavity_face_count": len(self.cavity_face_ids),
            "core_face_count": len(self.core_face_ids),
            "cavity_area_mm2": round(self.cavity_area_mm2, 3),
            "core_area_mm2": round(self.core_area_mm2, 3),
            "ambiguous_area_mm2": round(self.ambiguous_area_mm2, 3),
            "total_area_mm2": round(self.total_area_mm2, 3),
            "ambiguous_area_fraction": round(self.ambiguous_area_fraction, 6),
            "confident_area_mm2": round(self.confident_area_mm2, 3),
            "cavity_area_fraction_of_confident": round(self.cavity_area_fraction_of_confident, 6),
            "core_area_fraction_of_confident": round(self.core_area_fraction_of_confident, 6),
            "smaller_region_area_fraction": round(self.smaller_region_area_fraction, 6),
            "inconsistent_face_ids": list(self.inconsistent_face_ids),
            "faces": [f.to_dict() for f in self.faces],
            "warnings": list(self.warnings),
        }


def _sample_face_g(face: object, pull_direction: Vec3, grid: int) -> tuple[float, float, float, int]:
    """
    ``(mean_g, min_g, max_g, sample_count)`` from an ``M × M`` UV sample.

    Multi-sampling is what makes an inconsistency *detectable*: a face whose
    sampled ``g`` values straddle zero but which carries a single cavity/core
    label is reporting more certainty than the geometry supports. v1's single
    UV-centroid sample cannot see this by construction.

    Falls back to the face's stored centroid normal when OCC sampling is
    unavailable, reporting ``sample_count = 1`` so the caller can tell.
    """
    stored_g = dot3(face.normal, pull_direction) if face.normal_valid else 0.0
    if not _OCC_AVAILABLE or grid < 2:
        return stored_g, stored_g, stored_g, 1

    try:
        u_min, u_max, v_min, v_max = breptools.UVBounds(face.occ_face)
    except Exception:
        return stored_g, stored_g, stored_g, 1
    if not all(math.isfinite(x) for x in (u_min, u_max, v_min, v_max)):
        return stored_g, stored_g, stored_g, 1

    values: list[float] = []
    for i in range(grid):
        for j in range(grid):
            u = u_min + (u_max - u_min) * (i + 0.5) / grid
            v = v_min + (v_max - v_min) * (j + 0.5) / grid
            normal = _face_normal_at_uv(face.occ_face, u, v)
            if normal is not None:
                values.append(dot3(normal, pull_direction))
    if not values:
        return stored_g, stored_g, stored_g, 1
    return sum(values) / len(values), min(values), max(values), len(values)


def classify_regions(
    part: PartGeometry,
    separation: SeparationResult,
    pull_direction: Vec3,
    *,
    loop_face_ids: frozenset[int],
    cfg: object,
    tooling_split_face_ids: dict[int, float] | None = None,
) -> RegionClassification:
    """
    Assign H3's two regions to cavity and core, and classify every face.

    The cavity side is the component whose **area-weighted mean g is
    positive** — an aggregate, so a handful of oddly-oriented faces cannot
    flip a whole region.

    Labels:

    ``cavity`` / ``core``
        the face's region, with its multi-sample evidence attached.
    ``ambiguous``
        a face inside a zero-draft band (``|mean g| ≤ ε``) that does **not**
        touch ``Γ`` — its side is genuinely undetermined, and saying so is
        more useful than guessing.
    ``split``
        cannot occur at Level 0 (loops run along edges, so no face is cut) —
        UNLESS the face is a coaxial D-043 tooling split (2026-08-15,
        plan Phase 3A), which reuses this same label since it is likewise a
        single face genuinely belonging to both regions. ``tooling_split_face_ids``
        is optional and defaults to empty, matching every pre-existing call
        site — passing it changes ONLY the reported cavity/core area split
        for those specific faces (via real axial geometry, not the ``mean_g``
        fallback below, which is ~0 everywhere on a coaxial face by
        construction and so carries no side information for them); it never
        changes which faces land in which region, and never runs for a
        genuine Track-B split face.
    """
    faces_by_id = {f.face_id: f for f in part.faces}
    epsilon = cfg.silhouette_epsilon
    grid = cfg.face_sample_grid
    warnings: list[str] = []

    if len(separation.components) != 2:
        return RegionClassification(
            cavity_face_ids=frozenset(), core_face_ids=frozenset(),
            warnings=("H3 did not produce exactly two regions; no classification.",),
        )

    stats: dict[int, tuple[float, float, float, int]] = {}
    for face_id, face in faces_by_id.items():
        if face.normal_valid:
            stats[face_id] = _sample_face_g(face, pull_direction, grid)

    def region_mean(component: frozenset[int]) -> float:
        area = sum(faces_by_id[f].area for f in component if f in stats)
        if area <= 0:
            return 0.0
        return sum(faces_by_id[f].area * stats[f][0] for f in component if f in stats) / area

    first, second = separation.components
    cavity_component, core_component = (
        (first, second) if region_mean(first) >= region_mean(second) else (second, first)
    )

    classifications: list[FaceClassification] = []
    cavity_area = core_area = ambiguous_area = total_area = 0.0
    inconsistent: list[int] = []

    for face_id in sorted(faces_by_id):
        if face_id not in stats:
            continue
        face = faces_by_id[face_id]
        mean_g, min_g, max_g, count = stats[face_id]
        total_area += face.area

        in_cavity = face_id in cavity_component
        in_core = face_id in core_component
        if in_cavity and in_core:
            # The loop runs THROUGH this face, so it genuinely belongs to both
            # sides. Report BOTH sub-areas rather than forcing one label — this
            # is exactly the case v1's single UV-centroid normal gets wrong,
            # and it matters most on the large curved flanks where it happens.
            tooling_share = None
            if tooling_split_face_ids and face_id in tooling_split_face_ids:
                tooling_share = _tooling_split_cavity_share(
                    part, face_id, tooling_split_face_ids[face_id], pull_direction,
                    cavity_component, core_component, grid,
                )
            if tooling_share is not None:
                share = tooling_share
            else:
                # Genuine Track-B split face (or a tooling-split face whose
                # neighbours were all themselves ambiguous — falls back to
                # the previous behaviour rather than guessing further).
                positive = max(0.0, mean_g)
                negative = max(0.0, -mean_g)
                total = positive + negative
                share = positive / total if total > 0 else 0.5
            classification = FaceClassification(
                face_id=face_id, label="split",
                cavity_area_mm2=face.area * share,
                core_area_mm2=face.area * (1.0 - share),
                mean_g=mean_g, min_g=min_g, max_g=max_g, sample_count=count,
            )
            classifications.append(classification)
            cavity_area += classification.cavity_area_mm2
            core_area += classification.core_area_mm2
            continue
        if abs(mean_g) <= epsilon and face_id not in loop_face_ids:
            label = "ambiguous"
            ambiguous_area += face.area
            cavity_mm2 = core_mm2 = 0.0
        elif in_cavity:
            label, cavity_mm2, core_mm2 = "cavity", face.area, 0.0
            cavity_area += face.area
        else:
            label, cavity_mm2, core_mm2 = "core", 0.0, face.area
            core_area += face.area

        classification = FaceClassification(
            face_id=face_id, label=label,  # type: ignore[arg-type]
            cavity_area_mm2=cavity_mm2, core_area_mm2=core_mm2,
            mean_g=mean_g, min_g=min_g, max_g=max_g, sample_count=count,
        )
        classifications.append(classification)
        if classification.is_inconsistent:
            inconsistent.append(face_id)

    if inconsistent:
        warnings.append(
            f"{len(inconsistent)} face(s) carry a single cavity/core label but their "
            "sampled normals straddle the parting plane. At Level 0 this is expected "
            "wherever the true silhouette runs through a face interior — those faces "
            "need Track B (P2) to be split correctly."
        )

    return RegionClassification(
        cavity_face_ids=frozenset(cavity_component),
        core_face_ids=frozenset(core_component),
        faces=tuple(classifications),
        cavity_area_mm2=cavity_area,
        core_area_mm2=core_area,
        ambiguous_area_mm2=ambiguous_area,
        total_area_mm2=total_area,
        inconsistent_face_ids=tuple(inconsistent),
        warnings=tuple(warnings),
    )
