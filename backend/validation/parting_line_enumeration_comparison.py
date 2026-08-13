"""
backend/validation/parting_line_enumeration_comparison.py
--------------------------------------------------------------
READ-ONLY diagnostic experiment (Track A of the 2026-08-12 investigation):
does a broader enumeration strategy expose a valid separating candidate for
Part1 +X/+Y that the current fundamental-cycle-basis strategy misses?

Runs the SAME graph (built exactly as production does) through:
  1. "basis"   -- the current default (mu_max_for_johnson is irrelevant here)
  2. "johnson" -- exhaustive-ish simple-cycle enumeration, with
     mu_max_for_johnson/max_candidates/time_budget_s overridden HERE, as
     function-call parameters to extract_loops, for this diagnostic only.
     Nothing in config.yaml or backend/config.py is touched.

Every resulting loop (from both strategies) is run through the REAL
evaluate_gates (H0-H7), unmodified. This does not change production
ranking, H3, or H4 -- it only asks more candidates the same, unmodified
questions.

Binary question this answers: does EITHER strategy produce a candidate that
passes H3 (separates into 2 regions) with a materially better H4 result (or
outright passes) than what "basis" already finds? If yes: enumeration-space
limitation, confirmed. If no: the limitation is not about how many cycles
are examined -- something else is wrong, and enumeration should stop being
suspected.
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


def _run_strategy(graph, stats, cfg, strategy: str, *, mu_max: int, max_candidates: int, time_budget_s: float):
    from backend.geometry.parting_line_v2.graph import extract_loops

    started = time.perf_counter()
    loops, actual_strategy, cap_hit = extract_loops(
        graph, stats, max_candidates=max_candidates, mu_max_for_johnson=mu_max,
        time_budget_s=time_budget_s, strategy=strategy,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return loops, actual_strategy, cap_hit, elapsed_ms


def _evaluate(part, graph, loops, pull_direction, cfg, bbox_diagonal_mm, part_projected_area_mm2):
    from dataclasses import replace

    from backend.geometry.parting_line_v2.contracts import UndercutInput
    from backend.geometry.parting_line_v2.gates import evaluate_gates
    from backend.geometry.parting_line_v2.types import PartingLoopCandidate

    undercuts = UndercutInput.empty()
    candidates = []
    for index, (segment_ids, points) in enumerate(loops):
        candidate = PartingLoopCandidate(
            candidate_id=index,
            segments=tuple(graph.segments_by_id[s] for s in segment_ids),
            points=points, is_closed=True, discovered_by="cycle_basis",
        )
        outcome = evaluate_gates(
            candidate, part, pull_direction, undercuts=undercuts, cfg=cfg,
            bbox_diagonal_mm=bbox_diagonal_mm, part_projected_area_mm2=part_projected_area_mm2,
        )
        candidate = replace(candidate, feasibility=outcome.report)
        candidates.append(candidate)
    return candidates


def _summarize(candidates, loops) -> dict:
    h3_pass = [c for c in candidates if c.feasibility and c.feasibility.measurements.get("h3_region_count") == 2.0]
    h4_pass = [c for c in candidates if c.feasibility and (
        c.feasibility.passed or c.feasibility.failed_gate not in ("H0", "H1", "H2", "H3", "H4")
    )]
    fully_passed = [c for c in candidates if c.feasibility and c.feasibility.passed]
    max_size = max((len(c.segments) for c in candidates), default=0)

    best = None
    if h3_pass:
        # "best" = passed H3, with the smallest H4 violation fraction (closest to passing).
        best = min(
            h3_pass,
            key=lambda c: c.feasibility.measurements.get("h4_orientation_violation_fraction", 1.0)
        )

    return {
        "cycles_examined": len(loops),
        "max_cycle_size": max_size,
        "h3_pass_count": len(h3_pass),
        "h4_or_later_pass_count": len(h4_pass),
        "fully_passed_count": len(fully_passed),
        "best_h3_passing_candidate": (
            {
                "candidate_id": best.candidate_id, "segment_count": len(best.segments),
                "failed_gate": best.feasibility.failed_gate,
                "h4_violation_fraction": best.feasibility.measurements.get("h4_orientation_violation_fraction"),
                "reason": best.feasibility.reason,
            } if best else None
        ),
    }


def _compare(part_path: str, direction_label: str) -> dict:
    from backend.config import settings
    from backend.geometry.parting_line_v2 import measures
    from backend.geometry.parting_line_v2.contracts import PullDirectionInput
    from backend.geometry.parting_line_v2.engine import _bbox_diagonal
    from backend.geometry.parting_line_v2.graph import build_graph, reduce_to_two_core
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
        [f.area for f in valid_faces],
        [mean_abs_g(f, pull.direction, cfg.face_sample_grid) for f in valid_faces],
    )

    track_a = detect_edge_silhouettes(part, pull.direction, cfg=cfg, bbox_diagonal_mm=bbox_diagonal)
    track_b = detect_face_silhouettes(
        part, pull.direction, cfg=cfg, bbox_diagonal_mm=bbox_diagonal,
        start_segment_id=len(track_a.segments),
    )
    stitched = stitch_tracks(
        part, track_a.segments, track_b.segments,
        tolerance_mm=max(cfg.stitch_snap_tolerance_rel * bbox_diagonal, 1e-6),
    )
    graph = build_graph(stitched.segments, bbox_diagonal_mm=bbox_diagonal, cfg=cfg)
    stats = reduce_to_two_core(graph)

    results = {}
    for label, strategy, mu_max, max_cand, budget in [
        ("basis", "basis", cfg.mu_max_for_johnson, cfg.max_candidates, cfg.enumeration_time_budget_s),
        ("johnson", "johnson", 500, 5000, 60.0),  # diagnostic-only override
    ]:
        loops, actual_strategy, cap_hit, elapsed_ms = _run_strategy(
            graph, stats, cfg, strategy, mu_max=mu_max, max_candidates=max_cand, time_budget_s=budget
        )
        candidates = _evaluate(part, graph, loops, pull.direction, cfg, bbox_diagonal, part_projected_area)
        summary = _summarize(candidates, loops)
        summary.update({
            "requested_strategy": strategy, "actual_strategy": actual_strategy,
            "cap_or_budget_hit": cap_hit, "runtime_ms": round(elapsed_ms, 1),
            "mu": stats.cyclomatic_number, "branch_node_count": stats.branch_node_count,
        })
        results[label] = summary

    return {
        "direction_label": direction_label, "direction": list(pull.direction),
        "mu": stats.cyclomatic_number, "branch_node_count": stats.branch_node_count,
        "node_count": stats.nodes_after, "edge_count": stats.edges_after,
        "strategies": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default="reports/enumeration_comparison_part1.json")
    args = parser.parse_args(argv)

    part_path = str(REPO_ROOT / "data" / "parts" / "Part1.stp")
    results = {}
    for direction in ["+X", "+Y"]:
        print(f"--- Part1 @ {direction} ---")
        record = _compare(part_path, direction)
        results[direction] = record
        print(f"  mu={record['mu']} branch={record['branch_node_count']} "
              f"nodes={record['node_count']} edges={record['edge_count']}")
        for strat_name, s in record["strategies"].items():
            print(f"  [{strat_name}] examined={s['cycles_examined']} max_size={s['max_cycle_size']} "
                  f"h3_pass={s['h3_pass_count']} fully_passed={s['fully_passed_count']} "
                  f"runtime={s['runtime_ms']}ms cap_hit={s['cap_or_budget_hit']}")
            print(f"           best_h3_passing={s['best_h3_passing_candidate']}")

    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nreport -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
