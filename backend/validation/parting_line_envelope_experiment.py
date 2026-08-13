"""
backend/validation/parting_line_envelope_experiment.py
------------------------------------------------------------
READ-ONLY diagnostic (Part3 envelope experiment, 2026-08-12): does removing
the articulation-attached facet branches (confirmed genuine geometric
pinches, not stitching artifacts -- see the connectivity-localization
diagnosis) let basis/Johnson enumeration find a better global candidate on
what remains?

Builds a DIAGNOSTIC-ONLY copy of the reduced graph containing only the
"envelope" (the dominant component with every articulation-point-attached
facet branch stripped, iteratively, exactly as the prior diagnosis did).
Recomputes ReductionStats for that subgraph specifically (its own node/edge
count, branch count, cyclomatic number -- NOT the full graph's), then runs
the real, unmodified extract_loops and evaluate_gates against it.

Nothing in backend/geometry/parting_line_v2/ is modified. This never
touches production code -- the envelope graph exists only inside this
script's memory for one diagnostic run.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DIRECTIONS = {"+X": (1.0, 0.0, 0.0), "-X": (-1.0, 0.0, 0.0),
              "+Y": (0.0, 1.0, 0.0), "-Y": (0.0, -1.0, 0.0)}


def _envelope_nodes(graph) -> set[int]:
    """Iteratively strip articulation-point-attached branches (smaller side
    each time) from the dominant component until none remain."""
    import networkx as nx

    def components():
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

    dominant = max(components(), key=len)
    simple = nx.Graph()
    simple.add_nodes_from(dominant)
    for n in dominant:
        for nb, _ in graph.adjacency.get(n, ()):
            if nb in dominant:
                simple.add_edge(n, nb)

    envelope = simple.copy()
    for _ in range(50):
        if envelope.number_of_nodes() <= 2:
            break
        cuts = list(nx.articulation_points(envelope))
        if not cuts:
            break
        to_remove: set[int] = set()
        for c in cuts:
            g2 = envelope.copy()
            g2.remove_node(c)
            pieces = sorted(nx.connected_components(g2), key=len)
            to_remove |= pieces[0]
        if not to_remove:
            break
        envelope.remove_nodes_from(to_remove)
    return set(envelope.nodes())


def _build_envelope_graph(graph, envelope_nodes: set[int]):
    """Diagnostic-only SilhouetteGraph restricted to envelope_nodes."""
    from backend.geometry.parting_line_v2.graph import SilhouetteGraph

    env = SilhouetteGraph(weld_tolerance_mm=graph.weld_tolerance_mm)
    env.node_points = {n: p for n, p in graph.node_points.items() if n in envelope_nodes}
    env.adjacency = {
        n: [(nb, sid) for nb, sid in graph.adjacency.get(n, ()) if nb in envelope_nodes]
        for n in envelope_nodes
    }
    kept_segment_ids = {sid for n in envelope_nodes for _, sid in env.adjacency.get(n, ())}
    env.segment_nodes = {
        sid: nodes for sid, nodes in graph.segment_nodes.items()
        if sid in kept_segment_ids and nodes[0] in envelope_nodes and nodes[1] in envelope_nodes
    }
    env.segments_by_id = {sid: seg for sid, seg in graph.segments_by_id.items() if sid in kept_segment_ids}
    return env


def _stats_for(env) -> "ReductionStats":  # noqa: F821
    from backend.geometry.parting_line_v2.graph import ReductionStats

    nodes_after = len(env.node_points)
    edges_after = len(env.segment_nodes)
    branch = sum(1 for n in env.adjacency if len(env.adjacency[n]) > 2)

    def components():
        seen: set[int] = set()
        comps = []
        for start in sorted(env.adjacency):
            if start in seen:
                continue
            stack, group = [start], []
            seen.add(start)
            while stack:
                n = stack.pop()
                group.append(n)
                for nb, _ in env.adjacency.get(n, ()):
                    if nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
            comps.append(group)
        return comps

    comps = components()
    mu = edges_after - nodes_after + len(comps) if nodes_after else 0
    return ReductionStats(
        nodes_before=nodes_after, edges_before=edges_after,
        nodes_after=nodes_after, edges_after=edges_after,
        branch_node_count=branch, component_count=len(comps),
        cyclomatic_number=max(0, mu),
    )


def _evaluate_and_summarize(part, env, loops, pull_direction, cfg, bbox_diagonal_mm, part_projected_area_mm2):
    from dataclasses import replace

    from backend.geometry.parting_line_v2.contracts import UndercutInput
    from backend.geometry.parting_line_v2.gates import evaluate_gates
    from backend.geometry.parting_line_v2.types import PartingLoopCandidate

    faces_by_id = {f.face_id: f for f in part.faces}
    undercuts = UndercutInput.empty()
    h3_pass = []
    max_size = 0
    for index, (segment_ids, points) in enumerate(loops):
        max_size = max(max_size, len(segment_ids))
        candidate = PartingLoopCandidate(
            candidate_id=index, segments=tuple(env.segments_by_id[s] for s in segment_ids),
            points=points, is_closed=True, discovered_by="cycle_basis",
        )
        outcome = evaluate_gates(
            candidate, part, pull_direction, undercuts=undercuts, cfg=cfg,
            bbox_diagonal_mm=bbox_diagonal_mm, part_projected_area_mm2=part_projected_area_mm2,
        )
        candidate = replace(candidate, feasibility=outcome.report)
        if outcome.separation and outcome.separation.component_count == 2:
            a = sum(faces_by_id[f].area for f in outcome.separation.components[0] if f in faces_by_id)
            b = sum(faces_by_id[f].area for f in outcome.separation.components[1] if f in faces_by_id)
            frac = min(a, b) / (a + b) if (a + b) > 0 else 0.0
            h3_pass.append((candidate, frac))

    best_violation = None
    best_balance = None
    if h3_pass:
        best_violation = min(
            h3_pass, key=lambda cf: cf[0].feasibility.measurements.get("h4_orientation_violation_fraction", 1.0)
        )
        best_balance = max(h3_pass, key=lambda cf: cf[1])
    fully_passed = sum(1 for c, _ in h3_pass if c.feasibility.passed)

    return {
        "cycles_examined": len(loops), "max_cycle_size": max_size,
        "h3_pass_count": len(h3_pass), "fully_passed_count": fully_passed,
        "best_by_violation": (
            {"segment_count": len(best_violation[0].segments), "area_balance": round(best_violation[1], 4),
             "h4_violation": best_violation[0].feasibility.measurements.get("h4_orientation_violation_fraction"),
             "failed_gate": best_violation[0].feasibility.failed_gate}
            if best_violation else None
        ),
        "best_by_balance": (
            {"segment_count": len(best_balance[0].segments), "area_balance": round(best_balance[1], 4),
             "h4_violation": best_balance[0].feasibility.measurements.get("h4_orientation_violation_fraction"),
             "failed_gate": best_balance[0].feasibility.failed_gate}
            if best_balance else None
        ),
    }


def _run(part_path: str, direction_label: str) -> dict:
    from backend.config import settings
    from backend.geometry.parting_line_v2 import measures
    from backend.geometry.parting_line_v2.contracts import PullDirectionInput
    from backend.geometry.parting_line_v2.engine import _bbox_diagonal
    from backend.geometry.parting_line_v2.graph import build_graph, extract_loops, reduce_to_two_core
    from backend.geometry.parting_line_v2.regions import mean_abs_g
    from backend.geometry.parting_line_v2.stitch import stitch_tracks
    from backend.geometry.parting_line_v2.track_a import detect_edge_silhouettes
    from backend.geometry.parting_line_v2.track_b import detect_face_silhouettes
    from backend.geometry.step_loader import load_step

    cfg = settings.dfm.parting_line_v2
    part = load_step(part_path)
    pull = PullDirectionInput(DIRECTIONS[direction_label], "manual")
    assert pull.is_correctness_evidence
    bbox_diagonal = _bbox_diagonal(part)

    valid_faces = [f for f in part.faces if f.normal_valid]
    part_projected_area = measures.cauchy_projected_area(
        [f.area for f in valid_faces], [mean_abs_g(f, pull.direction, cfg.face_sample_grid) for f in valid_faces]
    )

    track_a = detect_edge_silhouettes(part, pull.direction, cfg=cfg, bbox_diagonal_mm=bbox_diagonal)
    track_b = detect_face_silhouettes(
        part, pull.direction, cfg=cfg, bbox_diagonal_mm=bbox_diagonal, start_segment_id=len(track_a.segments)
    )
    stitched = stitch_tracks(
        part, track_a.segments, track_b.segments,
        tolerance_mm=max(cfg.stitch_snap_tolerance_rel * bbox_diagonal, 1e-6),
    )
    graph = build_graph(stitched.segments, bbox_diagonal_mm=bbox_diagonal, cfg=cfg)
    reduce_to_two_core(graph)

    envelope_nodes = _envelope_nodes(graph)
    env = _build_envelope_graph(graph, envelope_nodes)
    env_stats = _stats_for(env)

    results = {}
    for label, strategy, mu_max, max_cand, budget in [
        ("basis", "basis", cfg.mu_max_for_johnson, cfg.max_candidates, cfg.enumeration_time_budget_s),
        ("johnson", "johnson", 500, 5000, 60.0),
    ]:
        started = time.perf_counter()
        loops, actual_strategy, cap_hit = extract_loops(
            env, env_stats, max_candidates=max_cand, mu_max_for_johnson=mu_max,
            time_budget_s=budget, strategy=strategy,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        summary = _evaluate_and_summarize(
            part, env, loops, pull.direction, cfg, bbox_diagonal, part_projected_area
        )
        summary.update({"actual_strategy": actual_strategy, "cap_hit": cap_hit, "runtime_ms": round(elapsed_ms, 1)})
        results[label] = summary

    return {
        "direction_label": direction_label, "direction": list(pull.direction),
        "envelope_node_count": len(envelope_nodes),
        "envelope_edge_count": len(env.segment_nodes),
        "envelope_branch_node_count": env_stats.branch_node_count,
        "envelope_mu": env_stats.cyclomatic_number,
        "strategies": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default="reports/envelope_experiment_part3.json")
    args = parser.parse_args(argv)

    part_path = str(REPO_ROOT / "data" / "parts" / "Part3.stp")
    results = {}
    for direction in ["+X", "+Y"]:
        print(f"--- Part3 envelope @ {direction} ---")
        record = _run(part_path, direction)
        results[direction] = record
        print(f"  envelope: nodes={record['envelope_node_count']} edges={record['envelope_edge_count']} "
              f"branch={record['envelope_branch_node_count']} mu={record['envelope_mu']}")
        for strat_name, s in record["strategies"].items():
            print(f"  [{strat_name}] examined={s['cycles_examined']} max_size={s['max_cycle_size']} "
                  f"h3_pass={s['h3_pass_count']} fully_passed={s['fully_passed_count']} "
                  f"runtime={s['runtime_ms']}ms cap_hit={s['cap_hit']}")
            print(f"           best_by_violation={s['best_by_violation']}")
            print(f"           best_by_balance={s['best_by_balance']}")

    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nreport -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
