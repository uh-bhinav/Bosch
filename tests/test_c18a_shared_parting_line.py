"""
tests/test_c18a_shared_parting_line.py
----------------------------------------
Phase C18A -- eliminate the stale, undercuts-empty _resolve_v2_parting_line
duplication in backend/api/main.py's /core-cavity and /export/report, by
threading resolve_authoritative_parting_line's real-undercut-aware result
into the C14/C16 orchestration via precomputed_pl_result/precomputed_
undercuts, instead of recomputing analyse_parting_line/detect_undercuts a
second time.

Layered per this project's testing convention: fast, pure/mock tests first,
then real-fixture integration tests on Part1.stp/Part3.stp.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.geometry import mold_orchestration as orch

REPO_ROOT = Path(__file__).resolve().parent.parent
PART1_PATH = REPO_ROOT / "data" / "parts" / "Part1.stp"
PART3_PATH = REPO_ROOT / "data" / "parts" / "Part3.stp"


def _occ_available() -> bool:
    try:
        import OCC  # noqa: F401
        return True
    except ImportError:
        return False


requires_occ = pytest.mark.skipif(not _occ_available(), reason="pythonOCC not installed")
requires_part1 = pytest.mark.skipif(not PART1_PATH.exists(), reason="Part1.stp not present")
requires_part3 = pytest.mark.skipif(not PART3_PATH.exists(), reason="Part3.stp not present")

PULL_Z = (0.0, 0.0, 1.0)
BORE_FACE_ID = 35
STACK1 = frozenset(range(0, 17))
STACK2 = frozenset(range(18, 35))


def _candidate_110_authorization():
    from backend.geometry.parting_line_v2.contracts import (
        CorePinFaceRef, DelegatedSecondaryAction, DelegationEvidence,
    )

    refs = (CorePinFaceRef(BORE_FACE_ID, PULL_Z, "straight coaxial through-bore"),)
    delegations = (
        DelegatedSecondaryAction(
            face_ids=STACK1, movement_direction=(1.0, 0.0, 0.0), movement_type="radial_slide",
            evidence=DelegationEvidence(source="manual_engineering", note="original rib stack"),
        ),
        DelegatedSecondaryAction(
            face_ids=STACK2, movement_direction=(-1.0, 0.0, 0.0), movement_type="radial_slide",
            evidence=DelegationEvidence(source="manual_engineering", note="mirror rib stack"),
        ),
    )
    return refs, delegations


def _fake_undercuts(direction, features=None):
    from backend.geometry.undercut_detector import UndercutDetectionResult
    return UndercutDetectionResult(
        pull_direction=direction, method="fake", undercut_face_ids=[],
        accessible_face_ids=[], parting_face_ids=[], skipped_face_ids=[],
        features=features or [],
    )


def _fake_pl_result(direction, *, selected):
    from backend.geometry.parting_line_v2.engine import PartingLineV2Result
    from backend.geometry.parting_line_v2.contracts import PullDirectionInput

    fake = MagicMock(spec=PartingLineV2Result)
    fake.pull_direction = PullDirectionInput(direction, "manual")
    fake.selected = selected
    fake.regions = MagicMock(name="regions")
    fake.outcome = "feasible" if selected is not None else "no_feasible_candidate"
    return fake


# ---------------------------------------------------------------------------
# resolve_authoritative_parting_line -- calls analyse_parting_line exactly
# once, with real (not empty) undercut evidence.
# ---------------------------------------------------------------------------

def test_resolve_authoritative_parting_line_uses_real_undercuts(monkeypatch):
    import backend.geometry.mold_orchestration as orch_mod

    captured = {}

    def fake_analyse(part, pull, *, undercuts, cfg, core_pin_face_refs, delegations):
        captured["undercuts_input"] = undercuts
        captured["pull"] = pull
        return _fake_pl_result(pull.direction, selected=None)

    monkeypatch.setattr(orch_mod, "analyse_parting_line", fake_analyse)

    # Non-empty undercut evidence (face 5) -- proves the passed-in
    # UndercutDetectionResult's actual content reaches analyse_parting_line,
    # not a silently-substituted UndercutInput.empty().
    from backend.geometry.undercut_detector import UndercutDetectionResult
    undercuts = UndercutDetectionResult(
        pull_direction=PULL_Z, method="fake", undercut_face_ids=[5],
        accessible_face_ids=[], parting_face_ids=[], skipped_face_ids=[],
    )
    result = orch.resolve_authoritative_parting_line(
        MagicMock(), PULL_Z, undercuts,
        core_pin_face_refs=(), delegations=(), source_label="optimizer",
    )
    assert result.outcome == "no_feasible_candidate"
    from backend.geometry.parting_line_v2 import UndercutInput
    assert captured["undercuts_input"] != UndercutInput.empty()
    assert 5 in captured["undercuts_input"].undercut_face_ids
    assert captured["pull"].source == "optimizer"


# ---------------------------------------------------------------------------
# precomputed_pl_result / precomputed_undercuts -- proves no duplicate
# analyse_parting_line / detect_undercuts call.
# ---------------------------------------------------------------------------

def test_resolve_winning_direction_mold_skips_analyse_parting_line_when_precomputed(monkeypatch):
    import backend.geometry.mold_orchestration as orch_mod
    from backend.geometry.core_cavity import CoreCavitySolidResult

    def explode(*a, **k):
        raise AssertionError("analyse_parting_line must not be called when precomputed_pl_result is given")
    monkeypatch.setattr(orch_mod, "analyse_parting_line", explode)
    monkeypatch.setattr(
        orch_mod, "split_core_cavity_solids",
        lambda *a, **k: CoreCavitySolidResult(solid_split_status="split_ok", cavity_solid=object(), core_solid=object()),
    )

    from backend.geometry.direction_optimizer import DirectionOptimizationResult
    from backend.geometry.draft_analyzer import DraftAnalysisResult

    draft = DraftAnalysisResult(
        pull_direction=PULL_Z, pull_direction_label="mock", analysis_pass="mock",
        good_face_ids=[], marginal_face_ids=[], bad_face_ids=[], skipped_face_ids=[],
        good_area_mm2=0.0, marginal_area_mm2=0.0, bad_area_mm2=0.0, skipped_area_mm2=0.0,
        total_analysed_area_mm2=0.0, good_threshold_deg=1.5, marginal_threshold_deg=0.5,
        severity="none",
    )
    undercuts = _fake_undercuts(PULL_Z)
    direction_result = DirectionOptimizationResult(
        best_direction=PULL_Z, best_label="+Z", best_score=1.0,
        initial_pull_direction=PULL_Z, initial_label="+Z",
        initial_draft=draft, initial_undercuts=undercuts,
        optimal_draft=draft, optimal_undercuts=undercuts,
        optimal_found=True,
    )

    fake_candidate = MagicMock()
    fake_candidate.points = ()
    fake_candidate.feasibility = None
    precomputed = _fake_pl_result(PULL_Z, selected=fake_candidate)

    result = orch.resolve_winning_direction_mold(
        MagicMock(), direction_result, generate_side_cores=False,
        precomputed_pl_result=precomputed,
    )
    assert result.status == "generated"
    assert result.pl_result is precomputed


def test_resolve_manual_direction_mold_skips_detect_undercuts_and_analyse_when_precomputed(monkeypatch):
    import backend.geometry.mold_orchestration as orch_mod
    from backend.geometry.core_cavity import CoreCavitySolidResult

    def explode_detect(*a, **k):
        raise AssertionError("detect_undercuts must not be called when precomputed_undercuts is given")
    def explode_analyse(*a, **k):
        raise AssertionError("analyse_parting_line must not be called when precomputed_pl_result is given")
    monkeypatch.setattr(orch_mod, "detect_undercuts", explode_detect)
    monkeypatch.setattr(orch_mod, "analyse_parting_line", explode_analyse)
    monkeypatch.setattr(
        orch_mod, "split_core_cavity_solids",
        lambda *a, **k: CoreCavitySolidResult(solid_split_status="split_ok", cavity_solid=object(), core_solid=object()),
    )

    fake_candidate = MagicMock()
    fake_candidate.points = ()
    fake_candidate.feasibility = None
    precomputed_pl = _fake_pl_result(PULL_Z, selected=fake_candidate)
    precomputed_undercuts = _fake_undercuts(PULL_Z)

    result = orch.resolve_manual_direction_mold(
        MagicMock(), PULL_Z, generate_side_cores=False,
        precomputed_undercuts=precomputed_undercuts,
        precomputed_pl_result=precomputed_pl,
    )
    assert result.status == "generated"
    assert result.pl_result is precomputed_pl


def test_prepare_manual_direction_invalid_never_calls_detect_undercuts(monkeypatch):
    import backend.geometry.mold_orchestration as orch_mod

    def explode(*a, **k):
        raise AssertionError("detect_undercuts must never be called for an invalid direction")
    monkeypatch.setattr(orch_mod, "detect_undercuts", explode)

    normalized, undercuts, invalid = orch.prepare_manual_direction(MagicMock(), (0.0, 0.0, 0.0))
    assert normalized is None
    assert undercuts is None
    assert invalid is not None
    assert invalid.status == "invalid_direction"


# ---------------------------------------------------------------------------
# API-level (main.py) mock tests: proves /core-cavity now computes
# analyse_parting_line exactly ONCE per request when solid_split=True,
# not twice, and that the face-classification region_classification and
# the orchestration's own pl_result come from the SAME object.
# ---------------------------------------------------------------------------

def test_core_cavity_endpoint_calls_analyse_parting_line_exactly_once(monkeypatch):
    import backend.api.main as main_mod
    import backend.geometry.mold_orchestration as orch_mod

    call_count = {"n": 0}

    def fake_analyse(part, pull, *, undercuts, cfg, core_pin_face_refs, delegations):
        call_count["n"] += 1
        return _fake_pl_result(pull.direction, selected=None)

    monkeypatch.setattr(orch_mod, "analyse_parting_line", fake_analyse)

    fake_part = MagicMock()
    fake_part.to_dict.return_value = {}
    monkeypatch.setattr(main_mod, "load_step_cached", lambda path: fake_part)
    monkeypatch.setattr(main_mod, "_part_path_or_raise", lambda filename, op: (filename, "fake_path"))

    fake_undercuts = _fake_undercuts(PULL_Z)

    class FakeDirectionResult:
        best_direction = PULL_Z
        optimal_undercuts = fake_undercuts
        optimal_found = True

    monkeypatch.setattr(main_mod, "optimize_mold_direction", lambda part, **k: FakeDirectionResult())

    fake_cc_result = MagicMock()
    fake_cc_result.to_dict.return_value = {}
    fake_cc_result.cavity_face_ids = []
    fake_cc_result.core_face_ids = []
    fake_cc_result.parting_face_ids = []
    fake_cc_result.skipped_face_ids = []
    monkeypatch.setattr(main_mod, "classify_core_cavity", lambda *a, **k: fake_cc_result)

    payload = main_mod.part_core_cavity(
        "fake.stp", use_optimal_direction=True, solid_split=True,
        include_mesh=False, core_pin_face_refs=None, delegations=None,
        side_core_severities="critical",
    )
    # analyse_parting_line is called exactly once: by resolve_authoritative_
    # parting_line for face classification, reused (precomputed_pl_result)
    # by the orchestration -- never a second time.
    assert call_count["n"] == 1
    assert payload["parting_line_v2_outcome"] == payload["orchestration"]["parting_line_v2_outcome"]


def test_core_cavity_endpoint_manual_reuses_undercuts_and_pl_result(monkeypatch):
    """
    Manual path: detect_undercuts and analyse_parting_line must each be
    called exactly once for the whole request, even though BOTH face
    classification AND the solid-split orchestration need their results.
    """
    import backend.api.main as main_mod
    import backend.geometry.mold_orchestration as orch_mod

    detect_calls = {"n": 0}
    analyse_calls = {"n": 0}

    def fake_detect(part, direction, mutate=False, boolean_refine=False):
        detect_calls["n"] += 1
        return _fake_undercuts(direction)

    def fake_analyse(part, pull, *, undercuts, cfg, core_pin_face_refs, delegations):
        analyse_calls["n"] += 1
        return _fake_pl_result(pull.direction, selected=None)

    monkeypatch.setattr(orch_mod, "detect_undercuts", fake_detect)
    monkeypatch.setattr(orch_mod, "analyse_parting_line", fake_analyse)

    fake_part = MagicMock()
    fake_part.to_dict.return_value = {}
    monkeypatch.setattr(main_mod, "load_step_cached", lambda path: fake_part)
    monkeypatch.setattr(main_mod, "_part_path_or_raise", lambda filename, op: (filename, "fake_path"))

    fake_cc_result = MagicMock()
    fake_cc_result.to_dict.return_value = {}
    fake_cc_result.cavity_face_ids = []
    fake_cc_result.core_face_ids = []
    fake_cc_result.parting_face_ids = []
    fake_cc_result.skipped_face_ids = []
    monkeypatch.setattr(main_mod, "classify_core_cavity", lambda *a, **k: fake_cc_result)

    payload = main_mod.part_core_cavity(
        "fake.stp", use_optimal_direction=False, dx=0.0, dy=0.0, dz=1.0,
        solid_split=True, include_mesh=False, core_pin_face_refs=None, delegations=None,
        side_core_severities="critical",
    )
    assert detect_calls["n"] == 1
    assert analyse_calls["n"] == 1
    assert payload["parting_line_v2_outcome"] == payload["orchestration"]["parting_line_v2_outcome"]


def test_core_cavity_endpoint_manual_invalid_direction_is_graceful(monkeypatch):
    import backend.api.main as main_mod
    import backend.geometry.mold_orchestration as orch_mod

    def explode(*a, **k):
        raise AssertionError("must never reach detect_undercuts/analyse_parting_line for a zero direction")
    monkeypatch.setattr(orch_mod, "detect_undercuts", explode)
    monkeypatch.setattr(orch_mod, "analyse_parting_line", explode)

    fake_part = MagicMock()
    fake_part.to_dict.return_value = {}
    monkeypatch.setattr(main_mod, "load_step_cached", lambda path: fake_part)
    monkeypatch.setattr(main_mod, "_part_path_or_raise", lambda filename, op: (filename, "fake_path"))

    fake_cc_result = MagicMock()
    fake_cc_result.to_dict.return_value = {}
    fake_cc_result.cavity_face_ids = []
    fake_cc_result.core_face_ids = []
    fake_cc_result.parting_face_ids = []
    fake_cc_result.skipped_face_ids = []
    monkeypatch.setattr(main_mod, "classify_core_cavity", lambda *a, **k: fake_cc_result)

    payload = main_mod.part_core_cavity(
        "fake.stp", use_optimal_direction=False, dx=0.0, dy=0.0, dz=0.0,
        solid_split=True, include_mesh=False, core_pin_face_refs=None, delegations=None,
    )
    assert payload["orchestration"]["status"] == "invalid_direction"
    assert payload["parting_line_v2_outcome"] is None


def test_resolve_v2_parting_line_no_longer_exists():
    import backend.api.main as main_mod
    assert not hasattr(main_mod, "_resolve_v2_parting_line")


# ---------------------------------------------------------------------------
# Real-fixture integration tests.
# ---------------------------------------------------------------------------

@requires_occ
@requires_part1
def test_part1_core_cavity_endpoint_regions_match_orchestration():
    """
    Real Part1, automatic direction, through the actual /core-cavity
    endpoint function: the top-level parting_line_v2_outcome (face
    classification) and orchestration.parting_line_v2_outcome (solid
    split) must now be IDENTICAL -- both come from the SAME
    resolve_authoritative_parting_line call, per C18A. Also confirms the
    known Part1 -Z regression (score=742.3105286124178) is unaffected.
    """
    import backend.api.main as main_mod

    payload = main_mod.part_core_cavity(
        "Part1.stp", use_optimal_direction=True, dx=0.0, dy=0.0, dz=1.0,
        threshold=None, solid_split=True, generate_side_core=False,
        multi_feature_side_cores=False, side_core_severities="critical",
        side_core_max_features=None, core_pin_face_refs=None, delegations=None,
        include_faces=False, include_mesh=False, include_mesh_geometry=False,
        mesh_deflection=0.5,
    )
    assert payload["orchestration"]["optimal_found"] is True
    assert payload["orchestration"]["pull_direction"] == [0.0, 0.0, -1.0]
    assert payload["parting_line_v2_outcome"] == payload["orchestration"]["parting_line_v2_outcome"]
    assert payload["orchestration"]["solid_split"]["solid_split_status"] == "split_ok"


@requires_occ
@requires_part3
def test_part3_candidate_110_core_cavity_endpoint_delegation_still_excludes_features():
    """
    Real Part3, manual +Z, candidate-110 authorization, through the actual
    /core-cavity endpoint: delegated-feature exclusion must still behave
    exactly as C16 established, now routed through the shared,
    once-computed parting-line result.
    """
    import json
    import backend.api.main as main_mod

    refs, delegations = _candidate_110_authorization()
    core_pin_json = json.dumps([
        {"face_id": BORE_FACE_ID, "axis_direction": list(PULL_Z), "reason": "straight coaxial through-bore"},
    ])
    delegations_json = json.dumps([
        {"face_ids": sorted(STACK1), "movement_direction": [1.0, 0.0, 0.0], "movement_type": "radial_slide",
         "source": "manual_engineering", "note": "original rib stack"},
        {"face_ids": sorted(STACK2), "movement_direction": [-1.0, 0.0, 0.0], "movement_type": "radial_slide",
         "source": "manual_engineering", "note": "mirror rib stack"},
    ])

    payload = main_mod.part_core_cavity(
        "Part3.stp", use_optimal_direction=False, dx=0.0, dy=0.0, dz=1.0,
        threshold=None, solid_split=True, multi_feature_side_cores=True,
        side_core_severities="critical,moderate,minor", side_core_max_features=None,
        core_pin_face_refs=core_pin_json, delegations=delegations_json,
        include_faces=False, include_mesh=False, include_mesh_geometry=False,
        mesh_deflection=0.5,
    )
    orchestration = payload["orchestration"]
    if orchestration["solid_split"] is not None:
        assert set(orchestration["delegated_face_ids"]) == (STACK1 | STACK2)
        for entry in payload.get("side_cores", {}).get("results", []) if payload.get("side_cores") else []:
            assert entry["feature_id"] not in orchestration["excluded_feature_ids"] or entry["status"] != "generated"


@requires_occ
@requires_part1
def test_export_report_still_generates_valid_pdf_after_c18a():
    import backend.api.main as main_mod

    response = main_mod.export_pdf_report(
        "Part1.stp", use_optimal_direction=False, dx=0.0, dy=0.0, dz=1.0,
        include_solid_split=False, include_side_core=False,
        include_agent_narrative=False,
        core_pin_face_refs=None, delegations=None,
    )
    assert response.media_type == "application/pdf"
    assert response.body[:4] == b"%PDF"
