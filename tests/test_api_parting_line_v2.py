"""
tests/test_api_parting_line_v2.py
----------------------------------
API-layer tests for the /parts/{filename}/parting-line-v2 endpoint's
optional core_pin_face_refs / delegations query parameters (Phase 1 of the
frontend-integration plan).

These go through fastapi.testclient.TestClient -- real HTTP-shaped
request/response, real JSON encoding/decoding -- not a direct Python call
into analyse_parting_line. That is the whole point: the earlier Part3 +Z
candidate-110 result was only ever reproduced via a direct Python call
(tests/test_parting_line_v2_delegation.py); this file proves the same
result is reachable through the actual API contract a frontend would use.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PART3_PATH = REPO_ROOT / "data" / "parts" / "Part3.stp"


def _occ_available() -> bool:
    try:
        import OCC  # noqa: F401
        return True
    except ImportError:
        return False


requires_occ = pytest.mark.skipif(not _occ_available(), reason="pythonOCC not installed")
requires_part3 = pytest.mark.skipif(not PART3_PATH.exists(), reason="Part3.stp not present")

STACK1 = list(range(0, 17))
STACK2 = list(range(18, 35))
BORE_FACE_ID = 35


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Additive-only: omitting the new params preserves today's exact behaviour
# ---------------------------------------------------------------------------

@requires_occ
@requires_part3
def test_omitted_params_preserve_baseline_behaviour(client):
    """No core_pin_face_refs/delegations -> same outcome as before this
    change existed: +Z has no feasible candidate (candidate 110 fails H4 at
    7.56% without delegation)."""
    response = client.get(
        "/parts/Part3.stp/parting-line-v2",
        params={"dx": 0, "dy": 0, "dz": 1, "include_mesh": False},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["outcome"] == "no_feasible_candidate"
    assert payload["selected"] is None


# ---------------------------------------------------------------------------
# 2. The decisive test: the API itself reproduces candidate 110's pass
# ---------------------------------------------------------------------------

@requires_occ
@requires_part3
def test_api_reproduces_candidate_110_with_authorized_inputs(client):
    core_pin_face_refs = json.dumps([
        {"face_id": BORE_FACE_ID, "axis_direction": [0.0, 0.0, 1.0],
         "reason": "straight coaxial through-bore"},
    ])
    delegations = json.dumps([
        {"face_ids": STACK1, "movement_direction": [1.0, 0.0, 0.0],
         "movement_type": "radial_slide", "source": "manual_engineering",
         "note": "original rib stack, radial outward +X"},
        {"face_ids": STACK2, "movement_direction": [-1.0, 0.0, 0.0],
         "movement_type": "radial_slide", "source": "manual_engineering",
         "note": "mirror rib stack, radial outward -X"},
    ])

    response = client.get(
        "/parts/Part3.stp/parting-line-v2",
        params={
            "dx": 0, "dy": 0, "dz": 1, "include_mesh": False,
            "core_pin_face_refs": core_pin_face_refs,
            "delegations": delegations,
        },
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["outcome"] == "feasible"
    selected = payload["selected"]
    assert selected is not None
    assert selected["candidate_id"] == 110

    feasibility = selected["feasibility"]
    assert feasibility["passed"] is True
    assert feasibility["failed_gate"] is None
    assert feasibility["measurements"]["h4_orientation_violation_fraction"] == pytest.approx(
        0.004994890916885516, rel=1e-6
    )
    assert feasibility["measurements"]["h4_delegated_face_count"] == 34.0

    validated = feasibility["validated_delegations"]
    assert len(validated) == 2
    for record in validated:
        assert record["evidence"]["geometric_verification"] == "unverified"
    all_delegated_faces = {fid for record in validated for fid in record["face_ids"]}
    assert all_delegated_faces == set(STACK1) | set(STACK2)

    core_pin_interfaces = selected["core_pin_interfaces"]
    assert len(core_pin_interfaces) == 1
    assert core_pin_interfaces[0]["face_id"] == BORE_FACE_ID
    assert core_pin_interfaces[0]["split_param"] == pytest.approx(4.0, abs=0.01)

    # Core-pin metadata must never appear as a curve in segments/loops --
    # architectural invariant carried over from D-043, re-checked at the API
    # boundary.
    assert selected["discovered_by"] == "cycle_basis"
    assert selected["segment_count"] == 2

    assert payload["regions"] is not None
    assert payload["regions"]["core_face_count"] == 5
    assert payload["regions"]["cavity_face_count"] == 410


# ---------------------------------------------------------------------------
# 3. geometric_verification is never accepted from the request
# ---------------------------------------------------------------------------

@requires_occ
@requires_part3
def test_geometric_verification_field_cannot_be_overridden(client):
    """Even if a caller tries to smuggle a different geometric_verification
    value in, the parser only reads source/note -- the field is structurally
    unreachable, not just conventionally defaulted."""
    delegations = json.dumps([
        {"face_ids": STACK1, "movement_direction": [1.0, 0.0, 0.0],
         "movement_type": "radial_slide", "source": "manual_engineering",
         "note": "test", "geometric_verification": "verified"},
    ])
    response = client.get(
        "/parts/Part3.stp/parting-line-v2",
        params={
            "dx": 0, "dy": 0, "dz": 1, "include_mesh": False,
            "delegations": delegations,
        },
    )
    assert response.status_code == 200
    # STACK1 alone doesn't pass H4 (needs both stacks) -- irrelevant here,
    # we only care that no candidate anywhere reports a non-"unverified"
    # value even though the request tried to set one.
    payload = response.json()
    for candidate in payload["scorecard"]:
        feasibility = candidate.get("feasibility") or {}
        for record in feasibility.get("validated_delegations", []):
            assert record["evidence"]["geometric_verification"] == "unverified"


# ---------------------------------------------------------------------------
# 4. Malformed input produces the existing structured error, not a 500
# ---------------------------------------------------------------------------

@requires_occ
@requires_part3
def test_malformed_core_pin_face_refs_returns_structured_400(client):
    response = client.get(
        "/parts/Part3.stp/parting-line-v2",
        params={"dx": 0, "dy": 0, "dz": 1, "include_mesh": False,
                "core_pin_face_refs": "not json"},
    )
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_input"
    assert "operation" in error and "recovery_hint" in error


@requires_occ
@requires_part3
def test_malformed_delegations_missing_field_returns_structured_400(client):
    response = client.get(
        "/parts/Part3.stp/parting-line-v2",
        params={"dx": 0, "dy": 0, "dz": 1, "include_mesh": False,
                "delegations": json.dumps([{"face_ids": [1, 2]}])},
    )
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_input"


@requires_occ
@requires_part3
def test_empty_face_ids_rejected(client):
    response = client.get(
        "/parts/Part3.stp/parting-line-v2",
        params={"dx": 0, "dy": 0, "dz": 1, "include_mesh": False,
                "delegations": json.dumps([{
                    "face_ids": [], "movement_direction": [1.0, 0.0, 0.0],
                    "movement_type": "radial_slide", "source": "manual_engineering",
                    "note": "test",
                }])},
    )
    assert response.status_code == 400
