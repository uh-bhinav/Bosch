"""
tests/test_mold_orchestration_manual.py
-----------------------------------------
Phase C16 -- manual/engineer-supplied pull direction orchestration
(backend.geometry.mold_orchestration.resolve_manual_direction_mold).

Proves the manual path converges into the EXACT SAME
_resolve_mold_for_direction core the automatic path
(resolve_winning_direction_mold, Phase C14) uses -- never a second,
parallel chain -- and never fabricates a DirectionOptimizationResult or
optimal_found for an engineer-chosen direction (Phase C15).

Layered per this project's testing convention: fast, pure/mock tests first
(no OCC, no real fixtures), then real-fixture integration tests on
Part1.stp/Part3.stp guarded by requires_occ/requires_part1/requires_part3.
"""

from __future__ import annotations

import math
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


def _fake_pl_result(direction, *, selected, outcome_override=None):
    from backend.geometry.parting_line_v2.engine import PartingLineV2Result
    from backend.geometry.parting_line_v2.contracts import PullDirectionInput

    fake = MagicMock(spec=PartingLineV2Result)
    fake.pull_direction = PullDirectionInput(direction, "manual")
    fake.selected = selected
    if outcome_override is not None:
        fake.outcome = outcome_override
    else:
        fake.outcome = "feasible" if selected is not None else "no_feasible_candidate"
    return fake


class _FeatureStub:
    def __init__(self, feature_id, face_ids, severity="critical", interference_volume_mm3=1.0):
        self.feature_id = feature_id
        self.face_ids = face_ids
        self.severity = severity
        self.interference_volume_mm3 = interference_volume_mm3


# ---------------------------------------------------------------------------
# Validation: invalid / non-unit direction.
# ---------------------------------------------------------------------------

def test_invalid_direction_zero_vector(monkeypatch):
    import backend.geometry.mold_orchestration as orch_mod

    def explode(*a, **k):
        raise AssertionError("must never reach undercut detection for an invalid direction")
    monkeypatch.setattr(orch_mod, "detect_undercuts", explode)

    result = orch.resolve_manual_direction_mold(MagicMock(), (0.0, 0.0, 0.0))
    assert result.status == "invalid_direction"
    assert result.pull_direction is None
    assert result.direction_result is None


def test_invalid_direction_non_finite(monkeypatch):
    import backend.geometry.mold_orchestration as orch_mod

    def explode(*a, **k):
        raise AssertionError("must never reach undercut detection for a non-finite direction")
    monkeypatch.setattr(orch_mod, "detect_undercuts", explode)

    result = orch.resolve_manual_direction_mold(MagicMock(), (float("nan"), 0.0, 1.0))
    assert result.status == "invalid_direction"

    result_inf = orch.resolve_manual_direction_mold(MagicMock(), (float("inf"), 0.0, 0.0))
    assert result_inf.status == "invalid_direction"


def test_non_unit_direction_gets_normalized(monkeypatch):
    """
    A non-unit manual direction (e.g. (2,0,0)) must be normalized to a
    unit vector BEFORE detect_undercuts/analyse_parting_line/
    split_core_cavity_solids ever see it -- proven by inspecting the exact
    direction detect_undercuts is called with.
    """
    import backend.geometry.mold_orchestration as orch_mod

    captured = {}

    def fake_detect_undercuts(part, direction, mutate=False, boolean_refine=False):
        captured["direction"] = direction
        return _fake_undercuts(direction)

    monkeypatch.setattr(orch_mod, "detect_undercuts", fake_detect_undercuts)
    monkeypatch.setattr(
        orch_mod, "analyse_parting_line",
        lambda part, pull, **k: _fake_pl_result(pull.direction, selected=None),
    )

    orch.resolve_manual_direction_mold(MagicMock(), (2.0, 0.0, 0.0))
    assert captured["direction"] == (1.0, 0.0, 0.0)


def test_manual_direction_uses_mutate_true_and_boolean_refine_true(monkeypatch):
    """
    Same final-direction convention optimize_mold_direction's own last
    step uses for its winning direction (CLAUDE.md's mutate-flag
    contract).
    """
    import backend.geometry.mold_orchestration as orch_mod

    captured = {}

    def fake_detect_undercuts(part, direction, mutate=False, boolean_refine=False):
        captured["mutate"] = mutate
        captured["boolean_refine"] = boolean_refine
        return _fake_undercuts(direction)

    monkeypatch.setattr(orch_mod, "detect_undercuts", fake_detect_undercuts)
    monkeypatch.setattr(
        orch_mod, "analyse_parting_line",
        lambda part, pull, **k: _fake_pl_result(pull.direction, selected=None),
    )

    orch.resolve_manual_direction_mold(MagicMock(), PULL_Z)
    assert captured["mutate"] is True
    assert captured["boolean_refine"] is True


def test_manual_never_calls_optimize_mold_direction():
    """
    AST-level structural proof: resolve_manual_direction_mold's CODE never
    calls optimize_mold_direction (prose in its own docstring explaining
    why is fine -- ast.walk only sees real syntax nodes, not the
    docstring's opaque string constant).
    """
    import ast
    import inspect
    import backend.geometry.mold_orchestration as orch_mod

    tree = ast.parse(inspect.getsource(orch_mod.resolve_manual_direction_mold))
    called_names = {
        n.func.id for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "optimize_mold_direction" not in called_names


# ---------------------------------------------------------------------------
# Required semantics table (mock-based, mirrors test_mold_orchestration.py's
# automatic-path coverage exactly).
# ---------------------------------------------------------------------------

def test_manual_valid_feasible_direction(monkeypatch):
    import backend.geometry.mold_orchestration as orch_mod
    from backend.geometry.core_cavity import CoreCavitySolidResult

    fake_candidate = MagicMock()
    fake_candidate.points = ()
    fake_candidate.feasibility = None

    monkeypatch.setattr(orch_mod, "detect_undercuts", lambda part, direction, **k: _fake_undercuts(direction))
    monkeypatch.setattr(
        orch_mod, "analyse_parting_line",
        lambda part, pull, **k: _fake_pl_result(pull.direction, selected=fake_candidate),
    )
    fake_split = CoreCavitySolidResult(
        solid_split_status="split_ok", cavity_solid=object(), core_solid=object(),
    )
    monkeypatch.setattr(orch_mod, "split_core_cavity_solids", lambda *a, **k: fake_split)

    result = orch.resolve_manual_direction_mold(MagicMock(), PULL_Z, generate_side_cores=False)
    assert result.status == "generated"
    assert result.direction_result is None
    assert result.pull_direction == PULL_Z


def test_manual_h0_h7_rejected(monkeypatch):
    import backend.geometry.mold_orchestration as orch_mod

    monkeypatch.setattr(orch_mod, "detect_undercuts", lambda part, direction, **k: _fake_undercuts(direction))
    monkeypatch.setattr(
        orch_mod, "analyse_parting_line",
        lambda part, pull, **k: _fake_pl_result(
            pull.direction, selected=None, outcome_override="no_feasible_candidate",
        ),
    )

    result = orch.resolve_manual_direction_mold(MagicMock(), PULL_Z)
    assert result.status == "blocked_by_parting_line"
    assert result.pl_result.outcome == "no_feasible_candidate"


def test_manual_referred_to_side_action(monkeypatch):
    """
    'Requires authorized secondary action' scenario: H0-H7 routes every
    candidate to H5 referral rather than rejecting outright.
    parting_line_v2_outcome must distinguish this from a plain
    no_feasible_candidate rejection -- the existing PartingLineV2Result.
    outcome vocabulary (C9/C11), not an invented status.
    """
    import backend.geometry.mold_orchestration as orch_mod

    monkeypatch.setattr(orch_mod, "detect_undercuts", lambda part, direction, **k: _fake_undercuts(direction))
    monkeypatch.setattr(
        orch_mod, "analyse_parting_line",
        lambda part, pull, **k: _fake_pl_result(
            pull.direction, selected=None, outcome_override="referred_to_side_action",
        ),
    )

    result = orch.resolve_manual_direction_mold(MagicMock(), PULL_Z)
    assert result.status == "blocked_by_parting_line"
    assert result.pl_result.outcome == "referred_to_side_action"
    assert result.direction_result is None


def test_manual_core_cavity_split_fails(monkeypatch):
    import backend.geometry.mold_orchestration as orch_mod
    from backend.geometry.core_cavity import CoreCavitySolidResult

    fake_candidate = MagicMock()
    fake_candidate.points = ()
    fake_candidate.feasibility = None
    monkeypatch.setattr(orch_mod, "detect_undercuts", lambda part, direction, **k: _fake_undercuts(direction))
    monkeypatch.setattr(
        orch_mod, "analyse_parting_line",
        lambda part, pull, **k: _fake_pl_result(pull.direction, selected=fake_candidate),
    )
    monkeypatch.setattr(
        orch_mod, "split_core_cavity_solids",
        lambda *a, **k: CoreCavitySolidResult(solid_split_status="failed"),
    )

    result = orch.resolve_manual_direction_mold(MagicMock(), PULL_Z)
    assert result.status == "blocked_by_core_cavity_split"


def test_manual_side_core_partial_failure(monkeypatch):
    """
    A per-feature side-core failure must never downgrade the overall
    status away from "generated" -- unchanged granular-failure semantics
    from C14.
    """
    import backend.geometry.mold_orchestration as orch_mod
    from backend.geometry.core_cavity import CoreCavitySolidResult
    from backend.geometry.side_core import SideCoreResult

    fake_candidate = MagicMock()
    fake_candidate.points = ()
    fake_candidate.feasibility = None
    features = [_FeatureStub(0, [1, 2]), _FeatureStub(1, [3, 4])]

    monkeypatch.setattr(
        orch_mod, "detect_undercuts",
        lambda part, direction, **k: _fake_undercuts(direction, features=features),
    )
    monkeypatch.setattr(
        orch_mod, "analyse_parting_line",
        lambda part, pull, **k: _fake_pl_result(pull.direction, selected=fake_candidate),
    )
    fake_split = CoreCavitySolidResult(
        solid_split_status="split_ok", cavity_solid=object(), core_solid=object(),
    )
    monkeypatch.setattr(orch_mod, "split_core_cavity_solids", lambda *a, **k: fake_split)

    def fake_generate_side_core(part, feature, split_result):
        if feature.feature_id == 0:
            return SideCoreResult(status="failed", feature_id=0, failure_reason="synthetic failure")
        return SideCoreResult(status="generated", feature_id=1, containing_half="cavity")

    monkeypatch.setattr(orch_mod, "generate_side_core", fake_generate_side_core)
    monkeypatch.setattr(orch_mod, "combine_side_cores_per_half", lambda *a, **k: {})

    result = orch.resolve_manual_direction_mold(
        MagicMock(), PULL_Z, severities=("critical",), primary_only=False,
    )
    assert result.status == "generated"
    statuses = {r.feature_id: r.status for r in result.multi_side_core_result.results}
    assert statuses == {0: "failed", 1: "generated"}


def test_direction_result_is_none_for_manual(monkeypatch):
    import backend.geometry.mold_orchestration as orch_mod

    monkeypatch.setattr(orch_mod, "detect_undercuts", lambda part, direction, **k: _fake_undercuts(direction))
    monkeypatch.setattr(
        orch_mod, "analyse_parting_line",
        lambda part, pull, **k: _fake_pl_result(pull.direction, selected=None),
    )

    result = orch.resolve_manual_direction_mold(MagicMock(), PULL_Z)
    assert result.direction_result is None
    d = result.to_dict()
    assert d["optimal_found"] is None
    assert d["pull_direction"] == [0.0, 0.0, 1.0]


# ---------------------------------------------------------------------------
# Real-fixture integration tests.
# ---------------------------------------------------------------------------

@requires_occ
@requires_part1
def test_part1_real_manual_pull_z_regression():
    """
    Regression guard against test_side_core.py's own existing baseline:
    Part1 @ manual (0,0,1) must still produce a real, volume-conserving
    side core through the NEW resolve_manual_direction_mold path,
    matching the same feature (highest-confidence critical, Bosch
    criterion #5) the pre-existing generate_primary_side_core baseline
    demonstrates.
    """
    from backend.geometry.step_loader import load_step
    from backend.config import settings

    part = load_step(str(PART1_PATH))
    result = orch.resolve_manual_direction_mold(part, PULL_Z, primary_only=True)

    assert result.status == "generated"
    assert result.direction_result is None
    assert result.pull_direction == (0.0, 0.0, 1.0)
    assert result.split_result.solid_split_status == "split_ok"
    assert result.multi_side_core_result is not None
    generated = result.multi_side_core_result.generated_results
    assert generated, "Expected at least one generated side core at Part1 @ +Z (known critical feature)."
    tolerance = settings.dfm.side_core.volume_conservation_tolerance
    for r in generated:
        assert r.side_core_volume_mm3 > 0.0
        assert r.conservation_error <= tolerance


@requires_occ
@requires_part1
def test_real_non_unit_direction_succeeds_and_matches_normalized():
    """
    A real non-unit manual direction ((0,0,2), magnitude 2) must succeed
    (normalized internally) and produce the SAME result as the already-
    normalized (0,0,1) -- proving the normalize3 step is load-bearing, not
    cosmetic.
    """
    from backend.geometry.step_loader import load_step

    part_a = load_step(str(PART1_PATH))
    part_b = load_step(str(PART1_PATH))

    result_unit = orch.resolve_manual_direction_mold(part_a, (0.0, 0.0, 1.0), primary_only=True)
    result_scaled = orch.resolve_manual_direction_mold(part_b, (0.0, 0.0, 2.0), primary_only=True)

    assert result_unit.status == result_scaled.status == "generated"
    assert result_scaled.pull_direction == (0.0, 0.0, 1.0)
    vol_unit = round(result_unit.multi_side_core_result.generated_results[0].side_core_volume_mm3, 3)
    vol_scaled = round(result_scaled.multi_side_core_result.generated_results[0].side_core_volume_mm3, 3)
    assert vol_unit == vol_scaled


@requires_occ
@requires_part3
def test_part3_candidate_110_manual_plus_z_excludes_delegated_features():
    """
    Real Part3 manual +Z with the real candidate-110 authorization: any
    undercut feature fully covered by the authorized STACK1/STACK2
    delegation must never reach side-core generation, through the NEW
    manual path. Cross-checked two independent ways: (a) against
    filter_features_excluding_delegated applied directly to the real
    detect_undercuts() feature list (the same check C14's
    test_part3_delegated_faces_excluded_from_real_undercut_features makes
    for the automatic path), and (b) against the actually-attempted
    feature ids inside the returned multi_side_core_result, if any side
    cores were attempted at all.
    """
    from backend.geometry.step_loader import load_step
    from backend.geometry.undercut_detector import detect_undercuts

    part = load_step(str(PART3_PATH))
    refs, delegations = _candidate_110_authorization()
    result = orch.resolve_manual_direction_mold(
        part, PULL_Z, core_pin_face_refs=refs, delegations=delegations,
        severities=("critical", "moderate", "minor"), primary_only=False,
    )

    assert result.pull_direction == PULL_Z
    assert result.direction_result is None
    # Real Part3+authorization may legitimately end up blocked_by_parting_line
    # (H5 routes to referral with real undercut evidence -- Phase C12's own
    # finding) rather than reaching the split; delegated_face_ids is only
    # populated once the chain gets past the split, so only assert it when
    # that actually happened.
    if result.split_result is not None:
        assert result.delegated_face_ids == (STACK1 | STACK2)

    # (a) Independent recomputation from a fresh real detect_undercuts()
    # call at the same direction -- must agree with what the orchestrator
    # itself excluded.
    fresh_undercuts = detect_undercuts(part, PULL_Z, mutate=False, boolean_refine=True)
    delegated_face_ids = frozenset(fid for d in delegations for fid in d.face_ids)
    eligible = orch.filter_features_excluding_delegated(fresh_undercuts.features, delegated_face_ids)
    eligible_ids = {f.feature_id for f in eligible}
    fully_delegated_ids = {
        f.feature_id for f in fresh_undercuts.features
        if frozenset(f.face_ids) and frozenset(f.face_ids) <= delegated_face_ids
    }
    assert fully_delegated_ids.isdisjoint(eligible_ids)

    # (b) No fully-delegated feature id was ever handed to generate_side_core.
    if result.multi_side_core_result is not None:
        attempted_ids = {r.feature_id for r in result.multi_side_core_result.results}
        assert attempted_ids.isdisjoint(fully_delegated_ids), (
            f"Delegated feature ids {fully_delegated_ids & attempted_ids} were "
            "sent to generate_side_core despite being fully covered by the "
            "candidate-110 authorization."
        )
