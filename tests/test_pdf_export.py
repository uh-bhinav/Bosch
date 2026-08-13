"""
tests/test_pdf_export.py
---------------------------
Tests for backend/report/pdf_export.py -- the PDF DfM report export
(Stage 6, roadmap §5).

This module is a pure presentation layer (no recomputation, roadmap §5.5's
honesty constraint) -- most tests here exercise the pure helper functions
(`_collect_warnings`, `_direction_label_display`) directly with hand-built
dicts, plus end-to-end PDF generation checks (structural validity: real
%PDF header/footer, reasonable size) against both real Part1.stp/Part3.stp
geometry and minimal/all-optional-sections-omitted inputs.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.report.pdf_export import _collect_warnings, _direction_label_display, build_dfm_report_pdf

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PART1_PATH = PROJECT_ROOT / "data" / "parts" / "Part1.stp"
PART3_PATH = PROJECT_ROOT / "data" / "parts" / "Part3.stp"
HAS_OCC = True
try:
    import OCC  # noqa: F401
except ImportError:
    HAS_OCC = False

skip_no_occ = pytest.mark.skipif(not HAS_OCC, reason="pythonocc-core not installed")
skip_no_part1 = pytest.mark.skipif(not PART1_PATH.exists(), reason=f"Part1.stp not found at {PART1_PATH}")
skip_no_part3 = pytest.mark.skipif(not PART3_PATH.exists(), reason=f"Part3.stp not found at {PART3_PATH}")


def _minimal_part_summary() -> dict:
    return {
        "source_file": "Part1.stp",
        "face_count": 311, "edge_count": 762, "vertex_count": 444,
        "solid_count": 1, "shell_count": 1,
        "bounding_box": {"dimensions_mm": [19.0, 19.0, 15.0]},
    }


def _minimal_draft() -> dict:
    return {
        "pull_direction": [0.232, 0.357, 0.905],
        "is_manufacturable": True, "severity": "none",
        "percentages": {"good_pct": 99.98, "marginal_pct": 0.02, "bad_pct": 0.0},
        "face_counts": {"bad": 0},
    }


def _minimal_undercuts() -> dict:
    return {
        "has_undercuts": False, "has_critical_undercut": False, "feature_count": 0,
        "face_counts": {"undercut": 0},
        "boolean_refinement": {"enabled": True},
        "features": [],
    }


def _minimal_parting_line() -> dict:
    return {
        "readiness": {"status": "ready", "score": 0.792, "blockers": []},
        "closure_error_mm": 0.0, "closure_guaranteed": True,
        "silhouette_coverage_ratio": 0.948, "bridging_status": "not_needed",
        "parting_surface": {"status": "generated_filling"},
        "warnings": [],
    }


def _minimal_core_cavity() -> dict:
    return {
        "face_counts": {"cavity": 68, "core": 240, "parting": 3},
        "percentages": {"cavity_pct": 48.86, "core_pct": 51.04},
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# _direction_label_display -- regression guard for the duplicate-vector bug
# (the exact bug already fixed once in frontend/app.py's own copy, S3.5)
# ---------------------------------------------------------------------------


def test_direction_label_display_uses_real_axis_label():
    direction = {"best_label": "+Z", "best_direction": [0.0, 0.0, 1.0]}
    assert _direction_label_display(direction) == "+Z (+0.000, +0.000, +1.000)"


def test_direction_label_display_avoids_duplicating_a_fallback_vector_label():
    # direction_optimizer.py's _direction_label() falls back to raw vector
    # text (not a real "+X"-style label) for non-axis-aligned directions --
    # best_label and best_direction can be the same string. Must not print
    # the vector twice.
    direction = {
        "best_label": "(+0.232, +0.357, +0.905)",
        "best_direction": [0.232, 0.357, 0.905],
    }
    result = _direction_label_display(direction)
    assert result.count("0.232") == 1


def test_direction_label_display_handles_missing_direction():
    assert _direction_label_display({}) == "n/a"


# ---------------------------------------------------------------------------
# _collect_warnings -- roadmap §5.5's honesty constraint: never drop a
# warning from any source for a cleaner-looking page
# ---------------------------------------------------------------------------


def test_collect_warnings_aggregates_parting_line_and_core_cavity():
    warnings = _collect_warnings(
        undercuts=_minimal_undercuts(),
        parting_line={**_minimal_parting_line(), "warnings": ["loop is branched"]},
        core_cavity={**_minimal_core_cavity(), "warnings": ["low coverage"]},
        solid_split=None, side_core=None, agent_report=None,
    )
    assert any("loop is branched" in w for w in warnings)
    assert any("low coverage" in w for w in warnings)


def test_collect_warnings_surfaces_readiness_blockers():
    parting_line = _minimal_parting_line()
    parting_line["readiness"]["blockers"] = ["closure error above tolerance"]
    warnings = _collect_warnings(
        undercuts=_minimal_undercuts(), parting_line=parting_line,
        core_cavity=_minimal_core_cavity(), solid_split=None, side_core=None, agent_report=None,
    )
    assert any("closure error above tolerance" in w for w in warnings)


def test_collect_warnings_flags_degraded_boolean_reliability():
    undercuts = _minimal_undercuts()
    undercuts["boolean_refinement"]["reliability"] = {
        "reliability_level": "low", "reliability_label": "Proxy-heavy",
        "summary": "mostly proxy evidence",
    }
    warnings = _collect_warnings(
        undercuts=undercuts, parting_line=_minimal_parting_line(),
        core_cavity=_minimal_core_cavity(), solid_split=None, side_core=None, agent_report=None,
    )
    assert any("Proxy-heavy" in w for w in warnings)


def test_collect_warnings_flags_planar_approximation_split_tool():
    solid_split = {"solid_split_status": "split_ok", "split_tool_kind": "planar_approximation"}
    warnings = _collect_warnings(
        undercuts=_minimal_undercuts(), parting_line=_minimal_parting_line(),
        core_cavity=_minimal_core_cavity(), solid_split=solid_split, side_core=None, agent_report=None,
    )
    assert any("planar-approximation" in w for w in warnings)


def test_collect_warnings_flags_failed_solid_split():
    solid_split = {"solid_split_status": "failed", "failure_reason": "degenerate sliver"}
    warnings = _collect_warnings(
        undercuts=_minimal_undercuts(), parting_line=_minimal_parting_line(),
        core_cavity=_minimal_core_cavity(), solid_split=solid_split, side_core=None, agent_report=None,
    )
    assert any("degenerate sliver" in w for w in warnings)


def test_collect_warnings_flags_failed_side_core_but_not_no_feature():
    warnings_failed = _collect_warnings(
        undercuts=_minimal_undercuts(), parting_line=_minimal_parting_line(),
        core_cavity=_minimal_core_cavity(), solid_split=None,
        side_core={"status": "failed", "failure_reason": "volumes don't conserve"},
        agent_report=None,
    )
    assert any("volumes don't conserve" in w for w in warnings_failed)

    warnings_no_feature = _collect_warnings(
        undercuts=_minimal_undercuts(), parting_line=_minimal_parting_line(),
        core_cavity=_minimal_core_cavity(), solid_split=None,
        side_core={"status": "no_feature"},
        agent_report=None,
    )
    assert not any("no_feature" in w for w in warnings_no_feature), (
        "'no_feature' is an expected, non-error state (no undercuts at this "
        "direction) and must not be surfaced as a warning."
    )


def test_collect_warnings_surfaces_agent_analysis_warnings():
    warnings = _collect_warnings(
        undercuts=_minimal_undercuts(), parting_line=_minimal_parting_line(),
        core_cavity=_minimal_core_cavity(), solid_split=None, side_core=None,
        agent_report={"analysis_warnings": ["model output was truncated"]},
    )
    assert any("model output was truncated" in w for w in warnings)


def test_collect_warnings_empty_when_nothing_is_wrong():
    warnings = _collect_warnings(
        undercuts=_minimal_undercuts(), parting_line=_minimal_parting_line(),
        core_cavity=_minimal_core_cavity(), solid_split=None, side_core=None, agent_report=None,
    )
    assert warnings == []


# ---------------------------------------------------------------------------
# build_dfm_report_pdf -- structural validity with hand-built (mocked) dicts
# ---------------------------------------------------------------------------


def _assert_valid_pdf(data: bytes) -> None:
    assert data[:4] == b"%PDF", "Output must start with a real PDF header."
    assert b"%%EOF" in data[-64:] or b"%%EOF" in data, "Output must contain a PDF trailer."
    assert len(data) > 500, "A report with real content should not be near-empty."


def test_build_dfm_report_pdf_with_only_required_sections():
    pdf_bytes = build_dfm_report_pdf(
        filename="Part1.stp",
        part_summary=_minimal_part_summary(),
        draft=_minimal_draft(),
        undercuts=_minimal_undercuts(),
        parting_line=_minimal_parting_line(),
        core_cavity=_minimal_core_cavity(),
    )
    _assert_valid_pdf(pdf_bytes)


def test_build_dfm_report_pdf_with_all_optional_sections():
    pdf_bytes = build_dfm_report_pdf(
        filename="Part1.stp",
        part_summary=_minimal_part_summary(),
        draft=_minimal_draft(),
        undercuts=_minimal_undercuts(),
        parting_line=_minimal_parting_line(),
        core_cavity=_minimal_core_cavity(),
        direction={"best_direction": [0.232, 0.357, 0.905], "best_label": "+Z", "best_score": 0.313, "candidate_count": 114},
        solid_split={
            "solid_split_status": "split_ok", "split_solid_count": 2,
            "cavity_solid_volume_mm3": 17587.3, "core_solid_volume_mm3": 16909.7,
            "split_tool_kind": "planar_approximation",
        },
        side_core={
            "status": "generated", "containing_half": "core",
            "side_core_volume_mm3": 9219.8, "conservation_error": 0.0,
        },
        agent_report={
            "summary": "One minor draft issue.",
            "overall_manufacturability": "acceptable",
            "tools_called": ["optimize_pull_direction"],
            "pull_direction_source": "optimal",
            "findings": [{
                "severity": "low", "category": "draft", "title": "Marginal draft",
                "evidence_source": "boolean_confirmed", "confidence": 1.0,
            }],
            "analysis_warnings": [],
        },
    )
    _assert_valid_pdf(pdf_bytes)


def test_build_dfm_report_pdf_side_core_no_feature_does_not_show_misleading_error():
    """
    Regression guard: SideCoreResult.conservation_error defaults to 1.0
    (unset) when status is "no_feature" -- rendering it unconditionally
    would read as "100% conservation error" for a state that isn't an error
    at all. Assert the PDF's rendered text does not contain that string.
    """
    pdf_bytes = build_dfm_report_pdf(
        filename="Part1.stp",
        part_summary=_minimal_part_summary(),
        draft=_minimal_draft(),
        undercuts=_minimal_undercuts(),
        parting_line=_minimal_parting_line(),
        core_cavity=_minimal_core_cavity(),
        solid_split={"solid_split_status": "split_ok", "split_solid_count": 2},
        side_core={"status": "no_feature", "conservation_error": 1.0},
    )
    _assert_valid_pdf(pdf_bytes)
    assert b"100.0000" not in pdf_bytes and b"100.00%" not in pdf_bytes


def test_build_dfm_report_pdf_with_a_screenshot():
    from io import BytesIO

    from PIL import Image as PILImage

    img = PILImage.new("RGB", (60, 40), color=(10, 20, 30))
    buf = BytesIO()
    img.save(buf, format="PNG")

    pdf_bytes = build_dfm_report_pdf(
        filename="Part1.stp",
        part_summary=_minimal_part_summary(),
        draft=_minimal_draft(),
        undercuts=_minimal_undercuts(),
        parting_line=_minimal_parting_line(),
        core_cavity=_minimal_core_cavity(),
        screenshot_png=buf.getvalue(),
    )
    _assert_valid_pdf(pdf_bytes)


def test_build_dfm_report_pdf_handles_missing_optional_warning_lists_gracefully():
    # parting_line/core_cavity without a "warnings" key at all (not just an
    # empty list) must not raise -- defensive .get(..., []) throughout.
    pdf_bytes = build_dfm_report_pdf(
        filename="Part1.stp",
        part_summary=_minimal_part_summary(),
        draft=_minimal_draft(),
        undercuts=_minimal_undercuts(),
        parting_line={k: v for k, v in _minimal_parting_line().items() if k != "warnings"},
        core_cavity={k: v for k, v in _minimal_core_cavity().items() if k != "warnings"},
    )
    _assert_valid_pdf(pdf_bytes)


# ---------------------------------------------------------------------------
# End-to-end: real Part1.stp/Part3.stp geometry through the full pipeline
# ---------------------------------------------------------------------------


def _build_report_for_real_part(part_path: Path, include_side_core: bool) -> bytes:
    from backend.geometry.core_cavity import classify_core_cavity, split_core_cavity_solids
    from backend.geometry.direction_optimizer import optimize_mold_direction
    from backend.geometry.draft_analyzer import analyze_draft
    from backend.geometry.parting_line import detect_parting_line_candidates
    from backend.geometry.side_core import generate_primary_side_core
    from backend.geometry.step_loader import load_step
    from backend.geometry.undercut_detector import detect_undercuts

    part = load_step(part_path)
    direction_result = optimize_mold_direction(part)
    pull_direction = direction_result.best_direction

    draft = analyze_draft(part, pull_direction, mutate=False)
    undercuts = detect_undercuts(part, pull_direction, mutate=False, boolean_refine=True)
    parting = detect_parting_line_candidates(part, pull_direction, undercut_context=undercuts, mutate=False)
    core_cavity = classify_core_cavity(part, pull_direction=pull_direction, mutate=False)

    parting_sheet = (
        parting.parting_surface.occ_shape
        if parting.parting_surface.status.startswith("generated")
        else None
    )
    solid_split = split_core_cavity_solids(part, parting_sheet, pull_direction, loop_points=parting.wire_points)

    side_core_dict = None
    if include_side_core and solid_split.solid_split_status == "split_ok":
        side_core_dict = generate_primary_side_core(part, undercuts, solid_split).to_dict()

    return build_dfm_report_pdf(
        filename=part_path.name,
        part_summary=part.to_dict(include_faces=False),
        draft=draft.to_dict(),
        undercuts=undercuts.to_dict(),
        parting_line=parting.to_dict(),
        core_cavity=core_cavity.to_dict(),
        direction=direction_result.to_dict(include_all_candidates=False),
        solid_split=solid_split.to_dict(),
        side_core=side_core_dict,
    )


@skip_no_occ
@skip_no_part1
def test_real_pdf_report_on_part1():
    pdf_bytes = _build_report_for_real_part(PART1_PATH, include_side_core=True)
    _assert_valid_pdf(pdf_bytes)


@skip_no_occ
@skip_no_part3
def test_real_pdf_report_on_part3():
    pdf_bytes = _build_report_for_real_part(PART3_PATH, include_side_core=False)
    _assert_valid_pdf(pdf_bytes)
