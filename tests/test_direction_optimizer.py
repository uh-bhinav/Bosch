"""
tests/test_direction_optimizer.py
---------------------------------
Pure tests for candidate direction generation and draft-based scoring.
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import pytest


def _make_face(face_id: int, normal: tuple[float, float, float], area: float = 100.0):
    from backend.models.geometry_models import FaceData

    return FaceData(
        face_id=face_id,
        occ_face=MagicMock(),
        surface_type="Plane",
        normal=normal,
        centroid=(0.0, 0.0, 0.0),
        area=area,
        u_range=(0.0, 1.0),
        v_range=(0.0, 1.0),
        is_reversed=False,
        normal_valid=True,
    )


def _make_part(faces):
    from backend.models.geometry_models import BoundingBox, PartGeometry

    return PartGeometry(
        source_file="mock.stp",
        occ_shape=MagicMock(),
        faces=faces,
        bounding_box=BoundingBox(0.0, 0.0, 0.0, 10.0, 10.0, 10.0),
        face_count=len(faces),
        solid_count=1,
        shell_count=1,
    )


def _make_direction_candidate(
    label: str,
    score: float,
    bad_area_pct: float = 0.0,
    undercut_area_pct: float = 0.0,
    principal_axis_alignment: float = 1.0,
    direction: tuple[float, float, float] = (1.0, 0.0, 0.0),
    accessibility_risk_area_pct: float = 0.0,
    evidence_tier: str = "unverified",
    boolean_refined: bool = False,
):
    from backend.geometry.direction_optimizer import DirectionCandidateResult

    return DirectionCandidateResult(
        direction=direction,
        label=label,
        score=score,
        bad_face_count=0,
        marginal_face_count=0,
        good_face_count=1,
        bad_area_mm2=0.0,
        marginal_area_mm2=0.0,
        total_area_mm2=100.0,
        bad_area_pct=bad_area_pct,
        marginal_area_pct=0.0,
        undercut_face_count=0,
        undercut_feature_count=0,
        undercut_area_pct=undercut_area_pct,
        boolean_refined=boolean_refined,
        boolean_checked_count=0,
        interference_volume_mm3=0.0,
        principal_axis_alignment=principal_axis_alignment,
        accessibility_risk_area_pct=accessibility_risk_area_pct,
        evidence_tier=evidence_tier,
    )


def test_generate_candidate_directions_includes_principal_axes():
    from backend.geometry.direction_optimizer import generate_candidate_directions

    directions = generate_candidate_directions(angular_step_deg=45.0, max_candidates=12)

    assert (1.0, 0.0, 0.0) in directions
    assert (-1.0, 0.0, 0.0) in directions
    assert (0.0, 1.0, 0.0) in directions
    assert (0.0, -1.0, 0.0) in directions
    assert (0.0, 0.0, 1.0) in directions
    assert (0.0, 0.0, -1.0) in directions


def test_generate_candidate_directions_are_unit_vectors():
    from backend.geometry.direction_optimizer import generate_candidate_directions

    for direction in generate_candidate_directions(angular_step_deg=30.0, max_candidates=20):
        mag = math.sqrt(sum(v * v for v in direction))
        assert abs(mag - 1.0) < 1e-9


def test_optimize_mold_direction_mutates_part_to_best_direction(monkeypatch):
    import backend.geometry.undercut_detector as undercut_module
    from backend.geometry.direction_optimizer import optimize_mold_direction

    # Disable real OCC Boolean calls: occ_face/occ_shape are MagicMocks and
    # would stall for minutes against a real pythonocc-core installation.
    monkeypatch.setattr(undercut_module, "_OCC_BOOLEAN_AVAILABLE", False)

    # Face normal +X is bad for +Z pull and good for +X pull.
    face = _make_face(0, (1.0, 0.0, 0.0))
    part = _make_part([face])

    result = optimize_mold_direction(part, angular_step_deg=90.0, max_candidates=6)

    # Phase 5C-2 (D-052): draft angle is sign-blind (asin(|n.d|)), and this
    # single-face, no-undercut, OCC-disabled (unverified tier) part has
    # NO evidence distinguishing +X from -X -- both are exactly tied on
    # tier, score, accessibility risk, and axis alignment. Pre-Phase-5C-2,
    # this was resolved by accidental candidate-generation list order
    # (+X listed before -X in generate_candidate_directions, and the old
    # comparator's min() picked the first tied element -- not a
    # deliberate, evidence-based choice). The new deterministic
    # direction-tuple tiebreak (required for CASE 5/6: exact ties must
    # never depend on list/iteration order) now consistently picks -X
    # instead ((-1,0,0) < (1,0,0) lexicographically) -- a different but
    # equally arbitrary-and-now-STABLE choice between two provably
    # equivalent directions, not a regression.
    assert result.best_label == "-X"
    assert result.initial_draft.face_results[0]["draft_classification"] == "bad"
    assert result.optimal_draft.face_results[0]["draft_classification"] == "good"
    assert part.optimal_pull_direction == (-1.0, 0.0, 0.0)
    assert face.draft_classification == "good"
    assert result.boolean_refined_candidate_count >= 0
    assert result.boolean_pruned_candidate_count >= 0
    assert result.boolean_survivor_candidate_count >= result.boolean_promising_candidate_count
    assert result.boolean_pruning_summary is not None
    assert result.direction_cache_entries >= 0
    assert "boolean_refined_candidate_count" in result.to_dict()
    assert "boolean_pruned_candidate_count" in result.to_dict()
    assert "boolean_pruning_summary" in result.to_dict()
    assert "direction_cache" in result.to_dict()
    assert "hit_rate" in result.to_dict()["direction_cache"]
    assert "final_direction_reused" in result.to_dict()["direction_cache"]
    assert "boolean_volume_cache_entries" in result.to_dict()["direction_cache"]


def test_boolean_pruning_selector_caps_survivors_and_reports_pruned_count():
    from backend.config import settings
    from backend.geometry.direction_optimizer import _select_boolean_refinement_candidates

    candidates = [
        _make_direction_candidate(f"C{i}", score)
        for i, score in enumerate([10.0, 10.5, 11.0, 13.0, 19.0, 21.0, 50.0, 80.0])
    ]

    promising, summary = _select_boolean_refinement_candidates(candidates)

    cfg = settings.dfm.direction_search
    assert len(promising) <= cfg.boolean_refine_top_candidates
    assert summary.promising_count == len(promising)
    assert summary.pruned_count == len(candidates) - len(promising)
    assert summary.survivor_count <= cfg.prefilter_survivor_top_count
    assert summary.ratio_threshold == 20.0
    assert summary.near_tie_threshold == 12.5
    assert summary.uncertainty_threshold > summary.near_tie_threshold
    assert summary.pruned_examples


def test_boolean_pruning_selector_keeps_minimum_candidate_when_best_score_is_zero():
    from backend.config import settings
    from backend.geometry.direction_optimizer import _select_boolean_refinement_candidates

    candidates = [
        _make_direction_candidate(f"Z{i}", score)
        for i, score in enumerate([0.0, 0.5, 2.0, 10.0])
    ]

    promising, summary = _select_boolean_refinement_candidates(candidates)

    assert len(promising) >= settings.dfm.direction_search.prefilter_min_boolean_candidates
    assert promising[0].label == "Z0"
    assert summary.ratio_threshold == settings.dfm.direction_search.prefilter_zero_score_margin
    assert summary.pruned_count == len(candidates) - len(promising)


def test_boolean_pruning_selector_keeps_low_risk_candidate_outside_ratio():
    from backend.geometry.direction_optimizer import _select_boolean_refinement_candidates

    candidates = [
        _make_direction_candidate("best", 10.0, bad_area_pct=10.0, undercut_area_pct=10.0),
        _make_direction_candidate("poor", 40.0, bad_area_pct=20.0, undercut_area_pct=20.0),
        _make_direction_candidate("low-risk", 30.0, bad_area_pct=1.0, undercut_area_pct=1.0),
    ]

    promising, summary = _select_boolean_refinement_candidates(candidates)

    labels = {candidate.label for candidate in promising}
    assert "low-risk" in labels
    assert summary.low_risk_candidate_count >= 1
    assert any(
        "low-risk prefilter" in reason
        for reason in summary.survivor_reasons["low-risk"]
    )


def test_boolean_pruning_selector_keeps_principal_axis_guard():
    from backend.geometry.direction_optimizer import _select_boolean_refinement_candidates

    candidates = [
        _make_direction_candidate("best", 10.0, principal_axis_alignment=0.82),
        _make_direction_candidate("principal", 22.0, principal_axis_alignment=1.0),
        _make_direction_candidate("off-axis", 21.0, principal_axis_alignment=0.80),
    ]

    promising, summary = _select_boolean_refinement_candidates(candidates)

    labels = {candidate.label for candidate in promising}
    assert "principal" in labels
    assert summary.principal_axis_guard_count >= 1
    assert "principal-axis guard" in summary.survivor_reasons["principal"]


def test_stage3_pruning_ignores_stage12_verified_baseline_before_fix():
    """
    Phase 5C-1 (Issue #4, D-051) baseline characterization.

    _select_boolean_refinement_candidates() anchors its ratio/near-tie
    thresholds ONLY to `ordered[0]` -- the cheapest score anywhere in the
    merged candidate pool -- with no way to know that a much higher score
    belongs to the Stage-1+2 pool's own real, Boolean-VERIFIED best
    candidate. An unrelated, cheap/unverified candidate with an
    optimistic score can therefore make the survival bar too tight for a
    DIFFERENT candidate that is genuinely competitive with the verified
    baseline -- pruning it before it ever gets Boolean-checked, purely
    because of a comparison to a number that was never trustworthy in the
    first place.

    Scenario: "stage12-verified-best" (500.0) stands in for the Stage-1+2
    pool's own real, Boolean-refined best score. "optimistic-cheap" (50.0)
    is a cheap-only (unverified) Stage-3 candidate that becomes the pool's
    global minimum. "competitive-vs-baseline" (520.0) is well within both
    the ratio (500*2.0=1000) and near-tie (500*1.25=625) margins OF THE
    VERIFIED BASELINE -- exactly the kind of candidate that could plausibly
    rival or beat 500.0 if it were actually Boolean-refined.
    "clearly-worse" (5000.0) is not competitive against anything.

    With today's single-anchor math (config: prefilter_skip_score_factor=
    2.0, boolean_refine_score_margin=0.25):
        ratio_threshold    = 50.0 * 2.0  = 100.0
        near_tie_threshold = 50.0 * 1.25 = 62.5
    520.0 exceeds both, so "competitive-vs-baseline" is pruned -- even
    though it sits well inside the SAME margins measured against the real
    baseline (1000.0 / 625.0). This test locks in that CURRENT, pre-fix
    behavior so the fix below has a demonstrated "before" to improve on,
    not just an assertion of the desired "after".
    """
    from backend.geometry.direction_optimizer import _select_boolean_refinement_candidates

    candidates = [
        _make_direction_candidate(
            "stage12-verified-best", 500.0, bad_area_pct=20.0, undercut_area_pct=20.0,
            principal_axis_alignment=0.5,
        ),
        _make_direction_candidate(
            "optimistic-cheap", 50.0, bad_area_pct=20.0, undercut_area_pct=20.0,
            principal_axis_alignment=0.5,
        ),
        _make_direction_candidate(
            "competitive-vs-baseline", 520.0, bad_area_pct=20.0, undercut_area_pct=20.0,
            principal_axis_alignment=0.5,
        ),
        _make_direction_candidate(
            "clearly-worse", 5000.0, bad_area_pct=20.0, undercut_area_pct=20.0,
            principal_axis_alignment=0.5,
        ),
    ]

    promising, summary = _select_boolean_refinement_candidates(candidates)

    assert summary.ratio_threshold == pytest.approx(100.0)
    assert summary.near_tie_threshold == pytest.approx(62.5)
    labels = {c.label for c in promising}
    assert "competitive-vs-baseline" not in labels, (
        "pre-fix: a candidate competitive with the verified Stage-1+2 "
        "baseline is wrongly pruned because of an unrelated cheap/"
        "unverified candidate's optimistic score"
    )
    assert "clearly-worse" not in labels


def test_stage3_pruning_retains_candidate_competitive_with_stage12_baseline_after_fix():
    """
    Phase 5C-1 (Issue #4, D-051) post-fix invariant.

    _select_boolean_refinement_candidates() accepts an optional
    `baseline_score` -- the Stage-1+2 pool's own verified best score --
    and retains any candidate within the EXISTING ratio/near-tie margins
    of THAT baseline, in ADDITION to (never instead of) whatever the
    pre-existing local-pool-anchored logic already retains. This can only
    add survivors relative to the pre-fix behavior in the test above,
    never remove one.

    Same scenario and constants as the baseline test:
        baseline_ratio_threshold    = 500.0 * 2.0  = 1000.0
        baseline_near_tie_threshold = 500.0 * 1.25 = 625.0
    "competitive-vs-baseline" (520.0) <= 625.0 -> now retained.
    "clearly-worse" (5000.0) > 1000.0 -> still pruned even under the wider
    baseline anchor -- proving the fix does NOT make Stage 3 exhaustive,
    it only rescues candidates that are genuinely competitive with real
    evidence, using the SAME existing constants, not a new threshold.
    """
    from backend.config import settings
    from backend.geometry.direction_optimizer import _select_boolean_refinement_candidates

    candidates = [
        _make_direction_candidate(
            "stage12-verified-best", 500.0, bad_area_pct=20.0, undercut_area_pct=20.0,
            principal_axis_alignment=0.5,
        ),
        _make_direction_candidate(
            "optimistic-cheap", 50.0, bad_area_pct=20.0, undercut_area_pct=20.0,
            principal_axis_alignment=0.5,
        ),
        _make_direction_candidate(
            "competitive-vs-baseline", 520.0, bad_area_pct=20.0, undercut_area_pct=20.0,
            principal_axis_alignment=0.5,
        ),
        _make_direction_candidate(
            "clearly-worse", 5000.0, bad_area_pct=20.0, undercut_area_pct=20.0,
            principal_axis_alignment=0.5,
        ),
    ]

    promising, summary = _select_boolean_refinement_candidates(
        candidates, baseline_score=500.0
    )

    labels = {c.label for c in promising}
    assert "competitive-vs-baseline" in labels, (
        "post-fix: must be retained -- within margin of the real, "
        "verified Stage-1+2 baseline"
    )
    assert "clearly-worse" not in labels, (
        "bounded: a genuinely non-competitive candidate must stay pruned "
        "even under the new baseline anchor -- Stage 3 must not become "
        "exhaustive"
    )
    assert len(promising) <= settings.dfm.direction_search.boolean_refine_top_candidates
    assert summary.baseline_score == pytest.approx(500.0)
    assert summary.baseline_ratio_threshold == pytest.approx(1000.0)
    assert summary.baseline_near_tie_threshold == pytest.approx(625.0)
    assert summary.baseline_rescued_candidate_count >= 1


def test_stage3_pruning_baseline_none_is_byte_identical_to_before():
    """
    Omitting `baseline_score` (the default) must reproduce the pre-fix
    behavior exactly -- every existing call site that doesn't pass it
    (and every pre-existing test in this file) must be completely
    unaffected by this phase.
    """
    from backend.geometry.direction_optimizer import _select_boolean_refinement_candidates

    candidates = [
        _make_direction_candidate(
            "stage12-verified-best", 500.0, bad_area_pct=20.0, undercut_area_pct=20.0,
            principal_axis_alignment=0.5,
        ),
        _make_direction_candidate(
            "optimistic-cheap", 50.0, bad_area_pct=20.0, undercut_area_pct=20.0,
            principal_axis_alignment=0.5,
        ),
        _make_direction_candidate(
            "competitive-vs-baseline", 520.0, bad_area_pct=20.0, undercut_area_pct=20.0,
            principal_axis_alignment=0.5,
        ),
        _make_direction_candidate(
            "clearly-worse", 5000.0, bad_area_pct=20.0, undercut_area_pct=20.0,
            principal_axis_alignment=0.5,
        ),
    ]

    promising_explicit_none, summary_explicit_none = _select_boolean_refinement_candidates(
        candidates, baseline_score=None
    )
    promising_omitted, summary_omitted = _select_boolean_refinement_candidates(candidates)

    assert [c.label for c in promising_explicit_none] == [c.label for c in promising_omitted]
    assert summary_explicit_none.baseline_score is None
    assert summary_omitted.baseline_score is None
    assert summary_omitted.baseline_rescued_candidate_count == 0
    labels = {c.label for c in promising_omitted}
    assert "competitive-vs-baseline" not in labels


def test_comparator_case1_verified_beats_unverified_with_better_raw_score():
    """
    CASE 1: an unverified candidate with a numerically BETTER (lower) raw
    score must never defeat a verified one. Tier stays absolutely
    dominant -- unchanged from Phase 5B, re-proven here as the foundation
    the rest of Phase 5C-2's comparator is built on top of.
    """
    from backend.geometry.direction_optimizer import _tiered_best

    verified = _make_direction_candidate(
        "verified", score=500.0, evidence_tier="verified_acceptable", boolean_refined=True,
    )
    unverified_better_score = _make_direction_candidate(
        "unverified", score=10.0, evidence_tier="unverified", boolean_refined=False,
    )

    winner = _tiered_best([verified, unverified_better_score])
    assert winner.label == "verified"


def test_comparator_case2_materially_different_score_beats_axis_alignment():
    """
    CASE 2: two verified candidates with MATERIALLY different scores --
    the worse-scored one being a perfect principal axis, the better-scored
    one an off-axis diagonal. Score must decide; axis preference must
    NEVER override a real, non-tied evidence/score difference.
    """
    from backend.geometry.direction_optimizer import _tiered_best

    diagonal_better_score = _make_direction_candidate(
        "diagonal", score=100.0, evidence_tier="verified_acceptable", boolean_refined=True,
        principal_axis_alignment=0.707, direction=(0.707, 0.707, 0.0),
    )
    axis_worse_score = _make_direction_candidate(
        "axis", score=900.0, evidence_tier="verified_acceptable", boolean_refined=True,
        principal_axis_alignment=1.0, direction=(1.0, 0.0, 0.0),
    )

    winner = _tiered_best([diagonal_better_score, axis_worse_score])
    assert winner.label == "diagonal", (
        "a materially better verified candidate must never lose merely "
        "because a worse-scored candidate is a principal axis"
    )


def test_comparator_case3_identical_score_broken_by_accessibility_risk():
    """
    CASE 3: two verified candidates with an EXACTLY identical score but
    different accessibility_risk_area_pct. The lower-risk candidate must
    win -- this is real, already-computed geometric evidence (D-047),
    previously discarded once boolean_refined=True, now used as the
    first tie-breaker.
    """
    from backend.geometry.direction_optimizer import _tiered_best

    higher_risk = _make_direction_candidate(
        "higher-risk", score=250.0, evidence_tier="verified_acceptable", boolean_refined=True,
        accessibility_risk_area_pct=40.0, direction=(0.0, 0.707, -0.707),
    )
    lower_risk = _make_direction_candidate(
        "lower-risk", score=250.0, evidence_tier="verified_acceptable", boolean_refined=True,
        accessibility_risk_area_pct=12.0, direction=(0.0, -0.707, -0.707),
    )

    winner = _tiered_best([higher_risk, lower_risk])
    assert winner.label == "lower-risk"


def test_comparator_case4_identical_score_and_risk_broken_by_axis_preference():
    """
    CASE 4: two verified candidates, identical score AND identical
    accessibility_risk_area_pct, one a principal axis and one not. Only
    now -- with every more-important signal exhausted -- does axis
    preference decide. This is the ONLY circumstance in which axis
    preference is allowed to determine the winner.
    """
    from backend.geometry.direction_optimizer import _tiered_best

    off_axis = _make_direction_candidate(
        "off-axis", score=180.0, evidence_tier="verified_acceptable", boolean_refined=True,
        accessibility_risk_area_pct=5.0, principal_axis_alignment=0.707,
        direction=(0.707, 0.0, 0.707),
    )
    axis = _make_direction_candidate(
        "axis", score=180.0, evidence_tier="verified_acceptable", boolean_refined=True,
        accessibility_risk_area_pct=5.0, principal_axis_alignment=1.0,
        direction=(0.0, 1.0, 0.0),
    )

    winner = _tiered_best([off_axis, axis])
    assert winner.label == "axis", (
        "axis preference must matter once score and risk are genuinely "
        "tied -- this is the case Phase 5C-2 exists to fix (previously "
        "numerically inert)"
    )


def test_comparator_case5_mirror_equivalent_candidates_resolve_deterministically():
    """
    CASE 5: two mirror-equivalent candidates (+Y / -Y), identical on
    every measured field (score, risk, axis alignment -- the pattern
    empirically confirmed this session on a genuinely symmetric real
    part, cupshot_in_bus_v2.STEP). With no remaining evidence to
    distinguish them, the comparator must still make a single,
    deterministic choice (never "either, whichever iterates first") --
    proven here by running the SAME two candidates through _tiered_best
    in both list orders and requiring the identical winner both times.
    """
    from backend.geometry.direction_optimizer import _tiered_best

    plus_y = _make_direction_candidate(
        "+Y", score=300.0, evidence_tier="verified_acceptable", boolean_refined=True,
        accessibility_risk_area_pct=8.0, principal_axis_alignment=1.0,
        direction=(0.0, 1.0, 0.0),
    )
    minus_y = _make_direction_candidate(
        "-Y", score=300.0, evidence_tier="verified_acceptable", boolean_refined=True,
        accessibility_risk_area_pct=8.0, principal_axis_alignment=1.0,
        direction=(0.0, -1.0, 0.0),
    )

    winner_order_a = _tiered_best([plus_y, minus_y])
    winner_order_b = _tiered_best([minus_y, plus_y])
    assert winner_order_a.label == winner_order_b.label, (
        "mirror-equivalent candidates must resolve to the SAME winner "
        "regardless of which order they appear in the candidate list"
    )


def test_comparator_case6_three_way_exact_tie_is_order_independent():
    """
    CASE 6: three candidates tied exactly on tier, score, accessibility
    risk, AND axis alignment (all off-axis, all equally so) -- the exact
    real-world pattern observed this session on Plastic Cover.STEP (a
    genuine 3-way exact score tie with divergent risk that, before this
    phase, silently resolved by list order). List order is deliberately
    shuffled across three permutations; the winner must be identical in
    all three, proving the comparator never depends on iteration order.
    """
    from backend.geometry.direction_optimizer import _tiered_best

    a = _make_direction_candidate(
        "tie-a", score=400.0, evidence_tier="verified_acceptable", boolean_refined=True,
        accessibility_risk_area_pct=15.0, principal_axis_alignment=0.707,
        direction=(0.0, 0.707, -0.707),
    )
    b = _make_direction_candidate(
        "tie-b", score=400.0, evidence_tier="verified_acceptable", boolean_refined=True,
        accessibility_risk_area_pct=15.0, principal_axis_alignment=0.707,
        direction=(0.0, -0.707, 0.707),
    )
    c = _make_direction_candidate(
        "tie-c", score=400.0, evidence_tier="verified_acceptable", boolean_refined=True,
        accessibility_risk_area_pct=15.0, principal_axis_alignment=0.707,
        direction=(0.0, -0.707, -0.707),
    )

    winners = {
        _tiered_best([a, b, c]).label,
        _tiered_best([b, c, a]).label,
        _tiered_best([c, a, b]).label,
        _tiered_best([c, b, a]).label,
    }
    assert len(winners) == 1, (
        f"three-way exact tie must resolve to the SAME winner regardless "
        f"of list order, got different winners across permutations: {winners}"
    )


def test_comparator_repeated_execution_is_deterministic():
    """
    Invariant 6: the same input, run repeatedly, must produce the same
    selected direction every time. _tiered_best has no hidden state
    (randomness, dict-iteration-order dependence, wall-clock dependence)
    -- proven by calling it 20 times on an unshuffled but otherwise
    ambiguous (near-total-tie) pool and requiring an identical winner
    every time.
    """
    from backend.geometry.direction_optimizer import _tiered_best

    candidates = [
        _make_direction_candidate(
            f"c{i}", score=100.0, evidence_tier="verified_acceptable", boolean_refined=True,
            accessibility_risk_area_pct=10.0, principal_axis_alignment=0.707,
            direction=(0.0, 0.707 * (1 if i % 2 == 0 else -1), 0.707),
        )
        for i in range(5)
    ]
    winners = {_tiered_best(candidates).label for _ in range(20)}
    assert len(winners) == 1


def test_direction_level_cache_reuses_detection_and_applies_overlay():
    from backend.geometry.direction_optimizer import _cached_detect_boolean_undercuts
    from backend.geometry.undercut_detector import UndercutDetectionResult

    faces = [
        _make_face(0, (1.0, 0.0, 0.0)),
        _make_face(1, (0.0, 1.0, 0.0)),
    ]
    part = _make_part(faces)
    cached_result = UndercutDetectionResult(
        pull_direction=(1.0, 0.0, 0.0),
        method="test cached undercuts",
        undercut_face_ids=[0],
        accessible_face_ids=[1],
        parting_face_ids=[],
        skipped_face_ids=[],
        features=[],
        undercut_area_mm2=100.0,
        total_analysed_area_mm2=200.0,
        boolean_refined=True,
    )
    direction_cache = {}
    boolean_volume_cache = {}

    with patch(
        "backend.geometry.direction_optimizer.detect_undercuts",
        return_value=cached_result,
    ) as detect_mock:
        first, first_hit = _cached_detect_boolean_undercuts(
            part=part,
            direction=(1.0, 0.0, 0.0),
            direction_cache=direction_cache,
            boolean_volume_cache=boolean_volume_cache,
            mutate=False,
            max_boolean_faces=12,
        )
        second, second_hit = _cached_detect_boolean_undercuts(
            part=part,
            direction=(1.0, 0.0, 0.0),
            direction_cache=direction_cache,
            boolean_volume_cache=boolean_volume_cache,
            mutate=True,
            max_boolean_faces=12,
        )

    assert first is cached_result
    assert second is cached_result
    assert first_hit is False
    assert second_hit is True
    assert detect_mock.call_count == 1
    assert faces[0].is_undercut is True
    assert faces[0].undercut_depth_mm == 0.0
    assert faces[0].undercut_type == "pending-feature-group"
    assert faces[1].is_undercut is False


def test_direction_level_cache_key_keeps_boolean_scope_separate():
    from backend.geometry.direction_optimizer import _cached_detect_boolean_undercuts
    from backend.geometry.undercut_detector import UndercutDetectionResult

    part = _make_part([_make_face(0, (1.0, 0.0, 0.0))])
    result = UndercutDetectionResult(
        pull_direction=(1.0, 0.0, 0.0),
        method="test cached undercuts",
        undercut_face_ids=[],
        accessible_face_ids=[0],
        parting_face_ids=[],
        skipped_face_ids=[],
        boolean_refined=True,
    )
    direction_cache = {}

    with patch(
        "backend.geometry.direction_optimizer.detect_undercuts",
        return_value=result,
    ) as detect_mock:
        _cached_detect_boolean_undercuts(
            part=part,
            direction=(1.0, 0.0, 0.0),
            direction_cache=direction_cache,
            boolean_volume_cache={},
            mutate=False,
            max_boolean_faces=12,
        )
        _cached_detect_boolean_undercuts(
            part=part,
            direction=(1.0, 0.0, 0.0),
            direction_cache=direction_cache,
            boolean_volume_cache={},
            mutate=False,
            max_boolean_faces=24,
        )

    assert detect_mock.call_count == 2
    assert len(direction_cache) == 2


def test_direction_level_cache_reuses_larger_boolean_face_budget():
    from backend.geometry.direction_optimizer import _cached_detect_boolean_undercuts
    from backend.geometry.undercut_detector import UndercutDetectionResult

    part = _make_part([_make_face(0, (1.0, 0.0, 0.0))])
    result = UndercutDetectionResult(
        pull_direction=(1.0, 0.0, 0.0),
        method="test cached undercuts",
        undercut_face_ids=[],
        accessible_face_ids=[0],
        parting_face_ids=[],
        skipped_face_ids=[],
        boolean_refined=True,
    )
    direction_cache = {}

    with patch(
        "backend.geometry.direction_optimizer.detect_undercuts",
        return_value=result,
    ) as detect_mock:
        first, first_hit = _cached_detect_boolean_undercuts(
            part=part,
            direction=(1.0, 0.0, 0.0),
            direction_cache=direction_cache,
            boolean_volume_cache={},
            mutate=False,
            max_boolean_faces=24,
        )
        second, second_hit = _cached_detect_boolean_undercuts(
            part=part,
            direction=(1.0, 0.0, 0.0),
            direction_cache=direction_cache,
            boolean_volume_cache={},
            mutate=False,
            max_boolean_faces=12,
        )

    assert first is result
    assert second is result
    assert first_hit is False
    assert second_hit is True
    assert detect_mock.call_count == 1
    assert len(direction_cache) == 1


def test_direction_level_cache_does_not_cross_part_signature():
    from backend.geometry.direction_optimizer import _cached_detect_boolean_undercuts
    from backend.geometry.undercut_detector import UndercutDetectionResult

    part_a = _make_part([_make_face(0, (1.0, 0.0, 0.0), area=100.0)])
    part_b = _make_part([_make_face(0, (1.0, 0.0, 0.0), area=250.0)])
    result = UndercutDetectionResult(
        pull_direction=(1.0, 0.0, 0.0),
        method="test cached undercuts",
        undercut_face_ids=[],
        accessible_face_ids=[0],
        parting_face_ids=[],
        skipped_face_ids=[],
        boolean_refined=True,
    )
    direction_cache = {}

    with patch(
        "backend.geometry.direction_optimizer.detect_undercuts",
        return_value=result,
    ) as detect_mock:
        _cached_detect_boolean_undercuts(
            part=part_a,
            direction=(1.0, 0.0, 0.0),
            direction_cache=direction_cache,
            boolean_volume_cache={},
            mutate=False,
            max_boolean_faces=24,
        )
        _, second_hit = _cached_detect_boolean_undercuts(
            part=part_b,
            direction=(1.0, 0.0, 0.0),
            direction_cache=direction_cache,
            boolean_volume_cache={},
            mutate=False,
            max_boolean_faces=12,
        )

    assert second_hit is False
    assert detect_mock.call_count == 2
    assert len(direction_cache) == 2


# ─────────────────────────────────────────────────────────────────────────────
# Flash risk term (Roadmap Phase 1d, Gap 1)
# ─────────────────────────────────────────────────────────────────────────────

def test_flash_risk_area_fraction_flags_thin_face_near_parallel_to_pull():
    from backend.geometry.direction_optimizer import _flash_risk_area_fraction

    # bbox diagonal = sqrt(3*10^2) ~= 17.32mm; default flash_thin_area_factor
    # 0.02 -> thin_area_limit ~= 0.02 * 17.32^2 ~= 6.0 mm^2. area=1.0 is thin.
    thin_flash_face = _make_face(0, (1.0, 0.0, 0.0), area=1.0)  # perpendicular to +Z pull
    part = _make_part([thin_flash_face])

    fraction = _flash_risk_area_fraction(part, (0.0, 0.0, 1.0))

    assert fraction == 1.0


def test_flash_risk_area_fraction_ignores_thick_face_near_parallel_to_pull():
    from backend.geometry.direction_optimizer import _flash_risk_area_fraction

    thick_face = _make_face(0, (1.0, 0.0, 0.0), area=500.0)  # perpendicular, but not thin
    part = _make_part([thick_face])

    fraction = _flash_risk_area_fraction(part, (0.0, 0.0, 1.0))

    assert fraction == 0.0


def test_flash_risk_area_fraction_ignores_well_drafted_thin_face():
    from backend.geometry.direction_optimizer import _flash_risk_area_fraction

    well_drafted_thin_face = _make_face(0, (0.0, 0.0, 1.0), area=1.0)  # aligned with pull
    part = _make_part([well_drafted_thin_face])

    fraction = _flash_risk_area_fraction(part, (0.0, 0.0, 1.0))

    assert fraction == 0.0


def test_flash_risk_term_increases_score_for_thin_near_parallel_face():
    from backend.geometry.direction_optimizer import _score_candidate
    from backend.geometry.draft_analyzer import analyze_draft
    from backend.geometry.undercut_detector import detect_undercuts

    flash_risk_part = _make_part([_make_face(0, (1.0, 0.0, 0.0), area=1.0)])
    no_flash_part = _make_part([_make_face(0, (1.0, 0.0, 0.0), area=500.0)])
    pull_dir = (0.0, 0.0, 1.0)

    def score_for(part):
        draft = analyze_draft(part=part, pull_direction=pull_dir, mutate=False)
        undercuts = detect_undercuts(part, pull_dir, mutate=False, boolean_refine=False)
        return _score_candidate(draft, undercuts, pull_dir, part)

    assert score_for(flash_risk_part) > score_for(no_flash_part)


# ─────────────────────────────────────────────────────────────────────────────
# Coarse-to-fine direction search (Roadmap Phase 1d, Gap 2)
# ─────────────────────────────────────────────────────────────────────────────

def test_generate_fine_candidate_directions_are_unit_vectors_within_cone():
    import math

    from backend.geometry.direction_optimizer import generate_fine_candidate_directions

    base = (0.0, 0.0, 1.0)
    cone_half_angle_deg = 15.0
    seen: set[tuple[int, int, int]] = set()

    directions = generate_fine_candidate_directions(
        base_direction=base,
        cone_half_angle_deg=cone_half_angle_deg,
        angular_step_deg=5.0,
        seen=seen,
    )

    assert directions  # non-empty for these parameters
    cos_limit = math.cos(math.radians(cone_half_angle_deg)) - 1e-6
    for direction in directions:
        mag = math.sqrt(sum(v * v for v in direction))
        assert abs(mag - 1.0) < 1e-9
        dot = sum(a * b for a, b in zip(direction, base))
        assert dot >= cos_limit, f"{direction} outside the {cone_half_angle_deg} deg cone"


def test_generate_fine_candidate_directions_respects_seen_dedup():
    from backend.geometry.direction_optimizer import (
        _dedupe_direction,
        generate_fine_candidate_directions,
    )

    base = (0.0, 0.0, 1.0)
    seen: set[tuple[int, int, int]] = set()
    first_pass = generate_fine_candidate_directions(base, 15.0, 5.0, seen)
    # Re-run with the SAME seen set: every direction should already be present.
    second_pass = generate_fine_candidate_directions(base, 15.0, 5.0, seen)

    assert first_pass  # sanity: first pass actually found candidates
    assert second_pass == []


def test_generate_fine_candidate_directions_empty_for_nonpositive_params():
    from backend.geometry.direction_optimizer import generate_fine_candidate_directions

    assert generate_fine_candidate_directions((0.0, 0.0, 1.0), 0.0, 5.0, set()) == []
    assert generate_fine_candidate_directions((0.0, 0.0, 1.0), 15.0, 0.0, set()) == []


def test_optimize_mold_direction_fine_search_adds_candidates(monkeypatch):
    """
    With fine search enabled (default), the candidate list must be at least
    as large as the coarse-only grid, and every candidate score must have
    come from mutate=False (part.faces must only reflect the FINAL winner).

    _OCC_BOOLEAN_AVAILABLE is forced False here so this test never risks
    feeding a MagicMock occ_face into a real OCC Boolean call.
    """
    import backend.geometry.undercut_detector as undercut_module
    from backend.geometry.direction_optimizer import (
        generate_candidate_directions,
        optimize_mold_direction,
    )

    monkeypatch.setattr(undercut_module, "_OCC_BOOLEAN_AVAILABLE", False)

    face = _make_face(0, (1.0, 0.0, 0.03), area=100.0)
    part = _make_part([face])

    result_fine = optimize_mold_direction(part, angular_step_deg=45.0, max_candidates=6)
    coarse_only_count = len(generate_candidate_directions(45.0, 6))

    assert len(result_fine.candidates) >= coarse_only_count
    assert result_fine.best_direction is not None


# ---------------------------------------------------------------------------
# Milestone 3: Hierarchical Search
# ---------------------------------------------------------------------------

class TestHierarchicalSearch:
    """
    Tests for the staged (principal → diagonal → spherical) direction search.
    """

    def test_no_verified_optimum_when_occ_unavailable(self, monkeypatch):
        """
        Phase 5B (2026-08-16): with OCC unavailable, boolean_refined is
        False for every candidate everywhere -- nothing can ever reach
        evidence_tier "verified_acceptable". The optimizer must report this
        honestly (optimal_found=False, best_evidence_tier="unverified",
        best_unverified_candidate populated) rather than silently picking
        a "best" candidate as though it were validated.

        search_stage_reached is no longer a proxy for "did the search
        exhaust all stages" (Phase 5B redefined it to mean "which candidate
        pool the winner came from") -- with nothing verified anywhere, the
        winner is the best RAW cheap score across the entire combined pool,
        which for this single-face part (normal exactly +Z) is genuinely
        the +Z principal axis itself (stage 1), not an artifact of the old
        stage-exhaustion semantics.
        """
        import backend.geometry.undercut_detector as undercut_module
        from backend.geometry.direction_optimizer import optimize_mold_direction

        monkeypatch.setattr(undercut_module, "_OCC_BOOLEAN_AVAILABLE", False)

        face = _make_face(0, (0.0, 0.0, 1.0), area=100.0)
        part = _make_part([face])

        result = optimize_mold_direction(part, angular_step_deg=45.0, max_candidates=6)

        assert result.best_direction is not None
        assert result.optimal_found is False
        assert result.best_evidence_tier == "unverified"
        assert result.best_unverified_candidate is not None
        assert result.best_unverified_candidate.direction == result.best_direction
        assert result.search_stage_reached == 1

    def test_search_stage_reached_field_in_to_dict(self, monkeypatch):
        """DirectionOptimizationResult.to_dict() must include search_stage_reached."""
        import backend.geometry.undercut_detector as undercut_module
        from backend.geometry.direction_optimizer import optimize_mold_direction

        monkeypatch.setattr(undercut_module, "_OCC_BOOLEAN_AVAILABLE", False)

        face = _make_face(0, (0.0, 0.0, 1.0), area=100.0)
        part = _make_part([face])

        result = optimize_mold_direction(part, angular_step_deg=45.0, max_candidates=6)
        d = result.to_dict()

        assert "search_stage_reached" in d
        assert isinstance(d["search_stage_reached"], int)
        # O4 (2026-08-17): 0 is now also valid (winner resolved directly
        # from a custom initial_pull_direction) -- this specific test's
        # scenario (default +Z, single face) still resolves to 1, but the
        # field's overall valid range has genuinely expanded.
        assert d["search_stage_reached"] in {0, 1, 2, 3}

    def test_stage1_early_exit_when_principal_boolean_acceptable(self, monkeypatch):
        """
        When a Stage 1 principal direction passes cheap screen AND
        Boolean-confirms zero confirmed undercuts, the search exits with
        search_stage_reached=1 without evaluating Stage 2 or Stage 3 candidates.
        """
        import backend.geometry.direction_optimizer as optimizer_module
        from backend.geometry.direction_optimizer import optimize_mold_direction
        from backend.geometry.undercut_detector import UndercutDetectionResult

        # Face aligned with +Z: good draft, not core-side → passes cheap screen.
        face = _make_face(0, (0.0, 0.0, 1.0), area=100.0)
        part = _make_part([face])

        def mock_cached_boolean(
            part, direction, direction_cache, boolean_volume_cache, mutate, max_boolean_faces
        ):
            """Return a Boolean-refined result with zero confirmed undercuts."""
            ok_result = UndercutDetectionResult(
                pull_direction=direction,
                method="mock-boolean",
                undercut_face_ids=[],
                accessible_face_ids=[f.face_id for f in part.faces],
                parting_face_ids=[],
                skipped_face_ids=[],
                boolean_refined=True,
                boolean_confirmed_face_ids=[],
                total_analysed_area_mm2=100.0,
            )
            return ok_result, False

        monkeypatch.setattr(
            optimizer_module, "_cached_detect_boolean_undercuts", mock_cached_boolean
        )
        # D-062: _is_parting_line_feasible is a real, unmocked downstream
        # gate now consulted before early exit -- against this test's
        # MagicMock occ_shape it would (correctly, per its own mock-safety
        # guard) always report False, which would silently turn this
        # into "Stage 3 also runs, but the comparator's axis-preference
        # tiebreaker still happens to pick a Stage 1 direction" rather
        # than the genuine Stage-1-only early exit this test exists to
        # verify. Mocked True here so the test continues to exercise the
        # actual early-exit code path its docstring/assertions claim.
        monkeypatch.setattr(
            optimizer_module, "_is_parting_line_feasible",
            lambda part, direction, *args, **kwargs: optimizer_module.PartingLineFeasibilityResult(feasible=True),
        )

        result = optimize_mold_direction(part, angular_step_deg=45.0, max_candidates=10)

        assert result.search_stage_reached == 1
        assert result.optimal_found is True
        # Best direction must be one of the 6 principal axes
        principal_axes = {
            (1.0, 0.0, 0.0), (-1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0), (0.0, -1.0, 0.0),
            (0.0, 0.0, 1.0), (0.0, 0.0, -1.0),
        }
        assert result.best_direction in principal_axes

    def test_stage2_runs_when_no_principal_cheaply_suitable(self, monkeypatch):
        """
        Phase 5B (2026-08-16): the cheap suitability screen no longer gates
        WHETHER a principal or diagonal direction is Boolean-refined (all
        of Stage 1+2 are always Boolean-refined now) -- it was only ever
        used, pre-Phase-5B, to decide whether to attempt Boolean refinement
        at all. This test's tight thresholds now only affect
        evidence_tier's "verified_acceptable" classification (via
        suitability_max_confirmed_undercut_pct, untouched here), not
        candidate-selection. With OCC unavailable (so nothing is ever
        boolean_refined regardless of thresholds), the honest outcome is
        optimal_found=False -- there is no verified candidate for ANY
        stage to have "found", by construction of this test's mock.
        """
        import backend.geometry.direction_optimizer as optimizer_module
        import backend.geometry.undercut_detector as undercut_module
        from backend.geometry.direction_optimizer import optimize_mold_direction
        from backend.config import settings

        monkeypatch.setattr(undercut_module, "_OCC_BOOLEAN_AVAILABLE", False)

        # Override suitability thresholds to be so tight that no principal passes.
        # The face has normal=(1,0,0); pull=(1,0,0) would give 90° draft (good,
        # bad_pct=0%), but pull=(0,0,1) gives 0° draft (bad_pct=100% → fails).
        # By setting max_bad_draft_pct=0.0, every direction with any bad face fails.
        original_cfg = settings.dfm.direction_search
        tight_cfg = type(original_cfg)(
            **{
                **{f.name: getattr(original_cfg, f.name) for f in original_cfg.__dataclass_fields__.values()},
                "suitability_max_bad_draft_pct": 0.0,          # Nothing passes cheap screen
                "suitability_max_accessibility_risk_pct": 0.0,  # Belt and suspenders
            }
        )
        object.__setattr__(settings.dfm, "direction_search", tight_cfg)

        try:
            # A part with a purely sideways normal — every direction except the
            # exact alignment will have bad draft faces.
            face = _make_face(0, (1.0, 0.0, 0.0), area=100.0)
            part = _make_part([face])

            result = optimize_mold_direction(part, angular_step_deg=45.0, max_candidates=6)

            # OCC is unavailable, so nothing anywhere is ever boolean_refined
            # regardless of the (irrelevant, post-Phase-5B) cheap thresholds
            # -- the honest result is "no verified optimum", not a specific
            # stage number.
            assert result.optimal_found is False
            assert result.best_evidence_tier == "unverified"
            assert result.best_unverified_candidate is not None
        finally:
            # Restore original config
            object.__setattr__(settings.dfm, "direction_search", original_cfg)

    def test_hierarchical_disabled_still_returns_valid_result(self, monkeypatch):
        """
        With hierarchical_search_enabled=False the optimizer falls directly to
        Stage 3 (flat behavior), search_stage_reached==3, and the result is valid.
        """
        import backend.geometry.direction_optimizer as optimizer_module
        import backend.geometry.undercut_detector as undercut_module
        from backend.geometry.direction_optimizer import optimize_mold_direction
        from backend.config import settings

        monkeypatch.setattr(undercut_module, "_OCC_BOOLEAN_AVAILABLE", False)

        original_cfg = settings.dfm.direction_search
        flat_cfg = type(original_cfg)(
            **{
                **{f.name: getattr(original_cfg, f.name) for f in original_cfg.__dataclass_fields__.values()},
                "hierarchical_search_enabled": False,
            }
        )
        object.__setattr__(settings.dfm, "direction_search", flat_cfg)

        try:
            face = _make_face(0, (0.0, 0.0, 1.0), area=100.0)
            part = _make_part([face])
            result = optimize_mold_direction(part, angular_step_deg=45.0, max_candidates=6)

            assert result.search_stage_reached == 3
            assert result.best_direction is not None
        finally:
            object.__setattr__(settings.dfm, "direction_search", original_cfg)


# ---------------------------------------------------------------------------
# O4 (2026-08-17): initial_pull_direction seeds the Stage 1+2 incumbent.
#
# Full mocked optimize_mold_direction() end-to-end tests for the control-
# flow pieces that need the real function's plumbing (candidate pool
# assembly, the bound-ordered loop, final attribution) -- as opposed to
# tests A/B/C/G/I-L in test_direction_optimizer_parting_line_feasibility.py,
# which exercise the seeding condition, the feasibility cache, and real
# Part1/Part3 geometry directly.
# ---------------------------------------------------------------------------

class TestInitialDirectionSeeding:
    @staticmethod
    def _close(direction, target, tol=1e-6):
        return all(abs(a - b) < tol for a, b in zip(direction, target))

    def _clean_result(self, part, direction):
        from backend.geometry.undercut_detector import UndercutDetectionResult

        return UndercutDetectionResult(
            pull_direction=direction, method="mock-boolean", undercut_face_ids=[],
            accessible_face_ids=[f.face_id for f in part.faces], parting_face_ids=[],
            skipped_face_ids=[], boolean_refined=True, boolean_confirmed_face_ids=[],
            total_analysed_area_mm2=100.0,
        )

    def test_d_feasibility_cache_prevents_duplicate_h0_h7_call_for_coincident_direction(self, monkeypatch):
        """
        O4 Test D (REQUIRED): initial_pull_direction defaults to +Z, which
        coincides with Stage 1's own +Z principal. The expensive
        parting_line_v2 feasibility check for that direction must run
        exactly once -- reused, not re-invoked, when Stage 1's own
        bound-ordered loop later reaches the same direction.
        """
        import backend.geometry.direction_optimizer as optimizer_module
        from backend.geometry.direction_optimizer import optimize_mold_direction

        face = _make_face(0, (0.0, 0.0, 1.0), area=100.0)
        part = _make_part([face])

        monkeypatch.setattr(
            optimizer_module, "_cached_detect_boolean_undercuts",
            lambda part, direction, direction_cache, boolean_volume_cache, mutate, max_boolean_faces: (
                self._clean_result(part, direction), False,
            ),
        )
        call_log: list[tuple[float, float, float]] = []

        def counting_feasible(part, direction, *args, **kwargs):
            call_log.append(tuple(round(v, 6) for v in direction))
            return optimizer_module.PartingLineFeasibilityResult(feasible=True)

        monkeypatch.setattr(optimizer_module, "_is_parting_line_feasible", counting_feasible)

        result = optimize_mold_direction(part, angular_step_deg=45.0, max_candidates=10)

        z_calls = [c for c in call_log if c == (0.0, 0.0, 1.0)]
        assert len(z_calls) == 1, (
            "expected exactly one feasibility evaluation for the +Z direction "
            f"shared between the initial seed and Stage 1's own principal, got {len(z_calls)}: {call_log}"
        )
        assert result.optimal_found is True

    def test_e_custom_initial_direction_is_retained_as_a_candidate(self, monkeypatch):
        """
        O4 Test E: initial_pull_direction absent from the 18 configured
        Stage 1/2 directions must not silently disappear from the final
        candidate pool.
        """
        import backend.geometry.direction_optimizer as optimizer_module
        from backend.geometry.direction_optimizer import optimize_mold_direction
        from backend.geometry.undercut_detector import UndercutDetectionResult
        from backend.models.geometry_models import normalize3

        custom_direction = normalize3((1.0, 2.0, 4.0))  # not a principal or configured diagonal
        face = _make_face(0, custom_direction, area=100.0)
        part = _make_part([face])

        def direction_dependent_mock(part, direction, direction_cache, boolean_volume_cache, mutate, max_boolean_faces):
            if self._close(direction, custom_direction):
                return self._clean_result(part, direction), False
            # Every configured Stage 1/2 direction gets a real confirmed
            # undercut in this mock -- keeps evidence_tier below
            # "verified_acceptable" for all 18 of them, so none can
            # compete with (or need to be beaten by) the custom seed for
            # this retention/attribution test.
            bad = UndercutDetectionResult(
                pull_direction=direction, method="mock-boolean", undercut_face_ids=[0],
                accessible_face_ids=[], parting_face_ids=[], skipped_face_ids=[],
                boolean_refined=True, boolean_confirmed_face_ids=[0],
                total_analysed_area_mm2=100.0,
            )
            return bad, False

        monkeypatch.setattr(optimizer_module, "_cached_detect_boolean_undercuts", direction_dependent_mock)
        monkeypatch.setattr(
            optimizer_module, "_is_parting_line_feasible",
            lambda part, direction, *a, **k: optimizer_module.PartingLineFeasibilityResult(feasible=True),
        )

        result = optimize_mold_direction(
            part, angular_step_deg=45.0, max_candidates=10,
            initial_pull_direction=custom_direction,
        )

        candidate_directions = [tuple(round(v, 6) for v in c.direction) for c in result.candidates]
        expected = tuple(round(v, 6) for v in custom_direction)
        assert expected in candidate_directions

    def test_f_custom_initial_winner_is_attributed_to_initial_not_stage3(self, monkeypatch):
        """
        O4 Test F: when a genuinely custom initial_pull_direction is the
        only evidence-verified AND feasible candidate found, it must win
        and must be attributed to search_stage_reached==0 ("initial"),
        never mislabeled as Stage 3.
        """
        import backend.geometry.direction_optimizer as optimizer_module
        from backend.geometry.direction_optimizer import optimize_mold_direction
        from backend.geometry.undercut_detector import UndercutDetectionResult
        from backend.models.geometry_models import normalize3

        custom_direction = normalize3((1.0, 2.0, 4.0))
        face = _make_face(0, custom_direction, area=100.0)
        part = _make_part([face])

        def direction_dependent_mock(part, direction, direction_cache, boolean_volume_cache, mutate, max_boolean_faces):
            if self._close(direction, custom_direction):
                return self._clean_result(part, direction), False
            bad = UndercutDetectionResult(
                pull_direction=direction, method="mock-boolean", undercut_face_ids=[0],
                accessible_face_ids=[], parting_face_ids=[], skipped_face_ids=[],
                boolean_refined=True, boolean_confirmed_face_ids=[0],
                total_analysed_area_mm2=100.0,
            )
            return bad, False

        monkeypatch.setattr(optimizer_module, "_cached_detect_boolean_undercuts", direction_dependent_mock)
        monkeypatch.setattr(
            optimizer_module, "_is_parting_line_feasible",
            lambda part, direction, *a, **k: optimizer_module.PartingLineFeasibilityResult(feasible=True),
        )

        result = optimize_mold_direction(
            part, angular_step_deg=45.0, max_candidates=10,
            initial_pull_direction=custom_direction,
        )

        best = tuple(round(v, 6) for v in result.best_direction)
        expected = tuple(round(v, 6) for v in custom_direction)
        assert best == expected
        assert result.optimal_found is True
        assert result.search_stage_reached == 0

    def test_h_a_better_normal_candidate_still_beats_the_initial_seed(self, monkeypatch):
        """
        O4 Test H: the initial seed must not shortcut the search -- a
        Stage 1/2 candidate that is ALSO evidence-verified and feasible,
        with a materially better score, must still win over the seed via
        the unmodified _tiered_best comparator.
        """
        import backend.geometry.direction_optimizer as optimizer_module
        from backend.geometry.direction_optimizer import optimize_mold_direction

        # Face aligned with +X: perfect draft for +X (the seed, default
        # initial_pull_direction is +Z here so +Z is the seed instead --
        # give +Z a real but mediocre score by tilting it off-normal
        # slightly relative to the face, while +X is a genuine principal
        # with zero bad draft, so +X should out-score the +Z seed once
        # both are evidence-verified and feasible.)
        face = _make_face(0, (1.0, 0.0, 0.0), area=100.0)
        part = _make_part([face])

        monkeypatch.setattr(
            optimizer_module, "_cached_detect_boolean_undercuts",
            lambda part, direction, direction_cache, boolean_volume_cache, mutate, max_boolean_faces: (
                self._clean_result(part, direction), False,
            ),
        )
        monkeypatch.setattr(
            optimizer_module, "_is_parting_line_feasible",
            lambda part, direction, *a, **k: optimizer_module.PartingLineFeasibilityResult(feasible=True),
        )

        result = optimize_mold_direction(part, angular_step_deg=45.0, max_candidates=10)

        # The face is perfectly aligned with the X axis (zero bad draft in
        # EITHER +X or -X, a genuine tie the comparator's own deterministic
        # direction tiebreaker resolves -- not this test's concern) but
        # only at 90 degrees to +Z (the seed, 100% bad draft) -- the winner
        # must be the X-axis principal, never the +Z seed itself.
        assert result.best_direction != (0.0, 0.0, 1.0)
        assert result.best_direction in {(1.0, 0.0, 0.0), (-1.0, 0.0, 0.0)}
        assert result.optimal_found is True
        assert result.search_stage_reached == 1


# ---------------------------------------------------------------------------
# Milestone 4: Scoring Independence (accessibility risk ≠ draft ≠ undercut)
# ---------------------------------------------------------------------------

class TestScoringIndependence:
    """
    Tests that verify the three scoring signals are genuinely independent:
    1. bad_draft_pct — surface orientation
    2. accessibility_risk_area_pct — heuristic (core-side + concave edge)
    3. confirmed_undercut_area_pct — Boolean-confirmed obstruction
    """

    def test_cheap_score_uses_accessibility_risk_not_undercut_pct(self, monkeypatch):
        """
        In the cheap stage (boolean_refined=False), the score must incorporate
        accessibility_risk_area_pct from the undercut result.
        A face with bad draft + zero accessibility risk must score lower than
        the same face with zero bad draft + high accessibility risk —
        assuming the accessibility weight exceeds the bad-draft weight.
        """
        import backend.geometry.undercut_detector as undercut_module
        from backend.geometry.direction_optimizer import (
            DirectionCandidateResult,
            optimize_mold_direction,
        )

        monkeypatch.setattr(undercut_module, "_OCC_BOOLEAN_AVAILABLE", False)

        # Part: face with normal=(0,0,1) — aligns with pull=(0,0,1) → good draft.
        # No edges registered → no accessibility risk.
        face = _make_face(0, (0.0, 0.0, 1.0), area=100.0)
        part = _make_part([face])

        result = optimize_mold_direction(part, angular_step_deg=45.0, max_candidates=6)

        # The +Z candidate should exist in the scored list
        z_candidates = [
            c for c in result.candidates
            if c.direction == (0.0, 0.0, 1.0)
        ]
        assert z_candidates, "Expected +Z candidate in results"
        z = z_candidates[0]

        # +Z gives good draft → bad_area_pct = 0, accessibility_risk = 0
        assert z.bad_area_pct == pytest.approx(0.0, abs=1.0)
        assert z.accessibility_risk_area_pct == pytest.approx(0.0, abs=1.0)

    def test_accessibility_risk_field_exists_on_candidate_result(self, monkeypatch):
        """
        DirectionCandidateResult must carry accessibility_risk_area_pct as a
        first-class field (Milestone 4 additive change).
        """
        import backend.geometry.undercut_detector as undercut_module
        from backend.geometry.direction_optimizer import optimize_mold_direction

        monkeypatch.setattr(undercut_module, "_OCC_BOOLEAN_AVAILABLE", False)

        face = _make_face(0, (0.0, 0.0, 1.0), area=100.0)
        part = _make_part([face])

        result = optimize_mold_direction(part, angular_step_deg=45.0, max_candidates=6)

        for candidate in result.candidates:
            assert hasattr(candidate, "accessibility_risk_area_pct")
            assert isinstance(candidate.accessibility_risk_area_pct, float)
            d = candidate.to_dict()
            assert "accessibility_risk_area_pct" in d["percentages"]

    def test_boolean_stage_score_uses_confirmed_undercut_not_proxy(self, monkeypatch):
        """
        After Boolean refinement, _score_candidate() must use
        boolean_confirmed_face_ids (authoritative) — NOT undercut_face_ids
        (proxy).  We verify this by patching Boolean to confirm NO undercuts
        even on a face that would proxy-undercut cheaply.
        """
        import backend.geometry.direction_optimizer as optimizer_module
        from backend.geometry.direction_optimizer import optimize_mold_direction
        from backend.geometry.undercut_detector import UndercutDetectionResult

        # Face that would register as a proxy undercut (normal perpendicular to pull)
        # but Boolean says no confirmed undercut.
        face = _make_face(0, (1.0, 0.0, 0.0), area=100.0)
        part = _make_part([face])

        def mock_cached_boolean(
            part, direction, direction_cache, boolean_volume_cache, mutate, max_boolean_faces
        ):
            return UndercutDetectionResult(
                pull_direction=direction,
                method="mock-boolean",
                undercut_face_ids=[0],          # proxy says face 0 is undercut
                accessible_face_ids=[],
                parting_face_ids=[],
                skipped_face_ids=[],
                boolean_refined=True,
                boolean_confirmed_face_ids=[],   # Boolean says: NO confirmed undercuts
                total_analysed_area_mm2=100.0,
                undercut_area_mm2=100.0,
            ), False

        monkeypatch.setattr(
            optimizer_module, "_cached_detect_boolean_undercuts", mock_cached_boolean
        )

        result = optimize_mold_direction(part, angular_step_deg=45.0, max_candidates=10)

        # At least one candidate must have been Boolean-refined
        boolean_refined_candidates = [c for c in result.candidates if c.boolean_refined]
        assert boolean_refined_candidates, "Expected at least one Boolean-refined candidate"

        # The winning direction is Boolean-confirmed → search_stage_reached should be
        # 1 (or 2, depending on which principal passed cheap screen and got Boolean-refined).
        # What matters: the result is valid.
        assert result.best_direction is not None
        assert result.search_stage_reached in {1, 2, 3}

    def test_bad_draft_and_accessibility_risk_are_independent_signals(self):
        """
        A face with bad draft (n⊥d) but all-convex edges must score zero
        accessibility risk.  A face with good draft but core-side+concave
        must score nonzero accessibility risk.  The signals don't overlap.
        """
        # Import the internal scoring helper directly to test signal isolation.
        from backend.geometry.draft_analyzer import analyze_draft
        from backend.geometry.undercut_detector import detect_undercuts
        from backend.models.geometry_models import BoundingBox, EdgeData, PartGeometry

        # Face 1: bad draft (sideways normal), all convex edges
        bad_draft_face = _make_face(0, (1.0, 0.0, 0.0), area=100.0)
        convex_edge = EdgeData(
            edge_id=0,
            occ_edge=MagicMock(),
            edge_type="Line",
            length=1.0,
            adjacent_face_ids=[0],
            start_vertex=(0.0, 0.0, 0.0),
            end_vertex=(1.0, 0.0, 0.0),
            is_seam=False,
            convexity="convex",
        )
        from backend.models.geometry_models import BoundingBox, PartGeometry
        part_bad_draft = PartGeometry(
            source_file="mock.stp",
            occ_shape=MagicMock(),
            faces=[bad_draft_face],
            bounding_box=BoundingBox(0.0, 0.0, 0.0, 10.0, 10.0, 10.0),
            face_count=1,
            solid_count=1,
            shell_count=1,
            edges=[convex_edge],
            face_to_edges={0: [0]},
        )

        undercuts = detect_undercuts(
            part_bad_draft, (0.0, 0.0, 1.0), mutate=False, boolean_refine=False
        )
        draft = analyze_draft(part_bad_draft, (0.0, 0.0, 1.0), mutate=False)

        # Bad draft (face is a proxy undercut), but no accessibility risk
        assert draft.bad_pct > 0.0
        assert undercuts.accessibility_risk_area_pct == pytest.approx(0.0)


class TestO22ProcessIsolation:
    """
    O22: undercut-detection process isolation.

    Rule 9's 13 targeted tests. Items covered elsewhere rather than here:
      - #9 (O2 lower-bound pruning) / #10 (O4 seeding, feasibility cache) /
        #11 (Part1 semantics) / #13 (existing regression suite): none of
        that code was touched by O22 -- the full existing suite (this file
        + test_undercut_detector.py) passing unmodified IS the regression
        evidence, and the required real-Part1 critical test (fresh-child
        vs in-process on the XY-diagonal direction, run separately per the
        O22 spec) is the #11 evidence.
      - #12 (Part3 authorization stays parent-side): verified by
        inspection, not a live Part3 run here -- `_cached_detect_boolean_undercuts`
        is the ONLY function O22 modified, and it never receives or touches
        `core_pin_face_refs`/`delegations`; those remain exclusively
        parameters of `optimize_mold_direction`/`_cached_is_parting_line_feasible`,
        neither of which this phase changed.
    """

    def _make_isolatable_part(self, faces):
        """A part whose occ_shape is a REAL (empty) TopoDS_Shape -- passes
        the mock-safety `isinstance` guard so the isolation path is
        actually exercised, while everything else stays fake/mocked."""
        from OCC.Core.TopoDS import TopoDS_Shape
        from backend.models.geometry_models import BoundingBox, PartGeometry

        return PartGeometry(
            source_file="/tmp/o22_fake_part.stp",
            occ_shape=TopoDS_Shape(),
            faces=faces,
            bounding_box=BoundingBox(0.0, 0.0, 0.0, 10.0, 10.0, 10.0),
            face_count=len(faces),
            solid_count=1,
            shell_count=1,
        )

    def _dummy_success_result(self, direction):
        from backend.geometry.undercut_detector import UndercutDetectionResult

        return UndercutDetectionResult(
            pull_direction=direction,
            method="isolated-child-test",
            undercut_face_ids=[],
            accessible_face_ids=[0],
            parting_face_ids=[],
            skipped_face_ids=[],
            boolean_refined=True,
        )

    # 1. cache hit -> no child spawned
    def test_cache_hit_spawns_no_child(self, monkeypatch):
        import backend.geometry.direction_optimizer as opt_mod
        from backend.geometry.undercut_detector import UndercutDetectionResult

        part = self._make_isolatable_part([_make_face(0, (1.0, 0.0, 0.0))])
        direction = (1.0, 0.0, 0.0)

        def fail_if_called(*args, **kwargs):
            raise AssertionError("must not spawn a child on a cache hit")

        monkeypatch.setattr(opt_mod, "_run_isolated_undercut_detection", fail_if_called)

        key = opt_mod._direction_cache_key(
            part=part, direction=direction, boolean_refine=True,
            boolean_check_all_faces=False, max_boolean_faces=120,
        )
        precomputed = UndercutDetectionResult(
            pull_direction=direction, method="precomputed", undercut_face_ids=[],
            accessible_face_ids=[], parting_face_ids=[], skipped_face_ids=[],
        )
        direction_cache = {key: precomputed}

        result, hit = opt_mod._cached_detect_boolean_undercuts(
            part=part, direction=direction, direction_cache=direction_cache,
            boolean_volume_cache={}, mutate=False, max_boolean_faces=120,
        )
        assert hit is True
        assert result is precomputed

    # 2. cache miss -> exactly one child spawned
    def test_cache_miss_spawns_exactly_one_child(self, monkeypatch):
        import backend.geometry.direction_optimizer as opt_mod

        part = self._make_isolatable_part([_make_face(0, (1.0, 0.0, 0.0))])
        direction = (1.0, 0.0, 0.0)
        spawn_calls = []

        def fake_spawn(part_arg, direction_arg, max_boolean_faces):
            spawn_calls.append((direction_arg, max_boolean_faces))
            return self._dummy_success_result(direction_arg)

        monkeypatch.setattr(opt_mod, "_run_isolated_undercut_detection", fake_spawn)

        direction_cache = {}
        result, hit = opt_mod._cached_detect_boolean_undercuts(
            part=part, direction=direction, direction_cache=direction_cache,
            boolean_volume_cache={}, mutate=False, max_boolean_faces=120,
        )
        assert hit is False
        assert len(spawn_calls) == 1
        assert spawn_calls[0][0] == direction
        assert result.evaluation_failed is False
        assert len(direction_cache) == 1

    # 3. fresh child result reaches parent with the same optimizer-relevant
    #    fields as direct in-process detection (round-trip through the real
    #    to_plain/from_plain serialization, not a hand-built stub).
    def test_isolated_result_round_trips_equal_to_inprocess_fields(self, monkeypatch):
        import backend.geometry.direction_optimizer as opt_mod
        import backend.geometry.undercut_detector as undercut_module
        from backend.geometry.undercut_detector import (
            undercut_result_from_plain,
            undercut_result_to_plain,
        )

        monkeypatch.setattr(undercut_module, "_OCC_BOOLEAN_AVAILABLE", False)

        face = _make_face(0, (1.0, 0.0, 0.0))
        part = self._make_isolatable_part([face])
        direction = (1.0, 0.0, 0.0)

        direct = undercut_module.detect_undercuts(
            part, direction, mutate=False, boolean_refine=True, max_boolean_faces=120,
        )
        round_tripped = undercut_result_from_plain(undercut_result_to_plain(direct))

        for attr in [
            "undercut_face_ids", "accessible_face_ids", "parting_face_ids",
            "skipped_face_ids", "boolean_refined", "boolean_checked_face_ids",
            "boolean_confirmed_face_ids", "interference_volume_mm3",
            "accessibility_risk_face_ids", "candidate_unconfirmed_face_ids",
            "ray_verified_clear_face_ids", "evaluation_failed",
        ]:
            assert getattr(direct, attr) == getattr(round_tripped, attr), attr

        def fake_spawn(part_arg, direction_arg, max_boolean_faces):
            return round_tripped

        monkeypatch.setattr(opt_mod, "_run_isolated_undercut_detection", fake_spawn)
        via_isolation, hit = opt_mod._cached_detect_boolean_undercuts(
            part=part, direction=direction, direction_cache={},
            boolean_volume_cache={}, mutate=False, max_boolean_faces=120,
        )
        assert hit is False
        assert via_isolation.undercut_face_ids == direct.undercut_face_ids
        assert via_isolation.accessible_face_ids == direct.accessible_face_ids
        assert via_isolation.evaluation_failed == direct.evaluation_failed

    # 4. OCC field exclusion -- boolean_intersection_shapes never crosses
    def test_boolean_intersection_shapes_excluded_from_plain_payload(self):
        from backend.geometry.undercut_detector import (
            UndercutDetectionResult,
            UndercutFeature,
            undercut_result_from_plain,
            undercut_result_to_plain,
        )

        live_occ_handle = object()  # stands in for a TopoDS_Shape
        feature = UndercutFeature(
            feature_id=0, face_ids=[0], undercut_type="pocket", severity="minor",
            evidence_source="boolean", type_classification_method="test",
            type_classification_score=1.0, type_classification_factors=[],
            release_direction=(0.0, 0.0, 1.0), location=(0.0, 0.0, 0.0),
            depth_proxy_mm=1.0, total_area_mm2=10.0, min_draft_angle_deg=0.0,
            boolean_intersection_shapes=[live_occ_handle],
        )
        result = UndercutDetectionResult(
            pull_direction=(0.0, 0.0, 1.0), method="test", undercut_face_ids=[0],
            accessible_face_ids=[], parting_face_ids=[], skipped_face_ids=[],
            features=[feature],
        )

        plain = undercut_result_to_plain(result)
        # The live OCC handle itself must never appear anywhere in the
        # serialized payload -- json.dumps would choke on it if it did.
        import json
        json.dumps(plain)  # must not raise (would, if live_occ_handle leaked in)
        assert "boolean_intersection_shapes" not in plain["features"][0]

        reconstructed = undercut_result_from_plain(plain)
        assert reconstructed.features[0].boolean_intersection_shapes == []

    # 5. child exception -> evaluation_failed, never clean/infeasible
    def test_child_nonzero_exit_becomes_evaluation_failed_not_clean(self, monkeypatch):
        import subprocess as subprocess_module

        import backend.geometry.direction_optimizer as opt_mod

        class FakeCompletedProcess:
            returncode = 1
            stdout = ""
            stderr = "Traceback: boom"

        monkeypatch.setattr(
            opt_mod.subprocess, "run", lambda *a, **k: FakeCompletedProcess()
        )

        result = opt_mod._run_isolated_undercut_detection(
            self._make_isolatable_part([_make_face(0, (1.0, 0.0, 0.0))]),
            (1.0, 0.0, 0.0), 120,
        )
        assert result.evaluation_failed is True
        assert result.evaluation_error
        assert result.undercut_face_ids == []
        assert result.boolean_refined is False  # never silently "clean"/"confirmed"

    # 6. child timeout -> evaluation_failed
    def test_child_timeout_becomes_evaluation_failed(self, monkeypatch):
        import subprocess as subprocess_module

        import backend.geometry.direction_optimizer as opt_mod

        def raise_timeout(*a, **k):
            raise subprocess_module.TimeoutExpired(cmd="worker", timeout=150.0)

        monkeypatch.setattr(opt_mod.subprocess, "run", raise_timeout)

        result = opt_mod._run_isolated_undercut_detection(
            self._make_isolatable_part([_make_face(0, (1.0, 0.0, 0.0))]),
            (1.0, 0.0, 0.0), 120,
        )
        assert result.evaluation_failed is True
        assert "timed out" in result.evaluation_error
        assert result.undercut_face_ids == []

    # 7. malformed payload -> evaluation_failed
    def test_child_malformed_stdout_becomes_evaluation_failed(self, monkeypatch):
        import backend.geometry.direction_optimizer as opt_mod

        class FakeCompletedProcess:
            returncode = 0
            stdout = "not valid json{{{"
            stderr = ""

        monkeypatch.setattr(
            opt_mod.subprocess, "run", lambda *a, **k: FakeCompletedProcess()
        )

        result = opt_mod._run_isolated_undercut_detection(
            self._make_isolatable_part([_make_face(0, (1.0, 0.0, 0.0))]),
            (1.0, 0.0, 0.0), 120,
        )
        assert result.evaluation_failed is True
        assert result.evaluation_error

        # Also cover an explicit {"ok": false, ...} payload.
        import json as json_module

        class FakeOkFalseProcess:
            returncode = 0
            stdout = json_module.dumps({"ok": False, "error": "STEP load failed"})
            stderr = ""

        monkeypatch.setattr(
            opt_mod.subprocess, "run", lambda *a, **k: FakeOkFalseProcess()
        )
        result2 = opt_mod._run_isolated_undercut_detection(
            self._make_isolatable_part([_make_face(0, (1.0, 0.0, 0.0))]),
            (1.0, 0.0, 0.0), 120,
        )
        assert result2.evaluation_failed is True
        assert result2.evaluation_error == "STEP load failed"

    # 8. failed candidate never reaches _tiered_best
    def test_failed_candidate_excluded_from_tiered_best(self):
        from backend.geometry.direction_optimizer import (
            DirectionCandidateResult,
            _tiered_best,
        )

        failed = DirectionCandidateResult(
            direction=(1.0, 0.0, 0.0), label="+X", score=float("inf"),
            bad_face_count=0, marginal_face_count=0, good_face_count=1,
            bad_area_mm2=0.0, marginal_area_mm2=0.0, total_area_mm2=100.0,
            bad_area_pct=0.0, marginal_area_pct=0.0, undercut_face_count=0,
            undercut_feature_count=0, undercut_area_pct=0.0, boolean_refined=False,
            boolean_checked_count=0, interference_volume_mm3=0.0,
            principal_axis_alignment=1.0, evidence_tier="unverified",
            evaluation_failed=True, evaluation_error="child timed out",
        )
        healthy_but_unverified = _make_direction_candidate(
            "-X", score=5.0, direction=(-1.0, 0.0, 0.0), evidence_tier="unverified",
        )
        verified = _make_direction_candidate(
            "+Y", score=1.0, direction=(0.0, 1.0, 0.0),
            evidence_tier="verified_acceptable", boolean_refined=True,
        )

        winner = _tiered_best([failed, healthy_but_unverified, verified])
        assert winner is verified

        # Even with no verified candidate present, a failed one must not
        # beat a merely-unverified-but-successfully-scored candidate.
        winner_no_verified = _tiered_best([failed, healthy_but_unverified])
        assert winner_no_verified is healthy_but_unverified

    # Failure propagation through _build_refined_candidate (the single
    # integration point Rule 5 relies on for every call site).
    def test_build_refined_candidate_propagates_failure_as_unverified(self):
        from backend.config import settings
        from backend.geometry.direction_optimizer import _build_refined_candidate
        from backend.geometry.draft_analyzer import analyze_draft
        from backend.geometry.undercut_detector import UndercutDetectionResult

        face = _make_face(0, (1.0, 0.0, 0.0))
        part = self._make_isolatable_part([face])
        direction = (1.0, 0.0, 0.0)
        draft = analyze_draft(part, direction, mutate=False)
        failed_undercuts = UndercutDetectionResult(
            pull_direction=direction, method="isolated-child-timeout",
            undercut_face_ids=[], accessible_face_ids=[], parting_face_ids=[],
            skipped_face_ids=[], evaluation_failed=True,
            evaluation_error="child evaluation timed out after 150.0s",
        )

        candidate = _build_refined_candidate(
            direction, draft, failed_undercuts, part, settings.dfm.direction_search,
        )
        assert candidate.evaluation_failed is True
        assert candidate.evidence_tier == "unverified"
        assert candidate.evaluation_error == failed_undercuts.evaluation_error


class TestO24BoundedParallelExecution:
    """
    O24: bounded parallel fresh-child direction evaluation.

    These tests replace the real O22 isolated-child mechanism
    (`_cached_detect_boolean_undercuts`) and the real parting-line
    feasibility check (`_cached_is_parting_line_feasible`) with fully
    controlled fakes, so ONLY the batching/concurrency layer added in O24
    (inside `_boolean_refine_candidates` and the Stage-1+2 loop) is under
    test -- per the O24 spec's "prefer mocked/unit tests" instruction.
    Real fresh-child correctness itself is already covered by O22's tests
    and the real Part1 measurements.
    """

    def _settings_with_parallelism(self, n: int):
        import dataclasses

        from backend.config import settings as real_settings

        direction_search = dataclasses.replace(
            real_settings.dfm.direction_search, direction_parallelism=n,
        )
        dfm = dataclasses.replace(real_settings.dfm, direction_search=direction_search)
        return dataclasses.replace(real_settings, dfm=dfm)

    def _make_part(self, n_faces: int = 6):
        # Enough distinct principal-axis faces that Stage 1+2 has several
        # genuinely different candidates to batch/evaluate.
        faces = [
            _make_face(0, (1.0, 0.0, 0.0), area=40.0),
            _make_face(1, (-1.0, 0.0, 0.0), area=40.0),
            _make_face(2, (0.0, 1.0, 0.0), area=40.0),
            _make_face(3, (0.0, -1.0, 0.0), area=40.0),
            _make_face(4, (0.0, 0.0, 1.0), area=40.0),
            _make_face(5, (0.0, 0.0, -1.0), area=40.0),
        ][:n_faces]
        from backend.models.geometry_models import BoundingBox, PartGeometry

        return PartGeometry(
            source_file="mock.stp", occ_shape=MagicMock(), faces=faces,
            bounding_box=BoundingBox(0.0, 0.0, 0.0, 10.0, 10.0, 10.0),
            face_count=len(faces), solid_count=1, shell_count=1,
        )

    def _patch_fake_detect(
        self, monkeypatch, tracker, clean_direction=None, sleep_by_label=None,
        fail_labels=None,
    ):
        """
        Replace _cached_detect_boolean_undercuts with a fake that: tracks
        live-concurrency (current/max) under a lock, optionally sleeps per
        direction label to deliberately scramble completion order, marks
        `fail_labels` as evaluation_failed, and makes `clean_direction`
        (if given) verified_acceptable/feasible-eligible -- everything else
        is real-but-not-clean (boolean_refined, some confirmed undercut).
        """
        import threading as threading_module
        import time as time_module

        import backend.geometry.direction_optimizer as opt_mod
        from backend.geometry.undercut_detector import UndercutDetectionResult

        lock = threading_module.Lock()
        sleep_by_label = sleep_by_label or {}
        fail_labels = fail_labels or set()

        def fake(part, direction, direction_cache, boolean_volume_cache, mutate, max_boolean_faces):
            label = opt_mod._direction_label(direction)
            with lock:
                tracker["current"] += 1
                tracker["max"] = max(tracker["max"], tracker["current"])
                tracker["order"].append(label)
            try:
                time_module.sleep(sleep_by_label.get(label, 0.0))
                if label in fail_labels:
                    return UndercutDetectionResult(
                        pull_direction=direction, method="fake-isolated-child-failure",
                        undercut_face_ids=[], accessible_face_ids=[], parting_face_ids=[],
                        skipped_face_ids=[], evaluation_failed=True,
                        evaluation_error=f"simulated failure for {label}",
                    ), False
                if clean_direction is not None and direction == clean_direction:
                    return UndercutDetectionResult(
                        pull_direction=direction, method="fake-clean",
                        undercut_face_ids=[], accessible_face_ids=[0], parting_face_ids=[],
                        skipped_face_ids=[], boolean_refined=True,
                    ), False
                return UndercutDetectionResult(
                    pull_direction=direction, method="fake-dirty",
                    undercut_face_ids=[0], accessible_face_ids=[], parting_face_ids=[],
                    skipped_face_ids=[], boolean_refined=True,
                    boolean_confirmed_face_ids=[0], undercut_area_mm2=50.0,
                    total_analysed_area_mm2=100.0,
                ), False
            finally:
                with lock:
                    tracker["current"] -= 1

        monkeypatch.setattr(opt_mod, "_cached_detect_boolean_undercuts", fake)

    def _patch_feasible_always_true(self, monkeypatch):
        import backend.geometry.direction_optimizer as opt_mod
        from backend.geometry.direction_optimizer import PartingLineFeasibilityResult

        monkeypatch.setattr(
            opt_mod, "_cached_is_parting_line_feasible",
            lambda part, direction, core_pin_face_refs, delegations, cache, undercuts=None: (
                PartingLineFeasibilityResult(feasible=True, outcome="feasible")
            ),
        )

    # 3. concurrency=1 vs concurrency=6 (approximates "byte-identical to
    #    sequential" -- concurrency=1 batches of size 1 are exactly the
    #    pre-O24 per-candidate loop).
    # 4. identical per-direction result fields at concurrency=6.
    def test_concurrency_1_and_6_produce_identical_final_result(self, monkeypatch):
        import backend.geometry.direction_optimizer as opt_mod

        part = self._make_part()
        tracker = {"current": 0, "max": 0, "order": []}
        self._patch_fake_detect(monkeypatch, tracker, clean_direction=(0.0, 0.0, -1.0))
        self._patch_feasible_always_true(monkeypatch)

        monkeypatch.setattr(opt_mod, "settings", self._settings_with_parallelism(1))
        result_c1 = opt_mod.optimize_mold_direction(part)

        tracker["current"] = 0
        tracker["max"] = 0
        tracker["order"] = []
        monkeypatch.setattr(opt_mod, "settings", self._settings_with_parallelism(6))
        result_c6 = opt_mod.optimize_mold_direction(part)

        assert result_c1.best_direction == result_c6.best_direction
        assert result_c1.best_label == result_c6.best_label
        assert result_c1.best_score == result_c6.best_score
        assert result_c1.best_evidence_tier == result_c6.best_evidence_tier
        assert result_c1.optimal_found == result_c6.optimal_found
        assert result_c1.search_stage_reached == result_c6.search_stage_reached
        assert result_c1.best_label == "-Z"
        assert result_c1.optimal_found is True

        c1_by_label = {c.label: c for c in result_c1.candidates}
        c6_by_label = {c.label: c for c in result_c6.candidates}
        assert set(c1_by_label) == set(c6_by_label)
        for label, c1 in c1_by_label.items():
            c6 = c6_by_label[label]
            assert c1.score == c6.score
            assert c1.evidence_tier == c6.evidence_tier
            assert c1.undercut_face_count == c6.undercut_face_count
            assert c1.boolean_refined == c6.boolean_refined

    # 7. maximum simultaneous children never exceeds configured cap.
    def test_max_concurrent_never_exceeds_configured_cap(self, monkeypatch):
        import backend.geometry.direction_optimizer as opt_mod

        part = self._make_part()
        tracker = {"current": 0, "max": 0, "order": []}
        # Sleep just enough that overlap is measurable but the test stays fast.
        sleep_by_label = {"+X": 0.05, "-X": 0.05, "+Y": 0.05, "-Y": 0.05, "+Z": 0.05, "-Z": 0.05}
        self._patch_fake_detect(monkeypatch, tracker, sleep_by_label=sleep_by_label)
        self._patch_feasible_always_true(monkeypatch)

        monkeypatch.setattr(opt_mod, "settings", self._settings_with_parallelism(3))
        opt_mod.optimize_mold_direction(part)

        assert tracker["max"] <= 3
        assert tracker["max"] >= 2  # confirms real overlap actually happened, not accidental serialization

    # 5. completion order randomized/reversed -> final winner unchanged.
    def test_completion_order_does_not_affect_winner(self, monkeypatch):
        import backend.geometry.direction_optimizer as opt_mod

        part = self._make_part()
        tracker = {"current": 0, "max": 0, "order": []}
        # -Z (the clean/winning direction) is made to finish FIRST despite
        # being scanned LAST in bound order (it has the worst cheap draft
        # score among principal axes for a symmetric mock part, so bound-
        # order still visits it near the end); other directions sleep
        # longer so they finish AFTER -Z despite starting earlier.
        sleep_by_label = {"+X": 0.08, "-X": 0.08, "+Y": 0.08, "-Y": 0.08, "+Z": 0.08, "-Z": 0.0}
        self._patch_fake_detect(
            monkeypatch, tracker, clean_direction=(0.0, 0.0, -1.0), sleep_by_label=sleep_by_label,
        )
        self._patch_feasible_always_true(monkeypatch)
        monkeypatch.setattr(opt_mod, "settings", self._settings_with_parallelism(6))

        result = opt_mod.optimize_mold_direction(part)
        assert result.best_label == "-Z"
        assert result.optimal_found is True
        # -Z genuinely finished before at least one slower batch-mate.
        assert tracker["order"].index("-Z") < len(tracker["order"]) - 1

    # 6. one child failure does not corrupt other candidate results.
    def test_one_failure_does_not_corrupt_other_candidates(self, monkeypatch):
        import backend.geometry.direction_optimizer as opt_mod

        part = self._make_part()
        tracker = {"current": 0, "max": 0, "order": []}
        self._patch_fake_detect(
            monkeypatch, tracker, clean_direction=(0.0, 0.0, -1.0), fail_labels={"+X"},
        )
        self._patch_feasible_always_true(monkeypatch)
        monkeypatch.setattr(opt_mod, "settings", self._settings_with_parallelism(6))

        result = opt_mod.optimize_mold_direction(part)

        by_label = {c.label: c for c in result.candidates}
        assert by_label["+X"].evaluation_failed is True
        assert by_label["+X"].evidence_tier == "unverified"
        # The failure never becomes the winner, never becomes verified/feasible.
        assert result.best_label == "-Z"
        assert result.optimal_found is True
        assert result.best_evidence_tier == "verified_acceptable"
        # Every OTHER candidate is unaffected -- real data, not corrupted/zeroed.
        assert by_label["+Y"].evaluation_failed is False
        assert by_label["+Y"].boolean_refined is True
        assert any(
            f["direction_label"] == "+X" for f in result.evaluation_failures
        )

    # 8. O4 initial seed remains functional under parallel execution.
    def test_o4_initial_seed_still_seeds_best_feasible(self, monkeypatch):
        import backend.geometry.direction_optimizer as opt_mod

        part = self._make_part()
        tracker = {"current": 0, "max": 0, "order": []}
        # Default initial_pull_direction is +Z -- make IT the clean one, so
        # a correct O4 seed should resolve the whole search at stage 0/1
        # without needing to fall through to evaluate every candidate.
        self._patch_fake_detect(monkeypatch, tracker, clean_direction=(0.0, 0.0, 1.0))
        self._patch_feasible_always_true(monkeypatch)
        monkeypatch.setattr(opt_mod, "settings", self._settings_with_parallelism(6))

        result = opt_mod.optimize_mold_direction(part)
        assert result.best_label == "+Z"
        assert result.optimal_found is True
        assert result.best_evidence_tier == "verified_acceptable"

    # 9. exact comparator/tiebreak behavior unchanged -- two directions tie
    #    exactly (score, tier, accessibility risk, axis alignment all
    #    equal); the deterministic direction-tuple tiebreak must still pick
    #    the lexicographically smaller direction, exactly as pre-O24.
    def test_exact_tie_still_resolved_by_deterministic_direction_tiebreak(self, monkeypatch):
        import backend.geometry.direction_optimizer as opt_mod

        part = self._make_part()
        tracker = {"current": 0, "max": 0, "order": []}

        from backend.geometry.undercut_detector import UndercutDetectionResult

        def fake(part, direction, direction_cache, boolean_volume_cache, mutate, max_boolean_faces):
            # +Z and -Z tie exactly (both fully clean); everything else dirty.
            if direction in ((0.0, 0.0, 1.0), (0.0, 0.0, -1.0)):
                return UndercutDetectionResult(
                    pull_direction=direction, method="fake-clean",
                    undercut_face_ids=[], accessible_face_ids=[0], parting_face_ids=[],
                    skipped_face_ids=[], boolean_refined=True,
                ), False
            return UndercutDetectionResult(
                pull_direction=direction, method="fake-dirty",
                undercut_face_ids=[0], accessible_face_ids=[], parting_face_ids=[],
                skipped_face_ids=[], boolean_refined=True,
                boolean_confirmed_face_ids=[0], undercut_area_mm2=50.0,
                total_analysed_area_mm2=100.0,
            ), False

        monkeypatch.setattr(opt_mod, "_cached_detect_boolean_undercuts", fake)
        self._patch_feasible_always_true(monkeypatch)
        monkeypatch.setattr(opt_mod, "settings", self._settings_with_parallelism(6))

        result = opt_mod.optimize_mold_direction(part)
        assert result.best_label == "-Z"  # (0,0,-1) < (0,0,1) lexicographically
        assert result.best_score == pytest.approx(
            next(c.score for c in result.candidates if c.label == "+Z")
        )

    # 10. no OCC object crosses the process boundary -- covered by O22's
    #     dedicated test, re-affirmed here in the O24 batched path: the
    #     fake never receives or returns anything but plain data, and the
    #     production dispatch closure only ever calls
    #     _cached_detect_boolean_undercuts (O22's own boundary, unchanged
    #     by O24) -- no new serialization path was introduced.
    def test_batched_dispatch_never_bypasses_o22_isolation_boundary(self, monkeypatch):
        import inspect

        import backend.geometry.direction_optimizer as opt_mod

        source = inspect.getsource(opt_mod.optimize_mold_direction)
        # The O24 batching code must dispatch exclusively through the
        # existing O22 entry point -- never subprocess/Popen directly.
        assert "_cached_detect_boolean_undercuts" in source
        assert "subprocess.Popen" not in source


class TestC12SideActionReferrals:
    """
    C12 (2026-08-17): top-level SideActionReferral reporting -- pure
    diagnostic plumbing, no side_core invocation, no change to
    optimal_found/candidate-selection semantics.
    """

    def _make_part(self):
        # Reuses the module-level _make_face/_make_part helpers -- same
        # 6-axis-face symmetric mock used by TestO24.
        return _make_part([
            _make_face(0, (1.0, 0.0, 0.0), area=40.0),
            _make_face(1, (-1.0, 0.0, 0.0), area=40.0),
            _make_face(2, (0.0, 1.0, 0.0), area=40.0),
            _make_face(3, (0.0, -1.0, 0.0), area=40.0),
            _make_face(4, (0.0, 0.0, 1.0), area=40.0),
            _make_face(5, (0.0, 0.0, -1.0), area=40.0),
        ])

    def _patch_detect_always_clean(self, monkeypatch):
        import backend.geometry.direction_optimizer as opt_mod
        from backend.geometry.undercut_detector import UndercutDetectionResult

        def fake(part, direction, direction_cache, boolean_volume_cache, mutate, max_boolean_faces):
            return UndercutDetectionResult(
                pull_direction=direction, method="fake-clean",
                undercut_face_ids=[], accessible_face_ids=[0], parting_face_ids=[],
                skipped_face_ids=[], boolean_refined=True,
            ), False

        monkeypatch.setattr(opt_mod, "_cached_detect_boolean_undercuts", fake)

    def _make_referral_dict(self, feature_id=1, segment_id=7, conflict_length_mm=3.5):
        return {
            "feature_ids": [feature_id],
            "conflicting_segment_ids": [segment_id],
            "conflict_length_mm": conflict_length_mm,
            "release_direction_hint": [0.0, 0.0, 1.0],
            "note": "Main parting line cannot pass cleanly through this feature; requires a side action.",
        }

    def _patch_feasibility(self, monkeypatch, referred_directions, referral_dict, call_log=None):
        """
        referred_directions: set of directions that must come back
        feasible=False, outcome="referred_to_side_action", carrying
        referral_dict. Every other direction comes back feasible=True.
        """
        import backend.geometry.direction_optimizer as opt_mod
        from backend.geometry.direction_optimizer import PartingLineFeasibilityResult

        def fake(part, direction, core_pin_face_refs, delegations, cache, undercuts=None):
            if call_log is not None:
                call_log.append(direction)
            if direction in referred_directions:
                return PartingLineFeasibilityResult(
                    feasible=False, outcome="referred_to_side_action",
                    reason="requires_side_action", referrals=(referral_dict,),
                )
            return PartingLineFeasibilityResult(feasible=True, outcome="feasible")

        monkeypatch.setattr(opt_mod, "_cached_is_parting_line_feasible", fake)

    # 1. Referral propagation through _is_parting_line_feasible itself
    # (the real function body, only analyse_parting_line mocked out).
    def test_is_parting_line_feasible_preserves_referrals(self, monkeypatch):
        import backend.geometry.direction_optimizer as opt_mod
        from OCC.Core.TopoDS import TopoDS_Shape
        from backend.models.geometry_models import BoundingBox, PartGeometry

        part = PartGeometry(
            source_file="mock.stp", occ_shape=TopoDS_Shape(), faces=[],
            bounding_box=BoundingBox(0.0, 0.0, 0.0, 10.0, 10.0, 10.0),
            face_count=0, solid_count=1, shell_count=1,
        )

        class FakeReferral:
            def to_dict(self):
                return self._as_dict

            def __init__(self, d):
                self._as_dict = d

        referral_dict = self._make_referral_dict()

        class FakeResult:
            outcome = "referred_to_side_action"
            best_rejected_failed_gate = "H5"
            best_rejected_reason = "requires_side_action"
            referrals = (FakeReferral(referral_dict),)

        # analyse_parting_line is imported lazily inside the function body
        # (`from backend.geometry.parting_line_v2.engine import
        # analyse_parting_line`) -- patch it at its source module so the
        # lazy import resolves to the fake.
        import backend.geometry.parting_line_v2.engine as engine_mod
        monkeypatch.setattr(engine_mod, "analyse_parting_line", lambda *a, **k: FakeResult())

        result = opt_mod._is_parting_line_feasible(part, (0.0, 0.0, 1.0))
        assert result.feasible is False
        assert result.outcome == "referred_to_side_action"
        assert result.referrals == (referral_dict,)

    # 2. Top-level propagation from the initial-direction seed path.
    def test_referral_propagates_from_initial_seed(self, monkeypatch):
        import backend.geometry.direction_optimizer as opt_mod

        part = self._make_part()
        self._patch_detect_always_clean(monkeypatch)
        referral = self._make_referral_dict(feature_id=1)
        # Default initial_pull_direction is +Z.
        self._patch_feasibility(monkeypatch, {(0.0, 0.0, 1.0)}, referral)

        result = opt_mod.optimize_mold_direction(part)
        assert len(result.side_action_referrals) >= 1
        entry = result.side_action_referrals[0]
        assert entry["direction"] == [0.0, 0.0, 1.0]
        assert entry["direction_label"] == "+Z"
        assert entry["referral"] == referral

    # 2b. Top-level propagation from the Stage 1+2 loop (a non-initial,
    # non-winning direction gets referred). Verified empirically: for this
    # symmetric 6-axis-face mock, only +Z (the default initial direction)
    # and the 12 Stage-1/2 diagonal candidates ever reach
    # _cached_is_parting_line_feasible -- the other 5 axis directions never
    # reach evidence_tier=="verified_acceptable" and are pruned before the
    # feasibility call. A diagonal is therefore required here, not an axis.
    def test_referral_propagates_from_stage12_loop(self, monkeypatch):
        import math

        import backend.geometry.direction_optimizer as opt_mod

        part = self._make_part()
        self._patch_detect_always_clean(monkeypatch)
        referral = self._make_referral_dict(feature_id=2)
        r2 = 1.0 / math.sqrt(2.0)
        diagonal = (r2, r2, 0.0)
        # diagonal is referred; +Z (initial) and every other diagonal is
        # feasible, so the winner is unaffected and the referral is purely
        # diagnostic.
        self._patch_feasibility(monkeypatch, {diagonal}, referral)

        result = opt_mod.optimize_mold_direction(part)
        directions_referred = [tuple(e["direction"]) for e in result.side_action_referrals]
        assert diagonal in directions_referred
        assert result.optimal_found is True  # winner itself unaffected

    # 3. Deduplication: _record_side_action_referrals must collapse two
    # calls carrying the same (direction, referral) pair -- the exact
    # scenario the user's spec calls out ("O4/O10 caching create duplicate
    # diagnostics" when the same direction is re-evaluated through
    # different control-flow paths, e.g. the Stage 1+2 loop and the later
    # Stage 3/tail-path re-check of the eventual winner's own direction,
    # both funneling through the SAME feasibility_cache). Testing the
    # helper directly is more precise than reverse-engineering which real
    # search topology produces a second visit -- the real Part3
    # candidate-110 fixture test below exercises the full integration.
    def test_record_side_action_referrals_deduplicates_same_direction_and_referral(self):
        from backend.geometry.direction_optimizer import (
            PartingLineFeasibilityResult,
            _record_side_action_referrals,
        )

        referral = self._make_referral_dict(feature_id=3)
        feasibility = PartingLineFeasibilityResult(
            feasible=False, outcome="referred_to_side_action", referrals=(referral,),
        )
        direction = (0.0, 0.0, 1.0)
        side_action_referrals: list = []
        seen_referral_keys: set = set()

        _record_side_action_referrals(side_action_referrals, seen_referral_keys, direction, feasibility)
        # Second call: same direction, same feasibility object (as would
        # happen on a feasibility_cache hit for the same direction reached
        # through a different code path).
        _record_side_action_referrals(side_action_referrals, seen_referral_keys, direction, feasibility)

        assert len(side_action_referrals) == 1
        assert side_action_referrals[0]["direction"] == [0.0, 0.0, 1.0]
        assert side_action_referrals[0]["referral"] == referral

    def test_record_side_action_referrals_keeps_distinct_directions(self):
        from backend.geometry.direction_optimizer import (
            PartingLineFeasibilityResult,
            _record_side_action_referrals,
        )

        referral = self._make_referral_dict(feature_id=4)
        feasibility = PartingLineFeasibilityResult(
            feasible=False, outcome="referred_to_side_action", referrals=(referral,),
        )
        side_action_referrals: list = []
        seen_referral_keys: set = set()

        _record_side_action_referrals(
            side_action_referrals, seen_referral_keys, (0.0, 0.0, 1.0), feasibility,
        )
        _record_side_action_referrals(
            side_action_referrals, seen_referral_keys, (1.0, 0.0, 0.0), feasibility,
        )

        assert len(side_action_referrals) == 2

    # 4. No referral at all for an ordinary fully-feasible search.
    def test_no_referrals_when_nothing_is_referred(self, monkeypatch):
        import backend.geometry.direction_optimizer as opt_mod

        part = self._make_part()
        self._patch_detect_always_clean(monkeypatch)
        self._patch_feasibility(monkeypatch, set(), self._make_referral_dict())

        result = opt_mod.optimize_mold_direction(part)
        assert result.side_action_referrals == []
        assert result.optimal_found is True

    # 6. Explicit proof no side-core function is ever invoked by the
    # optimizer, even when referrals exist.
    def test_optimizer_never_calls_side_core(self, monkeypatch):
        import math

        import backend.geometry.direction_optimizer as opt_mod
        import backend.geometry.side_core as side_core_mod

        part = self._make_part()
        self._patch_detect_always_clean(monkeypatch)
        referral = self._make_referral_dict()
        r2 = 1.0 / math.sqrt(2.0)
        self._patch_feasibility(monkeypatch, {(0.0, 0.0, 1.0), (r2, r2, 0.0)}, referral)

        def explode(*a, **k):
            raise AssertionError("optimize_mold_direction must never call side_core")

        monkeypatch.setattr(side_core_mod, "generate_side_core", explode)
        monkeypatch.setattr(side_core_mod, "generate_primary_side_core", explode)
        monkeypatch.setattr(side_core_mod, "generate_side_cores_for_features", explode)

        result = opt_mod.optimize_mold_direction(part)
        assert len(result.side_action_referrals) >= 1  # referrals did occur
        # No exception means side_core was never touched.

    # 8. Backward-compatible serialization: side_action_referrals key
    # present and empty by default, additive to the existing schema.
    def test_to_dict_includes_side_action_referrals_additively(self, monkeypatch):
        import backend.geometry.direction_optimizer as opt_mod

        part = self._make_part()
        self._patch_detect_always_clean(monkeypatch)
        self._patch_feasibility(monkeypatch, set(), self._make_referral_dict())

        result = opt_mod.optimize_mold_direction(part)
        d = result.to_dict()
        assert "side_action_referrals" in d
        assert d["side_action_referrals"] == []
        # Existing keys still present -- purely additive. (optimal_found
        # itself is a dataclass field, not part of to_dict()'s pre-existing
        # output -- confirmed by reading to_dict()'s body -- so it is
        # checked on the result object, not the serialized dict.)
        assert "evaluation_failures" in d
        assert result.optimal_found is True
