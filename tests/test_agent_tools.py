"""
tests/test_agent_tools.py
---------------------------
Tests for backend/agent/tools.py -- the six DfM tool definitions wrapping
the geometry engine (Stage 5, roadmap §4.3), and the four hard rules they
must all follow (never return OCC handles, always mutate=False, truncate
aggressively, surface failures as data).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.agent import tools as agent_tools

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PART1_PATH = PROJECT_ROOT / "data" / "parts" / "Part1.stp"
HAS_OCC = True
try:
    import OCC  # noqa: F401
except ImportError:
    HAS_OCC = False

skip_no_occ = pytest.mark.skipif(not HAS_OCC, reason="pythonocc-core not installed")
skip_no_part1 = pytest.mark.skipif(
    not PART1_PATH.exists(), reason=f"Part1.stp not found at {PART1_PATH}"
)


# ---------------------------------------------------------------------------
# _resolve_part_path -- mirrors main.py's path-traversal guard
# ---------------------------------------------------------------------------


def test_resolve_part_path_rejects_path_traversal():
    with pytest.raises(ValueError, match="path separators"):
        agent_tools._resolve_part_path("../data/parts/Part1.stp")


def test_resolve_part_path_rejects_a_missing_file():
    with pytest.raises(FileNotFoundError):
        agent_tools._resolve_part_path("DefinitelyNotARealFile.stp")


@skip_no_part1
def test_resolve_part_path_accepts_a_real_file():
    path = agent_tools._resolve_part_path("Part1.stp")
    assert path == PART1_PATH


# ---------------------------------------------------------------------------
# _tool_safe -- rule 4: never raise, always return structured error data
# ---------------------------------------------------------------------------


def test_tool_safe_converts_value_error_to_structured_error():
    @agent_tools._tool_safe
    def _boom():
        raise ValueError("bad input")

    result = _boom()
    assert result["status"] == "error"
    assert result["code"] == "invalid_part_reference"
    assert "bad input" in result["message"]
    assert "recovery_hint" in result


def test_tool_safe_converts_file_not_found_to_structured_error():
    @agent_tools._tool_safe
    def _boom():
        raise FileNotFoundError("nope")

    result = _boom()
    assert result["status"] == "error"
    assert result["code"] == "invalid_part_reference"


def test_tool_safe_converts_arbitrary_exception_to_structured_error():
    @agent_tools._tool_safe
    def _boom():
        raise RuntimeError("something unexpected")

    result = _boom()
    assert result["status"] == "error"
    assert result["code"] == "tool_execution_failed"
    assert "RuntimeError" in result["message"]


def test_tool_safe_passes_through_a_successful_result():
    @agent_tools._tool_safe
    def _ok():
        return {"status": "ok", "value": 42}

    assert _ok() == {"status": "ok", "value": 42}


# ---------------------------------------------------------------------------
# _truncate_ids -- rule 3: cap face-ID lists
# ---------------------------------------------------------------------------


def test_truncate_ids_below_cap_is_untouched():
    ids = list(range(10))
    result, truncated = agent_tools._truncate_ids(ids)
    assert result == ids
    assert truncated is False


def test_truncate_ids_above_cap_truncates_and_flags():
    ids = list(range(1000))
    result, truncated = agent_tools._truncate_ids(ids)
    assert len(result) == agent_tools.settings.agent.max_face_ids_per_tool
    assert truncated is True


# ---------------------------------------------------------------------------
# _normalize_direction
# ---------------------------------------------------------------------------


def test_normalize_direction_defaults_to_plus_z():
    assert agent_tools._normalize_direction(None) == (0.0, 0.0, 1.0)
    assert agent_tools._normalize_direction([]) == (0.0, 0.0, 1.0)


def test_normalize_direction_passes_through_a_valid_vector():
    assert agent_tools._normalize_direction([1.0, 0.0, 0.0]) == (1.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# TOOL_SPECS -- structural checks across all six tools
# ---------------------------------------------------------------------------


def test_tool_specs_has_exactly_six_tools_matching_the_roadmap():
    names = {spec.name for spec in agent_tools.TOOL_SPECS}
    assert names == {
        "load_part_summary",
        "optimize_pull_direction",
        "analyze_draft",
        "detect_undercuts",
        "detect_parting_line",
        "classify_core_cavity",
    }


def test_every_tool_spec_requires_filename():
    for spec in agent_tools.TOOL_SPECS:
        assert "filename" in spec.parameters["properties"]
        assert "filename" in spec.parameters["required"]


def test_tools_by_name_matches_tool_specs():
    assert set(agent_tools.TOOLS_BY_NAME.keys()) == {s.name for s in agent_tools.TOOL_SPECS}
    for spec in agent_tools.TOOL_SPECS:
        assert agent_tools.TOOLS_BY_NAME[spec.name] is spec


# ---------------------------------------------------------------------------
# End-to-end real-geometry checks: rule 1 (no OCC handles), rule 2 (mutate
# safety), all six tools actually running against Part1.stp.
# ---------------------------------------------------------------------------


def _assert_no_occ_handles(payload: object) -> None:
    """Recursively assert no dict key that looks like a raw OCC handle field."""
    forbidden = {"occ_face", "occ_edge", "occ_shape", "occ_vertex"}
    if isinstance(payload, dict):
        for key, value in payload.items():
            assert key not in forbidden, f"OCC handle key {key!r} leaked into tool output"
            _assert_no_occ_handles(value)
    elif isinstance(payload, list):
        for item in payload:
            _assert_no_occ_handles(item)


@skip_no_occ
@skip_no_part1
def test_load_part_summary_real_part1():
    result = agent_tools.load_part_summary("Part1.stp")
    assert result["status"] == "ok"
    assert result["face_count"] > 0
    _assert_no_occ_handles(result)


@skip_no_occ
@skip_no_part1
def test_optimize_pull_direction_real_part1():
    result = agent_tools.optimize_pull_direction("Part1.stp")
    assert result["status"] == "ok"
    assert len(result["best_direction"]) == 3
    _assert_no_occ_handles(result)


@skip_no_occ
@skip_no_part1
def test_analyze_draft_tool_real_part1_truncates_bad_face_ids():
    result = agent_tools.analyze_draft_tool("Part1.stp", pull_direction=[0.0, 0.0, 1.0])
    assert result["status"] == "ok"
    assert "bad_face_ids_truncated" in result
    _assert_no_occ_handles(result)


@skip_no_occ
@skip_no_part1
def test_detect_undercuts_tool_real_part1_marks_evidence_source_data():
    result = agent_tools.detect_undercuts_tool("Part1.stp", pull_direction=[0.0, 0.0, 1.0])
    assert result["status"] == "ok"
    for feature in result.get("features", []):
        assert "face_ids_truncated" in feature
    _assert_no_occ_handles(result)


@skip_no_occ
@skip_no_part1
def test_detect_parting_line_tool_real_part1():
    result = agent_tools.detect_parting_line_tool("Part1.stp", pull_direction=[0.0, 0.0, 1.0])
    assert result["status"] == "ok"
    _assert_no_occ_handles(result)


@skip_no_occ
@skip_no_part1
def test_classify_core_cavity_tool_real_part1():
    result = agent_tools.classify_core_cavity_tool("Part1.stp", pull_direction=[0.0, 0.0, 1.0])
    assert result["status"] == "ok"
    _assert_no_occ_handles(result)


@skip_no_occ
@skip_no_part1
def test_tool_calls_never_mutate_the_shared_load_step_cached_template():
    """
    Rule 2 (mutate=False), verified against the real S3.8 cache: calling a
    tool must never leave a mutated face/direction field visible to a
    fresh load_step_cached() call afterwards.
    """
    from backend.geometry.step_loader import load_step_cached

    before = load_step_cached(PART1_PATH)
    assert before.optimal_pull_direction is None

    agent_tools.optimize_pull_direction("Part1.stp")
    agent_tools.analyze_draft_tool("Part1.stp", pull_direction=[0.0, 0.0, 1.0])
    agent_tools.detect_undercuts_tool("Part1.stp", pull_direction=[0.0, 0.0, 1.0])

    after = load_step_cached(PART1_PATH)
    assert after.optimal_pull_direction is None, (
        "A tool call mutated the cached template's optimal_pull_direction -- "
        "this would corrupt every other concurrent request's geometry."
    )
