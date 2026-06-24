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
    assert result.diagnostics.status == "ok"
    assert result.diagnostics.failure_code is None


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
