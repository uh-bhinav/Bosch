"""
tests/test_part_validation.py
-----------------------------
Tests for the STEP validation harness.
"""

from __future__ import annotations

from types import SimpleNamespace


def test_discover_step_files_sorts_stp_and_step(tmp_path):
    from backend.validation.part_validation import discover_step_files

    (tmp_path / "B.step").write_text("dummy")
    (tmp_path / "A.stp").write_text("dummy")
    (tmp_path / "ignore.txt").write_text("dummy")

    files = discover_step_files(tmp_path)

    assert [path.name for path in files] == ["A.stp", "B.step"]


def test_missing_expected_files_reports_part2(tmp_path):
    from backend.validation.part_validation import missing_expected_files

    (tmp_path / "Part1.stp").write_text("dummy")

    missing = missing_expected_files(
        tmp_path,
        expected_files=("Part1.stp", "Part2.stp"),
    )

    assert missing == ["Part2.stp"]


def test_validation_suite_warns_when_expected_file_missing(tmp_path):
    from backend.validation.part_validation import ValidationSuiteResult

    result = ValidationSuiteResult(
        parts_dir=str(tmp_path),
        expected_files=["Part1.stp", "Part2.stp"],
        discovered_files=["Part1.stp"],
        missing_expected_files=["Part2.stp"],
        part_results=[],
    )

    assert result.status == "warning"
    payload = result.to_dict()
    assert payload["status"] == "warning"
    assert payload["missing_expected_files"] == ["Part2.stp"]


def test_validation_suite_fails_when_any_part_fails(tmp_path):
    from backend.validation.part_validation import (
        PartValidationResult,
        ValidationSuiteResult,
        ValidationStepResult,
    )

    part = PartValidationResult(
        filename="Part1.stp",
        path=str(tmp_path / "Part1.stp"),
        status="failed",
        steps=[
            ValidationStepResult(
                name="load_step",
                status="failed",
                elapsed_s=0.01,
                message="bad file",
            )
        ],
    )
    result = ValidationSuiteResult(
        parts_dir=str(tmp_path),
        expected_files=["Part1.stp"],
        discovered_files=["Part1.stp"],
        missing_expected_files=[],
        part_results=[part],
    )

    assert result.status == "failed"
    assert result.to_dict()["part_results"][0]["steps"][0]["message"] == "bad file"


def test_validation_suite_warns_when_any_part_is_skipped(tmp_path):
    from backend.validation.part_validation import (
        PartValidationResult,
        ValidationSuiteResult,
        ValidationStepResult,
    )

    part = PartValidationResult(
        filename="Part1.stp",
        path=str(tmp_path / "Part1.stp"),
        status="skipped",
        steps=[
            ValidationStepResult(
                name="load_step",
                status="skipped",
                elapsed_s=0.01,
                message="pythonOCC unavailable",
            )
        ],
    )
    result = ValidationSuiteResult(
        parts_dir=str(tmp_path),
        expected_files=["Part1.stp"],
        discovered_files=["Part1.stp"],
        missing_expected_files=[],
        part_results=[part],
    )

    assert result.status == "warning"


def test_validate_available_parts_reports_missing_directory(tmp_path):
    from backend.validation.part_validation import validate_available_parts

    missing_dir = tmp_path / "parts"

    result = validate_available_parts(
        parts_dir=missing_dir,
        expected_files=("Part1.stp", "Part2.stp"),
    )

    assert result.status == "warning"
    assert result.discovered_files == []
    assert result.missing_expected_files == ["Part1.stp", "Part2.stp"]


def test_parting_line_metrics_report_readiness_quality_and_conflict():
    from backend.validation.part_validation import _parting_line_metrics

    result = SimpleNamespace(
        candidate_edge_ids=[1, 2, 3],
        silhouette_edge_ids=[1, 3],
        selected_edge_ids=[1, 2],
        components=[SimpleNamespace(component_id=0)],
        warnings=["minor gap closed"],
        readiness=SimpleNamespace(
            status="review",
            score=0.73,
            reasons=["minor undercut conflict"],
            blockers=[],
        ),
        diagnostic_gate=SimpleNamespace(
            status="review",
            can_display_curve=True,
            can_use_for_report=True,
            blocks_core_cavity=False,
            requires_manual_review=True,
        ),
        diagnostics=SimpleNamespace(
            status="warning",
            failure_code=None,
            skipped_edge_count=2,
            unorderable_edge_count=0,
        ),
        selection_quality=SimpleNamespace(level="good", score=0.81),
        undercut_conflict=SimpleNamespace(conflict_level="low", conflict_score=0.12),
        refinement=SimpleNamespace(status="refined", quality="smooth"),
    )

    metrics = _parting_line_metrics(result)

    assert metrics["candidate_edge_count"] == 3
    assert metrics["silhouette_edge_count"] == 2
    assert metrics["selected_edge_count"] == 2
    assert metrics["component_count"] == 1
    assert metrics["readiness_status"] == "review"
    assert metrics["gate_status"] == "review"
    assert metrics["gate_can_display_curve"] is True
    assert metrics["gate_can_use_for_report"] is True
    assert metrics["gate_blocks_core_cavity"] is False
    assert metrics["gate_requires_manual_review"] is True
    assert metrics["diagnostics_status"] == "warning"
    assert metrics["diagnostics_failure_code"] is None
    assert metrics["diagnostics_skipped_edge_count"] == 2
    assert metrics["diagnostics_unorderable_edge_count"] == 0
    assert metrics["selection_quality_level"] == "good"
    assert metrics["undercut_conflict_level"] == "low"
    assert metrics["refinement_quality"] == "smooth"
    assert metrics["warning_count"] == 1


def test_parting_line_metrics_are_safe_for_partial_result_objects():
    from backend.validation.part_validation import _parting_line_metrics

    metrics = _parting_line_metrics(SimpleNamespace())

    assert metrics["readiness_status"] == "unknown"
    assert metrics["readiness_score"] == 0.0
    assert metrics["candidate_edge_count"] == 0
    assert metrics["gate_status"] == "unknown"
    assert metrics["gate_can_use_for_report"] is False
    assert metrics["diagnostics_status"] == "unknown"
    assert metrics["diagnostics_skipped_edge_count"] == 0
    assert metrics["selection_quality_level"] == "unknown"


def test_undercut_context_metrics_report_boolean_context():
    from backend.validation.part_validation import _undercut_context_metrics

    context = SimpleNamespace(
        boolean_refined=True,
        undercut_face_ids=[1, 2, 3],
        features=[
            SimpleNamespace(feature_id=1, boolean_refined=True),
            SimpleNamespace(feature_id=2, interference_volume_mm3=0.0),
            SimpleNamespace(feature_id=3, boolean_intersection_shapes=[object()]),
        ],
    )

    metrics = _undercut_context_metrics(context)

    assert metrics["undercut_context_present"] is True
    assert metrics["undercut_context_boolean_refined"] is True
    assert metrics["undercut_context_feature_count"] == 3
    assert metrics["undercut_context_face_count"] == 3
    assert metrics["undercut_context_boolean_feature_count"] == 2


def test_undercut_context_metrics_handle_missing_context():
    from backend.validation.part_validation import _undercut_context_metrics

    metrics = _undercut_context_metrics(None)

    assert metrics["undercut_context_present"] is False
    assert metrics["undercut_context_boolean_feature_count"] == 0
