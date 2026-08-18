"""
backend/validation/parting_line_mechanism_b_avsb.py
------------------------------------------------------
Bounded A-vs-B test for Mechanism B (2026-08-14): for each of the 7
dangling degree-1 "single-arc-stub at a genuine B-Rep vertex" instances
found at Part3 +X (clusters 24, 76, 78, 80, 87, 92, 156), determine whether
the vertex's OTHER incident arc edge(s) -- the "companion" -- SHOULD have
contributed a cut piece (its two flanking region-nodes are on opposite
sides of the min-cut) or legitimately should not have (same side).

READ-ONLY DIAGNOSTIC. Does not modify
`backend/geometry/parting_line_v2/*` or
`backend/validation/parting_line_region_partition_prototype.py`. The graph
construction below is a byte-for-byte copy of
`build_min_cut_partition_nway_subedge` up to the min-cut call, extended
ONLY to also return `cavity_nodes`/`core_nodes`/`sub_pieces` (private
internals the original function computes but does not expose) -- no
behaviour is changed.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import networkx as nx
from OCC.Core.BRep import BRep_Tool

import backend.validation.parting_line_forensic_trace as ft
import backend.validation.parting_line_region_partition_prototype as proto
from backend.geometry.parting_line_v2.types import FaceBacking


def build_graph_with_internals(part, direction, track_b_segments, silhouette_edge_ids,
                                *, unary_weight, smoothness_weight, silhouette_discount):
    """Verbatim copy of build_min_cut_partition_nway_subedge's graph-construction
    steps, extended to also return cavity_nodes/core_nodes/sub_pieces/face_regions."""
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
        segs = track_b_by_face.get(face.face_id, [])
        regions = proto.build_face_regions(part, face, segs)
        face_regions[face.face_id] = regions if regions else None
        if regions:
            face_region_adjacency[face.face_id] = proto.region_adjacency(regions)

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
            area_mm2, mean_g = proto.region_stats(face, region, direction)
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

    sub_pieces: dict[int, list[tuple]] = {}
    edge_capacity: dict[tuple, float] = {}
    for (a, b), edge_ids in pair_edges.items():
        for edge_id in edge_ids:
            edge = edges_by_id.get(edge_id)
            if edge is None:
                continue
            intervals = proto.edge_subinterval_attachment(
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

    for (na, nb), cap in edge_capacity.items():
        graph.add_edge(na, nb, capacity=cap)
        graph.add_edge(nb, na, capacity=cap)

    cut_value, (reachable, non_reachable) = nx.minimum_cut(graph, "S", "T", capacity="capacity")
    cavity_nodes = frozenset(n for n in reachable if n not in ("S", "T"))
    core_nodes = frozenset(n for n in non_reachable if n not in ("S", "T"))

    return {
        "cavity_nodes": cavity_nodes, "core_nodes": core_nodes,
        "sub_pieces": sub_pieces, "face_regions": face_regions,
        "edge_capacity": edge_capacity,
    }


TARGETS = [
    (24, (-9.08605129973476, 8.58450183636699, 22.0), 35, [9, 38]),
    (76, (6.0, 0.0, 39.0), 113, [35, 319]),
    (78, (-6.0, 0.0, 39.0), 114, [35, 319]),
    (80, (-7.0, 0.0, 0.0), 115, [36, 320]),
    (87, (-17.0, -0.0, 0.0), 116, [36, 321]),
    (92, (-18.0, -0.0, 4.0), 119, [37, 317]),
    (156, (7.0, 0.0, 40.0), 201, [40, 319]),
]


def _edge_endpoint_side(part, edge_id, target_3d):
    """Which end (t=first or t=last) of edge_id is nearest target_3d, via real
    OCC evaluation -- never raw parameter comparison."""
    edges_by_id = {e.edge_id: e for e in part.edges}
    edge = edges_by_id[edge_id]
    nearest = ft._edge_nearest_point(edge, target_3d)
    return nearest


def main():
    from backend.config import settings
    from backend.geometry.parting_line_v2.contracts import PullDirectionInput
    from backend.geometry.parting_line_v2.track_a import detect_edge_silhouettes
    from backend.geometry.parting_line_v2.track_b import detect_face_silhouettes
    from backend.geometry.parting_line_v2.types import EdgeBacking
    from backend.geometry.step_loader import load_step_cached

    cfg = settings.dfm.parting_line_v2
    part3 = load_step_cached("data/parts/Part3.stp")

    def unit(v):
        n = math.sqrt(sum(c * c for c in v))
        return tuple(c / n for c in v)

    direction_tuple = unit((1, 0, 0))
    direction = PullDirectionInput(direction_tuple, "manual").direction
    bbox_diag = proto._bbox_diagonal(part3)
    track_a = detect_edge_silhouettes(part3, direction, cfg=cfg, bbox_diagonal_mm=bbox_diag)
    silhouette_edge_ids = frozenset(
        s.backing.edge_id for s in track_a.segments
        if s.kind == "silhouette" and isinstance(s.backing, EdgeBacking)
    )
    track_b = detect_face_silhouettes(part3, direction, cfg=cfg, bbox_diagonal_mm=bbox_diag,
                                       start_segment_id=len(track_a.segments))
    unary_w, smooth_w, discount = proto.OBJECTIVES["C_balanced_low"]

    internals = build_graph_with_internals(
        part3, direction, track_b.segments, silhouette_edge_ids,
        unary_weight=unary_w, smoothness_weight=smooth_w, silhouette_discount=discount,
    )
    cavity_nodes = internals["cavity_nodes"]
    core_nodes = internals["core_nodes"]
    sub_pieces = internals["sub_pieces"]
    face_regions = internals["face_regions"]

    def side_of(node):
        if node in cavity_nodes:
            return "cavity"
        if node in core_nodes:
            return "core"
        return "UNKNOWN(not in graph)"

    edges_by_id = {e.edge_id: e for e in part3.edges}

    print(f"{'cluster':>7} | {'vertex':>28} | {'present_edge':>12} | companions", flush=True)
    print("=" * 140, flush=True)

    results = []
    for cluster_id, target, present_edge_id, present_faces in TARGETS:
        print(f"\n--- cluster {cluster_id} @ {target} (present piece: edge {present_edge_id}, faces {present_faces}) ---",
              flush=True)
        # 1. every edge exactly incident to this vertex (real OCC search, tight radius)
        hits = ft.search_all_edges_near_point(part3, target, 0.02)
        print(f"    incident edges: {[(h['edge_id'], h['edge_type'], h['adjacent_face_ids']) for h in hits]}",
              flush=True)

        for h in hits:
            eid = h["edge_id"]
            if eid == present_edge_id:
                continue  # this is the already-known present piece, not a companion
            fids = h["adjacent_face_ids"]
            if len(fids) != 2:
                print(f"    companion candidate: edge {eid} ({h['edge_type']}) faces={fids} "
                      f"-- SKIPPED (not a 2-face edge, no region-pair to test)", flush=True)
                continue
            a, b = sorted(fids)
            regions_a = face_regions.get(a)
            regions_b = face_regions.get(b)
            ra = regions_a[0].region_id if regions_a else 0
            rb = regions_b[0].region_id if regions_b else 0
            # find which sub-interval of this companion edge actually touches target
            ivs = sub_pieces.get(eid, [])
            edge = edges_by_id[eid]
            nearest = ft._edge_nearest_point(edge, target)
            t_target = nearest["t"] if nearest else None
            matching_iv = None
            for (t_start, t_end, na, nb) in ivs:
                lo, hi = min(t_start, t_end), max(t_start, t_end)
                if t_target is not None and (lo - 1e-6) <= t_target <= (hi + 1e-6):
                    # only count if target is at one of the interval's OWN endpoints
                    if abs(t_target - t_start) < 1e-4 or abs(t_target - t_end) < 1e-4:
                        matching_iv = (t_start, t_end, na, nb)
                        break
            if matching_iv is None:
                print(f"    companion: edge {eid} ({h['edge_type']}) faces=({a},{b}) "
                      f"-- NO sub-interval endpoint found at this vertex "
                      f"(sub_pieces for this edge: {ivs}) => CASE B CANDIDATE (attachment never generated a breakpoint here)",
                      flush=True)
                results.append((cluster_id, eid, "no_subinterval_at_vertex", None, None, None))
                continue
            t_start, t_end, na, nb = matching_iv
            side_a, side_b = side_of(na), side_of(nb)
            same_side = side_a == side_b
            is_cut_piece = side_a != side_b
            verdict = "CASE A (same side, correctly not cut)" if same_side else \
                      "CASE B (opposite sides -- SHOULD be a cut piece)"
            print(f"    companion: edge {eid} ({h['edge_type']}) faces=({a},{b}) "
                  f"interval=[{t_start:.4f},{t_end:.4f}] na={na}({side_a}) nb={nb}({side_b}) "
                  f"is_cut_piece_by_construction={is_cut_piece} => {verdict}", flush=True)
            results.append((cluster_id, eid, "found", side_a, side_b, is_cut_piece))

    print("\n\n========== SUMMARY ==========", flush=True)
    for r in results:
        print(r, flush=True)


if __name__ == "__main__":
    main()
