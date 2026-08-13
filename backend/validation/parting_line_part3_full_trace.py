"""
backend/validation/parting_line_part3_full_trace.py
------------------------------------------------------------
Phase 3/4 (2026-08-12 diagnostic phase): full 24-direction graph-detail
trace for Part3 -- adds what the earlier baseline matrix didn't capture
(pre-2-core component count, articulation points) and combines with the
already-saved Track A/B/graph/candidate/gate data from
reports/baseline_matrix_{principal,diagonal}.json.

Read-only. No production code touched. Manual directions only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PRINCIPAL_DIRECTIONS = {
    "+X": (1.0, 0.0, 0.0), "-X": (-1.0, 0.0, 0.0),
    "+Y": (0.0, 1.0, 0.0), "-Y": (0.0, -1.0, 0.0),
    "+Z": (0.0, 0.0, 1.0), "-Z": (0.0, 0.0, -1.0),
}
DIAGONAL_DIRECTIONS = {
    "(1,1,0)": (1.0, 1.0, 0.0), "(1,-1,0)": (1.0, -1.0, 0.0),
    "(1,0,1)": (1.0, 0.0, 1.0), "(1,0,-1)": (1.0, 0.0, -1.0),
    "(0,1,1)": (0.0, 1.0, 1.0), "(0,1,-1)": (0.0, 1.0, -1.0),
}
ALL_DIRECTIONS = {**PRINCIPAL_DIRECTIONS, **DIAGONAL_DIRECTIONS}


def _graph_detail(part_path: str, direction: tuple) -> dict:
    import networkx as nx

    from backend.config import settings
    from backend.geometry.parting_line_v2.contracts import PullDirectionInput
    from backend.geometry.parting_line_v2.engine import _bbox_diagonal
    from backend.geometry.parting_line_v2.graph import build_graph, reduce_to_two_core
    from backend.geometry.parting_line_v2.stitch import stitch_tracks
    from backend.geometry.parting_line_v2.track_a import detect_edge_silhouettes
    from backend.geometry.parting_line_v2.track_b import detect_face_silhouettes
    from backend.geometry.step_loader import load_step
    import math

    def normalize(v):
        n = math.sqrt(sum(c * c for c in v))
        return tuple(c / n for c in v)

    cfg = settings.dfm.parting_line_v2
    part = load_step(part_path)
    pull = PullDirectionInput(normalize(direction), "manual")
    bbox_diagonal = _bbox_diagonal(part)

    track_a = detect_edge_silhouettes(part, pull.direction, cfg=cfg, bbox_diagonal_mm=bbox_diagonal)
    track_b = detect_face_silhouettes(
        part, pull.direction, cfg=cfg, bbox_diagonal_mm=bbox_diagonal, start_segment_id=len(track_a.segments)
    )
    stitched = stitch_tracks(
        part, track_a.segments, track_b.segments,
        tolerance_mm=max(cfg.stitch_snap_tolerance_rel * bbox_diagonal, 1e-6),
    )
    graph = build_graph(stitched.segments, bbox_diagonal_mm=bbox_diagonal, cfg=cfg)

    # pre-2-core components
    def components(g):
        seen: set = set()
        comps = []
        for start in sorted(g.adjacency):
            if start in seen:
                continue
            stack, group = [start], set()
            seen.add(start)
            while stack:
                n = stack.pop()
                group.add(n)
                for nb, _ in g.adjacency.get(n, ()):
                    if nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
            comps.append(group)
        return comps

    pre_components = components(graph)
    reduce_to_two_core(graph)  # mutates in place -> post-2-core state
    post_components = components(graph)

    dominant = max(post_components, key=len) if post_components else set()
    simple = nx.Graph()
    simple.add_nodes_from(dominant)
    for n in dominant:
        for nb, _ in graph.adjacency.get(n, ()):
            if nb in dominant:
                simple.add_edge(n, nb)
    articulation_points = list(nx.articulation_points(simple)) if simple.number_of_nodes() > 2 else []

    return {
        "pre_2core_component_count": len(pre_components),
        "post_2core_component_count": len(post_components),
        "dominant_component_size": len(dominant),
        "articulation_point_count": len(articulation_points),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default="reports/part3_full_trace.json")
    args = parser.parse_args(argv)

    part_path = str(REPO_ROOT / "data" / "parts" / "Part3.stp")

    # Load already-computed candidate/gate data.
    existing: dict[str, dict] = {}
    for fname in ["baseline_matrix_principal.json", "baseline_matrix_diagonal.json"]:
        p = REPO_ROOT / "reports" / fname
        if p.exists():
            data = json.loads(p.read_text())
            existing.update(data.get("Part3", {}))

    results = {}
    for label, direction in ALL_DIRECTIONS.items():
        print(f"--- Part3 @ {label} ---")
        detail = _graph_detail(part_path, direction)
        base = existing.get(label, {})
        record = {**base, **detail}
        results[label] = record
        print(f"  pre_2core_comps={detail['pre_2core_component_count']} "
              f"post_2core_comps={detail['post_2core_component_count']} "
              f"dominant_size={detail['dominant_component_size']} "
              f"articulation_points={detail['articulation_point_count']}")
        if base:
            print(f"  [from baseline] candidates={base.get('candidate_count')} "
                  f"H3={base.get('h3_failures')} H4={base.get('h4_failures')} "
                  f"fully_valid={base.get('fully_valid_candidate_count')}")

    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nreport -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
