"""
tests/test_agent_schemas.py
-----------------------------
Tests for backend/agent/schemas.py -- the structured DfM recommendation
schema (Stage 5, roadmap §4.5).
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from backend.agent.schemas import DfMFinding, DfMReport, EvidenceSource, Severity


def _finding(**overrides) -> DfMFinding:
    base = dict(
        finding_id="f1",
        category="undercut",
        severity=Severity.HIGH,
        title="12 faces below minimum draft",
        description="Faces 3, 7, 9 have less than 0.5deg draft.",
        affected_face_ids=[3, 7, 9],
        measured_values={"min_draft_deg": 0.3},
        evidence_source=EvidenceSource.BOOLEAN_CONFIRMED,
        confidence=0.9,
        recommendation="Increase draft to at least 1.5deg on the affected faces.",
        estimated_tooling_impact="requires side-action slide",
    )
    base.update(overrides)
    return DfMFinding(**base)


def test_dfm_finding_validates_a_correct_shape():
    finding = _finding()
    assert finding.severity == Severity.HIGH
    assert finding.evidence_source == EvidenceSource.BOOLEAN_CONFIRMED
    assert finding.affected_face_ids == [3, 7, 9]


def test_dfm_finding_rejects_confidence_outside_0_1():
    with pytest.raises(ValidationError):
        _finding(confidence=1.5)


def test_dfm_finding_estimated_tooling_impact_is_optional():
    finding = _finding(estimated_tooling_impact=None)
    assert finding.estimated_tooling_impact is None


def test_dfm_finding_rejects_unknown_category():
    with pytest.raises(ValidationError):
        _finding(category="not_a_real_category")


def test_dfm_report_validates_and_serializes_to_json_safe_dict():
    report = DfMReport(
        part_name="Part1.stp",
        pull_direction=(0.0, 0.0, 1.0),
        pull_direction_source="optimal",
        overall_manufacturability="acceptable",
        findings=[_finding()],
        summary="One high-severity undercut finding.",
        analysis_warnings=["Boolean refinement skipped 2 faces."],
        tools_called=["optimize_pull_direction", "detect_undercuts"],
    )
    payload = report.model_dump(mode="json")
    # Must be genuinely JSON-serializable (datetime/enum/tuple all resolved).
    dumped = json.dumps(payload)
    reloaded = json.loads(dumped)
    assert reloaded["part_name"] == "Part1.stp"
    assert reloaded["pull_direction"] == [0.0, 0.0, 1.0]
    assert reloaded["findings"][0]["severity"] == "high"
    assert reloaded["findings"][0]["evidence_source"] == "boolean_confirmed"
    assert isinstance(reloaded["generated_at"], str)


def test_dfm_report_defaults_to_empty_findings_and_warnings():
    report = DfMReport(
        part_name="Part1.stp",
        pull_direction=(0.0, 0.0, 1.0),
        pull_direction_source="default_z",
        overall_manufacturability="good",
        summary="No issues found.",
    )
    assert report.findings == []
    assert report.analysis_warnings == []
    assert report.tools_called == []


def test_severity_and_evidence_source_enum_values_are_stable():
    # Locks the exact wire values the agent's system prompt promises the
    # model it must use -- a silent rename here would desync the prompt.
    assert {s.value for s in Severity} == {"critical", "high", "medium", "low"}
    assert {e.value for e in EvidenceSource} == {
        "boolean_confirmed", "proxy_heuristic", "user_supplied",
    }
