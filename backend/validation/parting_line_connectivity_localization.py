"""
backend/validation/parting_line_connectivity_localization.py
------------------------------------------------------------------
READ-ONLY localization of WHERE global-loop connectivity is lost, at
controlled directions only.

Prior finding (P3 candidate-generation diagnosis) needed a sharper check:
the DOMINANT 2-core graph component at Part1 +X spans the part's full bbox
(x:[-9.5, 9.5], matching +Z exactly) -- so the component itself is not
missing the far-x region. But the LARGEST candidate cycle actually produced
only reaches x=6.6. That is a genuine, confirmed discrepancy between
"the graph is connected out there" and "no cycle uses it" -- and it points
at a specific, checkable graph-theoretic structure: an articulation point
(cut vertex). If the far-x segments attach to the rest of the component
through a single node, no SIMPLE cycle can ever include both the far region
and a full tour of the rest -- entering and leaving through the same node
would revisit it, which a simple cycle cannot do. This would mean NO
enumeration strategy (basis, Johnson, or exhaustive) could ever produce the
missing loop, because it does not exist as a simple cycle in the graph --
an entirely different conclusion from "enumeration hasn't found it yet".

This script:
1. Rebuilds the 2-core graph exactly as production code does (self-checked
   against build_graph/reduce_to_two_core).
2. Isolates the dominant component.
3. Finds articulation points within it (networkx, already a project
   dependency).
4. For each articulation point separating a spatially distinct region,
   traces the exact segments/endpoints meeting there back to B-Rep
   edge/face identity.
5. Checks whether there is a nearby (but un-welded) endpoint pair near that
   same location -- i.e., whether the articulation point is itself an
   artifact of a failed weld (a "should have been a second connection but
   wasn't"), or a genuine single physical vertex with no second path.

Does not bridge, merge, or modify anything. Pull direction is always an
explicit, manually-supplied vector.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DIRECTIONS = {
    "+X": (1.0, 0.0, 0.0), "-X": (-1.0, 0.0, 0.0),
    "+Y": (0.0, 1.0, 0.0), "-Y": (0.0, -1.0, 0.0),
    "+Z": (0.0, 0.0, 1.0), "-Z": (0.0, 0.0, -1.0),
}


def _describe_backing(segment, part) -> dict:
    from backend.geometry.parting_line_v2.types import EdgeBacking

    b = segment.backing
    if isinstance(b, EdgeBacking):
        edge = next((e for e in part.edges if e.edge_id == b.edge_id), None)
        return {
            "provenance": "edge", "edge_id": b.edge_id,
            "adjacent_face_ids": list(edge.adjacent_face_ids) if edge else None,
            "t_start": round(b.t_start, 6), "t_end": round(b.t_end, 6),
        }
    return {
        "provenance": "face", "face_id": b.face_id,
        "uv_start": [round(c, 6) for c in b.uv[0]] if b.uv else None,
        "uv_end": [round(c, 6) for c in b.uv[-1]] if b.uv else None,
    }


def _localize(part_path: str, direction_label: str) -> dict:
    import networkx as nx

    from backend.config import settings
    from backend.geometry.parting_line_v2.contracts import PullDirectionInput
    from backend.geometry.parting_line_v2.engine import _bbox_diagonal
    from backend.geometry.parting_line_v2.graph import build_graph, reduce_to_two_core
    from backend.geometry.parting_line_v2.stitch import stitch_tracks
    from backend.geometry.parting_line_v2.track_a import detect_edge_silhouettes
    from backend.geometry.parting_line_v2.track_b import detect_face_silhouettes
    from backend.geometry.step_loader import load_step

    cfg = settings.dfm.parting_line_v2
    part = load_step(part_path)
    pull = PullDirectionInput(DIRECTIONS[direction_label], "manual")
    assert pull.is_correctness_evidence
    bbox_diagonal = _bbox_diagonal(part)

    track_a = detect_edge_silhouettes(part, pull.direction, cfg=cfg, bbox_diagonal_mm=bbox_diagonal)
    track_b = detect_face_silhouettes(
        part, pull.direction, cfg=cfg, bbox_diagonal_mm=bbox_diagonal,
        start_segment_id=len(track_a.segments),
    )
    stitched = stitch_tracks(
        part, track_a.segments, track_b.segments,
        tolerance_mm=max(cfg.stitch_snap_tolerance_rel * bbox_diagonal, 1e-6),
    )
    all_segments = stitched.segments
    segments_by_id = {s.segment_id: s for s in all_segments}

    graph = build_graph(all_segments, bbox_diagonal_mm=bbox_diagonal, cfg=cfg)
    reduce_to_two_core(graph)  # mutates in place

    # --- isolate the dominant (largest) component -----------------------
    def _components():
        seen: set[int] = set()
        comps = []
        for start in sorted(graph.adjacency):
            if start in seen:
                continue
            stack, group = [start], set()
            seen.add(start)
            while stack:
                n = stack.pop()
                group.add(n)
                for nb, _ in graph.adjacency.get(n, ()):
                    if nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
            comps.append(group)
        return comps

    components = _components()
    dominant = max(components, key=len)

    # --- build a plain networkx graph for the dominant component --------
    g = nx.MultiGraph()
    g.add_nodes_from(dominant)
    for node in dominant:
        for neighbour, segment_id in graph.adjacency.get(node, ()):
            if neighbour in dominant:
                g.add_edge(node, neighbour, key=segment_id, segment_id=segment_id)

    # networkx articulation_points requires a simple Graph for connectivity
    # purposes; build a simple-graph view (parallel edges collapsed) purely
    # for cut-vertex detection -- a node's status as a cut vertex depends
    # only on which OTHER nodes it connects, not edge multiplicity.
    simple = nx.Graph()
    simple.add_nodes_from(g.nodes())
    simple.add_edges_from(g.edges())
    cuts = list(nx.articulation_points(simple)) if simple.number_of_nodes() > 2 else []

    bbox = {
        "x": [min(graph.node_points[n][0] for n in dominant), max(graph.node_points[n][0] for n in dominant)],
        "y": [min(graph.node_points[n][1] for n in dominant), max(graph.node_points[n][1] for n in dominant)],
        "z": [min(graph.node_points[n][2] for n in dominant), max(graph.node_points[n][2] for n in dominant)],
    }

    cut_details = []
    for cut_node in cuts:
        # What splits off if this node is removed? Look at the component
        # structure of the graph with this node deleted.
        without = simple.copy()
        without.remove_node(cut_node)
        pieces = list(nx.connected_components(without))
        pieces.sort(key=len)
        smallest_piece = pieces[0] if pieces else set()
        piece_bbox = None
        if smallest_piece:
            piece_bbox = {
                "x": [min(graph.node_points[n][0] for n in smallest_piece), max(graph.node_points[n][0] for n in smallest_piece)],
                "y": [min(graph.node_points[n][1] for n in smallest_piece), max(graph.node_points[n][1] for n in smallest_piece)],
                "z": [min(graph.node_points[n][2] for n in smallest_piece), max(graph.node_points[n][2] for n in smallest_piece)],
            }
        incident_segment_ids = sorted({sid for _, sid in graph.adjacency.get(cut_node, ())})
        cut_details.append({
            "cut_node": cut_node, "point": list(graph.node_points[cut_node]),
            "piece_count_if_removed": len(pieces),
            "piece_sizes_if_removed": [len(p) for p in pieces],
            "smallest_piece_size": len(smallest_piece),
            "smallest_piece_bbox": piece_bbox,
            "incident_segments": [
                {"segment_id": sid, **_describe_backing(segments_by_id[sid], part)}
                for sid in incident_segment_ids
            ],
        })

    # Rank cut points by how "spatially separating" they are (biggest
    # smallest-piece bbox span = most likely to be the one truncating the
    # global loop, as opposed to a cut point pinching off a tiny local twig).
    cut_details.sort(key=lambda c: -c["smallest_piece_size"])

    # --- for the top cut point, check for a nearby un-welded endpoint ---
    # i.e. is this articulation point an artifact of a failed weld nearby,
    # or a genuine single physical vertex with truly one connection?
    nearby_gap = None
    if cut_details:
        top = cut_details[0]
        cut_point = graph.node_points[top["cut_node"]]
        best = None
        for node, point in graph.node_points.items():
            if node == top["cut_node"]:
                continue
            d = math.dist(cut_point, point)
            if best is None or d < best[1]:
                best = (node, d)
        if best:
            nearby_gap = {
                "nearest_other_node": best[0], "distance_mm": best[1],
                "nearest_other_node_incident_segments": sorted(
                    {sid for _, sid in graph.adjacency.get(best[0], ())}
                ),
            }

    return {
        "direction_label": direction_label, "direction": list(pull.direction),
        "dominant_component_size": len(dominant),
        "dominant_component_bbox": bbox,
        "articulation_point_count": len(cuts),
        "cut_points": cut_details[:5],
        "top_cut_point_nearby_check": nearby_gap,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default="reports/connectivity_localization.json")
    args = parser.parse_args(argv)

    targets = [
        (str(REPO_ROOT / "data" / "parts" / "Part1.stp"), "+Z"),
        (str(REPO_ROOT / "data" / "parts" / "Part1.stp"), "+X"),
        (str(REPO_ROOT / "data" / "parts" / "Part1.stp"), "+Y"),
        (str(REPO_ROOT / "data" / "parts" / "Part3.stp"), "+X"),
        (str(REPO_ROOT / "data" / "parts" / "Part3.stp"), "+Y"),
    ]
    results = {}
    for part_path, direction in targets:
        key = f"{Path(part_path).stem}_{direction}"
        print(f"--- {key} ---")
        record = _localize(part_path, direction)
        results[key] = record
        print(f"  dominant component: {record['dominant_component_size']} nodes, bbox={record['dominant_component_bbox']}")
        print(f"  articulation points: {record['articulation_point_count']}")
        for cp in record["cut_points"][:3]:
            print(f"    cut_node={cp['cut_node']} smallest_piece={cp['smallest_piece_size']} "
                  f"bbox={cp['smallest_piece_bbox']}")
        if record["top_cut_point_nearby_check"]:
            print(f"  nearest-other-node check: {record['top_cut_point_nearby_check']}")

    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nreport -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
