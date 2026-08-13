"""
backend/validation/parting_line_h3_h4_diagnosis.py
-----------------------------------------------------
READ-ONLY diagnosis of H3 (topological separation) and H4 (orientation
consistency) failures, at controlled directions only.

Does NOT modify H3, H4, tolerances, enumeration, ranking, or pull-direction
handling. Builds a failure taxonomy purely from data `analyse_parting_line`
already computes (`FeasibilityReport.measurements`), plus a direct re-run of
`separate_surface`/`classify_regions` for representative candidates only (the
same functions `evaluate_gates` already calls internally -- engine.py
discards this detail for rejected candidates, so it is recomputed here for
inspection, never re-derived differently).

H3, as implemented (`regions.py::separate_surface`): builds a graph of
(face_id, side) nodes -- side is 0 for a face the loop doesn't pass through,
+-1 for a face split by the loop's own Track-B interior curve, by sign(g).
Two nodes are adjacent iff they share a B-Rep edge NOT (fully) covered by
the loop. Component count after removing the loop's edges:
    1   -> loop does not separate the part (REJECT)
    2   -> exactly cavity + core (PASS, proceeds to H4)
    >2  -> loop over-partitions the part (REJECT)

H4, as implemented (`gates.py`): only reached if H3 passes. For each of the
two H3 regions (labelled cavity/core by area-weighted mean g sign), sums the
AREA of faces whose g has the WRONG sign beyond `orientation_epsilon`, as a
fraction of that region's own area. REJECT if either region's wrong-sign
area fraction exceeds `orientation_violation_max` (default 2%).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DIRECTIONS = {
    "+X": (1.0, 0.0, 0.0), "-X": (-1.0, 0.0, 0.0),
    "+Y": (0.0, 1.0, 0.0), "-Y": (0.0, -1.0, 0.0),
    "+Z": (0.0, 0.0, 1.0), "-Z": (0.0, 0.0, -1.0),
}


def _bucket_h3_count(n: int) -> str:
    if n == 1:
        return "1 (under-separates)"
    if n == 2:
        return "2 (should have passed -- investigate)"
    if n <= 4:
        return f"{n} (over-partitions, small)"
    return f"{n} (over-partitions, large)" if n <= 10 else ">10 (over-partitions, very large)"


def _candidate_detail(part, candidate, pull_direction, cfg) -> dict:
    """Full geometric detail for one candidate, via a direct (read-only)
    re-run of separate_surface/classify_regions -- exactly what evaluate_gates
    already computed internally, recovered here for inspection."""
    from backend.geometry.parting_line_v2.regions import classify_regions, separate_surface
    from backend.geometry.parting_line_v2.types import EdgeBacking, FaceBacking

    loop_edge_ids = frozenset(
        s.backing.edge_id for s in candidate.segments if isinstance(s.backing, EdgeBacking)
    )
    split_face_ids = frozenset(
        s.backing.face_id for s in candidate.segments if isinstance(s.backing, FaceBacking)
    )
    loop_edge_intervals: dict[int, list[tuple[float, float]]] = {}
    for segment in candidate.segments:
        if isinstance(segment.backing, EdgeBacking):
            loop_edge_intervals.setdefault(segment.backing.edge_id, []).append(
                (segment.backing.t_start, segment.backing.t_end)
            )
    separation = separate_surface(
        part, loop_edge_ids, split_face_ids=split_face_ids,
        pull_direction=pull_direction, loop_edge_intervals=loop_edge_intervals,
    )

    kind_mix: dict[str, int] = {}
    for s in candidate.segments:
        kind_mix[s.kind] = kind_mix.get(s.kind, 0) + 1

    xs = [p[0] for p in candidate.points]
    ys = [p[1] for p in candidate.points]
    zs = [p[2] for p in candidate.points]
    bbox = {
        "x": [min(xs), max(xs)], "y": [min(ys), max(ys)], "z": [min(zs), max(zs)],
    } if candidate.points else None

    detail = {
        "candidate_id": candidate.candidate_id,
        "discovered_by": candidate.discovered_by,
        "is_closed": candidate.is_closed,
        "loop_count": candidate.loop_count,
        "segment_count": len(candidate.segments),
        "provenance_mix": candidate.provenance_mix,
        "kind_mix": kind_mix,
        "bbox_mm": bbox,
        "feasibility": candidate.feasibility.to_dict() if candidate.feasibility else None,
        "h3_component_sizes": [len(c) for c in separation.components],
        "h3_component_count": separation.component_count,
    }

    faces_by_id = {f.face_id: f for f in part.faces}
    if separation.component_count == 2:
        loop_face_ids = frozenset(
            face_id for edge_id in loop_edge_ids
            for face_id in part.edge_to_faces.get(edge_id, ())
        )
        regions = classify_regions(
            part, separation, pull_direction, loop_face_ids=loop_face_ids, cfg=cfg
        )
        cavity_area = sum(faces_by_id[f].area for f in regions.cavity_face_ids if f in faces_by_id)
        core_area = sum(faces_by_id[f].area for f in regions.core_face_ids if f in faces_by_id)
        total_area = cavity_area + core_area
        g_by_id = {c.face_id: c.mean_g for c in regions.faces}

        def violators(face_ids, sign):
            return sorted(
                (fid, round(g_by_id.get(fid, 0.0), 4), round(faces_by_id[fid].area, 2))
                for fid in face_ids
                if fid in g_by_id and sign * g_by_id[fid] < 0
            )

        detail.update({
            "cavity_face_count": len(regions.cavity_face_ids),
            "core_face_count": len(regions.core_face_ids),
            "cavity_area_mm2": round(cavity_area, 3),
            "core_area_mm2": round(core_area, 3),
            "smaller_side_area_fraction": (
                round(min(cavity_area, core_area) / total_area, 4) if total_area > 0 else None
            ),
            "cavity_wrong_sign_faces": violators(regions.cavity_face_ids, 1.0)[:10],
            "core_wrong_sign_faces": violators(regions.core_face_ids, -1.0)[:10],
        })
    else:
        detail["component_sizes_all"] = [len(c) for c in separation.components]

    return detail


def _diagnose(part_path: str, direction_label: str, *, top_n_examples: int) -> dict:
    from backend.config import settings
    from backend.geometry.parting_line_v2.contracts import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line
    from backend.geometry.step_loader import load_step

    cfg = settings.dfm.parting_line_v2
    part = load_step(part_path)
    pull = PullDirectionInput(DIRECTIONS[direction_label], "manual")
    assert pull.is_correctness_evidence

    result = analyse_parting_line(part, pull, undercuts=UndercutInput.empty(), cfg=cfg)

    h3_failures = [c for c in result.candidates if c.feasibility and c.feasibility.failed_gate == "H3"]
    h4_failures = [c for c in result.candidates if c.feasibility and c.feasibility.failed_gate == "H4"]
    other_failures = [
        c for c in result.candidates
        if c.feasibility and c.feasibility.failed_gate not in ("H3", "H4", None)
    ]
    passed = [c for c in result.candidates if c.feasibility and c.feasibility.passed]

    h3_histogram: dict[str, int] = {}
    for c in h3_failures:
        n = int(c.feasibility.measurements.get("h3_region_count", -1))
        key = _bucket_h3_count(n)
        h3_histogram[key] = h3_histogram.get(key, 0) + 1

    h4_histogram: dict[str, int] = {}
    h4_side_histogram: dict[str, int] = {"cavity": 0, "core": 0, "both/unclear": 0}
    for c in h4_failures:
        frac = c.feasibility.measurements.get("h4_orientation_violation_fraction", 0.0)
        bucket = (
            "2-10%" if frac <= 0.10 else "10-30%" if frac <= 0.30 else
            "30-60%" if frac <= 0.60 else ">60%"
        )
        h4_histogram[bucket] = h4_histogram.get(bucket, 0) + 1

    # Representative examples: smallest and largest h3_region_count among H3
    # failures; smallest and largest violation fraction among H4 failures.
    examples = {}
    if h3_failures:
        by_count = sorted(h3_failures, key=lambda c: c.feasibility.measurements.get("h3_region_count", 0))
        examples["h3_min_region_count"] = _candidate_detail(part, by_count[0], pull.direction, cfg)
        examples["h3_max_region_count"] = _candidate_detail(part, by_count[-1], pull.direction, cfg)
    if h4_failures:
        by_frac = sorted(
            h4_failures, key=lambda c: c.feasibility.measurements.get("h4_orientation_violation_fraction", 0)
        )
        examples["h4_min_violation"] = _candidate_detail(part, by_frac[0], pull.direction, cfg)
        examples["h4_max_violation"] = _candidate_detail(part, by_frac[-1], pull.direction, cfg)
    if passed:
        examples["passed"] = _candidate_detail(part, passed[0], pull.direction, cfg)

    return {
        "direction_label": direction_label, "direction": list(pull.direction),
        "total_candidates": len(result.candidates),
        "outcome": result.outcome,
        "h3_failure_count": len(h3_failures),
        "h4_failure_count": len(h4_failures),
        "other_failure_count": len(other_failures),
        "other_failure_gates": sorted({c.feasibility.failed_gate for c in other_failures}),
        "passed_count": len(passed),
        "h3_histogram": h3_histogram,
        "h4_violation_fraction_histogram": h4_histogram,
        "examples": examples,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default="reports/h3_h4_diagnosis.json")
    args = parser.parse_args(argv)

    targets = [
        (str(REPO_ROOT / "data" / "parts" / "Part1.stp"), "+X"),
        (str(REPO_ROOT / "data" / "parts" / "Part1.stp"), "+Y"),
        (str(REPO_ROOT / "data" / "parts" / "Part3.stp"), "+X"),
        (str(REPO_ROOT / "data" / "parts" / "Part3.stp"), "+Y"),
    ]
    results = {}
    for part_path, direction in targets:
        key = f"{Path(part_path).stem}_{direction}"
        print(f"--- {key} ---")
        record = _diagnose(part_path, direction, top_n_examples=2)
        results[key] = record
        print(f"  total={record['total_candidates']} outcome={record['outcome']}")
        print(f"  H3 failures: {record['h3_failure_count']}  histogram: {record['h3_histogram']}")
        print(f"  H4 failures: {record['h4_failure_count']}  histogram: {record['h4_violation_fraction_histogram']}")
        print(f"  other failures: {record['other_failure_count']} at {record['other_failure_gates']}")
        print(f"  passed: {record['passed_count']}")

    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nreport -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
