"""
tests/test_parting_line.py
--------------------------
Pure tests for initial parting-line candidate detection.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock


def _make_face(
    face_id: int,
    normal: tuple[float, float, float],
    valid: bool = True,
    centroid: tuple[float, float, float] = (0.0, 0.0, 0.0),
):
    from backend.models.geometry_models import FaceData

    return FaceData(
        face_id=face_id,
        occ_face=MagicMock(),
        surface_type="Plane",
        normal=normal,
        centroid=centroid,
        area=100.0,
        u_range=(0.0, 1.0),
        v_range=(0.0, 1.0),
        is_reversed=False,
        normal_valid=valid,
    )


def _make_edge(
    edge_id: int,
    adjacent_face_ids: list[int],
    start=(0.0, 0.0, 0.0),
    end=(1.0, 0.0, 0.0),
    length: float = 1.0,
):
    from backend.models.geometry_models import EdgeData

    return EdgeData(
        edge_id=edge_id,
        occ_edge=MagicMock(),
        edge_type="Line",
        length=length,
        adjacent_face_ids=adjacent_face_ids,
        start_vertex=start,
        end_vertex=end,
        is_seam=False,
    )


def _make_part(faces, edges):
    from backend.models.geometry_models import BoundingBox, PartGeometry

    return PartGeometry(
        source_file="mock.stp",
        occ_shape=MagicMock(),
        faces=faces,
        edges=edges,
        bounding_box=BoundingBox(0.0, 0.0, 0.0, 10.0, 10.0, 10.0),
        face_count=len(faces),
        edge_count=len(edges),
        solid_count=1,
        shell_count=1,
        face_to_edges={face.face_id: [] for face in faces},
        edge_to_faces={edge.edge_id: edge.adjacent_face_ids for edge in edges},
    )


def test_detects_silhouette_edge_when_adjacent_normals_straddle_pull_direction():
    from backend.geometry.parting_line import detect_parting_line_candidates

    part = _make_part(
        faces=[
            _make_face(0, (0.0, 0.0, 1.0)),
            _make_face(1, (0.0, 0.0, -1.0)),
        ],
        edges=[_make_edge(0, [0, 1])],
    )

    result = detect_parting_line_candidates(part, (0.0, 0.0, 1.0))

    assert result.silhouette_edge_ids == [0]
    assert result.selected_edge_ids == [0]
    assert part.edges[0].is_silhouette is True
    assert part.edges[0].is_parting_edge is True
    assert part.parting_edge_ids == [0]


def test_detects_near_parting_edge_when_one_face_is_vertical_to_pull():
    from backend.geometry.parting_line import detect_parting_line_candidates

    part = _make_part(
        faces=[
            _make_face(0, (1.0, 0.0, 0.0)),
            _make_face(1, (0.0, 0.0, 1.0)),
        ],
        edges=[_make_edge(0, [0, 1])],
    )

    result = detect_parting_line_candidates(part, (0.0, 0.0, 1.0))

    candidate = result.candidates[0]
    assert candidate.kind == "near_parting"
    assert result.selected_edge_ids == [0]
    assert part.edges[0].is_silhouette is False
    assert part.edges[0].is_parting_edge is True


def test_boundary_edges_can_be_retained_or_ignored():
    from backend.geometry.parting_line import detect_parting_line_candidates

    part = _make_part(
        faces=[_make_face(0, (1.0, 0.0, 0.0))],
        edges=[_make_edge(0, [0])],
    )

    kept = detect_parting_line_candidates(
        part,
        (0.0, 0.0, 1.0),
        include_boundary=True,
        mutate=False,
    )
    ignored = detect_parting_line_candidates(
        part,
        (0.0, 0.0, 1.0),
        include_boundary=False,
        mutate=False,
    )

    assert kept.candidates[0].kind == "boundary"
    assert kept.selected_edge_ids == [0]
    assert ignored.candidates[0].kind == "skipped"
    assert ignored.selected_edge_ids == []


def test_boundary_edge_not_near_parting_plane_is_skipped_as_noise():
    from backend.geometry.parting_line import detect_parting_line_candidates

    part = _make_part(
        faces=[_make_face(0, (0.0, 0.0, 1.0))],
        edges=[_make_edge(0, [0])],
    )

    result = detect_parting_line_candidates(
        part,
        (0.0, 0.0, 1.0),
        include_boundary=True,
        mutate=False,
    )

    assert result.candidates[0].kind == "skipped"
    assert "not near" in result.candidates[0].reason
    assert result.selected_edge_ids == []
    assert result.readiness.status == "failed"
    assert result.diagnostic_gate.status == "failed"
    assert result.diagnostic_gate.can_use_for_report is False
    assert result.diagnostic_gate.blocks_core_cavity is True
    assert result.diagnostic_gate.requires_manual_review is True
    assert result.diagnostics.status == "failed"
    assert result.diagnostics.failure_code == "no_candidate_edges"
    assert result.diagnostics.skipped_edge_count == 1
    assert "no selected candidate edges" in result.readiness.blockers


def test_boundary_only_component_gets_noise_penalty():
    from backend.geometry.parting_line import detect_parting_line_candidates

    part = _make_part(
        faces=[_make_face(0, (1.0, 0.0, 0.0))],
        edges=[
            _make_edge(0, [0], start=(0, 0, 0), end=(1, 0, 0)),
            _make_edge(1, [0], start=(1, 0, 0), end=(1, 1, 0)),
        ],
    )

    result = detect_parting_line_candidates(part, (0.0, 0.0, 1.0), mutate=False)

    assert result.components[0].candidate_kinds["boundary"] == 2
    assert result.components[0].noise.level in {"medium", "high"}
    assert "candidate_noise" in result.selected_wire.quality_assessment.penalties


def test_non_manifold_component_gets_noise_penalty():
    from backend.geometry.parting_line import detect_parting_line_candidates

    part = _make_part(
        faces=[
            _make_face(0, (0.0, 0.0, 1.0)),
            _make_face(1, (0.0, 0.0, -1.0)),
            _make_face(2, (1.0, 0.0, 0.0)),
        ],
        edges=[_make_edge(0, [0, 1, 2])],
    )

    result = detect_parting_line_candidates(part, (0.0, 0.0, 1.0), mutate=False)

    assert result.candidates[0].kind == "non_manifold"
    assert result.components[0].noise.level in {"medium", "high"}
    assert "non_manifold_edges" in result.selected_wire.quality_assessment.penalties


def test_groups_connected_candidate_edges_and_selects_longest_component():
    from backend.geometry.parting_line import detect_parting_line_candidates

    faces = [
        _make_face(0, (0.0, 0.0, 1.0)),
        _make_face(1, (0.0, 0.0, -1.0)),
        _make_face(2, (1.0, 0.0, 0.0)),
    ]
    edges = [
        _make_edge(0, [0, 1], start=(0, 0, 0), end=(1, 0, 0), length=1.0),
        _make_edge(1, [0, 1], start=(1, 0, 0), end=(2, 0, 0), length=2.0),
        _make_edge(2, [2], start=(10, 0, 0), end=(11, 0, 0), length=1.0),
    ]
    part = _make_part(faces, edges)

    result = detect_parting_line_candidates(part, (0.0, 0.0, 1.0), mutate=False)

    assert len(result.components) == 2
    assert result.components[0].edge_ids == [0, 1]
    assert result.components[0].total_length_mm == 3.0
    assert result.selected_edge_ids == [0, 1]
    assert result.selected_wire.ordered_edge_ids == [0, 1]
    assert result.selected_wire.quality == "open_chain"


def test_orders_closed_loop_wire_and_marks_it_closed():
    from backend.geometry.parting_line import detect_parting_line_candidates

    faces = [
        _make_face(0, (0.0, 0.0, 1.0)),
        _make_face(1, (0.0, 0.0, -1.0)),
    ]
    edges = [
        _make_edge(0, [0, 1], start=(0, 0, 0), end=(1, 0, 0)),
        _make_edge(1, [0, 1], start=(1, 0, 0), end=(1, 1, 0)),
        _make_edge(2, [0, 1], start=(1, 1, 0), end=(0, 1, 0)),
        _make_edge(3, [0, 1], start=(0, 1, 0), end=(0, 0, 0)),
    ]
    part = _make_part(faces, edges)

    result = detect_parting_line_candidates(part, (0.0, 0.0, 1.0), mutate=False)

    assert result.selected_wire.is_closed is True
    assert result.selected_wire.quality == "closed_loop"
    assert result.selected_wire.ordered_edge_ids == [0, 1, 2, 3]
    assert result.selected_wire.points[0] == result.selected_wire.points[-1]
    assert result.selected_wire.projection.abs_area_mm2 == 1.0
    assert result.selected_wire.projection.quality == "closed_area"
    assert result.refinement.status == "accepted"
    assert result.refinement.quality == "refined_closed"
    assert result.refinement.refined_edge_ids == [0, 1, 2, 3]
    assert len(result.refinement.refined_points) > len(result.selected_wire.points)
    assert result.refinement.smoothing_iterations == 8
    assert result.refinement.display_metrics["raw_point_count"] == 5
    assert result.refinement.display_metrics["resampled_point_count"] >= 96
    assert (
        result.refinement.display_metrics["refined_point_count"]
        == len(result.refinement.refined_points)
    )
    assert result.refinement.display_metrics["closure_error_mm"] <= 1e-9
    assert result.readiness.status == "ready"
    assert result.readiness.score > 0.78
    assert result.diagnostic_gate.status == "ready"
    assert result.diagnostic_gate.can_display_curve is True
    assert result.diagnostic_gate.can_use_for_report is True
    assert result.diagnostic_gate.blocks_core_cavity is False
    assert result.diagnostic_gate.requires_manual_review is False


def test_projection_selects_larger_projected_closed_loop_over_longer_skinny_loop():
    from backend.geometry.parting_line import detect_parting_line_candidates

    faces = [
        _make_face(0, (0.0, 0.0, 1.0)),
        _make_face(1, (0.0, 0.0, -1.0)),
    ]
    edges = [
        # Long skinny loop: high perimeter/edge length but low projected area.
        _make_edge(0, [0, 1], start=(0, 0, 0), end=(50, 0, 0), length=50.0),
        _make_edge(1, [0, 1], start=(50, 0, 0), end=(50, 0.2, 0), length=0.2),
        _make_edge(2, [0, 1], start=(50, 0.2, 0), end=(0, 0.2, 0), length=50.0),
        _make_edge(3, [0, 1], start=(0, 0.2, 0), end=(0, 0, 0), length=0.2),
        # Shorter projected outer loop: lower perimeter but much larger area.
        _make_edge(4, [0, 1], start=(100, 0, 0), end=(110, 0, 0), length=10.0),
        _make_edge(5, [0, 1], start=(110, 0, 0), end=(110, 10, 0), length=10.0),
        _make_edge(6, [0, 1], start=(110, 10, 0), end=(100, 10, 0), length=10.0),
        _make_edge(7, [0, 1], start=(100, 10, 0), end=(100, 0, 0), length=10.0),
    ]
    part = _make_part(faces, edges)

    result = detect_parting_line_candidates(part, (0.0, 0.0, 1.0), mutate=False)

    assert result.selected_wire.ordered_edge_ids == [4, 5, 6, 7]
    assert result.selected_wire.projection.abs_area_mm2 == 100.0
    assert len(result.component_wires) == 2


def test_undercut_conflict_penalty_prefers_clean_parting_loop():
    from backend.geometry.parting_line import detect_parting_line_candidates

    faces = [
        _make_face(0, (0.0, 0.0, 1.0), centroid=(2.5, 2.5, 0.0)),
        _make_face(1, (0.0, 0.0, -1.0), centroid=(2.5, 2.5, 0.0)),
        _make_face(2, (0.0, 0.0, 1.0), centroid=(22.5, 2.5, 0.0)),
        _make_face(3, (0.0, 0.0, -1.0), centroid=(22.5, 2.5, 0.0)),
    ]
    edges = [
        # Larger loop, but it is attached to an undercut face.
        _make_edge(0, [0, 1], start=(0, 0, 0), end=(10, 0, 0), length=10.0),
        _make_edge(1, [0, 1], start=(10, 0, 0), end=(10, 10, 0), length=10.0),
        _make_edge(2, [0, 1], start=(10, 10, 0), end=(0, 10, 0), length=10.0),
        _make_edge(3, [0, 1], start=(0, 10, 0), end=(0, 0, 0), length=10.0),
        # Smaller clean loop.
        _make_edge(4, [2, 3], start=(20, 0, 0), end=(25, 0, 0), length=5.0),
        _make_edge(5, [2, 3], start=(25, 0, 0), end=(25, 5, 0), length=5.0),
        _make_edge(6, [2, 3], start=(25, 5, 0), end=(20, 5, 0), length=5.0),
        _make_edge(7, [2, 3], start=(20, 5, 0), end=(20, 0, 0), length=5.0),
    ]
    part = _make_part(faces, edges)
    undercut_context = SimpleNamespace(
        undercut_face_ids=[0],
        features=[
            SimpleNamespace(
                feature_id=10,
                face_ids=[0],
                severity="critical",
                location=(2.5, 2.5, 0.0),
                depth_proxy_mm=3.0,
                total_area_mm2=400.0,
            )
        ],
    )

    result = detect_parting_line_candidates(
        part,
        (0.0, 0.0, 1.0),
        undercut_context=undercut_context,
        mutate=False,
    )

    assert result.selected_wire.ordered_edge_ids == [4, 5, 6, 7]
    assert result.undercut_conflict.checked is True
    assert result.undercut_conflict.conflict_score == 0.0
    conflicted_wire = next(
        wire for wire in result.component_wires if set(wire.ordered_edge_ids) == {0, 1, 2, 3}
    )
    assert conflicted_wire.undercut_conflict.conflict_level == "high"
    assert 0 in conflicted_wire.undercut_conflict.conflicting_face_ids


def test_high_conflict_selected_parting_line_blocks_core_cavity_gate():
    from backend.geometry.parting_line import detect_parting_line_candidates

    faces = [
        _make_face(0, (0.0, 0.0, 1.0), centroid=(5.0, 5.0, 0.0)),
        _make_face(1, (0.0, 0.0, -1.0), centroid=(5.0, 5.0, 0.0)),
    ]
    edges = [
        _make_edge(0, [0, 1], start=(0, 0, 0), end=(10, 0, 0), length=10.0),
        _make_edge(1, [0, 1], start=(10, 0, 0), end=(10, 10, 0), length=10.0),
        _make_edge(2, [0, 1], start=(10, 10, 0), end=(0, 10, 0), length=10.0),
        _make_edge(3, [0, 1], start=(0, 10, 0), end=(0, 0, 0), length=10.0),
    ]
    part = _make_part(faces, edges)
    undercut_context = SimpleNamespace(
        undercut_face_ids=[0],
        features=[
            SimpleNamespace(
                feature_id=7,
                face_ids=[0],
                severity="critical",
                location=(5.0, 5.0, 0.0),
                depth_proxy_mm=4.0,
                total_area_mm2=100.0,
            )
        ],
    )

    result = detect_parting_line_candidates(
        part,
        (0.0, 0.0, 1.0),
        undercut_context=undercut_context,
        mutate=False,
    )

    assert result.undercut_conflict.conflict_level == "high"
    assert result.undercut_conflict.near_feature_conflicts[0]["location"] == [5.0, 5.0, 0.0]
    assert result.diagnostic_gate.can_display_curve is True
    assert result.diagnostic_gate.can_use_for_report is True
    assert result.diagnostic_gate.blocks_core_cavity is True
    assert result.diagnostic_gate.requires_manual_review is True


def test_parting_line_reports_not_checked_when_no_undercut_context_supplied():
    from backend.geometry.parting_line import detect_parting_line_candidates

    part = _make_part(
        faces=[
            _make_face(0, (0.0, 0.0, 1.0)),
            _make_face(1, (0.0, 0.0, -1.0)),
        ],
        edges=[_make_edge(0, [0, 1])],
    )

    result = detect_parting_line_candidates(part, (0.0, 0.0, 1.0), mutate=False)

    assert result.undercut_conflict.checked is False
    assert result.undercut_conflict.conflict_level == "not_checked"


def test_open_wire_has_projection_extent_but_no_projected_area():
    from backend.geometry.parting_line import detect_parting_line_candidates

    faces = [
        _make_face(0, (0.0, 0.0, 1.0)),
        _make_face(1, (0.0, 0.0, -1.0)),
    ]
    edges = [
        _make_edge(0, [0, 1], start=(0, 0, 0), end=(1, 0, 0)),
        _make_edge(1, [0, 1], start=(1, 0, 0), end=(1, 2, 0)),
    ]
    part = _make_part(faces, edges)

    result = detect_parting_line_candidates(part, (0.0, 0.0, 1.0), mutate=False)

    assert result.selected_wire.quality == "open_chain"
    assert result.selected_wire.projection.abs_area_mm2 == 0.0
    assert result.selected_wire.projection.bbox_area_mm2 == 2.0
    assert result.selected_wire.projection.quality == "open_extent"


def test_branched_candidate_graph_reports_branch_and_gap():
    from backend.geometry.parting_line import detect_parting_line_candidates

    faces = [
        _make_face(0, (0.0, 0.0, 1.0)),
        _make_face(1, (0.0, 0.0, -1.0)),
    ]
    edges = [
        _make_edge(0, [0, 1], start=(0, 0, 0), end=(1, 0, 0)),
        _make_edge(1, [0, 1], start=(1, 0, 0), end=(2, 0, 0)),
        _make_edge(2, [0, 1], start=(1, 0, 0), end=(1, 1, 0)),
    ]
    part = _make_part(faces, edges)

    result = detect_parting_line_candidates(part, (0.0, 0.0, 1.0), mutate=False)

    assert result.selected_wire.branch_point_count == 1
    assert result.selected_wire.gap_count >= 1
    assert result.selected_wire.quality == "partial"
    assert result.refinement.status == "accepted"
    assert result.refinement.refined_edge_ids == [0, 1]
    assert result.refinement.removed_edge_ids == [2]
    assert result.refinement.quality == "graph_cleaned_open"
    assert any("branched" in warning for warning in result.warnings)
    assert any("discarded lower-weight" in warning for warning in result.warnings)


def test_branched_refinement_uses_weighted_path_search_not_local_greedy_choice():
    from backend.geometry.parting_line import detect_parting_line_candidates

    faces = [
        _make_face(0, (0.0, 0.0, 1.0)),
        _make_face(1, (0.0, 0.0, -1.0)),
    ]
    edges = [
        # Branch point at A=(0,0,0). A local greedy walk from B would choose
        # A-F, but the better total path is B-A-C-D-E.
        _make_edge(0, [0, 1], start=(-10, 0, 0), end=(0, 0, 0), length=10.0),
        _make_edge(1, [0, 1], start=(0, 0, 0), end=(6, 0, 0), length=6.0),
        _make_edge(2, [0, 1], start=(6, 0, 0), end=(12, 0, 0), length=6.0),
        _make_edge(3, [0, 1], start=(12, 0, 0), end=(18, 0, 0), length=6.0),
        _make_edge(4, [0, 1], start=(0, 0, 0), end=(0, 9, 0), length=9.0),
    ]
    part = _make_part(faces, edges)

    result = detect_parting_line_candidates(part, (0.0, 0.0, 1.0), mutate=False)

    assert result.selected_wire.branch_point_count == 1
    assert result.refinement.refined_edge_ids == [0, 1, 2, 3]
    assert result.refinement.removed_edge_ids == [4]
    assert result.refinement.quality == "graph_cleaned_open"
    assert result.refinement.graph_cleanup.status == "optimized"
    assert result.refinement.graph_cleanup.retained_edge_ids == [0, 1, 2, 3]
    assert result.refinement.graph_cleanup.removed_edge_ids == [4]


def test_graph_cleanup_penalizes_branch_that_overlaps_major_undercut():
    from backend.geometry.parting_line import detect_parting_line_candidates

    faces = [
        _make_face(0, (0.0, 0.0, 1.0)),
        _make_face(1, (0.0, 0.0, -1.0)),
        _make_face(2, (0.0, 0.0, 1.0), centroid=(0.0, 14.0, 0.0)),
        _make_face(3, (0.0, 0.0, -1.0), centroid=(0.0, 14.0, 0.0)),
    ]
    edges = [
        _make_edge(0, [0, 1], start=(-10, 0, 0), end=(0, 0, 0), length=10.0),
        _make_edge(1, [0, 1], start=(0, 0, 0), end=(6, 0, 0), length=6.0),
        _make_edge(2, [0, 1], start=(6, 0, 0), end=(12, 0, 0), length=6.0),
        _make_edge(3, [0, 1], start=(12, 0, 0), end=(18, 0, 0), length=6.0),
        # This branch is long enough to look attractive without the undercut
        # penalty, but it touches the major undercut face.
        _make_edge(4, [2, 3], start=(0, 0, 0), end=(0, 14, 0), length=14.0),
    ]
    part = _make_part(faces, edges)
    undercut_context = SimpleNamespace(
        undercut_face_ids=[2],
        features=[
            SimpleNamespace(
                feature_id=42,
                face_ids=[2],
                severity="critical",
                location=(0.0, 14.0, 0.0),
                depth_proxy_mm=4.0,
                total_area_mm2=160.0,
                is_major_feature=True,
            )
        ],
    )

    result = detect_parting_line_candidates(
        part,
        (0.0, 0.0, 1.0),
        undercut_context=undercut_context,
        mutate=False,
    )

    cleanup = result.refinement.graph_cleanup
    assert result.refinement.refined_edge_ids == [0, 1, 2, 3]
    assert cleanup.conflict_penalized_edge_ids == [4]
    assert cleanup.removed_conflict_edge_ids == [4]
    assert cleanup.retained_conflict_edge_ids == []
    assert result.undercut_conflict.conflict_score == 0.0
    assert result.to_dict()["selected_wire_undercut_conflict"]["conflict_score"] > 0.0


def test_refinement_can_be_disabled_for_raw_wire_debugging():
    from backend.geometry.parting_line import detect_parting_line_candidates

    faces = [
        _make_face(0, (0.0, 0.0, 1.0)),
        _make_face(1, (0.0, 0.0, -1.0)),
    ]
    edges = [
        _make_edge(0, [0, 1], start=(0, 0, 0), end=(1, 0, 0)),
        _make_edge(1, [0, 1], start=(1, 0, 0), end=(1, 1, 0)),
        _make_edge(2, [0, 1], start=(1, 1, 0), end=(0, 1, 0)),
        _make_edge(3, [0, 1], start=(0, 1, 0), end=(0, 0, 0)),
    ]
    part = _make_part(faces, edges)

    result = detect_parting_line_candidates(
        part,
        (0.0, 0.0, 1.0),
        refine=False,
        mutate=False,
    )

    assert result.refinement.status == "disabled"
    assert result.refinement.refined_points == result.selected_wire.points
    assert result.refinement.smoothing_iterations == 0


def test_selected_wire_reports_unorderable_edges_without_endpoints():
    from backend.geometry.parting_line import detect_parting_line_candidates

    part = _make_part(
        faces=[_make_face(0, (1.0, 0.0, 0.0))],
        edges=[_make_edge(0, [0], start=None, end=None)],
    )

    result = detect_parting_line_candidates(part, (0.0, 0.0, 1.0), mutate=False)

    assert result.selected_wire.ordered_edge_ids == []
    assert result.selected_wire.skipped_edge_ids == [0]
    assert result.selected_wire.quality == "empty"
    assert result.diagnostics.status == "failed"
    assert result.diagnostics.failure_code == "selected_wire_unorderable"
    assert result.diagnostics.unorderable_edge_count == 1
    assert any("endpoint data is unavailable" in warning for warning in result.warnings)


def test_single_closed_edge_without_endpoints_can_use_sampled_curve_points():
    from backend.geometry import parting_line

    original_sampler = parting_line._sample_closed_edge_points
    parting_line._sample_closed_edge_points = lambda edge: [
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (-1.0, 0.0, 0.0),
        (0.0, -1.0, 0.0),
        (1.0, 0.0, 0.0),
    ]
    try:
        part = _make_part(
            faces=[_make_face(0, (1.0, 0.0, 0.0))],
            edges=[
                _make_edge(
                    0,
                    [0],
                    start=None,
                    end=None,
                    length=6.283,
                )
            ],
        )

        result = parting_line.detect_parting_line_candidates(
            part,
            (0.0, 0.0, 1.0),
            mutate=False,
        )
    finally:
        parting_line._sample_closed_edge_points = original_sampler

    assert result.selected_edge_ids == [0]
    assert result.selected_wire.is_closed is True
    assert result.selected_wire.quality == "closed_loop"
    assert result.selected_wire.skipped_edge_ids == []
    assert result.selected_wire.projection.quality == "closed_area"
    assert result.refinement.status == "accepted"
    assert result.diagnostic_gate.can_display_curve is True
    # The sampled curve is a tiny radius-1 circle inside the mock part's
    # 10x10x10 bounding box (~3.9% projected coverage) — the Bug H
    # silhouette-coverage guard correctly flags that as a likely local
    # feature rather than the main parting line, so this legitimately reads
    # "warning", not "ok". (This test could never run to completion on real
    # OCC before BUG G's hang fix, so its assertions here were never
    # actually verified against real behavior until now.)
    assert result.diagnostics.status == "warning"
    assert result.diagnostics.failure_code is None
    assert any("projected extent" in warning for warning in result.warnings)


def test_single_closed_edge_with_same_start_end_uses_sampled_curve_points():
    from backend.geometry import parting_line

    original_sampler = parting_line._sample_closed_edge_points
    parting_line._sample_closed_edge_points = lambda edge: [
        (2.0, 0.0, 0.0),
        (0.0, 2.0, 0.0),
        (-2.0, 0.0, 0.0),
        (0.0, -2.0, 0.0),
        (2.0, 0.0, 0.0),
    ]
    try:
        part = _make_part(
            faces=[
                _make_face(0, (0.0, 0.0, 1.0)),
                _make_face(1, (0.0, 0.0, -1.0)),
            ],
            edges=[
                _make_edge(
                    0,
                    [0, 1],
                    start=(2.0, 0.0, 0.0),
                    end=(2.0, 0.0, 0.0),
                    length=12.566,
                )
            ],
        )

        result = parting_line.detect_parting_line_candidates(
            part,
            (0.0, 0.0, 1.0),
            mutate=False,
        )
    finally:
        parting_line._sample_closed_edge_points = original_sampler

    assert result.selected_edge_ids == [0]
    assert result.selected_wire.is_closed is True
    assert len(result.selected_wire.points) == 5
    assert result.selected_wire.quality == "closed_loop"
    assert result.selected_wire.projection.quality == "closed_area"
    assert result.diagnostics.failure_code is None


def test_mutate_false_does_not_modify_part_or_edges():
    from backend.geometry.parting_line import detect_parting_line_candidates

    part = _make_part(
        faces=[
            _make_face(0, (0.0, 0.0, 1.0)),
            _make_face(1, (0.0, 0.0, -1.0)),
        ],
        edges=[_make_edge(0, [0, 1])],
    )

    result = detect_parting_line_candidates(part, (0.0, 0.0, 1.0), mutate=False)

    assert result.selected_edge_ids == [0]
    assert part.edges[0].is_silhouette is None
    assert part.edges[0].is_parting_edge is None
    assert part.parting_edge_ids == []


def test_invalid_pull_direction_raises_value_error():
    import pytest

    from backend.geometry.parting_line import detect_parting_line_candidates

    part = _make_part(faces=[], edges=[])

    with pytest.raises(ValueError):
        detect_parting_line_candidates(part, (0.0, 0.0, 0.0))


def test_negative_smoothing_iterations_raises_value_error():
    import pytest

    from backend.geometry.parting_line import detect_parting_line_candidates

    part = _make_part(faces=[], edges=[])

    with pytest.raises(ValueError):
        detect_parting_line_candidates(
            part,
            (0.0, 0.0, 1.0),
            smoothing_iterations=-1,
        )


# =============================================================================
# Closure honesty guard (Stage 1.1 / Bug A)
#
# The original Milestone 1.8 implementation computed a closing path through
# the B-Rep edge graph and then DISCARDED it, returning
# (closure_guaranteed=True, closure_error_mm=0.0) while handing back a curve
# with a 17.35 mm gap on the real Part1.stp.  A parting surface was then
# built from that open curve and every downstream stage trusted the false
# guarantee.
#
# These tests assert the invariant that makes that impossible: whenever the
# engine REPORTS closure, the returned points must MEASURABLY be closed.
# Mock-based structural tests cannot catch this — only measuring the geometry
# can.
# =============================================================================

def _measured_gap(points) -> float:
    from backend.models.geometry_models import mag3

    if not points or len(points) < 2:
        return 0.0
    a, b = points[0], points[-1]
    return mag3((b[0] - a[0], b[1] - a[1], b[2] - a[2]))


def test_reported_closure_always_matches_measured_geometry():
    """If closure_guaranteed is True, the points must actually be closed."""
    from backend.config import settings
    from backend.geometry.parting_line import detect_parting_line_candidates

    tol = settings.dfm.parting_line.max_closure_error_mm
    faces = [
        _make_face(0, (0.0, 0.0, 1.0)),
        _make_face(1, (0.0, 0.0, -1.0)),
        _make_face(2, (1.0, 0.0, 0.0)),
    ]
    edges = [
        _make_edge(0, [0, 1], start=(0.0, 0.0, 0.0), end=(1.0, 0.0, 0.0)),
        _make_edge(1, [0, 1], start=(1.0, 0.0, 0.0), end=(1.0, 1.0, 0.0)),
        _make_edge(2, [0, 1], start=(1.0, 1.0, 0.0), end=(0.0, 0.0, 0.0)),
    ]
    part = _make_part(faces, edges)

    result = detect_parting_line_candidates(part, (0.0, 0.0, 1.0))

    if result.closure_guaranteed:
        pts = result.refinement.refined_points or result.wire_points
        gap = _measured_gap(pts)
        assert gap <= tol, (
            f"closure_guaranteed=True but the returned curve has a measured "
            f"gap of {gap:.6f} mm (tolerance {tol} mm). The engine must never "
            f"report a closure it has not achieved."
        )
        assert abs(result.closure_error_mm - gap) <= 1e-6, (
            f"reported closure_error_mm={result.closure_error_mm:.6f} does not "
            f"match the measured gap {gap:.6f}"
        )


def test_closure_bridge_count_implies_points_were_actually_spliced():
    """
    A non-zero closure_bridge_edge_count means real B-Rep vertices were
    added to the curve. Guards against the count being reported while the
    geometry is left untouched.
    """
    from backend.geometry.parting_line import _attempt_loop_closure

    open_points = [(0.0, 0.0, 0.0), (5.0, 0.0, 0.0), (5.0, 5.0, 0.0)]
    edges = {
        0: _make_edge(0, [0, 1], start=(5.0, 5.0, 0.0), end=(0.0, 0.0, 0.0)),
    }

    guaranteed, error, closed_pts, bridges, _ = _attempt_loop_closure(
        open_points,
        is_closed=False,
        edges_by_id=edges,
        candidate_by_id={},
        point_tolerance=1e-4,
        undercut_face_ids=set(),
        bridge_penalty_factor=4.0,
        boundary_bridge_factor=0.6,
        max_closure_error_mm=0.05,
    )

    if bridges > 0:
        assert len(closed_pts) > len(open_points), (
            "bridge edges were reported but no points were added to the curve"
        )
        assert _measured_gap(closed_pts) <= 0.05
        assert guaranteed is True
    if guaranteed:
        assert _measured_gap(closed_pts) <= 0.05


def test_open_loop_that_cannot_close_reports_failure_honestly():
    """Unclosable loop must report closure_guaranteed=False, not a false True."""
    from backend.geometry.parting_line import _attempt_loop_closure

    open_points = [(0.0, 0.0, 0.0), (5.0, 0.0, 0.0), (5.0, 5.0, 0.0)]

    guaranteed, error, closed_pts, bridges, warnings = _attempt_loop_closure(
        open_points,
        is_closed=False,
        edges_by_id={},          # no edges at all -> cannot close
        candidate_by_id={},
        point_tolerance=1e-4,
        undercut_face_ids=set(),
        bridge_penalty_factor=4.0,
        boundary_bridge_factor=0.6,
        max_closure_error_mm=0.05,
    )

    assert guaranteed is False
    assert bridges == 0
    assert closed_pts == open_points          # original curve returned untouched
    assert error > 0.05
    assert warnings


def test_bridging_is_skipped_when_a_closed_loop_already_exists():
    """
    Bug F guard: bridging must not run (and must not degrade the result) when
    the selected wire is already a closed loop. On real parts, bridging an
    already-good loop dropped readiness from 1.000 to 0.080.
    """
    from backend.geometry.parting_line import detect_parting_line_candidates

    faces = [
        _make_face(0, (0.0, 0.0, 1.0)),
        _make_face(1, (0.0, 0.0, -1.0)),
    ]
    edges = [
        _make_edge(0, [0, 1], start=(0.0, 0.0, 0.0), end=(1.0, 0.0, 0.0)),
        _make_edge(1, [0, 1], start=(1.0, 0.0, 0.0), end=(1.0, 1.0, 0.0)),
        _make_edge(2, [0, 1], start=(1.0, 1.0, 0.0), end=(0.0, 0.0, 0.0)),
    ]
    part = _make_part(faces, edges)

    result = detect_parting_line_candidates(part, (0.0, 0.0, 1.0))

    assert result.bridging_status in {
        "not_needed",
        "applied",
        "discarded_not_an_improvement",
        "unavailable",
        "disabled",
    }
    if result.selected_wire.is_closed:
        assert result.bridging_status != "applied", (
            "bridging ran even though a closed loop was already selected"
        )


def test_tiny_loop_in_a_large_part_is_flagged_as_not_the_main_parting_line():
    """
    Bug H guard: the engine used to rank a small, tidy loop (a hole rim) above
    the true main silhouette, then report it as a perfect parting line.

    Coverage must be measured against the part's projected extent, and a loop
    that spans a tiny fraction of it must produce a warning — never a silent
    pass. This is the check that makes the failure mode visible.
    """
    from backend.geometry.parting_line import detect_parting_line_candidates

    faces = [
        _make_face(0, (0.0, 0.0, 1.0)),
        _make_face(1, (0.0, 0.0, -1.0)),
    ]
    # A 1x1 loop inside a part whose bounding box is 10x10x10.
    edges = [
        _make_edge(0, [0, 1], start=(0.0, 0.0, 0.0), end=(1.0, 0.0, 0.0)),
        _make_edge(1, [0, 1], start=(1.0, 0.0, 0.0), end=(1.0, 1.0, 0.0)),
        _make_edge(2, [0, 1], start=(1.0, 1.0, 0.0), end=(0.0, 0.0, 0.0)),
    ]
    part = _make_part(faces, edges)

    result = detect_parting_line_candidates(part, (0.0, 0.0, 1.0))

    assert result.silhouette_coverage_ratio < 0.1, (
        "a 1x1 loop in a 10x10 projected extent should measure ~1% coverage, "
        f"got {result.silhouette_coverage_ratio:.3f}"
    )
    assert any("projected extent" in w for w in result.warnings), (
        "an implausibly small parting loop must be flagged, not silently "
        f"accepted; warnings were: {result.warnings}"
    )


def test_loop_spanning_the_part_is_not_flagged_for_coverage():
    """
    The coverage guard must not cry wolf: a loop that actually wraps the part
    silhouette carries no coverage warning.
    """
    from backend.geometry.parting_line import detect_parting_line_candidates

    faces = [
        _make_face(0, (0.0, 0.0, 1.0)),
        _make_face(1, (0.0, 0.0, -1.0)),
    ]
    # Spans the full 10x10 projected extent of the part bounding box.
    edges = [
        _make_edge(0, [0, 1], start=(0.0, 0.0, 0.0), end=(10.0, 0.0, 0.0)),
        _make_edge(1, [0, 1], start=(10.0, 0.0, 0.0), end=(10.0, 10.0, 0.0)),
        _make_edge(2, [0, 1], start=(10.0, 10.0, 0.0), end=(0.0, 0.0, 0.0)),
    ]
    part = _make_part(faces, edges)

    result = detect_parting_line_candidates(part, (0.0, 0.0, 1.0))

    assert result.silhouette_coverage_ratio > 0.9, (
        f"expected near-full coverage, got {result.silhouette_coverage_ratio:.3f}"
    )
    assert not any("projected extent" in w for w in result.warnings), (
        f"a full-extent loop must not be flagged; warnings were: {result.warnings}"
    )


def test_ring_bridging_excludes_local_features_and_connects_the_rest_into_a_cycle():
    """
    Bug H-2 (root cause fix): bridging must not indiscriminately fuse every
    disconnected component into one blob, AND the components it does bridge
    must form a CYCLE, not a spanning tree — a tree can never contain a
    closed loop, so no wire tracer could ever close it (this is exactly what
    made Part3's original tree-bridged 259-edge component score 0.00 and
    fail to close, proven by an exhaustive 177,032-state search finding
    nothing). Component C (an isolated local feature near the part's centre)
    must be excluded; components A and B must be connected via a genuine
    cycle (both ring links found, not just one tree edge).
    """
    from backend.geometry.parting_line import (
        _bridge_disconnected_components,
        _projection_basis,
        PartingLineComponent,
        PartingLineEdgeCandidate,
    )
    from backend.models.geometry_models import EdgeData

    def edge(eid, start, end, length, adjacent):
        return EdgeData(
            edge_id=eid,
            occ_edge=MagicMock(),
            edge_type="Line",
            length=length,
            adjacent_face_ids=list(adjacent),
            start_vertex=start,
            end_vertex=end,
            is_seam=False,
        )

    # Component A near corner (0,0); component B near opposite corner (10,10).
    # Merging just these two already covers the full 10x10 extent.
    e0 = edge(0, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 1.0, adjacent=(0, 1))
    e1 = edge(1, (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), 1.0, adjacent=(0, 1))
    e2 = edge(2, (10.0, 10.0, 0.0), (9.0, 10.0, 0.0), 1.0, adjacent=(0, 1))
    e3 = edge(3, (10.0, 10.0, 0.0), (10.0, 9.0, 0.0), 1.0, adjacent=(0, 1))
    # Component C: an isolated local feature near the centre — should be
    # left unmerged once A+B already cover the extent.
    e4 = edge(4, (5.0, 5.0, 0.0), (5.0, 5.5, 0.0), 0.5, adjacent=(0, 1))

    # Non-candidate bridge edges wiring the graph together. A<->B is cheap;
    # anything touching C is deliberately much more expensive, and C's tiny
    # (near-degenerate) extent should get it excluded from ring construction
    # regardless of cost.
    bridge_ab = edge(10, (0.0, 1.0, 0.0), (9.0, 10.0, 0.0), 5.0, adjacent=(2, 3))
    bridge_ac = edge(11, (0.0, 1.0, 0.0), (5.0, 5.0, 0.0), 1000.0, adjacent=(2, 3))
    bridge_bc = edge(12, (10.0, 9.0, 0.0), (5.0, 5.5, 0.0), 1000.0, adjacent=(2, 3))

    edges_by_id = {e.edge_id: e for e in [e0, e1, e2, e3, e4, bridge_ab, bridge_ac, bridge_bc]}
    candidate_by_id = {
        eid: PartingLineEdgeCandidate(
            edge_id=eid, adjacent_face_ids=[0, 1], kind="silhouette", score=1.0, length_mm=1.0,
        )
        for eid in (0, 1, 2, 3, 4)
    }

    comp_a = PartingLineComponent(0, [0, 1], 2.0, {"silhouette": 2}, 3)
    comp_b = PartingLineComponent(1, [2, 3], 2.0, {"silhouette": 2}, 3)
    comp_c = PartingLineComponent(2, [4], 0.5, {"silhouette": 1}, 2)
    components = [comp_a, comp_b, comp_c]
    component_points = {
        0: [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        1: [(10.0, 10.0, 0.0), (9.0, 10.0, 0.0), (10.0, 9.0, 0.0)],
        2: [(5.0, 5.0, 0.0), (5.0, 5.5, 0.0)],
    }

    pull_direction = (0.0, 0.0, 1.0)
    u_axis, v_axis = _projection_basis(pull_direction)

    merged, merged_points, warnings = _bridge_disconnected_components(
        components,
        component_points,
        edges_by_id,
        candidate_by_id,
        point_tolerance=1e-4,
        undercut_face_ids=set(),
        part_extent_area=100.0,  # a 10x10 part
        projection_basis=(u_axis, v_axis),
        min_coverage_ratio=0.5,
    )

    assert len(merged) == 1, "A and B should have been merged into one component"
    kept_edge_ids = set(merged[0].edge_ids)
    assert {0, 1, 2, 3} <= kept_edge_ids, "A and B's own edges must be kept"
    assert 4 not in kept_edge_ids, (
        "component C must be excluded as a local feature; "
        f"kept edges were {sorted(kept_edge_ids)}"
    )
    assert any("Ring-bridged" in w for w in warnings), (
        f"expected a ring-bridging summary; got: {warnings}"
    )
    assert any("excluded before ring construction as probable local features" in w for w in warnings), (
        f"expected C's exclusion to be reported; got: {warnings}"
    )
    assert any("a closed cycle" in w for w in warnings), (
        f"expected the ring to be reported as closed; got: {warnings}"
    )
    ring_link_count = sum(1 for w in warnings if w.startswith("Ring bridge:"))
    assert ring_link_count == 2, (
        "A and B (2 components) should be connected via a 2-link ring "
        f"(a genuine cycle), not a single tree edge; got {ring_link_count} link(s)"
    )


def test_ring_bridging_closes_a_loop_that_tree_bridging_structurally_could_not():
    """
    Bug H-2 root cause, end-to-end proof: 4 disconnected component fragments
    sit at the corners of a square, with exactly the 4 "side" bridge edges
    available to connect them (no shortcuts). A tree-based bridge strategy
    can only ever use 3 of those 4 edges (N-1 for N=4 components, by
    definition of a spanning tree) and leaves the square OPEN on one side —
    it is structurally impossible for a tree to close this loop, however
    smart the wire tracer is. Ring bridging uses all 4 (one per angular
    neighbor pair, wrapping around) and the resulting square genuinely
    closes.
    """
    from backend.geometry.parting_line import detect_parting_line_candidates

    faces = [
        _make_face(0, (0.0, 0.0, 1.0)),
        _make_face(1, (0.0, 0.0, -1.0)),
    ]

    def candidate_edge(eid, start, end):
        return _make_edge(eid, [0, 1], start=start, end=end, length=1.0)

    def bridge_edge(eid, start, end, length):
        # Adjacent to faces outside the silhouette-straddling pair, so
        # `_classify_edge` does not treat it as a parting-line candidate —
        # it only exists in the part's full edge graph for bridging to route
        # through, exactly like a real non-candidate manifold edge.
        return _make_edge(eid, [2, 3], start=start, end=end, length=length)

    # Four L-shaped corner fragments (2 candidate edges each) at the corners
    # of a 10x10 square.
    edges = [
        candidate_edge(0, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),   # A arm 1
        candidate_edge(1, (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)),   # A arm 2
        candidate_edge(2, (10.0, 0.0, 0.0), (9.0, 0.0, 0.0)),  # B arm 1
        candidate_edge(3, (10.0, 0.0, 0.0), (10.0, 1.0, 0.0)), # B arm 2
        candidate_edge(4, (10.0, 10.0, 0.0), (9.0, 10.0, 0.0)),  # C arm 1
        candidate_edge(5, (10.0, 10.0, 0.0), (10.0, 9.0, 0.0)),  # C arm 2
        candidate_edge(6, (0.0, 10.0, 0.0), (1.0, 10.0, 0.0)),   # D arm 1
        candidate_edge(7, (0.0, 10.0, 0.0), (0.0, 9.0, 0.0)),    # D arm 2
        # The only 4 available connections — exactly the square's sides.
        bridge_edge(10, (1.0, 0.0, 0.0), (9.0, 0.0, 0.0), 8.0),   # A-B (bottom)
        bridge_edge(11, (10.0, 1.0, 0.0), (10.0, 9.0, 0.0), 8.0), # B-C (right)
        bridge_edge(12, (9.0, 10.0, 0.0), (1.0, 10.0, 0.0), 8.0), # C-D (top)
        bridge_edge(13, (0.0, 9.0, 0.0), (0.0, 1.0, 0.0), 8.0),   # D-A (left)
    ]
    part = _make_part(faces, edges)

    result = detect_parting_line_candidates(part, (0.0, 0.0, 1.0), mutate=False)

    assert result.bridging_status == "applied", (
        f"expected bridging to apply and improve the result; status was "
        f"{result.bridging_status!r}, warnings: {result.warnings}"
    )
    assert result.selected_wire.is_closed, (
        "ring bridging should have connected all 4 corners into one closed "
        f"square loop; warnings: {result.warnings}"
    )
    assert set(result.selected_edge_ids) >= {0, 1, 2, 3, 4, 5, 6, 7}, (
        "all 4 corner fragments' own edges should be part of the closed loop"
    )


def test_search_verified_closed_loop_is_not_penalized_for_source_components_mess():
    """
    Bug H-3: once the second-pass search finds and substitutes a genuinely
    closed, clean sub-loop, the wire's quality must reflect THAT loop, not
    the messier component it was extracted from. This component has: a
    triangle (the real closed loop), a dead-end tail edge that fools the
    single-pass greedy walk into ending away from its own start (so it does
    NOT report closed on its own -- forcing the second-pass search to run),
    and one entirely unparseable edge (start=end=None) elsewhere in the same
    component, standing in for the unrelated data-quality issues a large
    bridged super-component can carry (exactly what happened on Part3: a
    269-edge bridged component with 5 unrelated unparseable edges capped a
    genuinely closed 15-edge loop's score at 0.00).
    """
    from backend.geometry.parting_line import (
        _build_ordered_wire,
        PartingLineComponent,
        PartingLineEdgeCandidate,
    )
    from backend.models.geometry_models import EdgeData

    def edge(eid, start, end, length):
        return EdgeData(
            edge_id=eid,
            occ_edge=MagicMock(),
            edge_type="Line",
            length=length,
            adjacent_face_ids=[0, 1],
            start_vertex=start,
            end_vertex=end,
            is_seam=False,
        )

    # Triangle A(0,0,0) - B(10,0,0) - C(0,10,0) - back to A.
    e_ab = edge(0, (0.0, 0.0, 0.0), (10.0, 0.0, 0.0), 10.0)
    e_bc = edge(1, (10.0, 0.0, 0.0), (0.0, 10.0, 0.0), 14.0)
    e_ca = edge(2, (0.0, 10.0, 0.0), (0.0, 0.0, 0.0), 10.0)
    # Dead-end tail hanging off A: the sole degree-1 (open) endpoint, so the
    # greedy walk starts there, crosses the whole triangle, and ends back at
    # A -- never equal to its own start -- so it never reports closed.
    e_tail = edge(3, (-8.0, -8.0, 0.0), (0.0, 0.0, 0.0), 11.3)
    # Entirely unrelated, unparseable edge in the same component.
    e_bad = edge(4, None, None, 1.0)

    edges_by_id = {e.edge_id: e for e in [e_ab, e_bc, e_ca, e_tail, e_bad]}
    candidate_by_id = {
        eid: PartingLineEdgeCandidate(
            edge_id=eid, adjacent_face_ids=[0, 1], kind="silhouette", score=1.0, length_mm=1.0,
        )
        for eid in (0, 1, 2, 3, 4)
    }
    component = PartingLineComponent(0, [0, 1, 2, 3, 4], 46.3, {"silhouette": 5}, 4)

    wire = _build_ordered_wire(
        component,
        edges_by_id,
        candidate_by_id,
        point_tolerance=1e-4,
        pull_direction=(0.0, 0.0, 1.0),
    )

    assert wire.is_closed is True, "the search should have found the triangle A-B-C-A"
    assert set(wire.ordered_edge_ids) == {0, 1, 2}, (
        f"expected just the triangle's 3 edges, got {wire.ordered_edge_ids}"
    )
    assert wire.branch_point_count == 0, (
        "must be recomputed from the SELECTED triangle (branch-free), not "
        f"the whole component (which has a branch at A); got {wire.branch_point_count}"
    )
    assert wire.skipped_edge_ids == [4], "the unparseable edge is still reported, for transparency"
    assert wire.quality == "closed_loop", (
        "an unrelated unparseable edge elsewhere in the component must not "
        f"demote a verified closed loop to 'partial'; got {wire.quality!r}"
    )
