"""
backend/validation/parting_line_baseline_matrix.py
------------------------------------------------------------
Clean baseline matrix (2026-08-12): the SIX principal controlled directions
(+X, -X, +Y, -Y, +Z, -Z) against Part1 and Part3, using the UNMODIFIED
production pipeline (`analyse_parting_line`) end to end. No algorithm
changes. `PullDirectionInput(..., "manual")` throughout -- the direction
optimizer is never imported, called, or approximated (enforced elsewhere by
`test_no_module_imports_the_direction_optimizer`).

Captures, per part x direction, exactly the 19 fields requested for this
validation pass: direction (raw + normalized), Track A/B segment counts,
stitched segment count, graph node/edge/component counts, candidate count,
per-gate failure counts (H0, H3, H4, H5-H7), fully-valid candidate count,
best valid candidate detail (coverage, pull-axis span, region areas,
orientation), and final outcome.

This is a measurement script only -- it does not rank, bridge, or modify
anything, and does not decide which direction is "correct" for a part.
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

# Agreed finite diagonal set (2026-08-12) -- secondary fallback after the six
# principal directions, NOT a continuous search. Normalized before use.
DIAGONAL_DIRECTIONS = {
    "(1,1,0)": (1.0, 1.0, 0.0), "(1,-1,0)": (1.0, -1.0, 0.0),
    "(1,0,1)": (1.0, 0.0, 1.0), "(1,0,-1)": (1.0, 0.0, -1.0),
    "(0,1,1)": (0.0, 1.0, 1.0), "(0,1,-1)": (0.0, 1.0, -1.0),
}


def _normalize(v: tuple[float, float, float]) -> tuple[float, float, float]:
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def _run_one(part_path: str, direction_label: str, raw_direction: tuple) -> dict:
    from backend.config import settings
    from backend.geometry.parting_line_v2.contracts import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line
    from backend.geometry.step_loader import load_step

    cfg = settings.dfm.parting_line_v2
    part = load_step(part_path)
    normalized = _normalize(raw_direction)
    pull = PullDirectionInput(normalized, "manual")
    assert pull.is_correctness_evidence, "must be manual/fixture -- never optimizer-derived"

    result = analyse_parting_line(part, pull, undercuts=UndercutInput.empty(), cfg=cfg)

    gate_fail_counts: dict[str, int] = {}
    for c in result.candidates:
        if c.feasibility and not c.feasibility.passed and c.feasibility.failed_gate:
            gate_fail_counts[c.feasibility.failed_gate] = gate_fail_counts.get(c.feasibility.failed_gate, 0) + 1
    h5_h7_fail = sum(gate_fail_counts.get(g, 0) for g in ("H5", "H6", "H7"))

    fully_valid = [c for c in result.candidates if c.feasibility and c.feasibility.passed]

    best = None
    if fully_valid:
        # Best = ranking's own winner if one of the fully-valid set, else the
        # highest-coverage fully-valid candidate (ranking only ever selects
        # from the fully-valid set, so these coincide in practice).
        winner = result.selected
        best_candidate = winner if winner in fully_valid else max(fully_valid, key=lambda c: c.score.coverage if c.score else 0)
        xs = [p[0] for p in best_candidate.points]
        ys = [p[1] for p in best_candidate.points]
        zs = [p[2] for p in best_candidate.points]
        region = result.regions if result.selected is best_candidate else None
        best = {
            "candidate_id": best_candidate.candidate_id,
            "segment_count": len(best_candidate.segments),
            "provenance_mix": best_candidate.provenance_mix,
            "coverage": round(best_candidate.score.coverage, 4) if best_candidate.score else None,
            "pull_axis_span_mm": round(best_candidate.score.pull_axis_span_mm, 3) if best_candidate.score else None,
            "bbox_mm": {"x": [round(min(xs), 2), round(max(xs), 2)],
                        "y": [round(min(ys), 2), round(max(ys), 2)],
                        "z": [round(min(zs), 2), round(max(zs), 2)]},
            "cavity_area_mm2": round(region.cavity_area_mm2, 2) if region else None,
            "core_area_mm2": round(region.core_area_mm2, 2) if region else None,
            "ambiguous_area_fraction": round(region.ambiguous_area_fraction, 4) if region else None,
            "won_at_tier": best_candidate.score.won_at_tier if best_candidate.score else None,
        }

    return {
        "direction_label": direction_label,
        "direction_raw": list(raw_direction),
        "direction_normalized": [round(c, 6) for c in normalized],
        "direction_source": pull.source,
        "track_a_segment_count": result.track_a_summary.get("segment_count", 0),
        "track_b_segment_count": result.track_b_summary.get("segment_count", 0),
        "track_b_segment_kinds": result.track_b_summary.get("segment_kinds", {}),
        "stitched_segment_count": result.stitch_summary.get("segment_count", 0),
        "graph_node_count": result.reduction.get("nodes_after"),
        "graph_edge_count": result.reduction.get("edges_after"),
        "graph_component_count": result.reduction.get("component_count"),
        "graph_branch_node_count": result.reduction.get("branch_node_count"),
        "graph_mu": result.reduction.get("cyclomatic_number"),
        "candidate_count": len(result.candidates),
        "h0_failures": gate_fail_counts.get("H0", 0),
        "h1_failures": gate_fail_counts.get("H1", 0),
        "h2_failures": gate_fail_counts.get("H2", 0),
        "h3_failures": gate_fail_counts.get("H3", 0),
        "h4_failures": gate_fail_counts.get("H4", 0),
        "h5_h7_failures": h5_h7_fail,
        "fully_valid_candidate_count": len(fully_valid),
        "best_valid_candidate": best,
        "outcome": result.outcome,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default="reports/baseline_matrix_principal.json")
    parser.add_argument("--set", choices=["principal", "diagonal"], default="principal")
    args = parser.parse_args(argv)

    directions = PRINCIPAL_DIRECTIONS if args.set == "principal" else DIAGONAL_DIRECTIONS

    parts = {
        "Part1": str(REPO_ROOT / "data" / "parts" / "Part1.stp"),
        "Part3": str(REPO_ROOT / "data" / "parts" / "Part3.stp"),
    }
    results: dict[str, dict] = {}
    for part_name, part_path in parts.items():
        results[part_name] = {}
        for label, direction in directions.items():
            print(f"--- {part_name} @ {label} ---")
            record = _run_one(part_path, label, direction)
            results[part_name][label] = record
            print(f"  A={record['track_a_segment_count']} B={record['track_b_segment_count']} "
                  f"stitched={record['stitched_segment_count']} "
                  f"graph=({record['graph_node_count']}n/{record['graph_edge_count']}e/"
                  f"{record['graph_component_count']}c/mu={record['graph_mu']}/branch={record['graph_branch_node_count']})")
            print(f"  candidates={record['candidate_count']} "
                  f"H0={record['h0_failures']} H1={record['h1_failures']} H2={record['h2_failures']} "
                  f"H3={record['h3_failures']} H4={record['h4_failures']} H5-7={record['h5_h7_failures']} "
                  f"fully_valid={record['fully_valid_candidate_count']}")
            print(f"  outcome={record['outcome']}  best={record['best_valid_candidate']}")

    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nreport -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
