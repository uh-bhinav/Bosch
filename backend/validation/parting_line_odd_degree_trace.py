"""
backend/validation/parting_line_odd_degree_trace.py
------------------------------------------------------
READ-ONLY DIAGNOSTIC (P3.17, 2026-08-13). Traces every odd-degree vertex in
a P3.16 sub-edge-aware min-cut result, per-vertex, with full B-Rep
provenance -- not inferring cause from degree alone (per the standing
instruction). No production code touched.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import backend.validation.parting_line_region_partition_prototype as proto


def trace_odd_degree_vertices(part, cut_pieces, weld_cell_mm):
    """Full per-vertex diagnostic for every odd-degree cluster in this cut."""
    resolved = [proto._resolve_piece_geometry(part, p) for p in cut_pieces]
    clusters = proto._weld_piece_endpoints(resolved, weld_cell_mm)

    adjacency: dict[int, list[tuple[int, int]]] = {}
    for idx, (points, _backing, _g) in enumerate(resolved):
        k0, k1 = clusters[2 * idx], clusters[2 * idx + 1]
        adjacency.setdefault(k0, []).append((idx, k1))
        adjacency.setdefault(k1, []).append((idx, k0))

    cluster_point: dict[int, tuple] = {}
    all_points_by_cluster: dict[int, list[tuple]] = {}
    for idx, (points, _backing, _g) in enumerate(resolved):
        k0, k1 = clusters[2 * idx], clusters[2 * idx + 1]
        cluster_point.setdefault(k0, points[0])
        cluster_point.setdefault(k1, points[-1])
        all_points_by_cluster.setdefault(k0, []).append(points[0])
        all_points_by_cluster.setdefault(k1, []).append(points[-1])

    edges_by_id = {e.edge_id: e for e in part.edges}
    faces_by_id = {f.face_id: f for f in part.faces}

    def _is_near_seam(edge, t):
        """Rough periodic-seam check: parameter near 0 or 2*pi for a Circle edge."""
        if edge.edge_type != "Circle":
            return False
        return min(abs(t), abs(t - 2 * math.pi)) < 1e-3

    odd_vertices = []
    for cluster_id, entries in adjacency.items():
        degree = len(entries)
        if degree % 2 == 0:
            continue
        incident = []
        for idx, _partner in entries:
            piece = cut_pieces[idx]
            points, _backing, _g = resolved[idx]
            is_self_loop = clusters[2 * idx] == clusters[2 * idx + 1]
            info: dict = {
                "piece_index": idx, "kind": piece["kind"], "is_self_loop": is_self_loop,
                "point_start": tuple(round(c, 5) for c in points[0]),
                "point_end": tuple(round(c, 5) for c in points[-1]),
            }
            if piece["kind"] == "edge":
                edge = edges_by_id.get(piece["edge_id"])
                info["edge_id"] = piece["edge_id"]
                info["t_start"] = piece.get("t_start")
                info["t_end"] = piece.get("t_end")
                info["adjacent_face_ids"] = list(edge.adjacent_face_ids) if edge else None
                info["edge_type"] = edge.edge_type if edge else None
                info["edge_length"] = edge.length if edge else None
                info["near_seam"] = (
                    _is_near_seam(edge, piece.get("t_start", 0)) or _is_near_seam(edge, piece.get("t_end", 0))
                    if edge else False
                )
            else:
                face = faces_by_id.get(piece["face_id"])
                info["face_id"] = piece["face_id"]
                info["surface_type"] = face.surface_type if face else None
            incident.append(info)

        points_here = all_points_by_cluster[cluster_id]
        pairwise = [
            math.dist(points_here[i], points_here[j])
            for i in range(len(points_here)) for j in range(i + 1, len(points_here))
        ]
        odd_vertices.append({
            "cluster_id": cluster_id,
            "degree": degree,
            "representative_point": tuple(round(c, 5) for c in cluster_point[cluster_id]),
            "max_pairwise_endpoint_distance_mm": round(max(pairwise), 6) if pairwise else 0.0,
            "self_loop_count": sum(1 for i in incident if i["is_self_loop"]),
            "non_self_loop_count": sum(1 for i in incident if not i["is_self_loop"]),
            "distinct_faces_involved": sorted({
                fid for i in incident
                for fid in (i.get("adjacent_face_ids") or [i.get("face_id")])
                if fid is not None
            }),
            "any_near_seam": any(i.get("near_seam") for i in incident),
            "incident_pieces": incident,
        })
    return odd_vertices


def classify(vertex: dict) -> str:
    """Programmatic classification against the A-I taxonomy, from traced data only."""
    if vertex["any_near_seam"]:
        return "E_periodic_seam"
    if vertex["max_pairwise_endpoint_distance_mm"] > 1e-6 and vertex["max_pairwise_endpoint_distance_mm"] < 0.5:
        # genuinely distinct B-Rep points, welded together only by tolerance
        return "C_over_welding_candidate"
    if vertex["self_loop_count"] >= 2:
        return "F_or_I_multi_self_loop_convergence"
    if vertex["non_self_loop_count"] == 1 and vertex["self_loop_count"] == 0:
        return "A_missing_cross_face_attachment"
    if len(vertex["distinct_faces_involved"]) >= 3:
        return "F_multiple_curves_at_one_point"
    return "I_unclassified"


def run_direction(part, direction_tuple, cfg, undercuts, label: str, objective_name: str = "C_balanced_low"):
    import math as _m

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
    track_b = detect_face_silhouettes(part, direction, cfg=cfg, bbox_diagonal_mm=bbox_diag, start_segment_id=len(track_a.segments))

    unary_w, smooth_w, discount = proto.OBJECTIVES[objective_name]
    cut = proto.build_min_cut_partition_nway_subedge(
        part, direction, track_b.segments, silhouette_edge_ids,
        unary_weight=unary_w, smoothness_weight=smooth_w, silhouette_discount=discount,
    )
    if cut is None or not cut["cut_pieces"]:
        print(f"=== {label} @ {objective_name}: no cut pieces ===", flush=True)
        return []

    weld_cell = max(cfg.stitch_snap_tolerance_rel * bbox_diag, 1e-6)
    odd = trace_odd_degree_vertices(part, cut["cut_pieces"], weld_cell)

    print(f"\n=== {label} @ {objective_name}: {len(cut['cut_pieces'])} pieces, {len(odd)} odd-degree vertices ===", flush=True)
    tally: dict[str, int] = {}
    for v in odd:
        cls = classify(v)
        tally[cls] = tally.get(cls, 0) + 1
    print(f"    classification tally: {tally}", flush=True)
    for v in odd[:5]:
        print(f"    cluster={v['cluster_id']} degree={v['degree']} point={v['representative_point']} "
              f"self_loops={v['self_loop_count']} non_self_loop={v['non_self_loop_count']} "
              f"faces={v['distinct_faces_involved']} near_seam={v['any_near_seam']} "
              f"max_pairwise_dist_mm={v['max_pairwise_endpoint_distance_mm']} class={classify(v)}", flush=True)
        for p in v["incident_pieces"]:
            print(f"        {p}", flush=True)
    return odd


def main():
    from backend.config import settings
    from backend.geometry.parting_line_v2.contracts import UndercutInput
    from backend.geometry.step_loader import load_step_cached

    cfg = settings.dfm.parting_line_v2
    undercuts = UndercutInput.empty()

    def unit(v):
        n = math.sqrt(sum(c * c for c in v))
        return tuple(c / n for c in v)

    part3 = load_step_cached("data/parts/Part3.stp")
    az15 = unit((math.cos(math.radians(15)), math.sin(math.radians(15)), 0.0))

    directions = [
        (az15, "az15"),
        (unit((0, 1, 1)), "(0,1,1)"),
        (unit((1, 0, 0)), "+X"),
        (unit((-1, 0, 0)), "-X"),
        (unit((0, 1, 0)), "+Y"),
    ]

    all_tallies: dict[str, dict] = {}
    for direction, label in directions:
        odd = run_direction(part3, direction, cfg, undercuts, label)
        tally: dict[str, int] = {}
        for v in odd:
            cls = classify(v)
            tally[cls] = tally.get(cls, 0) + 1
        all_tallies[label] = tally

    print("\n\n========== AGGREGATE CLASSIFICATION ACROSS ALL 5 DIRECTIONS ==========")
    combined: dict[str, int] = {}
    for label, tally in all_tallies.items():
        print(f"  {label}: {tally}")
        for k, v in tally.items():
            combined[k] = combined.get(k, 0) + v
    print(f"\n  TOTAL: {combined}")


if __name__ == "__main__":
    main()
