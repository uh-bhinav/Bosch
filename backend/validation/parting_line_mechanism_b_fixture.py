"""
backend/validation/parting_line_mechanism_b_fixture.py
------------------------------------------------------
Mechanism B (2026-08-14/15): minimal REAL-OCC fixture reproducing "a
single-face B-Rep edge is the boundary between two regions of that SAME
split face" -- the proven root cause (D-042-era forensic finding) of all 7
dangling degree-1 vertices at Part3 +X (clusters 24/76/78/80/87/92/156;
face38/edge123, face319/edge792, face35/edge112, face320/edge793,
face321/edge794, face37/edge118 -- same mechanism in every case).

READ-ONLY DIAGNOSTIC. No file under `backend/geometry/parting_line_v2/` or
`backend/validation/parting_line_region_partition_prototype.py` is
modified. The corrected graph-construction function lives entirely in this
file and is never wired into production.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import networkx as nx
from OCC.Core.BRep import BRep_Tool
from OCC.Core.TopAbs import TopAbs_EDGE
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopoDS import topods

import backend.validation.parting_line_face_partition as fp
import backend.validation.parting_line_region_partition_prototype as proto
from backend.geometry.parting_line_v2.types import CurveSegment, FaceBacking
from backend.models.geometry_models import EdgeData


# ============================================================
# Task 1 -- minimal real-OCC fixture
# ============================================================

def build_fixture(pull_direction=(0.0, 1.0, 0.0)):
    """
    Real OCC periodic cylinder (`_build_periodic_cylinder_fixture`, D-040's
    already-validated Fixture K base -- unmodified, reused as-is) plus ONE
    Track-B-style interior curve at u=pi splitting the lateral face into 2
    regions. Together with the face's own built-in seam (u=0 == u=2*pi),
    this reproduces exactly Part3 face 38's structure: 2 regions, one
    shared boundary is a real interior curve, the OTHER shared boundary is
    the face's own single-face seam edge.

    Pull direction (0,1,0) against a Z-axis cylinder gives g(u) = sin(u):
    strictly positive for u in (0, pi), strictly negative for u in
    (pi, 2*pi), and exactly zero at u=0 and u=pi -- i.e. both dividers
    (the interior curve at u=pi and the seam at u=0=2*pi) sit exactly on
    the sign change, GUARANTEEING the two regions land on opposite
    min-cut sides without needing to search for a direction empirically.
    """
    lateral, bottom, top = fp._build_periodic_cylinder_fixture()

    # Build a real MiniPart: full edge dedup across all 3 faces, proper
    # edge_to_faces / face_to_edges, exactly mirroring step_loader's own
    # TShape-based dedup convention.
    seen_edge_keys: dict = {}
    edges_by_id: dict[int, object] = {}
    face_to_edges: dict[int, list[int]] = {}
    edge_to_faces: dict[int, set[int]] = {}
    next_id = 0

    _HASH_MOD = 2**31 - 1  # matches step_loader.py's own edge-dedup convention exactly

    lateral_edge_occurrences: dict[int, int] = {}
    for face in (lateral, bottom, top):
        explorer = TopExp_Explorer(face.occ_face, TopAbs_EDGE)
        ids_here: list[int] = []
        while explorer.More():
            occ_edge = topods.Edge(explorer.Current())
            key = occ_edge.HashCode(_HASH_MOD)  # NOT TShape() -- that Python wrapper has no
            # stable __hash__/__eq__ across separate explorer calls (verified empirically: two
            # IsSame()-true occurrences of the true seam edge produced different TShape() dict
            # keys and failed to dedup). HashCode() is step_loader.py's own proven convention.
            if key not in seen_edge_keys:
                first, last = BRep_Tool.Range(occ_edge)
                curve, _f, _l = BRep_Tool.Curve(occ_edge)
                length = _curve_length(occ_edge, first, last)
                edges_by_id[next_id] = EdgeData(
                    edge_id=next_id, occ_edge=occ_edge, edge_type="Circle",
                    length=length, adjacent_face_ids=[],  # filled below
                    start_vertex=None, end_vertex=None, is_seam=False,
                )
                seen_edge_keys[key] = next_id
                next_id += 1
            eid = seen_edge_keys[key]
            if eid not in ids_here:
                ids_here.append(eid)
            edge_to_faces.setdefault(eid, set()).add(face.face_id)
            if face is lateral:
                lateral_edge_occurrences[eid] = lateral_edge_occurrences.get(eid, 0) + 1
            explorer.Next()
        face_to_edges[face.face_id] = ids_here

    # The seam: the one edge_id that appeared TWICE in the lateral face's
    # own wire traversal above (counted in the SAME pass -- a second,
    # independent TopExp_Explorer pass over the same face was tried first
    # and produced non-matching TShape() dict keys across passes; counting
    # within one pass avoids that pitfall entirely).
    seam_edge_id = next(eid for eid, count in lateral_edge_occurrences.items() if count == 2)

    for eid, edge in edges_by_id.items():
        edge.adjacent_face_ids[:] = sorted(edge_to_faces[eid])
    edges_by_id[seam_edge_id].is_seam = True

    class MiniPart:
        def __init__(self):
            self.faces = [lateral, bottom, top]
            self.edges = list(edges_by_id.values())
            self.face_to_edges = face_to_edges
            self.edge_to_faces = {k: sorted(v) for k, v in edge_to_faces.items()}

    part = MiniPart()

    # One interior Track-B-style curve at u=pi, spanning the lateral
    # face's own v-range, sampled via REAL S(u,v) evaluation (never
    # fitted/interpolated) -- same construction discipline production
    # Track-B segments use.
    surf = BRep_Tool.Surface(lateral.occ_face)
    u_min, u_max = lateral.u_range
    v_min, v_max = lateral.v_range
    u_mid = (u_min + u_max) / 2.0  # the periodic cylinder's own u_range is (0, 2*pi) -> mid = pi
    n = 12
    points = []
    uv = []
    for i in range(n):
        v = v_min + (v_max - v_min) * i / (n - 1)
        p = surf.Value(u_mid, v)
        points.append((p.X(), p.Y(), p.Z()))
        uv.append((u_mid, v))
    backing = FaceBacking(face_id=lateral.face_id, uv=tuple(uv))
    interior_curve = CurveSegment(segment_id=9000, points=tuple(points), backing=backing, kind="silhouette")

    return part, lateral, bottom, top, seam_edge_id, interior_curve, u_mid


def _curve_length(occ_edge, first, last):
    from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
    from OCC.Core.GCPnts import GCPnts_AbscissaPoint
    curve = BRepAdaptor_Curve(occ_edge)
    return GCPnts_AbscissaPoint.Length(curve, first, last)


# ============================================================
# Task 2 -- baseline (current, unmodified machinery) on the fixture
# ============================================================

def _seam_aware_regions(part, lateral, seam_edge_id, interior_curve):
    """
    `build_face_regions` samples each `part.face_to_edges[face_id]` entry
    ONCE, via a single stored `occ_edge` orientation per edge_id (matching
    production step_loader's own deduped `face_to_edges`, verified: real
    Part3 `face_to_edges[38]` lists edge 123 exactly once too). For a seam
    edge this silently drops HALF the boundary (only one of its two
    real, differently-oriented wire occurrences is ever sampled) --
    confirmed empirically: `_sample_edge_uv` given the two differently-
    ORIENTED `TopoDS_Edge` occurrences of the SAME seam returns two
    DIFFERENT uv lines (u=0 vs u=2*pi), proving both are real and
    necessary to close the boundary on both sides.

    This is a genuine, SEPARATE finding from the originally-scoped
    Mechanism B (missing cut PIECE) -- it is a missing REGION precursor,
    discovered while building this fixture. To isolate Mechanism B's own
    effect (Task 2 as specified), this helper supplies the COMPLETE
    boundary (both seam orientations, sampled directly from the face's own
    real wire traversal, not invented) directly to `partition_face_uv` --
    a production function, called with more complete real input, not
    reimplemented or modified.
    """
    explorer = TopExp_Explorer(lateral.occ_face, TopAbs_EDGE)
    boundary_lines = []
    outer_lines = []
    while explorer.More():
        occ_edge = topods.Edge(explorer.Current())

        class _E:
            pass
        fake = _E()
        fake.occ_edge = occ_edge
        line = fp._sample_edge_uv(lateral.occ_face, fake)
        if line is not None and line.length > 0:
            boundary_lines.append(line)
            outer_lines.append(line)
        explorer.Next()
    interior_lines = [proto.LineString(interior_curve.backing.uv)]
    u_min, u_max = lateral.u_range
    v_min, v_max = lateral.v_range
    span = max(u_max - u_min, v_max - v_min, 1e-9)
    regions = fp.partition_face_uv(boundary_lines, interior_lines, snap_grid=1e-6 * span)
    return [fp.FaceRegion(region_id=i, polygon=r.polygon, uv_area=r.uv_area) for i, r in enumerate(regions)]


def run_baseline():
    print("=== Task 1/2: fixture construction + baseline (current machinery) ===", flush=True)
    part, lateral, bottom, top, seam_edge_id, interior_curve, u_mid = build_fixture()

    print(f"seam_edge_id = {seam_edge_id}  (is_seam={part.edges[seam_edge_id].is_seam}, "
          f"adjacent_face_ids={part.edges[seam_edge_id].adjacent_face_ids})", flush=True)
    assert part.edges[seam_edge_id].is_seam
    assert part.edges[seam_edge_id].adjacent_face_ids == [lateral.face_id], \
        "fixture invariant: seam edge must have exactly 1 adjacent face"
    print("  [1] confirmed: len(adjacent_face_ids) == 1 for the seam edge", flush=True)

    regions_current = fp.build_face_regions(part, lateral, [interior_curve])
    print(f"  regions found by CURRENT build_face_regions: {len(regions_current)} "
          f"(expected 2 -- this is a related, separately-flagged 'missing region' "
          f"symptom of the SAME single-orientation-seam-sampling root cause; see report)",
          flush=True)
    for r in regions_current:
        print(f"    region {r.region_id}: bounds={r.polygon.bounds} area_uv={r.uv_area:.4f}", flush=True)

    regions = _seam_aware_regions(part, lateral, seam_edge_id, interior_curve)
    print(f"  regions found with COMPLETE (both-orientation) seam boundary sampling: {len(regions)}", flush=True)
    for r in regions:
        print(f"    region {r.region_id}: bounds={r.polygon.bounds} area_uv={r.uv_area:.4f}", flush=True)
    assert len(regions) == 2, f"expected 2 regions (1 interior curve + 1 seam), got {len(regions)}"
    print("  [2] confirmed: face DOES split into exactly 2 regions once the seam's full boundary is supplied",
          flush=True)

    direction = (0.0, 1.0, 0.0)
    sides = {}
    for r in regions:
        area_mm2, mean_g = fp.region_stats(lateral, r, direction)
        sides[r.region_id] = mean_g
        print(f"    region {r.region_id}: area={area_mm2:.4f}mm2 mean_g={mean_g:.6f}", flush=True)
    assert (sides[regions[0].region_id] > 0) != (sides[regions[1].region_id] > 0), \
        "fixture invariant: the two regions must have opposite-sign mean g"
    print("  [3] confirmed: the two regions have OPPOSITE sign mean_g (will land on opposite min-cut sides)",
          flush=True)

    # Build the min-cut graph exactly as production's build_min_cut_partition_nway_subedge
    # does (verbatim copy, see parting_line_mechanism_b_avsb.py for the same pattern).
    from backend.geometry.parting_line_v2.contracts import PullDirectionInput
    result = build_graph_current(part, PullDirectionInput(direction, "manual").direction,
                                  [interior_curve], frozenset(), unary_weight=1.0,
                                  smoothness_weight=0.10, silhouette_discount=0.10,
                                  face_regions_override={lateral.face_id: regions})

    node0, node1 = (lateral.face_id, regions[0].region_id), (lateral.face_id, regions[1].region_id)
    side0 = "cavity" if node0 in result["cavity_nodes"] else "core"
    side1 = "cavity" if node1 in result["cavity_nodes"] else "core"
    print(f"  min-cut assignment: {node0}={side0}  {node1}={side1}", flush=True)
    assert side0 != side1, "fixture invariant violated: regions ended up on the SAME min-cut side"
    print("  [3b] confirmed via full min-cut graph: regions are on OPPOSITE sides", flush=True)

    print(f"  [4] pair_edges construction reached for seam edge {seam_edge_id}? "
          f"{seam_edge_id in result['pair_edges_seen']}", flush=True)
    assert seam_edge_id not in result["pair_edges_seen"], \
        "expected CURRENT pair_edges construction to SKIP the seam edge (len(face_ids)==1)"
    print("  [5] confirmed: current pair_edges construction skips the seam edge (len(face_ids) != 2)", flush=True)

    print(f"  [6] sub_pieces for seam edge {seam_edge_id}: "
          f"{result['sub_pieces'].get(seam_edge_id, 'ABSENT')}", flush=True)
    assert seam_edge_id not in result["sub_pieces"], "expected NO cut piece for the seam edge under current logic"
    print("  [6] confirmed: NO cut piece generated for the seam edge -- required boundary is missing", flush=True)

    # [7] resulting graph exhibits dangling/incomplete topology: the interior
    # curve IS represented (a real split-face piece, since it's a Track-B
    # segment touching both regions), but nothing represents the seam-side
    # closure -- so the boundary loop cannot close.
    print(f"  interior-curve split_face_cut_count = {result['split_face_cut_count']}", flush=True)
    assert result["split_face_cut_count"] >= 1, "the interior curve itself should still be a cut piece"
    print("  [7] confirmed: the interior-curve piece IS present (correct), but the seam-side piece is "
          "MISSING -- the boundary has only 1 of its 2 required dividers, exactly Part3's failure mode",
          flush=True)

    print("\nBASELINE: all 7 assertions PASS -- Mechanism B fully reproduced on a minimal real-OCC fixture.\n",
          flush=True)
    return part, lateral, bottom, top, seam_edge_id, interior_curve, regions, result


def build_graph_current(part, direction, track_b_segments, silhouette_edge_ids,
                         *, unary_weight, smoothness_weight, silhouette_discount,
                         face_regions_override: dict | None = None):
    """Verbatim copy of build_min_cut_partition_nway_subedge's construction
    (same as parting_line_mechanism_b_avsb.build_graph_with_internals),
    extended only to also record which edge_ids reach the pair_edges loop
    body (pair_edges_seen) and split_face_cut_count, for assertion purposes.

    `face_regions_override` (fixture-only; production has no such
    parameter): substitutes the correctly-found (both-seam-orientation)
    regions for a face, isolating Mechanism B's own cut-piece-construction
    defect from the separate, upstream missing-region symptom (see
    `_seam_aware_regions`'s docstring) -- exactly so Task 2 tests ONE
    mechanism at a time, per the standing "narrow interpretation only"
    rule this project applies to every diagnostic experiment.
    """
    usable_faces = [f for f in part.faces if f.normal_valid]
    usable_ids = {f.face_id for f in usable_faces}
    faces_by_id = {f.face_id: f for f in usable_faces}

    track_b_by_face: dict[int, list] = {}
    for seg in track_b_segments:
        if isinstance(seg.backing, FaceBacking):
            track_b_by_face.setdefault(seg.backing.face_id, []).append(seg)

    face_regions: dict[int, list] = {}
    face_region_adjacency: dict[int, dict] = {}
    for face in usable_faces:
        if face_regions_override is not None and face.face_id in face_regions_override:
            regions = face_regions_override[face.face_id]
        else:
            segs = track_b_by_face.get(face.face_id, [])
            regions = fp.build_face_regions(part, face, segs)
        face_regions[face.face_id] = regions if regions else None
        if regions:
            face_region_adjacency[face.face_id] = fp.region_adjacency(regions)

    graph = nx.DiGraph()
    graph.add_node("S")
    graph.add_node("T")

    for face in usable_faces:
        regions = face_regions[face.face_id]
        if not regions:
            g = face.signed_dot(direction)
            node = (face.face_id, 0)
            graph.add_edge("S", node, capacity=unary_weight * face.area * max(0.0, g))
            graph.add_edge(node, "T", capacity=unary_weight * face.area * max(0.0, -g))
            continue
        for region in regions:
            area_mm2, mean_g = fp.region_stats(face, region, direction)
            node = (face.face_id, region.region_id)
            graph.add_edge("S", node, capacity=unary_weight * area_mm2 * max(0.0, mean_g))
            graph.add_edge(node, "T", capacity=unary_weight * area_mm2 * max(0.0, -mean_g))

    edges_by_id = {e.edge_id: e for e in part.edges}
    pair_edges: dict[tuple[int, int], list[int]] = {}
    for edge_id, face_ids in part.edge_to_faces.items():
        if len(face_ids) != 2:
            continue
        a, b = sorted(face_ids)
        if a not in usable_ids or b not in usable_ids:
            continue
        pair_edges.setdefault((a, b), []).append(edge_id)

    pair_edges_seen = {eid for ids in pair_edges.values() for eid in ids}
    sub_pieces: dict[int, list[tuple]] = {}
    edge_capacity: dict[tuple, float] = {}
    for (a, b), edge_ids in pair_edges.items():
        for edge_id in edge_ids:
            edge = edges_by_id.get(edge_id)
            if edge is None:
                continue
            intervals = fp.edge_subinterval_attachment(
                faces_by_id[a], faces_by_id[b], edge, face_regions[a], face_regions[b]
            )
            if not intervals:
                continue
            discount = silhouette_discount if edge_id in silhouette_edge_ids else 1.0
            for iv in intervals:
                na, nb = (a, iv.region_a), (b, iv.region_b)
                sub_pieces.setdefault(edge_id, []).append((iv.t_start, iv.t_end, na, nb))
                key = tuple(sorted((na, nb), key=str))
                span_fraction = abs(iv.t_end - iv.t_start) / max(
                    abs(BRep_Tool.Range(edge.occ_edge)[1] - BRep_Tool.Range(edge.occ_edge)[0]), 1e-12
                )
                weight = smoothness_weight * edge.length * span_fraction * discount
                if weight <= 0.0:
                    continue
                edge_capacity[key] = edge_capacity.get(key, 0.0) + weight

    split_face_cut_count = 0
    cut_value, (reachable, non_reachable) = nx.minimum_cut(
        _finish_graph(graph, edge_capacity), "S", "T", capacity="capacity"
    )
    cavity_nodes = frozenset(n for n in reachable if n not in ("S", "T"))
    core_nodes = frozenset(n for n in non_reachable if n not in ("S", "T"))

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
                from shapely.geometry import LineString as _LS
                region_a = next(r for r in regions if r.region_id == ra)
                region_b = next(r for r in regions if r.region_id == rb)
                for seg in segs:
                    if len(seg.backing.uv) < 2:
                        continue
                    line = _LS(seg.backing.uv)
                    touches_a = region_a.polygon.boundary.intersection(line).length > 0
                    touches_b = region_b.polygon.boundary.intersection(line).length > 0
                    if touches_a and touches_b:
                        split_face_cut_count += 1

    return {
        "cavity_nodes": cavity_nodes, "core_nodes": core_nodes,
        "sub_pieces": sub_pieces, "face_regions": face_regions,
        "pair_edges_seen": pair_edges_seen, "split_face_cut_count": split_face_cut_count,
        "face_region_adjacency": face_region_adjacency,
    }


def _finish_graph(graph, edge_capacity):
    for (na, nb), cap in edge_capacity.items():
        graph.add_edge(na, nb, capacity=cap)
        graph.add_edge(nb, na, capacity=cap)
    return graph


# ============================================================
# Task 3 -- the smallest general fix
# ============================================================

def same_face_seam_subintervals(part, face, seam_edge_id, regions):
    """
    The missing construction path (Task 3). Generates sub-interval pieces
    for a SINGLE-FACE edge that is the boundary between two REGIONS of
    that SAME face -- the exact case `pair_edges` (which requires
    `len(face_ids) == 2`) cannot represent.

    Design, and why it is the minimal correct abstraction (not "remove
    len(face_ids) != 2", which the task explicitly warned against):
    `edge_subinterval_attachment(face_a, face_b, edge, regions_a,
    regions_b)` already does EXACTLY the right thing -- split a shared
    edge wherever region membership changes, on EACH side independently --
    provided it is given the correct UV sample for each "side". For a
    cross-face edge, "each side" naturally means face_a's own pcurve vs
    face_b's own pcurve, which is already correct. For a single-face seam
    edge, "each side" means the SAME face's own TWO pcurves for the edge's
    two different ORIENTED occurrences in that face's own wire (verified
    directly: `_sample_edge_uv` given the forward- vs reversed-orientation
    `TopoDS_Edge` for the SAME seam returns two DIFFERENT uv lines, u=0 vs
    u=2*pi on the fixture). So the fix is NOT a new topology (no second
    face is invented, `edge_to_faces` is not touched) -- it is recognizing
    that a single-face edge referenced twice in ITS OWN face's wire
    supplies the same two-sided information a cross-face edge supplies via
    two different faces, and both region endpoints of every resulting
    piece correctly reference THIS face's own region nodes:
    `(face_id, ra)` and `(face_id, rb)`.

    Returns a list of (t_start, t_end, region_a, region_b) tuples, exactly
    matching `sub_pieces[edge_id]`'s existing element shape elsewhere in
    this file, so no downstream consumer needs new logic to use them.
    """
    _HASH_MOD = 2**31 - 1
    edges_by_id = {e.edge_id: e for e in part.edges}
    edge = edges_by_id[seam_edge_id]
    target_hash = edge.occ_edge.HashCode(_HASH_MOD)

    explorer = TopExp_Explorer(face.occ_face, TopAbs_EDGE)
    occurrences = []
    while explorer.More():
        occ_edge = topods.Edge(explorer.Current())
        if occ_edge.HashCode(_HASH_MOD) == target_hash:
            occurrences.append(occ_edge)
        explorer.Next()
    if len(occurrences) != 2:
        return []  # not a genuine same-face-twice seam on this face -- nothing to do

    class _E:
        pass
    fake_a, fake_b = _E(), _E()
    fake_a.occ_edge, fake_b.occ_edge = occurrences[0], occurrences[1]
    line_a = fp._sample_edge_uv(face.occ_face, fake_a)
    line_b = fp._sample_edge_uv(face.occ_face, fake_b)
    if line_a is None or line_b is None or line_a.length == 0 or line_b.length == 0:
        return []

    bp_a = fp.edge_region_breakpoints(line_a, regions or [])
    bp_b = fp.edge_region_breakpoints(line_b, regions or [])
    raw_breakpoints = sorted(set(bp_a) | set(bp_b))
    _MERGE_TOL = 1e-4  # same constant, same justification as edge_subinterval_attachment
    breakpoints: list[float] = []
    for bp in raw_breakpoints:
        if breakpoints and bp - breakpoints[-1] < _MERGE_TOL:
            continue
        breakpoints.append(bp)

    first, last = BRep_Tool.Range(edge.occ_edge)
    pieces = []
    for i in range(len(breakpoints) - 1):
        n0, n1 = breakpoints[i], breakpoints[i + 1]
        if n1 - n0 < _MERGE_TOL:
            continue
        mid = (n0 + n1) / 2.0
        ra = fp.region_for_point(regions or [], line_a.interpolate(mid, normalized=True))
        rb = fp.region_for_point(regions or [], line_b.interpolate(mid, normalized=True))
        pieces.append((first + n0 * (last - first), first + n1 * (last - first), ra, rb))
    return pieces


def build_graph_fixed(part, direction, track_b_segments, silhouette_edge_ids,
                       *, unary_weight, smoothness_weight, silhouette_discount,
                       face_regions_override: dict | None = None):
    """`build_graph_current` + the Task 3 correction wired in BEFORE the
    min-cut solve (the smoothness cost of a same-face seam piece must be
    part of the graph the cut is computed over, not added after -- exactly
    like every existing cross-face smoothness edge)."""
    usable_faces = [f for f in part.faces if f.normal_valid]
    usable_ids = {f.face_id for f in usable_faces}
    faces_by_id = {f.face_id: f for f in usable_faces}

    track_b_by_face: dict[int, list] = {}
    for seg in track_b_segments:
        if isinstance(seg.backing, FaceBacking):
            track_b_by_face.setdefault(seg.backing.face_id, []).append(seg)

    face_regions: dict[int, list] = {}
    face_region_adjacency: dict[int, dict] = {}
    for face in usable_faces:
        if face_regions_override is not None and face.face_id in face_regions_override:
            regions = face_regions_override[face.face_id]
        else:
            segs = track_b_by_face.get(face.face_id, [])
            regions = fp.build_face_regions(part, face, segs)
        face_regions[face.face_id] = regions if regions else None
        if regions:
            face_region_adjacency[face.face_id] = fp.region_adjacency(regions)

    graph = nx.DiGraph()
    graph.add_node("S")
    graph.add_node("T")
    for face in usable_faces:
        regions = face_regions[face.face_id]
        if not regions:
            g = face.signed_dot(direction)
            node = (face.face_id, 0)
            graph.add_edge("S", node, capacity=unary_weight * face.area * max(0.0, g))
            graph.add_edge(node, "T", capacity=unary_weight * face.area * max(0.0, -g))
            continue
        for region in regions:
            area_mm2, mean_g = fp.region_stats(face, region, direction)
            node = (face.face_id, region.region_id)
            graph.add_edge("S", node, capacity=unary_weight * area_mm2 * max(0.0, mean_g))
            graph.add_edge(node, "T", capacity=unary_weight * area_mm2 * max(0.0, -mean_g))

    edges_by_id = {e.edge_id: e for e in part.edges}
    pair_edges: dict[tuple[int, int], list[int]] = {}
    for edge_id, face_ids in part.edge_to_faces.items():
        if len(face_ids) != 2:
            continue
        a, b = sorted(face_ids)
        if a not in usable_ids or b not in usable_ids:
            continue
        pair_edges.setdefault((a, b), []).append(edge_id)

    pair_edges_seen = {eid for ids in pair_edges.values() for eid in ids}
    sub_pieces: dict[int, list[tuple]] = {}
    edge_capacity: dict[tuple, float] = {}

    for (a, b), edge_ids in pair_edges.items():
        for edge_id in edge_ids:
            edge = edges_by_id.get(edge_id)
            if edge is None:
                continue
            intervals = fp.edge_subinterval_attachment(
                faces_by_id[a], faces_by_id[b], edge, face_regions[a], face_regions[b]
            )
            if not intervals:
                continue
            discount = silhouette_discount if edge_id in silhouette_edge_ids else 1.0
            for iv in intervals:
                na, nb = (a, iv.region_a), (b, iv.region_b)
                sub_pieces.setdefault(edge_id, []).append((iv.t_start, iv.t_end, na, nb))
                key = tuple(sorted((na, nb), key=str))
                span_fraction = abs(iv.t_end - iv.t_start) / max(
                    abs(BRep_Tool.Range(edge.occ_edge)[1] - BRep_Tool.Range(edge.occ_edge)[0]), 1e-12
                )
                weight = smoothness_weight * edge.length * span_fraction * discount
                if weight <= 0.0:
                    continue
                edge_capacity[key] = edge_capacity.get(key, 0.0) + weight

    # --- Task 3 correction: single-face (len(face_ids)==1) edges that are
    # a region boundary of their own face. ---
    same_face_seam_edges_seen = set()
    for edge_id, face_ids in part.edge_to_faces.items():
        if len(face_ids) != 1:
            continue
        if edge_id not in usable_ids and face_ids[0] not in usable_ids:
            continue
        face_id = face_ids[0]
        if face_id not in usable_ids:
            continue
        regions = face_regions.get(face_id)
        if not regions or len(regions) < 2:
            continue  # unsplit face -- a single-face edge here is an ordinary boundary, not a region divider
        pieces = same_face_seam_subintervals(part, faces_by_id[face_id], edge_id, regions)
        if not pieces:
            continue
        same_face_seam_edges_seen.add(edge_id)
        edge = edges_by_id[edge_id]
        discount = silhouette_discount if edge_id in silhouette_edge_ids else 1.0
        for (t_start, t_end, ra, rb) in pieces:
            if ra == rb:
                continue  # both sides in the same region -- not a divider at this sub-interval
            na, nb = (face_id, ra), (face_id, rb)
            sub_pieces.setdefault(edge_id, []).append((t_start, t_end, na, nb))
            key = tuple(sorted((na, nb), key=str))
            span_fraction = abs(t_end - t_start) / max(
                abs(BRep_Tool.Range(edge.occ_edge)[1] - BRep_Tool.Range(edge.occ_edge)[0]), 1e-12
            )
            weight = smoothness_weight * edge.length * span_fraction * discount
            if weight <= 0.0:
                continue
            edge_capacity[key] = edge_capacity.get(key, 0.0) + weight

    cut_value, (reachable, non_reachable) = nx.minimum_cut(
        _finish_graph(graph, edge_capacity), "S", "T", capacity="capacity"
    )
    cavity_nodes = frozenset(n for n in reachable if n not in ("S", "T"))
    core_nodes = frozenset(n for n in non_reachable if n not in ("S", "T"))

    # Final cut-piece selection: same rule as production (opposite sides),
    # applied uniformly to cross-face AND same-face-seam sub_pieces.
    cut_pieces: list[dict] = []
    for edge_id, intervals in sub_pieces.items():
        for (t_start, t_end, na, nb) in intervals:
            if (na in cavity_nodes) != (nb in cavity_nodes):
                cut_pieces.append({"kind": "edge", "edge_id": edge_id, "t_start": t_start, "t_end": t_end,
                                    "region_a": na, "region_b": nb})

    # Split-face (Track-B interior curve) cut pieces -- IDENTICAL to
    # production's own logic in build_min_cut_partition_nway_subedge,
    # unaffected by the Task 3 correction (that correction only concerns
    # B-Rep EDGE pieces, never Track-B face-interior curve pieces).
    from shapely.geometry import LineString as _LS
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
                    line = _LS(seg.backing.uv)
                    touches_a = region_a.polygon.boundary.intersection(line).length > 0
                    touches_b = region_b.polygon.boundary.intersection(line).length > 0
                    if touches_a and touches_b:
                        cut_pieces.append({"kind": "face", "face_id": face_id, "segment": seg})
                        split_face_cut_count += 1

    return {
        "cavity_nodes": cavity_nodes, "core_nodes": core_nodes,
        "sub_pieces": sub_pieces, "face_regions": face_regions,
        "pair_edges_seen": pair_edges_seen, "same_face_seam_edges_seen": same_face_seam_edges_seen,
        "cut_pieces": cut_pieces, "split_face_cut_count": split_face_cut_count,
        "cavity_face_ids": frozenset(n[0] for n in cavity_nodes),
        "core_face_ids": frozenset(n[0] for n in core_nodes),
        "cut_value": cut_value,
    }


def run_fix_validation():
    print("\n=== Task 3/4: fix design + fixture validation ===", flush=True)
    part, lateral, bottom, top, seam_edge_id, interior_curve, u_mid = build_fixture()
    regions = _seam_aware_regions(part, lateral, seam_edge_id, interior_curve)
    assert len(regions) == 2

    from backend.geometry.parting_line_v2.contracts import PullDirectionInput
    direction = PullDirectionInput((0.0, 1.0, 0.0), "manual").direction
    result = build_graph_fixed(
        part, direction, [interior_curve], frozenset(), unary_weight=1.0,
        smoothness_weight=0.10, silhouette_discount=0.10,
        face_regions_override={lateral.face_id: regions},
    )

    print(f"  same_face_seam_edges_seen: {result['same_face_seam_edges_seen']}", flush=True)
    assert seam_edge_id in result["same_face_seam_edges_seen"], \
        "FIX FAILED: same-face seam construction path was not reached for the seam edge"
    print("  [A] confirmed: the seam edge is now reached by the same-face construction path", flush=True)

    seam_pieces = result["sub_pieces"].get(seam_edge_id, [])
    print(f"  seam_edge sub_pieces: {seam_pieces}", flush=True)
    assert len(seam_pieces) >= 1, "FIX FAILED: no sub-interval generated for the seam edge"
    print("  [B] confirmed: the seam edge now has at least one sub-interval piece", flush=True)

    node0 = (lateral.face_id, regions[0].region_id)
    node1 = (lateral.face_id, regions[1].region_id)
    seam_cut_pieces = [p for p in result["cut_pieces"] if p.get("edge_id") == seam_edge_id]
    print(f"  seam_edge cut_pieces (opposite-side, i.e. required): {seam_cut_pieces}", flush=True)
    assert len(seam_cut_pieces) >= 1, "FIX FAILED: the seam's required cut piece is still absent"
    for p in seam_cut_pieces:
        assert {p["region_a"], p["region_b"]} == {node0, node1}, \
            f"FIX WRONG: seam cut piece references unexpected nodes {p['region_a']}, {p['region_b']}"
    print("  [C] confirmed: the seam's cut piece correctly references THIS face's own two region nodes "
          f"({node0}, {node1}) -- no artificial face invented", flush=True)

    # No duplicate/artificial piece: exactly as many seam cut pieces as
    # there are real breakpoint-bounded sub-intervals with opposite sides
    # (1, for this fixture -- the seam is a single clean divider, no
    # interior Track-B curve crosses it).
    assert len(seam_cut_pieces) == 1, \
        f"FIX WRONG: expected exactly 1 seam cut piece for this fixture, got {len(seam_cut_pieces)}"
    print("  [D] confirmed: exactly 1 seam cut piece -- no duplicate/artificial piece created", flush=True)

    interior_cut_pieces = [p for p in result["cut_pieces"]
                            if p.get("edge_id") != seam_edge_id]
    print(f"  non-seam cut pieces (interior curve's own sub-edge attachments, if any): "
          f"{len(interior_cut_pieces)}", flush=True)

    # Region topology unchanged: still exactly 2 regions, same bounds/areas
    # as before the fix (the fix only adds a missing PIECE, it does not
    # alter region-finding).
    assert result["face_regions"][lateral.face_id] is regions, \
        "region topology must be untouched by this fix (same object, same 2 regions)"
    print("  [E] confirmed: region topology (2 regions) is unchanged by this fix", flush=True)

    print("\nFIX VALIDATION: all assertions PASS on the fixture.\n", flush=True)
    return result


# ============================================================
# Task 5 -- Part1 regression (real part, real production pipeline
# downstream of graph construction: _resolve_piece_geometry,
# _weld_piece_endpoints, decompose_pieces_into_loops,
# assemble_candidate_from_pieces, evaluate_gates -- all UNCHANGED,
# imported directly from proto / gates, never reimplemented).
# ============================================================

GOLDEN_PART1_PLUS_Z = {
    "cavity_face_count": 42, "core_face_count": 269,
    "cavity_area_mm2": 362.338, "core_area_mm2": 1203.814,
    "h3_region_count": 2.0, "h4_orientation_violation_fraction": 0.0,
    "h7_coverage": 0.9991608536203086,
    "is_single_continuous_loop": True, "h1_closure_error_mm": 0.0,
}


def _run_candidate(part, direction_tuple, cfg, undercuts, builder):
    from dataclasses import replace as _replace

    from backend.geometry.parting_line_v2.contracts import PullDirectionInput
    from backend.geometry.parting_line_v2.track_a import detect_edge_silhouettes
    from backend.geometry.parting_line_v2.track_b import detect_face_silhouettes
    from backend.geometry.parting_line_v2.types import EdgeBacking

    direction = PullDirectionInput(direction_tuple, "manual").direction
    bbox_diag = proto._bbox_diagonal(part)
    track_a = detect_edge_silhouettes(part, direction, cfg=cfg, bbox_diagonal_mm=bbox_diag)
    silhouette_edge_ids = frozenset(
        s.backing.edge_id for s in track_a.segments
        if s.kind == "silhouette" and isinstance(s.backing, EdgeBacking)
    )
    track_b = detect_face_silhouettes(part, direction, cfg=cfg, bbox_diagonal_mm=bbox_diag,
                                       start_segment_id=len(track_a.segments))
    valid_faces = [f for f in part.faces if f.normal_valid]
    part_projected_area = proto.measures.cauchy_projected_area(
        [f.area for f in valid_faces],
        [proto.mean_abs_g(f, direction, cfg.face_sample_grid) for f in valid_faces],
    )
    face_weld_cell = max(cfg.stitch_snap_tolerance_rel * bbox_diag, 1e-6)

    results = {}
    for obj_name, (unary_w, smooth_w, discount) in proto.OBJECTIVES.items():
        cut = builder(part, direction, track_b.segments, silhouette_edge_ids,
                      unary_weight=unary_w, smoothness_weight=smooth_w, silhouette_discount=discount)
        if cut is None or not cut["cut_pieces"]:
            results[obj_name] = {"degenerate": True}
            continue
        resolved_pieces = [proto._resolve_piece_geometry(part, p) for p in cut["cut_pieces"]]
        clusters = proto._weld_piece_endpoints(resolved_pieces, face_weld_cell)
        walks, decomp_notes = proto.decompose_pieces_into_loops(resolved_pieces, clusters)
        candidate = proto.assemble_candidate_from_pieces(
            resolved_pieces, clusters, walks, candidate_id=940000 + hash(obj_name) % 1000
        )
        if candidate is None:
            results[obj_name] = {"error": "could not assemble", "notes": decomp_notes}
            continue
        outcome = proto.evaluate_gates(candidate, part, direction, undercuts=undercuts, cfg=cfg,
                                  bbox_diagonal_mm=bbox_diag, part_projected_area_mm2=part_projected_area)
        candidate = _replace(candidate, feasibility=outcome.report)
        areas = None
        if outcome.regions is not None:
            areas = {"cavity_area_mm2": round(outcome.regions.cavity_area_mm2, 3),
                      "core_area_mm2": round(outcome.regions.core_area_mm2, 3)}
        results[obj_name] = {
            "cavity_face_count": len(cut["cavity_face_ids"]), "core_face_count": len(cut["core_face_ids"]),
            "region_areas": areas, "loop_count": len(walks), "is_single_continuous_loop": len(walks) == 1,
            "feasibility": outcome.report.to_dict(),
        }
    return results


def _fingerprint(r: dict) -> dict:
    fr = r["feasibility"]
    areas = r.get("region_areas") or {}
    return {
        "cavity_face_count": r["cavity_face_count"], "core_face_count": r["core_face_count"],
        "cavity_area_mm2": areas.get("cavity_area_mm2"), "core_area_mm2": areas.get("core_area_mm2"),
        "h3_region_count": fr["measurements"].get("h3_region_count"),
        "h4_orientation_violation_fraction": fr["measurements"].get("h4_orientation_violation_fraction"),
        "h7_coverage": fr["measurements"].get("h7_coverage"),
        "is_single_continuous_loop": r["is_single_continuous_loop"],
        "h1_closure_error_mm": fr["measurements"].get("h1_closure_error_mm"),
        "outcome": fr["outcome"], "failed_gate": fr["failed_gate"],
    }


def run_part1_regression():
    print("\n=== Task 5: Part1 +Z/+X regression, CURRENT vs FIXED graph construction ===", flush=True)
    from backend.config import settings
    from backend.geometry.parting_line_v2.contracts import UndercutInput
    from backend.geometry.step_loader import load_step_cached

    cfg = settings.dfm.parting_line_v2
    undercuts = UndercutInput.empty()
    part1 = load_step_cached("data/parts/Part1.stp")

    def unit(v):
        n = math.sqrt(sum(c * c for c in v))
        return tuple(c / n for c in v)

    all_match = True
    golden_match = None
    for direction, label in [(unit((0, 0, 1)), "+Z"), (unit((1, 0, 0)), "+X")]:
        current = _run_candidate(part1, direction, cfg, undercuts, proto.build_min_cut_partition_nway_subedge)
        fixed = _run_candidate(part1, direction, cfg, undercuts, build_graph_fixed)
        for obj_name in proto.OBJECTIVES:
            cr, fr = current.get(obj_name), fixed.get(obj_name)
            if cr is None or fr is None or "degenerate" in cr or "degenerate" in fr or "error" in cr or "error" in fr:
                print(f"  Part1 {label} / {obj_name}: unusable (current={cr}, fixed={fr})", flush=True)
                continue
            cfp, ffp = _fingerprint(cr), _fingerprint(fr)
            match = cfp == ffp
            all_match = all_match and match
            print(f"  Part1 {label} / {obj_name}: {'IDENTICAL' if match else 'DIFFERS'}", flush=True)
            if not match:
                for k in cfp:
                    if cfp[k] != ffp[k]:
                        print(f"      {k}: current={cfp[k]!r} fixed={ffp[k]!r}", flush=True)
            if label == "+Z" and obj_name == "C_balanced_low":
                golden_check = {k: ffp[k] for k in GOLDEN_PART1_PLUS_Z}
                golden_match = golden_check == GOLDEN_PART1_PLUS_Z
                print(f"      vs GOLDEN fingerprint: {'MATCH' if golden_match else 'MISMATCH'}", flush=True)
                if not golden_match:
                    for k in GOLDEN_PART1_PLUS_Z:
                        if golden_check[k] != GOLDEN_PART1_PLUS_Z[k]:
                            print(f"        {k}: golden={GOLDEN_PART1_PLUS_Z[k]!r} fixed={golden_check[k]!r}",
                                  flush=True)
    print(f"\nPart1 regression: {'ALL IDENTICAL' if all_match else 'SOME DIFFERENCES'}, "
          f"golden +Z/C_balanced_low fingerprint {'MATCHES' if golden_match else 'DOES NOT MATCH'}", flush=True)
    return all_match, golden_match


# ============================================================
# Task 6 -- Part3 +X-only rerun (causal measurement, not a broad sweep)
# ============================================================

def run_part3_plus_x_only():
    print("\n=== Task 6: Part3 +X only -- CURRENT vs FIXED, causal measurement ===", flush=True)
    from backend.config import settings
    from backend.geometry.parting_line_v2.contracts import UndercutInput
    from backend.geometry.step_loader import load_step_cached
    import backend.validation.parting_line_odd_degree_trace as odd_trace

    cfg = settings.dfm.parting_line_v2
    undercuts = UndercutInput.empty()
    part3 = load_step_cached("data/parts/Part3.stp")

    def unit(v):
        n = math.sqrt(sum(c * c for c in v))
        return tuple(c / n for c in v)

    direction = unit((1, 0, 0))

    # odd-degree count before/after, at C_balanced_low (matches all prior reporting)
    original_builder = proto.build_min_cut_partition_nway_subedge
    odd_before = odd_trace.run_direction(part3, direction, cfg, undercuts, "+X (CURRENT)")
    proto.build_min_cut_partition_nway_subedge = build_graph_fixed
    try:
        odd_after = odd_trace.run_direction(part3, direction, cfg, undercuts, "+X (FIXED)")
    finally:
        proto.build_min_cut_partition_nway_subedge = original_builder

    before_ids = {v["cluster_id"] for v in odd_before}
    after_points = {v["representative_point"] for v in odd_after}
    before_points = {v["representative_point"] for v in odd_before}
    known_7_points = {
        (-9.08605, 8.5845, 22.0), (6.0, 0.0, 39.0), (-6.0, 0.0, 39.0), (-7.0, 0.0, 0.0),
        (-17.0, -0.0, 0.0), (-18.0, -0.0, 4.0), (7.0, 0.0, 40.0),
    }
    print(f"\nodd-degree count: before={len(odd_before)} after={len(odd_after)}", flush=True)
    print(f"known-7 points still present after fix: {known_7_points & after_points} "
          f"(should be EMPTY if the fix works as designed)", flush=True)
    print(f"new odd-degree points not in the before set: {after_points - before_points}", flush=True)

    # Full gate outcome, current vs fixed, all 5 objectives
    current = _run_candidate(part3, direction, cfg, undercuts, proto.build_min_cut_partition_nway_subedge)
    fixed = _run_candidate(part3, direction, cfg, undercuts, build_graph_fixed)
    for obj_name in proto.OBJECTIVES:
        cr, fr = current.get(obj_name), fixed.get(obj_name)

        def _line(tag, r):
            if r is None:
                return f"    {tag} {obj_name:22s} MISSING"
            if "degenerate" in r:
                return f"    {tag} {obj_name:22s} degenerate cut"
            if "error" in r:
                return f"    {tag} {obj_name:22s} ERROR: {r['error']}"
            fr_ = r["feasibility"]
            areas = r.get("region_areas") or {}
            return (f"    {tag} {obj_name:22s} outcome={fr_['outcome']:10s} failed_gate={str(fr_['failed_gate']):5s} "
                    f"loops={r['loop_count']} cavity={r['cavity_face_count']} core={r['core_face_count']} "
                    f"cavity_mm2={areas.get('cavity_area_mm2')} core_mm2={areas.get('core_area_mm2')} "
                    f"h1={fr_['measurements'].get('h1_closure_error_mm')} h3={fr_['measurements'].get('h3_region_count')} "
                    f"h4={fr_['measurements'].get('h4_orientation_violation_fraction')} "
                    f"h7={fr_['measurements'].get('h7_coverage')}")

        print(_line("CURRENT", cr), flush=True)
        print(_line("FIXED  ", fr), flush=True)


if __name__ == "__main__":
    run_baseline()
    run_fix_validation()
    all_match, golden_match = run_part1_regression()
    if all_match and golden_match:
        run_part3_plus_x_only()
    else:
        print("\nSTOPPING before Task 6 -- Part1 regression did not pass cleanly.", flush=True)
