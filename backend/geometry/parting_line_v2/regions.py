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

from backend.geometry.parting_line_v2.types import FaceClassification
from backend.models.geometry_models import PartGeometry, Vec3, dot3

try:
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
    from OCC.Core.BRepTools import breptools
    from OCC.Core.GeomLProp import GeomLProp_SLProps

    from backend.geometry.step_loader import _face_normal_at_uv

    _OCC_AVAILABLE = True
except Exception:  # pragma: no cover
    _OCC_AVAILABLE = False


__all__ = ["SeparationResult", "separate_surface", "classify_regions", "mean_abs_g"]


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


def separate_surface(
    part: PartGeometry,
    loop_edge_ids: frozenset[int],
    *,
    split_face_ids: frozenset[int] = frozenset(),
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

    ==================  ==========================================
    ``count == 2``      PASS — the two components are cavity/core
    ``count == 1``      REJECT — the loop does not separate the part
    ``count > 2``       REJECT — the loop over-partitions
    ==================  ==========================================
    """
    usable = {f.face_id for f in part.faces if f.normal_valid}
    skipped = frozenset(f.face_id for f in part.faces if not f.normal_valid)
    faces_by_id = {f.face_id: f for f in part.faces}
    edges_by_id = {e.edge_id: e for e in part.edges}
    split = split_face_ids & usable

    def node_of(face_id: int, side: float | None) -> tuple[int, int]:
        """(face_id, side) where side is 0 for unsplit, +1/-1 for a split face."""
        if face_id not in split:
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
        if face_id in split:
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
                if b in split:
                    side_b = _g_at_edge_on_face(
                        faces_by_id[b].occ_face, edge.occ_edge, pull_direction,
                        free_parameter,
                    )
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

    def to_dict(self) -> dict:
        return {
            "cavity_face_count": len(self.cavity_face_ids),
            "core_face_count": len(self.core_face_ids),
            "cavity_area_mm2": round(self.cavity_area_mm2, 3),
            "core_area_mm2": round(self.core_area_mm2, 3),
            "ambiguous_area_mm2": round(self.ambiguous_area_mm2, 3),
            "total_area_mm2": round(self.total_area_mm2, 3),
            "ambiguous_area_fraction": round(self.ambiguous_area_fraction, 6),
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
        cannot occur at Level 0 (loops run along edges, so no face is cut).
        The label exists for P2, where Track B's curves do cut faces.
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
