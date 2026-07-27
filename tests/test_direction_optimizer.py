"""
tests/test_direction_optimizer.py
---------------------------------
Pure tests for candidate direction generation and draft-based scoring.
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch


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
):
    from backend.geometry.direction_optimizer import DirectionCandidateResult

    return DirectionCandidateResult(
        direction=(1.0, 0.0, 0.0),
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
        boolean_refined=False,
        boolean_checked_count=0,
        interference_volume_mm3=0.0,
        principal_axis_alignment=principal_axis_alignment,
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

    assert result.best_label == "+X"
    assert result.initial_draft.face_results[0]["draft_classification"] == "bad"
    assert result.optimal_draft.face_results[0]["draft_classification"] == "good"
    assert part.optimal_pull_direction == (1.0, 0.0, 0.0)
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
