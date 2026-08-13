"""
backend/validation/parting_line_h0_case_study.py
--------------------------------------------------
P3.1 follow-up (2026-08-12) — case study on Part3's H0 failures at +X/+Y.

Read-only. Runs the real `analyse_parting_line` (controlled/manual direction
only) and, for every candidate that fails gate H0, extracts the on-surface
report's `worst_offender` and traces that segment back to its Track A/B
provenance and backing -- to test whether H0 failures are downstream of the
same Track-A/Track-B termination mismatch found by
`parting_line_connectivity_diagnostic.py`'s `_diagnose_snap`.

Does not modify tolerances, welding, graph construction, enumeration,
ranking, or pull-direction handling.
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


def _case_study(part_path: str, direction_label: str, direction: tuple) -> dict:
    from backend.config import settings
    from backend.geometry.parting_line_v2.contracts import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line
    from backend.geometry.parting_line_v2.types import EdgeBacking, FaceBacking
    from backend.geometry.step_loader import load_step

    cfg = settings.dfm.parting_line_v2
    part = load_step(part_path)
    pull = PullDirectionInput(direction, "manual")
    assert pull.is_correctness_evidence

    result = analyse_parting_line(part, pull, undercuts=UndercutInput.empty(), cfg=cfg)

    edges_by_id = {e.edge_id: e for e in part.edges}
    cases = []
    for candidate in result.candidates:
        report = candidate.feasibility
        if report is None or report.failed_gate != "H0":
            continue
        on_surface = report.on_surface
        segments_by_id = {s.segment_id: s for s in candidate.segments}

        case = {
            "candidate_id": candidate.candidate_id,
            "reason": report.reason,
            "on_surface": on_surface.to_dict() if on_surface else None,
            "candidate_segment_count": len(candidate.segments),
            "candidate_provenance_mix": candidate.provenance_mix if hasattr(candidate, "provenance_mix") else None,
        }

        if on_surface and on_surface.worst_offender is not None:
            worst_segment_id, worst_point = on_surface.worst_offender
            segment = segments_by_id.get(worst_segment_id)
            if segment is not None:
                backing = segment.backing
                if isinstance(backing, EdgeBacking):
                    edge = edges_by_id.get(backing.edge_id)
                    backing_info = {
                        "provenance": "edge", "edge_id": backing.edge_id,
                        "adjacent_face_ids": list(edge.adjacent_face_ids) if edge else None,
                        "t_start": backing.t_start, "t_end": backing.t_end,
                    }
                else:
                    backing_info = {
                        "provenance": "face", "face_id": backing.face_id,
                        "uv_start": list(backing.uv[0]) if backing.uv else None,
                        "uv_end": list(backing.uv[-1]) if backing.uv else None,
                    }
                case["worst_offender"] = {
                    "segment_id": worst_segment_id,
                    "point": list(worst_point),
                    "segment_kind": segment.kind,
                    "backing": backing_info,
                }
            else:
                case["worst_offender"] = {
                    "segment_id": worst_segment_id, "point": list(worst_point),
                    "note": "segment_id not found among this candidate's own segments "
                            "(worst_offender may reference a different candidate's set)",
                }

        # Every segment in this candidate, for full context (small candidates only).
        case["all_segments"] = []
        for seg in candidate.segments:
            b = seg.backing
            if isinstance(b, EdgeBacking):
                info = {"provenance": "edge", "edge_id": b.edge_id, "t_start": b.t_start, "t_end": b.t_end}
            else:
                info = {"provenance": "face", "face_id": b.face_id}
            case["all_segments"].append({"segment_id": seg.segment_id, "kind": seg.kind, **info})

        cases.append(case)

    return {
        "direction_label": direction_label, "direction": list(direction),
        "direction_source": pull.source,
        "total_candidates": len(result.candidates),
        "h0_failure_count": len(cases),
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part", default=str(REPO_ROOT / "data" / "parts" / "Part3.stp"))
    parser.add_argument("--directions", default="+X,+Y")
    parser.add_argument("--json", default="reports/h0_case_study_part3.json")
    args = parser.parse_args(argv)

    results = []
    for label in [d.strip() for d in args.directions.split(",") if d.strip()]:
        print(f"--- {Path(args.part).stem} @ {label} ---")
        record = _case_study(args.part, label, DIRECTIONS[label])
        results.append(record)
        print(f"  {record['h0_failure_count']} H0 failures out of {record['total_candidates']} candidates")
        for case in record["cases"]:
            wo = case.get("worst_offender", {})
            print(f"    candidate {case['candidate_id']}: {case['reason']}")
            print(f"      worst offender: segment {wo.get('segment_id')} "
                  f"({wo.get('segment_kind')}) backing={wo.get('backing')}")

    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps({
        "part": Path(args.part).stem,
        "note": "Controlled directions only (direction_source=manual). Read-only.",
        "directions": results,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"\nreport -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
