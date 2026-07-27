"""
tests/test_step_loader.py
--------------------------
Test suite for Module 1: STEP Loader.

Test strategy
-------------
1. Unit tests with mocks (no STEP file, no OCC required) — always run.
2. Integration tests against the real Part1.stp (skipped if file absent).
3. Edge-case tests: corrupt file, wrong extension, empty shape.

Run
---
    pytest tests/test_step_loader.py -v
    pytest tests/test_step_loader.py -v -k "unit"       # mocks only
    pytest tests/test_step_loader.py -v -k "integration" # real file
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Helpers & paths
# ─────────────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PART1_PATH = PROJECT_ROOT / "data" / "parts" / "Part1.stp"
HAS_PART1 = PART1_PATH.exists()
HAS_OCC = True
try:
    import OCC  # noqa: F401
except ImportError:
    HAS_OCC = False

skip_no_occ = pytest.mark.skipif(not HAS_OCC, reason="pythonocc-core not installed")
skip_no_part1 = pytest.mark.skipif(
    not HAS_PART1, reason=f"Part1.stp not found at {PART1_PATH}"
)


# ─────────────────────────────────────────────────────────────────────────────
# Geometry model tests  (no OCC required)
# ─────────────────────────────────────────────────────────────────────────────

class TestBoundingBox:
    """Unit tests for BoundingBox dataclass."""

    def _make_bbox(self, xmin=0, ymin=0, zmin=0, xmax=10, ymax=20, zmax=30):
        from backend.models.geometry_models import BoundingBox
        return BoundingBox(
            xmin=xmin, ymin=ymin, zmin=zmin,
            xmax=xmax, ymax=ymax, zmax=zmax,
        )

    def test_diagonal(self):
        bbox = self._make_bbox(0, 0, 0, 10, 20, 30)
        expected = math.sqrt(10**2 + 20**2 + 30**2)
        assert abs(bbox.diagonal - expected) < 1e-9

    def test_center(self):
        bbox = self._make_bbox(0, 0, 0, 10, 20, 30)
        assert bbox.center == (5.0, 10.0, 15.0)

    def test_dimensions(self):
        bbox = self._make_bbox(xmin=5, xmax=15, ymin=2, ymax=12, zmin=1, zmax=21)
        assert bbox.dimensions == (10.0, 10.0, 20.0)

    def test_max_dimension(self):
        bbox = self._make_bbox(0, 0, 0, 100, 50, 30)
        assert bbox.max_dimension == 100.0

    def test_to_dict_keys(self):
        bbox = self._make_bbox()
        d = bbox.to_dict()
        for key in ["xmin", "xmax", "ymin", "ymax", "zmin", "zmax",
                    "diagonal_mm", "center_mm", "dimensions_mm"]:
            assert key in d, f"Missing key: {key}"


class TestFaceData:
    """Unit tests for FaceData dataclass."""

    def _make_face(self, normal=(0.0, 0.0, 1.0)):
        from backend.models.geometry_models import FaceData
        mock_occ_face = MagicMock()
        return FaceData(
            face_id=0,
            occ_face=mock_occ_face,
            surface_type="Plane",
            normal=normal,
            centroid=(5.0, 5.0, 0.0),
            area=100.0,
            u_range=(0.0, 10.0),
            v_range=(0.0, 10.0),
            is_reversed=False,
            normal_valid=True,
        )

    def test_draft_angle_face_parallel_to_pull(self):
        """Face pointing exactly in pull direction → 90° draft."""
        face = self._make_face(normal=(0.0, 0.0, 1.0))
        angle = face.draft_angle_for_direction((0.0, 0.0, 1.0))
        assert abs(angle - 90.0) < 0.001

    def test_draft_angle_face_perpendicular_to_pull(self):
        """Vertical wall (normal perpendicular to pull) → 0° draft."""
        face = self._make_face(normal=(1.0, 0.0, 0.0))
        angle = face.draft_angle_for_direction((0.0, 0.0, 1.0))
        assert abs(angle - 0.0) < 0.001

    def test_draft_angle_typical_1_5_degrees(self):
        """Face with 1.5° draft: n·d = sin(1.5°) ≈ 0.02618."""
        import math
        pull = (0.0, 0.0, 1.0)
        target_deg = 1.5
        sin_val = math.sin(math.radians(target_deg))
        # normal is in X-Z plane, tilted 1.5° from horizontal
        cos_val = math.cos(math.radians(target_deg))
        face = self._make_face(normal=(cos_val, 0.0, sin_val))
        angle = face.draft_angle_for_direction(pull)
        assert abs(angle - target_deg) < 0.01, f"Expected ~1.5°, got {angle:.4f}°"

    def test_draft_angle_invalid_normal(self):
        """Invalid normal should return 0.0 safely."""
        face = self._make_face(normal=(0.0, 0.0, 1.0))
        face.normal_valid = False
        angle = face.draft_angle_for_direction((0.0, 0.0, 1.0))
        assert angle == 0.0

    def test_to_dict_no_occ_objects(self):
        """to_dict() must not contain any non-serialisable objects."""
        import json
        face = self._make_face()
        d = face.to_dict()
        # Should not raise
        json.dumps(d)

    def test_to_dict_required_keys(self):
        face = self._make_face()
        d = face.to_dict()
        for key in ["face_id", "surface_type", "normal", "centroid",
                    "area_mm2", "is_reversed", "normal_valid"]:
            assert key in d, f"Missing key in to_dict(): {key}"


class TestDot3AndNormalize:
    """Unit tests for primitive geometry helpers."""

    def test_dot3(self):
        from backend.models.geometry_models import dot3
        assert dot3((1, 0, 0), (0, 1, 0)) == 0.0
        assert dot3((1, 0, 0), (1, 0, 0)) == 1.0
        assert abs(dot3((0.5, 0.5, 0.0), (1.0, 0.0, 0.0)) - 0.5) < 1e-9

    def test_normalize3(self):
        from backend.models.geometry_models import normalize3
        v = normalize3((3.0, 4.0, 0.0))
        assert abs(math.sqrt(v[0]**2 + v[1]**2 + v[2]**2) - 1.0) < 1e-9
        assert abs(v[0] - 0.6) < 1e-9
        assert abs(v[1] - 0.8) < 1e-9

    def test_normalize3_zero_raises(self):
        from backend.models.geometry_models import normalize3
        with pytest.raises(ValueError):
            normalize3((0.0, 0.0, 0.0))


# ─────────────────────────────────────────────────────────────────────────────
# STEPLoadError and FileNotFoundError  (no OCC required)
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadStepErrors:
    """Error path tests — patching OCC so they run without it installed."""

    def test_file_not_found(self, tmp_path):
        from backend.geometry.step_loader import load_step
        with pytest.raises(FileNotFoundError, match="not found"):
            load_step(tmp_path / "does_not_exist.stp")

    @skip_no_occ
    def test_corrupt_file_raises_step_load_error(self, tmp_path):
        """A file with garbage content should raise STEPLoadError."""
        from backend.geometry.step_loader import STEPLoadError, load_step
        bad = tmp_path / "corrupt.stp"
        bad.write_text("THIS IS NOT A STEP FILE\nrandom garbage\n")
        with pytest.raises(STEPLoadError):
            load_step(bad)

    def test_load_with_fallback_returns_none_on_missing(self, tmp_path):
        from backend.geometry.step_loader import load_step_with_fallback
        result = load_step_with_fallback(tmp_path / "missing.stp", strict=False)
        assert result is None

    def test_load_with_fallback_strict_raises(self, tmp_path):
        from backend.geometry.step_loader import load_step_with_fallback
        with pytest.raises(FileNotFoundError):
            load_step_with_fallback(tmp_path / "missing.stp", strict=True)


# ─────────────────────────────────────────────────────────────────────────────
# Config tests  (no OCC required)
# ─────────────────────────────────────────────────────────────────────────────

class TestConfig:
    def test_settings_loads_without_file(self):
        """Settings should fall back to defaults when config.yaml is absent."""
        from backend.config import load_settings
        s = load_settings(config_path="/nonexistent/config.yaml")
        assert s.dfm.draft.good_threshold_deg == 1.5
        assert s.dfm.draft.marginal_threshold_deg == 0.5
        assert s.dfm.direction_search.angular_step_deg == 15.0
        assert s.dfm.direction_search.boolean_refine_top_candidates == 5
        assert s.dfm.direction_search.boolean_refine_max_faces == 80
        assert s.agent.temperature == 0.1

    def test_settings_from_project_yaml(self):
        """Settings loaded from our real config.yaml."""
        from backend.config import settings
        # These match our config.yaml values
        assert settings.dfm.draft.good_threshold_deg == 1.5
        assert settings.dfm.direction_search.max_candidates == 54
        assert settings.dfm.direction_search.boolean_refine_score_margin == 0.25
        assert settings.dfm.core_cavity.cavity_color == (0.2, 0.8, 0.3)

    def test_settings_frozen(self):
        """Settings must be immutable (frozen=True)."""
        from backend.config import settings
        with pytest.raises((TypeError, AttributeError)):
            settings.dfm.draft.good_threshold_deg = 99.0  # type: ignore[misc]


# ─────────────────────────────────────────────────────────────────────────────
# Integration tests  (require Part1.stp + OCC)
# ─────────────────────────────────────────────────────────────────────────────

@skip_no_occ
@skip_no_part1
class TestLoadStepIntegration:
    """
    Full integration tests against the real Part1.stp provided by Bosch.

    Expected characteristics (from Quick_Analysis_of_the_File PDF):
    - Single MANIFOLD_SOLID_BREP (1 solid)
    - Hundreds of faces: cylinders, cones, spheres, tori, BSpline/NURBS
    - Siemens NX 2412 origin
    """

    @pytest.fixture(scope="class")
    def part(self):
        from backend.geometry.step_loader import load_step
        return load_step(PART1_PATH)

    # ── Load sanity ───────────────────────────────────────────────────────

    def test_loads_without_error(self, part):
        assert part is not None

    def test_has_faces(self, part):
        assert part.face_count > 0, "Part must have at least 1 face"

    def test_has_edges(self, part):
        assert part.edge_count > 0

    def test_has_at_least_one_solid(self, part):
        assert part.solid_count >= 1

    def test_faces_list_length_matches_face_count(self, part):
        assert len(part.faces) == part.face_count

    def test_load_time_is_reasonable(self, part):
        # Loading should complete well under 60 seconds for a moderate part
        assert part.load_time_s < 60.0, f"Load took {part.load_time_s:.1f}s — too slow"

    # ── Bounding box ─────────────────────────────────────────────────────

    def test_bounding_box_is_finite(self, part):
        bb = part.bounding_box
        for val in [bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax]:
            assert math.isfinite(val), f"Non-finite bbox value: {val}"

    def test_bounding_box_positive_diagonal(self, part):
        assert part.bounding_box.diagonal > 0.0

    def test_bounding_box_dimensions_positive(self, part):
        dims = part.bounding_box.dimensions
        for d in dims:
            assert d > 0.0, f"Non-positive dimension: {d}"

    # ── Face data quality ─────────────────────────────────────────────────

    def test_face_ids_are_sequential_from_zero(self, part):
        for i, face in enumerate(part.faces):
            assert face.face_id == i, f"Face {i} has id {face.face_id}"

    def test_most_faces_have_valid_normals(self, part):
        valid_ratio = sum(1 for f in part.faces if f.normal_valid) / part.face_count
        assert valid_ratio > 0.9, (
            f"Only {valid_ratio:.1%} faces have valid normals — "
            "check normal computation logic"
        )

    def test_normals_are_unit_vectors(self, part):
        for face in part.faces:
            if not face.normal_valid:
                continue
            n = face.normal
            mag = math.sqrt(n[0]**2 + n[1]**2 + n[2]**2)
            assert abs(mag - 1.0) < 1e-5, (
                f"Face {face.face_id} normal magnitude = {mag:.6f} (not unit)"
            )

    def test_face_areas_non_negative(self, part):
        for face in part.faces:
            assert face.area >= 0.0, f"Face {face.face_id} has negative area"

    def test_surface_type_breakdown_contains_expected_types(self, part):
        """
        Per Quick_Analysis_of_the_File PDF, Part1.stp has:
        cylinders, cones, spheres, tori, BSpline/NURBS.
        """
        stypes = part.surface_type_counts
        # At minimum we expect planes and some curved surfaces
        assert "Plane" in stypes or "Cylinder" in stypes, (
            f"Unexpected surface types: {stypes}"
        )

    # ── Serialisation ─────────────────────────────────────────────────────

    def test_to_dict_is_json_serialisable(self, part):
        import json
        d = part.to_dict(include_faces=False)
        json.dumps(d)  # Should not raise

    def test_to_dict_with_faces_is_json_serialisable(self, part):
        import json
        d = part.to_dict(include_faces=True)
        json.dumps(d)  # Should not raise

    def test_summary_returns_string(self, part):
        s = part.summary()
        assert isinstance(s, str)
        assert "Faces" in s

    # ── Part1.stp specific assertions ─────────────────────────────────────

    def test_single_solid(self, part):
        """Quick_Analysis PDF: 'Single MANIFOLD_SOLID_BREP (one solid body)'."""
        assert part.solid_count == 1, (
            f"Expected 1 solid, got {part.solid_count}"
        )

    def test_nurbs_surfaces_present(self, part):
        """Quick_Analysis PDF: 'Many B-spline / NURBS surfaces'."""
        nurbs_count = part.surface_type_counts.get("BSpline/NURBS", 0)
        assert nurbs_count > 0, (
            f"Expected BSpline/NURBS faces in Part1.stp, got 0. "
            f"Surface types: {part.surface_type_counts}"
        )

    def test_get_face_by_id(self, part):
        """get_face() must return the correct FaceData by face_id."""
        for test_id in [0, part.face_count // 2, part.face_count - 1]:
            face = part.get_face(test_id)
            assert face is not None, f"get_face({test_id}) returned None"
            assert face.face_id == test_id

    def test_valid_faces_count(self, part):
        valid = part.valid_faces
        assert len(valid) > 0
        assert all(f.normal_valid for f in valid)

    # ── Edge convexity (Roadmap Phase 1.1) ──────────────────────────────────

    def test_manifold_edges_have_convexity_classified(self, part):
        """
        Every manifold, non-seam edge should get a convexity classification
        on a well-formed real part. A large fraction landing on None would
        indicate systematic OCC evaluation failures (bad pcurves, degenerate
        tangents), not occasional per-edge geometry issues.
        """
        manifold_edges = [e for e in part.edges if e.is_manifold and not e.is_seam]
        assert manifold_edges, "Expected at least one manifold edge"
        classified = [e for e in manifold_edges if e.convexity is not None]
        ratio = len(classified) / len(manifold_edges)
        assert ratio > 0.9, (
            f"Only {ratio:.1%} of manifold edges got a convexity value — "
            "check _compute_edge_convexity for systematic failures"
        )
        for e in classified:
            assert e.convexity in ("convex", "concave", "tangent")

    def test_boundary_edges_have_no_convexity(self, part):
        """Convexity is only meaningful for manifold (2-face) edges."""
        for e in part.edges:
            if e.is_boundary or e.is_seam:
                assert e.convexity is None


# ─────────────────────────────────────────────────────────────────────────────
# Edge convexity — synthetic OCC shapes (Roadmap Phase 1.1)
#
# Real .stp integration tests can't isolate a known-correct answer (nobody
# can eyeball "concave" vs "convex" on 700+ real edges). These build shapes
# by hand where the right answer is obvious from the construction, so a sign
# error in the convexity formula fails loudly instead of hiding in a real
# part's face count. See docs/ARCHITECTURE_ROADMAP.md Milestone 1.1 gate.
# ─────────────────────────────────────────────────────────────────────────────

@skip_no_occ
class TestEdgeConvexitySynthetic:
    """No .stp file needed — shapes are built directly via OCC primitives."""

    @staticmethod
    def _edges_of(shape):
        from backend.geometry.step_loader import (
            _extract_all_faces,
            _extract_edges_and_build_adjacency,
        )
        warnings: list[str] = []
        faces = _extract_all_faces(shape, warnings)
        edges, _, _, _ = _extract_edges_and_build_adjacency(shape, faces, warnings)
        return edges

    def test_plain_box_is_fully_convex(self):
        """A cube has 12 edges; every one is an outside (convex) corner."""
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox

        box = BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape()
        edges = self._edges_of(box)
        manifold = [e for e in edges if e.is_manifold and not e.is_seam]

        assert len(manifold) == 12
        assert all(e.convexity == "convex" for e in manifold), (
            f"Expected all 12 box edges convex, got: "
            f"{[e.convexity for e in manifold]}"
        )

    def test_box_with_pocket_floor_edges_are_concave(self):
        """
        A 4x4x4 rectangular pocket cut into the top of a 10x10x10 box.
        The pocket floor's 4 perimeter edges (where the vertical pocket
        wall meets the horizontal pocket floor) are concave — an inside
        corner, same family as the inside corner of a room.
        """
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox
        from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Cut
        from OCC.Core.gp import gp_Pnt

        box = BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape()
        # Tool spans z=[6, 11]: overlaps the box top (z=10) so it cuts a
        # blind pocket with its floor at z=6, not a through-hole.
        pocket_tool = BRepPrimAPI_MakeBox(gp_Pnt(3.0, 3.0, 6.0), 4.0, 4.0, 5.0).Shape()
        cut = BRepAlgoAPI_Cut(box, pocket_tool)
        assert cut.IsDone(), "Boolean cut failed — cannot build pocket fixture"

        edges = self._edges_of(cut.Shape())
        manifold = [e for e in edges if e.is_manifold and not e.is_seam]

        floor_edges = [
            e for e in manifold
            if e.start_vertex and e.end_vertex
            and abs(e.start_vertex[2] - 6.0) < 1e-6
            and abs(e.end_vertex[2] - 6.0) < 1e-6
        ]
        assert len(floor_edges) == 4, (
            f"Expected 4 pocket-floor edges at z=6, found {len(floor_edges)}"
        )
        assert all(e.convexity == "concave" for e in floor_edges), (
            f"Expected all 4 pocket-floor edges concave, got: "
            f"{[e.convexity for e in floor_edges]}"
        )

        # The box's own 12 edges are untouched by the pocket and must
        # remain convex — regression guard against the formula flipping
        # sign globally instead of correctly discriminating by geometry.
        box_corner_edges = [
            e for e in manifold
            if e.start_vertex and e.end_vertex
            and {round(e.start_vertex[i], 3) for i in range(3)} & {0.0, 10.0}
            and {round(e.end_vertex[i], 3) for i in range(3)} & {0.0, 10.0}
            and e not in floor_edges
        ]
        assert any(e.convexity == "convex" for e in box_corner_edges), (
            "Expected at least some original box edges to remain convex"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Accuracy benchmark  (printed, not asserted — for human review)
# ─────────────────────────────────────────────────────────────────────────────

@skip_no_occ
@skip_no_part1
def test_print_geometry_summary():
    """
    Not a pass/fail test — prints the full geometry summary for human review.
    Useful to verify numbers match expectations from Quick_Analysis_of_the_File PDF.
    """
    from backend.geometry.step_loader import load_step
    part = load_step(PART1_PATH)
    print("\n" + part.summary())
    # This test always passes — it's an observation test
    assert True
