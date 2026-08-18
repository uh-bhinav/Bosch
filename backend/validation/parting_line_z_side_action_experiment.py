"""
backend/validation/parting_line_z_side_action_experiment.py
------------------------------------------------------
Z side-action-aware PL interface validation (2026-08-16). Tests whether
`side_core_face_ids` (the existing, already-implemented "Formulation B"
mechanism in build_min_cut_partition_nway_subedge) correctly represents
"this geometrically-justified region is released by an independent
secondary movement, not the primary two-way split" for the CONFIRMED
Z-direction radial-trapping region (alternating-radius rib sectors,
faces 0-16), as opposed to an arbitrary/unjustified face exclusion.

READ-ONLY DIAGNOSTIC. Mechanism B (`parting_line_mechanism_b_fixture.
build_graph_fixed`) is used UNMODIFIED, imported and wrapped -- never
edited. No production code touched.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import networkx as nx
from OCC.Core.BRep import BRep_Tool

import backend.validation.parting_line_face_partition as fp
import backend.validation.parting_line_mechanism_b_fixture as mb
import backend.validation.parting_line_region_partition_prototype as proto
from backend.geometry.parting_line_v2.types import FaceBacking

# ============================================================
# A. Geometrically justified side-action face set
# ============================================================

# Faces 0,2,4,6: the alternating-radius (12.5/9.5mm) cylindrical sectors
# themselves -- the DIRECTLY measured trapped geometry.
CYLINDER_FACES = frozenset({0, 2, 4, 6})

# Faces 1,3,5,7: the flat annular "shoulder" planes at each radius
# transition. These are NOT independently movable from the cylinders --
# they ARE the radius-change surfaces, rigidly continuous with the same
# stack. Excluding the cylinders but not their own transition shoulders
# would not correspond to any coherent physical movement.
SHOULDER_FACES = frozenset({1, 3, 5, 7})

# Faces 8-16: confirmed via direct adjacency query (part.face_adjacency)
# to be the ONLY faces directly connecting consecutive members of
# {0..7} to each other (each is adjacent to exactly two of them, e.g.
# face 13 -> {1,2}, face 12 -> {2,3}, etc.) -- 0.5mm-minor-radius blend
# fillets. A secondary movement that extracted the cylinders/shoulders
# but left these fillets attached to the "wrong" side would be
# geometrically incoherent (a gap or a duplicate sliver); they are
# necessary members of the same rigid secondary-action region.
FILLET_FACES = frozenset({8, 9, 10, 11, 12, 13, 14, 15, 16})

JUSTIFIED_SIDE_ACTION_FACES = CYLINDER_FACES | SHOULDER_FACES | FILLET_FACES
assert len(JUSTIFIED_SIDE_ACTION_FACES) == 17

# Explicitly EXCLUDED, and why: faces 329-338 (and their neighbors
# 369-385) are a SEPARATE small local feature -- each of 0-7 is also
# adjacent to one of them, but they were not part of the CONFIRMED
# radius-alternation measurement (they are a distinct sub-mm^2-scale
# structure at a specific angular position). Per the explicit
# instruction not to include faces merely because they are near the rib,
# they are left OUT of the justified set. (They remain the open Type-1/
# Type-2 question, untouched by this experiment.)


def build_graph_z_side_action(part, direction, track_b_segments, silhouette_edge_ids,
                               *, unary_weight, smoothness_weight, silhouette_discount,
                               side_core_face_ids=frozenset(), face_regions_override=None):
    """
    Mechanism B's `build_graph_fixed`, UNMODIFIED in every respect except
    one addition: faces in `side_core_face_ids` get zero unary (S/T)
    cost, exactly matching production's own already-implemented
    `side_core_face_ids` semantics in `build_min_cut_partition_nway_subedge`
    (P3.19) -- they remain full graph nodes, still subject to H3's
    whole-part topology requirement and to every cross-face/same-face
    smoothness edge unchanged; only their OWN primary orientation-
    consistency requirement is relaxed. This is a verbatim copy of
    `build_graph_fixed`'s body with that one substitution, not a new
    mechanism.
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
        face_unary_weight = 0.0 if face.face_id in side_core_face_ids else unary_weight
        regions = face_regions[face.face_id]
        if not regions:
            g = face.signed_dot(direction)
            node = (face.face_id, 0)
            graph.add_edge("S", node, capacity=face_unary_weight * face.area * max(0.0, g))
            graph.add_edge(node, "T", capacity=face_unary_weight * face.area * max(0.0, -g))
            continue
        for region in regions:
            area_mm2, mean_g = fp.region_stats(face, region, direction)
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

    same_face_seam_edges_seen = set()
    for edge_id, face_ids in part.edge_to_faces.items():
        if len(face_ids) != 1:
            continue
        face_id = face_ids[0]
        if face_id not in usable_ids:
            continue
        regions = face_regions.get(face_id)
        if not regions or len(regions) < 2:
            continue
        pieces = mb.same_face_seam_subintervals(part, faces_by_id[face_id], edge_id, regions)
        if not pieces:
            continue
        same_face_seam_edges_seen.add(edge_id)
        edge = edges_by_id[edge_id]
        discount = silhouette_discount if edge_id in silhouette_edge_ids else 1.0
        for (t_start, t_end, ra, rb) in pieces:
            if ra == rb:
                continue
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
        mb._finish_graph(graph, edge_capacity), "S", "T", capacity="capacity"
    )
    cavity_nodes = frozenset(n for n in reachable if n not in ("S", "T"))
    core_nodes = frozenset(n for n in non_reachable if n not in ("S", "T"))

    cut_pieces: list[dict] = []
    for edge_id, intervals in sub_pieces.items():
        for (t_start, t_end, na, nb) in intervals:
            if (na in cavity_nodes) != (nb in cavity_nodes):
                cut_pieces.append({"kind": "edge", "edge_id": edge_id, "t_start": t_start, "t_end": t_end,
                                    "region_a": na, "region_b": nb})

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


def _make_builder(side_core_face_ids):
    def builder(part, direction, track_b_segments, silhouette_edge_ids,
                *, unary_weight, smoothness_weight, silhouette_discount):
        return build_graph_z_side_action(
            part, direction, track_b_segments, silhouette_edge_ids,
            unary_weight=unary_weight, smoothness_weight=smoothness_weight,
            silhouette_discount=silhouette_discount, side_core_face_ids=side_core_face_ids,
        )
    return builder


def run_experiment():
    from backend.config import settings
    from backend.geometry.parting_line_v2.contracts import UndercutInput
    from backend.geometry.step_loader import load_step_cached

    cfg = settings.dfm.parting_line_v2
    undercuts = UndercutInput.empty()
    part3 = load_step_cached("data/parts/Part3.stp")

    def unit(v):
        n = math.sqrt(sum(c * c for c in v))
        return tuple(c / n for c in v)

    direction_z = unit((0, 0, 1))

    # Control set: 17 faces from a region uninvolved in the rib/bore
    # investigation (verified below to not overlap the justified set or
    # the bore).
    control_faces = frozenset(range(200, 217))

    print(f"Justified side-action set ({len(JUSTIFIED_SIDE_ACTION_FACES)} faces): "
          f"{sorted(JUSTIFIED_SIDE_ACTION_FACES)}", flush=True)
    print(f"Control set ({len(control_faces)} faces): {sorted(control_faces)}", flush=True)
    faces_by_id = {f.face_id: f for f in part3.faces}
    print("Control set surface types:",
          [faces_by_id[f].surface_type for f in sorted(control_faces) if f in faces_by_id], flush=True)

    cases = {
        "A_baseline": frozenset(),
        "B_justified_side_action": JUSTIFIED_SIDE_ACTION_FACES,
        "C_control_arbitrary": control_faces,
    }

    for case_name, face_set in cases.items():
        print(f"\n=== CASE {case_name} (side_core_face_ids size={len(face_set)}) ===", flush=True)
        results = mb._run_candidate(part3, direction_z, cfg, undercuts, _make_builder(face_set))
        for obj_name, r in results.items():
            if "degenerate" in r:
                print(f"  {obj_name}: degenerate cut", flush=True)
                continue
            if "error" in r:
                print(f"  {obj_name}: ERROR {r['error']}", flush=True)
                continue
            fr = r["feasibility"]
            areas = r.get("region_areas") or {}
            print(f"  {obj_name}: outcome={fr['outcome']} failed_gate={fr['failed_gate']} "
                  f"loops={r['loop_count']} single_loop={r['is_single_continuous_loop']} "
                  f"cavity={r['cavity_face_count']} core={r['core_face_count']} "
                  f"cavity_mm2={areas.get('cavity_area_mm2')} core_mm2={areas.get('core_area_mm2')} "
                  f"h1={fr['measurements'].get('h1_closure_error_mm')} "
                  f"h3={fr['measurements'].get('h3_region_count')} "
                  f"h4={fr['measurements'].get('h4_orientation_violation_fraction')} "
                  f"h7={fr['measurements'].get('h7_coverage')}", flush=True)


if __name__ == "__main__":
    run_experiment()
