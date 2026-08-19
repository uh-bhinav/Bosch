"""
Read-only diagnostic (2026-08-19): instruments `optimize_mold_direction`'s
per-candidate Boolean-undercut and parting-line-feasibility timing on a real
part, WITHOUT modifying production code -- monkeypatches two already-private
module functions (`_run_isolated_undercut_detection`,
`_cached_is_parting_line_feasible`) at the call boundary, runs the real
unmodified search, then restores them. Never imported by the runtime
pipeline (see README §4's description of this directory).

Purpose: answer, with real measured numbers rather than memory/assumption --
how many candidate directions are actually Boolean-refined, whether O24's
`direction_parallelism` batching is actually overlapping wall time (not just
configured), and where Part1's ~195-350s full-analysis time actually goes.

Usage:
    python -m backend.validation.direction_search_timing_diagnostic Part1.stp
    python -m backend.validation.direction_search_timing_diagnostic Part3.stp
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.config import settings  # noqa: E402
from backend.geometry import direction_optimizer as opt_mod  # noqa: E402
from backend.geometry.step_loader import load_step  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    filename = argv[0] if argv else "Part1.stp"
    part_path = Path(__file__).resolve().parents[2] / "data" / "parts" / filename

    boolean_events: list[dict] = []
    parting_events: list[dict] = []
    lock = threading.Lock()

    orig_boolean = opt_mod._run_isolated_undercut_detection
    orig_parting = opt_mod._cached_is_parting_line_feasible

    def wrapped_boolean(part, direction, max_boolean_faces):
        t0 = time.perf_counter()
        tid = threading.get_ident()
        result = orig_boolean(part, direction, max_boolean_faces)
        elapsed = time.perf_counter() - t0
        with lock:
            boolean_events.append({
                "direction": [round(v, 4) for v in direction],
                "thread_id": tid,
                "elapsed_s": round(elapsed, 3),
                "evaluation_failed": result.evaluation_failed,
                "start_offset_s": None,  # filled in below relative to t_search_start
                "t0": t0,
            })
        return result

    def wrapped_parting(*args, **kwargs):
        t0 = time.perf_counter()
        tid = threading.get_ident()
        result = orig_parting(*args, **kwargs)
        elapsed = time.perf_counter() - t0
        with lock:
            parting_events.append({
                "thread_id": tid,
                "elapsed_s": round(elapsed, 3),
                "t0": t0,
            })
        return result

    opt_mod._run_isolated_undercut_detection = wrapped_boolean
    opt_mod._cached_is_parting_line_feasible = wrapped_parting
    try:
        part = load_step(str(part_path))
        t_search_start = time.perf_counter()
        result = opt_mod.optimize_mold_direction(part)
        total_wall_s = time.perf_counter() - t_search_start
    finally:
        opt_mod._run_isolated_undercut_detection = orig_boolean
        opt_mod._cached_is_parting_line_feasible = orig_parting

    for e in boolean_events:
        e["start_offset_s"] = round(e.pop("t0") - t_search_start, 3)
    for e in parting_events:
        e["start_offset_s"] = round(e.pop("t0") - t_search_start, 3)

    sum_boolean_s = sum(e["elapsed_s"] for e in boolean_events)
    sum_parting_s = sum(e["elapsed_s"] for e in parting_events)
    distinct_threads = len({e["thread_id"] for e in boolean_events})

    report = {
        "part": filename,
        "configured_direction_parallelism": settings.dfm.direction_search.direction_parallelism,
        "total_wall_time_s": round(total_wall_s, 3),
        "analysis_time_s_reported_by_result": round(result.analysis_time_s, 3),
        "winning_direction": result.best_direction,
        "winning_label": result.best_label,
        "optimal_found": result.optimal_found,
        "best_evidence_tier": result.best_evidence_tier,
        "search_stage_reached": result.search_stage_reached,
        "candidates_scored_total": len(result.candidates),
        "boolean_refined_candidate_count": result.boolean_refined_candidate_count,
        "boolean_pruned_candidate_count": result.boolean_pruned_candidate_count,
        "boolean_survivor_candidate_count": result.boolean_survivor_candidate_count,
        "direction_cache_hits": result.direction_cache_hits,
        "direction_cache_misses": result.direction_cache_misses,
        "boolean_undercut_checks": {
            "count": len(boolean_events),
            "sum_of_individual_times_s": round(sum_boolean_s, 3),
            "distinct_worker_threads_used": distinct_threads,
            "parallel_speedup_factor": round(sum_boolean_s / total_wall_s, 2) if total_wall_s > 0 else None,
            "events": boolean_events,
        },
        "parting_line_feasibility_checks": {
            "count": len(parting_events),
            "sum_of_individual_times_s": round(sum_parting_s, 3),
            "events": parting_events,
        },
        "note": (
            "Boolean checks within one O24 batch run concurrently (separate "
            "subprocesses dispatched from separate threads), so their "
            "start_offset_s values overlapping is the actual evidence "
            "parallelism is live -- sum_of_individual_times_s is NOT wall "
            "time, it is what sequential (direction_parallelism=1) execution "
            "would have cost for the same candidates. parting_line_feasibility "
            "checks run strictly sequentially in the main thread (never "
            "batched), so their sum IS wall time for that portion."
        ),
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
