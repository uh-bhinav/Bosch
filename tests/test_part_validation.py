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


# ---------------------------------------------------------------------------
# check_assertions — Cross-cutting X.1 real-geometry assertion flags.
#
# Each test below builds a hand-crafted, JSON-safe suite payload (exactly the
# shape ValidationSuiteResult.to_dict() produces) representing deliberately
# bad geometry, and asserts the matching flag fails FOR THE RIGHT REASON.
# This is the gate the roadmap requires: an assertion is worthless if it only
# ever passes.
# ---------------------------------------------------------------------------


def _suite_payload(parting_line_metrics=None, core_cavity_metrics=None, has_parting_line_step=True):
    steps = []
    if has_parting_line_step:
        steps.append({
            "name": "parting_line",
            "status": "passed",
            "elapsed_s": 0.1,
            "message": "",
            "metrics": parting_line_metrics or {},
        })
    if core_cavity_metrics is not None:
        steps.append({
            "name": "core_cavity_split",
            "status": "passed",
            "elapsed_s": 0.1,
            "message": "",
            "metrics": core_cavity_metrics,
        })
    return {
        "part_results": [
            {"filename": "Part1.stp", "path": "/data/parts/Part1.stp", "status": "passed", "steps": steps}
        ]
    }


_GOOD_PARTING_LINE_METRICS = {
    "closure_error_mm": 0.001,
    "closure_guaranteed": True,
    "graph_cleanup_strategy": "exact",
    "parting_surface_status": "generated_planar",
    "silhouette_coverage_ratio": 0.92,
}


def test_check_assertions_passes_clean_payload():
    from backend.validation.part_validation import check_assertions

    payload = _suite_payload(_GOOD_PARTING_LINE_METRICS, core_cavity_metrics={
        "solid_split_status": "split_ok",
        "split_solid_count": 2,
    })

    failures = check_assertions(
        payload,
        assert_parting_line_closed=0.05,
        assert_core_cavity_solids=2,
        assert_exact_optimiser=True,
        assert_parting_surface_generated=True,
        assert_silhouette_coverage=0.35,
    )

    assert failures == []


def test_assert_parting_line_closed_rejects_a_lying_closure_flag():
    """Bug A: closure_guaranteed=True must not be trusted over the measured gap."""
    from backend.validation.part_validation import check_assertions

    bad_metrics = dict(_GOOD_PARTING_LINE_METRICS, closure_error_mm=17.0, closure_guaranteed=True)
    payload = _suite_payload(bad_metrics)

    failures = check_assertions(payload, assert_parting_line_closed=0.05)

    assert len(failures) == 1
    assert failures[0].flag == "--assert-parting-line-closed"
    assert "17.0" in failures[0].message


def test_assert_parting_line_closed_rejects_an_honestly_unclosed_wire():
    from backend.validation.part_validation import check_assertions

    bad_metrics = dict(_GOOD_PARTING_LINE_METRICS, closure_error_mm=2.0, closure_guaranteed=False)
    payload = _suite_payload(bad_metrics)

    failures = check_assertions(payload, assert_parting_line_closed=0.05)

    assert len(failures) == 1
    assert "closure_guaranteed=False" in failures[0].message


def test_assert_exact_optimiser_rejects_greedy_fallback():
    """Bug B: silent fallback to the non-backtracking greedy tracer."""
    from backend.validation.part_validation import check_assertions

    bad_metrics = dict(_GOOD_PARTING_LINE_METRICS, graph_cleanup_strategy="greedy-fallback")
    payload = _suite_payload(bad_metrics)

    failures = check_assertions(payload, assert_exact_optimiser=True)

    assert len(failures) == 1
    assert failures[0].flag == "--assert-exact-optimiser"
    assert "greedy-fallback" in failures[0].message


def test_assert_parting_surface_generated_rejects_failed_status():
    """Bug E: parting surface generation failing must not pass silently."""
    from backend.validation.part_validation import check_assertions

    bad_metrics = dict(_GOOD_PARTING_LINE_METRICS, parting_surface_status="failed")
    payload = _suite_payload(bad_metrics)

    failures = check_assertions(payload, assert_parting_surface_generated=True)

    assert len(failures) == 1
    assert failures[0].flag == "--assert-parting-surface-generated"


def test_assert_silhouette_coverage_rejects_a_local_feature_loop():
    """Bug H: a low coverage ratio means a hole rim/boss was selected, not the main silhouette."""
    from backend.validation.part_validation import check_assertions

    bad_metrics = dict(_GOOD_PARTING_LINE_METRICS, silhouette_coverage_ratio=0.06)
    payload = _suite_payload(bad_metrics)

    failures = check_assertions(payload, assert_silhouette_coverage=0.35)

    assert len(failures) == 1
    assert failures[0].flag == "--assert-silhouette-coverage"
    assert "0.06" in failures[0].message


def test_assert_core_cavity_solids_rejects_a_degenerate_split():
    """Stage 2 gate: solid_split_status must be split_ok with exactly N solids."""
    from backend.validation.part_validation import check_assertions

    payload = _suite_payload(_GOOD_PARTING_LINE_METRICS, core_cavity_metrics={
        "solid_split_status": "failed",
        "split_solid_count": 0,
    })

    failures = check_assertions(payload, assert_core_cavity_solids=2)

    assert len(failures) == 1
    assert failures[0].flag == "--assert-core-cavity-solids"


def test_assert_core_cavity_solids_requires_the_step_to_have_run():
    """A missing step must fail the assertion, never pass it by omission."""
    from backend.validation.part_validation import check_assertions

    payload = _suite_payload(_GOOD_PARTING_LINE_METRICS, core_cavity_metrics=None)

    failures = check_assertions(payload, assert_core_cavity_solids=2)

    assert len(failures) == 1
    assert "core_cavity_split" in failures[0].message.lower() or "--core-cavity" in failures[0].message


def test_assertions_fail_when_parting_line_step_itself_is_missing():
    """A skipped/absent parting_line step must fail every parting-line assertion, not skip it."""
    from backend.validation.part_validation import check_assertions

    payload = _suite_payload(has_parting_line_step=False)

    failures = check_assertions(
        payload,
        assert_parting_line_closed=0.05,
        assert_exact_optimiser=True,
        assert_parting_surface_generated=True,
        assert_silhouette_coverage=0.35,
    )

    assert len(failures) == 4
