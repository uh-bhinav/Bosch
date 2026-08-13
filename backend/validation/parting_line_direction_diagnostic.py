"""
backend/validation/parting_line_direction_diagnostic.py
------------------------------------------------------------
P3.3 Step 1 (2026-08-13): a direction-ONLY diagnostic layer, computed
BEFORE any parting-line candidate is judged.

Purpose: "given direction d, does the geometry itself look plausibly
moldable?" -- a diagnostic signal, NOT proof a parting line exists, and
independent of whether the v2 pipeline finds a valid candidate. Ranking
directions by this layer FIRST, then checking parting-line outcome
separately, avoids the circular reasoning "the parting-line algorithm
liked this direction, therefore the direction must be good."

Deliberately reuses existing moldability machinery instead of inventing a
new score:
  - backend.geometry.draft_analyzer.analyze_draft() (mutate=False) for the
    draft-angle distribution (good/marginal/bad area, severity).
  - backend.geometry.undercut_detector.detect_undercuts() (mutate=False,
    boolean_refine=False -- fast proxy only, this is a screening layer
    across many directions, not a final DfM verdict) for undercut area.
  - FaceData.signed_dot() (already on every face) for the positive /
    negative / near-zero sign(g) area split, using the SAME
    silhouette_epsilon threshold parting_line_v2 itself uses for its
    zero-draft band (config.yaml dfm.parting_line_v2.silhouette_epsilon),
    so "near-zero" here means the same thing it means to the parting-line
    engine, not a newly invented cutoff.

Read-only. No production code touched. Manual directions only.
"""

from __future__ import annotations

import argparse
import json
import math
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


def _normalize(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def _direction_only_metrics(part_path: str, direction: tuple) -> dict:
    from backend.config import settings
    from backend.geometry.draft_analyzer import analyze_draft
    from backend.geometry.undercut_detector import detect_undercuts
    from backend.geometry.step_loader import load_step

    part = load_step(part_path)
    d = _normalize(direction)
    cfg = settings.dfm.parting_line_v2
    eps = cfg.silhouette_epsilon

    draft = analyze_draft(part, d, pull_direction_label="direction-only-scan", mutate=False)
    undercuts = detect_undercuts(part, d, mutate=False, boolean_refine=False)

    total_area = 0.0
    positive_area = 0.0
    negative_area = 0.0
    near_zero_area = 0.0
    skipped_area = 0.0
    for face in part.faces:
        if not face.normal_valid:
            skipped_area += face.area
            continue
        g = face.signed_dot(d)
        total_area += face.area
        if g > eps:
            positive_area += face.area
        elif g < -eps:
            negative_area += face.area
        else:
            near_zero_area += face.area

    return {
        "direction": d,
        "total_analysed_area_mm2": round(total_area, 3),
        "positive_area_mm2": round(positive_area, 3),
        "negative_area_mm2": round(negative_area, 3),
        "near_zero_area_mm2": round(near_zero_area, 3),
        "skipped_area_mm2": round(skipped_area, 3),
        "positive_area_pct": round(100.0 * positive_area / total_area, 2) if total_area else 0.0,
        "negative_area_pct": round(100.0 * negative_area / total_area, 2) if total_area else 0.0,
        "near_zero_area_pct": round(100.0 * near_zero_area / total_area, 2) if total_area else 0.0,
        "draft_good_pct": round(draft.good_pct, 2),
        "draft_marginal_pct": round(draft.marginal_pct, 2),
        "draft_bad_pct": round(draft.bad_pct, 2),
        "draft_severity": draft.severity,
        "undercut_area_mm2": round(undercuts.undercut_area_mm2, 3),
        "undercut_area_pct": round(undercuts.undercut_area_pct, 2),
        "undercut_face_count": len(undercuts.undercut_face_ids),
        "silhouette_epsilon_used": eps,
    }


def _moldability_rank_key(metrics: dict) -> tuple:
    """
    Lower is more promising. Deliberately simple and inspectable, not a
    fitted score: near-zero (ambiguous/ill-defined-side) area is the
    strongest direction-only red flag for parting-line feasibility (a face
    the engine cannot cleanly assign to either mold half), then undercut
    area, then bad-draft area. No weighting/tuning -- lexicographic, so the
    ranking itself is auditable without hidden coefficients.
    """
    return (
        metrics["near_zero_area_pct"],
        metrics["undercut_area_pct"],
        metrics["draft_bad_pct"],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default="reports/parting_line_direction_diagnostic.json")
    args = parser.parse_args(argv)

    targets = [
        ("Part1", str(REPO_ROOT / "data" / "parts" / "Part1.stp"), ALL_DIRECTIONS),
        ("Part3", str(REPO_ROOT / "data" / "parts" / "Part3.stp"), ALL_DIRECTIONS),
    ]

    results: dict[str, dict] = {}
    for part_name, path, directions in targets:
        print(f"=== {part_name} ===")
        part_results = {}
        for label, direction in directions.items():
            metrics = _direction_only_metrics(path, direction)
            part_results[label] = metrics
            print(
                f"  {label:>9}: near_zero={metrics['near_zero_area_pct']:5.1f}%  "
                f"undercut={metrics['undercut_area_pct']:5.1f}%  "
                f"draft_bad={metrics['draft_bad_pct']:5.1f}%  "
                f"draft_good={metrics['draft_good_pct']:5.1f}%"
            )
        ranked = sorted(part_results.items(), key=lambda kv: _moldability_rank_key(kv[1]))
        print(f"  --- {part_name} ranked most-to-least promising (direction-only) ---")
        for rank, (label, metrics) in enumerate(ranked, start=1):
            print(f"    {rank}. {label}  (near_zero={metrics['near_zero_area_pct']:.1f}%, "
                  f"undercut={metrics['undercut_area_pct']:.1f}%, bad={metrics['draft_bad_pct']:.1f}%)")
        results[part_name] = {
            "per_direction": part_results,
            "ranked_most_promising_first": [label for label, _ in ranked],
        }

    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nreport -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
