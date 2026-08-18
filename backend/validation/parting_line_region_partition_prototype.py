"""
backend/validation/parting_line_region_partition_prototype.py
---------------------------------------------------------------
READ-ONLY EXPERIMENTAL PROTOTYPE (P3.12, 2026-08-13). Not production code:
not imported by backend.geometry.parting_line_v2, not wired into
analyse_parting_line, not part of the frozen Level 0-2 pipeline.

Purpose
-------
The architecture report (docs/DECISIONS_AND_ALGORITHMS.md, "the untested
representational ceiling" discussion) proposed a region-first / global
min-cut candidate PROPOSER as the smallest change capable of testing whether
Part3's failure is a candidate-representation ceiling (the existing
cycle-search's hard <=4-simultaneous-loop-union bound) rather than a
direction-feasibility problem. A follow-up review correctly flagged that the
report's "a min-cut boundary is a valid geometric candidate by construction"
framing was too strong: a min cut gives a PARTITION OF FACES, not a
B-Rep-supported, H0-H7-valid parting curve. Those are different claims.

This script tests the weaker, correct claim only. It:

  1. Builds a global s-t minimum-cut partition of the part's face-adjacency
     graph (nodes = whole faces; Track-B split-face nodes are OUT OF SCOPE
     for this prototype -- see "Scope limitation" below), under THREE
     deliberately different cost formulations (plus two extra weight
     variants of the third, to check whether any resulting boundary is
     robust across a range of weights or is an artifact of one specific
     choice).
  2. Converts ONLY the resulting cut's B-Rep edges into real, on-surface
     `CurveSegment`/`PartingLoopCandidate` objects (sampled directly from
     each edge's own OCC curve -- never fitted, never interpolated).
  3. Runs every candidate through the UNCHANGED, PRODUCTION
     `backend.geometry.parting_line_v2.gates.evaluate_gates` -- the exact
     same H0-H7 chain the real cycle-based pipeline uses. This script never
     decides validity itself; the optimizer's only job is to propose
     something worth testing.
  4. Logs exactly where each candidate passed or failed, per gate.

The question this answers
--------------------------
    Current cycle search:      NO VALID PL  (established, D-026..D-037)
    Region-partition search:   ???

If region-partition ALSO finds nothing that survives H0-H7 on directions
where the cycle search already fails, that is new evidence toward direction
infeasibility (or an H4-unsatisfiable Gauss map), not a representational
ceiling. If it finds something that DOES survive, unmodified, that is
evidence the cycle search's <=4-loop-union bound was the actual limiting
factor -- and it still needs manual geometric review before being trusted,
exactly like any new code path would.

Scope limitation (deliberate, stated up front, not discovered later)
----------------------------------------------------------------------
The min-cut graph's nodes are WHOLE faces. No face is split by a Track-B
interior curve here, so every candidate this script can propose runs along
existing B-Rep edges only, never through a face interior. This mirrors
regions.py's own documented Level-0 scope ("the cheap face-adjacency form of
H3 is exact when Γ runs only along B-Rep edges"). Extending this to
Track-B split-face nodes is natural future work if this face-only version
finds anything worth extending -- it is not attempted here.

Cost model
----------
Standard binary graph-cut / image-segmentation construction. Source S =
"cavity" label, sink T = "core" label.

    capacity(S, face)   = unary_weight * area(face) * max(0, +g(face))
    capacity(face, T)   = unary_weight * area(face) * max(0, -g(face))
    capacity(a, b)      = smoothness_weight * shared_edge_length(a, b)
                           * (silhouette_discount if any shared edge is
                              already Track-A-flagged silhouette else 1.0)

g(face) = face.signed_dot(pull_direction), the SAME visibility function
(g = n.d) the rest of parting_line_v2 uses throughout.

Three named objectives, per the review's explicit request to check whether
a Part3 answer (if any) is an artifact of one weighting or is robust across
a plausible range:

    A_orientation_dominant  -- pure per-face sign(g) baseline (smoothness=0).
                                This is INTENTIONALLY the naive per-face
                                model D-033 already showed fails as a
                                standalone separability diagnostic (too
                                fragmented) -- included as a negative
                                control, not a serious proposal.
    B_silhouette_dominant   -- cut cost dominated by following existing
                                Track-A silhouette geometry; unary weight
                                kept small (not zero -- a literal zero unary
                                weight makes the S-T cut degenerate, since
                                cutting nothing is then free) only to force a
                                genuine two-sided split to exist at all.
    C_balanced_{low,mid,high} -- meaningful weight on both terms, at three
                                smoothness/silhouette-discount ratios, per
                                the review: "if a broad range of reasonable
                                weights repeatedly converges on the same
                                geometric boundary, that's strong evidence."

No production code is modified. `detect_edge_silhouettes` (Track A) is
called read-only, purely so the cost model can know which edges are already
detected sign changes -- never to gate correctness. `evaluate_gates`,
`separate_surface`, `classify_regions`, `ranking.score_candidate` are called
completely unmodified as the sole arbiters of validity and quality.
"""

from __future__ import annotations

import itertools
import json
import math
import sys
import time
from dataclasses import replace
from pathlib import Path

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.config import settings  # noqa: E402
from backend.geometry.parting_line_v2 import measures, ranking  # noqa: E402
from backend.geometry.parting_line_v2.contracts import PullDirectionInput, UndercutInput  # noqa: E402
from backend.geometry.parting_line_v2.gates import evaluate_gates  # noqa: E402
from backend.geometry.parting_line_v2.regions import mean_abs_g  # noqa: E402
from backend.geometry.parting_line_v2.track_a import detect_edge_silhouettes  # noqa: E402
from backend.geometry.parting_line_v2.track_b import detect_face_silhouettes  # noqa: E402
from backend.geometry.parting_line_v2.types import CurveSegment, EdgeBacking, FaceBacking, PartingLoopCandidate  # noqa: E402
from backend.geometry.step_loader import load_step_cached  # noqa: E402

from OCC.Core.BRep import BRep_Tool  # noqa: E402
from OCC.Core.BRepAdaptor import BRepAdaptor_Curve  # noqa: E402

from shapely.geometry import LineString  # noqa: E402

from backend.validation.parting_line_face_partition import (  # noqa: E402
    _sample_edge_uv, build_face_regions, edge_subinterval_attachment, region_adjacency, region_stats,
)

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"

#: name -> (unary_weight, smoothness_weight, silhouette_discount)
OBJECTIVES: dict[str, tuple[float, float, float]] = {
    "A_orientation_dominant": (1.0, 0.0, 1.0),
    "B_silhouette_dominant": (0.05, 1.0, 0.05),
    "C_balanced_low": (1.0, 0.10, 0.10),
    "C_balanced_mid": (1.0, 0.30, 0.10),
    "C_balanced_high": (1.0, 1.00, 0.10),
}

#: diagnostic-only discovered_by tag -- NOT in PartingLoopCandidate's
#: production Literal (single_cycle/cycle_basis/johnson/beam/loop_union).
#: Python dataclasses do not enforce Literal at runtime, and nothing in
#: gates.py/ranking.py branches on this field, so this is safe here but must
#: never be written by production code.
DISCOVERED_BY_TAG = "region_partition_prototype"


def _bbox_diagonal(part) -> float:
    bbox = part.bounding_box
    if bbox is None:
        return 1.0
    return math.sqrt(
        (bbox.xmax - bbox.xmin) ** 2
        + (bbox.ymax - bbox.ymin) ** 2
        + (bbox.zmax - bbox.zmin) ** 2
    ) or 1.0


def _dist(a, b) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _weld_key(point, cell: float) -> tuple[int, int, int]:
    return (round(point[0] / cell), round(point[1] / cell), round(point[2] / cell))


# ---------------------------------------------------------------------------
# Step 1-3: build the min-cut, read off the cut edge set
# ---------------------------------------------------------------------------

def build_min_cut_partition(
    part, direction, silhouette_edge_ids: frozenset[int],
    *, unary_weight: float, smoothness_weight: float, silhouette_discount: float,
):
    """
    One global s-t minimum cut over the part's face-adjacency graph.

    Returns (cavity_face_ids, core_face_ids, cut_edge_ids, cut_value), or
    None if the part has fewer than 2 usable (normal_valid) faces.
    """
    usable_faces = [f for f in part.faces if f.normal_valid]
    if len(usable_faces) < 2:
        return None
    usable_ids = {f.face_id for f in usable_faces}

    graph = nx.DiGraph()
    graph.add_node("S")
    graph.add_node("T")
    for face in usable_faces:
        g = face.signed_dot(direction)
        cost_core = face.area * max(0.0, g)
        cost_cavity = face.area * max(0.0, -g)
        graph.add_edge("S", face.face_id, capacity=unary_weight * cost_core)
        graph.add_edge(face.face_id, "T", capacity=unary_weight * cost_cavity)

    edges_by_id = {e.edge_id: e for e in part.edges}
    pair_edges: dict[tuple[int, int], list[int]] = {}
    for edge_id, face_ids in part.edge_to_faces.items():
        if len(face_ids) != 2:
            continue
        a, b = sorted(face_ids)
        if a not in usable_ids or b not in usable_ids:
            continue
        pair_edges.setdefault((a, b), []).append(edge_id)

    for (a, b), edge_ids in pair_edges.items():
        total_length = sum(edges_by_id[e].length for e in edge_ids if e in edges_by_id)
        any_silhouette = any(e in silhouette_edge_ids for e in edge_ids)
        discount = silhouette_discount if any_silhouette else 1.0
        weight = smoothness_weight * total_length * discount
        if weight <= 0.0:
            continue
        graph.add_edge(a, b, capacity=weight)
        graph.add_edge(b, a, capacity=weight)

    cut_value, (reachable, non_reachable) = nx.minimum_cut(graph, "S", "T", capacity="capacity")
    cavity_face_ids = frozenset(n for n in reachable if isinstance(n, int))
    core_face_ids = frozenset(n for n in non_reachable if isinstance(n, int))

    cut_edge_ids: set[int] = set()
    for (a, b), edge_ids in pair_edges.items():
        if (a in cavity_face_ids) != (b in cavity_face_ids):
            cut_edge_ids.update(edge_ids)

    return cavity_face_ids, core_face_ids, frozenset(cut_edge_ids), cut_value


# ---------------------------------------------------------------------------
# Step 4: decompose the cut edge set into closed walks (Hierholzer, deterministic)
# ---------------------------------------------------------------------------

def _edge_endpoints(edge):
    """(start, end) 3-D points, or None for a closed/periodic edge (no dividing vertex)."""
    if edge.start_vertex is None or edge.end_vertex is None:
        return None
    return edge.start_vertex, edge.end_vertex


def decompose_into_loops(part, cut_edge_ids: frozenset[int], *, weld_cell_mm: float):
    """
    Deterministic decomposition of the cut edge set into closed walks.

    A 2-coloring boundary on a closed 2-manifold has EVEN degree at every
    vertex it touches -- walking around any vertex, the face-label sequence
    must flip an even number of times. This is a real topological guarantee,
    not an assumption, so Hierholzer's algorithm (which always succeeds on a
    connected, all-even-degree multigraph) should always find a closed walk
    per connected component. If a component turns out to have an odd-degree
    vertex anyway (a numerical welding glitch, or genuinely non-manifold
    input), that component is SKIPPED with a note -- never forced closed.

    Each connected component becomes ONE closed walk (member curve of Γ);
    a component that revisits a vertex is left as-is for H1/H2 to accept or
    reject on their own terms, rather than this function guessing the "most
    natural" simple-loop split at a branch point.
    """
    edges_by_id = {e.edge_id: e for e in part.edges}
    standalone: list[list[int]] = []
    adjacency: dict[tuple, list[tuple[int, tuple]]] = {}

    for edge_id in sorted(cut_edge_ids):
        edge = edges_by_id.get(edge_id)
        if edge is None:
            continue
        endpoints = _edge_endpoints(edge)
        if endpoints is None:
            standalone.append([edge_id])
            continue
        p0, p1 = endpoints
        k0, k1 = _weld_key(p0, weld_cell_mm), _weld_key(p1, weld_cell_mm)
        adjacency.setdefault(k0, []).append((edge_id, k1))
        adjacency.setdefault(k1, []).append((edge_id, k0))

    seen_vertices: set = set()
    components: list[set] = []
    for v in adjacency:
        if v in seen_vertices:
            continue
        stack, comp = [v], set()
        seen_vertices.add(v)
        while stack:
            cur = stack.pop()
            comp.add(cur)
            for _eid, nb in adjacency[cur]:
                if nb not in seen_vertices:
                    seen_vertices.add(nb)
                    stack.append(nb)
        components.append(comp)

    notes: list[str] = []
    loops: list[list[int]] = []
    for comp in components:
        degrees = {v: len(adjacency[v]) for v in comp}
        if any(d % 2 != 0 for d in degrees.values()):
            notes.append(
                f"component with {len(comp)} vertices has an odd-degree vertex -- "
                "cannot decompose into a closed curve; skipped, not forced."
            )
            continue
        comp_edge_ids = {eid for v in comp for eid, _ in adjacency[v]}
        remaining = {v: sorted(adjacency[v], key=lambda t: t[0]) for v in comp}
        used: set[int] = set()
        start = min(comp)
        stack: list[tuple] = [(start, None)]
        edge_circuit: list[int] = []
        while stack:
            v, via = stack[-1]
            nxt = next(((eid, nb) for eid, nb in remaining.get(v, []) if eid not in used), None)
            if nxt is None:
                stack.pop()
                if via is not None:
                    edge_circuit.append(via)
            else:
                eid, nb = nxt
                used.add(eid)
                stack.append((nb, eid))
        edge_circuit.reverse()
        if len(used) != len(comp_edge_ids):
            notes.append(
                f"component: only {len(used)}/{len(comp_edge_ids)} edges consumed by the "
                "Hierholzer walk (unexpected -- reported, not hidden)."
            )
        if edge_circuit:
            loops.append(edge_circuit)

    return standalone + loops, notes


# ---------------------------------------------------------------------------
# Step 5: assemble a real, on-surface PartingLoopCandidate
# ---------------------------------------------------------------------------

_seg_id_counter = itertools.count(900_000)


def _sample_edge_points(edge, first: float, last: float, n: int = 9) -> list[tuple]:
    curve = BRepAdaptor_Curve(edge.occ_edge)
    points = []
    for i in range(n):
        t = first + (last - first) * i / (n - 1)
        p = curve.Value(t)
        points.append((p.X(), p.Y(), p.Z()))
    return points


def _resolve_walk_directions(part, walk: list[int], weld_cell_mm: float) -> list[tuple[int, bool]]:
    """
    ``[(edge_id, sample_ascending)]`` for a cyclic walk, derived from which
    vertex each CONSECUTIVE pair of edges actually shares.

    Deliberately not "start from an arbitrary anchor point and chase the
    nearest next point" -- Hierholzer's algorithm does not preserve which
    physical endpoint of the first edge begins the cycle, so anchoring on
    ``edge.start_vertex`` there is arbitrary and can silently pick the wrong
    direction for that one edge, which is exactly the kind of off-by-one
    that makes a genuinely closed topological walk fail H1's numeric
    closure check. Matching consecutive edges' SHARED weld-key vertex has no
    such ambiguity: it is well-defined from the topology alone, independent
    of where the walk happens to start.
    """
    edges_by_id = {e.edge_id: e for e in part.edges}
    if len(walk) == 1:
        return [(walk[0], True)]

    endpoints: dict[int, tuple | None] = {}
    for edge_id in walk:
        edge = edges_by_id[edge_id]
        raw = _edge_endpoints(edge)
        endpoints[edge_id] = (
            (_weld_key(raw[0], weld_cell_mm), _weld_key(raw[1], weld_cell_mm))
            if raw is not None else None
        )

    n = len(walk)
    junction_after: list[tuple | None] = []
    for i in range(n):
        cur_ep, nxt_ep = endpoints[walk[i]], endpoints[walk[(i + 1) % n]]
        shared = None
        if cur_ep is not None and nxt_ep is not None:
            for candidate in cur_ep:
                if candidate in nxt_ep:
                    shared = candidate
                    break
        junction_after.append(shared)

    resolved: list[tuple[int, bool]] = []
    for i, edge_id in enumerate(walk):
        ep = endpoints[edge_id]
        to_vertex = junction_after[i]
        if ep is None or to_vertex is None:
            resolved.append((edge_id, True))
        elif ep[1] == to_vertex:
            resolved.append((edge_id, True))   # ascending sample already ends at the junction
        elif ep[0] == to_vertex:
            resolved.append((edge_id, False))  # reverse so it ends at the junction
        else:
            resolved.append((edge_id, True))   # unexpected; fall back rather than crash
    return resolved


def assemble_candidate(part, loop_edge_walks: list[list[int]], candidate_id: int, *, weld_cell_mm: float):
    """Build a real PartingLoopCandidate whose every point is C(t) off the actual OCC edge curve."""
    edges_by_id = {e.edge_id: e for e in part.edges}
    all_segments: list[CurveSegment] = []
    loops_points: list[tuple] = []

    for walk in loop_edge_walks:
        if not walk:
            continue
        loop_pts: list[tuple] = []
        for edge_id, ascending in _resolve_walk_directions(part, walk, weld_cell_mm):
            edge = edges_by_id.get(edge_id)
            if edge is None:
                continue
            first_p, last_p = BRep_Tool.Range(edge.occ_edge)
            points = _sample_edge_points(edge, first_p, last_p, n=9)
            if not ascending:
                points = list(reversed(points))
            if loop_pts and _dist(loop_pts[-1], points[0]) < 1e-6:
                points = points[1:]
            if len(points) < 2:
                continue
            loop_pts.extend(points)

            segment = CurveSegment(
                segment_id=next(_seg_id_counter),
                points=tuple(points),
                backing=EdgeBacking(edge_id=edge_id, t_start=first_p, t_end=last_p),
                kind="silhouette",
            )
            all_segments.append(segment)

        if len(loop_pts) >= 2:
            loops_points.append(tuple(loop_pts))

    if not loops_points or not all_segments:
        return None

    total_points = tuple(p for loop in loops_points for p in loop)
    return PartingLoopCandidate(
        candidate_id=candidate_id,
        segments=tuple(all_segments),
        points=total_points,
        is_closed=True,
        discovered_by=DISCOVERED_BY_TAG,  # type: ignore[arg-type]
        loops=tuple(loops_points),
    )


# ---------------------------------------------------------------------------
# Step 6-7: run every objective through the unchanged production gates
# ---------------------------------------------------------------------------

def run_experiment(part, direction_tuple, part_label: str, direction_label: str, cfg, undercuts):
    bbox_diag = _bbox_diagonal(part)
    direction = PullDirectionInput(direction_tuple, "manual").direction

    track_a = detect_edge_silhouettes(part, direction, cfg=cfg, bbox_diagonal_mm=bbox_diag)
    silhouette_edge_ids = frozenset(
        s.backing.edge_id for s in track_a.segments
        if s.kind == "silhouette" and isinstance(s.backing, EdgeBacking)
    )

    valid_faces = [f for f in part.faces if f.normal_valid]
    part_projected_area = measures.cauchy_projected_area(
        [f.area for f in valid_faces],
        [mean_abs_g(f, direction, cfg.face_sample_grid) for f in valid_faces],
    )
    weld_cell = max(cfg.weld_tolerance_rel * bbox_diag, 1e-7) * 5.0

    results = []
    for obj_name, (unary_w, smooth_w, discount) in OBJECTIVES.items():
        t0 = time.time()
        cut = build_min_cut_partition(
            part, direction, silhouette_edge_ids,
            unary_weight=unary_w, smoothness_weight=smooth_w, silhouette_discount=discount,
        )
        if cut is None:
            results.append({"objective": obj_name, "error": "insufficient usable faces"})
            continue
        cavity_ids, core_ids, cut_edge_ids, cut_value = cut
        if not cut_edge_ids:
            results.append({
                "objective": obj_name, "degenerate_cut": True,
                "cavity_face_count": len(cavity_ids), "core_face_count": len(core_ids),
                "cut_value": cut_value,
            })
            continue

        walks, decomp_notes = decompose_into_loops(part, cut_edge_ids, weld_cell_mm=weld_cell)
        candidate = assemble_candidate(
            part, walks, candidate_id=900000 + hash(obj_name) % 1000, weld_cell_mm=weld_cell
        )
        elapsed_s = round(time.time() - t0, 3)
        if candidate is None:
            results.append({
                "objective": obj_name, "error": "could not assemble any closed loop",
                "decomposition_notes": decomp_notes, "cut_edge_count": len(cut_edge_ids),
            })
            continue

        outcome = evaluate_gates(
            candidate, part, direction,
            undercuts=undercuts, cfg=cfg,
            bbox_diagonal_mm=bbox_diag, part_projected_area_mm2=part_projected_area,
        )
        candidate = replace(candidate, feasibility=outcome.report)
        score_dict = None
        if outcome.report.passed and outcome.regions is not None:
            score = ranking.score_candidate(
                candidate, direction, undercuts=undercuts,
                bbox_diagonal_mm=bbox_diag, part_projected_area_mm2=part_projected_area,
                ambiguous_area_fraction=outcome.regions.ambiguous_area_fraction,
            )
            score_dict = score.to_dict()

        results.append({
            "objective": obj_name,
            "weights": {"unary": unary_w, "smoothness": smooth_w, "silhouette_discount": discount},
            "cut_value": cut_value,
            "cavity_face_count": len(cavity_ids),
            "core_face_count": len(core_ids),
            "cut_edge_count": len(cut_edge_ids),
            "loop_count": len(walks),
            "decomposition_notes": decomp_notes,
            "elapsed_s": elapsed_s,
            "candidate_segment_count": len(candidate.segments),
            "candidate_point_count": len(candidate.points),
            "feasibility": outcome.report.to_dict(),
            "score": score_dict,
        })

    return {
        "part": part_label,
        "direction_label": direction_label,
        "direction": list(direction),
        "silhouette_edge_count": len(silhouette_edge_ids),
        "usable_face_count": len(valid_faces),
        "part_projected_area_mm2": part_projected_area,
        "bbox_diagonal_mm": bbox_diag,
        "results": results,
    }



# ===========================================================================
# EXPERIMENT 1 (P3.13, 2026-08-13): Track-B split-face nodes
# ===========================================================================
#
# Everything above this line is D-038's original face-only prototype, left
# UNCHANGED so Phase 2 below can do an exact apples-to-apples OLD-vs-NEW
# comparison by calling both `run_experiment` (OLD) and `run_experiment_split`
# (NEW) on the identical direction/geometry/cost sweep.
#
# What's new: faces carrying a genuine Track-B interior silhouette curve get
# TWO min-cut nodes, (face_id, +1) and (face_id, -1), instead of one -- so the
# min-cut can propose a boundary that runs through a face interior, not just
# along existing B-Rep edges. Per ground rule 8, face-ATTACHMENT (which side
# of a split face a neighbouring edge connects to) reuses
# `regions.py._g_at_edge_on_face` directly -- the exact same evaluator H3
# itself uses -- rather than a fresh reimplementation, so construction and
# validation agree on this specific geometric question by construction, not
# by coincidence.
#
# No edge is added between a face's own (+1)/(-1) nodes: they are already
# divided by the face's real, already-computed Track-B curve, and that curve
# IS the cut geometry used if the min-cut ever separates them -- modelling an
# extra internal smoothness cost there would double-penalise geometry the
# search should be free to use for nothing.

from backend.geometry.parting_line_v2.regions import _g_at_edge_on_face  # noqa: E402


def _face_split_stats(face, direction, grid: int = 7):
    """
    Area-weighted split of a face's ``g`` into its ``{g>=0}`` and ``{g<0}``
    parts: ``(positive_area_mm2, negative_area_mm2, mean_g_positive,
    mean_g_negative)``.

    Written fresh (M x M UV sampling, area-weighted by the surface Jacobian)
    rather than importing `regions.py`'s private `_sample_face_g`, to keep
    this script's reuse of production internals limited to the one function
    (`_g_at_edge_on_face`) genuinely needed for consistency with H3's own
    face-attachment decision -- but it is the SAME area-weighted philosophy
    `regions.py.mean_abs_g` already uses and was validated against (D-011:
    a single centroid sample has no bounding property; uniform-(u,v)
    sampling overestimates a sphere's true area-weighted average by 27%).
    """
    from OCC.Core.BRepTools import breptools
    from OCC.Core.GeomLProp import GeomLProp_SLProps

    from backend.geometry.step_loader import _face_normal_at_uv
    from backend.models.geometry_models import dot3

    def _fallback():
        g = face.signed_dot(direction)
        return (face.area, 0.0, g, 0.0) if g >= 0.0 else (0.0, face.area, 0.0, g)

    try:
        surface = BRep_Tool.Surface(face.occ_face)
        u_min, u_max, v_min, v_max = breptools.UVBounds(face.occ_face)
    except Exception:
        return _fallback()
    if not all(math.isfinite(x) for x in (u_min, u_max, v_min, v_max)):
        return _fallback()

    pos_w = neg_w = pos_g_sum = neg_g_sum = 0.0
    for i in range(grid):
        for j in range(grid):
            u = u_min + (u_max - u_min) * (i + 0.5) / grid
            v = v_min + (v_max - v_min) * (j + 0.5) / grid
            normal = _face_normal_at_uv(face.occ_face, u, v)
            if normal is None:
                continue
            g = dot3(normal, direction)
            try:
                props = GeomLProp_SLProps(surface, u, v, 1, 1e-9)
                du, dv = props.D1U(), props.D1V()
                jac = math.sqrt(
                    (du.Y() * dv.Z() - du.Z() * dv.Y()) ** 2
                    + (du.Z() * dv.X() - du.X() * dv.Z()) ** 2
                    + (du.X() * dv.Y() - du.Y() * dv.X()) ** 2
                )
            except Exception:
                jac = 1.0
            if jac <= 0.0:
                continue
            if g >= 0.0:
                pos_w += jac
                pos_g_sum += g * jac
            else:
                neg_w += jac
                neg_g_sum += g * jac

    total = pos_w + neg_w
    if total <= 0.0:
        return _fallback()
    positive_area = face.area * (pos_w / total)
    negative_area = face.area * (neg_w / total)
    mean_g_pos = (pos_g_sum / pos_w) if pos_w > 0 else 0.0
    mean_g_neg = (neg_g_sum / neg_w) if neg_w > 0 else 0.0
    return positive_area, negative_area, mean_g_pos, mean_g_neg


def build_min_cut_partition_split(
    part, direction, track_b_segments, silhouette_edge_ids,
    *, unary_weight: float, smoothness_weight: float, silhouette_discount: float,
    max_curves_per_split_face: int | None = None,
):
    """
    Same s-t min cut as `build_min_cut_partition`, plus Track-B split-face
    nodes.

    ``max_curves_per_split_face`` (P3.14 / "Option 2", 2026-08-13): the
    binary ``(face,+1)/(face,-1)`` split is only topologically valid for a
    face with a SINGLE interior curve dividing it into exactly two sides
    (D-014's own stated scope: "a single monotone crossing"). Forcing a face
    with 2+ disjoint interior curves into a binary split produces attachment
    assignments matching no real continuous curve, which is what caused the
    pervasive odd-degree fragmentation observed at P3.13's unrestricted
    attempt (measured on Part3 az15: 45% of split faces have >1 curve; 19 of
    26 cut-piece components came back odd-degree). Set to ``1`` to represent
    ONLY faces with exactly one curve as split (proven-correct binary
    semantics); every face with more curves is treated as a single whole,
    unsplit node -- i.e. reverts to D-038 behaviour for exactly that subset
    of faces. ``None`` (default) keeps P3.13's unrestricted-but-invalid
    behaviour, kept only so existing callers are unaffected.
    """
    usable_faces = [f for f in part.faces if f.normal_valid]
    if len(usable_faces) < 2:
        return None
    usable_ids = {f.face_id for f in usable_faces}
    faces_by_id = {f.face_id: f for f in usable_faces}

    track_b_by_face: dict[int, list] = {}
    for seg in track_b_segments:
        if isinstance(seg.backing, FaceBacking):
            track_b_by_face.setdefault(seg.backing.face_id, []).append(seg)

    all_split_candidate_ids = {fid for fid in track_b_by_face if fid in usable_ids}
    if max_curves_per_split_face is None:
        split_face_ids = set(all_split_candidate_ids)
    else:
        split_face_ids = {
            fid for fid in all_split_candidate_ids
            if len(track_b_by_face[fid]) <= max_curves_per_split_face
        }

    graph = nx.DiGraph()
    graph.add_node("S")
    graph.add_node("T")

    for fid in split_face_ids:
        pos_area, neg_area, mean_pos, mean_neg = _face_split_stats(faces_by_id[fid], direction)
        graph.add_edge("S", (fid, 1), capacity=unary_weight * pos_area * max(0.0, mean_pos))
        graph.add_edge((fid, 1), "T", capacity=0.0)
        graph.add_edge("S", (fid, -1), capacity=0.0)
        graph.add_edge((fid, -1), "T", capacity=unary_weight * neg_area * max(0.0, -mean_neg))

    for face in usable_faces:
        if face.face_id in split_face_ids:
            continue
        g = face.signed_dot(direction)
        graph.add_edge("S", face.face_id, capacity=unary_weight * face.area * max(0.0, g))
        graph.add_edge(face.face_id, "T", capacity=unary_weight * face.area * max(0.0, -g))

    def node_of(fid, side_g):
        if fid not in split_face_ids:
            return fid
        return (fid, 1) if (side_g is None or side_g >= 0.0) else (fid, -1)

    edges_by_id = {e.edge_id: e for e in part.edges}
    pair_edges: dict[tuple[int, int], list[int]] = {}
    for edge_id, face_ids in part.edge_to_faces.items():
        if len(face_ids) != 2:
            continue
        a, b = sorted(face_ids)
        if a not in usable_ids or b not in usable_ids:
            continue
        pair_edges.setdefault((a, b), []).append(edge_id)

    # Per-EDGE attachment (not per face-pair): if `a` and `b` share more than
    # one boundary edge and `a` is split, different edges can legitimately
    # attach to different sides of `a` -- aggregating by whole face-pair
    # first would silently pick one edge's attachment for all of them.
    #
    # Attachment (`edge_attachment`) is computed for EVERY face-adjacent edge
    # unconditionally, independent of its smoothness capacity: at
    # smoothness_weight=0 (Objective A) no capacity edge is added to the
    # min-cut graph at all, but the resulting cavity/core LABELS are still
    # real per-face optimisation results, and any edge whose two sides ended
    # up with different labels is still a genuine cut -- extraction must not
    # silently skip it just because it never contributed a smoothing cost.
    edge_attachment: dict[int, tuple] = {}
    edge_capacity: dict[tuple, float] = {}
    for (a, b), edge_ids in pair_edges.items():
        for edge_id in edge_ids:
            edge = edges_by_id.get(edge_id)
            if edge is None:
                continue
            side_a = (
                _g_at_edge_on_face(faces_by_id[a].occ_face, edge.occ_edge, direction)
                if a in split_face_ids else None
            )
            side_b = (
                _g_at_edge_on_face(faces_by_id[b].occ_face, edge.occ_edge, direction)
                if b in split_face_ids else None
            )
            na, nb = node_of(a, side_a), node_of(b, side_b)
            key = tuple(sorted((na, nb), key=str))
            edge_attachment[edge_id] = key

            discount = silhouette_discount if edge_id in silhouette_edge_ids else 1.0
            weight = smoothness_weight * edge.length * discount
            if weight <= 0.0:
                continue
            edge_capacity[key] = edge_capacity.get(key, 0.0) + weight

    for (na, nb), cap in edge_capacity.items():
        graph.add_edge(na, nb, capacity=cap)
        graph.add_edge(nb, na, capacity=cap)

    cut_value, (reachable, non_reachable) = nx.minimum_cut(graph, "S", "T", capacity="capacity")
    cavity_nodes = frozenset(n for n in reachable if n not in ("S", "T"))
    core_nodes = frozenset(n for n in non_reachable if n not in ("S", "T"))

    cut_pieces: list[dict] = []
    for edge_id, (na, nb) in edge_attachment.items():
        if (na in cavity_nodes) != (nb in cavity_nodes):
            cut_pieces.append({"kind": "edge", "edge_id": edge_id})
    split_face_cut_count = 0
    for fid in split_face_ids:
        pos_side = (fid, 1) in cavity_nodes
        neg_side = (fid, -1) in cavity_nodes
        if pos_side != neg_side:
            split_face_cut_count += 1
            for seg in track_b_by_face[fid]:
                cut_pieces.append({"kind": "face", "face_id": fid, "segment": seg})

    cavity_face_ids = frozenset(n if isinstance(n, int) else n[0] for n in cavity_nodes)
    core_face_ids = frozenset(n if isinstance(n, int) else n[0] for n in core_nodes)

    curve_count_histogram: dict[int, int] = {}
    for fid in all_split_candidate_ids:
        n = len(track_b_by_face[fid])
        curve_count_histogram[n] = curve_count_histogram.get(n, 0) + 1

    return {
        "cavity_face_ids": cavity_face_ids, "core_face_ids": core_face_ids,
        "cut_pieces": cut_pieces, "cut_value": cut_value,
        "split_face_ids": split_face_ids,
        "split_face_cut_count": split_face_cut_count,
        "node_count_before": len(usable_faces),
        "node_count_after": len(usable_faces) + len(split_face_ids),
        "total_track_b_faces": len(all_split_candidate_ids),
        "represented_split_face_count": len(split_face_ids),
        "unsplit_track_b_face_count": len(all_split_candidate_ids) - len(split_face_ids),
        "curve_count_histogram": curve_count_histogram,
    }


def build_min_cut_partition_nway(
    part, direction, track_b_segments, silhouette_edge_ids,
    *, unary_weight: float, smoothness_weight: float, silhouette_discount: float,
):
    """
    N-way generalisation of the min-cut partition (Option 1, P3.15).

    Every usable face is partitioned into its ACTUAL connected regions via
    `build_face_regions` (shapely polygonize on the face's own boundary
    edges + Track-B's own interior curves) -- a face with 0 or 1 Track-B
    curves comes back as 1 or 2 regions, matching P3.13's binary model
    exactly for those cases; a face with N>1 disjoint curves comes back with
    its real region count and adjacency, fixing the exact defect (D-039)
    that made the binary model topologically invalid for 45% of Part3's
    split faces.
    """
    usable_faces = [f for f in part.faces if f.normal_valid]
    if len(usable_faces) < 2:
        return None
    usable_ids = {f.face_id for f in usable_faces}
    faces_by_id = {f.face_id: f for f in usable_faces}

    track_b_by_face: dict[int, list] = {}
    for seg in track_b_segments:
        if isinstance(seg.backing, FaceBacking):
            track_b_by_face.setdefault(seg.backing.face_id, []).append(seg)

    face_regions: dict[int, list] = {}
    face_region_adjacency: dict[int, dict] = {}
    for face in usable_faces:
        segs = track_b_by_face.get(face.face_id, [])
        regions = build_face_regions(part, face, segs)
        face_regions[face.face_id] = regions if regions else None
        if regions:
            face_region_adjacency[face.face_id] = region_adjacency(regions)

    graph = nx.DiGraph()
    graph.add_node("S")
    graph.add_node("T")

    for face in usable_faces:
        regions = face_regions[face.face_id]
        if not regions:
            # Degenerate/failed partition (e.g. unsampleable boundary) --
            # fall back to a single whole-face node rather than silently
            # dropping the face from the graph.
            g = face.signed_dot(direction)
            node = (face.face_id, 0)
            graph.add_edge("S", node, capacity=unary_weight * face.area * max(0.0, g))
            graph.add_edge(node, "T", capacity=unary_weight * face.area * max(0.0, -g))
            continue
        for region in regions:
            area_mm2, mean_g = region_stats(face, region, direction)
            node = (face.face_id, region.region_id)
            graph.add_edge("S", node, capacity=unary_weight * area_mm2 * max(0.0, mean_g))
            graph.add_edge(node, "T", capacity=unary_weight * area_mm2 * max(0.0, -mean_g))
        # No edge between same-face adjacent regions: already divided by
        # real, already-detected Track-B geometry -- free to cut, matching
        # the binary model's same reasoning.

    edges_by_id = {e.edge_id: e for e in part.edges}
    pair_edges: dict[tuple[int, int], list[int]] = {}
    for edge_id, face_ids in part.edge_to_faces.items():
        if len(face_ids) != 2:
            continue
        a, b = sorted(face_ids)
        if a not in usable_ids or b not in usable_ids:
            continue
        pair_edges.setdefault((a, b), []).append(edge_id)

    def region_for_edge_midpoint(face, edge, regions):
        if not regions:
            return 0
        line = _sample_edge_uv(face.occ_face, edge)
        if line is None or line.length == 0:
            return regions[0].region_id
        mid = line.interpolate(0.5, normalized=True)
        for region in regions:
            if region.polygon.covers(mid):
                return region.region_id
        # Midpoint landed exactly on a shared boundary (numerically
        # ambiguous, not a modelling error) -- nearest region wins.
        best = min(regions, key=lambda r: r.polygon.distance(mid))
        return best.region_id

    edge_attachment: dict[int, tuple] = {}
    edge_capacity: dict[tuple, float] = {}
    for (a, b), edge_ids in pair_edges.items():
        for edge_id in edge_ids:
            edge = edges_by_id.get(edge_id)
            if edge is None:
                continue
            ra = region_for_edge_midpoint(faces_by_id[a], edge, face_regions[a])
            rb = region_for_edge_midpoint(faces_by_id[b], edge, face_regions[b])
            na, nb = (a, ra), (b, rb)
            key = tuple(sorted((na, nb), key=str))
            edge_attachment[edge_id] = key

            discount = silhouette_discount if edge_id in silhouette_edge_ids else 1.0
            weight = smoothness_weight * edge.length * discount
            if weight <= 0.0:
                continue
            edge_capacity[key] = edge_capacity.get(key, 0.0) + weight

    for (na, nb), cap in edge_capacity.items():
        graph.add_edge(na, nb, capacity=cap)
        graph.add_edge(nb, na, capacity=cap)

    cut_value, (reachable, non_reachable) = nx.minimum_cut(graph, "S", "T", capacity="capacity")
    cavity_nodes = frozenset(n for n in reachable if n not in ("S", "T"))
    core_nodes = frozenset(n for n in non_reachable if n not in ("S", "T"))

    cut_pieces: list[dict] = []
    for edge_id, (na, nb) in edge_attachment.items():
        if (na in cavity_nodes) != (nb in cavity_nodes):
            cut_pieces.append({"kind": "edge", "edge_id": edge_id})

    split_face_cut_count = 0
    for face_id, regions in face_regions.items():
        if not regions or len(regions) < 2:
            continue
        adjacency = face_region_adjacency[face_id]
        segs = track_b_by_face.get(face_id, [])
        checked_pairs: set[tuple] = set()
        for ra in adjacency:
            for rb in adjacency[ra]:
                pair_key = tuple(sorted((ra, rb)))
                if pair_key in checked_pairs:
                    continue
                checked_pairs.add(pair_key)
                node_a, node_b = (face_id, ra), (face_id, rb)
                if (node_a in cavity_nodes) == (node_b in cavity_nodes):
                    continue
                region_a = next(r for r in regions if r.region_id == ra)
                region_b = next(r for r in regions if r.region_id == rb)
                for seg in segs:
                    if len(seg.backing.uv) < 2:
                        continue
                    line = LineString(seg.backing.uv)
                    touches_a = region_a.polygon.boundary.intersection(line).length > 0
                    touches_b = region_b.polygon.boundary.intersection(line).length > 0
                    if touches_a and touches_b:
                        cut_pieces.append({"kind": "face", "face_id": face_id, "segment": seg})
                        split_face_cut_count += 1

    cavity_face_ids = frozenset(n[0] for n in cavity_nodes)
    core_face_ids = frozenset(n[0] for n in core_nodes)

    region_count_histogram: dict[int, int] = {}
    for regions in face_regions.values():
        n = len(regions) if regions else 1
        region_count_histogram[n] = region_count_histogram.get(n, 0) + 1

    return {
        "cavity_face_ids": cavity_face_ids, "core_face_ids": core_face_ids,
        "cut_pieces": cut_pieces, "cut_value": cut_value,
        "split_face_cut_count": split_face_cut_count,
        "node_count_before": len(usable_faces),
        "node_count_after": sum(len(r) if r else 1 for r in face_regions.values()),
        "region_count_histogram": region_count_histogram,
        "total_track_b_faces": len(track_b_by_face),
    }


def build_min_cut_partition_nway_subedge(
    part, direction, track_b_segments, silhouette_edge_ids,
    *, unary_weight: float, smoothness_weight: float, silhouette_discount: float,
    side_core_face_ids: frozenset[int] = frozenset(),
):
    """
    Sub-edge-aware counterpart of `build_min_cut_partition_nway` (P3.16,
    "Task 3"). IDENTICAL face-region construction and unary costs; the ONLY
    difference is cross-face attachment: instead of one representative
    midpoint sample per shared B-Rep edge (`region_for_edge_midpoint`,
    exact only when the edge borders a single region per side -- D-014's
    limitation recurring at the edge level), every shared edge is split at
    every parameter where either adjacent face's region boundary actually
    crosses it (`edge_subinterval_attachment`, exact shapely intersection,
    proven against real OCC geometry by Fixtures I/J), and each resulting
    sub-interval gets its own independent attachment and smoothness cost.

    ``side_core_face_ids`` (P3.19, "Formulation B" diagnostic, 2026-08-14):
    faces independently justified (via `detect_undercuts`, not guessed) as
    belonging to a separate mould movement get ZERO unary cost -- they are
    still full graph nodes, still subject to H3's topological requirement
    that the WHOLE part separates into exactly two regions, and still
    contribute their own cross-face smoothness edges unchanged. The only
    thing removed is the requirement that THEIR OWN orientation be
    consistent with whichever side they land on -- i.e. they no longer need
    to be resolved by the *primary* two-way split. This is not deleting
    geometry (H3 still sees every face) and not lowering H4's threshold
    (H4's 2% limit is untouched); it tests whether the PRIMARY split is
    representable once a specific, evidenced side-action feature is no
    longer required to resolve through the main pull direction alone.
    """
    usable_faces = [f for f in part.faces if f.normal_valid]
    if len(usable_faces) < 2:
        return None
    usable_ids = {f.face_id for f in usable_faces}
    faces_by_id = {f.face_id: f for f in usable_faces}

    track_b_by_face: dict[int, list] = {}
    for seg in track_b_segments:
        if isinstance(seg.backing, FaceBacking):
            track_b_by_face.setdefault(seg.backing.face_id, []).append(seg)

    face_regions: dict[int, list] = {}
    face_region_adjacency: dict[int, dict] = {}
    for face in usable_faces:
        segs = track_b_by_face.get(face.face_id, [])
        regions = build_face_regions(part, face, segs)
        face_regions[face.face_id] = regions if regions else None
        if regions:
            face_region_adjacency[face.face_id] = region_adjacency(regions)

    graph = nx.DiGraph()
    graph.add_node("S")
    graph.add_node("T")

    for face in usable_faces:
        face_unary_weight = 0.0 if face.face_id in side_core_face_ids else unary_weight
        regions = face_regions[face.face_id]
        if not regions:
            g = face.signed_dot(direction)
            node = (face.face_id, 0)
            graph.add_edge("S", node, capacity=face_unary_weight * face.area * max(0.0, g))
            graph.add_edge(node, "T", capacity=face_unary_weight * face.area * max(0.0, -g))
            continue
        for region in regions:
            area_mm2, mean_g = region_stats(face, region, direction)
            node = (face.face_id, region.region_id)
            graph.add_edge("S", node, capacity=face_unary_weight * area_mm2 * max(0.0, mean_g))
            graph.add_edge(node, "T", capacity=face_unary_weight * area_mm2 * max(0.0, -mean_g))

    edges_by_id = {e.edge_id: e for e in part.edges}
    pair_edges: dict[tuple[int, int], list[int]] = {}
    for edge_id, face_ids in part.edge_to_faces.items():
        if len(face_ids) != 2:
            continue
        a, b = sorted(face_ids)
        if a not in usable_ids or b not in usable_ids:
            continue
        pair_edges.setdefault((a, b), []).append(edge_id)

    # sub_pieces[edge_id] = list of (t_start, t_end, na, nb) -- every
    # sub-interval of every shared edge, kept separately (not merged into
    # one edge_attachment entry) so each can be independently cut.
    sub_pieces: dict[int, list[tuple]] = {}
    edge_capacity: dict[tuple, float] = {}
    for (a, b), edge_ids in pair_edges.items():
        for edge_id in edge_ids:
            edge = edges_by_id.get(edge_id)
            if edge is None:
                continue
            intervals = edge_subinterval_attachment(
                faces_by_id[a], faces_by_id[b], edge, face_regions[a], face_regions[b]
            )
            if not intervals:
                continue
            discount = silhouette_discount if edge_id in silhouette_edge_ids else 1.0
            for iv in intervals:
                na, nb = (a, iv.region_a), (b, iv.region_b)
                key = tuple(sorted((na, nb), key=str))
                sub_pieces.setdefault(edge_id, []).append((iv.t_start, iv.t_end, na, nb))

                span_fraction = abs(iv.t_end - iv.t_start) / max(
                    abs(BRep_Tool.Range(edge.occ_edge)[1] - BRep_Tool.Range(edge.occ_edge)[0]), 1e-12
                )
                weight = smoothness_weight * edge.length * span_fraction * discount
                if weight <= 0.0:
                    continue
                edge_capacity[key] = edge_capacity.get(key, 0.0) + weight

    for (na, nb), cap in edge_capacity.items():
        graph.add_edge(na, nb, capacity=cap)
        graph.add_edge(nb, na, capacity=cap)

    cut_value, (reachable, non_reachable) = nx.minimum_cut(graph, "S", "T", capacity="capacity")
    cavity_nodes = frozenset(n for n in reachable if n not in ("S", "T"))
    core_nodes = frozenset(n for n in non_reachable if n not in ("S", "T"))

    cut_pieces: list[dict] = []
    sub_edge_cut_count = 0
    for edge_id, intervals in sub_pieces.items():
        for t_start, t_end, na, nb in intervals:
            if (na in cavity_nodes) != (nb in cavity_nodes):
                cut_pieces.append({"kind": "edge", "edge_id": edge_id, "t_start": t_start, "t_end": t_end})
                sub_edge_cut_count += 1

    split_face_cut_count = 0
    for face_id, regions in face_regions.items():
        if not regions or len(regions) < 2:
            continue
        adjacency = face_region_adjacency[face_id]
        segs = track_b_by_face.get(face_id, [])
        checked_pairs: set[tuple] = set()
        for ra in adjacency:
            for rb in adjacency[ra]:
                pair_key = tuple(sorted((ra, rb)))
                if pair_key in checked_pairs:
                    continue
                checked_pairs.add(pair_key)
                node_a, node_b = (face_id, ra), (face_id, rb)
                if (node_a in cavity_nodes) == (node_b in cavity_nodes):
                    continue
                region_a = next(r for r in regions if r.region_id == ra)
                region_b = next(r for r in regions if r.region_id == rb)
                for seg in segs:
                    if len(seg.backing.uv) < 2:
                        continue
                    line = LineString(seg.backing.uv)
                    touches_a = region_a.polygon.boundary.intersection(line).length > 0
                    touches_b = region_b.polygon.boundary.intersection(line).length > 0
                    if touches_a and touches_b:
                        cut_pieces.append({"kind": "face", "face_id": face_id, "segment": seg})
                        split_face_cut_count += 1

    cavity_face_ids = frozenset(n[0] for n in cavity_nodes)
    core_face_ids = frozenset(n[0] for n in core_nodes)

    region_count_histogram: dict[int, int] = {}
    for regions in face_regions.values():
        n = len(regions) if regions else 1
        region_count_histogram[n] = region_count_histogram.get(n, 0) + 1

    multi_interval_edge_count = sum(1 for ivs in sub_pieces.values() if len(ivs) > 1)

    return {
        "cavity_face_ids": cavity_face_ids, "core_face_ids": core_face_ids,
        "cut_pieces": cut_pieces, "cut_value": cut_value,
        "split_face_cut_count": split_face_cut_count,
        "sub_edge_cut_count": sub_edge_cut_count,
        "multi_interval_edge_count": multi_interval_edge_count,
        "node_count_before": len(usable_faces),
        "node_count_after": sum(len(r) if r else 1 for r in face_regions.values()),
        "region_count_histogram": region_count_histogram,
        "total_track_b_faces": len(track_b_by_face),
    }


def _resolve_piece_geometry(part, piece: dict):
    """
    ``(points, backing, g_values)`` for one cut piece, in a fixed native
    order. An "edge" piece with explicit ``t_start``/``t_end`` (P3.16,
    sub-edge-aware attachment) samples only that sub-range of the edge's own
    curve, rather than always resampling the FULL edge -- the same
    ``EdgeBacking`` sub-range convention Track A's own segment splitting and
    H3's ``_uncovered_parameter`` (D-015) already use.
    """
    if piece["kind"] == "edge":
        edges_by_id = {e.edge_id: e for e in part.edges}
        edge = edges_by_id[piece["edge_id"]]
        full_first, full_last = BRep_Tool.Range(edge.occ_edge)
        first_p = piece.get("t_start", full_first)
        last_p = piece.get("t_end", full_last)
        points = tuple(_sample_edge_points(edge, first_p, last_p, n=9))
        return points, EdgeBacking(edge_id=piece["edge_id"], t_start=first_p, t_end=last_p), ()
    seg = piece["segment"]  # a real, already-computed Track-B CurveSegment -- reused verbatim
    return tuple(seg.points), seg.backing, tuple(seg.g_values)


def _weld_piece_endpoints(resolved_pieces: list[tuple], tolerance: float) -> dict[int, int]:
    """
    Proper radius-based welding of every piece's two endpoints (union-find on
    ACTUAL 3-D distance), not grid-cell rounding.

    Grid-cell rounding (`_weld_key`, used safely elsewhere in this file for
    exact/near-exact B-Rep-edge-to-B-Rep-edge vertices) has a documented
    failure mode -- production's own `graph.py` docstring calls it out
    explicitly: two points closer than the tolerance can land in different
    cells and never merge, which is exactly why production uses a
    27-neighbour-cell spatial hash instead of single-cell rounding. Track-B
    curve endpoints are only APPROXIMATELY on a bounding edge (never exactly,
    by construction -- D-022/D-023), so this failure mode is not a corner
    case here, it is the common case: a first version of this function used
    `_weld_key` directly and 19 of 26 cut-piece components came back
    odd-degree and got silently dropped -- almost the entire candidate.
    Piece-endpoint counts here are small (at most a few hundred), so a
    direct O(n^2) pairwise union-find is simple, correct by construction, and
    fast enough not to need the spatial-hash optimisation production uses at
    B-Rep scale.

    Returns ``{endpoint_slot: canonical_cluster_id}`` where
    ``endpoint_slot = 2*piece_index`` (start) or ``2*piece_index + 1`` (end).
    """
    points: list[tuple] = []
    for pts, _backing, _g in resolved_pieces:
        points.append(pts[0])
        points.append(pts[-1])
    n = len(points)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        for j in range(i + 1, n):
            if _dist(points[i], points[j]) <= tolerance:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj

    return {i: find(i) for i in range(n)}


def decompose_pieces_into_loops(resolved_pieces: list[tuple], clusters: dict[int, int]):
    """
    Same deterministic Hierholzer decomposition as `decompose_into_loops`,
    generalised to operate on piece INDICES rather than B-Rep edge ids, so it
    works identically whether a piece's geometry came from a whole B-Rep edge
    or from a face's own Track-B interior curve. Vertex identity comes from
    `clusters` (see `_weld_piece_endpoints`), not grid-cell rounding.
    """
    adjacency: dict[int, list[tuple[int, int]]] = {}
    for idx, (points, _backing, _g) in enumerate(resolved_pieces):
        k0, k1 = clusters[2 * idx], clusters[2 * idx + 1]
        adjacency.setdefault(k0, []).append((idx, k1))
        adjacency.setdefault(k1, []).append((idx, k0))

    seen_vertices: set = set()
    components: list[set] = []
    for v in adjacency:
        if v in seen_vertices:
            continue
        stack, comp = [v], set()
        seen_vertices.add(v)
        while stack:
            cur = stack.pop()
            comp.add(cur)
            for _idx, nb in adjacency[cur]:
                if nb not in seen_vertices:
                    seen_vertices.add(nb)
                    stack.append(nb)
        components.append(comp)

    notes: list[str] = []
    loops: list[list[int]] = []
    for comp in components:
        degrees = {v: len(adjacency[v]) for v in comp}
        if any(d % 2 != 0 for d in degrees.values()):
            notes.append(
                f"component with {len(comp)} vertices has an odd-degree vertex -- "
                "skipped, not forced."
            )
            continue
        comp_piece_idxs = {idx for v in comp for idx, _ in adjacency[v]}
        remaining = {v: sorted(adjacency[v], key=lambda t: t[0]) for v in comp}
        used: set[int] = set()
        start = min(comp)
        stack: list[tuple] = [(start, None)]
        walk: list[int] = []
        while stack:
            v, via = stack[-1]
            nxt = next(((idx, nb) for idx, nb in remaining.get(v, []) if idx not in used), None)
            if nxt is None:
                stack.pop()
                if via is not None:
                    walk.append(via)
            else:
                idx, nb = nxt
                used.add(idx)
                stack.append((nb, idx))
        walk.reverse()
        if len(used) != len(comp_piece_idxs):
            notes.append(
                f"component: only {len(used)}/{len(comp_piece_idxs)} pieces consumed "
                "by the Hierholzer walk (unexpected)."
            )
        if walk:
            loops.append(walk)
    return loops, notes


def _resolve_piece_directions(resolved_pieces, clusters: dict[int, int], walk: list[int]):
    if len(walk) == 1:
        return [(walk[0], True)]
    endpoints = {idx: (clusters[2 * idx], clusters[2 * idx + 1]) for idx in walk}
    n = len(walk)
    junction_after = []
    for i in range(n):
        cur_ep, nxt_ep = endpoints[walk[i]], endpoints[walk[(i + 1) % n]]
        shared = next((c for c in cur_ep if c in nxt_ep), None)
        junction_after.append(shared)

    resolved = []
    for i, idx in enumerate(walk):
        ep = endpoints[idx]
        to_v = junction_after[i]
        if to_v is None:
            resolved.append((idx, True))
        elif ep[1] == to_v:
            resolved.append((idx, True))
        elif ep[0] == to_v:
            resolved.append((idx, False))
        else:
            resolved.append((idx, True))
    return resolved


def assemble_candidate_from_pieces(resolved_pieces, clusters: dict[int, int], loop_walks: list[list[int]], candidate_id: int):
    all_segments: list[CurveSegment] = []
    loops_points: list[tuple] = []

    for walk in loop_walks:
        if not walk:
            continue
        loop_pts: list[tuple] = []
        for idx, ascending in _resolve_piece_directions(resolved_pieces, clusters, walk):
            points, backing, g_values = resolved_pieces[idx]
            pts = list(points)
            uv = list(backing.uv) if isinstance(backing, FaceBacking) else None
            gvals = list(g_values) if g_values else None
            if not ascending:
                pts.reverse()
                if uv is not None:
                    uv.reverse()
                if gvals is not None:
                    gvals.reverse()
            if loop_pts and _dist(loop_pts[-1], pts[0]) < 1e-6:
                pts = pts[1:]
                if uv is not None:
                    uv = uv[1:]
                if gvals is not None:
                    gvals = gvals[1:]
            if len(pts) < 2:
                continue
            loop_pts.extend(pts)

            final_backing = FaceBacking(face_id=backing.face_id, uv=tuple(uv)) if uv is not None else backing
            segment = CurveSegment(
                segment_id=next(_seg_id_counter),
                points=tuple(pts),
                backing=final_backing,
                kind="silhouette",
                g_values=tuple(gvals) if gvals is not None and len(gvals) == len(pts) else (),
            )
            all_segments.append(segment)

        if len(loop_pts) >= 2:
            loops_points.append(tuple(loop_pts))

    if not loops_points or not all_segments:
        return None

    total_points = tuple(p for loop in loops_points for p in loop)
    return PartingLoopCandidate(
        candidate_id=candidate_id,
        segments=tuple(all_segments),
        points=total_points,
        is_closed=True,
        discovered_by=DISCOVERED_BY_TAG,  # type: ignore[arg-type]
        loops=tuple(loops_points),
    )


def run_experiment_split(
    part, direction_tuple, part_label: str, direction_label: str, cfg, undercuts,
    *, max_curves_per_split_face: int | None = None,
):
    """Track-B-inclusive counterpart of `run_experiment` -- same objectives, same gates."""
    bbox_diag = _bbox_diagonal(part)
    direction = PullDirectionInput(direction_tuple, "manual").direction

    track_a = detect_edge_silhouettes(part, direction, cfg=cfg, bbox_diagonal_mm=bbox_diag)
    silhouette_edge_ids = frozenset(
        s.backing.edge_id for s in track_a.segments
        if s.kind == "silhouette" and isinstance(s.backing, EdgeBacking)
    )
    track_b = detect_face_silhouettes(
        part, direction, cfg=cfg, bbox_diagonal_mm=bbox_diag, start_segment_id=len(track_a.segments)
    )

    valid_faces = [f for f in part.faces if f.normal_valid]
    part_projected_area = measures.cauchy_projected_area(
        [f.area for f in valid_faces],
        [mean_abs_g(f, direction, cfg.face_sample_grid) for f in valid_faces],
    )
    weld_cell = max(cfg.weld_tolerance_rel * bbox_diag, 1e-7) * 5.0
    # Track-B curve endpoints land on a bounding edge only approximately (the
    # same problem stitch.py solves in production via stitch_snap_tolerance_rel,
    # D-022 widened to ~0.02 relative after measuring real Part3 junction gaps
    # of 0.043-1.05mm) -- use the SAME, looser tolerance scale here rather than
    # the tight point-welding tolerance, for exactly the same reason.
    face_weld_cell = max(cfg.stitch_snap_tolerance_rel * bbox_diag, 1e-6)

    track_b_by_face_all: dict[int, int] = {}
    for seg in track_b.segments:
        if isinstance(seg.backing, FaceBacking):
            track_b_by_face_all[seg.backing.face_id] = track_b_by_face_all.get(seg.backing.face_id, 0) + 1
    split_face_count = len(track_b_by_face_all)
    curve_count_histogram: dict[int, int] = {}
    for count in track_b_by_face_all.values():
        curve_count_histogram[count] = curve_count_histogram.get(count, 0) + 1

    results = []
    for obj_name, (unary_w, smooth_w, discount) in OBJECTIVES.items():
        t0 = time.time()
        cut = build_min_cut_partition_split(
            part, direction, track_b.segments, silhouette_edge_ids,
            unary_weight=unary_w, smoothness_weight=smooth_w, silhouette_discount=discount,
            max_curves_per_split_face=max_curves_per_split_face,
        )
        if cut is None:
            results.append({"objective": obj_name, "error": "insufficient usable faces"})
            continue
        if not cut["cut_pieces"]:
            results.append({
                "objective": obj_name, "degenerate_cut": True,
                "cavity_face_count": len(cut["cavity_face_ids"]),
                "core_face_count": len(cut["core_face_ids"]),
                "cut_value": cut["cut_value"],
                "split_face_cut_count": cut["split_face_cut_count"],
            })
            continue

        resolved_pieces = [_resolve_piece_geometry(part, p) for p in cut["cut_pieces"]]
        clusters = _weld_piece_endpoints(resolved_pieces, face_weld_cell)
        walks, decomp_notes = decompose_pieces_into_loops(resolved_pieces, clusters)
        candidate = assemble_candidate_from_pieces(
            resolved_pieces, clusters, walks, candidate_id=910000 + hash(obj_name) % 1000
        )
        elapsed_s = round(time.time() - t0, 3)
        if candidate is None:
            results.append({
                "objective": obj_name, "error": "could not assemble any closed loop",
                "decomposition_notes": decomp_notes,
                "cut_piece_count": len(cut["cut_pieces"]),
                "split_face_cut_count": cut["split_face_cut_count"],
            })
            continue

        outcome = evaluate_gates(
            candidate, part, direction,
            undercuts=undercuts, cfg=cfg,
            bbox_diagonal_mm=bbox_diag, part_projected_area_mm2=part_projected_area,
        )
        candidate = replace(candidate, feasibility=outcome.report)
        score_dict = None
        region_areas = None
        if outcome.regions is not None:
            region_areas = {
                "cavity_area_mm2": round(outcome.regions.cavity_area_mm2, 3),
                "core_area_mm2": round(outcome.regions.core_area_mm2, 3),
                "ambiguous_area_mm2": round(outcome.regions.ambiguous_area_mm2, 3),
                "total_area_mm2": round(outcome.regions.total_area_mm2, 3),
            }
        if outcome.report.passed and outcome.regions is not None:
            score = ranking.score_candidate(
                candidate, direction, undercuts=undercuts,
                bbox_diagonal_mm=bbox_diag, part_projected_area_mm2=part_projected_area,
                ambiguous_area_fraction=outcome.regions.ambiguous_area_fraction,
            )
            score_dict = score.to_dict()

        # Trivial-pinch check (the exact D-038 false-lead pattern): flag
        # whenever one side is under 5% of the total usable face count.
        total_faces = len(cut["cavity_face_ids"]) + len(cut["core_face_ids"])
        smaller_side = min(len(cut["cavity_face_ids"]), len(cut["core_face_ids"]))
        is_trivial_pinch = total_faces > 0 and (smaller_side / total_faces) < 0.05

        results.append({
            "objective": obj_name,
            "weights": {"unary": unary_w, "smoothness": smooth_w, "silhouette_discount": discount},
            "cut_value": cut["cut_value"],
            "cavity_face_count": len(cut["cavity_face_ids"]),
            "core_face_count": len(cut["core_face_ids"]),
            "faces_touched": total_faces,
            "region_areas": region_areas,
            "is_trivial_pinch": is_trivial_pinch,
            "cut_piece_count": len(cut["cut_pieces"]),
            "split_face_cut_count": cut["split_face_cut_count"],
            "represented_split_face_count": cut["represented_split_face_count"],
            "unsplit_track_b_face_count": cut["unsplit_track_b_face_count"],
            "loop_count": len(walks),
            "is_single_continuous_loop": len(walks) == 1,
            "decomposition_notes": decomp_notes,
            "elapsed_s": elapsed_s,
            "candidate_segment_count": len(candidate.segments),
            "candidate_point_count": len(candidate.points),
            "feasibility": outcome.report.to_dict(),
            "score": score_dict,
        })

    return {
        "part": part_label,
        "direction_label": direction_label,
        "direction": list(direction),
        "track_a_segment_count": len(track_a.segments),
        "track_b_segment_count": len(track_b.segments),
        "split_face_count": split_face_count,
        "curve_count_histogram": curve_count_histogram,
        "max_curves_per_split_face_setting": max_curves_per_split_face,
        "node_count_before": len(valid_faces),
        "node_count_after": len(valid_faces) + split_face_count,
        "part_projected_area_mm2": part_projected_area,
        "bbox_diagonal_mm": bbox_diag,
        "results": results,
    }


def run_experiment_nway(part, direction_tuple, part_label: str, direction_label: str, cfg, undercuts):
    """N-way (Option 1, P3.15) counterpart of `run_experiment_split` -- same objectives, same gates."""
    bbox_diag = _bbox_diagonal(part)
    direction = PullDirectionInput(direction_tuple, "manual").direction

    track_a = detect_edge_silhouettes(part, direction, cfg=cfg, bbox_diagonal_mm=bbox_diag)
    silhouette_edge_ids = frozenset(
        s.backing.edge_id for s in track_a.segments
        if s.kind == "silhouette" and isinstance(s.backing, EdgeBacking)
    )
    track_b = detect_face_silhouettes(
        part, direction, cfg=cfg, bbox_diagonal_mm=bbox_diag, start_segment_id=len(track_a.segments)
    )

    valid_faces = [f for f in part.faces if f.normal_valid]
    part_projected_area = measures.cauchy_projected_area(
        [f.area for f in valid_faces],
        [mean_abs_g(f, direction, cfg.face_sample_grid) for f in valid_faces],
    )
    face_weld_cell = max(cfg.stitch_snap_tolerance_rel * bbox_diag, 1e-6)

    track_b_by_face_all: dict[int, int] = {}
    for seg in track_b.segments:
        if isinstance(seg.backing, FaceBacking):
            track_b_by_face_all[seg.backing.face_id] = track_b_by_face_all.get(seg.backing.face_id, 0) + 1
    split_face_count = len(track_b_by_face_all)
    curve_count_histogram: dict[int, int] = {}
    for count in track_b_by_face_all.values():
        curve_count_histogram[count] = curve_count_histogram.get(count, 0) + 1

    results = []
    region_count_histogram_last: dict = {}
    for obj_name, (unary_w, smooth_w, discount) in OBJECTIVES.items():
        t0 = time.time()
        cut = build_min_cut_partition_nway(
            part, direction, track_b.segments, silhouette_edge_ids,
            unary_weight=unary_w, smoothness_weight=smooth_w, silhouette_discount=discount,
        )
        if cut is None:
            results.append({"objective": obj_name, "error": "insufficient usable faces"})
            continue
        region_count_histogram_last = cut["region_count_histogram"]
        if not cut["cut_pieces"]:
            results.append({
                "objective": obj_name, "degenerate_cut": True,
                "cavity_face_count": len(cut["cavity_face_ids"]),
                "core_face_count": len(cut["core_face_ids"]),
                "cut_value": cut["cut_value"],
                "split_face_cut_count": cut["split_face_cut_count"],
            })
            continue

        resolved_pieces = [_resolve_piece_geometry(part, p) for p in cut["cut_pieces"]]
        clusters = _weld_piece_endpoints(resolved_pieces, face_weld_cell)
        walks, decomp_notes = decompose_pieces_into_loops(resolved_pieces, clusters)
        candidate = assemble_candidate_from_pieces(
            resolved_pieces, clusters, walks, candidate_id=920000 + hash(obj_name) % 1000
        )
        elapsed_s = round(time.time() - t0, 3)
        if candidate is None:
            results.append({
                "objective": obj_name, "error": "could not assemble any closed loop",
                "decomposition_notes": decomp_notes,
                "cut_piece_count": len(cut["cut_pieces"]),
                "split_face_cut_count": cut["split_face_cut_count"],
            })
            continue

        outcome = evaluate_gates(
            candidate, part, direction,
            undercuts=undercuts, cfg=cfg,
            bbox_diagonal_mm=bbox_diag, part_projected_area_mm2=part_projected_area,
        )
        candidate = replace(candidate, feasibility=outcome.report)
        score_dict = None
        region_areas = None
        if outcome.regions is not None:
            region_areas = {
                "cavity_area_mm2": round(outcome.regions.cavity_area_mm2, 3),
                "core_area_mm2": round(outcome.regions.core_area_mm2, 3),
                "ambiguous_area_mm2": round(outcome.regions.ambiguous_area_mm2, 3),
                "total_area_mm2": round(outcome.regions.total_area_mm2, 3),
            }
        if outcome.report.passed and outcome.regions is not None:
            score = ranking.score_candidate(
                candidate, direction, undercuts=undercuts,
                bbox_diagonal_mm=bbox_diag, part_projected_area_mm2=part_projected_area,
                ambiguous_area_fraction=outcome.regions.ambiguous_area_fraction,
            )
            score_dict = score.to_dict()

        total_faces = len(cut["cavity_face_ids"]) + len(cut["core_face_ids"])
        smaller_side = min(len(cut["cavity_face_ids"]), len(cut["core_face_ids"]))
        is_trivial_pinch = total_faces > 0 and (smaller_side / total_faces) < 0.05

        results.append({
            "objective": obj_name,
            "weights": {"unary": unary_w, "smoothness": smooth_w, "silhouette_discount": discount},
            "cut_value": cut["cut_value"],
            "cavity_face_count": len(cut["cavity_face_ids"]),
            "core_face_count": len(cut["core_face_ids"]),
            "faces_touched": total_faces,
            "region_areas": region_areas,
            "is_trivial_pinch": is_trivial_pinch,
            "cut_piece_count": len(cut["cut_pieces"]),
            "split_face_cut_count": cut["split_face_cut_count"],
            "represented_split_face_count": sum(
                n for regions, n in cut["region_count_histogram"].items() if regions > 1
            ),
            "loop_count": len(walks),
            "is_single_continuous_loop": len(walks) == 1,
            "decomposition_notes": decomp_notes,
            "elapsed_s": elapsed_s,
            "candidate_segment_count": len(candidate.segments),
            "candidate_point_count": len(candidate.points),
            "feasibility": outcome.report.to_dict(),
            "score": score_dict,
        })

    return {
        "part": part_label,
        "direction_label": direction_label,
        "direction": list(direction),
        "track_a_segment_count": len(track_a.segments),
        "track_b_segment_count": len(track_b.segments),
        "split_face_count": split_face_count,
        "curve_count_histogram": curve_count_histogram,
        "region_count_histogram": region_count_histogram_last,
        "node_count_before": len(valid_faces),
        "part_projected_area_mm2": part_projected_area,
        "bbox_diagonal_mm": bbox_diag,
        "results": results,
    }


def run_experiment_nway_subedge(part, direction_tuple, part_label: str, direction_label: str, cfg, undercuts):
    """Sub-edge-aware N-way (P3.16, "Task 3") counterpart of `run_experiment_nway`."""
    bbox_diag = _bbox_diagonal(part)
    direction = PullDirectionInput(direction_tuple, "manual").direction

    track_a = detect_edge_silhouettes(part, direction, cfg=cfg, bbox_diagonal_mm=bbox_diag)
    silhouette_edge_ids = frozenset(
        s.backing.edge_id for s in track_a.segments
        if s.kind == "silhouette" and isinstance(s.backing, EdgeBacking)
    )
    track_b = detect_face_silhouettes(
        part, direction, cfg=cfg, bbox_diagonal_mm=bbox_diag, start_segment_id=len(track_a.segments)
    )

    valid_faces = [f for f in part.faces if f.normal_valid]
    part_projected_area = measures.cauchy_projected_area(
        [f.area for f in valid_faces],
        [mean_abs_g(f, direction, cfg.face_sample_grid) for f in valid_faces],
    )
    face_weld_cell = max(cfg.stitch_snap_tolerance_rel * bbox_diag, 1e-6)

    track_b_by_face_all: dict[int, int] = {}
    for seg in track_b.segments:
        if isinstance(seg.backing, FaceBacking):
            track_b_by_face_all[seg.backing.face_id] = track_b_by_face_all.get(seg.backing.face_id, 0) + 1
    split_face_count = len(track_b_by_face_all)
    curve_count_histogram: dict[int, int] = {}
    for count in track_b_by_face_all.values():
        curve_count_histogram[count] = curve_count_histogram.get(count, 0) + 1

    results = []
    region_count_histogram_last: dict = {}
    for obj_name, (unary_w, smooth_w, discount) in OBJECTIVES.items():
        t0 = time.time()
        cut = build_min_cut_partition_nway_subedge(
            part, direction, track_b.segments, silhouette_edge_ids,
            unary_weight=unary_w, smoothness_weight=smooth_w, silhouette_discount=discount,
        )
        if cut is None:
            results.append({"objective": obj_name, "error": "insufficient usable faces"})
            continue
        region_count_histogram_last = cut["region_count_histogram"]
        if not cut["cut_pieces"]:
            results.append({
                "objective": obj_name, "degenerate_cut": True,
                "cavity_face_count": len(cut["cavity_face_ids"]),
                "core_face_count": len(cut["core_face_ids"]),
                "cut_value": cut["cut_value"],
                "split_face_cut_count": cut["split_face_cut_count"],
                "sub_edge_cut_count": cut["sub_edge_cut_count"],
                "multi_interval_edge_count": cut["multi_interval_edge_count"],
            })
            continue

        resolved_pieces = [_resolve_piece_geometry(part, p) for p in cut["cut_pieces"]]
        clusters = _weld_piece_endpoints(resolved_pieces, face_weld_cell)
        walks, decomp_notes = decompose_pieces_into_loops(resolved_pieces, clusters)
        candidate = assemble_candidate_from_pieces(
            resolved_pieces, clusters, walks, candidate_id=930000 + hash(obj_name) % 1000
        )
        elapsed_s = round(time.time() - t0, 3)
        if candidate is None:
            results.append({
                "objective": obj_name, "error": "could not assemble any closed loop",
                "decomposition_notes": decomp_notes,
                "cut_piece_count": len(cut["cut_pieces"]),
                "split_face_cut_count": cut["split_face_cut_count"],
                "sub_edge_cut_count": cut["sub_edge_cut_count"],
                "multi_interval_edge_count": cut["multi_interval_edge_count"],
            })
            continue

        outcome = evaluate_gates(
            candidate, part, direction,
            undercuts=undercuts, cfg=cfg,
            bbox_diagonal_mm=bbox_diag, part_projected_area_mm2=part_projected_area,
        )
        candidate = replace(candidate, feasibility=outcome.report)
        score_dict = None
        region_areas = None
        if outcome.regions is not None:
            region_areas = {
                "cavity_area_mm2": round(outcome.regions.cavity_area_mm2, 3),
                "core_area_mm2": round(outcome.regions.core_area_mm2, 3),
                "ambiguous_area_mm2": round(outcome.regions.ambiguous_area_mm2, 3),
                "total_area_mm2": round(outcome.regions.total_area_mm2, 3),
            }
        if outcome.report.passed and outcome.regions is not None:
            score = ranking.score_candidate(
                candidate, direction, undercuts=undercuts,
                bbox_diagonal_mm=bbox_diag, part_projected_area_mm2=part_projected_area,
                ambiguous_area_fraction=outcome.regions.ambiguous_area_fraction,
            )
            score_dict = score.to_dict()

        total_faces = len(cut["cavity_face_ids"]) + len(cut["core_face_ids"])
        smaller_side = min(len(cut["cavity_face_ids"]), len(cut["core_face_ids"]))
        is_trivial_pinch = total_faces > 0 and (smaller_side / total_faces) < 0.05

        results.append({
            "objective": obj_name,
            "weights": {"unary": unary_w, "smoothness": smooth_w, "silhouette_discount": discount},
            "cut_value": cut["cut_value"],
            "cavity_face_count": len(cut["cavity_face_ids"]),
            "core_face_count": len(cut["core_face_ids"]),
            "faces_touched": total_faces,
            "region_areas": region_areas,
            "is_trivial_pinch": is_trivial_pinch,
            "cut_piece_count": len(cut["cut_pieces"]),
            "split_face_cut_count": cut["split_face_cut_count"],
            "sub_edge_cut_count": cut["sub_edge_cut_count"],
            "multi_interval_edge_count": cut["multi_interval_edge_count"],
            "represented_split_face_count": sum(
                n for regions, n in cut["region_count_histogram"].items() if regions > 1
            ),
            "loop_count": len(walks),
            "is_single_continuous_loop": len(walks) == 1,
            "decomposition_notes": decomp_notes,
            "elapsed_s": elapsed_s,
            "candidate_segment_count": len(candidate.segments),
            "candidate_point_count": len(candidate.points),
            "feasibility": outcome.report.to_dict(),
            "score": score_dict,
        })

    return {
        "part": part_label,
        "direction_label": direction_label,
        "direction": list(direction),
        "track_a_segment_count": len(track_a.segments),
        "track_b_segment_count": len(track_b.segments),
        "split_face_count": split_face_count,
        "curve_count_histogram": curve_count_histogram,
        "region_count_histogram": region_count_histogram_last,
        "node_count_before": len(valid_faces),
        "part_projected_area_mm2": part_projected_area,
        "bbox_diagonal_mm": bbox_diag,
        "results": results,
    }


def main_experiment_1():
    """The 5-phase matrix specified for Experiment 1 (post-D-038)."""
    cfg = settings.dfm.parting_line_v2
    undercuts = UndercutInput.empty()

    def unit(v):
        n = math.sqrt(sum(c * c for c in v))
        return tuple(c / n for c in v)

    print("Loading Part1.stp / Part3.stp ...", flush=True)
    part1 = load_step_cached("data/parts/Part1.stp")
    part3 = load_step_cached("data/parts/Part3.stp")

    az15 = unit((math.cos(math.radians(15)), math.sin(math.radians(15)), 0.0))

    def report_run(result):
        for r in result["results"]:
            if "error" in r:
                print(f"    {r['objective']:28s} ERROR: {r['error']}", flush=True)
            elif r.get("degenerate_cut"):
                print(f"    {r['objective']:28s} degenerate cut (split_face_cuts={r.get('split_face_cut_count')})", flush=True)
            else:
                fr = r["feasibility"]
                print(
                    f"    {r['objective']:28s} outcome={fr['outcome']:10s} "
                    f"failed_gate={str(fr['failed_gate']):5s} loops={r['loop_count']} "
                    f"split_face_cuts={r.get('split_face_cut_count', 'n/a')} "
                    f"cavity={r['cavity_face_count']} core={r['core_face_count']} "
                    f"h3={fr['measurements'].get('h3_region_count')} "
                    f"h4={fr['measurements'].get('h4_orientation_violation_fraction')}",
                    flush=True,
                )

    all_results: dict[str, object] = {"phase1_part1_regression": [], "phase2_d038_comparison": [],
                                       "phase3_track_b_heavy": []}

    print("\n########## PHASE 1 -- REGRESSION (Part1 +Z, Part1 +X) ##########", flush=True)
    for direction, label in [(unit((0, 0, 1)), "+Z (golden control)"), (unit((1, 0, 0)), "+X (negative control)")]:
        print(f"\n=== Part1 @ {label} -- NEW (Track-B-inclusive) ===", flush=True)
        result = run_experiment_split(part1, direction, "Part1", label, cfg, undercuts)
        report_run(result)
        all_results["phase1_part1_regression"].append(result)

    print("\n########## PHASE 2 -- EXACT D-038 COMPARISON (Part3 az15, (0,1,1)) ##########", flush=True)
    for direction, label in [(az15, "equatorial az15"), (unit((0, 1, 1)), "(0,1,1) CASE-A anchor")]:
        print(f"\n=== Part3 @ {label} -- OLD (face-only, D-038) ===", flush=True)
        old_result = run_experiment(part3, direction, "Part3", label, cfg, undercuts)
        report_run(old_result)
        print(f"=== Part3 @ {label} -- NEW (Track-B-inclusive) ===", flush=True)
        new_result = run_experiment_split(part3, direction, "Part3", label, cfg, undercuts)
        report_run(new_result)
        all_results["phase2_d038_comparison"].append({"direction_label": label, "old": old_result, "new": new_result})

    print("\n########## PHASE 3 -- TRACK-B-HEAVY DIRECTIONS (chosen by measured Track-B activity, D-026) ##########", flush=True)
    # D-026 principal-direction table: Track A/B segment counts were
    # +X=332/175, -X=332/174, +Y=336/169, -Y=336/171, +Z=352/0(ish) --
    # +X/-X/+Y are the three highest-Track-B-count directions on record,
    # chosen for that reason alone, not because any of them looked promising.
    for direction, label in [(unit((1, 0, 0)), "+X (highest measured Track-B count)"),
                              (unit((-1, 0, 0)), "-X (2nd highest measured Track-B count)"),
                              (unit((0, 1, 0)), "+Y (3rd highest measured Track-B count)")]:
        print(f"\n=== Part3 @ {label} -- NEW (Track-B-inclusive) ===", flush=True)
        result = run_experiment_split(part3, direction, "Part3", label, cfg, undercuts)
        print(f"    track_a={result['track_a_segment_count']} track_b={result['track_b_segment_count']} "
              f"split_faces={result['split_face_count']} nodes_before={result['node_count_before']} "
              f"nodes_after={result['node_count_after']}", flush=True)
        report_run(result)
        all_results["phase3_track_b_heavy"].append(result)

    REPORTS_DIR.mkdir(exist_ok=True)
    out_path = REPORTS_DIR / "region_partition_experiment1.json"
    out_path.write_text(json.dumps(all_results, indent=2))
    print(f"\nDone. Full results in {out_path}", flush=True)


# ===========================================================================
# OPTION 2 (P3.14, 2026-08-13): single-curve-only Track-B split faces
# ===========================================================================
#
# P3.13's unrestricted split-face attempt applied a binary (face,+1)/(face,-1)
# model to EVERY Track-B split face, including the 45% with more than one
# disjoint interior curve -- topologically invalid for those faces (D-014's
# own stated scope is a single monotone crossing), and the direct cause of
# the pervasive odd-degree fragmentation observed there. This is NOT a
# finding about Part3's separability; it is a finding about that specific
# construction's validity. Option 2 isolates the variable: represent ONLY
# the faces where the binary model is provably correct (exactly one curve),
# leave every multi-curve face exactly as D-038 did (unsplit, whole-face).

def _gate_tally(results: list[dict]) -> dict:
    tally = {"H0": 0, "H1": 0, "H2": 0, "H3": 0, "H4": 0, "H5": 0, "H6": 0, "H7": 0,
             "degenerate_or_error": 0, "feasible": 0}
    largest = None
    for r in results:
        if "error" in r or r.get("degenerate_cut"):
            tally["degenerate_or_error"] += 1
            continue
        fr = r["feasibility"]
        if fr["passed"]:
            tally["feasible"] += 1
        elif fr["failed_gate"] in tally:
            tally[fr["failed_gate"]] += 1
        cov = fr["measurements"].get("h7_coverage")
        if cov is not None and (largest is None or cov > largest.get("h7_coverage", -1)):
            largest = {
                "objective": r["objective"], "h7_coverage": cov,
                "cavity_face_count": r["cavity_face_count"], "core_face_count": r["core_face_count"],
                "loop_count": r["loop_count"], "is_trivial_pinch": r.get("is_trivial_pinch"),
            }
    return {"gate_tally": tally, "largest_by_coverage": largest}


def report_run_option2(result: dict):
    for r in result["results"]:
        if "error" in r:
            print(f"    {r['objective']:28s} ERROR: {r['error']}", flush=True)
        elif r.get("degenerate_cut"):
            print(f"    {r['objective']:28s} degenerate cut", flush=True)
        else:
            fr = r["feasibility"]
            areas = r.get("region_areas") or {}
            print(
                f"    {r['objective']:28s} outcome={fr['outcome']:10s} "
                f"failed_gate={str(fr['failed_gate']):5s} loops={r['loop_count']} "
                f"single_loop={r['is_single_continuous_loop']} pinch={r['is_trivial_pinch']} "
                f"represented_split={r['represented_split_face_count']} "
                f"cavity={r['cavity_face_count']} core={r['core_face_count']} "
                f"cavity_mm2={areas.get('cavity_area_mm2')} core_mm2={areas.get('core_area_mm2')} "
                f"h3={fr['measurements'].get('h3_region_count')} "
                f"h4={fr['measurements'].get('h4_orientation_violation_fraction')} "
                f"h7={fr['measurements'].get('h7_coverage')}",
                flush=True,
            )
    summary = _gate_tally(result["results"])
    print(f"    -- gate tally: {summary['gate_tally']}", flush=True)
    if summary["largest_by_coverage"]:
        print(f"    -- largest by coverage: {summary['largest_by_coverage']}", flush=True)


def main_option1():
    """Option 1 (P3.15): proper N-way face partitioning, full matrix per the post-D-039 spec."""
    cfg = settings.dfm.parting_line_v2
    undercuts = UndercutInput.empty()

    def unit(v):
        n = math.sqrt(sum(c * c for c in v))
        return tuple(c / n for c in v)

    print("Loading Part1.stp / Part3.stp ...", flush=True)
    part1 = load_step_cached("data/parts/Part1.stp")
    part3 = load_step_cached("data/parts/Part3.stp")

    az15 = unit((math.cos(math.radians(15)), math.sin(math.radians(15)), 0.0))

    all_results: dict[str, object] = {
        "phase4_part1_regression": [], "phase5_part3": [], "phase6_three_way_comparison": [],
    }

    print("\n########## PHASE 4 -- REGRESSION (Part1 +Z, Part1 +X), N-WAY ##########", flush=True)
    for direction, label in [(unit((0, 0, 1)), "+Z (golden control)"), (unit((1, 0, 0)), "+X (negative control)")]:
        print(f"\n=== Part1 @ {label} -- N-WAY ===", flush=True)
        result = run_experiment_nway(part1, direction, "Part1", label, cfg, undercuts)
        print(f"    split_faces(track_b)={result['split_face_count']} region_hist={result['region_count_histogram']}", flush=True)
        report_run_option2(result)
        all_results["phase4_part1_regression"].append(result)

    print("\n########## PHASE 5 -- PART3, N-WAY ##########", flush=True)
    directions = [
        (az15, "equatorial az15"),
        (unit((0, 1, 1)), "(0,1,1) CASE-A anchor"),
        (unit((1, 0, 0)), "+X (highest measured Track-B count)"),
        (unit((-1, 0, 0)), "-X (2nd highest measured Track-B count)"),
        (unit((0, 1, 0)), "+Y (3rd highest measured Track-B count)"),
    ]
    for direction, label in directions:
        print(f"\n=== Part3 @ {label} -- N-WAY ===", flush=True)
        t0 = time.time()
        result = run_experiment_nway(part3, direction, "Part3", label, cfg, undercuts)
        print(f"    track_a={result['track_a_segment_count']} track_b={result['track_b_segment_count']} "
              f"split_faces(track_b)={result['split_face_count']} curve_hist={result['curve_count_histogram']} "
              f"region_hist={result['region_count_histogram']}", flush=True)
        report_run_option2(result)
        print(f"    ({time.time() - t0:.1f}s)", flush=True)
        all_results["phase5_part3"].append(result)
        REPORTS_DIR.mkdir(exist_ok=True)
        (REPORTS_DIR / "region_partition_option1.json").write_text(json.dumps(all_results, indent=2))

    print(f"\nDone. Full results in {REPORTS_DIR / 'region_partition_option1.json'}", flush=True)


def main_subedge():
    """P3.16 (post-D-040): sub-edge-aware cross-face attachment, Tasks 5-7."""
    cfg = settings.dfm.parting_line_v2
    undercuts = UndercutInput.empty()

    def unit(v):
        n = math.sqrt(sum(c * c for c in v))
        return tuple(c / n for c in v)

    print("Loading Part1.stp / Part3.stp ...", flush=True)
    part1 = load_step_cached("data/parts/Part1.stp")
    part3 = load_step_cached("data/parts/Part3.stp")
    az15 = unit((math.cos(math.radians(15)), math.sin(math.radians(15)), 0.0))

    all_results: dict[str, object] = {"phase5_part1_regression": [], "phase6_part3": []}

    print("\n########## REGRESSION (Part1 +Z, Part1 +X), SUB-EDGE ##########", flush=True)
    for direction, label in [(unit((0, 0, 1)), "+Z (golden control)"), (unit((1, 0, 0)), "+X (negative control)")]:
        print(f"\n=== Part1 @ {label} -- SUB-EDGE ===", flush=True)
        result = run_experiment_nway_subedge(part1, direction, "Part1", label, cfg, undercuts)
        report_run_option2(result)
        all_results["phase5_part1_regression"].append(result)

    print("\n########## PART3, SUB-EDGE ##########", flush=True)
    directions = [
        (az15, "equatorial az15"),
        (unit((0, 1, 1)), "(0,1,1) CASE-A anchor"),
        (unit((1, 0, 0)), "+X (highest measured Track-B count)"),
        (unit((-1, 0, 0)), "-X (2nd highest measured Track-B count)"),
        (unit((0, 1, 0)), "+Y (3rd highest measured Track-B count)"),
    ]
    for direction, label in directions:
        print(f"\n=== Part3 @ {label} -- SUB-EDGE ===", flush=True)
        t0 = time.time()
        result = run_experiment_nway_subedge(part3, direction, "Part3", label, cfg, undercuts)
        print(f"    track_a={result['track_a_segment_count']} track_b={result['track_b_segment_count']} "
              f"split_faces(track_b)={result['split_face_count']} curve_hist={result['curve_count_histogram']} "
              f"region_hist={result['region_count_histogram']}", flush=True)
        for r in result["results"]:
            if "error" in r:
                print(f"    {r['objective']:28s} ERROR: {r['error']}", flush=True)
            elif r.get("degenerate_cut"):
                print(f"    {r['objective']:28s} degenerate cut", flush=True)
            else:
                fr = r["feasibility"]
                areas = r.get("region_areas") or {}
                print(
                    f"    {r['objective']:28s} outcome={fr['outcome']:10s} "
                    f"failed_gate={str(fr['failed_gate']):5s} loops={r['loop_count']} "
                    f"single_loop={r['is_single_continuous_loop']} pinch={r['is_trivial_pinch']} "
                    f"sub_edge_cuts={r.get('sub_edge_cut_count')} multi_interval_edges={r.get('multi_interval_edge_count')} "
                    f"cavity={r['cavity_face_count']} core={r['core_face_count']} "
                    f"cavity_mm2={areas.get('cavity_area_mm2')} core_mm2={areas.get('core_area_mm2')} "
                    f"h3={fr['measurements'].get('h3_region_count')} "
                    f"h4={fr['measurements'].get('h4_orientation_violation_fraction')} "
                    f"h7={fr['measurements'].get('h7_coverage')}",
                    flush=True,
                )
        summary = _gate_tally(result["results"])
        print(f"    -- gate tally: {summary['gate_tally']}", flush=True)
        print(f"    ({time.time() - t0:.1f}s)", flush=True)
        all_results["phase6_part3"].append(result)
        REPORTS_DIR.mkdir(exist_ok=True)
        (REPORTS_DIR / "region_partition_subedge.json").write_text(json.dumps(all_results, indent=2))

    print(f"\nDone. Full results in {REPORTS_DIR / 'region_partition_subedge.json'}", flush=True)


def main_option2():
    cfg = settings.dfm.parting_line_v2
    undercuts = UndercutInput.empty()

    def unit(v):
        n = math.sqrt(sum(c * c for c in v))
        return tuple(c / n for c in v)

    print("Loading Part1.stp / Part3.stp ...", flush=True)
    part1 = load_step_cached("data/parts/Part1.stp")
    part3 = load_step_cached("data/parts/Part3.stp")

    az15 = unit((math.cos(math.radians(15)), math.sin(math.radians(15)), 0.0))

    all_results: dict[str, object] = {
        "phase1_part1_regression": [], "phase2_d038_vs_option2": [], "phase3_track_b_heavy": [],
    }

    print("\n########## PHASE 1 -- REGRESSION (Part1 +Z, Part1 +X), Option 2 (max_curves=1) ##########", flush=True)
    for direction, label in [(unit((0, 0, 1)), "+Z (golden control)"), (unit((1, 0, 0)), "+X (negative control)")]:
        print(f"\n=== Part1 @ {label} -- OPTION 2 ===", flush=True)
        result = run_experiment_split(part1, direction, "Part1", label, cfg, undercuts, max_curves_per_split_face=1)
        print(f"    split_faces(total)={result['split_face_count']} histogram={result['curve_count_histogram']}", flush=True)
        report_run_option2(result)
        all_results["phase1_part1_regression"].append(result)

    print("\n########## PHASE 2 -- D-038 (face-only) vs OPTION 2 (Part3 az15, (0,1,1)) ##########", flush=True)
    for direction, label in [(az15, "equatorial az15"), (unit((0, 1, 1)), "(0,1,1) CASE-A anchor")]:
        print(f"\n=== Part3 @ {label} -- D-038 (face-only) ===", flush=True)
        old_result = run_experiment(part3, direction, "Part3", label, cfg, undercuts)
        for r in old_result["results"]:
            if "error" in r:
                print(f"    {r['objective']:28s} ERROR: {r['error']}", flush=True)
            elif r.get("degenerate_cut"):
                print(f"    {r['objective']:28s} degenerate cut", flush=True)
            else:
                fr = r["feasibility"]
                print(f"    {r['objective']:28s} outcome={fr['outcome']:10s} failed_gate={str(fr['failed_gate']):5s} "
                      f"loops={r['loop_count']} cavity={r['cavity_face_count']} core={r['core_face_count']} "
                      f"h3={fr['measurements'].get('h3_region_count')} h4={fr['measurements'].get('h4_orientation_violation_fraction')}",
                      flush=True)

        print(f"=== Part3 @ {label} -- OPTION 2 (single-curve faces only) ===", flush=True)
        new_result = run_experiment_split(part3, direction, "Part3", label, cfg, undercuts, max_curves_per_split_face=1)
        print(f"    split_faces(total)={new_result['split_face_count']} histogram={new_result['curve_count_histogram']} "
              f"represented(1-curve)={new_result['curve_count_histogram'].get(1, 0)} "
              f"unsplit(2+curve)={new_result['split_face_count'] - new_result['curve_count_histogram'].get(1, 0)}",
              flush=True)
        report_run_option2(new_result)
        all_results["phase2_d038_vs_option2"].append({
            "direction_label": label, "old_d038": old_result, "option2": new_result,
        })

    print("\n########## PHASE 3 -- TRACK-B-HEAVY DIRECTIONS, OPTION 2 (chosen by measured activity, D-026) ##########", flush=True)
    for direction, label in [(unit((1, 0, 0)), "+X (highest measured Track-B count)"),
                              (unit((-1, 0, 0)), "-X (2nd highest measured Track-B count)"),
                              (unit((0, 1, 0)), "+Y (3rd highest measured Track-B count)")]:
        print(f"\n=== Part3 @ {label} -- OPTION 2 ===", flush=True)
        result = run_experiment_split(part3, direction, "Part3", label, cfg, undercuts, max_curves_per_split_face=1)
        print(f"    track_a={result['track_a_segment_count']} track_b={result['track_b_segment_count']} "
              f"split_faces(total)={result['split_face_count']} histogram={result['curve_count_histogram']}", flush=True)
        report_run_option2(result)
        all_results["phase3_track_b_heavy"].append(result)

    REPORTS_DIR.mkdir(exist_ok=True)
    out_path = REPORTS_DIR / "region_partition_option2.json"
    out_path.write_text(json.dumps(all_results, indent=2))
    print(f"\nDone. Full results in {out_path}", flush=True)


def main():
    cfg = settings.dfm.parting_line_v2
    undercuts = UndercutInput.empty()

    def unit(v):
        n = math.sqrt(sum(c * c for c in v))
        return tuple(c / n for c in v)

    print("Loading Part1.stp / Part3.stp ...", flush=True)
    part1 = load_step_cached("data/parts/Part1.stp")
    part3 = load_step_cached("data/parts/Part3.stp")
    print(f"Part1: {len(part1.faces)} faces, {len(part1.edges)} edges", flush=True)
    print(f"Part3: {len(part3.faces)} faces, {len(part3.edges)} edges", flush=True)

    az15 = unit((math.cos(math.radians(15)), math.sin(math.radians(15)), 0.0))

    jobs = [
        (part1, "Part1", unit((0.0, 0.0, 1.0)), "+Z (golden control)"),
        (part1, "Part1", unit((1.0, 0.0, 0.0)), "+X (known cycle-search failure)"),
        (part3, "Part3", az15, "equatorial az15 (D-036 strongest single loop, 73pct bbox)"),
        (part3, "Part3", unit((0.0, 1.0, 1.0)), "(0,1,1) CASE-A cluster anchor (D-033)"),
        (part3, "Part3", unit((1.0, 0.0, 0.0)), "+X (known cycle-search failure, D-026)"),
    ]

    all_results = []
    REPORTS_DIR.mkdir(exist_ok=True)
    out_path = REPORTS_DIR / "region_partition_prototype.json"
    for part, part_label, direction, direction_label in jobs:
        print(f"\n=== {part_label} @ {direction_label} ===", flush=True)
        t0 = time.time()
        result = run_experiment(part, direction, part_label, direction_label, cfg, undercuts)
        all_results.append(result)
        for r in result["results"]:
            if "error" in r:
                print(f"  {r['objective']:28s} ERROR: {r['error']}", flush=True)
            elif r.get("degenerate_cut"):
                print(f"  {r['objective']:28s} degenerate cut (no separation found)", flush=True)
            else:
                fr = r["feasibility"]
                print(
                    f"  {r['objective']:28s} outcome={fr['outcome']:10s} "
                    f"failed_gate={str(fr['failed_gate']):5s} loops={r['loop_count']} "
                    f"h3_region_count={fr['measurements'].get('h3_region_count')} "
                    f"h4_violation={fr['measurements'].get('h4_orientation_violation_fraction')}",
                    flush=True,
                )
        print(f"  ({time.time() - t0:.1f}s)", flush=True)
        out_path.write_text(json.dumps(all_results, indent=2))

    print(f"\nDone. Full results in {out_path}", flush=True)


if __name__ == "__main__":
    if "--subedge" in sys.argv:
        main_subedge()
    elif "--option1" in sys.argv:
        main_option1()
    elif "--option2" in sys.argv:
        main_option2()
    elif "--experiment1" in sys.argv:
        main_experiment_1()
    else:
        main()
