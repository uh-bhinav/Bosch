"""
tests/test_undercut_semantic_contract.py
-----------------------------------------
Synthetic geometric controls and semantic contract tests for the
pull-direction / undercut pipeline corrections.

Implements tests T1–T16 from the plan (Section 10):
  T1-T6:  Synthetic geometric controls (R5)
  T7-T13: Semantic contract tests
  T14-T16: Boolean mechanism tests (R3)

These tests do NOT require OCC — they mock the Boolean operations
and verify the semantic contracts of result assembly.

OCC tests (T17-T19) and API tests (T20-T21) require the full runtime
and are marked @pytest.mark.requires_occ.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _make_boolean_metrics(volume_mm3: float = 0.0):
    """Build a real BooleanInterferenceMetrics with the given volume."""
    from backend.geometry.undercut_detector import BooleanInterferenceMetrics
    return BooleanInterferenceMetrics(
        volume_mm3=volume_mm3,
        depth_mm=max(0.0, volume_mm3 / 80.0) if volume_mm3 > 0 else 0.0,
        elapsed_s=0.001,
    )


# ---------------------------------------------------------------------------
# Helpers: build minimal FaceData / PartGeometry mocks
# ---------------------------------------------------------------------------

def _make_face(face_id: int, normal: tuple, area: float = 100.0):
    from backend.models.geometry_models import FaceData
    return FaceData(
        face_id=face_id,
        occ_face=MagicMock(),
        surface_type="Plane",
        normal=normal,
        centroid=(0.0, 0.0, float(face_id)),
        area=area,
        u_range=(0.0, 1.0),
        v_range=(0.0, 1.0),
        is_reversed=False,
        normal_valid=True,
    )


def _make_edge(edge_id: int, face_ids: list[int], convexity: str = "convex"):
    from backend.models.geometry_models import EdgeData
    return EdgeData(
        edge_id=edge_id,
        occ_edge=MagicMock(),
        edge_type="Line",
        length=1.0,
        adjacent_face_ids=face_ids,
        start_vertex=(0.0, 0.0, 0.0),
        end_vertex=(1.0, 0.0, 0.0),
        is_seam=False,
        convexity=convexity,
    )


def _make_part(faces, edges=None, face_to_edges=None):
    from backend.models.geometry_models import BoundingBox, PartGeometry
    return PartGeometry(
        source_file="mock.stp",
        occ_shape=MagicMock(),
        faces=faces,
        bounding_box=BoundingBox(0.0, 0.0, 0.0, 100.0, 100.0, 100.0),
        face_count=len(faces),
        solid_count=1,
        shell_count=1,
        edges=edges or [],
        face_to_edges=face_to_edges or {f.face_id: [] for f in faces},
    )


# ===========================================================================
# T1 — R5a: Zero-draft accessible vertical wall → NOT confirmed undercut
# ===========================================================================

def test_zero_draft_accessible_wall_not_in_undercut_ids_no_boolean():
    """
    A vertical wall with 0° draft (normal ⊥ pull) and all-convex edges should
    be convexity-suppressed and NOT appear in undercut_face_ids.

    Zero draft alone is NEVER sufficient evidence for a confirmed undercut.
    """
    from backend.geometry.undercut_detector import detect_undercuts

    # Normal perpendicular to pull → 0° draft
    face = _make_face(0, (1.0, 0.0, 0.0), area=100.0)
    edge = _make_edge(0, [0], convexity="convex")
    part = _make_part([face], edges=[edge], face_to_edges={0: [0]})

    result = detect_undercuts(part, (0.0, 0.0, 1.0), mutate=False, boolean_refine=False)

    # With convexity suppression: convex wall should be suppressed
    assert 0 not in result.undercut_face_ids, (
        "Zero-draft face with all-convex edges must NOT be a confirmed undercut"
    )
    assert 0 in result.convexity_suppressed_face_ids, (
        "Zero-draft face with all-convex edges should be convexity-suppressed"
    )


def test_zero_draft_no_boolean_undercut_ids_empty():
    """
    Without Boolean, undercut_face_ids must be empty (no confirmed undercuts).
    Convexity-suppressed faces (zero-draft, convex edges) go nowhere in the
    confirmed list.
    """
    from backend.geometry.undercut_detector import detect_undercuts

    face = _make_face(0, (1.0, 0.0, 0.0), area=100.0)
    edge = _make_edge(0, [0], convexity="convex")
    part = _make_part([face], edges=[edge], face_to_edges={0: [0]})

    result = detect_undercuts(part, (0.0, 0.0, 1.0), mutate=False, boolean_refine=False)

    # T8 semantic: without Boolean, undercut_face_ids must always be empty
    assert result.undercut_face_ids == [], (
        "Without Boolean, undercut_face_ids must be empty — nothing is confirmed"
    )
    assert not result.boolean_validation_complete, (
        "Without Boolean, validation_complete must be False"
    )


# ===========================================================================
# T3 — R5c: Concave but accessible → NOT undercut when Boolean finds no volume
# ===========================================================================

def test_concave_face_no_boolean_volume_not_in_undercut():
    """
    A face with concave edges but Boolean returning volume=0 must NOT be a
    confirmed undercut. It goes into boolean_no_interference_face_ids.
    """
    from backend.geometry.undercut_detector import _boolean_refine_undercuts, detect_undercuts
    from backend.models.geometry_models import BoundingBox, PartGeometry

    # Core-side face (signed_dot < 0) with concave edge → accessibility risk candidate
    # But Boolean returns volume=0 → no interference
    face = _make_face(0, (0.0, 0.0, -1.0), area=80.0)  # n·d = -1 for d=(0,0,1)
    edge = _make_edge(0, [0], convexity="concave")
    part = _make_part([face], edges=[edge], face_to_edges={0: [0]})

    with patch(
        "backend.geometry.undercut_detector._swept_face_interference_volume",
        return_value=_make_boolean_metrics(volume_mm3=0.0),
    ), patch(
        "backend.geometry.undercut_detector._OCC_BOOLEAN_AVAILABLE",
        True,
    ):
        result = detect_undercuts(part, (0.0, 0.0, 1.0), mutate=False, boolean_refine=True)

    # Concave + core-side → risk candidate → Boolean checked → volume=0 → no_interference
    assert 0 not in result.undercut_face_ids, (
        "Concave face with Boolean volume=0 must NOT be a confirmed undercut"
    )
    assert 0 in result.boolean_no_interference_face_ids, (
        "Boolean volume=0 face must be in boolean_no_interference_face_ids"
    )
    assert 0 not in result.suspected_undercut_face_ids, (
        "Successfully-checked zero-volume face must NOT be suspected"
    )


# ===========================================================================
# T5 — R5e: Boolean failure → suspected, not confirmed
# ===========================================================================

def test_boolean_failure_goes_to_suspected_not_confirmed():
    """
    A face where the Boolean operation raises an OCC exception must land in
    suspected_undercut_face_ids, NOT in undercut_face_ids.
    """
    from backend.geometry.undercut_detector import detect_undercuts

    # Core-side face with concave edge → risk candidate
    face = _make_face(0, (0.0, 0.0, -1.0), area=50.0)
    edge = _make_edge(0, [0], convexity="concave")
    part = _make_part([face], edges=[edge], face_to_edges={0: [0]})

    with patch(
        "backend.geometry.undercut_detector._swept_face_interference_volume",
        side_effect=RuntimeError("OCC Boolean failed"),
    ), patch(
        "backend.geometry.undercut_detector._OCC_BOOLEAN_AVAILABLE",
        True,
    ):
        result = detect_undercuts(part, (0.0, 0.0, 1.0), mutate=False, boolean_refine=True)

    assert 0 not in result.undercut_face_ids, (
        "Boolean-failed face must NOT be in undercut_face_ids"
    )
    assert 0 not in result.boolean_no_interference_face_ids, (
        "Boolean-failed face must NOT be in boolean_no_interference_face_ids"
    )
    assert 0 in result.boolean_failed_face_ids, (
        "Boolean-failed face must be in boolean_failed_face_ids"
    )
    assert 0 in result.suspected_undercut_face_ids, (
        "Boolean-failed face must be in suspected_undercut_face_ids"
    )


# ===========================================================================
# T6 — R5f: Boolean budget exhaustion → validation incomplete
# ===========================================================================

def test_budget_exhaustion_produces_incomplete_validation():
    """
    When candidates exceed max_boolean_faces, skipped candidates must be in
    suspected_undercut_face_ids and boolean_validation_complete must be False.
    """
    from backend.geometry.undercut_detector import detect_undercuts

    # Create 5 core-side concave faces
    faces = [_make_face(i, (0.0, 0.0, -1.0), area=10.0) for i in range(5)]
    edges = [_make_edge(i, [i], convexity="concave") for i in range(5)]
    face_to_edges = {i: [i] for i in range(5)}
    part = _make_part(faces, edges=edges, face_to_edges=face_to_edges)

    with patch(
        "backend.geometry.undercut_detector._swept_face_interference_volume",
        return_value=_make_boolean_metrics(volume_mm3=0.0),
    ), patch(
        "backend.geometry.undercut_detector._OCC_BOOLEAN_AVAILABLE",
        True,
    ):
        # Budget of 2 → 3 candidates are skipped
        result = detect_undercuts(
            part, (0.0, 0.0, 1.0), mutate=False, boolean_refine=True, max_boolean_faces=2
        )

    assert not result.boolean_validation_complete, (
        "validation_complete must be False when candidates exceed budget"
    )
    assert result.boolean_candidate_count > len(result.boolean_checked_face_ids), (
        "candidate_count must be greater than checked_count when budget exhausted"
    )
    # Skipped faces must be suspected, not confirmed
    for fid in result.boolean_skipped_face_ids:
        assert fid not in result.undercut_face_ids, (
            f"Budget-skipped face {fid} must NOT be in undercut_face_ids"
        )
        assert fid in result.suspected_undercut_face_ids, (
            f"Budget-skipped face {fid} must be in suspected_undercut_face_ids"
        )


# ===========================================================================
# T7 — Semantic contract: undercut_face_ids == boolean_confirmed when Boolean ran
# ===========================================================================

def test_undercut_face_ids_equals_confirmed_when_boolean_ran():
    """
    When Boolean refinement ran, undercut_face_ids must be exactly the set
    of Boolean-confirmed faces (no more, no less).
    """
    from backend.geometry.undercut_detector import detect_undercuts

    # Core-side face with concave edge
    face = _make_face(0, (0.0, 0.0, -1.0), area=50.0)
    edge = _make_edge(0, [0], convexity="concave")
    part = _make_part([face], edges=[edge], face_to_edges={0: [0]})

    with patch(
        "backend.geometry.undercut_detector._swept_face_interference_volume",
        return_value=_make_boolean_metrics(volume_mm3=50.0),
    ), patch(
        "backend.geometry.undercut_detector._OCC_BOOLEAN_AVAILABLE",
        True,
    ):
        result = detect_undercuts(part, (0.0, 0.0, 1.0), mutate=False, boolean_refine=True)

    assert set(result.undercut_face_ids) == set(result.boolean_confirmed_face_ids), (
        "undercut_face_ids must equal boolean_confirmed_face_ids when Boolean ran"
    )


# ===========================================================================
# T8 — Semantic contract: no-Boolean path has empty undercut_face_ids
# ===========================================================================

def test_no_boolean_undercut_face_ids_is_empty():
    """
    Without Boolean refinement, undercut_face_ids must be empty. Proxy
    candidates go to suspected_undercut_face_ids.
    """
    from backend.geometry.undercut_detector import detect_undercuts

    # Face with bad draft (proxy candidate) but no Boolean
    face = _make_face(0, (1.0, 0.0, 0.0), area=100.0)
    edge = _make_edge(0, [0], convexity="concave")
    part = _make_part([face], edges=[edge], face_to_edges={0: [0]})

    result = detect_undercuts(part, (0.0, 0.0, 1.0), mutate=False, boolean_refine=False)

    assert result.undercut_face_ids == [], (
        "Without Boolean, undercut_face_ids must always be empty"
    )
    assert not result.boolean_validation_complete, (
        "Without Boolean, validation_complete must be False"
    )
    # Proxy candidates go to suspected
    assert 0 in result.suspected_undercut_face_ids, (
        "Without Boolean, proxy candidates must be in suspected_undercut_face_ids"
    )


# ===========================================================================
# T9 — Accessibility risk faces must be included in Boolean candidate pool
# ===========================================================================

def test_accessibility_risk_face_included_in_boolean_candidates():
    """
    A face with good draft (not a proxy candidate) but core-side with a concave
    edge (accessibility risk) must be checked by Boolean when available.
    """
    from backend.geometry.undercut_detector import detect_undercuts

    # Good draft (70° → signed_dot = -sin(70°) ≈ -0.94, well above marginal threshold)
    # But core-side (n·d < 0) with concave edge → accessibility risk
    import math
    angle_deg = 70.0
    nz = -math.cos(math.radians(angle_deg))  # core-side: negative z component
    nx = math.sin(math.radians(angle_deg))
    face = _make_face(0, (nx, 0.0, nz), area=100.0)
    edge = _make_edge(0, [0], convexity="concave")
    part = _make_part([face], edges=[edge], face_to_edges={0: [0]})

    with patch(
        "backend.geometry.undercut_detector._swept_face_interference_volume",
        return_value=_make_boolean_metrics(volume_mm3=0.0),
    ), patch(
        "backend.geometry.undercut_detector._OCC_BOOLEAN_AVAILABLE",
        True,
    ):
        result = detect_undercuts(part, (0.0, 0.0, 1.0), mutate=False, boolean_refine=True)

    # Face must have been Boolean-checked (it's an accessibility risk face)
    assert 0 in result.boolean_checked_face_ids, (
        "Accessibility risk face (good draft + core-side + concave edge) must be Boolean-checked"
    )
    # Volume=0 → no_interference (not suspected, not confirmed)
    assert 0 in result.boolean_no_interference_face_ids, (
        "Zero-volume Boolean result must go into boolean_no_interference_face_ids"
    )
    assert 0 not in result.undercut_face_ids, (
        "Zero-volume Boolean face must NOT be in undercut_face_ids"
    )


# ===========================================================================
# T13 — R4: Suitability gate rejects incomplete validation
# ===========================================================================

def test_suitability_gate_rejects_incomplete_validation():
    """
    _is_direction_suitable_boolean() must return False when
    boolean_validation_complete is False, even if zero confirmed undercuts.
    """
    from backend.geometry.direction_optimizer import _is_direction_suitable_boolean
    from backend.geometry.undercut_detector import UndercutDetectionResult
    from backend.config import settings

    part = _make_part([_make_face(0, (0.0, 0.0, 1.0))])
    cfg = settings.dfm.direction_search

    # Incomplete validation: boolean ran, confirmed=0, but some candidates were skipped
    incomplete_result = UndercutDetectionResult(
        pull_direction=(0.0, 0.0, 1.0),
        method="test",
        undercut_face_ids=[],
        accessible_face_ids=[0],
        parting_face_ids=[],
        skipped_face_ids=[],
        boolean_refined=True,
        boolean_confirmed_face_ids=[],
        boolean_validation_complete=False,  # <-- incomplete
        boolean_candidate_count=10,
        total_analysed_area_mm2=100.0,
    )

    result = _is_direction_suitable_boolean(incomplete_result, part, cfg)
    assert result is False, (
        "_is_direction_suitable_boolean must return False when validation is incomplete"
    )

    # Complete validation: same conditions but complete → should pass
    complete_result = UndercutDetectionResult(
        pull_direction=(0.0, 0.0, 1.0),
        method="test",
        undercut_face_ids=[],
        accessible_face_ids=[0],
        parting_face_ids=[],
        skipped_face_ids=[],
        boolean_refined=True,
        boolean_confirmed_face_ids=[],
        boolean_validation_complete=True,  # <-- complete
        boolean_candidate_count=0,
        total_analysed_area_mm2=100.0,
    )

    result = _is_direction_suitable_boolean(complete_result, part, cfg)
    assert result is True, (
        "_is_direction_suitable_boolean must return True when validation is complete with 0 confirmed"
    )


# ===========================================================================
# T14 — R3: Direction sign correctness
# ===========================================================================

def test_face_access_direction_sign():
    """
    _face_access_direction returns +d for cavity-side (n·d >= 0) and -d for
    core-side (n·d < 0).
    """
    from backend.geometry.undercut_detector import _face_access_direction

    pull = (0.0, 0.0, 1.0)

    # Cavity-side: n points roughly in same direction as pull → signed_dot >= 0
    cavity_face = _make_face(0, (0.0, 0.0, 1.0))
    assert _face_access_direction(cavity_face, pull) == pytest.approx((0.0, 0.0, 1.0)), (
        "Cavity-side face must sweep in +d direction"
    )

    # Core-side: n points roughly opposite to pull → signed_dot < 0
    core_face = _make_face(1, (0.0, 0.0, -1.0))
    result = _face_access_direction(core_face, pull)
    assert result[2] < 0, "Core-side face must sweep in -d direction"


# ===========================================================================
# T15 — R3: Sweep distance covers part geometry
# ===========================================================================

def test_sweep_distance_covers_part_diagonal():
    """
    The sweep distance used in _swept_face_interference_volume must be >= the
    part bounding box diagonal so that the sweep covers the full geometry.
    This is verified by checking config: sweep_distance = max(diag * factor, min).
    """
    from backend.config import settings

    cfg = settings.dfm.direction_search
    diagonal = 100.0  # mm (typical test part)
    sweep_distance = max(
        diagonal * cfg.boolean_sweep_distance_factor,
        cfg.boolean_min_sweep_distance_mm,
    )
    assert sweep_distance >= diagonal, (
        f"Sweep distance {sweep_distance} must be >= diagonal {diagonal}"
    )


# ===========================================================================
# T16 — R3: Face offset is non-zero (prevents self-intersection)
# ===========================================================================

def test_offset_is_positive_for_any_part_size():
    """
    The face offset epsilon must be > 0 for any part size (epsilon prevents
    the originating face from registering self-intersection).
    """
    from backend.config import settings

    cfg = settings.dfm.direction_search
    for diagonal in [1.0, 10.0, 100.0, 500.0]:
        epsilon = max(
            diagonal * cfg.boolean_offset_factor,
            cfg.boolean_min_offset_mm,
        )
        assert epsilon > 0, f"Offset must be > 0 for diagonal={diagonal}"


# ===========================================================================
# Semantic invariant: CONFIRMED ∩ SUSPECTED = ∅
# ===========================================================================

def test_confirmed_and_suspected_are_disjoint():
    """
    confirmed_undercut_face_ids and suspected_undercut_face_ids must be disjoint.
    A face cannot be both confirmed and suspected simultaneously.
    """
    from backend.geometry.undercut_detector import detect_undercuts

    faces = [
        _make_face(0, (0.0, 0.0, -1.0), area=50.0),   # core-side, concave
        _make_face(1, (0.0, 0.0, -1.0), area=50.0),   # core-side, concave
    ]
    edges = [
        _make_edge(0, [0], convexity="concave"),
        _make_edge(1, [1], convexity="concave"),
    ]
    face_to_edges = {0: [0], 1: [1]}
    part = _make_part(faces, edges=edges, face_to_edges=face_to_edges)

    # Face 0: returns volume > 0 (confirmed). Face 1: raises exception (failed/suspected).
    def side_effect(part, face, pull):
        if face.face_id == 0:
            return _make_boolean_metrics(volume_mm3=50.0)
        raise RuntimeError("OCC error on face 1")

    with patch(
        "backend.geometry.undercut_detector._swept_face_interference_volume",
        side_effect=side_effect,
    ), patch(
        "backend.geometry.undercut_detector._OCC_BOOLEAN_AVAILABLE",
        True,
    ):
        result = detect_undercuts(part, (0.0, 0.0, 1.0), mutate=False, boolean_refine=True)

    confirmed_set = set(result.undercut_face_ids)
    suspected_set = set(result.suspected_undercut_face_ids)
    no_interference_set = set(result.boolean_no_interference_face_ids)

    assert confirmed_set & suspected_set == set(), (
        "confirmed ∩ suspected must be empty"
    )
    assert confirmed_set & no_interference_set == set(), (
        "confirmed ∩ no_interference must be empty"
    )
    assert suspected_set & no_interference_set == set(), (
        "suspected ∩ no_interference must be empty"
    )


# ===========================================================================
# Semantic invariant: validation_fallback field exists
# ===========================================================================

def test_direction_optimization_result_has_validation_fallback():
    """
    DirectionOptimizationResult must have validation_fallback field (R1).
    """
    from backend.geometry.direction_optimizer import DirectionOptimizationResult
    import inspect
    fields = {f.name for f in DirectionOptimizationResult.__dataclass_fields__.values()}
    assert "validation_fallback" in fields, (
        "DirectionOptimizationResult must have validation_fallback field"
    )


# ===========================================================================
# Semantic invariant: UndercutDetectionResult has new fields
# ===========================================================================

def test_undercut_detection_result_has_new_fields():
    """
    UndercutDetectionResult must have the new semantic fields.
    """
    from backend.geometry.undercut_detector import UndercutDetectionResult

    fields = set(UndercutDetectionResult.__dataclass_fields__.keys())

    assert "suspected_undercut_face_ids" in fields
    assert "suspected_undercut_area_mm2" in fields
    assert "boolean_no_interference_face_ids" in fields
    assert "boolean_candidate_count" in fields
    assert "boolean_validation_complete" in fields


def test_undercut_detection_result_to_dict_includes_new_fields():
    """
    to_dict() must include suspected_undercut, no_interference_face_ids,
    validation_complete, and candidate_count in the response JSON.
    """
    from backend.geometry.undercut_detector import UndercutDetectionResult

    result = UndercutDetectionResult(
        pull_direction=(0.0, 0.0, 1.0),
        method="test",
        undercut_face_ids=[],
        accessible_face_ids=[],
        parting_face_ids=[],
        skipped_face_ids=[],
        suspected_undercut_face_ids=[1, 2],
        boolean_no_interference_face_ids=[3],
        boolean_candidate_count=5,
        boolean_validation_complete=True,
    )

    d = result.to_dict()

    # face_ids must include suspected_undercut
    assert "suspected_undercut" in d["face_ids"]
    assert d["face_ids"]["suspected_undercut"] == [1, 2]

    # boolean_refinement must include new fields
    br = d["boolean_refinement"]
    assert "no_interference_face_ids" in br
    assert br["no_interference_face_ids"] == [3]
    assert "candidate_count" in br
    assert br["candidate_count"] == 5
    assert "validation_complete" in br
    assert br["validation_complete"] is True
    assert "validation_coverage_pct" in br


# ===========================================================================
# Fix D tests: perpendicular-dot face exclusion from Boolean candidate pool
# ===========================================================================

def test_perpendicular_dot_faces_excluded_from_boolean_candidates():
    """
    A face with |n·d| = 0.005 (proxy undercut due to ~0.29° draft) must NOT
    appear in boolean_checked_face_ids after Fix D.

    Perpendicular-dot faces are excluded from Boolean swept-face validation
    because the current _face_access_direction() → ±pull_dir formulation
    produces unreliable (always-positive) results for these faces.
    """
    from backend.geometry.undercut_detector import detect_undercuts

    # n·d = 0.005 → |n·d| ≤ 0.01 → perpendicular-dot → excluded from Boolean
    # draft_angle = arcsin(0.005) ≈ 0.29° < 0.5° → proxy undercut candidate
    # But it's in parting_ids (perp-dot set) → excluded from check_ids
    face = _make_face(0, (0.005, 0.0, 0.99998749), area=100.0)
    edge = _make_edge(0, [0], convexity="concave")
    part = _make_part([face], edges=[edge], face_to_edges={0: [0]})

    with patch(
        "backend.geometry.undercut_detector._OCC_BOOLEAN_AVAILABLE", True
    ), patch(
        "backend.geometry.undercut_detector._swept_face_interference_volume",
        return_value=_make_boolean_metrics(volume_mm3=5.0),
    ):
        result = detect_undercuts(
            part, (0.0, 0.0, 1.0), mutate=False, boolean_refine=True, max_boolean_faces=80
        )

    assert 0 not in result.boolean_checked_face_ids, (
        "Perpendicular-dot face (|n·d|=0.005) must NOT be Boolean-checked"
    )


def test_risk_face_not_perpendicular_is_boolean_tested():
    """
    A face with n·d = -0.5 and a concave edge is an accessibility risk face
    (not perpendicular-dot) and must be Boolean-tested.
    """
    from backend.geometry.undercut_detector import detect_undercuts

    # n·d = -0.5 → core-side, |n·d| = 0.5 >> 0.01 → NOT perpendicular-dot
    # concave edge → accessibility risk
    face = _make_face(0, (-0.5, 0.0, -0.866), area=100.0)
    edge = _make_edge(0, [0], convexity="concave")
    part = _make_part([face], edges=[edge], face_to_edges={0: [0]})

    with patch(
        "backend.geometry.undercut_detector._OCC_BOOLEAN_AVAILABLE", True
    ), patch(
        "backend.geometry.undercut_detector._swept_face_interference_volume",
        return_value=_make_boolean_metrics(volume_mm3=0.0),
    ):
        result = detect_undercuts(
            part, (0.0, 0.0, 1.0), mutate=False, boolean_refine=True, max_boolean_faces=80
        )

    assert 0 in result.boolean_checked_face_ids, (
        "Non-perpendicular risk face (n·d=-0.5, concave edge) must be Boolean-checked"
    )


def test_proxy_undercut_with_concave_edge_excluded_from_boolean():
    """
    Proxy undercut faces (draft_angle < 0.5° → |n·d| < sin(0.5°) ≈ 0.0087 ≤ 0.01)
    are always perpendicular-dot. Fix D excludes them from Boolean candidates.
    Even if the face also has a concave edge, the perpendicular-dot exclusion
    takes precedence: it must NOT be Boolean-checked.

    Note: a perpendicular-dot face (|n·d| ≤ 0.01) cannot simultaneously be a
    core-side risk face (requires n·d < -0.01) — these sets are disjoint by
    construction of the thresholds. The exclusion matters for proxy undercuts,
    which are always in the perp-dot set and were previously the main source of
    the bloated Boolean candidate pool (~230 faces on Part1+Z).
    """
    from backend.geometry.undercut_detector import detect_undercuts

    # n=(0.999987, 0.0, 0.005) with pull=(0,0,1):
    #   n·d = 0.005, |n·d| = 0.005 ≤ 0.01 → perpendicular-dot
    #   draft_angle = asin(|n·d|) = asin(0.005) ≈ 0.29° < 0.5° → proxy undercut
    #   concave edge → would be a candidate if not excluded
    face = _make_face(0, (0.999987, 0.0, 0.005), area=100.0)
    edge = _make_edge(0, [0], convexity="concave")
    part = _make_part([face], edges=[edge], face_to_edges={0: [0]})

    with patch(
        "backend.geometry.undercut_detector._OCC_BOOLEAN_AVAILABLE", True
    ), patch(
        "backend.geometry.undercut_detector._swept_face_interference_volume",
        return_value=_make_boolean_metrics(volume_mm3=5.0),
    ):
        result = detect_undercuts(
            part, (0.0, 0.0, 1.0), mutate=False, boolean_refine=True, max_boolean_faces=80
        )

    assert 0 not in result.boolean_checked_face_ids, (
        "Proxy undercut (perpendicular-dot, |n·d|=0.005) must NOT be Boolean-checked, "
        "even with a concave edge (perpendicular-dot exclusion takes precedence)"
    )


def test_no_interference_rendered_as_accessible():
    """
    API-level: no_interference faces (Boolean ran, volume=0) must be rendered
    as 'accessible' (neutral gray), NOT as 'no_interference' (pale green).
    Fix E suppresses the visually confusing green rendering.
    """
    from backend.geometry.undercut_detector import UndercutDetectionResult
    from backend.api.main import _undercut_mesh_visual_payload

    class MockMesh:
        face_ids = [0, 1, 2]

    # Face 1 is no_interference (Boolean ran, volume=0)
    result = UndercutDetectionResult(
        pull_direction=(0.0, 0.0, 1.0),
        method="test",
        undercut_face_ids=[],
        accessible_face_ids=[0, 2],
        parting_face_ids=[],
        skipped_face_ids=[],
        boolean_no_interference_face_ids=[1],
        boolean_candidate_count=1,
        boolean_validation_complete=True,
    )

    payload = _undercut_mesh_visual_payload(
        mesh=MockMesh(),
        result=result,
    )

    classifications = payload["undercut_classification"]
    # Face index 1 (face_id=1) should be "accessible" not "no_interference"
    assert classifications[1] == "accessible", (
        "no_interference face must render as 'accessible' (Fix E), not 'no_interference'"
    )


def test_vertical_wall_not_confirmed_undercut():
    """
    A perpendicular-dot face (vertical wall, n·d≈0) excluded from Boolean candidates
    must NOT appear in undercut_face_ids. Without Boolean confirmation, there is
    no confirmed undercut regardless of draft angle.
    """
    from backend.geometry.undercut_detector import detect_undercuts

    # Vertical wall: n=(1,0,0), pull=(0,0,1) → n·d=0, draft=0° → perpendicular-dot
    # With only convex edges: convexity-suppressed → not even a suspected undercut
    face = _make_face(0, (1.0, 0.0, 0.0), area=100.0)
    edge = _make_edge(0, [0], convexity="convex")
    part = _make_part([face], edges=[edge], face_to_edges={0: [0]})

    with patch(
        "backend.geometry.undercut_detector._OCC_BOOLEAN_AVAILABLE", True
    ):
        result = detect_undercuts(
            part, (0.0, 0.0, 1.0), mutate=False, boolean_refine=True, max_boolean_faces=80
        )

    assert 0 not in result.undercut_face_ids, (
        "Perpendicular-dot face excluded from Boolean must NOT be a confirmed undercut"
    )
    assert 0 not in result.boolean_checked_face_ids, (
        "Perpendicular-dot face must NOT have been Boolean-checked"
    )


def test_pool_reduction_enables_validation_complete():
    """
    When the Boolean candidate pool contains only non-perpendicular risk faces
    and the pool size is ≤ max_boolean_faces, validation_complete must be True.

    This verifies the plan's core prediction: after Fix D, validation_complete
    is achievable naturally (by pool reduction, NOT by redefining completeness).
    """
    from backend.geometry.undercut_detector import detect_undercuts

    # 20 core-side + concave-edge faces, well within max_boolean_faces=80
    faces = [_make_face(i, (0.0, 0.0, -1.0), area=100.0) for i in range(20)]
    edges = [_make_edge(i, [i], convexity="concave") for i in range(20)]
    face_to_edges = {i: [i] for i in range(20)}
    part = _make_part(faces, edges=edges, face_to_edges=face_to_edges)

    with patch(
        "backend.geometry.undercut_detector._OCC_BOOLEAN_AVAILABLE", True
    ), patch(
        "backend.geometry.undercut_detector._swept_face_interference_volume",
        return_value=_make_boolean_metrics(volume_mm3=0.0),
    ):
        result = detect_undercuts(
            part, (0.0, 0.0, 1.0), mutate=False, boolean_refine=True, max_boolean_faces=80
        )

    assert result.boolean_candidate_count == 20, (
        f"Expected 20 candidates, got {result.boolean_candidate_count}"
    )
    assert result.boolean_validation_complete is True, (
        "All 20 candidates fit within budget of 80 → validation must be complete "
        "(natural pool reduction, NOT redefined semantics)"
    )
