"""
tests/test_direction_optimizer_evidence_tiers.py
----------------------------------------------------
Phase 5B (2026-08-16): characterization/semantic tests for the tiered
evidence-based selection correction to optimize_mold_direction.

Design under test:
  - All 6 principal axes + all 12 configured diagonals are ALWAYS
    Boolean-refined now, regardless of the cheap bad_pct/accessibility_
    risk_pct screen (which remains a triage signal for the Stage-3
    spherical grid only).
  - Every DirectionCandidateResult carries an explicit evidence_tier
    ("verified_acceptable" | "verified_undercuts_present" | "unverified")
    and confirmed_undercut_pct (0.0 when unverified -- never read as
    "confirmed clean").
  - Final selection is tier-first, score-second (_tiered_best), never a
    raw-score-only sort across candidates with different evidence quality.
  - optimal_found=True iff the winner's own evidence_tier is
    "verified_acceptable". best_unverified_candidate is populated
    whenever optimal_found is False.

These tests use TODAY's live baseline (real STEP geometry, actual
scoring/threshold config) as characterization evidence, not invented
expectations -- and are explicit about WHY each assertion should hold
given the design, not merely "whatever the code currently returns".

No Part1/Part3/UC3 face IDs or thresholds are hardcoded to force a
particular outcome; every assertion is a structural property of the
design (e.g. "if boolean_refined is True for a candidate, its
evidence_tier must not be 'unverified'"), evaluated against real data.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tests"))
from test_direction_optimizer import _make_face, _make_part  # noqa: E402
PART1_PATH = REPO_ROOT / "data" / "parts" / "Part1.stp"
PART3_PATH = REPO_ROOT / "data" / "parts" / "Part3.stp"
DHUKKAN_PATH = REPO_ROOT / "data" / "parts" / "Dhukkan.stp"
UC3_PATH = REPO_ROOT / "data" / "fixtures" / "synthetic" / "UC3_spool_true_undercut.stp"


def _occ_available() -> bool:
    try:
        import OCC  # noqa: F401
        return True
    except ImportError:
        return False


requires_occ = pytest.mark.skipif(not _occ_available(), reason="pythonOCC not installed")
requires_part1 = pytest.mark.skipif(not PART1_PATH.exists(), reason="Part1.stp not present")
requires_part3 = pytest.mark.skipif(not PART3_PATH.exists(), reason="Part3.stp not present")
requires_dhukkan = pytest.mark.skipif(not DHUKKAN_PATH.exists(), reason="Dhukkan.stp not present")
requires_uc3 = pytest.mark.skipif(not UC3_PATH.exists(), reason="UC3 fixture not present")
pytestmark = [pytest.mark.filterwarnings("ignore::DeprecationWarning"), pytest.mark.slow]


def _load(path):
    from backend.geometry.step_loader import load_step
    return load_step(str(path))


def _optimize(path):
    from backend.geometry.direction_optimizer import optimize_mold_direction
    return optimize_mold_direction(_load(path))


# Module-scoped fixtures: each real part's full optimizer search is run
# EXACTLY ONCE per test session and shared across every test that needs it
# (a single Part1 run alone costs ~150s -- calling optimize_mold_direction
# fresh per test function here would make this file impractically slow).
@pytest.fixture(scope="module")
def part1_result():
    return _optimize(PART1_PATH)


@pytest.fixture(scope="module")
def part3_result():
    return _optimize(PART3_PATH)


@pytest.fixture(scope="module")
def dhukkan_result():
    return _optimize(DHUKKAN_PATH)


@pytest.fixture(scope="module")
def uc3_result():
    return _optimize(UC3_PATH)


# ---------------------------------------------------------------------------
# H1/H2. Principal/configured directions are Boolean-refined even when they
# fail the cheap bad_pct/accessibility_risk_pct gate.
# ---------------------------------------------------------------------------

@requires_occ
@requires_part1
def test_part1_principal_axes_are_boolean_refined_despite_high_bad_pct(part1_result):
    """Characterization: on Part1, every one of the 6 principal axes has
    bad_pct far above suitability_max_bad_draft_pct (measured this session:
    43-72% vs a 30% threshold) -- pre-Phase-5B, none of them would ever
    reach Boolean refinement. Post-Phase-5B, all 6 must be boolean_refined
    regardless of that gate."""
    result = part1_result
    principal_labels = {"+X", "-X", "+Y", "-Y", "+Z", "-Z"}
    principal_candidates = [c for c in result.candidates if c.label in principal_labels]
    assert len(principal_candidates) == 6
    for c in principal_candidates:
        assert c.boolean_refined is True, f"{c.label} was never Boolean-refined"
        # Corroborates the audit's own finding -- if this ever stops being
        # true, the "why this matters" story for this test changes and
        # should be re-examined, not silently left stale.
        # (Not asserted as a hard requirement -- draft/geometry could
        # change if Part1.stp is ever replaced -- just characterized.)


@requires_occ
@requires_uc3
def test_uc3_z_axes_are_boolean_refined_despite_failing_cheap_screen(uc3_result):
    """Characterization: UC3's ±Z axes fail the cheap screen (measured:
    bad_pct=42.18%, over the 30% default) yet sit exactly on this fixture's
    hand-verified true undercut axis. They must still be Boolean-refined."""
    result = uc3_result
    z_candidates = [c for c in result.candidates if c.label in ("+Z", "-Z")]
    assert len(z_candidates) == 2
    for c in z_candidates:
        assert c.boolean_refined is True


# ---------------------------------------------------------------------------
# H3. A verified-clean candidate outranks an unverified one even with a
# numerically lower raw score.
# ---------------------------------------------------------------------------

@requires_occ
def test_verified_beats_unverified_regardless_of_raw_score():
    """Direct, deterministic proof of the tier-first comparator (no live
    geometry needed -- this is a property of _tiered_best itself)."""
    from backend.geometry.direction_optimizer import DirectionCandidateResult, _tiered_best

    def _candidate(label, score, tier, confirmed_pct=0.0):
        return DirectionCandidateResult(
            direction=(1.0, 0.0, 0.0), label=label, score=score,
            bad_face_count=0, marginal_face_count=0, good_face_count=1,
            bad_area_mm2=0.0, marginal_area_mm2=0.0, total_area_mm2=1.0,
            bad_area_pct=0.0, marginal_area_pct=0.0, undercut_face_count=0,
            undercut_feature_count=0, undercut_area_pct=0.0,
            boolean_refined=(tier != "unverified"), boolean_checked_count=0,
            interference_volume_mm3=0.0, principal_axis_alignment=1.0,
            confirmed_undercut_pct=confirmed_pct, evidence_tier=tier,
        )

    unverified_low_score = _candidate("cheap-only", score=1.0, tier="unverified")
    verified_high_score = _candidate("verified", score=999.0, tier="verified_acceptable")

    winner = _tiered_best([unverified_low_score, verified_high_score])
    assert winner is verified_high_score, (
        "an unverified candidate with a numerically lower score must never "
        "outrank a verified-acceptable one"
    )


# ---------------------------------------------------------------------------
# H4. A verified candidate with confirmed undercuts does not masquerade as
# clean.
# ---------------------------------------------------------------------------

@requires_occ
def test_verified_with_undercuts_is_not_reported_as_clean():
    from backend.geometry.direction_optimizer import DirectionCandidateResult, _evidence_tier
    from backend.config import settings

    cfg = settings.dfm.direction_search
    tier = _evidence_tier(
        boolean_refined=True,
        confirmed_undercut_pct=cfg.suitability_max_confirmed_undercut_pct + 5.0,
        feature_acceptability="clean",
        cfg=cfg,
    )
    assert tier == "verified_undercuts_present"
    assert tier != "verified_acceptable"


# ---------------------------------------------------------------------------
# H5. If no direction passes acceptance, no direction is reported as a
# validated optimum.
# ---------------------------------------------------------------------------

@requires_occ
def test_no_acceptable_candidate_means_optimal_found_is_false(monkeypatch):
    """Deterministic construction (mock geometry, OCC forced unavailable)
    so boolean_refined is False everywhere -- optimal_found must be False,
    never silently True with an unvalidated best_direction."""
    import backend.geometry.undercut_detector as undercut_module
    from backend.geometry.direction_optimizer import optimize_mold_direction

    monkeypatch.setattr(undercut_module, "_OCC_BOOLEAN_AVAILABLE", False)

    face = _make_face(0, (0.0, 0.0, 1.0), area=100.0)
    part = _make_part([face])
    result = optimize_mold_direction(part, angular_step_deg=45.0, max_candidates=6)
    assert result.optimal_found is False
    assert result.best_evidence_tier != "verified_acceptable"


# ---------------------------------------------------------------------------
# H6. Diagnostic best-unverified candidate can still be returned separately.
# ---------------------------------------------------------------------------

@requires_occ
def test_best_unverified_candidate_exposed_when_nothing_verified(monkeypatch):
    import backend.geometry.undercut_detector as undercut_module
    from backend.geometry.direction_optimizer import optimize_mold_direction

    monkeypatch.setattr(undercut_module, "_OCC_BOOLEAN_AVAILABLE", False)
    face = _make_face(0, (0.0, 0.0, 1.0), area=100.0)
    part = _make_part([face])
    result = optimize_mold_direction(part, angular_step_deg=45.0, max_candidates=6)
    assert result.best_unverified_candidate is not None
    assert result.best_unverified_candidate.direction == result.best_direction
    assert result.best_unverified_candidate.evidence_tier == result.best_evidence_tier


# ---------------------------------------------------------------------------
# H7. Stage-3 candidates can still use cheap triage without forcing full
# spherical-grid Boolean verification.
# ---------------------------------------------------------------------------

@requires_occ
@requires_uc3
def test_stage3_spherical_grid_is_not_exhaustively_boolean_refined():
    """
    Forces Stage 3 deterministically by making the acceptance threshold
    unsatisfiable (suitability_max_confirmed_undercut_pct < 0, so even a
    genuinely 0%-confirmed candidate can never be "verified_acceptable") --
    without this override, UC3 now legitimately finds a verified-acceptable
    diagonal within Stage 1+2 (a direct, positive consequence of this same
    Phase 5B fix: diagonals are now always Boolean-refined too) and exits
    early, which is correct behavior but means UC3's un-forced outcome no
    longer reliably exercises Stage 3's own triage path. Stage 3 must still
    triage (not Boolean-verify every one of its spherical candidates) --
    the existing pruning mechanism (_select_boolean_refinement_candidates)
    is untouched by Phase 5B.
    """
    from backend.config import settings
    from backend.geometry.direction_optimizer import optimize_mold_direction, _direction_label
    from backend.models.geometry_models import normalize3
    from backend.geometry.step_loader import load_step

    original_cfg = settings.dfm.direction_search
    unsatisfiable_cfg = type(original_cfg)(**{
        **{f.name: getattr(original_cfg, f.name) for f in original_cfg.__dataclass_fields__.values()},
        "suitability_max_confirmed_undercut_pct": -1.0,
    })
    object.__setattr__(settings.dfm, "direction_search", unsatisfiable_cfg)
    try:
        part = load_step(str(UC3_PATH))
        result = optimize_mold_direction(part)
    finally:
        object.__setattr__(settings.dfm, "direction_search", original_cfg)

    assert result.optimal_found is False, "threshold is unsatisfiable by construction"
    principal_labels = {"+X", "-X", "+Y", "-Y", "+Z", "-Z"}
    diagonal_labels = {
        _direction_label(normalize3(d)) for d in original_cfg.stage2_directions
    }
    stage12_labels = principal_labels | diagonal_labels
    spherical_candidates = [c for c in result.candidates if c.label not in stage12_labels]
    assert len(spherical_candidates) > 0, "Stage 3 should be reached when nothing can ever be acceptable"
    boolean_refined_spherical = sum(1 for c in spherical_candidates if c.boolean_refined)
    assert boolean_refined_spherical < len(spherical_candidates), (
        "Stage 3 triage should still prune most spherical candidates from "
        "Boolean refinement -- verifying every one would be the "
        "computationally-expensive full search this design explicitly "
        "avoids"
    )


# ---------------------------------------------------------------------------
# H8/H9. Existing Part3 +X/-X and Dhukkan +Z behavior remains explainable.
# ---------------------------------------------------------------------------

@requires_occ
@requires_part3
def test_part3_plus_x_minus_x_remain_explainable_post_correction(part3_result):
    """Characterization, not a fixed-number regression pin: +X and -X must
    both be boolean_refined (they pass the cheap screen on Part3), and
    whichever one the optimizer prefers must be explainable by its own
    evidence_tier/confirmed_undercut_pct -- never by an unverified score."""
    result = part3_result
    plus_x = next(c for c in result.candidates if c.label == "+X")
    minus_x = next(c for c in result.candidates if c.label == "-X")
    assert plus_x.boolean_refined is True
    assert minus_x.boolean_refined is True
    assert plus_x.evidence_tier != "unverified"
    assert minus_x.evidence_tier != "unverified"
    # Whichever the optimizer actually selected must be tier-consistent
    # with its own comparison rule.
    from backend.geometry.direction_optimizer import _EVIDENCE_TIER_RANK
    winner_candidate = next(c for c in result.candidates if c.direction == result.best_direction)
    for other in (plus_x, minus_x):
        winner_rank = (_EVIDENCE_TIER_RANK[winner_candidate.evidence_tier], winner_candidate.score)
        other_rank = (_EVIDENCE_TIER_RANK[other.evidence_tier], other.score)
        assert winner_rank <= other_rank


@requires_occ
@requires_dhukkan
def test_dhukkan_plus_z_remains_explainable_post_correction(dhukkan_result):
    result = dhukkan_result
    plus_z = next(c for c in result.candidates if c.label == "+Z")
    assert plus_z.boolean_refined is True
    assert plus_z.evidence_tier != "unverified"


# ---------------------------------------------------------------------------
# H10. Symmetry behavior remains physically sensible.
# ---------------------------------------------------------------------------

@requires_occ
@requires_part1
def test_part1_mirror_pairs_have_identical_draft_but_may_differ_in_confirmed_evidence(part1_result):
    """bad_pct must be IDENTICAL for every mirror pair (draft angle is
    sign-blind by design, untouched by Phase 5B). confirmed_undercut_pct
    MAY legitimately differ between mirror directions (a real part's true
    undercut risk is generally NOT mirror-symmetric) -- this is a sanity
    check that the two signals behave according to their own, different,
    documented symmetry properties, not that everything must match."""
    result = part1_result
    by_label = {c.label: c for c in result.candidates if c.label in
                ("+X", "-X", "+Y", "-Y", "+Z", "-Z")}
    for pos, neg in (("+X", "-X"), ("+Y", "-Y"), ("+Z", "-Z")):
        assert by_label[pos].bad_area_pct == pytest.approx(by_label[neg].bad_area_pct, rel=1e-9)
