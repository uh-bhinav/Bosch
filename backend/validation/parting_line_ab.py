"""
backend/validation/parting_line_ab.py
-------------------------------------
A/B harness comparing the v1 and v2 parting-line engines across the fixture
corpus (plan P0 / P6).

**P0 role: establish the baseline.** v2 has no algorithm yet, so this currently
runs v1 across every fixture and records the table that every later phase is
measured against. Without a baseline, "optimized" and "improved" mean nothing
(plan point 4 / §11).

Usage::

    .micromamba/root/envs/dfm_agent/bin/python -m backend.validation.parting_line_ab
    ... --engine v1 --json reports/baseline_p0.json
    ... --parts F3,F11          # subset by fixture id or filename
    ... --optimize              # run the real direction optimizer on real parts
                                # (slow; default uses each fixture's declared
                                #  pull direction and +Z for the real parts)

Honesty notes baked into the output:

* v1 is **not** stage-instrumented (that is a v2 feature, plan §12.5), so only
  ``total_ms`` is reported for it. Per-stage p50/p95 arrive when v2 does.
* ``coverage`` here is v1's ``silhouette_coverage_ratio``, which uses
  **bounding-box** areas. Plan §8.1 replaces that with a shoelace numerator
  over a proper projected-outline denominator. The two are NOT comparable
  as-is, and the report says so rather than putting them in one column.
* Part3 has **no ground truth**. Its row is diagnostic, never a correctness
  score.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SYNTHETIC_DIR = REPO_ROOT / "data" / "fixtures" / "synthetic"
REAL_PARTS_DIR = REPO_ROOT / "data" / "parts"

#: The two real fixtures. F16 (Part3) deliberately carries no expected answer.
REAL_FIXTURES = [
    {
        "fixture_id": "F15",
        "name": "Part1",
        "filename": "Part1.stp",
        "pull_direction": [0.0, 0.0, 1.0],
        "expected": "coverage >= 0.90 (v1 achieves 94.8% at its optimal direction)",
        "analytic": False,
        "p1_expectation": "pass",
    },
    {
        "fixture_id": "F16",
        "name": "Part3",
        "filename": "Part3.stp",
        "pull_direction": [0.0, 0.0, 1.0],
        "expected": (
            "UNKNOWN — Bosch has not disclosed an expected solution. Scored on "
            "feasibility, fragmentation and honesty, NEVER on correctness."
        ),
        "analytic": False,
        "p1_expectation": "honest_result_or_honest_rejection",
    },
]


@dataclass
class RunResult:
    """One engine's result on one fixture."""

    fixture_id: str
    name: str
    engine: str
    status: str                       # "ok" | "error" | "not_implemented"
    total_ms: float = 0.0
    error: str | None = None
    measures: dict[str, Any] = field(default_factory=dict)
    stage_timings: dict[str, Any] | None = None

    def to_dict(self) -> dict:
        return {
            "fixture_id": self.fixture_id,
            "name": self.name,
            "engine": self.engine,
            "status": self.status,
            "total_ms": round(self.total_ms, 2),
            "error": self.error,
            "measures": self.measures,
            "stage_timings": self.stage_timings,
        }


def _load_corpus(subset: set[str] | None) -> list[dict]:
    """Synthetic fixtures from the manifest, plus the two real parts."""
    corpus: list[dict] = []

    manifest_path = SYNTHETIC_DIR / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for fixture in manifest.get("fixtures", []):
            fixture = dict(fixture)
            fixture["path"] = str(SYNTHETIC_DIR / fixture["filename"])
            fixture["kind"] = "synthetic"
            corpus.append(fixture)
    else:
        print(
            f"WARNING: {manifest_path} not found. Run "
            "scripts/generate_fixtures.py first.",
            file=sys.stderr,
        )

    for fixture in REAL_FIXTURES:
        path = REAL_PARTS_DIR / fixture["filename"]
        if not path.exists():
            continue
        fixture = dict(fixture)
        fixture["path"] = str(path)
        fixture["kind"] = "real"
        fixture["targets"] = "real Bosch geometry"
        corpus.append(fixture)

    if subset:
        corpus = [
            f for f in corpus
            if f["fixture_id"] in subset
            or f["name"] in subset
            or f["filename"] in subset
        ]
    return corpus


def _resolve_direction(fixture: dict, part: object, optimize: bool) -> tuple[float, float, float]:
    """
    Pull direction for this run.

    Synthetic fixtures declare theirs in the manifest — they were *designed*
    around a specific direction, so overriding it would invalidate the expected
    answer. Real parts default to +Z for speed; ``--optimize`` runs the real
    optimizer, which is what produced v1's published 94.8% figure.
    """
    if optimize and fixture["kind"] == "real":
        from backend.geometry.direction_optimizer import optimize_mold_direction

        result = optimize_mold_direction(part)  # type: ignore[arg-type]
        return tuple(float(c) for c in result.best_direction)  # type: ignore[return-value]
    return tuple(float(c) for c in fixture["pull_direction"])  # type: ignore[return-value]


def _run_v1(fixture: dict, optimize: bool) -> RunResult:
    from backend.geometry.parting_line import detect_parting_line_candidates
    from backend.geometry.step_loader import load_step

    result = RunResult(fixture["fixture_id"], fixture["name"], "v1", "ok")
    started = time.perf_counter()
    try:
        part = load_step(fixture["path"])
        direction = _resolve_direction(fixture, part, optimize)
        parting = detect_parting_line_candidates(part, direction, mutate=False)

        refinement = parting.refinement
        result.measures = {
            "pull_direction": [round(c, 6) for c in direction],
            "face_count": len(part.faces),
            "edge_count": len(part.edges),
            # --- what v1 reports (NOT directly comparable to v2's §8 measures) ---
            "v1_readiness_status": parting.readiness.status,
            "v1_readiness_score": round(parting.readiness.score, 4),
            "v1_refinement_confidence": round(refinement.confidence, 4),
            "v1_bbox_coverage_ratio": round(parting.silhouette_coverage_ratio, 4),
            # --- structural facts (ARE comparable across engines) ---
            "candidate_edge_count": len(parting.candidate_edge_ids),
            "silhouette_edge_count": len(parting.silhouette_edge_ids),
            "component_count": len(parting.components),
            "selected_is_closed": parting.selected_wire.is_closed,
            "branch_point_count": parting.selected_wire.branch_point_count,
            "gap_count": parting.selected_wire.gap_count,
            "closure_guaranteed": parting.closure_guaranteed,
            "closure_error_mm": round(parting.closure_error_mm, 6),
            "closure_bridge_edge_count": parting.closure_bridge_edge_count,
            "bridging_status": parting.bridging_status,
            "graph_cleanup_strategy": refinement.graph_cleanup.strategy,
            "parting_surface_status": parting.parting_surface.status,
            "parting_surface_strategy": parting.parting_surface.strategy,
            "warning_count": len(parting.warnings),
            # --- H0 cannot be evaluated for v1 ---
            "on_surface": None,
        }
    except Exception as exc:  # noqa: BLE001
        result.status = "error"
        result.error = f"{type(exc).__name__}: {exc}"
    result.total_ms = (time.perf_counter() - started) * 1000.0
    return result


def _run_v2(fixture: dict, optimize: bool) -> RunResult:
    """
    Run the v2 Level 0 pipeline (P1).

    ``no_feasible_candidate`` is reported as **status ``ok``** with
    ``outcome`` saying so — it is a correct, informative result, not an error.
    That distinction is the entire point of separating feasibility from
    scoring: on a sphere, "there is no edge-based silhouette here" is the
    right answer, and v1's equivalent run returns a confident wrong loop.
    """
    from backend.config import settings
    from backend.geometry.parting_line_v2 import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line
    from backend.geometry.step_loader import load_step

    result = RunResult(fixture["fixture_id"], fixture["name"], "v2", "ok")
    started = time.perf_counter()
    try:
        part = load_step(fixture["path"])
        direction = _resolve_direction(fixture, part, optimize)
        analysis = analyse_parting_line(
            part,
            PullDirectionInput(direction, "optimizer" if optimize else "fixture"),
            undercuts=UndercutInput.empty(),
            cfg=settings.dfm.parting_line_v2,
        )
        selected = analysis.selected
        score = selected.score if selected else None
        on_surface = selected.feasibility.on_surface if selected and selected.feasibility else None

        result.measures = {
            "pull_direction": [round(c, 6) for c in direction],
            "face_count": len(part.faces),
            "edge_count": len(part.edges),
            "outcome": analysis.outcome,
            # --- Track A ---
            "track_a_segments": analysis.track_a_summary.get("segment_count", 0),
            "track_a_kinds": analysis.track_a_summary.get("segment_kinds", {}),
            # --- graph reduction (P3a will aggregate these) ---
            "cyclomatic_number": analysis.bounds.cyclomatic_number,
            "branch_node_count": analysis.bounds.branch_node_count,
            "node_count": analysis.bounds.node_count,
            "component_count": analysis.reduction.get("component_count", 0),
            "strategy": analysis.bounds.strategy,
            "candidates_found": analysis.bounds.candidates_found,
            "k_max_hit": analysis.bounds.k_max_hit,
            # --- filter ---
            "rejection_summary": analysis.rejection_summary,
            "referral_count": len(analysis.referrals),
            # --- H0, the on-surface invariant ---
            "on_surface": (
                {
                    "passed": on_surface.passed,
                    "max_edge_deviation_mm": on_surface.max_edge_deviation_mm,
                    "max_surface_deviation_mm": on_surface.max_surface_deviation_mm,
                }
                if on_surface else None
            ),
            # --- scorecard (§8 measures) ---
            "coverage": round(score.coverage, 6) if score else None,
            "coverage_is_exact": score.coverage_is_exact if score else None,
            "pull_axis_span_mm": round(score.pull_axis_span_mm, 4) if score else None,
            "excess_turning": round(score.excess_turning, 6) if score else None,
            "length_3d_mm": round(score.length_3d_mm, 4) if score else None,
            "ambiguous_area_fraction": round(score.ambiguous_area_fraction, 6) if score else None,
            "stable_id": score.stable_id if score else None,
            "won_at_tier": score.won_at_tier if score else None,
            # --- core/cavity from H3's regions ---
            "cavity_face_count": len(analysis.regions.cavity_face_ids) if analysis.regions else 0,
            "core_face_count": len(analysis.regions.core_face_ids) if analysis.regions else 0,
            "inconsistent_face_count": (
                len(analysis.regions.inconsistent_face_ids) if analysis.regions else 0
            ),
        }
        result.stage_timings = analysis.timings.to_dict()
    except Exception as exc:  # noqa: BLE001
        result.status = "error"
        result.error = f"{type(exc).__name__}: {exc}"
    result.total_ms = (time.perf_counter() - started) * 1000.0
    return result


def _print_table(results: list[RunResult], corpus_by_id: dict[str, dict]) -> None:
    engine = results[0].engine if results else "v1"
    if engine == "v2":
        header = (
            f"{'id':<5}{'fixture':<34}{'outcome':<24}{'mu':>4}{'brch':>5}"
            f"{'cand':>5}{'cover':>8}{'span':>8}{'H0dev':>10}{'tier':>6}{'ms':>8}"
        )
        print("\n" + header)
        print("-" * len(header))
        for run in results:
            if run.status != "ok":
                print(f"{run.fixture_id:<5}{run.name:<34}ERROR  {(run.error or '')[:70]}")
                continue
            m = run.measures
            cov = f"{m['coverage'] * 100:>7.1f}%" if m.get("coverage") is not None else "       -"
            span = f"{m['pull_axis_span_mm']:>8.2f}" if m.get("pull_axis_span_mm") is not None else "       -"
            dev = (
                f"{m['on_surface']['max_edge_deviation_mm']:>10.2e}"
                if m.get("on_surface") else "         -"
            )
            print(
                f"{run.fixture_id:<5}{run.name:<34}{m['outcome']:<24}"
                f"{m['cyclomatic_number']:>4}{m['branch_node_count']:>5}"
                f"{m['candidates_found']:>5}{cov}{span}{dev}"
                f"{str(m.get('won_at_tier') or '-'):>6}{run.total_ms:>8.1f}"
            )
        return

    header = (
        f"{'id':<5}{'fixture':<36}{'status':<9}{'closed':<8}{'comp':>5}"
        f"{'brch':>5}{'bboxCov':>9}{'surface':<20}{'ms':>9}"
    )
    print("\n" + header)
    print("-" * len(header))
    for run in results:
        if run.status != "ok":
            print(f"{run.fixture_id:<5}{run.name:<36}{run.status:<9}"
                  f"{(run.error or '')[:60]}")
            continue
        m = run.measures
        print(
            f"{run.fixture_id:<5}{run.name:<36}{run.status:<9}"
            f"{str(m['selected_is_closed']):<8}"
            f"{m['component_count']:>5}"
            f"{m['branch_point_count']:>5}"
            f"{m['v1_bbox_coverage_ratio'] * 100:>8.1f}%"
            f"  {m['parting_surface_status']:<18}"
            f"{run.total_ms:>9.1f}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=["v1", "v2", "both"], default="v1")
    parser.add_argument("--parts", default="", help="comma-separated fixture ids/names")
    parser.add_argument("--optimize", action="store_true",
                        help="run the real direction optimizer on real parts (slow)")
    parser.add_argument("--json", default="", help="write the full report here")
    args = parser.parse_args(argv)

    subset = {s.strip() for s in args.parts.split(",") if s.strip()} or None
    corpus = _load_corpus(subset)
    if not corpus:
        print("No fixtures found.", file=sys.stderr)
        return 2

    engines = ["v1", "v2"] if args.engine == "both" else [args.engine]
    runners = {"v1": _run_v1, "v2": _run_v2}

    print(f"Corpus: {len(corpus)} fixture(s) | engines: {', '.join(engines)}")
    if args.optimize:
        print("Direction: real optimizer on real parts (slow)")
    else:
        print("Direction: each fixture's declared direction; +Z for real parts")

    all_results: list[RunResult] = []
    for engine in engines:
        engine_results = [runners[engine](f, args.optimize) for f in corpus]
        all_results.extend(engine_results)
        _print_table(engine_results, {f["fixture_id"]: f for f in corpus})

    ok = [r for r in all_results if r.status == "ok"]
    errors = [r for r in all_results if r.status == "error"]
    times = [r.total_ms for r in ok]

    print(f"\n{len(ok)} ok, {len(errors)} error(s), "
          f"{len([r for r in all_results if r.status == 'not_implemented'])} not implemented")
    if times:
        print(f"runtime  p50 {statistics.median(times):8.1f} ms   "
              f"p95 {sorted(times)[max(0, int(0.95 * (len(times) - 1)))]:8.1f} ms   "
              f"max {max(times):8.1f} ms")
    if errors:
        print("\nERRORS:")
        for run in errors:
            print(f"  {run.fixture_id} {run.name}: {run.error}")

    report = {
        "generated_by": "backend/validation/parting_line_ab.py",
        "phase": "P0 baseline",
        "engines": engines,
        "direction_mode": "optimizer" if args.optimize else "declared",
        "caveats": [
            "v1 is NOT stage-instrumented; only total_ms is available for it. "
            "Per-stage p50/p95 (plan §12.5) arrive with v2.",
            "v1_bbox_coverage_ratio uses BOUNDING-BOX areas. Plan §8.1 replaces "
            "this with a shoelace numerator over a proper projected-outline "
            "denominator. The two are not directly comparable.",
            "F16 (Part3) has NO ground truth. Its row is diagnostic only and "
            "must never be reported as a correctness score.",
        ],
        "corpus": [
            {k: v for k, v in f.items() if k != "path"} for f in corpus
        ],
        "results": [r.to_dict() for r in all_results],
    }
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"\nreport -> {out}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
