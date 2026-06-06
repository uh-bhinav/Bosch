"""
tests/test_api_boolean_regions.py
---------------------------------
Focused tests for Boolean-region visualization payloads.
"""

from __future__ import annotations

from types import SimpleNamespace


def test_boolean_region_mesh_payloads_are_json_safe(monkeypatch):
    from backend.api import main
    from backend.geometry.visualize_raw import RawMeshData

    mesh = RawMeshData(
        points=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        faces=[(0, 1, 2)],
        face_ids=[0],
    )

    def fake_build_shape_display_mesh(shape, linear_deflection=0.5, angular_deflection=0.5):
        assert shape == "boolean-shape"
        assert linear_deflection == 0.25
        assert angular_deflection == 0.5
        return mesh

    monkeypatch.setattr(main, "build_shape_display_mesh", fake_build_shape_display_mesh)

    feature = SimpleNamespace(
        feature_id=7,
        boolean_intersection_shapes=["boolean-shape"],
        boolean_intersection_face_ids=[3, 4],
        severity="critical",
        geometric_feature_type="hook/undercut-ledge-candidate",
        geometric_feature_confidence=0.82,
        undercut_type="external",
        recommended_mold_action="side-action required",
        action_confidence=0.88,
        action_confidence_label="high",
        action_explanation="High confidence because Boolean interference is confirmed.",
        release_direction=(1.0, 0.0, 0.0),
        depth_proxy_mm=2.5,
    )

    payload = main._boolean_region_mesh_payloads([feature], mesh_deflection=0.25)

    assert payload["region_count"] == 1
    assert payload["triangle_count"] == 1
    assert payload["point_count"] == 3
    assert "legend" in payload
    assert payload["warnings"] == []

    region = payload["regions"][0]
    assert region["feature_id"] == 7
    assert region["severity"] == "critical"
    assert region["source_face_ids"] == [3, 4]
    assert region["geometric_feature_type"] == "hook/undercut-ledge-candidate"
    assert region["geometric_feature_confidence"] == 0.82
    assert region["action_confidence"] == 0.88
    assert region["action_confidence_label"] == "high"
    assert region["action_explanation"] == "High confidence because Boolean interference is confirmed."
    assert region["release_direction"] == [1.0, 0.0, 0.0]
    assert region["depth_proxy_mm"] == 2.5
    assert region["mesh"]["points"] == [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    assert region["mesh"]["faces"] == [[0, 1, 2]]
    assert region["mesh"]["feature_ids"] == [7]
    assert region["mesh"]["region_rgb"] == [[1.0, 0.10, 0.04]]
    assert region["visual_style"]["label"] == "Critical Boolean interference"
