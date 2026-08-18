"""
tests/test_direction_optimizer_feature_acceptability.py
---------------------------------------------------------
Phase 5C-3 (Issue #1, D-053), renamed D-054: feature-level undercut
acceptability.

The Phase 5C-3 audit found that `_evidence_tier()`'s aggregate-area-only
rule (`confirmed_undercut_pct <= suitability_max_confirmed_undercut_pct`)
lets a small-but-individually-critical confirmed feature reach
"verified_acceptable" purely because it sits on a large part --
demonstrated concretely by UC4_small_deep_pocket_on_large_plate.stp, which
reuses UC3's own hand-verified 800mm^2/8mm/6400mm^3 confirmed ring
(severity="critical", is_major_feature=True,
recommended_mold_action="draft-redesign-or-local-action-review") but
reads as ~0.9% of UC4's much larger plate instead of UC3's ~13-23%.

D-054 (second investigation, same day): the middle `feature_acceptability`
state was renamed from `"secondary_tooling_required"` to
`"confirmed_undercut_secondary_tooling_candidate"`. `recommended_mold_action`
is a real, evidence-based mechanism-CLASS signal, but it is NOT proof that
a mechanism is feasible, collision-free, actuated, or manufacturable --
even this project's own human-authorized, structurally-validated
`DelegatedSecondaryAction` (D-044) never claims more than
`geometric_verification="unverified"`. The rename is semantic only: the
underlying detection rule, evidence-tier ranking, and
`optimal_found`-eligibility are UNCHANGED from the original Phase 5C-3
implementation.

These tests prove the fix (`_feature_acceptability()`, threaded into
`_evidence_tier()`) using BOTH synthetic UndercutFeature objects (isolating
the exact logical rule) and the real UC3/UC4/Part3 fixtures (proving it
holds on real B-Rep geometry, not just mocks).
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "data" / "fixtures" / "synthetic"
UC3_PATH = FIXTURE_DIR / "UC3_spool_true_undercut.stp"
UC4_PATH = FIXTURE_DIR / "UC4_small_deep_pocket_on_large_plate.stp"

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _occ_available() -> bool:
    try:
        import OCC  # noqa: F401
        return True
    except ImportError:
        return False


requires_occ = pytest.mark.skipif(not _occ_available(), reason="pythonOCC not installed")
requires_uc3 = pytest.mark.skipif(not UC3_PATH.exists(), reason="UC3 fixture not present")
requires_uc4 = pytest.mark.skipif(not UC4_PATH.exists(), reason="UC4 fixture not present")

PULL_Z = (0.0, 0.0, 1.0)


def _make_feature(
    feature_id: int,
    *,
    confirmed: bool,
    severity: str = "critical",
    recommended_mold_action: str = "draft-redesign-or-local-action-review",
    interference_volume_mm3: float = 6400.0,
    depth_proxy_mm: float = 30.0,
    face_ids: list[int] | None = None,
):
    from backend.geometry.undercut_detector import UndercutFeature

    face_ids = face_ids if face_ids is not None else [feature_id]
    return UndercutFeature(
        feature_id=feature_id,
        face_ids=face_ids,
        undercut_type="internal/core-side",
        severity=severity,
        evidence_source="boolean-confirmed" if confirmed else "proxy-only",
        type_classification_method="test",
        type_classification_score=0.9,
        type_classification_factors=[],
        release_direction=(0.0, 0.0, -1.0),
        location=(0.0, 0.0, 0.0),
        depth_proxy_mm=depth_proxy_mm,
        total_area_mm2=800.0,
        min_draft_angle_deg=0.0,
        interference_volume_mm3=interference_volume_mm3,
        boolean_confirmed_face_ids=face_ids if confirmed else [],
        recommended_mold_action=recommended_mold_action,
        side_action_candidate=True,
        action_reason="test feature",
    )


def _make_undercut_result(features):
    from backend.geometry.undercut_detector import UndercutDetectionResult

    return UndercutDetectionResult(
        pull_direction=PULL_Z,
        method="test",
        undercut_face_ids=[],
        accessible_face_ids=[],
        parting_face_ids=[],
        skipped_face_ids=[],
        features=features,
        boolean_refined=True,
    )


# ---------------------------------------------------------------------------
# 1. _feature_acceptability() unit tests -- isolate the exact logical rule.
# ---------------------------------------------------------------------------

def test_no_confirmed_features_is_clean():
    from backend.geometry.direction_optimizer import _feature_acceptability

    result = _make_undercut_result([_make_feature(0, confirmed=False)])
    state, secondary, manual, reason = _feature_acceptability(result)
    assert state == "clean"
    assert secondary == 0
    assert manual == 0
    assert reason == ""


def test_confirmed_feature_with_real_action_is_secondary_tooling_candidate():
    from backend.geometry.direction_optimizer import _feature_acceptability

    result = _make_undercut_result([
        _make_feature(0, confirmed=True, recommended_mold_action="side-action"),
    ])
    state, secondary, manual, reason = _feature_acceptability(result)
    assert state == "confirmed_undercut_secondary_tooling_candidate"
    assert secondary == 1
    assert manual == 0
    assert "feature 0" in reason


def test_confirmed_feature_with_manual_review_action_requires_manual_review():
    from backend.geometry.direction_optimizer import _feature_acceptability

    result = _make_undercut_result([
        _make_feature(0, confirmed=True, recommended_mold_action="manual-review"),
    ])
    state, secondary, manual, reason = _feature_acceptability(result)
    assert state == "requires_manual_review"
    assert manual == 1
    assert "Boolean refinement failed" in reason


def test_manual_review_takes_priority_over_secondary_tooling_when_mixed():
    """One confirmed feature is a real, evidence-based side-action; another
    is a manual-review (unreliable evidence). The unreliable one must
    dominate the classification -- we cannot honestly call a direction a
    "secondary tooling candidate" while any part of the evidence is
    unreliable."""
    from backend.geometry.direction_optimizer import _feature_acceptability

    result = _make_undercut_result([
        _make_feature(0, confirmed=True, recommended_mold_action="side-action", face_ids=[0]),
        _make_feature(1, confirmed=True, recommended_mold_action="manual-review", face_ids=[1]),
    ])
    state, secondary, manual, reason = _feature_acceptability(result)
    assert state == "requires_manual_review"
    assert secondary == 1  # the side-action feature is still counted
    assert manual == 1


def test_worst_feature_by_severity_is_reported_as_the_reason():
    from backend.geometry.direction_optimizer import _feature_acceptability

    result = _make_undercut_result([
        _make_feature(0, confirmed=True, severity="minor", recommended_mold_action="side-action", face_ids=[0]),
        _make_feature(1, confirmed=True, severity="critical", recommended_mold_action="lifter-or-collapsible-core-review", face_ids=[1]),
    ])
    state, secondary, manual, reason = _feature_acceptability(result)
    assert state == "confirmed_undercut_secondary_tooling_candidate"
    assert secondary == 2
    assert "feature 1" in reason
    assert "critical" in reason


# ---------------------------------------------------------------------------
# 2. _evidence_tier() -- proves the UC4 failure mode directly and that the
#    fix corrects it without touching the aggregate-area path.
# ---------------------------------------------------------------------------

def test_small_area_but_critical_feature_no_longer_reaches_verified_acceptable():
    """
    The exact UC4 shape: confirmed_undercut_pct well under the 10%
    threshold (so the OLD area-only rule would have said
    "verified_acceptable"), but feature_acceptability is
    "confirmed_undercut_secondary_tooling_candidate" (a real, confirmed,
    critical feature exists). The fix must reject this combination --
    and, per D-054, a secondary-tooling candidate is NEVER
    optimal_found-eligible on its own, since the geometric evidence
    (recommended_mold_action) is not proof of feasibility.
    """
    from backend.config import settings
    from backend.geometry.direction_optimizer import _evidence_tier

    cfg = settings.dfm.direction_search
    small_area_pct = 0.894  # UC4's actual measured value
    assert small_area_pct <= cfg.suitability_max_confirmed_undercut_pct, (
        "sanity check: this scenario must be one the OLD area-only rule "
        "would have accepted, or this test proves nothing"
    )

    tier = _evidence_tier(
        boolean_refined=True,
        confirmed_undercut_pct=small_area_pct,
        feature_acceptability="confirmed_undercut_secondary_tooling_candidate",
        cfg=cfg,
    )
    assert tier != "verified_acceptable", (
        "pre-fix behavior: this WOULD have been verified_acceptable "
        "because area alone was checked"
    )
    assert tier == "verified_undercuts_present"


def test_genuinely_clean_direction_is_completely_unaffected():
    """0% confirmed area AND feature_acceptability=='clean' must still
    reach verified_acceptable exactly as before this phase -- the fix must
    never downgrade a genuinely clean direction."""
    from backend.config import settings
    from backend.geometry.direction_optimizer import _evidence_tier

    cfg = settings.dfm.direction_search
    tier = _evidence_tier(
        boolean_refined=True,
        confirmed_undercut_pct=0.0,
        feature_acceptability="clean",
        cfg=cfg,
    )
    assert tier == "verified_acceptable"


def test_manual_review_never_reaches_verified_acceptable_even_at_zero_area():
    """A feature whose OWN evidence failed (manual-review) must not be
    silently treated as clean merely because its reported area happens to
    be small/zero."""
    from backend.config import settings
    from backend.geometry.direction_optimizer import _evidence_tier

    cfg = settings.dfm.direction_search
    tier = _evidence_tier(
        boolean_refined=True,
        confirmed_undercut_pct=0.01,
        feature_acceptability="requires_manual_review",
        cfg=cfg,
    )
    assert tier == "verified_undercuts_present"


def test_unverified_still_takes_priority_over_feature_acceptability():
    from backend.config import settings
    from backend.geometry.direction_optimizer import _evidence_tier

    cfg = settings.dfm.direction_search
    tier = _evidence_tier(
        boolean_refined=False,
        confirmed_undercut_pct=0.0,
        feature_acceptability="clean",
        cfg=cfg,
    )
    assert tier == "unverified"


# ---------------------------------------------------------------------------
# 3. Real-geometry regression: UC3 (large-area, already correctly
#    rejected) and UC4 (small-area, the fixed failure mode).
# ---------------------------------------------------------------------------

@requires_occ
@requires_uc4
def test_uc4_real_fixture_no_longer_verified_acceptable():
    """
    UC4_small_deep_pocket_on_large_plate.stp, hand-verified in Phase 5C-0:
    the confirmed ring (800mm^2, 8mm swept depth, 6400mm^3 -- identical to
    UC3's own hand-verified feature) originally read as ~0.89-1.5% of UC4's
    much larger plate, demonstrating a small-area-but-critical feature that
    the OLD aggregate-area-only rule would have wrongly accepted.

    Phase 5D-1 (D-056) update: the bilateral accessibility-risk fix now
    ALSO confirms face 10 -- UC4's entire 39900mm^2 plate-top face, whose
    concave annulus around the stem gap is a genuine cavity-side mirror of
    face 4's own already-proven shelf. Its swept prism hand-verifiably
    intersects the cap over the same 800mm^2/8mm/6400mm^3 overlap (real
    interference, correctly Boolean-confirmed -- not a false positive; see
    /private/tmp scratch verification). Because the CONFIRMED-AREA metric
    attributes a face's ENTIRE area to "confirmed" once any interference is
    found on it (a pre-existing, unchanged whole-face-granularity trait of
    confirmed_undercut_pct -- out of scope for 5D-1 to alter), UC4's
    confirmed_undercut_pct now jumps to ~45%, well ABOVE
    suitability_max_confirmed_undercut_pct. UC4 therefore no longer
    demonstrates the original "small-area-but-critical" failure mode on
    its own area metric alone -- but it still correctly proves that a
    confirmed critical feature blocks verified_acceptable, and
    feature_acceptability remains the mechanism that would catch this
    even if the area happened to be small (as it still does, independent
    of area, per test_small_area_but_critical_feature_no_longer_reaches_
    verified_acceptable's synthetic proof above).
    """
    from backend.geometry.step_loader import load_step
    from backend.geometry.undercut_detector import detect_undercuts
    from backend.geometry.draft_analyzer import analyze_draft
    from backend.geometry.direction_optimizer import _build_refined_candidate
    from backend.config import settings

    part = load_step(str(UC4_PATH))
    cfg = settings.dfm.direction_search
    draft = analyze_draft(part=part, pull_direction=PULL_Z, mutate=False)
    undercuts = detect_undercuts(part, PULL_Z, mutate=False, boolean_refine=True)
    candidate = _build_refined_candidate(PULL_Z, draft, undercuts, part, cfg)

    assert candidate.boolean_refined is True
    # Post-5D-1: face 10 (the plate-top face) is now also genuinely
    # Boolean-confirmed, so the confirmed area is no longer small -- this
    # is a correct, expected consequence of the bilateral fix, not a
    # regression. The invariant this test actually protects
    # (evidence_tier/feature_acceptability rejection) does not depend on
    # which side of the threshold the area falls on.
    assert candidate.evidence_tier != "verified_acceptable", (
        "a confirmed critical feature must never reach verified_acceptable, "
        "regardless of whether the rejection is also independently "
        "explained by the aggregate-area rule"
    )
    assert candidate.evidence_tier == "verified_undercuts_present"
    assert candidate.feature_acceptability == "confirmed_undercut_secondary_tooling_candidate"
    assert candidate.secondary_tooling_feature_count >= 1
    assert candidate.manual_review_feature_count == 0
    assert "critical" in candidate.feature_acceptability_reason
    assert "draft-redesign-or-local-action-review" in candidate.feature_acceptability_reason

    # D-054: not optimal_found-eligible SOLELY because the confirmed area
    # happens to be small -- the tier decision must be driven by
    # feature_acceptability, not by re-checking the area threshold alone.
    optimal_found_equivalent = candidate.evidence_tier == "verified_acceptable"
    assert optimal_found_equivalent is False, (
        "a secondary-tooling candidate must never be reported as a "
        "validated optimum merely because its confirmed area is small"
    )


@requires_occ
@requires_uc3
def test_uc3_real_fixture_reports_feature_acceptability_consistently():
    """
    UC3's own confirmed ring is large enough (13-23% of its smaller body)
    to already fail the aggregate-area check on its own -- this test
    proves the NEW feature_acceptability field is populated consistently
    alongside that pre-existing, unchanged rejection, not that the
    rejection reason changed.
    """
    from backend.geometry.step_loader import load_step
    from backend.geometry.undercut_detector import detect_undercuts
    from backend.geometry.draft_analyzer import analyze_draft
    from backend.geometry.direction_optimizer import _build_refined_candidate
    from backend.config import settings

    part = load_step(str(UC3_PATH))
    cfg = settings.dfm.direction_search
    draft = analyze_draft(part=part, pull_direction=PULL_Z, mutate=False)
    undercuts = detect_undercuts(part, PULL_Z, mutate=False, boolean_refine=True)
    candidate = _build_refined_candidate(PULL_Z, draft, undercuts, part, cfg)

    assert candidate.evidence_tier == "verified_undercuts_present"
    assert candidate.feature_acceptability == "confirmed_undercut_secondary_tooling_candidate"
    assert candidate.secondary_tooling_feature_count >= 1


@requires_occ
@requires_uc3
def test_uc3_clean_principal_axis_still_reports_clean():
    """A principal axis with zero confirmed features on UC3 (e.g. +X,
    perpendicular to the spool's own axis) must still report
    feature_acceptability=="clean" -- proving the fix does not turn every
    direction on a part-with-an-undercut into a rejection."""
    from backend.geometry.step_loader import load_step
    from backend.geometry.undercut_detector import detect_undercuts
    from backend.geometry.draft_analyzer import analyze_draft
    from backend.geometry.direction_optimizer import _build_refined_candidate
    from backend.config import settings

    part = load_step(str(UC3_PATH))
    cfg = settings.dfm.direction_search
    pull_x = (1.0, 0.0, 0.0)
    draft = analyze_draft(part=part, pull_direction=pull_x, mutate=False)
    undercuts = detect_undercuts(part, pull_x, mutate=False, boolean_refine=True)
    candidate = _build_refined_candidate(pull_x, draft, undercuts, part, cfg)

    assert candidate.feature_acceptability == "clean"
    assert candidate.secondary_tooling_feature_count == 0


# ---------------------------------------------------------------------------
# 4. Part3 +Z (D-054 second investigation reference case): direction_
#    optimizer's own undercut evidence at +Z is CLEAN -- all three
#    candidate features there (including face 35, the bore candidate-110
#    later authorizes as a core-pin) are Boolean-NOT-APPLICABLE (coaxial
#    with +Z, near-zero-g, excluded from the sweep per D-046), never
#    Boolean-CONFIRMED. Candidate 110's real secondary-tooling need (core-
#    pin for H3 topological closure, delegation for H4 orientation) comes
#    from parting_line_v2's own H3/H4 gates -- a different geometric
#    question direction_optimizer's undercut detector does not model at
#    all. This test locks in that direction_optimizer's CLEAN
#    classification for Part3 +Z is correct and does not depend on, or
#    conflict with, parting_line_v2's separate core-pin/delegation
#    architecture. No Part3-specific logic exists anywhere in
#    direction_optimizer.py -- this is General fixture verification, not
#    a special case.
# ---------------------------------------------------------------------------

@requires_occ
def test_part3_plus_z_remains_clean_in_direction_optimizer():
    part3_path = REPO_ROOT / "data" / "parts" / "Part3.stp"
    if not part3_path.exists():
        pytest.skip("Part3.stp not present")

    from backend.geometry.step_loader import load_step
    from backend.geometry.undercut_detector import detect_undercuts
    from backend.geometry.draft_analyzer import analyze_draft
    from backend.geometry.direction_optimizer import _build_refined_candidate
    from backend.config import settings

    part = load_step(str(part3_path))
    cfg = settings.dfm.direction_search
    draft = analyze_draft(part=part, pull_direction=PULL_Z, mutate=False)
    undercuts = detect_undercuts(part, PULL_Z, mutate=False, boolean_refine=True)
    candidate = _build_refined_candidate(PULL_Z, draft, undercuts, part, cfg)

    assert candidate.boolean_refined is True
    assert candidate.feature_acceptability == "clean", (
        "direction_optimizer's own undercut evidence at Part3 +Z has no "
        "Boolean-CONFIRMED feature (the bore is coaxial with +Z and "
        "excluded from the sweep as not-applicable, per D-046) -- it is "
        "genuinely clean by this detector's own evidence, independent of "
        "whatever parting_line_v2's separate H3/H4 gates require"
    )
    assert candidate.evidence_tier == "verified_acceptable"
    assert candidate.secondary_tooling_feature_count == 0
    assert candidate.manual_review_feature_count == 0
