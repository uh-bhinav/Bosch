"""
backend/validation/parting_line_2core_pruning_diagnosis.py
------------------------------------------------------------
Phase P3.2 Task 1/2/3/4 diagnostic (2026-08-13): reproduces exactly what
`reduce_to_two_core()` discards for a given part+direction, classifies each
raw (pre-2-core) connected component by its cyclomatic number, and cross-
references discarded segments against independently-sampled sign(g) to
identify genuinely parting-relevant fragments.

Mathematical anchor (verified, not assumed, by this script): 2-core peeling
(iterative degree<=1 removal) can only ever remove tree edges. Removing a
degree-1 node removes exactly one node and one edge, so E-V is invariant
per removal, and a leaf's removal never disconnects the remainder -- so the
cyclomatic number of every RAW connected component (mu = E - V + 1) is
IDENTICAL to the cyclomatic number of what that component reduces to after
2-core (or the component vanishes entirely if mu_raw == 0). This script
verifies that invariant empirically per component as a self-check, then
uses raw (pre-2-core) component membership -- not just "was it pruned" --
to distinguish "this fragment could never have been part of ANY cycle, full
stop" from "this fragment is close to real global structure but the current
graph never connects it."

Read-only. No production code touched. Manual directions only
(direction-contamination discipline maintained).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _normalize(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def _raw_components(graph):
    """BFS components of the RAW (pre-reduction) graph, with per-component mu."""
    seen = set()
    comps = []
    for start in sorted(graph.adjacency):
        if start in seen:
            continue
        stack, nodes = [start], set()
        seen.add(start)
        while stack:
            n = stack.pop()
            nodes.add(n)
            for nb, _sid in graph.adjacency.get(n, ()):
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        edge_ids = set()
        for n in nodes:
            for _nb, sid in graph.adjacency.get(n, ()):
                edge_ids.add(sid)
        v, e = len(nodes), len(edge_ids)
        mu = e - v + 1 if v else 0
        comps.append({"nodes": nodes, "edge_ids": edge_ids, "v": v, "e": e, "mu": mu})
    return comps


def _run(part_path: str, direction: tuple, label: str) -> dict:
    from backend.config import settings
    from backend.geometry.parting_line_v2.contracts import PullDirectionInput
    from backend.geometry.parting_line_v2.engine import _bbox_diagonal
    from backend.geometry.parting_line_v2.graph import build_graph, reduce_to_two_core
    from backend.geometry.parting_line_v2.stitch import stitch_tracks
    from backend.geometry.parting_line_v2.track_a import detect_edge_silhouettes
    from backend.geometry.parting_line_v2.track_b import detect_face_silhouettes
    from backend.geometry.parting_line_v2.track_b import _FaceField
    from backend.geometry.parting_line_v2.types import EdgeBacking, FaceBacking
    from backend.geometry.step_loader import load_step
    from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_VERTEX
    from OCC.Core.BRep import BRep_Tool

    part = load_step(part_path)
    pull = PullDirectionInput(_normalize(direction), "manual")
    bbox_diagonal = _bbox_diagonal(part)

    track_a = detect_edge_silhouettes(part, pull.direction, cfg=settings.dfm.parting_line_v2, bbox_diagonal_mm=bbox_diagonal)
    track_b = detect_face_silhouettes(
        part, pull.direction, cfg=settings.dfm.parting_line_v2, bbox_diagonal_mm=bbox_diagonal,
        start_segment_id=len(track_a.segments),
    )
    stitched = stitch_tracks(
        part, track_a.segments, track_b.segments,
        tolerance_mm=max(settings.dfm.parting_line_v2.stitch_snap_tolerance_rel * bbox_diagonal, 1e-6),
    )
    segs_by_id = {s.segment_id: s for s in stitched.segments}

    graph = build_graph(stitched.segments, bbox_diagonal_mm=bbox_diagonal, cfg=settings.dfm.parting_line_v2)
    nodes_before, edges_before = len(graph.node_points), len(graph.segment_nodes)
    raw_comps = _raw_components(graph)

    # degree-before, per node, captured BEFORE mutation
    degree_before = {n: len(inc) for n, inc in graph.adjacency.items()}
    raw_component_of_segment = {}
    for idx, comp in enumerate(raw_comps):
        for sid in comp["edge_ids"]:
            raw_component_of_segment[sid] = idx

    stats = reduce_to_two_core(graph)  # mutates graph in place
    surviving_segment_ids = set(graph.segment_nodes)
    pruned_ids = set(stats.pruned_edge_ids)

    # Verify the cyclomatic-number invariant per raw component.
    post_components = []
    seen = set()
    for start in sorted(graph.adjacency):
        if start in seen:
            continue
        stack, nodes = [start], set()
        seen.add(start)
        while stack:
            n = stack.pop()
            nodes.add(n)
            for nb, _sid in graph.adjacency.get(n, ()):
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        edge_ids = {sid for n in nodes for _nb, sid in graph.adjacency.get(n, ())}
        v, e = len(nodes), len(edge_ids)
        post_components.append({"v": v, "e": e, "mu": e - v + 1 if v else 0, "edge_ids": edge_ids})

    invariant_violations = []
    for comp in raw_comps:
        if comp["mu"] == 0:
            survivors = comp["edge_ids"] & surviving_segment_ids
            if survivors:
                invariant_violations.append({"raw_mu0_component_size": comp["e"], "unexpected_survivors": sorted(survivors)})
        else:
            matched = [pc for pc in post_components if pc["edge_ids"] <= comp["edge_ids"]]
            total_post_mu = sum(pc["mu"] for pc in matched)
            if total_post_mu != comp["mu"]:
                invariant_violations.append({
                    "raw_component_edges": sorted(comp["edge_ids"]),
                    "raw_mu": comp["mu"], "post_mu_sum": total_post_mu,
                })

    # sign(g) sampling per face, using the SAME production sampler as track_b.py
    faces_by_id = {f.face_id: f for f in part.faces}
    mixed_sign_face_cache: dict[int, str] = {}

    def face_sign_profile(face_id: int) -> str:
        if face_id in mixed_sign_face_cache:
            return mixed_sign_face_cache[face_id]
        face = faces_by_id.get(face_id)
        if face is None:
            mixed_sign_face_cache[face_id] = "unknown"
            return "unknown"
        field = _FaceField(face.occ_face, pull.direction)
        surf = BRepAdaptor_Surface(face.occ_face, True)
        umin, umax, vmin, vmax = surf.FirstUParameter(), surf.LastUParameter(), surf.FirstVParameter(), surf.LastVParameter()
        signs = set()
        for uf in (0.1, 0.3, 0.5, 0.7, 0.9):
            for vf in (0.1, 0.3, 0.5, 0.7, 0.9):
                g = field.g(umin + uf * (umax - umin), vmin + vf * (vmax - vmin))
                if g is not None:
                    signs.add(1 if g > 1e-6 else (-1 if g < -1e-6 else 0))
        result = "mixed" if len(signs) > 1 else ("zero" if signs == {0} else ("positive" if signs == {1} else ("negative" if signs == {-1} else "no_samples")))
        mixed_sign_face_cache[face_id] = result
        return result

    def nearest_vertex_distance(point, occ_shape) -> float | None:
        best = None
        explorer = TopExp_Explorer(occ_shape, TopAbs_VERTEX)
        while explorer.More():
            vtx = explorer.Current()
            p = BRep_Tool.Pnt(vtx)
            d = math.dist(point, (p.X(), p.Y(), p.Z()))
            if best is None or d < best:
                best = d
            explorer.Next()
        return best

    # Build inventory of PRUNED segments that touch a mixed-sign face (the
    # "parting-relevant" filter Task 1 asks for).
    inventory = []
    for sid in sorted(pruned_ids):
        seg = segs_by_id[sid]
        backing = seg.backing
        if isinstance(backing, FaceBacking):
            face_id = backing.face_id
            backing_desc = {"type": "FaceBacking", "face_id": face_id}
        else:
            face_id = None
            adj = part.edge_to_faces.get(backing.edge_id, [])
            backing_desc = {"type": "EdgeBacking", "edge_id": backing.edge_id, "t_start": backing.t_start, "t_end": backing.t_end, "adjacent_face_ids": adj}
            # for edge-backed segments, treat as mixed if EITHER adjacent face is mixed
        touched_faces = [face_id] if face_id is not None else backing_desc.get("adjacent_face_ids", [])
        sign_profiles = {fid: face_sign_profile(fid) for fid in touched_faces if fid is not None}
        is_mixed_relevant = any(v == "mixed" for v in sign_profiles.values())
        if not is_mixed_relevant:
            continue

        node_a, node_b = None, None
        # segment_nodes was popped during reduction; recover from original build by re-deriving
        p0, p1 = seg.points[0], seg.points[-1]
        length = sum(
            math.dist(seg.points[i], seg.points[i + 1]) for i in range(len(seg.points) - 1)
        )
        raw_comp_idx = raw_component_of_segment.get(sid)
        raw_comp = raw_comps[raw_comp_idx] if raw_comp_idx is not None else None

        # neighbouring segments = other segments sharing a raw component
        neighbours_in_component = sorted((raw_comp["edge_ids"] - {sid})) if raw_comp else []

        dist_p0_vertex = nearest_vertex_distance(p0, part.occ_shape) if hasattr(part, "occ_shape") else None
        dist_p1_vertex = nearest_vertex_distance(p1, part.occ_shape) if hasattr(part, "occ_shape") else None

        inventory.append({
            "segment_id": sid,
            "track": "A" if isinstance(backing, EdgeBacking) else "B",
            "kind": seg.kind,
            "backing": backing_desc,
            "start_point": [round(c, 4) for c in p0],
            "end_point": [round(c, 4) for c in p1],
            "length_mm": round(length, 4),
            "sign_profiles": sign_profiles,
            "raw_component_index": raw_comp_idx,
            "raw_component_v": raw_comp["v"] if raw_comp else None,
            "raw_component_e": raw_comp["e"] if raw_comp else None,
            "raw_component_mu": raw_comp["mu"] if raw_comp else None,
            "raw_component_shares_group1": (
                raw_comp_idx == raw_component_of_segment.get(9) if 9 in raw_component_of_segment else None
            ),
            "neighbour_segment_ids_in_raw_component": neighbours_in_component,
            "nearest_brep_vertex_distance_mm": {
                "start": round(dist_p0_vertex, 5) if dist_p0_vertex is not None else None,
                "end": round(dist_p1_vertex, 5) if dist_p1_vertex is not None else None,
            },
        })

    group1_ids = {9, 243, 120, 121}
    group1_raw_component_indices = sorted({raw_component_of_segment.get(s) for s in group1_ids if s in raw_component_of_segment})

    return {
        "label": label,
        "direction": pull.direction,
        "bbox_diagonal_mm": round(bbox_diagonal, 3),
        "nodes_before": nodes_before,
        "edges_before": edges_before,
        "nodes_after": stats.nodes_after,
        "edges_after": stats.edges_after,
        "pruned_segment_count": len(pruned_ids),
        "raw_component_count": len(raw_comps),
        "raw_component_mu_histogram": sorted({c["mu"] for c in raw_comps}),
        "raw_components_with_mu_gt_0": [{"v": c["v"], "e": c["e"], "mu": c["mu"]} for c in raw_comps if c["mu"] > 0],
        "cyclomatic_invariant_violations": invariant_violations,
        "group1_raw_component_indices": group1_raw_component_indices,
        "mixed_sign_relevant_pruned_segment_count": len(inventory),
        "mixed_sign_relevant_pruned_segments": inventory,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default="reports/parting_line_2core_pruning_diagnosis.json")
    args = parser.parse_args(argv)

    targets = [
        ("Part3", str(REPO_ROOT / "data" / "parts" / "Part3.stp"), (0.0, 1.0, 1.0), "Part3_(0,1,1)"),
        ("Part1", str(REPO_ROOT / "data" / "parts" / "Part1.stp"), (0.0, 0.0, 1.0), "Part1_+Z"),
        ("Part1", str(REPO_ROOT / "data" / "parts" / "Part1.stp"), (1.0, 0.0, 0.0), "Part1_+X"),
        ("Part1", str(REPO_ROOT / "data" / "parts" / "Part1.stp"), (0.0, 1.0, 0.0), "Part1_+Y"),
    ]

    results = {}
    for _part, path, direction, label in targets:
        print(f"--- {label} ---")
        r = _run(path, direction, label)
        results[label] = r
        print(f"  raw: {r['nodes_before']} nodes / {r['edges_before']} edges, "
              f"{r['raw_component_count']} components, mu histogram {r['raw_component_mu_histogram']}")
        print(f"  pruned: {r['pruned_segment_count']} segments; "
              f"mixed-sign-relevant among pruned: {r['mixed_sign_relevant_pruned_segment_count']}")
        print(f"  cyclomatic invariant violations: {len(r['cyclomatic_invariant_violations'])}")

    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nreport -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
