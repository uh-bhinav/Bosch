"""
tests/test_visualize_raw.py
---------------------------
Unit tests for the raw visualization adapter that do not require OCC/PyVista.
"""

from __future__ import annotations


def test_raw_mesh_data_counts_and_dict():
    from backend.geometry.visualize_raw import RawMeshData

    mesh = RawMeshData(
        points=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        faces=[(0, 1, 2)],
        face_ids=[3],
        face_centers={3: (0.3333, 0.3333, 0.0)},
    )

    assert mesh.point_count == 3
    assert mesh.triangle_count == 1

    data = mesh.to_dict()
    assert data["point_count"] == 3
    assert data["triangle_count"] == 1
    assert data["face_count"] == 1
    assert data["face_ids"] == [3]
    assert data["face_centers"]["3"] == [0.3333, 0.3333, 0.0]


def test_raw_mesh_payload_can_include_geometry():
    from backend.geometry.visualize_raw import RawMeshData

    mesh = RawMeshData(
        points=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        faces=[(0, 1, 2)],
        face_ids=[3],
    )

    payload = mesh.to_payload(include_geometry=True)

    assert payload["points"] == [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    assert payload["faces"] == [[0, 1, 2]]


def test_build_display_mesh_alias_exists():
    from backend.geometry.visualize_raw import (
        build_display_mesh,
        build_raw_mesh,
        build_shape_display_mesh,
    )

    assert build_display_mesh is not None
    assert build_raw_mesh is not None
    assert build_shape_display_mesh is not None


def test_empty_shape_display_mesh_is_json_safe_without_occ():
    from backend.geometry.visualize_raw import build_shape_display_mesh

    mesh = build_shape_display_mesh(None)
    payload = mesh.to_payload(include_geometry=True)

    assert payload["point_count"] == 0
    assert payload["triangle_count"] == 0
    assert payload["face_count"] == 0
    assert payload["face_ids"] == []
    assert payload["points"] == []
    assert payload["faces"] == []
