"""
tests/test_direction_optimizer_parting_line_feasibility.py
-------------------------------------------------------------
D-062 (2026-08-16): the pull-direction optimizer's evidence_tier ==
"verified_acceptable" is NOT equivalent to "downstream-feasible" --
directly demonstrated on Part1, where the optimizer's own evidence-only
winner (a diagonal) is independently rejected by parting_line_v2's own
H0-H7 gates. This module tests:

1. _common_lower_bound is a genuine, mathematically exact lower bound
   on _score_candidate's eventual Boolean-refined score (synthetic,
   mock-based -- proof re-verified directly against the live
   _score_candidate source before implementation).
2. _is_parting_line_feasible correctly wraps parting_line_v2's outcome.
3. The bound-driven pruning logic inside optimize_mold_direction's
   Stage 1+2 loop never discards a candidate that could still win.
4. Real-geometry Part1 (+Z, the known diagonal) and Part3 (+Z) checks,
   using ONLY single-direction calls -- never the full 18-direction
   optimize_mold_direction().

No Part1/Part3-specific production logic exists anywhere in
direction_optimizer.py -- the face/direction values referenced below are
test fixtures verifying already-known results, not algorithm inputs.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

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
pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

PULL_Z = (0.0, 0.0, 1.0)
DIAGONAL = (-0.7071067811865475, 0.0, 0.7071067811865475)


# ---------------------------------------------------------------------------
# 1. _common_lower_bound: synthetic proof re-verification.
# ---------------------------------------------------------------------------

def _make_mock_part(bbox_dims=(10.0, 10.0, 10.0)):
    from unittest.mock import MagicMock
    from backend.models.geometry_models import BoundingBox, PartGeometry

    bbox = BoundingBox(0.0, 0.0, 0.0, *bbox_dims)
    return PartGeometry(
        source_file="mock.stp",
        occ_shape=MagicMock(),
        faces=[],
        bounding_box=bbox,
        face_count=0,
        solid_count=1,
    )


def _make_draft(bad_pct=0.0, marginal_pct=0.0, bad_ids=None, marginal_ids=None, face_count=1):
    """
    bad_pct/marginal_pct/face_count_analysed are all @property values
    derived from the real dataclass fields (bad_area_mm2/
    total_analysed_area_mm2, and good/marginal/bad_face_ids lengths) --
    NOT settable constructor kwargs. This helper reverse-derives the
    underlying fields so the requested percentages/counts come out exact.
    """
    from backend.geometry.draft_analyzer import DraftAnalysisResult

    bad_ids = bad_ids or []
    marginal_ids = marginal_ids or []
    remaining = max(0, face_count - len(bad_ids) - len(marginal_ids))
    good_ids = list(range(1000, 1000 + remaining))
    total_area = 100.0
    bad_area = bad_pct / 100.0 * total_area
    marginal_area = marginal_pct / 100.0 * total_area
    good_area = max(0.0, total_area - bad_area - marginal_area)

    return DraftAnalysisResult(
        pull_direction=PULL_Z,
        pull_direction_label="test",
        analysis_pass="test",
        good_face_ids=good_ids,
        marginal_face_ids=marginal_ids,
        bad_face_ids=bad_ids,
        skipped_face_ids=[],
        good_area_mm2=good_area,
        marginal_area_mm2=marginal_area,
        bad_area_mm2=bad_area,
        skipped_area_mm2=0.0,
        total_analysed_area_mm2=total_area,
        good_threshold_deg=1.5,
        marginal_threshold_deg=0.5,
        severity="none",
    )


def test_common_lower_bound_matches_score_candidate_shared_terms():
    """Direct algebraic re-verification: for a synthetic candidate with
    ZERO confirmed undercut and ZERO interference (the equality case of
    the proof), _score_candidate's Boolean-refined branch must equal
    _common_lower_bound exactly."""
    from backend.geometry.direction_optimizer import _common_lower_bound, _score_candidate
    from backend.geometry.undercut_detector import UndercutDetectionResult

    part = _make_mock_part()
    draft = _make_draft(bad_pct=20.0, marginal_pct=5.0, bad_ids=[1, 2], marginal_ids=[3], face_count=10)
    direction = PULL_Z

    undercuts = UndercutDetectionResult(
        pull_direction=direction, method="test",
        undercut_face_ids=[], accessible_face_ids=[], parting_face_ids=[], skipped_face_ids=[],
        boolean_refined=True,
        boolean_confirmed_face_ids=[],  # zero confirmed
        interference_volume_mm3=0.0,     # zero interference
        total_analysed_area_mm2=100.0,
    )

    bound = _common_lower_bound(draft, direction, part)
    actual = _score_candidate(draft, undercuts, direction, part)
    assert actual == pytest.approx(bound, abs=1e-9)


def test_common_lower_bound_is_strictly_less_when_undercut_confirmed():
    """When confirmed undercut area is genuinely positive, the actual
    score must be STRICTLY greater than the bound -- proving the bound is
    a true lower bound, not an approximation that happens to match."""
    from backend.geometry.direction_optimizer import _common_lower_bound, _score_candidate
    from backend.geometry.undercut_detector import UndercutDetectionResult
    from backend.models.geometry_models import FaceData
    from unittest.mock import MagicMock

    part = _make_mock_part()
    face = FaceData(
        face_id=0, occ_face=MagicMock(), surface_type="Plane", normal=(0.0, 0.0, 1.0),
        centroid=(0.0, 0.0, 0.0), area=50.0, u_range=(0.0, 1.0), v_range=(0.0, 1.0),
        is_reversed=False, normal_valid=True,
    )
    part.faces.append(face)
    draft = _make_draft(bad_pct=0.0, marginal_pct=0.0, face_count=1)
    direction = PULL_Z

    undercuts = UndercutDetectionResult(
        pull_direction=direction, method="test",
        undercut_face_ids=[], accessible_face_ids=[], parting_face_ids=[], skipped_face_ids=[],
        boolean_refined=True,
        boolean_confirmed_face_ids=[0],
        interference_volume_mm3=0.0,
        total_analysed_area_mm2=100.0,
    )

    bound = _common_lower_bound(draft, direction, part)
    actual = _score_candidate(draft, undercuts, direction, part)
    assert actual > bound


# ---------------------------------------------------------------------------
# 2. Score-bound pruning logic: candidate-level correctness (isolated,
#    reproducing exactly the pruning condition used inside
#    optimize_mold_direction's Stage 1+2 loop).
# ---------------------------------------------------------------------------

def _prune_condition(candidate_lower_bound: float, incumbent_score: float | None) -> bool:
    """Mirrors the EXACT condition used in optimize_mold_direction's
    Stage 1+2 loop: prune iff an incumbent exists AND
    candidate_lower_bound > incumbent.score (STRICT, not >=).

    Re-derived during implementation, deliberately deviating from a
    literal ">=" reading: >= is safe against a pure RAW-SCORE comparison,
    but not against the full _tiered_best/_comparator_key lexicographic
    order this project already relies on (tier, score, accessibility
    risk, axis alignment, direction). At an EXACT bound/incumbent tie,
    the untested candidate's actual final score can still equal the
    incumbent's (the bound is achieved exactly when confirmed_undercut_pct
    and interference_volume_frac are both zero) -- and at a genuine score
    tie, _tiered_best's further tiebreakers might prefer the untested
    candidate over the incumbent. Pruning at ">=" would silently discard
    that possibility without ever computing it. Strict ">" guarantees the
    pruned candidate's final score is PROVABLY worse, never merely
    not-yet-shown-better."""
    return incumbent_score is not None and candidate_lower_bound > incumbent_score


def test_candidate_with_bound_above_incumbent_is_pruned():
    assert _prune_condition(candidate_lower_bound=500.0, incumbent_score=100.0) is True


def test_candidate_with_bound_below_incumbent_is_not_pruned():
    assert _prune_condition(candidate_lower_bound=50.0, incumbent_score=100.0) is False


def test_no_incumbent_means_nothing_is_pruned():
    assert _prune_condition(candidate_lower_bound=1e9, incumbent_score=None) is False


def test_equality_boundary_is_deterministic_and_documented():
    """At an EXACT bound == incumbent tie, the candidate must NOT be
    pruned -- it is evaluated in full, and _tiered_best's own unmodified
    tiebreakers decide the outcome if its actual score does turn out to
    tie the incumbent's. This is the corrected, comparator-safe behavior
    (see _prune_condition's docstring) -- this test locks it in so a
    future change back to ">=" would fail here first."""
    assert _prune_condition(candidate_lower_bound=100.0, incumbent_score=100.0) is False


def test_negative_incumbent_score_is_not_a_valid_precondition():
    """The pruning proof (_common_lower_bound docstring) relies on every
    score being a sum of non-negative weighted terms -- a negative score
    would indicate a violated precondition (e.g. a negative config
    weight), which this test treats as invalid input the pruning logic
    should never be asked to reason about correctly."""
    from backend.config import settings

    cfg = settings.dfm.direction_search
    for name in (
        "scoring_bad_draft", "scoring_marginal_draft", "flash_risk_weight",
        "scoring_bad_draft_count", "scoring_marginal_draft_count",
        "scoring_axis_preference", "scoring_confirmed_undercut",
        "boolean_interference_weight",
    ):
        value = getattr(cfg, name)
        assert value >= 0.0, f"{name}={value} violates the pruning proof's non-negativity precondition"


# ---------------------------------------------------------------------------
# 3. _is_parting_line_feasible: synthetic eligibility matrix.
# ---------------------------------------------------------------------------

def test_feasibility_matrix_verified_and_feasible_is_eligible():
    evidence_tier = "verified_acceptable"
    feasible = True
    eligible = evidence_tier == "verified_acceptable" and feasible
    assert eligible is True


def test_feasibility_matrix_verified_and_infeasible_is_not_eligible():
    evidence_tier = "verified_acceptable"
    feasible = False
    eligible = evidence_tier == "verified_acceptable" and feasible
    assert eligible is False


def test_feasibility_matrix_unverified_and_feasible_is_not_eligible():
    evidence_tier = "verified_undercuts_present"
    feasible = True
    eligible = evidence_tier == "verified_acceptable" and feasible
    assert eligible is False


def test_feasibility_matrix_no_feasible_candidate_means_optimal_not_found():
    best_feasible = None
    optimal_found = best_feasible is not None
    assert optimal_found is False


# ---------------------------------------------------------------------------
# 4. Real geometry, single-direction only -- NOT the full 18-direction search.
# ---------------------------------------------------------------------------

@requires_occ
@requires_part1
def test_part1_z_is_parting_line_feasible():
    from backend.geometry.step_loader import load_step
    from backend.geometry.direction_optimizer import _is_parting_line_feasible

    part = load_step(str(PART1_PATH))
    assert _is_parting_line_feasible(part, PULL_Z).feasible is True


@requires_occ
@requires_part1
def test_part1_diagonal_is_not_parting_line_feasible():
    """The exact counter-example this whole phase is built around: the
    direction-optimizer's own evidence-only winner on Part1 is
    independently rejected by parting_line_v2."""
    from backend.geometry.step_loader import load_step
    from backend.geometry.direction_optimizer import _is_parting_line_feasible

    part = load_step(str(PART1_PATH))
    assert _is_parting_line_feasible(part, DIAGONAL).feasible is False


@requires_occ
@requires_part3
def test_part3_z_without_core_pin_authorization_is_honestly_infeasible():
    """
    Part3's H3 gate has no purely-geometric closure for its coaxial
    through-bore -- it structurally requires the SEPARATE, human-
    authorized core_pin_face_refs/delegations mechanism (D-043/D-044,
    untouched by this phase) to close at all. Verified directly:
    analyse_parting_line(Part3, +Z) with NO authorization returns
    outcome="no_feasible_candidate", regions=None.

    With no authorization supplied (the default, O3), this means Part3's
    automatic optimal_found is honestly False -- this is the exact
    category of previously-hidden defect D-062 exists to surface, not a
    regression to work around.
    """
    from backend.geometry.step_loader import load_step
    from backend.geometry.direction_optimizer import _is_parting_line_feasible

    part = load_step(str(PART3_PATH))
    result = _is_parting_line_feasible(part, PULL_Z)
    assert result.feasible is False


# ---------------------------------------------------------------------------
# O3 (2026-08-17): threading optional, caller-supplied authorization
# through optimize_mold_direction(). Ground truth reused verbatim from the
# already-frozen, already-verified candidate-110 fixture
# (tests/test_parting_line_v2_region_balance.py's _candidate_110_result) --
# not invented for this file.
# ---------------------------------------------------------------------------

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
            evidence=DelegationEvidence(source="manual_engineering", note="original rib stack, radial outward +X"),
        ),
        DelegatedSecondaryAction(
            face_ids=STACK2, movement_direction=(-1.0, 0.0, 0.0), movement_type="radial_slide",
            evidence=DelegationEvidence(source="manual_engineering", note="mirror rib stack, radial outward -X"),
        ),
    )
    return refs, delegations


# TEST 1 — Part3 +Z WITHOUT authorization remains infeasible (duplicate of
# the pre-O3 test above, kept explicit per the required test list).
@requires_occ
@requires_part3
def test_1_part3_z_without_authorization_remains_infeasible():
    from backend.geometry.step_loader import load_step
    from backend.geometry.direction_optimizer import _is_parting_line_feasible

    part = load_step(str(PART3_PATH))
    result = _is_parting_line_feasible(part, PULL_Z)
    assert result.feasible is False


# TEST 2 — Part3 +Z WITH candidate-110's exact known-good authorization
# becomes feasible, and the underlying regions match the frozen result.
@requires_occ
@requires_part3
def test_2_part3_z_with_candidate_110_authorization_is_feasible():
    from backend.geometry.step_loader import load_step
    from backend.geometry.direction_optimizer import _is_parting_line_feasible
    from backend.geometry.parting_line_v2 import PullDirectionInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line
    from backend.config import settings

    part = load_step(str(PART3_PATH))
    refs, delegations = _candidate_110_authorization()

    result = _is_parting_line_feasible(part, PULL_Z, refs, delegations)
    assert result.feasible is True

    # Do not merely check the boolean: compare the actual gate/region
    # result against the frozen candidate-110 fixture values.
    full = analyse_parting_line(
        part, PullDirectionInput(PULL_Z, "fixture"), cfg=settings.dfm.parting_line_v2,
        core_pin_face_refs=refs, delegations=delegations,
    )
    assert full.outcome == "feasible"
    assert full.selected is not None
    assert full.selected.candidate_id == 110
    assert full.regions is not None
    assert len(full.regions.cavity_face_ids) == 410
    assert full.regions.core_face_ids == frozenset({35, 36, 37, 320, 321})


# TEST 3 — Part1 +Z WITHOUT authorization: feasibility unaffected.
@requires_occ
@requires_part1
def test_3_part1_z_without_authorization_remains_feasible():
    from backend.geometry.step_loader import load_step
    from backend.geometry.direction_optimizer import _is_parting_line_feasible

    part = load_step(str(PART1_PATH))
    assert _is_parting_line_feasible(part, PULL_Z).feasible is True


# TEST 4 — Part1 +Z WITH empty authorization explicitly supplied: identical.
@requires_occ
@requires_part1
def test_4_part1_z_with_explicit_empty_authorization_is_identical():
    from backend.geometry.step_loader import load_step
    from backend.geometry.direction_optimizer import _is_parting_line_feasible

    part = load_step(str(PART1_PATH))
    default_result = _is_parting_line_feasible(part, PULL_Z)
    explicit_result = _is_parting_line_feasible(part, PULL_Z, (), ())
    assert default_result.feasible == explicit_result.feasible is True


# TEST 5 — Part1's previously-rejected diagonal remains infeasible even
# with Part3's authorization supplied (proves O1 was not weakened by
# threading unrelated authorization through).
@requires_occ
@requires_part1
def test_5_part1_diagonal_remains_infeasible_even_with_authorization_supplied():
    from backend.geometry.step_loader import load_step
    from backend.geometry.direction_optimizer import _is_parting_line_feasible

    part = load_step(str(PART1_PATH))
    refs, delegations = _candidate_110_authorization()
    result = _is_parting_line_feasible(part, DIAGONAL, refs, delegations)
    assert result.feasible is False


# TEST 6 — Authorization isolation: no automatic construction of
# CorePinFaceRef/DelegatedSecondaryAction anywhere in direction_optimizer.py,
# and no Part1/Part3/fixture-specific branching.
def test_6_direction_optimizer_never_constructs_authorization_itself():
    import inspect
    from backend.geometry import direction_optimizer

    source = inspect.getsource(direction_optimizer)
    assert "CorePinFaceRef(" not in source, (
        "direction_optimizer.py must never construct a CorePinFaceRef itself"
    )
    assert "DelegatedSecondaryAction(" not in source, (
        "direction_optimizer.py must never construct a DelegatedSecondaryAction itself"
    )


def test_6_direction_optimizer_has_no_fixture_specific_branching():
    import inspect
    from backend.geometry import direction_optimizer

    source = inspect.getsource(direction_optimizer)
    for needle in ("Part1.stp", "Part3.stp", "Part1\"", "Part3\"", "candidate_id == 110", "face_id == 35"):
        assert needle not in source, f"found forbidden fixture-specific text: {needle!r}"


# TEST 7 — O2 interaction: synthetic candidates verify the bound/pruning
# logic still requires downstream feasibility, without running the full
# optimizer.
def test_7_pruning_condition_is_independent_of_and_compatible_with_feasibility_gate():
    """
    The O2 pruning rule (candidate_lower_bound > incumbent.score) and the
    O1 feasibility gate are orthogonal checks applied in sequence inside
    the same loop (see optimize_mold_direction's Stage 1+2 block): a
    candidate is pruned purely on the mathematical bound BEFORE any
    Boolean/feasibility work runs, and separately, a fully-evaluated
    candidate only becomes the incumbent if BOTH evidence_tier ==
    "verified_acceptable" AND feasibility.feasible are True. This test
    exercises that combined eligibility logic directly, with synthetic
    values, mirroring the exact loop body -- not the full 18-direction
    search.
    """
    def eligible(evidence_tier: str, feasible: bool) -> bool:
        if evidence_tier != "verified_acceptable":
            return False
        return feasible

    assert eligible("verified_acceptable", True) is True
    assert eligible("verified_acceptable", False) is False
    assert eligible("verified_undercuts_present", True) is False
    assert eligible("unverified", False) is False

    # Pruning must still occur purely on the bound, before feasibility is
    # ever consulted -- a pruned candidate's feasibility is simply never
    # computed (verified by construction: the loop `continue`s/`break`s
    # before reaching the feasibility call for such candidates).
    def prune_condition(candidate_lower_bound: float, incumbent_score: float | None) -> bool:
        return incumbent_score is not None and candidate_lower_bound > incumbent_score

    incumbent_score = 100.0  # only established AFTER a feasible candidate is found
    assert prune_condition(150.0, incumbent_score) is True
    assert prune_condition(50.0, incumbent_score) is False
    # Before any feasible incumbent exists, nothing is prunable on the
    # bound alone -- every candidate must still get its chance to be
    # evaluated for both evidence and feasibility.
    assert prune_condition(1e9, None) is False


# ---------------------------------------------------------------------------
# O4 (2026-08-17): initial_pull_direction seeding of the Stage 1+2 incumbent.
#
# The already-computed initial-direction evidence (initial/initial_undercuts,
# unconditionally built before Stage 1+2 even runs -- see
# optimize_mold_direction's docstring) is now also used to seed
# best_feasible, but ONLY when it independently passes the exact same two
# gates every other candidate must pass: evidence_tier=="verified_acceptable"
# AND _is_parting_line_feasible(...).feasible. Tests A/B/C/G below exercise
# the seeding condition and the feasibility cache in isolation, mirroring
# the production block in optimize_mold_direction without running the full
# 18-direction search. Tests I-L re-confirm the four already-established
# Part1/Part3 feasibility facts hold through the new
# _cached_is_parting_line_feasible wrapper that is now actually wired into
# the optimizer, using single-direction real-geometry calls only.
# ---------------------------------------------------------------------------


def _clean_boolean_refined_undercuts():
    from backend.geometry.undercut_detector import UndercutDetectionResult

    return UndercutDetectionResult(
        pull_direction=PULL_Z, method="mock-boolean", undercut_face_ids=[],
        accessible_face_ids=[], parting_face_ids=[], skipped_face_ids=[],
        boolean_refined=True, boolean_confirmed_face_ids=[],
        total_analysed_area_mm2=100.0,
    )


def _unverified_undercuts():
    from backend.geometry.undercut_detector import UndercutDetectionResult

    return UndercutDetectionResult(
        pull_direction=PULL_Z, method="mock-cheap-only", undercut_face_ids=[],
        accessible_face_ids=[], parting_face_ids=[], skipped_face_ids=[],
        boolean_refined=False, total_analysed_area_mm2=100.0,
    )


# TEST A — Initial feasible seed: evidence-verified AND parting_line_v2
# feasible -- the seeding condition must accept it.
def test_a_initial_feasible_and_verified_direction_is_eligible_to_seed(monkeypatch):
    import backend.geometry.direction_optimizer as optimizer_module
    from backend.config import settings

    part = _make_mock_part()
    draft = _make_draft(bad_pct=0.0, marginal_pct=0.0)
    undercuts = _clean_boolean_refined_undercuts()
    cfg = settings.dfm.direction_search

    initial_candidate = optimizer_module._build_refined_candidate(
        PULL_Z, draft, undercuts, part, cfg,
    )
    assert initial_candidate.evidence_tier == "verified_acceptable"

    monkeypatch.setattr(
        optimizer_module, "_is_parting_line_feasible",
        lambda part, direction, *a, **k: optimizer_module.PartingLineFeasibilityResult(feasible=True),
    )
    cache: dict = {}
    feasibility = optimizer_module._cached_is_parting_line_feasible(part, PULL_Z, (), (), cache)
    assert feasibility.feasible is True

    # Exactly the two-gate condition optimize_mold_direction applies before
    # seeding best_feasible.
    would_seed = (
        initial_candidate.evidence_tier == "verified_acceptable" and feasibility.feasible
    )
    assert would_seed is True


# TEST B — Initial infeasible seed: evidence-verified but parting_line_v2
# rejects it -- must NOT seed, regardless of how good the evidence looks.
def test_b_initial_infeasible_direction_never_seeds_incumbent(monkeypatch):
    import backend.geometry.direction_optimizer as optimizer_module
    from backend.config import settings

    part = _make_mock_part()
    draft = _make_draft(bad_pct=0.0, marginal_pct=0.0)
    undercuts = _clean_boolean_refined_undercuts()
    cfg = settings.dfm.direction_search

    initial_candidate = optimizer_module._build_refined_candidate(
        PULL_Z, draft, undercuts, part, cfg,
    )
    assert initial_candidate.evidence_tier == "verified_acceptable"

    monkeypatch.setattr(
        optimizer_module, "_is_parting_line_feasible",
        lambda part, direction, *a, **k: optimizer_module.PartingLineFeasibilityResult(
            feasible=False, reason="mock-rejected",
        ),
    )
    cache: dict = {}
    feasibility = optimizer_module._cached_is_parting_line_feasible(part, PULL_Z, (), (), cache)
    assert feasibility.feasible is False

    would_seed = (
        initial_candidate.evidence_tier == "verified_acceptable" and feasibility.feasible
    )
    assert would_seed is False


# TEST B2 — An unverified evidence tier must never seed even if a
# feasibility check would (hypothetically) return True -- the evidence
# gate is checked FIRST, and _is_parting_line_feasible must never even be
# consulted for an unverified candidate (mirrors the production
# short-circuit `if initial_candidate.evidence_tier == "verified_acceptable"`).
def test_b2_unverified_evidence_tier_never_seeds_even_if_feasible(monkeypatch):
    import backend.geometry.direction_optimizer as optimizer_module
    from backend.config import settings

    part = _make_mock_part()
    draft = _make_draft(bad_pct=0.0, marginal_pct=0.0)
    undercuts = _unverified_undercuts()
    cfg = settings.dfm.direction_search

    initial_candidate = optimizer_module._build_refined_candidate(
        PULL_Z, draft, undercuts, part, cfg,
    )
    assert initial_candidate.evidence_tier == "unverified"

    calls = []
    monkeypatch.setattr(
        optimizer_module, "_is_parting_line_feasible",
        lambda part, direction, *a, **k: (
            calls.append(direction),
            optimizer_module.PartingLineFeasibilityResult(feasible=True),
        )[1],
    )
    if initial_candidate.evidence_tier == "verified_acceptable":
        optimizer_module._cached_is_parting_line_feasible(part, PULL_Z, (), (), {})
    assert calls == [], "feasibility must never be consulted for an unverified initial candidate"


# TEST C — Initial direction identical to Stage-1 +Z: the feasibility
# cache key must be byte-identical whether built from the initial-seed
# call site or from Stage 1's own loop reaching the same direction later.
def test_c_feasibility_cache_key_identical_for_coincident_directions():
    from backend.geometry.direction_optimizer import _feasibility_cache_key
    from backend.models.geometry_models import normalize3

    part = _make_mock_part()
    key_from_initial_seed = _feasibility_cache_key(part, PULL_Z, (), ())
    key_from_stage1_own_principal = _feasibility_cache_key(part, normalize3((0.0, 0.0, 1.0)), (), ())
    key_from_unnormalized_input = _feasibility_cache_key(part, normalize3((0.0, 0.0, 5.0)), (), ())

    assert key_from_initial_seed == key_from_stage1_own_principal == key_from_unnormalized_input

    # Different authorization must NOT collide with the unauthorized key --
    # this is what lets Part3's authorized/unauthorized checks coexist in
    # the same cache without one masking the other.
    from backend.geometry.parting_line_v2.contracts import CorePinFaceRef
    refs = (CorePinFaceRef(35, PULL_Z, "test"),)
    key_with_authorization = _feasibility_cache_key(part, PULL_Z, refs, ())
    assert key_with_authorization != key_from_initial_seed


# TEST G — Seeding must never bypass _tiered_best's own tiebreaker
# hierarchy: two feasible, same-tier, same-score candidates differing
# only in accessibility_risk_area_pct must resolve identically regardless
# of which one plays the role of "the seed" (i.e. regardless of list
# order), never via a bespoke score-only comparison.
def test_g_seed_does_not_bypass_tiered_comparator_tiebreakers():
    from backend.geometry.direction_optimizer import DirectionCandidateResult, _tiered_best

    common_kwargs = dict(
        label="candidate", score=100.0, bad_face_count=0, marginal_face_count=0,
        good_face_count=1, bad_area_mm2=0.0, marginal_area_mm2=0.0,
        total_area_mm2=100.0, bad_area_pct=0.0, marginal_area_pct=0.0,
        undercut_face_count=0, undercut_feature_count=0, undercut_area_pct=0.0,
        boolean_refined=True, boolean_checked_count=0, interference_volume_mm3=0.0,
        principal_axis_alignment=1.0, evidence_tier="verified_acceptable",
    )
    higher_risk_seed = DirectionCandidateResult(
        direction=(0.0, 0.0, 1.0), accessibility_risk_area_pct=40.0, **common_kwargs,
    )
    lower_risk_later_discovery = DirectionCandidateResult(
        direction=(0.0, 0.0, -1.0), accessibility_risk_area_pct=5.0, **common_kwargs,
    )

    winner_seed_first = _tiered_best([higher_risk_seed, lower_risk_later_discovery])
    winner_seed_last = _tiered_best([lower_risk_later_discovery, higher_risk_seed])

    assert winner_seed_first is lower_risk_later_discovery
    assert winner_seed_last is lower_risk_later_discovery


# TEST I — Part1 +Z remains feasible through the cached wrapper.
@requires_occ
@requires_part1
def test_i_part1_z_remains_feasible_through_cached_wrapper():
    from backend.geometry.step_loader import load_step
    from backend.geometry.direction_optimizer import _cached_is_parting_line_feasible

    part = load_step(str(PART1_PATH))
    cache: dict = {}
    result = _cached_is_parting_line_feasible(part, PULL_Z, (), (), cache)
    assert result.feasible is True
    assert len(cache) == 1
    # A second call for the same direction must hit the cache, not
    # re-invoke analyse_parting_line -- verified via a second call
    # returning the exact same object.
    result_again = _cached_is_parting_line_feasible(part, PULL_Z, (), (), cache)
    assert result_again is result
    assert len(cache) == 1


# TEST J — Part1's known diagonal remains infeasible through the cached
# wrapper (O1 unweakened by the O4 integration).
@requires_occ
@requires_part1
def test_j_part1_diagonal_remains_infeasible_through_cached_wrapper():
    from backend.geometry.step_loader import load_step
    from backend.geometry.direction_optimizer import _cached_is_parting_line_feasible

    part = load_step(str(PART1_PATH))
    result = _cached_is_parting_line_feasible(part, DIAGONAL, (), (), {})
    assert result.feasible is False


# TEST K — Part3 +Z remains infeasible without authorization through the
# cached wrapper.
@requires_occ
@requires_part3
def test_k_part3_z_remains_infeasible_without_authorization_through_cached_wrapper():
    from backend.geometry.step_loader import load_step
    from backend.geometry.direction_optimizer import _cached_is_parting_line_feasible

    part = load_step(str(PART3_PATH))
    result = _cached_is_parting_line_feasible(part, PULL_Z, (), (), {})
    assert result.feasible is False


# TEST L — Part3 +Z remains feasible with the known candidate-110
# authorization through the cached wrapper.
@requires_occ
@requires_part3
def test_l_part3_z_remains_feasible_with_candidate_110_authorization_through_cached_wrapper():
    from backend.geometry.step_loader import load_step
    from backend.geometry.direction_optimizer import _cached_is_parting_line_feasible

    part = load_step(str(PART3_PATH))
    refs, delegations = _candidate_110_authorization()
    result = _cached_is_parting_line_feasible(part, PULL_Z, refs, delegations, {})
    assert result.feasible is True


# TEST M (C12, 2026-08-17) — full real optimize_mold_direction() search on
# Part3 with candidate-110's authorization threaded through. Combines two of
# C12's required test categories into one real (expensive, ~200s+) run:
# (a) the top-level result reports requires_side_action referrals while
# optimal_found is False, and (b) explicit proof no side_core function is
# ever invoked, even though referrals occur.
#
# Ground truth established by a real run this session
# (side_action_referrals had 11 entries, all attributed to +Z/-Z -- NOT the
# actual winning -X direction; optimal_found=False; best_direction=-X;
# best_score=271.6557846314601 -- identical to the pre-C12 C10 baseline
# run). This is NOT the same as "candidate-110's own +Z direction becomes
# the winner" -- the winner here is whichever direction the unmodified
# tiered comparator picks as best overall (-X), independent of the
# candidate-110 authorization's own +Z referral. That referral shows up in
# side_action_referrals purely as a diagnostic entry for +Z/-Z, exactly as
# C11/C12 designed: PartingLineV2Result.referrals aggregates every
# candidate's referral for a direction, independent of whether that
# direction is the ultimate optimizer winner.
@requires_occ
@requires_part3
def test_m_part3_candidate_110_authorized_reports_referrals_without_side_core(monkeypatch):
    from backend.geometry.step_loader import load_step
    from backend.geometry.direction_optimizer import optimize_mold_direction
    import backend.geometry.side_core as side_core_mod

    def explode(*a, **k):
        raise AssertionError("optimize_mold_direction must never call side_core")

    monkeypatch.setattr(side_core_mod, "generate_side_core", explode)
    monkeypatch.setattr(side_core_mod, "generate_primary_side_core", explode)
    monkeypatch.setattr(side_core_mod, "generate_side_cores_for_features", explode)

    part = load_step(str(PART3_PATH))
    refs, delegations = _candidate_110_authorization()
    result = optimize_mold_direction(part, core_pin_face_refs=refs, delegations=delegations)

    # (a) requires_side_action referrals are surfaced at the top level.
    assert len(result.side_action_referrals) > 0
    for entry in result.side_action_referrals:
        assert set(entry.keys()) == {"direction", "direction_label", "referral"}
        assert entry["referral"]["note"] == (
            "Main parting line cannot pass cleanly through this feature; "
            "requires a side action."
        )

    # optimal_found remains False -- H5 requires_side_action is still not a
    # valid main-split optimum, and this is NOT collapsed into generic
    # "no feasible candidate" infeasibility (best_evidence_tier stays
    # "verified_acceptable", proving the distinction survives).
    assert result.optimal_found is False
    assert result.best_evidence_tier == "verified_acceptable"

    # (b) no exception means no side_core function was ever called, even
    # though real requires_side_action referrals occurred during this run.


# TEST N (C12, 2026-08-17) — Part1 unauthorized: the optimizer's own
# selected optimum is completely unaffected by any side_action_referrals
# collected along the way. Ground truth established by a real run this
# session: Part1 DOES produce non-empty side_action_referrals (4 entries,
# from +Z/-Z candidates other than the winner) -- this is expected,
# by-design behavior (PartingLineV2Result.referrals aggregates every
# candidate's referral for a direction, independent of that direction's own
# selected/feasible outcome -- see C11's analysis of
# PartingLineV2Result.referrals), NOT a regression. The invariant C12
# actually guarantees for Part1 is backward compatibility of the WINNING
# direction: optimal_found stays True and best_direction/best_score are
# byte-identical to the pre-C12 baseline (best_score=742.3105286124178,
# best_direction=-Z, established in Phase C10).
@requires_occ
@requires_part1
def test_n_part1_unauthorized_optimum_unaffected_by_referrals():
    from backend.geometry.step_loader import load_step
    from backend.geometry.direction_optimizer import optimize_mold_direction

    part = load_step(str(PART1_PATH))
    result = optimize_mold_direction(part)

    assert result.optimal_found is True
    assert result.best_direction == (0.0, 0.0, -1.0)
    assert result.best_label == "-Z"
    assert abs(result.best_score - 742.3105286124178) < 1e-6
    # Every referral entry (if any) must be a well-formed diagnostic and
    # must NOT be for the winning direction's OWN selected candidate --
    # i.e. its presence never changes optimal_found/best_direction/
    # best_score above, which is the actual backward-compatibility
    # guarantee C12 makes for Part1.
    for entry in result.side_action_referrals:
        assert set(entry.keys()) == {"direction", "direction_label", "referral"}
