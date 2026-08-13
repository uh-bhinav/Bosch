"""
backend/agent/tools.py
------------------------
Tool definitions wrapping the geometry engine (Stage 5, roadmap §4.3).

Six tools mirror the six analysis endpoints in `backend/api/main.py`. Every
tool follows the roadmap's four hard rules:

1. **Never return OCC handles.** Every tool returns the result of a
   dataclass's `.to_dict()` (or a plain dict built from JSON-safe fields) --
   `occ_face`/`occ_edge`/`occ_shape` never approach the LLM boundary.
2. **Always `mutate=False`.** Every geometry call below passes `mutate=False`
   where the function supports it. This is belt-and-suspenders: since Stage
   3.8, `load_step_cached()` already hands every caller a fresh,
   independently-mutable clone (mutating one clone can never affect another,
   verified by `tests/test_step_loader.py::TestLoadStepCached`), so a stray
   `mutate=True` here would not corrupt a *different* request's state the way
   the roadmap originally worried about under a hypothetical shared-object
   cache -- but it would still make a single tool call's behavior
   inconsistent with a read-only, exploratory agent call, so the flag is
   still set deliberately on every call that exposes it.
3. **Truncate aggressively.** Long face-ID lists are capped at
   `agent.max_face_ids_per_tool` (default 25) with a `truncated: true`
   marker rather than dumping hundreds of raw IDs into context.
4. **Surface failures as data, not exceptions.** `_tool_safe` catches every
   exception and returns `{"status": "error", "code", "message",
   "recovery_hint"}` -- the same structured shape `backend/api/main.py`
   already uses (CLAUDE.md invariant #5) -- so a Boolean failure or a bad
   filename is something the agent can reason about, never a crash.
"""
from __future__ import annotations

from functools import wraps
from pathlib import Path
from typing import Any, Callable

from backend.config import settings
from backend.geometry.core_cavity import classify_core_cavity
from backend.geometry.direction_optimizer import optimize_mold_direction
from backend.geometry.draft_analyzer import analyze_draft
from backend.geometry.parting_line import detect_parting_line_candidates
from backend.geometry.step_loader import STEPLoadError, load_step_cached
from backend.geometry.undercut_detector import detect_undercuts
from backend.agent.providers import ToolSpec

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PARTS_DIR = PROJECT_ROOT / "data" / "parts"


def _resolve_part_path(filename: str) -> Path:
    """Mirrors backend/api/main.py's `_part_path_or_raise` path-traversal guard."""
    safe_name = Path(filename).name
    if safe_name != filename:
        raise ValueError(f"filename must not contain path separators: {filename!r}")
    path = PARTS_DIR / safe_name
    if not path.exists():
        raise FileNotFoundError(f"STEP file not found: {safe_name} (looked in {PARTS_DIR})")
    return path


def _tool_safe(fn: Callable[..., dict]) -> Callable[..., dict]:
    """Rule 4: every tool call returns structured data, never raises."""

    @wraps(fn)
    def wrapper(*args, **kwargs) -> dict:
        try:
            return fn(*args, **kwargs)
        except (FileNotFoundError, ValueError) as exc:
            return {
                "status": "error",
                "code": "invalid_part_reference",
                "message": str(exc),
                "recovery_hint": "Call load_part_summary first to confirm the filename is valid.",
            }
        except STEPLoadError as exc:
            return {
                "status": "error",
                "code": "step_load_failed",
                "message": str(exc),
                "recovery_hint": "The STEP file may be malformed; check it loads outside the agent.",
            }
        except Exception as exc:  # noqa: BLE001 -- last-resort guard, rule 4
            return {
                "status": "error",
                "code": "tool_execution_failed",
                "message": f"{type(exc).__name__}: {exc}",
                "recovery_hint": "This tool call could not complete; treat the analysis as unavailable.",
            }

    return wrapper


def _truncate_ids(ids: list[int]) -> tuple[list[int], bool]:
    cap = settings.agent.max_face_ids_per_tool
    if len(ids) <= cap:
        return ids, False
    return ids[:cap], True


def _normalize_direction(pull_direction: list[float] | None) -> tuple[float, float, float]:
    if not pull_direction or len(pull_direction) != 3:
        return (0.0, 0.0, 1.0)
    return (float(pull_direction[0]), float(pull_direction[1]), float(pull_direction[2]))


@_tool_safe
def load_part_summary(filename: str) -> dict:
    part = load_step_cached(_resolve_part_path(filename))
    summary = part.to_dict(include_faces=False)
    summary["status"] = "ok"
    return summary


@_tool_safe
def optimize_pull_direction(filename: str) -> dict:
    part = load_step_cached(_resolve_part_path(filename))
    result = optimize_mold_direction(part)
    payload = result.to_dict(include_all_candidates=False)
    payload["status"] = "ok"
    return payload


@_tool_safe
def analyze_draft_tool(filename: str, pull_direction: list[float] | None = None) -> dict:
    part = load_step_cached(_resolve_part_path(filename))
    direction = _normalize_direction(pull_direction)
    result = analyze_draft(part, direction, pull_direction_label="agent-tool-call", mutate=False)
    payload = result.to_dict()
    bad_ids, truncated = _truncate_ids(payload.get("bad_face_ids", []))
    payload["bad_face_ids"] = bad_ids
    payload["bad_face_ids_truncated"] = truncated
    payload["status"] = "ok"
    return payload


@_tool_safe
def detect_undercuts_tool(filename: str, pull_direction: list[float] | None = None) -> dict:
    part = load_step_cached(_resolve_part_path(filename))
    direction = _normalize_direction(pull_direction)
    result = detect_undercuts(part, direction, mutate=False, boolean_refine=True)
    payload = result.to_dict()
    for feature in payload.get("features", []):
        ids, truncated = _truncate_ids(feature.get("face_ids", []))
        feature["face_ids"] = ids
        feature["face_ids_truncated"] = truncated
    payload["status"] = "ok"
    return payload


@_tool_safe
def detect_parting_line_tool(filename: str, pull_direction: list[float] | None = None) -> dict:
    part = load_step_cached(_resolve_part_path(filename))
    direction = _normalize_direction(pull_direction)
    result = detect_parting_line_candidates(part, direction, mutate=False)
    payload = result.to_dict()
    # Truncate large point lists (Rule 3) -- these are display-resolution
    # curve samples, not decision-relevant to the agent at full resolution.
    for key in ("wire_points",):
        if isinstance(payload.get(key), list) and len(payload[key]) > 50:
            payload[key] = payload[key][:50]
            payload[f"{key}_truncated"] = True
    payload["status"] = "ok"
    return payload


@_tool_safe
def classify_core_cavity_tool(filename: str, pull_direction: list[float] | None = None) -> dict:
    part = load_step_cached(_resolve_part_path(filename))
    direction = _normalize_direction(pull_direction)
    result = classify_core_cavity(part, pull_direction=direction, mutate=False)
    payload = result.to_dict()
    payload["status"] = "ok"
    return payload


_DIRECTION_PARAM = {
    "type": "array",
    "description": "Optional unit pull direction [x, y, z]. Omit to use +Z. "
                   "Pass the exact vector from optimize_pull_direction's "
                   "best_direction to keep all analyses consistent.",
    "items": {"type": "number"},
}

TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="load_part_summary",
        description=(
            "Load a STEP file and return topology counts, bounding box, and "
            "surface-type histogram. Call this first to confirm the part "
            "loads and to see its basic shape before deeper analysis."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "STEP filename in data/parts/, e.g. Part1.stp"},
            },
            "required": ["filename"],
        },
        fn=load_part_summary,
    ),
    ToolSpec(
        name="optimize_pull_direction",
        description=(
            "Run the full direction search and return the best mold-opening "
            "pull direction, its score, and candidate ranking. Call this "
            "FIRST (before draft/undercuts/parting-line/core-cavity) unless "
            "the user specified a direction -- pull direction is foundational "
            "and every other analysis is computed relative to it."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "STEP filename in data/parts/, e.g. Part1.stp"},
            },
            "required": ["filename"],
        },
        fn=optimize_pull_direction,
    ),
    ToolSpec(
        name="analyze_draft",
        description=(
            "Compute draft-angle classification (good/marginal/bad) for every "
            "face relative to a pull direction. Returns class counts, "
            "percentages, and the face IDs with insufficient draft."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "STEP filename in data/parts/, e.g. Part1.stp"},
                "pull_direction": _DIRECTION_PARAM,
            },
            "required": ["filename"],
        },
        fn=analyze_draft_tool,
    ),
    ToolSpec(
        name="detect_undercuts",
        description=(
            "Detect undercut/side-action features for a pull direction, with "
            "optional Boolean refinement. Returns features with severity, "
            "type, recommended mold action, and whether each face's "
            "confirmation is Boolean-confirmed vs. a proxy heuristic -- "
            "carry that distinction into any finding you report."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "STEP filename in data/parts/, e.g. Part1.stp"},
                "pull_direction": _DIRECTION_PARAM,
            },
            "required": ["filename"],
        },
        fn=detect_undercuts_tool,
    ),
    ToolSpec(
        name="detect_parting_line",
        description=(
            "Detect the candidate parting-line silhouette for a pull "
            "direction. Returns readiness, closure error, silhouette "
            "coverage, and undercut-conflict diagnostics. This is a "
            "candidate/foundation overlay, never a final optimized parting "
            "line -- label it that way unless readiness is 'ready'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "STEP filename in data/parts/, e.g. Part1.stp"},
                "pull_direction": _DIRECTION_PARAM,
            },
            "required": ["filename"],
        },
        fn=detect_parting_line_tool,
    ),
    ToolSpec(
        name="classify_core_cavity",
        description=(
            "Classify every face as cavity, core, or parting relative to a "
            "pull direction. Returns face counts and area percentages per "
            "class. This is Level 1 face classification only -- do not "
            "describe it as an exact 3-D solid split."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "STEP filename in data/parts/, e.g. Part1.stp"},
                "pull_direction": _DIRECTION_PARAM,
            },
            "required": ["filename"],
        },
        fn=classify_core_cavity_tool,
    ),
]

TOOLS_BY_NAME: dict[str, ToolSpec] = {t.name: t for t in TOOL_SPECS}
