"""
tests/test_dfm_agent.py
--------------------------
Tests for backend/agent/dfm_agent.py -- the orchestration loop (Stage 5,
roadmap §4.6).

Mock-based tests here verify the loop's logic (bounded iterations, batched
tool execution, direction tracking, report parsing) without a live provider
call. The real end-to-end verification against a live Gemini API key (which
is how the direction-tracking bug below was actually found) is documented in
CHANGELOG.md 2026-07-28 rather than re-run on every CI pass -- it depends on
a real GOOGLE_API_KEY and network access.
"""
from __future__ import annotations

import json

import pytest

from backend.agent.dfm_agent import _parse_report, _track_direction, execute_tool, run_dfm_analysis
from backend.agent.providers import Message, ProviderResponse, ToolCall, TokenUsage


class _ScriptedProvider:
    """A fake LLMProvider that returns a pre-scripted sequence of responses."""

    name = "scripted"

    def __init__(self, responses: list[ProviderResponse]):
        self._responses = list(responses)
        self.invocations: list[list[Message]] = []

    def invoke(self, messages, tools, *, system, temperature=0.1):
        self.invocations.append(list(messages))
        return self._responses.pop(0)


_VALID_FINAL_JSON = json.dumps({
    "overall_manufacturability": "acceptable",
    "findings": [{
        "finding_id": "f1",
        "category": "draft",
        "severity": "low",
        "title": "Marginal draft on one face",
        "description": "Face 232 is slightly under the draft minimum.",
        "affected_face_ids": [232],
        "measured_values": {"min_draft_angle_deg": 1.075},
        "evidence_source": "boolean_confirmed",
        "confidence": 1.0,
        "recommendation": "Increase draft on face 232.",
        "estimated_tooling_impact": None,
    }],
    "summary": "One minor draft issue.",
    "analysis_warnings": [],
})


# ---------------------------------------------------------------------------
# execute_tool
# ---------------------------------------------------------------------------


def test_execute_tool_returns_structured_error_for_unknown_tool():
    call = ToolCall(id="x_0", name="not_a_real_tool", arguments={})
    result = execute_tool(call, "Part1.stp")
    assert result["status"] == "error"
    assert result["code"] == "unknown_tool"


def test_execute_tool_injects_filename_when_the_model_omits_it(monkeypatch):
    captured = {}

    def _fake_tool(filename):
        captured["filename"] = filename
        return {"status": "ok"}

    from backend.agent import dfm_agent as agent_module
    monkeypatch.setitem(
        agent_module.TOOLS_BY_NAME, "load_part_summary",
        agent_module.TOOLS_BY_NAME["load_part_summary"].__class__(
            name="load_part_summary", description="d", parameters={}, fn=_fake_tool,
        ),
    )
    call = ToolCall(id="x_0", name="load_part_summary", arguments={})
    result = execute_tool(call, "Part1.stp")
    assert result == {"status": "ok"}
    assert captured["filename"] == "Part1.stp"


def test_execute_tool_returns_structured_error_for_bad_arguments(monkeypatch):
    from backend.agent import dfm_agent as agent_module

    def _fake_tool(filename, required_arg):
        return {"status": "ok"}

    monkeypatch.setitem(
        agent_module.TOOLS_BY_NAME, "load_part_summary",
        agent_module.TOOLS_BY_NAME["load_part_summary"].__class__(
            name="load_part_summary", description="d", parameters={}, fn=_fake_tool,
        ),
    )
    call = ToolCall(id="x_0", name="load_part_summary", arguments={})
    result = execute_tool(call, "Part1.stp")
    assert result["status"] == "error"
    assert result["code"] == "invalid_tool_arguments"


# ---------------------------------------------------------------------------
# run_dfm_analysis -- loop control
# ---------------------------------------------------------------------------


def test_run_dfm_analysis_stops_immediately_when_no_tool_calls():
    provider = _ScriptedProvider([
        ProviderResponse(text=_VALID_FINAL_JSON, tool_calls=[], finish_reason="end_turn", usage=TokenUsage()),
    ])
    report = run_dfm_analysis("Part1.stp", provider=provider)
    assert report.overall_manufacturability == "acceptable"
    assert report.tools_called == []
    assert len(provider.invocations) == 1


def test_run_dfm_analysis_executes_batched_tool_calls_then_continues(monkeypatch):
    from backend.agent import dfm_agent as agent_module

    def _fake_optimize(filename):
        return {"status": "ok", "best_direction": [0.232, 0.357, 0.905]}

    def _fake_draft(filename, pull_direction=None):
        return {"status": "ok", "bad_face_ids": [232]}

    monkeypatch.setitem(
        agent_module.TOOLS_BY_NAME, "optimize_pull_direction",
        agent_module.TOOLS_BY_NAME["optimize_pull_direction"].__class__(
            name="optimize_pull_direction", description="d", parameters={}, fn=_fake_optimize,
        ),
    )
    monkeypatch.setitem(
        agent_module.TOOLS_BY_NAME, "analyze_draft",
        agent_module.TOOLS_BY_NAME["analyze_draft"].__class__(
            name="analyze_draft", description="d", parameters={}, fn=_fake_draft,
        ),
    )

    first_turn = ProviderResponse(
        text=None,
        tool_calls=[
            ToolCall(id="opt_0", name="optimize_pull_direction", arguments={"filename": "Part1.stp"}),
            ToolCall(id="draft_0", name="analyze_draft", arguments={
                "filename": "Part1.stp", "pull_direction": [0.232, 0.357, 0.905],
            }),
        ],
        finish_reason="tool_use",
        usage=TokenUsage(),
    )
    second_turn = ProviderResponse(
        text=_VALID_FINAL_JSON, tool_calls=[], finish_reason="end_turn", usage=TokenUsage(),
    )
    provider = _ScriptedProvider([first_turn, second_turn])

    report = run_dfm_analysis("Part1.stp", provider=provider)

    assert report.tools_called == ["optimize_pull_direction", "analyze_draft"]
    assert report.pull_direction == (0.232, 0.357, 0.905)
    assert report.pull_direction_source == "optimal"
    # Both tool calls from the first turn must be executed and appended
    # together (batched), not split across separate provider turns.
    assert len(provider.invocations) == 2
    second_call_messages = provider.invocations[1]
    tool_role_messages = [m for m in second_call_messages if m.role == "tool"]
    assert len(tool_role_messages) == 2


def _with_max_tool_iterations(monkeypatch, value: int) -> None:
    """
    `AgentSettings`/`Settings` are frozen dataclasses, so a plain
    `monkeypatch.setattr(settings.agent, ...)` raises `FrozenInstanceError`.
    Rebuild the settings object via `dataclasses.replace()` and patch the
    name `dfm_agent` actually resolved at import time (`from backend.config
    import settings` binds a local name in that module's namespace --
    patching `backend.config.settings` alone would not affect it).
    """
    import dataclasses
    from backend.agent import dfm_agent as agent_module

    new_agent_settings = dataclasses.replace(agent_module.settings.agent, max_tool_iterations=value)
    new_settings = dataclasses.replace(agent_module.settings, agent=new_agent_settings)
    monkeypatch.setattr(agent_module, "settings", new_settings)


def test_run_dfm_analysis_bounds_the_loop_at_max_tool_iterations(monkeypatch):
    # A provider that ALWAYS requests another tool call -- without the
    # bound, this would loop forever.
    def _never_ending_response(*_args, **_kwargs):
        return ProviderResponse(
            text=None,
            tool_calls=[ToolCall(id="x_0", name="load_part_summary", arguments={"filename": "Part1.stp"})],
            finish_reason="tool_use",
            usage=TokenUsage(),
        )

    class _InfiniteProvider:
        name = "infinite"

        def invoke(self, *args, **kwargs):
            return _never_ending_response()

    _with_max_tool_iterations(monkeypatch, 3)
    provider = _InfiniteProvider()
    report = run_dfm_analysis("Part1.stp", provider=provider)
    # Loop ran to the bound and never produced a final JSON answer -> falls
    # back to a structured "did not complete" report rather than hanging.
    assert "did not complete" in report.summary or report.analysis_warnings


def test_run_dfm_analysis_zero_iterations_returns_a_fallback_report(monkeypatch):
    _with_max_tool_iterations(monkeypatch, 0)
    provider = _ScriptedProvider([])
    report = run_dfm_analysis("Part1.stp", provider=provider)
    assert report.overall_manufacturability == "acceptable"
    assert "never ran" in report.analysis_warnings[0]


# ---------------------------------------------------------------------------
# _track_direction -- regression test for the real bug found during live
# verification (2026-07-28): once "optimal" is established, a later tool
# call that echoes that same direction back (as the system prompt instructs)
# must NOT be re-classified as "user_specified".
# ---------------------------------------------------------------------------


def test_track_direction_optimal_source_is_not_overwritten_by_propagated_calls():
    state = ((0.0, 0.0, 1.0), "default_z")

    optimize_call = ToolCall(id="opt_0", name="optimize_pull_direction", arguments={"filename": "Part1.stp"})
    optimize_result = {"status": "ok", "best_direction": [0.232, 0.357, 0.905]}
    state = _track_direction(optimize_call, optimize_result, state)
    assert state == ((0.232, 0.357, 0.905), "optimal")

    # The system prompt instructs the model to pass the established
    # direction into every subsequent tool call -- this must NOT look like
    # a human override.
    draft_call = ToolCall(
        id="draft_0", name="analyze_draft",
        arguments={"filename": "Part1.stp", "pull_direction": [0.232, 0.357, 0.905]},
    )
    state = _track_direction(draft_call, {"status": "ok"}, state)
    assert state == ((0.232, 0.357, 0.905), "optimal"), (
        "A propagated pull_direction argument overwrote the 'optimal' source "
        "with a false 'user_specified' -- this is the exact 2026-07-28 bug."
    )


def test_track_direction_treats_a_pre_optimal_direction_as_user_specified():
    # Before optimize_pull_direction has ever run, a supplied direction is
    # the only signal available -- treat it as user_specified.
    state = ((0.0, 0.0, 1.0), "default_z")
    call = ToolCall(
        id="draft_0", name="analyze_draft",
        arguments={"filename": "Part1.stp", "pull_direction": [1.0, 0.0, 0.0]},
    )
    state = _track_direction(call, {"status": "ok"}, state)
    assert state == ((1.0, 0.0, 0.0), "user_specified")


def test_track_direction_ignores_error_results():
    state = ((0.0, 0.0, 1.0), "default_z")
    call = ToolCall(id="opt_0", name="optimize_pull_direction", arguments={"filename": "Part1.stp"})
    error_result = {"status": "error", "code": "step_load_failed"}
    assert _track_direction(call, error_result, state) == state


# ---------------------------------------------------------------------------
# _parse_report
# ---------------------------------------------------------------------------


def test_parse_report_handles_invalid_json_gracefully():
    report = _parse_report("Part1.stp", "not valid json at all", [], (0.0, 0.0, 1.0), "default_z")
    assert "did not complete" in report.summary
    assert any("not valid JSON" in w for w in report.analysis_warnings)


def test_parse_report_strips_a_markdown_code_fence():
    fenced = f"```json\n{_VALID_FINAL_JSON}\n```"
    report = _parse_report("Part1.stp", fenced, ["analyze_draft"], (0.0, 0.0, 1.0), "optimal")
    assert report.overall_manufacturability == "acceptable"
    assert len(report.findings) == 1


def test_parse_report_falls_back_on_schema_mismatch():
    bad_shape = json.dumps({"overall_manufacturability": "not-a-valid-enum-value", "findings": []})
    report = _parse_report("Part1.stp", bad_shape, [], (0.0, 0.0, 1.0), "default_z")
    assert "did not match the DfMReport schema" in report.analysis_warnings[0]


def test_parse_report_fills_in_mechanically_tracked_fields_not_model_reported():
    report = _parse_report(
        "Part1.stp", _VALID_FINAL_JSON, ["optimize_pull_direction", "analyze_draft"],
        (0.232, 0.357, 0.905), "optimal",
    )
    assert report.part_name == "Part1.stp"
    assert report.tools_called == ["optimize_pull_direction", "analyze_draft"]
    assert report.pull_direction == (0.232, 0.357, 0.905)
    assert report.pull_direction_source == "optimal"


def test_parse_report_handles_no_text_output():
    report = _parse_report("Part1.stp", None, [], (0.0, 0.0, 1.0), "default_z")
    assert "no final text" in report.analysis_warnings[0]
