"""
tests/test_performance_profile.py
---------------------------------
Tests for the performance profiling harness.
"""

from __future__ import annotations


def test_step_budget_status_within_and_over_budget():
    from backend.validation.performance_profile import PerformanceStepProfile

    within = PerformanceStepProfile(
        name="draft_default_z",
        status="passed",
        elapsed_s=1.0,
        budget_s=2.0,
    )
    over = PerformanceStepProfile(
        name="direction_search",
        status="passed",
        elapsed_s=5.0,
        budget_s=2.0,
    )

    assert within.budget_status == "within_budget"
    assert over.budget_status == "over_budget"
    assert over.to_dict()["budget_status"] == "over_budget"


def test_step_budget_status_not_applicable_for_skipped_step():
    from backend.validation.performance_profile import PerformanceStepProfile

    skipped = PerformanceStepProfile(
        name="load_step",
        status="skipped",
        elapsed_s=0.01,
        budget_s=30.0,
        message="pythonOCC unavailable",
    )

    assert skipped.budget_status == "not_applicable"


def test_part_profile_warns_on_over_budget_step(tmp_path):
    from backend.validation.performance_profile import (
        PartPerformanceProfile,
        PerformanceStepProfile,
    )

    profile = PartPerformanceProfile(
        filename="Part1.stp",
        path=str(tmp_path / "Part1.stp"),
        steps=[
            PerformanceStepProfile(
                name="load_step",
                status="passed",
                elapsed_s=45.0,
                budget_s=30.0,
            )
        ],
    )

    assert profile.status == "warning"
    assert profile.total_elapsed_s == 45.0


def test_suite_profile_warns_when_part2_missing(tmp_path):
    from backend.validation.performance_profile import PerformanceSuiteProfile

    suite = PerformanceSuiteProfile(
        parts_dir=str(tmp_path),
        expected_files=["Part1.stp", "Part2.stp"],
        discovered_files=["Part1.stp"],
        missing_expected_files=["Part2.stp"],
        part_profiles=[],
        budgets_s={"load_step": 30.0},
    )

    assert suite.status == "warning"
    payload = suite.to_dict()
    assert payload["missing_expected_files"] == ["Part2.stp"]
    assert payload["budgets_s"] == {"load_step": 30.0}


def test_parse_budget_overrides_defaults():
    from backend.validation.performance_profile import _parse_budget

    budgets = _parse_budget(["load_step=12.5", "direction_search=90"])

    assert budgets["load_step"] == 12.5
    assert budgets["direction_search"] == 90.0
    assert "draft_default_z" in budgets


def test_default_budgets_include_parting_line():
    from backend.validation.performance_profile import DEFAULT_BUDGETS_S

    assert DEFAULT_BUDGETS_S["parting_line"] > 0.0


def test_parse_budget_can_override_parting_line():
    from backend.validation.performance_profile import _parse_budget

    budgets = _parse_budget(["parting_line=22.5"])

    assert budgets["parting_line"] == 22.5
