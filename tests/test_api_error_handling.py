"""
tests/test_api_error_handling.py
--------------------------------
Focused tests for structured API failure payloads.
"""

from __future__ import annotations


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
