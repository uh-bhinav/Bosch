"""
backend/agent/dfm_agent.py
----------------------------
Orchestration loop (Stage 5, roadmap §4.6).

`run_dfm_analysis` drives the tool-calling loop against whichever provider
is configured, then parses the model's final structured JSON output into a
`DfMReport`. `tools_called` and `pull_direction`/`pull_direction_source` are
tracked mechanically from what actually executed, NOT reported by the model
-- an agent narrating its own audit trail is exactly the kind of claim this
project's honesty rules exist to prevent (see `.claude/rules/
honesty-and-scope.md`).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from backend.config import settings
from backend.agent.prompts import system_prompt
from backend.agent.providers import (
    LLMProvider, Message, ProviderResponse, ToolCall, build_provider,
)
from backend.agent.schemas import DfMReport
from backend.agent.tools import TOOL_SPECS, TOOLS_BY_NAME

logger = logging.getLogger(__name__)


def execute_tool(call: ToolCall, filename: str) -> dict:
    """Dispatch one tool call. Never raises -- matches CLAUDE.md invariant #5."""
    spec = TOOLS_BY_NAME.get(call.name)
    if spec is None:
        return {
            "status": "error",
            "code": "unknown_tool",
            "message": f"No such tool: {call.name!r}",
            "recovery_hint": "Only call tools from the provided tool list.",
        }
    args = dict(call.arguments)
    args.setdefault("filename", filename)
    try:
        return spec.fn(**args)
    except TypeError as exc:
        return {
            "status": "error",
            "code": "invalid_tool_arguments",
            "message": str(exc),
            "recovery_hint": "Check the tool's parameter schema and retry with valid arguments.",
        }


def _user_message(filename: str, user_query: Optional[str]) -> str:
    base = f"Perform a Design for Manufacturability review of {filename}."
    if user_query:
        base += f" Specific focus requested by the engineer: {user_query}"
    base += (
        "\n\nCall tools as needed to gather real measurements. When you are "
        "done, respond with ONLY a JSON object (no prose, no markdown code "
        "fence) matching exactly this shape:\n"
        '{"overall_manufacturability": "good"|"acceptable"|"problematic"|'
        '"not_manufacturable", "findings": [{"finding_id": str, '
        '"category": "draft"|"undercut"|"parting_line"|"core_cavity"|'
        '"pull_direction", "severity": "critical"|"high"|"medium"|"low", '
        '"title": str, "description": str, "affected_face_ids": [int], '
        '"measured_values": {str: float}, "evidence_source": '
        '"boolean_confirmed"|"proxy_heuristic"|"user_supplied", '
        '"confidence": float 0-1, "recommendation": str, '
        '"estimated_tooling_impact": str or null}], "summary": str, '
        '"analysis_warnings": [str]}'
    )
    return base


def _track_direction(
    call: ToolCall, result: dict, current: tuple[tuple[float, float, float], str],
) -> tuple[tuple[float, float, float], str]:
    """
    Rule: pull_direction/pull_direction_source come from what actually ran,
    not the model's prose.

    Real bug found and fixed during live verification (2026-07-28): once
    `optimize_pull_direction` establishes the direction as "optimal", the
    system prompt correctly instructs the model to pass that exact vector
    into every subsequent tool call so all analyses stay consistent -- but
    naively re-classifying "a pull_direction argument was supplied" as
    "user_specified" turned every one of those propagating calls into a
    false override, silently downgrading a real `optimize_pull_direction`
    result to a fabricated "user_specified" source. "optimal", once set,
    must win for the rest of the run.
    """
    if result.get("status") == "error":
        return current
    if call.name == "optimize_pull_direction":
        best = result.get("best_direction")
        if best and len(best) == 3:
            return (float(best[0]), float(best[1]), float(best[2])), "optimal"
    _, current_source = current
    if current_source == "optimal":
        return current
    supplied = call.arguments.get("pull_direction")
    if supplied and len(supplied) == 3:
        return (float(supplied[0]), float(supplied[1]), float(supplied[2])), "user_specified"
    return current


def _fallback_report(filename: str, reason: str) -> DfMReport:
    return DfMReport(
        part_name=filename,
        pull_direction=(0.0, 0.0, 1.0),
        pull_direction_source="default_z",
        overall_manufacturability="acceptable",
        findings=[],
        summary=f"Agent analysis did not complete: {reason}",
        analysis_warnings=[reason],
        tools_called=[],
    )


def _parse_report(
    filename: str,
    text: Optional[str],
    tools_called: list[str],
    direction: tuple[float, float, float],
    direction_source: str,
) -> DfMReport:
    if not text:
        return _fallback_report(filename, "Model returned no final text output.")
    stripped = text.strip()
    if stripped.startswith("```"):
        # Tolerate a markdown fence even though the prompt asks for none.
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:]
        stripped = stripped.strip()
    try:
        raw = json.loads(stripped)
    except json.JSONDecodeError as exc:
        return _fallback_report(filename, f"Model output was not valid JSON: {exc}")

    raw["part_name"] = filename
    raw["pull_direction"] = direction
    raw["pull_direction_source"] = direction_source
    raw["tools_called"] = tools_called
    raw["generated_at"] = datetime.now(timezone.utc).isoformat()

    try:
        return DfMReport.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError, kept broad per rule 4's spirit
        return _fallback_report(filename, f"Model output did not match the DfMReport schema: {exc}")


def run_dfm_analysis(
    filename: str,
    *,
    user_query: Optional[str] = None,
    provider: Optional[LLMProvider] = None,
) -> DfMReport:
    """
    Run the full DfM tool-calling sweep against `filename` and return a
    structured `DfMReport`.

    Notes (roadmap §4.6):
    - Bounded by `settings.agent.max_tool_iterations` (default 8) to prevent
      a runaway spend.
    - All tool calls in a single provider turn are executed, THEN all
      results are appended together -- splitting them across turns degrades
      parallel tool-calling on every provider.
    - `execute_tool` never raises.
    """
    provider = provider or build_provider(settings.agent)
    messages: list[Message] = [Message(role="user", content=_user_message(filename, user_query))]
    tools_called: list[str] = []
    direction: tuple[float, float, float] = (0.0, 0.0, 1.0)
    direction_source = "default_z"
    response: Optional[ProviderResponse] = None

    for _ in range(settings.agent.max_tool_iterations):
        response = provider.invoke(
            messages, TOOL_SPECS, system=system_prompt(), temperature=settings.agent.temperature,
        )
        if not response.tool_calls:
            break
        messages.append(Message(role="assistant", content=response.text, tool_calls=response.tool_calls))
        for call in response.tool_calls:
            tools_called.append(call.name)
            result = execute_tool(call, filename)
            direction, direction_source = _track_direction(call, result, (direction, direction_source))
            messages.append(Message(
                role="tool", tool_call_id=call.id, tool_name=call.name, tool_result=result,
            ))

    if response is None:
        return _fallback_report(filename, "max_tool_iterations is 0; the agent never ran.")

    return _parse_report(filename, response.text, tools_called, direction, direction_source)
