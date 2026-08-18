"""
tests/test_api_export_download.py
-----------------------------------
F6: tests for `GET /export/download/{filename}` -- the minimal additive
endpoint closing the gap that `POST /parts/{filename}/export/mold-halves`
only ever returned a server-side filesystem path, with no way for a
browser client to retrieve the actual file bytes. No OCC dependency --
this endpoint only serves whatever bytes are already on disk.
"""

from __future__ import annotations

import dataclasses

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.api import main

    patched_core_cavity = dataclasses.replace(main.settings.dfm.core_cavity, export_dir=str(tmp_path))
    patched_dfm = dataclasses.replace(main.settings.dfm, core_cavity=patched_core_cavity)
    patched_settings = dataclasses.replace(main.settings, dfm=patched_dfm)
    # settings dataclasses are frozen -- replace the module's own `settings`
    # name (main.py reads `settings.dfm.core_cavity.export_dir` directly),
    # not an attribute on the frozen object itself.
    monkeypatch.setattr(main, "settings", patched_settings)
    return TestClient(main.app), tmp_path


def test_download_serves_an_existing_exported_file(client):
    test_client, export_dir = client
    (export_dir / "Part1_mold_halves.stp").write_bytes(b"ISO-10303-21;\nfake step content\n")

    response = test_client.get("/export/download/Part1_mold_halves.stp")

    assert response.status_code == 200
    assert response.content == b"ISO-10303-21;\nfake step content\n"
    assert "attachment" in response.headers.get("content-disposition", "")
    assert "Part1_mold_halves.stp" in response.headers.get("content-disposition", "")


def test_download_reports_structured_404_for_a_missing_file(client):
    test_client, _ = client

    response = test_client.get("/export/download/does_not_exist.stp")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "export_file_not_found"
    assert "recovery_hint" in body["error"]


def test_download_rejects_path_traversal(client):
    test_client, _ = client

    response = test_client.get("/export/download/..%2F..%2Fetc%2Fpasswd")

    assert response.status_code in (400, 404)


def test_download_never_escapes_the_export_directory(client, tmp_path):
    test_client, export_dir = client
    # A file that genuinely exists, but OUTSIDE the configured export dir --
    # must not be reachable via a crafted relative filename.
    outside = tmp_path.parent / "secret.stp"
    outside.write_bytes(b"should not be servable")

    response = test_client.get(f"/export/download/{outside.name}")

    assert response.status_code == 404
