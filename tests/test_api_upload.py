"""
tests/test_api_upload.py
-------------------------
API-layer tests for POST /parts/upload (F2) and the /parts, /parts/{filename}
list/resolution changes it required. Pure API-contract tests -- no OCC
dependency, since upload validation is deliberately shallow (extension,
non-empty, size cap) and never parses STEP content itself; deep STEP
validation is exercised separately wherever /summary is already tested.

Every test monkeypatches PARTS_DIR/UPLOADS_DIR to tmp_path subdirectories so
none of this ever touches the real data/parts/ or data/uploads/ on disk.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.api import main

    parts_dir = tmp_path / "parts"
    uploads_dir = tmp_path / "uploads"
    parts_dir.mkdir()
    monkeypatch.setattr(main, "PARTS_DIR", parts_dir)
    monkeypatch.setattr(main, "UPLOADS_DIR", uploads_dir)

    return TestClient(main.app)


def _step_bytes() -> bytes:
    return b"ISO-10303-21;\nHEADER;\nENDSEC;\nEND-ISO-10303-21;\n"


# ---------------------------------------------------------------------------
# Successful upload
# ---------------------------------------------------------------------------

def test_upload_stores_file_and_returns_uuid_prefixed_name(client):
    response = client.post(
        "/parts/upload",
        files={"file": ("Part1.stp", _step_bytes(), "application/octet-stream")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["original_filename"] == "Part1.stp"
    assert payload["filename"].endswith("_Part1.stp")
    assert payload["filename"] != "Part1.stp"
    assert payload["size_bytes"] == len(_step_bytes())


def test_uploaded_file_is_immediately_listed_in_parts(client):
    upload = client.post(
        "/parts/upload",
        files={"file": ("Part1.stp", _step_bytes(), "application/octet-stream")},
    ).json()

    listed = client.get("/parts").json()
    assert upload["filename"] in listed["files"]


def test_uploaded_file_is_resolvable_by_other_endpoints(client):
    from backend.api import main

    upload = client.post(
        "/parts/upload",
        files={"file": ("Part1.stp", _step_bytes(), "application/octet-stream")},
    ).json()

    safe_name, path = main._part_path_or_raise(upload["filename"], "test resolution")
    assert safe_name == upload["filename"]
    assert path == main.UPLOADS_DIR / upload["filename"]
    assert path.read_bytes() == _step_bytes()


def test_two_uploads_of_the_same_original_name_do_not_collide(client):
    first = client.post(
        "/parts/upload",
        files={"file": ("Part1.stp", _step_bytes(), "application/octet-stream")},
    ).json()
    second = client.post(
        "/parts/upload",
        files={"file": ("Part1.stp", _step_bytes(), "application/octet-stream")},
    ).json()

    assert first["filename"] != second["filename"]
    listed = client.get("/parts").json()["files"]
    assert first["filename"] in listed
    assert second["filename"] in listed


def test_upload_never_writes_into_parts_dir(client):
    from backend.api import main

    client.post(
        "/parts/upload",
        files={"file": ("Part1.stp", _step_bytes(), "application/octet-stream")},
    )
    assert list(main.PARTS_DIR.iterdir()) == []


# ---------------------------------------------------------------------------
# Invalid file handling
# ---------------------------------------------------------------------------

def test_upload_rejects_non_step_extension(client):
    response = client.post(
        "/parts/upload",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_upload_extension"
    assert error["operation"] == "STEP file upload"
    assert "recovery_hint" in error


def test_upload_rejects_empty_file(client):
    response = client.post(
        "/parts/upload",
        files={"file": ("Part1.stp", b"", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "empty_upload"


def test_upload_rejects_oversized_file(client, monkeypatch):
    from backend.api import main

    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 10)
    response = client.post(
        "/parts/upload",
        files={"file": ("Part1.stp", b"x" * 11, "application/octet-stream")},
    )
    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == "upload_too_large"
    assert error["details"]["size_bytes"] == 11
    assert error["details"]["max_bytes"] == 10


def test_upload_accepts_uppercase_step_extension(client):
    response = client.post(
        "/parts/upload",
        files={"file": ("Part1.STEP", _step_bytes(), "application/octet-stream")},
    )
    assert response.status_code == 200
    assert response.json()["filename"].endswith("_Part1.STEP")


def test_upload_sanitizes_path_traversal_in_filename(client):
    response = client.post(
        "/parts/upload",
        files={"file": ("../../etc/evil.stp", _step_bytes(), "application/octet-stream")},
    )
    assert response.status_code == 200
    payload = response.json()
    # Only the basename survives -- no path separators, and the stored file
    # lives strictly inside UPLOADS_DIR.
    assert payload["original_filename"] == "evil.stp"
    assert "/" not in payload["filename"] and ".." not in payload["filename"]


# ---------------------------------------------------------------------------
# /parts merge behaviour (curated fixtures + uploads)
# ---------------------------------------------------------------------------

def test_parts_list_merges_fixtures_and_uploads(client):
    from backend.api import main

    (main.PARTS_DIR / "Fixture.stp").write_bytes(_step_bytes())
    upload = client.post(
        "/parts/upload",
        files={"file": ("Uploaded.stp", _step_bytes(), "application/octet-stream")},
    ).json()

    listed = client.get("/parts").json()["files"]
    assert "Fixture.stp" in listed
    assert upload["filename"] in listed
