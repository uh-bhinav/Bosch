"""
tests/test_api_error_handling.py
--------------------------------
Focused tests for structured API failure payloads.
"""

from __future__ import annotations

from pathlib import Path

import pytest

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


def test_error_detail_contains_recovery_hint():
    from backend.api.main import _error_detail

    detail = _error_detail(
        code="cad_runtime_missing",
        message="CAD runtime dependency missing.",
        operation="draft analysis",
        details={"exception": "OCC missing"},
    )

    assert detail["code"] == "cad_runtime_missing"
    assert detail["message"] == "CAD runtime dependency missing."
    assert detail["operation"] == "draft analysis"
    assert "locked Docker/conda environment" in detail["recovery_hint"]
    assert detail["details"] == {"exception": "OCC missing"}


def test_part_path_rejects_path_traversal():
    from fastapi import HTTPException

    from backend.api.main import _part_path_or_raise

    try:
        _part_path_or_raise("../Part1.stp", "STEP summary")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail["code"] == "invalid_filename"
        assert exc.detail["operation"] == "STEP summary"
    else:
        raise AssertionError("Expected path traversal filename to be rejected.")


def test_part_path_reports_missing_file(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from backend.api import main

    monkeypatch.setattr(main, "PARTS_DIR", tmp_path)

    try:
        main._part_path_or_raise("missing.stp", "undercut detection")
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail["code"] == "part_not_found"
        assert exc.detail["details"]["filename"] == "missing.stp"
    else:
        raise AssertionError("Expected missing STEP file to raise HTTPException.")


def test_list_parts_gracefully_handles_missing_directory(tmp_path, monkeypatch):
    from backend.api import main

    missing_dir = tmp_path / "does-not-exist"
    monkeypatch.setattr(main, "PARTS_DIR", missing_dir)

    payload = main.list_parts()

    assert payload["files"] == []
    assert payload["warnings"] == ["Parts directory does not exist."]


def test_parting_line_paths_payload_is_json_safe():
    from backend.api import main

    payload = main._parting_line_paths_payload({
        "wire_points": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
        "refinement": {
            "refined_points": [
                [0.0, 0.0, 0.0],
                [0.5, 0.0, 0.0],
                [1.0, 0.0, 0.0],
            ],
        },
    })

    assert payload["raw"]["point_count"] == 2
    assert payload["refined"]["point_count"] == 3
    # Both raw and refined are shown by default (matching the sidebar checkboxes).
    assert payload["raw"]["visible_by_default"] is True
    assert payload["refined"]["visible_by_default"] is True
    assert payload["legend"]["raw"]["label"] == "Raw selected parting wire"
    # Label matches PARTING_LINE_STYLES["refined"]["label"] in main.py.
    assert payload["legend"]["refined"]["label"] == "Parting Line (Refined)"


@skip_no_occ
@skip_no_part1
def test_core_cavity_endpoint_honours_a_manually_supplied_direction():
    """
    Regression guard for a real bug found while building Stage 3 S3.6
    (direction override, Bosch criterion #2): `/core-cavity` accepted
    `use_optimal_direction=false` but had no `dx`/`dy`/`dz` parameters at
    all -- it silently fell back to a hardcoded (0, 0, 1) regardless of what
    direction a caller actually wanted, with no way to classify against a
    genuinely custom direction. `/parting-line` already had the correct
    `pull_direction = (dx, dy, dz)` pattern; `/core-cavity` now matches it.
    """
    from backend.api.main import part_core_cavity

    default_z = part_core_cavity(
        "Part1.stp", use_optimal_direction=False, dx=0.0, dy=0.0, dz=1.0,
        threshold=None, solid_split=False, include_faces=False,
        include_mesh=False, mesh_deflection=0.5,
    )
    off_axis = part_core_cavity(
        "Part1.stp", use_optimal_direction=False, dx=1.0, dy=0.0, dz=0.0,
        threshold=None, solid_split=False, include_faces=False,
        include_mesh=False, mesh_deflection=0.5,
    )

    assert default_z["pull_direction_source"] == "manual_query_direction"
    assert off_axis["pull_direction_source"] == "manual_query_direction"
    # A genuinely different supplied direction must classify differently --
    # if this ever regresses to ignoring dx/dy/dz, these face counts would
    # be identical again.
    assert default_z["core_cavity"]["face_counts"] != off_axis["core_cavity"]["face_counts"]
