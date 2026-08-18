"""
tests/test_undercut_detector.py
-------------------------------
Pure tests for first-pass undercut/accessibility recognition.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _make_face(face_id: int, normal: tuple[float, float, float], area: float = 100.0):
    from backend.models.geometry_models import FaceData

    return FaceData(
        face_id=face_id,
        occ_face=MagicMock(),
        surface_type="Plane",
        normal=normal,
        centroid=(float(face_id), 0.0, 0.0),
        area=area,
        u_range=(0.0, 1.0),
        v_range=(0.0, 1.0),
        is_reversed=False,
        normal_valid=True,
    )


def _make_part(faces, adjacency=None, edges=None, face_to_edges=None):
    from backend.models.geometry_models import BoundingBox, PartGeometry

    return PartGeometry(
        source_file="mock.stp",
        occ_shape=MagicMock(),
        faces=faces,
        bounding_box=BoundingBox(0.0, 0.0, 0.0, 10.0, 10.0, 10.0),
        face_count=len(faces),
        solid_count=1,
        shell_count=1,
        face_adjacency=adjacency or {},
        edges=edges or [],
        face_to_edges=face_to_edges or {},
    )


def _make_edge(edge_id: int, adjacent_face_ids: list[int], convexity=None):
    from backend.models.geometry_models import EdgeData

    return EdgeData(
        edge_id=edge_id,
        occ_edge=MagicMock(),
        edge_type="Line",
        length=1.0,
        adjacent_face_ids=adjacent_face_ids,
        start_vertex=(0.0, 0.0, 0.0),
        end_vertex=(1.0, 0.0, 0.0),
        is_seam=False,
        convexity=convexity,
    )


def test_detect_undercuts_flags_zero_draft_face():
    from backend.geometry.undercut_detector import detect_undercuts

    face = _make_face(0, (1.0, 0.0, 0.0))
    part = _make_part([face])

    # boolean_refine=False: occ_face is a MagicMock; without this guard the
    # mock would be fed into real BRepAlgoAPI_Common calls in a Docker/conda
    # environment with pythonocc-core installed, stalling for minutes.
    result = detect_undercuts(part, (0.0, 0.0, 1.0), mutate=True, boolean_refine=False)

    assert result.undercut_face_ids == [0]
    assert result.has_undercuts is True
    assert face.is_undercut is True


def test_convexity_suppression_clears_false_positive_with_all_nonconcave_edges():
    """
    A face with zero draft (angle=0 < marginal_threshold) whose bounding
    edges are ALL convex/tangent has no genuine pocket evidence — it should
    be cleared from the undercut set entirely, not just left as a proxy hit.
    """
    from backend.geometry.undercut_detector import detect_undercuts

    face = _make_face(0, (1.0, 0.0, 0.0))
    edges = [
        _make_edge(0, [0, 1], convexity="convex"),
        _make_edge(1, [0, 1], convexity="tangent"),
    ]
    part = _make_part([face], edges=edges, face_to_edges={0: [0, 1]})

    result = detect_undercuts(part, (0.0, 0.0, 1.0), mutate=True, boolean_refine=False)

    assert result.undercut_face_ids == []
    assert result.convexity_suppressed_face_ids == [0]
    assert result.accessible_face_ids == [0]
    assert face.is_undercut is False


def test_convexity_suppression_does_not_clear_genuine_pocket():
    """
    Same zero-draft face, but one bounding edge is concave — genuine pocket
    evidence. Must remain flagged as an undercut.
    """
    from backend.geometry.undercut_detector import detect_undercuts

    face = _make_face(0, (1.0, 0.0, 0.0))
    edges = [
        _make_edge(0, [0, 1], convexity="convex"),
        _make_edge(1, [0, 1], convexity="concave"),
    ]
    part = _make_part([face], edges=edges, face_to_edges={0: [0, 1]})

    result = detect_undercuts(part, (0.0, 0.0, 1.0), mutate=True, boolean_refine=False)

    assert result.undercut_face_ids == [0]
    assert result.convexity_suppressed_face_ids == []


def test_convexity_suppression_is_conservative_when_edges_unclassified():
    """
    Suppression requires POSITIVE evidence (all edges classified non-concave).
    An unclassified edge (convexity=None — e.g. OCC evaluation failed) must
    NOT be treated as "not concave, therefore suppress" — leave it flagged.
    """
    from backend.geometry.undercut_detector import detect_undercuts

    face = _make_face(0, (1.0, 0.0, 0.0))
    edges = [
        _make_edge(0, [0, 1], convexity="convex"),
        _make_edge(1, [0, 1], convexity=None),
    ]
    part = _make_part([face], edges=edges, face_to_edges={0: [0, 1]})

    result = detect_undercuts(part, (0.0, 0.0, 1.0), mutate=True, boolean_refine=False)

    assert result.undercut_face_ids == [0]
    assert result.convexity_suppressed_face_ids == []


def test_convexity_suppression_disabled_via_config(monkeypatch):
    """dfm.undercut.convexity_suppression_enabled=False must be a full kill switch."""
    import dataclasses

    import backend.geometry.undercut_detector as detector
    from backend.geometry.undercut_detector import detect_undercuts

    disabled = dataclasses.replace(
        detector.settings,
        dfm=dataclasses.replace(
            detector.settings.dfm,
            undercut=dataclasses.replace(
                detector.settings.dfm.undercut, convexity_suppression_enabled=False
            ),
        ),
    )
    monkeypatch.setattr(detector, "settings", disabled)

    face = _make_face(0, (1.0, 0.0, 0.0))
    edges = [
        _make_edge(0, [0, 1], convexity="convex"),
        _make_edge(1, [0, 1], convexity="tangent"),
    ]
    part = _make_part([face], edges=edges, face_to_edges={0: [0, 1]})

    result = detect_undercuts(part, (0.0, 0.0, 1.0), mutate=True, boolean_refine=False)

    assert result.undercut_face_ids == [0]
    assert result.convexity_suppressed_face_ids == []


def test_detect_undercuts_groups_adjacent_faces():
    from backend.geometry.undercut_detector import detect_undercuts

    faces = [
        _make_face(0, (1.0, 0.0, 0.0)),
        _make_face(1, (1.0, 0.0, 0.0)),
        _make_face(2, (0.0, 0.0, 1.0)),
    ]
    part = _make_part(faces, adjacency={0: [1], 1: [0], 2: []})

    # boolean_refine=False: mock OCC objects must not reach real Boolean calls.
    result = detect_undercuts(part, (0.0, 0.0, 1.0), mutate=True, boolean_refine=False)

    assert result.undercut_face_ids == [0, 1]
    assert len(result.features) == 1
    assert result.features[0].face_ids == [0, 1]


def test_boolean_proximity_grouping_merges_nearby_regions():
    from backend.geometry.undercut_detector import (
        BooleanInterferenceMetrics,
        BooleanShapeAnalysis,
        _group_undercut_faces_with_boolean_proximity,
    )

    faces = [
        _make_face(0, (1.0, 0.0, 0.0)),
        _make_face(1, (1.0, 0.0, 0.0)),
    ]
    part = _make_part(faces, adjacency={0: [], 1: []})
    metrics = {
        0: BooleanInterferenceMetrics(
            volume_mm3=1.0,
            depth_mm=1.0,
            shape_analysis=BooleanShapeAnalysis(
                available=True,
                bbox_min=(0.0, 0.0, 0.0),
                bbox_max=(1.0, 1.0, 1.0),
                bbox_dimensions=(1.0, 1.0, 1.0),
            ),
        ),
        1: BooleanInterferenceMetrics(
            volume_mm3=1.0,
            depth_mm=1.0,
            shape_analysis=BooleanShapeAnalysis(
                available=True,
                bbox_min=(1.05, 0.0, 0.0),
                bbox_max=(2.05, 1.0, 1.0),
                bbox_dimensions=(1.0, 1.0, 1.0),
            ),
        ),
    }

    result = _group_undercut_faces_with_boolean_proximity(part, [0, 1], metrics)

    assert result.groups == [[0, 1]]
    assert result.method == "face-adjacency + boolean-region-proximity"
    assert result.proximity_link_count == 1
    assert any("linked 0-1" in factor for factor in result.factors)


def test_boolean_proximity_grouping_keeps_far_regions_separate():
    from backend.geometry.undercut_detector import (
        BooleanInterferenceMetrics,
        BooleanShapeAnalysis,
        _group_undercut_faces_with_boolean_proximity,
    )

    faces = [
        _make_face(0, (1.0, 0.0, 0.0)),
        _make_face(1, (1.0, 0.0, 0.0)),
    ]
    part = _make_part(faces, adjacency={0: [], 1: []})
    metrics = {
        0: BooleanInterferenceMetrics(
            volume_mm3=1.0,
            depth_mm=1.0,
            shape_analysis=BooleanShapeAnalysis(
                available=True,
                bbox_min=(0.0, 0.0, 0.0),
                bbox_max=(1.0, 1.0, 1.0),
                bbox_dimensions=(1.0, 1.0, 1.0),
            ),
        ),
        1: BooleanInterferenceMetrics(
            volume_mm3=1.0,
            depth_mm=1.0,
            shape_analysis=BooleanShapeAnalysis(
                available=True,
                bbox_min=(5.0, 0.0, 0.0),
                bbox_max=(6.0, 1.0, 1.0),
                bbox_dimensions=(1.0, 1.0, 1.0),
            ),
        ),
    }

    result = _group_undercut_faces_with_boolean_proximity(part, [0, 1], metrics)

    assert result.groups == [[0], [1]]
    assert result.method == "face-adjacency"
    assert result.proximity_link_count == 0


def test_boolean_region_pair_interaction_detects_nested_and_overlapping():
    from backend.geometry.undercut_detector import (
        BooleanShapeAnalysis,
        _boolean_region_pair_interaction,
    )

    outer = BooleanShapeAnalysis(
        available=True,
        bbox_min=(0.0, 0.0, 0.0),
        bbox_max=(4.0, 4.0, 4.0),
        bbox_dimensions=(4.0, 4.0, 4.0),
    )
    inner = BooleanShapeAnalysis(
        available=True,
        bbox_min=(1.0, 1.0, 1.0),
        bbox_max=(2.0, 2.0, 2.0),
        bbox_dimensions=(1.0, 1.0, 1.0),
    )
    overlap = BooleanShapeAnalysis(
        available=True,
        bbox_min=(3.0, 0.0, 0.0),
        bbox_max=(5.0, 2.0, 2.0),
        bbox_dimensions=(2.0, 2.0, 2.0),
    )

    nested_type, nested_ratio = _boolean_region_pair_interaction(outer, inner)
    overlap_type, overlap_ratio = _boolean_region_pair_interaction(outer, overlap)

    assert nested_type == "nested"
    assert nested_ratio == 1.0
    assert overlap_type == "overlapping"
    assert overlap_ratio > 0.0


def test_boolean_grouping_reports_nested_interaction_counts():
    from backend.geometry.undercut_detector import (
        BooleanInterferenceMetrics,
        BooleanShapeAnalysis,
        _group_undercut_faces_with_boolean_proximity,
    )

    faces = [
        _make_face(0, (1.0, 0.0, 0.0)),
        _make_face(1, (1.0, 0.0, 0.0)),
    ]
    part = _make_part(faces, adjacency={0: [], 1: []})
    metrics = {
        0: BooleanInterferenceMetrics(
            volume_mm3=10.0,
            depth_mm=1.0,
            shape_analysis=BooleanShapeAnalysis(
                available=True,
                bbox_min=(0.0, 0.0, 0.0),
                bbox_max=(4.0, 4.0, 4.0),
                bbox_dimensions=(4.0, 4.0, 4.0),
            ),
        ),
        1: BooleanInterferenceMetrics(
            volume_mm3=1.0,
            depth_mm=0.5,
            shape_analysis=BooleanShapeAnalysis(
                available=True,
                bbox_min=(1.0, 1.0, 1.0),
                bbox_max=(2.0, 2.0, 2.0),
                bbox_dimensions=(1.0, 1.0, 1.0),
            ),
        ),
    }

    result = _group_undercut_faces_with_boolean_proximity(part, [0, 1], metrics)

    assert result.groups == [[0, 1]]
    assert result.nested_pair_count == 1
    assert result.interaction_pair_count == 1
    assert any("nested 0-1" in factor for factor in result.factors)


def test_detect_undercuts_mutate_false_preserves_faces():
    from backend.geometry.undercut_detector import detect_undercuts

    face = _make_face(0, (1.0, 0.0, 0.0))
    part = _make_part([face])

    # boolean_refine=False: mock OCC objects must not reach real Boolean calls.
    result = detect_undercuts(part, (0.0, 0.0, 1.0), mutate=False, boolean_refine=False)

    assert result.undercut_face_ids == [0]
    assert face.is_undercut is None


def test_boolean_confirmed_faces_become_feature_evidence(monkeypatch):
    import backend.geometry.undercut_detector as detector
    from backend.geometry.undercut_detector import detect_undercuts

    faces = [
        _make_face(0, (0.9999875, 0.0, 0.005), area=50.0),
        _make_face(1, (0.9999875, 0.0, 0.005), area=50.0),
    ]
    part = _make_part(faces, adjacency={0: [1], 1: [0]})

    monkeypatch.setattr(detector, "_OCC_BOOLEAN_AVAILABLE", True)
    monkeypatch.setattr(detector, "_swept_face_interference_volume", lambda *args, **kwargs: 25.0)

    result = detect_undercuts(
        part,
        (0.0, 0.0, 1.0),
        mutate=False,
        boolean_refine=True,
        max_boolean_faces=10,
    )

    assert result.boolean_refined is True
    assert result.boolean_confirmed_face_ids == [0, 1]
    assert len(result.features) == 1
    feature = result.features[0]
    assert feature.evidence_source == "boolean-confirmed"
    assert feature.boolean_confirmed_face_ids == [0, 1]
    assert feature.interference_volume_mm3 == 50.0
    assert feature.boolean_depth_proxy_mm == 0.5


def test_boolean_intersection_shape_is_attached_to_confirmed_feature(monkeypatch):
    import backend.geometry.undercut_detector as detector
    from backend.geometry.undercut_detector import (
        BooleanInterferenceMetrics,
        BooleanShapeAnalysis,
        detect_undercuts,
    )

    shape = MagicMock(name="boolean_intersection_shape")
    face = _make_face(0, (0.9999875, 0.0, 0.005), area=50.0)
    part = _make_part([face])

    def return_metrics(*args, **kwargs):
        return BooleanInterferenceMetrics(
            volume_mm3=25.0,
            depth_mm=1.25,
            depth_method="test-intersection-shape",
            intersection_shape=shape,
            shape_analysis=BooleanShapeAnalysis(
                available=True,
                vertex_count=8,
                edge_count=12,
                bbox_min=(0.0, 0.0, 0.0),
                bbox_max=(2.0, 3.0, 4.0),
                bbox_center=(1.0, 1.5, 2.0),
                bbox_dimensions=(2.0, 3.0, 4.0),
                center_of_mass=(1.0, 1.5, 2.0),
                volume_mm3=25.0,
                method="test-analysis",
            ),
        )

    monkeypatch.setattr(detector, "_OCC_BOOLEAN_AVAILABLE", True)
    monkeypatch.setattr(detector, "_swept_face_interference_volume", return_metrics)

    result = detect_undercuts(
        part,
        (0.0, 0.0, 1.0),
        mutate=False,
        boolean_refine=True,
        max_boolean_faces=10,
    )

    feature = result.features[0]
    assert feature.boolean_confirmed_face_ids == [0]
    assert feature.boolean_intersection_face_ids == [0]
    assert feature.boolean_intersection_shape is shape
    assert feature.boolean_intersection_shapes == [shape]
    intersection = feature.to_dict()["boolean_intersection"]
    assert intersection["available"] is True
    assert intersection["shape_count"] == 1
    assert intersection["face_ids"] == [0]
    assert intersection["geometry"]["available"] is True
    assert intersection["geometry"]["vertex_count"] == 8
    assert intersection["geometry"]["edge_count"] == 12
    assert intersection["geometry"]["bbox_dimensions"] == [2.0, 3.0, 4.0]
    assert intersection["geometry"]["center_of_mass"] == [1.0, 1.5, 2.0]


def test_detector_groups_disconnected_nearby_boolean_regions(monkeypatch):
    import backend.geometry.undercut_detector as detector
    from backend.geometry.undercut_detector import (
        BooleanInterferenceMetrics,
        BooleanShapeAnalysis,
        detect_undercuts,
    )

    faces = [
        _make_face(0, (0.9999875, 0.0, 0.005), area=50.0),
        _make_face(1, (0.9999875, 0.0, 0.005), area=50.0),
    ]
    part = _make_part(faces, adjacency={0: [], 1: []})

    def return_metrics(part, face, direction, **kwargs):
        if face.face_id == 0:
            bbox_min = (0.0, 0.0, 0.0)
            bbox_max = (1.0, 1.0, 1.0)
        else:
            bbox_min = (1.05, 0.0, 0.0)
            bbox_max = (2.05, 1.0, 1.0)
        return BooleanInterferenceMetrics(
            volume_mm3=5.0,
            depth_mm=1.0,
            intersection_shape=MagicMock(name=f"shape_{face.face_id}"),
            shape_analysis=BooleanShapeAnalysis(
                available=True,
                vertex_count=8,
                edge_count=12,
                bbox_min=bbox_min,
                bbox_max=bbox_max,
                bbox_center=(
                    (bbox_min[0] + bbox_max[0]) * 0.5,
                    0.5,
                    0.5,
                ),
                bbox_dimensions=(1.0, 1.0, 1.0),
                center_of_mass=(
                    (bbox_min[0] + bbox_max[0]) * 0.5,
                    0.5,
                    0.5,
                ),
                volume_mm3=5.0,
                method="test-analysis",
            ),
        )

    monkeypatch.setattr(detector, "_OCC_BOOLEAN_AVAILABLE", True)
    monkeypatch.setattr(detector, "_swept_face_interference_volume", return_metrics)

    result = detect_undercuts(
        part,
        (0.0, 0.0, 1.0),
        mutate=False,
        boolean_refine=True,
        max_boolean_faces=10,
    )

    assert len(result.features) == 1
    assert result.features[0].face_ids == [0, 1]
    assert result.features[0].grouping_method == "face-adjacency + boolean-region-proximity"
    assert any("linked 0-1" in factor for factor in result.features[0].grouping_factors)


def test_detector_marks_nested_boolean_regions_as_interacting(monkeypatch):
    import backend.geometry.undercut_detector as detector
    from backend.geometry.undercut_detector import (
        BooleanInterferenceMetrics,
        BooleanShapeAnalysis,
        detect_undercuts,
    )

    faces = [
        _make_face(0, (0.9999875, 0.0, 0.005), area=100.0),
        _make_face(1, (0.9999875, 0.0, 0.005), area=100.0),
    ]
    part = _make_part(faces, adjacency={0: [], 1: []})

    def return_metrics(_part, face, _pull_direction, **kwargs):
        if face.face_id == 0:
            return BooleanInterferenceMetrics(
                volume_mm3=20.0,
                depth_mm=2.0,
                intersection_shape=MagicMock(name="outer_boolean_shape"),
                shape_analysis=BooleanShapeAnalysis(
                    available=True,
                    bbox_min=(0.0, 0.0, 0.0),
                    bbox_max=(4.0, 4.0, 4.0),
                    bbox_dimensions=(4.0, 4.0, 4.0),
                    volume_mm3=20.0,
                ),
            )
        return BooleanInterferenceMetrics(
            volume_mm3=5.0,
            depth_mm=1.0,
            intersection_shape=MagicMock(name="inner_boolean_shape"),
            shape_analysis=BooleanShapeAnalysis(
                available=True,
                bbox_min=(1.0, 1.0, 1.0),
                bbox_max=(2.0, 2.0, 2.0),
                bbox_dimensions=(1.0, 1.0, 1.0),
                volume_mm3=5.0,
            ),
        )

    monkeypatch.setattr(detector, "_OCC_BOOLEAN_AVAILABLE", True)
    monkeypatch.setattr(detector, "_swept_face_interference_volume", return_metrics)

    result = detect_undercuts(
        part,
        (0.0, 0.0, 1.0),
        mutate=False,
        boolean_refine=True,
        max_boolean_faces=10,
    )

    assert len(result.features) == 1
    feature = result.features[0]
    assert feature.interaction_type == "nested"
    assert feature.geometric_feature_type == "complex/interacting-candidate"
    assert any("nested pair 0-1" in factor for factor in feature.interaction_factors)
    assert any("upgraded to complex/interacting" in factor for factor in feature.geometric_feature_factors)


def test_boolean_region_geometry_combines_shape_analyses():
    from backend.geometry.undercut_detector import (
        BooleanShapeAnalysis,
        _combine_boolean_region_geometry,
    )

    geometry = _combine_boolean_region_geometry(
        source_face_ids=[0, 1],
        analyses=[
            BooleanShapeAnalysis(
                available=True,
                vertex_count=4,
                edge_count=6,
                bbox_min=(0.0, 0.0, 0.0),
                bbox_max=(1.0, 2.0, 3.0),
                bbox_center=(0.5, 1.0, 1.5),
                bbox_dimensions=(1.0, 2.0, 3.0),
                center_of_mass=(0.5, 1.0, 1.5),
                volume_mm3=2.0,
                method="test-a",
            ),
            BooleanShapeAnalysis(
                available=True,
                vertex_count=8,
                edge_count=12,
                bbox_min=(2.0, -1.0, 1.0),
                bbox_max=(5.0, 4.0, 6.0),
                bbox_center=(3.5, 1.5, 3.5),
                bbox_dimensions=(3.0, 5.0, 5.0),
                center_of_mass=(3.5, 1.5, 3.5),
                volume_mm3=6.0,
                method="test-b",
            ),
        ],
    )

    assert geometry.available is True
    assert geometry.shape_count == 2
    assert geometry.source_face_ids == [0, 1]
    assert geometry.vertex_count == 12
    assert geometry.edge_count == 18
    assert geometry.bbox_min == (0.0, -1.0, 0.0)
    assert geometry.bbox_max == (5.0, 4.0, 6.0)
    assert geometry.bbox_dimensions == (5.0, 5.0, 6.0)
    assert geometry.center_of_mass == (2.75, 1.375, 3.0)
    assert geometry.volume_mm3 == 8.0


def test_boolean_intersection_metadata_is_safe_when_no_shape_available():
    from backend.geometry.undercut_detector import UndercutFeature

    feature = UndercutFeature(
        feature_id=0,
        face_ids=[0],
        undercut_type="unknown",
        severity="minor",
        evidence_source="proxy-only",
        type_classification_method="test",
        type_classification_score=0.0,
        type_classification_factors=[],
        release_direction=(1.0, 0.0, 0.0),
        location=(0.0, 0.0, 0.0),
        depth_proxy_mm=0.0,
        total_area_mm2=1.0,
        min_draft_angle_deg=0.0,
    )

    assert feature.boolean_intersection_shape is None
    intersection = feature.to_dict()["boolean_intersection"]
    assert intersection["available"] is False
    assert intersection["shape_count"] == 0
    assert intersection["face_ids"] == []
    assert intersection["geometry"]["available"] is False
    assert intersection["geometry"]["shape_count"] == 0


def test_boolean_candidate_faces_are_ranked_before_limit(monkeypatch):
    import backend.geometry.undercut_detector as detector
    from backend.geometry.undercut_detector import detect_undercuts

    checked: list[int] = []
    faces = [
        _make_face(0, (0.9999875, 0.0, 0.005), area=10.0),
        _make_face(1, (0.9999875, 0.0, 0.005), area=500.0),
    ]
    part = _make_part(faces)

    def record_boolean(part, face, direction, **kwargs):
        checked.append(face.face_id)
        return 25.0

    monkeypatch.setattr(detector, "_OCC_BOOLEAN_AVAILABLE", True)
    monkeypatch.setattr(detector, "_swept_face_interference_volume", record_boolean)

    result = detect_undercuts(
        part,
        (0.0, 0.0, 1.0),
        mutate=False,
        boolean_refine=True,
        max_boolean_faces=1,
    )

    assert checked == [1]
    assert result.boolean_checked_face_ids == [1]


def test_boolean_candidate_ranking_seeds_each_feature_group():
    from backend.geometry.undercut_detector import _rank_boolean_candidate_faces

    faces = [
        _make_face(0, (1.0, 0.0, 0.0), area=1000.0),
        _make_face(1, (1.0, 0.0, 0.0), area=900.0),
        _make_face(2, (1.0, 0.0, 0.0), area=100.0),
    ]
    part = _make_part(
        faces,
        adjacency={
            0: [1],
            1: [0],
            2: [],
        },
    )
    draft_results = {
        0: {"draft_angle_deg": 0.0},
        1: {"draft_angle_deg": 0.0},
        2: {"draft_angle_deg": 0.0},
    }

    ranked = _rank_boolean_candidate_faces(
        part=part,
        pull_direction=(0.0, 0.0, 1.0),
        candidate_face_ids=[0, 1, 2],
        draft_face_results=draft_results,
    )

    assert ranked[:3] == [0, 2, 1]


def test_boolean_feature_ranking_affects_faces_checked_under_small_budget(monkeypatch):
    import backend.geometry.undercut_detector as detector
    from backend.geometry.undercut_detector import detect_undercuts

    checked: list[int] = []
    faces = [
        _make_face(0, (0.9999875, 0.0, 0.005), area=1000.0),
        _make_face(1, (0.9999875, 0.0, 0.005), area=900.0),
        _make_face(2, (0.9999875, 0.0, 0.005), area=100.0),
    ]
    part = _make_part(
        faces,
        adjacency={
            0: [1],
            1: [0],
            2: [],
        },
    )

    def record_boolean(part, face, direction, **kwargs):
        checked.append(face.face_id)
        return 25.0

    monkeypatch.setattr(detector, "_OCC_BOOLEAN_AVAILABLE", True)
    monkeypatch.setattr(detector, "_swept_face_interference_volume", record_boolean)

    result = detect_undercuts(
        part,
        (0.0, 0.0, 1.0),
        mutate=False,
        boolean_refine=True,
        max_boolean_faces=2,
    )

    assert checked == [0, 2]
    assert result.boolean_checked_face_ids == [0, 2]


def test_boolean_metrics_cache_reuses_previous_result(monkeypatch):
    import backend.geometry.undercut_detector as detector
    from backend.geometry.undercut_detector import detect_undercuts

    calls = 0
    face = _make_face(0, (0.9999875, 0.0, 0.005))
    part = _make_part([face])
    cache = {}

    def count_boolean(*args, **kwargs):
        nonlocal calls
        calls += 1
        return 25.0

    monkeypatch.setattr(detector, "_OCC_BOOLEAN_AVAILABLE", True)
    monkeypatch.setattr(detector, "_swept_face_interference_volume", count_boolean)

    first = detect_undercuts(
        part,
        (0.0, 0.0, 1.0),
        mutate=False,
        boolean_refine=True,
        boolean_volume_cache=cache,
    )
    second = detect_undercuts(
        part,
        (0.0, 0.0, 1.0),
        mutate=False,
        boolean_refine=True,
        boolean_volume_cache=cache,
    )

    assert calls == 1
    assert first.boolean_cache_misses == 1
    assert second.boolean_cache_hits == 1
    assert second.interference_volume_mm3 == 25.0


def test_boolean_failure_retain_proxy_with_reason(monkeypatch):
    import backend.geometry.undercut_detector as detector
    from backend.geometry.undercut_detector import detect_undercuts

    face = _make_face(0, (0.9999875, 0.0, 0.005))
    part = _make_part([face])

    def fail_boolean(*args, **kwargs):
        raise RuntimeError("mock Boolean failure")

    monkeypatch.setattr(detector, "_OCC_BOOLEAN_AVAILABLE", True)
    monkeypatch.setattr(detector, "_swept_face_interference_volume", fail_boolean)

    result = detect_undercuts(
        part,
        (0.0, 0.0, 1.0),
        mutate=False,
        boolean_refine=True,
        max_boolean_faces=10,
    )

    assert result.undercut_face_ids == [0]
    assert result.boolean_failed_face_ids == [0]
    assert result.boolean_failure_reasons == {0: "mock Boolean failure"}
    assert result.boolean_failure_details[0]["reason"] == "OCC swept Boolean failed."
    assert result.boolean_failure_details[0]["failure_class"] == "unknown"
    assert result.boolean_failure_details[0]["attempt_count"] >= 1
    assert result.boolean_failure_details[0]["fallback_action"] == "proxy-retained-after-boolean-failure"
    assert result.features[0].evidence_source == "proxy-retained-after-boolean-failure"
    assert result.features[0].recommended_mold_action == "manual-review"
    assert result.features[0].action_confidence_label == "low"
    reliability = result.to_dict()["boolean_refinement"]["reliability"]
    assert reliability["reliability_level"] == "low"
    assert reliability["proxy_retained_face_count"] == 1
    assert reliability["failure_class_counts"] == {"unknown": 1}
    assert "proxy-heavy" in reliability["reliability_label"].lower()
    assert any(
        "Boolean failure" in factor
        for factor in result.features[0].action_confidence_factors
    )


def test_sliver_faces_are_skipped_but_proxy_retained(monkeypatch):
    import backend.geometry.undercut_detector as detector
    from backend.geometry.undercut_detector import detect_undercuts

    calls = 0
    face = _make_face(0, (1.0, 0.0, 0.0), area=1e-8)
    part = _make_part([face])

    def should_not_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        return 25.0

    monkeypatch.setattr(detector, "_OCC_BOOLEAN_AVAILABLE", True)
    monkeypatch.setattr(detector, "_swept_face_interference_volume", should_not_run)

    result = detect_undercuts(
        part,
        (0.0, 0.0, 1.0),
        mutate=False,
        boolean_refine=True,
        max_boolean_faces=10,
    )

    assert calls == 0
    assert result.undercut_face_ids == [0]
    assert result.boolean_checked_face_ids == []
    assert result.boolean_skipped_face_ids == [0]
    assert 0 in result.boolean_skip_reasons
    assert result.features[0].evidence_source == "proxy-retained-after-boolean-skip"
    assert result.features[0].boolean_skipped_face_ids == [0]


def test_boolean_failure_info_preserves_attempt_diagnostics():
    from backend.geometry.undercut_detector import (
        BooleanAttemptInfo,
        _failure_info_from_attempts,
    )

    attempts = [
        BooleanAttemptInfo(
            attempt_index=1,
            offset_mm=0.001,
            fuzzy_value=0.0001,
            status="failed",
            error="offset face is null",
            elapsed_s=0.01,
        ),
        BooleanAttemptInfo(
            attempt_index=2,
            offset_mm=0.005,
            fuzzy_value=0.0005,
            status="failed",
            error="OCC common operation failed",
            elapsed_s=0.02,
        ),
    ]

    info = _failure_info_from_attempts(attempts)
    data = info.to_dict()

    assert info.failure_class == "boolean-common-failure"
    assert info.attempt_count == 2
    assert info.last_error == "OCC common operation failed"
    assert data["attempts"][0]["status"] == "failed"
    assert data["attempts"][1]["offset_mm"] == 0.005
    assert data["fallback_action"] == "proxy-retained-after-boolean-failure"


def test_boolean_error_classification_is_specific():
    from backend.geometry.undercut_detector import _classify_boolean_error

    assert _classify_boolean_error("OCC Boolean tools are unavailable") == "occ-runtime-unavailable"
    assert _classify_boolean_error("offset face is null") == "transform-failure"
    assert _classify_boolean_error("swept prism is null") == "sweep-construction-failure"
    assert _classify_boolean_error("OCC common operation failed") == "boolean-common-failure"
    assert _classify_boolean_error("shape has sliver tolerance instability") == "tolerance-or-sliver-instability"
    assert _classify_boolean_error("Boolean timed out") == "timeout-or-performance-risk"
    assert _classify_boolean_error("volume properties failed") == "volume-evaluation-failure"
    assert _classify_boolean_error("unexpected") == "unknown"


def test_boolean_performance_summary_reports_slow_faces_and_cache_rate():
    from backend.geometry.undercut_detector import (
        BooleanFailureInfo,
        BooleanInterferenceMetrics,
        _build_boolean_performance_summary,
    )

    summary = _build_boolean_performance_summary(
        checked_face_ids=[0, 1, 2],
        failed_face_ids=[2],
        skipped_face_ids=[3],
        metrics_by_face={
            0: BooleanInterferenceMetrics(
                volume_mm3=5.0,
                depth_mm=1.0,
                elapsed_s=0.02,
                attempt_count=1,
                depth_method="vertex-reference",
            ),
            1: BooleanInterferenceMetrics(
                volume_mm3=10.0,
                depth_mm=2.0,
                elapsed_s=0.08,
                attempt_count=3,
                depth_method="bbox-reference",
            ),
        },
        failure_details={
            2: BooleanFailureInfo(
                reason="OCC swept Boolean failed.",
                failure_class="boolean-common-failure",
                attempt_count=2,
                last_error="mock failure",
            )
        },
        cache_hits=1,
        cache_misses=2,
        elapsed_s=0.10,
    )
    data = summary.to_dict()

    assert data["checked_count"] == 3
    assert data["successful_count"] == 2
    assert data["failed_count"] == 1
    assert data["skipped_count"] == 1
    assert data["cache_hit_rate"] == 0.3333
    assert data["total_success_attempts"] == 4
    assert data["total_failed_attempts"] == 2
    assert data["slow_faces"][0]["face_id"] == 1
    assert data["slow_faces"][0]["depth_method"] == "bbox-reference"


def test_undercut_result_includes_boolean_performance_json():
    from backend.geometry.undercut_detector import (
        BooleanInterferenceMetrics,
        _build_boolean_performance_summary,
        UndercutDetectionResult,
    )

    performance = _build_boolean_performance_summary(
        checked_face_ids=[0],
        failed_face_ids=[],
        skipped_face_ids=[],
        metrics_by_face={
            0: BooleanInterferenceMetrics(
                volume_mm3=1.0,
                depth_mm=0.5,
                elapsed_s=0.01,
                attempt_count=1,
            )
        },
        failure_details={},
        cache_hits=0,
        cache_misses=1,
        elapsed_s=0.01,
    )
    result = UndercutDetectionResult(
        pull_direction=(0.0, 0.0, 1.0),
        method="test",
        undercut_face_ids=[],
        accessible_face_ids=[],
        parting_face_ids=[],
        skipped_face_ids=[],
        boolean_refined=True,
        boolean_checked_face_ids=[0],
        boolean_cache_misses=1,
        boolean_time_s=0.01,
        boolean_performance=performance,
    )

    data = result.to_dict()["boolean_refinement"]

    assert data["performance"]["checked_count"] == 1
    assert data["performance"]["slow_faces"][0]["face_id"] == 0


def test_boolean_success_without_interference_is_high_reliability(monkeypatch):
    import backend.geometry.undercut_detector as detector
    from backend.geometry.undercut_detector import detect_undercuts

    face = _make_face(0, (0.9999875, 0.0, 0.005))
    part = _make_part([face])

    monkeypatch.setattr(detector, "_OCC_BOOLEAN_AVAILABLE", True)
    monkeypatch.setattr(detector, "_swept_face_interference_volume", lambda *args, **kwargs: 0.0)

    result = detect_undercuts(
        part,
        (0.0, 0.0, 1.0),
        mutate=False,
        boolean_refine=True,
        max_boolean_faces=10,
    )
    reliability = result.to_dict()["boolean_refinement"]["reliability"]

    assert result.undercut_face_ids == []
    assert reliability["reliability_level"] == "high"
    assert reliability["successful_operation_ratio"] == 1.0
    assert reliability["confirmed_count"] == 0
    assert reliability["summary"].startswith("Boolean refinement completed")


def test_boolean_reliability_reports_sliver_skip_proxy_retention(monkeypatch):
    import backend.geometry.undercut_detector as detector
    from backend.geometry.undercut_detector import detect_undercuts

    face = _make_face(0, (1.0, 0.0, 0.0), area=1e-8)
    part = _make_part([face])

    monkeypatch.setattr(detector, "_OCC_BOOLEAN_AVAILABLE", True)

    result = detect_undercuts(
        part,
        (0.0, 0.0, 1.0),
        mutate=False,
        boolean_refine=True,
        max_boolean_faces=10,
    )
    reliability = result.to_dict()["boolean_refinement"]["reliability"]

    assert reliability["proxy_retained_skipped_count"] == 1
    assert reliability["skip_reason_counts"] == {"sliver-or-small-face": 1}
    assert "skipped 1 face" in reliability["summary"]


def test_boolean_depth_selection_prefers_vertex_reference():
    from backend.geometry.undercut_detector import _select_boolean_depth

    depth, method, reference_depth, span_depth = _select_boolean_depth(
        vertex_reference_depth=4.0,
        vertex_span_depth=2.0,
        bbox_reference_depth=9.0,
        bbox_span_depth=8.0,
        volume_area_depth=12.0,
    )

    assert depth == 4.0
    assert method == "vertex-reference"
    assert reference_depth == 4.0
    assert span_depth == 2.0


def test_boolean_depth_selection_keeps_reference_over_suspicious_span():
    from backend.geometry.undercut_detector import _select_boolean_depth_details

    estimate = _select_boolean_depth_details(
        vertex_reference_depth=2.0,
        vertex_span_depth=8.0,
        bbox_reference_depth=0.0,
        bbox_span_depth=0.0,
        volume_area_depth=12.0,
    )

    assert estimate.depth_mm == 2.0
    assert estimate.method == "vertex-reference"
    assert any("span exceeds reference" in factor for factor in estimate.factors)
    assert any("volume/area fallback exceeded" in factor for factor in estimate.factors)


def test_boolean_depth_selection_uses_bbox_when_vertices_absent():
    from backend.geometry.undercut_detector import _select_boolean_depth

    depth, method, reference_depth, span_depth = _select_boolean_depth(
        vertex_reference_depth=0.0,
        vertex_span_depth=0.0,
        bbox_reference_depth=3.0,
        bbox_span_depth=5.0,
        volume_area_depth=1.0,
    )

    assert depth == 3.0
    assert method == "bbox-reference"
    assert reference_depth == 3.0
    assert span_depth == 5.0


def test_boolean_depth_selection_falls_back_to_volume_area():
    from backend.geometry.undercut_detector import _select_boolean_depth

    depth, method, reference_depth, span_depth = _select_boolean_depth(
        vertex_reference_depth=0.0,
        vertex_span_depth=0.0,
        bbox_reference_depth=0.0,
        bbox_span_depth=0.0,
        volume_area_depth=0.25,
    )

    assert depth == 0.25
    assert method == "volume-area"
    assert reference_depth == 0.0
    assert span_depth == 0.0


def test_boolean_depth_details_exposes_all_candidate_evidence():
    from backend.geometry.undercut_detector import _select_boolean_depth_details

    estimate = _select_boolean_depth_details(
        vertex_reference_depth=0.0,
        vertex_span_depth=0.0,
        bbox_reference_depth=0.0,
        bbox_span_depth=3.0,
        volume_area_depth=1.0,
    )
    data = estimate.to_dict()

    assert data["method"] == "bbox-span"
    assert data["depth_mm"] == 3.0
    assert data["evidence"]["bbox_span_depth_mm"] == 3.0
    assert "selected bbox span" in " ".join(data["factors"])


def test_action_confidence_is_high_for_boolean_vertex_evidence():
    from backend.geometry.undercut_detector import _score_action_confidence

    confidence, factors = _score_action_confidence(
        undercut_type="internal/core-side",
        severity="critical",
        evidence_source="boolean-confirmed",
        pull_alignment=0.1,
        depth_proxy_mm=3.0,
        interference_volume_mm3=25.0,
        boolean_depth_method="vertex-reference",
    )

    assert confidence >= 0.75
    assert "Boolean-confirmed interference" in factors
    assert "depth from vertex-reference" in factors


def test_action_confidence_breakdown_explains_impacts():
    from backend.geometry.undercut_detector import _build_action_confidence_breakdown

    breakdown = _build_action_confidence_breakdown(
        undercut_type="internal/core-side",
        severity="critical",
        evidence_source="boolean-confirmed",
        pull_alignment=0.1,
        depth_proxy_mm=3.0,
        interference_volume_mm3=25.0,
        boolean_depth_method="vertex-reference",
        type_classification_score=0.82,
        type_classification_method="area-weighted-normal-consensus",
    )
    data = breakdown.to_dict()

    assert data["label"] == "high"
    assert data["final_score"] >= 0.75
    assert any(term["code"] == "evidence.boolean_confirmed" for term in data["terms"])
    assert any(term["impact"] > 0.0 for term in data["positive_terms"])
    assert "Boolean-confirmed interference" in data["summary"]


def test_action_confidence_is_low_for_failed_unknown_evidence():
    from backend.geometry.undercut_detector import _score_action_confidence

    confidence, factors = _score_action_confidence(
        undercut_type="unknown",
        severity="minor",
        evidence_source="proxy-retained-after-boolean-failure",
        pull_alignment=0.55,
        depth_proxy_mm=0.0,
        interference_volume_mm3=0.0,
        boolean_depth_method="none",
    )

    assert confidence < 0.45
    assert "Boolean failure reduced confidence" in factors
    assert "unknown undercut type" in factors


def test_mold_action_recommendation_includes_plain_english_explanation():
    from backend.geometry.undercut_detector import _recommend_mold_action

    recommendation = _recommend_mold_action(
        undercut_type="internal/core-side",
        severity="critical",
        evidence_source="boolean-confirmed",
        release_direction=(1.0, 0.0, 0.0),
        pull_direction=(0.0, 0.0, 1.0),
        depth_proxy_mm=3.0,
        interference_volume_mm3=25.0,
        boolean_depth_method="vertex-reference",
        type_classification_score=0.82,
        type_classification_method="area-weighted-normal-consensus",
    )

    assert recommendation.action == "lifter-or-collapsible-core-review"
    assert recommendation.confidence_label == "high"
    assert recommendation.confidence_breakdown["label"] == "high"
    assert "Release alignment to main pull is" in recommendation.explanation
    assert "Boolean interference volume is" in recommendation.explanation


def test_type_classification_uses_area_weighted_normal_consensus():
    from backend.geometry.undercut_detector import _classify_undercut_type

    faces = [
        _make_face(0, (0.0, 0.0, -1.0), area=900.0),
        _make_face(1, (0.0, 0.0, 1.0), area=100.0),
    ]
    part = _make_part(faces)

    result = _classify_undercut_type(faces, (0.0, 0.0, 1.0), part)

    assert result.undercut_type == "internal/core-side"
    assert result.method == "area-weighted-normal-consensus"
    assert result.score >= 0.75
    assert any("negative signed-normal consensus" in factor for factor in result.factors)


def test_type_classification_uses_radial_secondary_for_mixed_features():
    from backend.geometry.undercut_detector import _classify_undercut_type

    faces = [
        _make_face(8, (0.8, 0.0, 0.6), area=550.0),
        _make_face(9, (0.8, 0.0, -0.6), area=450.0),
    ]
    part = _make_part(faces)

    result = _classify_undercut_type(faces, (0.0, 0.0, 1.0), part)

    assert result.undercut_type == "external/cavity-side"
    assert result.method == "radial-normal-secondary"
    assert any("feature normals point away" in factor for factor in result.factors)
    assert any("radial evidence applicable" in factor for factor in result.factors)


def test_type_classification_uses_radial_secondary_for_internal_mixed_features():
    from backend.geometry.undercut_detector import _classify_undercut_type

    faces = [
        _make_face(8, (-0.8, 0.0, -0.6), area=550.0),
        _make_face(9, (-0.8, 0.0, 0.6), area=450.0),
    ]
    part = _make_part(faces)

    result = _classify_undercut_type(faces, (0.0, 0.0, 1.0), part)

    assert result.undercut_type == "internal/core-side"
    assert result.method == "radial-normal-secondary"
    assert any("feature normals point toward" in factor for factor in result.factors)
    assert any("radial evidence indicates internal" in factor for factor in result.factors)


def test_type_classification_preserves_true_silhouette():
    from backend.geometry.undercut_detector import _classify_undercut_type

    faces = [_make_face(0, (1.0, 0.0, 0.0), area=100.0)]
    part = _make_part(faces)

    result = _classify_undercut_type(faces, (0.0, 0.0, 1.0), part)

    assert result.undercut_type == "side-wall/silhouette"
    assert result.method == "silhouette-normal-distribution"
    assert any("dominant near-zero" in factor for factor in result.factors)


def test_type_classification_does_not_use_radial_for_pure_side_wall():
    from backend.geometry.undercut_detector import _classify_undercut_type

    faces = [
        _make_face(0, (1.0, 0.0, 0.0), area=600.0),
        _make_face(1, (1.0, 0.0, 0.0), area=400.0),
    ]
    part = _make_part(faces)

    result = _classify_undercut_type(faces, (0.0, 0.0, 1.0), part)

    assert result.undercut_type == "side-wall/silhouette"
    assert result.method == "silhouette-normal-distribution"


def test_boolean_geometry_refines_release_direction_and_depth():
    from backend.geometry.undercut_detector import (
        BooleanRegionGeometry,
        _estimate_release_and_depth_from_boolean_geometry,
    )

    face = _make_face(0, (0.0, 1.0, 0.0), area=100.0)
    part = _make_part([face])
    geometry = BooleanRegionGeometry(
        available=True,
        shape_count=1,
        source_face_ids=[0],
        bbox_min=(0.0, -0.5, -0.5),
        bbox_max=(4.0, 0.5, 0.5),
        bbox_center=(2.0, 0.0, 0.0),
        bbox_dimensions=(4.0, 1.0, 1.0),
        center_of_mass=(4.0, 0.0, 0.0),
        volume_mm3=20.0,
    )

    estimate = _estimate_release_and_depth_from_boolean_geometry(
        faces=[face],
        pull_direction=(0.0, 0.0, 1.0),
        part=part,
        geometry=geometry,
        fallback_release_direction=(0.0, 1.0, 0.0),
        fallback_depth_mm=1.0,
    )

    assert estimate.release_direction == (1.0, 0.0, 0.0)
    assert estimate.release_direction_method == "boolean-region-center-transverse"
    assert estimate.depth_mm == 4.0
    assert estimate.depth_method == "boolean-region-release-span"
    assert any("region center offset" in factor for factor in estimate.factors)


def test_boolean_geometry_falls_back_when_unavailable():
    from backend.geometry.undercut_detector import (
        BooleanRegionGeometry,
        _estimate_release_and_depth_from_boolean_geometry,
    )

    face = _make_face(0, (0.0, 1.0, 0.0), area=100.0)
    part = _make_part([face])

    estimate = _estimate_release_and_depth_from_boolean_geometry(
        faces=[face],
        pull_direction=(0.0, 0.0, 1.0),
        part=part,
        geometry=BooleanRegionGeometry(),
        fallback_release_direction=(0.0, 1.0, 0.0),
        fallback_depth_mm=1.25,
    )

    assert estimate.release_direction == (0.0, 1.0, 0.0)
    assert estimate.release_direction_method == "normal-transverse-fallback"
    assert estimate.depth_mm == 1.25
    assert estimate.depth_method == "projection-or-boolean-depth"


def test_geometric_feature_typing_identifies_hook_candidate():
    from backend.geometry.undercut_detector import (
        BooleanRegionGeometry,
        _classify_boolean_geometric_feature,
    )

    part = _make_part([_make_face(0, (1.0, 0.0, 0.0))])
    classification = _classify_boolean_geometric_feature(
        geometry=BooleanRegionGeometry(
            available=True,
            shape_count=1,
            source_face_ids=[0],
            vertex_count=8,
            edge_count=12,
            bbox_min=(0.0, -0.5, -0.2),
            bbox_max=(5.0, 0.5, 0.2),
            bbox_dimensions=(5.0, 1.0, 0.4),
            volume_mm3=2.0,
        ),
        pull_direction=(0.0, 0.0, 1.0),
        release_direction=(1.0, 0.0, 0.0),
        part=part,
        undercut_type="side-wall/silhouette",
        face_count=1,
    )

    assert classification.feature_type == "hook/undercut-ledge-candidate"
    assert classification.confidence_label in {"medium", "high"}
    assert classification.method == "boolean-region-release-span-flatness-rule"


def test_geometric_feature_typing_identifies_annular_candidate():
    from backend.geometry.undercut_detector import (
        BooleanRegionGeometry,
        _classify_boolean_geometric_feature,
    )

    part = _make_part([_make_face(0, (1.0, 0.0, 0.0))])
    classification = _classify_boolean_geometric_feature(
        geometry=BooleanRegionGeometry(
            available=True,
            shape_count=1,
            source_face_ids=[0],
            vertex_count=16,
            edge_count=24,
            bbox_min=(-2.0, -2.0, -0.4),
            bbox_max=(2.0, 2.0, 0.4),
            bbox_dimensions=(4.0, 4.0, 0.8),
            volume_mm3=12.0,
        ),
        pull_direction=(0.0, 0.0, 1.0),
        release_direction=(1.0, 0.0, 0.0),
        part=part,
        undercut_type="external/cavity-side",
        face_count=1,
    )

    assert classification.feature_type == "annular/ring-candidate"
    assert classification.method == "boolean-region-balanced-topology-rule"


def test_geometric_feature_typing_identifies_through_feature_candidate():
    from backend.geometry.undercut_detector import (
        BooleanRegionGeometry,
        _classify_boolean_geometric_feature,
    )

    part = _make_part([_make_face(0, (1.0, 0.0, 0.0))])
    classification = _classify_boolean_geometric_feature(
        geometry=BooleanRegionGeometry(
            available=True,
            shape_count=1,
            source_face_ids=[0, 1],
            vertex_count=12,
            edge_count=18,
            bbox_min=(0.0, 0.0, 0.0),
            bbox_max=(1.0, 1.0, 8.0),
            bbox_dimensions=(1.0, 1.0, 8.0),
            volume_mm3=8.0,
        ),
        pull_direction=(0.0, 0.0, 1.0),
        release_direction=(1.0, 0.0, 0.0),
        part=part,
        undercut_type="internal/core-side",
        face_count=2,
    )

    assert classification.feature_type == "through-feature-candidate"
    assert classification.method == "boolean-region-through-span-rule"


def test_geometric_feature_typing_identifies_pocket_candidate():
    from backend.geometry.undercut_detector import (
        BooleanRegionGeometry,
        _classify_boolean_geometric_feature,
    )

    part = _make_part([_make_face(0, (1.0, 0.0, 0.0))])
    classification = _classify_boolean_geometric_feature(
        geometry=BooleanRegionGeometry(
            available=True,
            shape_count=1,
            source_face_ids=[0],
            vertex_count=8,
            edge_count=12,
            bbox_min=(0.0, 0.0, 0.0),
            bbox_max=(1.0, 1.2, 1.4),
            bbox_dimensions=(1.0, 1.2, 1.4),
            volume_mm3=1.0,
        ),
        pull_direction=(0.0, 0.0, 1.0),
        release_direction=(1.0, 0.0, 0.0),
        part=part,
        undercut_type="internal/core-side",
        face_count=1,
    )

    assert classification.feature_type == "pocket/blind-undercut-candidate"
    assert classification.method == "boolean-region-local-compactness-rule"


def test_geometric_feature_typing_avoids_annular_for_low_topology_flat_plate():
    from backend.geometry.undercut_detector import (
        BooleanRegionGeometry,
        _classify_boolean_geometric_feature,
    )

    part = _make_part([_make_face(0, (1.0, 0.0, 0.0))])
    classification = _classify_boolean_geometric_feature(
        geometry=BooleanRegionGeometry(
            available=True,
            shape_count=1,
            source_face_ids=[0],
            vertex_count=8,
            edge_count=12,
            bbox_min=(-2.0, -2.0, -0.2),
            bbox_max=(2.0, 2.0, 0.2),
            bbox_dimensions=(4.0, 4.0, 0.4),
            volume_mm3=4.0,
        ),
        pull_direction=(0.0, 0.0, 1.0),
        release_direction=(1.0, 0.0, 0.0),
        part=part,
        undercut_type="external/cavity-side",
        face_count=1,
    )

    assert classification.feature_type != "annular/ring-candidate"
    assert "topology_density" in " ".join(classification.factors)


def test_geometric_feature_typing_avoids_pocket_for_elongated_local_region():
    from backend.geometry.undercut_detector import (
        BooleanRegionGeometry,
        _classify_boolean_geometric_feature,
    )

    part = _make_part([_make_face(0, (1.0, 0.0, 0.0))])
    classification = _classify_boolean_geometric_feature(
        geometry=BooleanRegionGeometry(
            available=True,
            shape_count=1,
            source_face_ids=[0],
            vertex_count=8,
            edge_count=12,
            bbox_min=(0.0, 0.0, 0.0),
            bbox_max=(5.0, 1.0, 1.0),
            bbox_dimensions=(5.0, 1.0, 1.0),
            volume_mm3=3.0,
        ),
        pull_direction=(0.0, 0.0, 1.0),
        release_direction=(1.0, 0.0, 0.0),
        part=part,
        undercut_type="side-wall/silhouette",
        face_count=1,
    )

    assert classification.feature_type != "pocket/blind-undercut-candidate"
    assert classification.feature_type == "hook/undercut-ledge-candidate"


def test_geometric_feature_typing_avoids_through_when_pull_does_not_dominate():
    from backend.geometry.undercut_detector import (
        BooleanRegionGeometry,
        _classify_boolean_geometric_feature,
    )

    part = _make_part([_make_face(0, (1.0, 0.0, 0.0))])
    classification = _classify_boolean_geometric_feature(
        geometry=BooleanRegionGeometry(
            available=True,
            shape_count=1,
            source_face_ids=[0, 1],
            vertex_count=12,
            edge_count=18,
            bbox_min=(0.0, 0.0, 0.0),
            bbox_max=(6.0, 1.0, 7.0),
            bbox_dimensions=(6.0, 1.0, 7.0),
            volume_mm3=16.0,
        ),
        pull_direction=(0.0, 0.0, 1.0),
        release_direction=(1.0, 0.0, 0.0),
        part=part,
        undercut_type="internal/core-side",
        face_count=2,
    )

    assert classification.feature_type != "through-feature-candidate"
    assert "pull_to_part_ratio" in " ".join(classification.factors)


def test_feature_semantics_identify_side_action_for_side_wall():
    from backend.geometry.undercut_detector import detect_undercuts

    face = _make_face(0, (1.0, 0.0, 0.0))
    part = _make_part([face])

    result = detect_undercuts(
        part,
        (0.0, 0.0, 1.0),
        mutate=False,
        boolean_refine=False,
    )

    feature = result.features[0]
    assert feature.undercut_type == "side-wall/silhouette"
    assert feature.type_classification_method == "silhouette-normal-distribution"
    assert feature.release_direction == (1.0, 0.0, 0.0)
    assert feature.pull_alignment == 0.0
    assert feature.side_action_candidate is True
    assert feature.recommended_mold_action == "side-action"
    assert feature.action_confidence_label in {"medium", "high"}
    assert feature.action_confidence > 0.0


def test_detector_uses_boolean_geometry_for_feature_release_and_depth(monkeypatch):
    import backend.geometry.undercut_detector as detector
    from backend.geometry.undercut_detector import (
        BooleanInterferenceMetrics,
        BooleanShapeAnalysis,
        detect_undercuts,
    )

    face = _make_face(0, (0.0, 0.9999875, 0.005), area=100.0)
    part = _make_part([face])
    shape = MagicMock(name="boolean_intersection_shape")

    def return_metrics(*args, **kwargs):
        return BooleanInterferenceMetrics(
            volume_mm3=20.0,
            depth_mm=1.0,
            depth_method="test-depth",
            intersection_shape=shape,
            shape_analysis=BooleanShapeAnalysis(
                available=True,
                vertex_count=8,
                edge_count=12,
                bbox_min=(0.0, -0.5, -0.5),
                bbox_max=(4.0, 0.5, 0.5),
                bbox_center=(2.0, 0.0, 0.0),
                bbox_dimensions=(4.0, 1.0, 1.0),
                center_of_mass=(4.0, 0.0, 0.0),
                volume_mm3=20.0,
                method="test-analysis",
            ),
        )

    monkeypatch.setattr(detector, "_OCC_BOOLEAN_AVAILABLE", True)
    monkeypatch.setattr(detector, "_swept_face_interference_volume", return_metrics)

    result = detect_undercuts(
        part,
        (0.0, 0.0, 1.0),
        mutate=False,
        boolean_refine=True,
        max_boolean_faces=10,
    )

    feature = result.features[0]
    assert feature.release_direction == (1.0, 0.0, 0.0)
    assert feature.release_direction_method == "boolean-region-center-transverse"
    assert feature.depth_proxy_mm == 4.0
    assert feature.depth_estimation_method == "boolean-region-release-span"
    assert feature.geometric_feature_type == "hook/undercut-ledge-candidate"
    assert feature.geometric_feature_confidence_label in {"medium", "high"}
    assert feature.to_dict()["release_direction_method"] == "boolean-region-center-transverse"
    assert feature.to_dict()["depth_estimation_method"] == "boolean-region-release-span"
    assert feature.to_dict()["geometric_feature_type"] == "hook/undercut-ledge-candidate"


def test_feature_semantics_identify_core_side_lifter_review(monkeypatch):
    import backend.geometry.undercut_detector as detector
    from backend.geometry.undercut_detector import detect_undercuts

    face = _make_face(0, (-0.1, 0.0, -0.995), area=1200.0)
    part = _make_part([face])

    monkeypatch.setattr(detector, "_OCC_BOOLEAN_AVAILABLE", True)
    monkeypatch.setattr(detector, "_swept_face_interference_volume", lambda *args, **kwargs: 25.0)

    result = detect_undercuts(
        part,
        (0.0, 0.0, 1.0),
        mutate=False,
        boolean_refine=True,
        boolean_check_all_faces=True,
    )

    feature = result.features[0]
    assert feature.undercut_type == "internal/core-side"
    assert feature.type_classification_method == "area-weighted-normal-consensus"
    assert feature.side_action_candidate is True
    assert feature.recommended_mold_action == "lifter-or-collapsible-core-review"
    assert feature.action_confidence_label == "high"


# ---------------------------------------------------------------------------
# Milestone 2: Accessibility Risk Signal
# ---------------------------------------------------------------------------

class TestAccessibilityRisk:
    """
    Tests for _compute_accessibility_risk() and the new fields it populates
    on UndercutDetectionResult.

    The three core invariants being tested:
    1. Bad draft + all convex edges → NOT accessibility risk (draft ≠ undercut)
    2. Good draft + core-side + concave edge → IS accessibility risk
    3. Core-side + all convex edges → NOT risk (no concave geometry evidence)
    """

    def test_bad_draft_all_convex_edges_not_accessibility_risk(self):
        """
        A face with bad draft (normal perpendicular to pull) but ALL convex
        edges must NOT be flagged as an accessibility risk.
        BAD DRAFT ≠ UNDERCUT — no concave edge means no pocket evidence.
        """
        from backend.geometry.undercut_detector import detect_undercuts

        # Normal perpendicular to pull → 0° draft (bad), but completely convex
        face = _make_face(0, (1.0, 0.0, 0.0))
        edge0 = _make_edge(0, [0], convexity="convex")
        edge1 = _make_edge(1, [0], convexity="convex")
        part = _make_part([face], edges=[edge0, edge1], face_to_edges={0: [0, 1]})

        result = detect_undercuts(part, (0.0, 0.0, 1.0), mutate=False, boolean_refine=False)

        assert result.accessibility_risk_area_mm2 == 0.0
        assert result.accessibility_risk_face_ids == []
        assert result.accessibility_risk_area_pct == 0.0

    def test_good_draft_core_side_concave_edge_is_accessibility_risk(self):
        """
        A face with good draft CAN still be an accessibility risk when it is
        core-side (normal opposes pull) and has a concave bounding edge.
        This proves accessibility risk is INDEPENDENT of draft classification.
        """
        from backend.geometry.undercut_detector import detect_undercuts

        # Normal = (-0.02, 0, -0.9998): strongly core-side (signed_dot ≈ -0.9998),
        # draft_angle = asin(0.9998) ≈ 88.9° → classified "good"
        face = _make_face(0, (-0.02, 0.0, -0.9998), area=200.0)
        concave_edge = _make_edge(0, [0], convexity="concave")
        part = _make_part([face], edges=[concave_edge], face_to_edges={0: [0]})

        result = detect_undercuts(part, (0.0, 0.0, 1.0), mutate=False, boolean_refine=False)

        assert 0 in result.accessibility_risk_face_ids
        assert result.accessibility_risk_area_mm2 == pytest.approx(200.0)

    def test_core_side_all_convex_edges_not_accessibility_risk(self):
        """
        A core-side face with ALL convex edges must NOT be flagged.
        A convex boss facing away from pull has no pocket geometry evidence.
        """
        from backend.geometry.undercut_detector import detect_undercuts

        # Normal = (0, 0, -1): directly opposing pull (core-side), but convex profile
        face = _make_face(0, (0.0, 0.0, -1.0))
        edge0 = _make_edge(0, [0], convexity="convex")
        edge1 = _make_edge(1, [0], convexity="tangent")
        part = _make_part([face], edges=[edge0, edge1], face_to_edges={0: [0, 1]})

        result = detect_undercuts(part, (0.0, 0.0, 1.0), mutate=False, boolean_refine=False)

        assert result.accessibility_risk_face_ids == []
        assert result.accessibility_risk_area_mm2 == 0.0

    def test_accessibility_risk_area_pct_computed_correctly(self):
        """
        accessibility_risk_area_pct must equal risk_area / total_area * 100.
        """
        from backend.geometry.undercut_detector import detect_undercuts

        # Two faces: one cavity-side (no risk), one core-side+concave (risk).
        cavity_face = _make_face(0, (0.0, 0.0, 1.0), area=100.0)   # positive → cavity
        risk_face = _make_face(1, (0.0, 0.0, -1.0), area=400.0)     # negative → core-side
        concave_edge = _make_edge(0, [1], convexity="concave")
        part = _make_part(
            [cavity_face, risk_face],
            edges=[concave_edge],
            face_to_edges={0: [], 1: [0]},
        )

        result = detect_undercuts(part, (0.0, 0.0, 1.0), mutate=False, boolean_refine=False)

        total_area = 100.0 + 400.0
        expected_pct = 400.0 / total_area * 100.0
        assert result.accessibility_risk_area_pct == pytest.approx(expected_pct, rel=1e-6)

    def test_accessibility_risk_fields_present_in_to_dict(self):
        """
        UndercutDetectionResult.to_dict() must include the accessibility_risk
        section with face_ids, area_mm2, and area_pct keys.
        """
        from backend.geometry.undercut_detector import detect_undercuts

        face = _make_face(0, (1.0, 0.0, 0.0))
        part = _make_part([face])

        result = detect_undercuts(part, (0.0, 0.0, 1.0), mutate=False, boolean_refine=False)
        d = result.to_dict()

        assert "accessibility_risk" in d
        risk = d["accessibility_risk"]
        assert "face_ids" in risk
        assert "area_mm2" in risk
        assert "area_pct" in risk

    def test_accessibility_risk_not_proof_of_undercut(self):
        """
        A face flagged as accessibility risk must NOT appear in proxy_undercut_ids
        unless it also independently qualifies for the proxy criterion (draft < 0.5°).
        The two signals are independent — accessibility risk is a heuristic, not
        confirmation.
        """
        from backend.geometry.undercut_detector import detect_undercuts

        # Normal ≈ (-0.02, 0, -0.9998): core-side with good draft (~88.9°).
        # This face is NOT a proxy undercut (draft >> 0.5°), but IS accessibility risk.
        face = _make_face(0, (-0.02, 0.0, -0.9998), area=150.0)
        concave_edge = _make_edge(0, [0], convexity="concave")
        part = _make_part([face], edges=[concave_edge], face_to_edges={0: [0]})

        result = detect_undercuts(part, (0.0, 0.0, 1.0), mutate=False, boolean_refine=False)

        # accessibility risk IS flagged
        assert 0 in result.accessibility_risk_face_ids
        # but NOT in undercut_face_ids (good draft ≫ 0.5° threshold, so not a proxy undercut)
        assert 0 not in result.undercut_face_ids

    def test_good_draft_cavity_side_concave_edge_is_accessibility_risk(self):
        """
        Phase 5D-1 (D-056): the mirror of
        test_good_draft_core_side_concave_edge_is_accessibility_risk --
        a face with good draft that is CAVITY-side (normal broadly aligned
        with pull) and has a concave bounding edge must ALSO be flagged.
        Same rule, sign-mirrored -- not a new heuristic.
        """
        from backend.geometry.undercut_detector import detect_undercuts

        # Normal = (0.02, 0, 0.9998): strongly cavity-side (signed_dot ≈ +0.9998),
        # draft_angle ≈ 88.9° → classified "good".
        face = _make_face(0, (0.02, 0.0, 0.9998), area=200.0)
        concave_edge = _make_edge(0, [0], convexity="concave")
        part = _make_part([face], edges=[concave_edge], face_to_edges={0: [0]})

        result = detect_undercuts(part, (0.0, 0.0, 1.0), mutate=False, boolean_refine=False)

        assert 0 in result.accessibility_risk_face_ids
        assert result.accessibility_risk_area_mm2 == pytest.approx(200.0)

    def test_cavity_side_all_convex_edges_not_accessibility_risk(self):
        """Mirror of test_core_side_all_convex_edges_not_accessibility_risk:
        a cavity-side face with ALL convex/tangent edges must NOT be
        flagged -- no pocket geometry evidence, on either side."""
        from backend.geometry.undercut_detector import detect_undercuts

        face = _make_face(0, (0.0, 0.0, 1.0))
        edge0 = _make_edge(0, [0], convexity="convex")
        edge1 = _make_edge(1, [0], convexity="tangent")
        part = _make_part([face], edges=[edge0, edge1], face_to_edges={0: [0, 1]})

        result = detect_undercuts(part, (0.0, 0.0, 1.0), mutate=False, boolean_refine=False)

        assert result.accessibility_risk_face_ids == []
        assert result.accessibility_risk_area_mm2 == 0.0

    def test_core_side_and_cavity_side_risk_faces_both_detected_simultaneously(self):
        """Union correctness: when a part has BOTH a qualifying core-side
        face and a qualifying cavity-side face, neither is dropped in
        favor of the other -- disjoint, both counted, areas simply add."""
        from backend.geometry.undercut_detector import detect_undercuts

        core_face = _make_face(0, (0.0, 0.0, -1.0), area=300.0)
        cavity_face = _make_face(1, (0.0, 0.0, 1.0), area=500.0)
        core_edge = _make_edge(0, [0], convexity="concave")
        cavity_edge = _make_edge(1, [1], convexity="concave")
        part = _make_part(
            [core_face, cavity_face],
            edges=[core_edge, cavity_edge],
            face_to_edges={0: [0], 1: [1]},
        )

        result = detect_undercuts(part, (0.0, 0.0, 1.0), mutate=False, boolean_refine=False)

        assert set(result.accessibility_risk_face_ids) == {0, 1}
        assert result.accessibility_risk_area_mm2 == pytest.approx(300.0 + 500.0)

    def test_precomputed_metrics_match_direct_computation(self):
        """
        detect_undercuts() called with precomputed_metrics must produce the same
        accessibility_risk_face_ids as when called without them.
        """
        from backend.geometry.draft_analyzer import precompute_directional_metrics
        from backend.geometry.undercut_detector import detect_undercuts

        face = _make_face(0, (0.0, 0.0, -1.0), area=100.0)
        concave_edge = _make_edge(0, [0], convexity="concave")
        part = _make_part([face], edges=[concave_edge], face_to_edges={0: [0]})
        pull = (0.0, 0.0, 1.0)

        pm = precompute_directional_metrics(part, pull)
        result_with = detect_undercuts(
            part, pull, mutate=False, boolean_refine=False,
            precomputed_metrics=pm,
        )
        result_without = detect_undercuts(part, pull, mutate=False, boolean_refine=False)

        assert result_with.accessibility_risk_face_ids == result_without.accessibility_risk_face_ids
        assert result_with.accessibility_risk_area_mm2 == pytest.approx(
            result_without.accessibility_risk_area_mm2
        )
