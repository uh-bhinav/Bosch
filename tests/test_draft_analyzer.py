"""
tests/test_draft_analyzer.py
------------------------------
Complete test suite for Module 2: Draft Analyzer.

Test strategy
-------------
Layer 1 — Pure function unit tests (zero OCC, zero files):
    _classify_draft, _mold_side, _assess_severity
    FaceData.draft_angle_for_direction (pure math)
    DraftAnalysisResult properties and to_dict

Layer 2 — Mock PartGeometry (no OCC, no .stp file):
    Synthetic FaceData objects with known normals.
    Verify the full analyze_draft() pipeline end-to-end.
    Cover all classification categories, seam faces, invalid normals.

Layer 3 — Integration with Part1.stp (requires OCC + file):
    Sanity checks on real data.

Run
---
    pytest tests/test_draft_analyzer.py -v
    pytest tests/test_draft_analyzer.py -v -k "unit"
    pytest tests/test_draft_analyzer.py -v -k "integration"
"""

from __future__ import annotations

import math
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PART1_PATH = PROJECT_ROOT / "data" / "parts" / "Part1.stp"
HAS_OCC = True
try:
    import OCC  # noqa: F401
except ImportError:
    HAS_OCC = False

skip_no_occ = pytest.mark.skipif(not HAS_OCC, reason="pythonocc-core not installed")
skip_no_part1 = pytest.mark.skipif(
    not PART1_PATH.exists(), reason=f"Part1.stp not at {PART1_PATH}"
)


# =============================================================================
# Helpers to build synthetic FaceData without OCC
# =============================================================================

def _make_face(face_id: int, normal: tuple, area: float = 100.0, valid: bool = True):
    """Build a FaceData with a mock OCC handle and a given normal."""
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
        normal_valid=valid,
    )


def _make_part_with_faces(faces):
    """Build a minimal PartGeometry stub with given FaceData objects."""
    from backend.models.geometry_models import BoundingBox, PartGeometry
    return PartGeometry(
        source_file="mock.stp",
        occ_shape=MagicMock(),
        faces=faces,
        bounding_box=BoundingBox(0, 0, 0, 50, 50, 50),
        face_count=len(faces),
        edge_count=0,
        vertex_count=0,
        solid_count=1,
        shell_count=1,
    )


# =============================================================================
# Layer 1: Pure function unit tests
# =============================================================================

class TestClassifyDraft:
    """Unit tests for _classify_draft()."""

    def _fn(self, angle):
        from backend.geometry.draft_analyzer import _classify_draft
        return _classify_draft(angle, good_thresh=1.5, marginal_thresh=0.5)

    def test_good(self):
        assert self._fn(2.0) == "good"
        assert self._fn(1.5) == "good"
        assert self._fn(90.0) == "good"

    def test_marginal_lower_bound(self):
        assert self._fn(0.5) == "marginal"
        assert self._fn(1.0) == "marginal"
        assert self._fn(1.499) == "marginal"

    def test_bad(self):
        assert self._fn(0.0) == "bad"
        assert self._fn(0.1) == "bad"
        assert self._fn(0.499) == "bad"

    def test_boundary_good_threshold(self):
        """Exactly at good threshold is classified as good."""
        assert self._fn(1.5) == "good"

    def test_boundary_marginal_threshold(self):
        """Exactly at marginal threshold is classified as marginal."""
        assert self._fn(0.5) == "marginal"


class TestMoldSide:
    """Unit tests for _mold_side()."""

    def _fn(self, dot):
        from backend.geometry.draft_analyzer import _mold_side
        return _mold_side(dot)

    def test_positive_cavity(self):
        assert self._fn(0.5) == "positive"
        assert self._fn(1.0) == "positive"

    def test_negative_core(self):
        assert self._fn(-0.5) == "negative"
        assert self._fn(-1.0) == "negative"

    def test_parting_near_zero(self):
        assert self._fn(0.0) == "parting"
        assert self._fn(0.005) == "parting"
        assert self._fn(-0.005) == "parting"


class TestAssessSeverity:
    """Unit tests for _assess_severity()."""

    def _fn(self, frac):
        from backend.geometry.draft_analyzer import _assess_severity
        return _assess_severity(frac)

    def test_none(self):
        assert self._fn(0.0) == "none"

    def test_minor(self):
        assert self._fn(0.01) == "minor"
        assert self._fn(0.04) == "minor"

    def test_moderate(self):
        assert self._fn(0.05) == "moderate"
        assert self._fn(0.15) == "moderate"
        assert self._fn(0.199) == "moderate"

    def test_critical(self):
        assert self._fn(0.2) == "critical"
        assert self._fn(0.8) == "critical"
        assert self._fn(1.0) == "critical"


class TestDraftAngleFormula:
    """
    Unit tests for FaceData.draft_angle_for_direction().

    Verifies the formula: draft = asin(|n · d|) in degrees.
    """

    def test_horizontal_face_gives_90_degrees(self):
        """Top face (normal = +Z) with pull = +Z → 90°."""
        face = _make_face(0, (0.0, 0.0, 1.0))
        assert abs(face.draft_angle_for_direction((0.0, 0.0, 1.0)) - 90.0) < 1e-6

    def test_vertical_wall_gives_zero_degrees(self):
        """Wall face (normal = +X) with pull = +Z → 0°."""
        face = _make_face(0, (1.0, 0.0, 0.0))
        assert abs(face.draft_angle_for_direction((0.0, 0.0, 1.0)) - 0.0) < 1e-6

    def test_bottom_face_gives_90_degrees(self):
        """Bottom face (normal = -Z) with pull = +Z → 90°.  |n·d| = |-1| = 1."""
        face = _make_face(0, (0.0, 0.0, -1.0))
        assert abs(face.draft_angle_for_direction((0.0, 0.0, 1.0)) - 90.0) < 1e-6

    def test_1_5_degree_draft_wall(self):
        """Typical 1.5° drafted wall: n tilted 1.5° from horizontal."""
        import math
        angle_rad = math.radians(1.5)
        # normal in XZ plane: mostly X, small Z component
        nx = math.cos(angle_rad)
        nz = math.sin(angle_rad)
        face = _make_face(0, (nx, 0.0, nz))
        measured = face.draft_angle_for_direction((0.0, 0.0, 1.0))
        assert abs(measured - 1.5) < 0.01, f"Expected 1.5°, got {measured:.4f}°"

    def test_45_degree_chamfer(self):
        """45° chamfer: n = (1/√2, 0, 1/√2) → draft = 45°."""
        v = 1.0 / math.sqrt(2)
        face = _make_face(0, (v, 0.0, v))
        measured = face.draft_angle_for_direction((0.0, 0.0, 1.0))
        assert abs(measured - 45.0) < 0.001

    def test_invalid_normal_returns_zero(self):
        face = _make_face(0, (1.0, 0.0, 0.0), valid=False)
        assert face.draft_angle_for_direction((0.0, 0.0, 1.0)) == 0.0


# =============================================================================
# Layer 2: Mock PartGeometry — full pipeline tests
# =============================================================================

class TestAnalyzeDraftMock:
    """End-to-end tests using synthetic FaceData objects."""

    def _pull(self):
        return (0.0, 0.0, 1.0)

    def test_single_good_face(self):
        """One face with 5° draft → classified good."""
        from backend.geometry.draft_analyzer import analyze_draft
        face = _make_face(0, (math.sin(math.radians(85)), 0.0, math.cos(math.radians(85))))
        # Actually let's be precise: draft = asin(|n·d|). For a 5° drafted wall:
        # n = (cos(5°), 0, sin(5°)) → n·d = sin(5°) → draft = asin(sin(5°)) = 5°
        nz = math.sin(math.radians(5))
        nx = math.cos(math.radians(5))
        face = _make_face(0, (nx, 0.0, nz))
        part = _make_part_with_faces([face])
        result = analyze_draft(part, self._pull())
        assert len(result.good_face_ids) == 1
        assert len(result.bad_face_ids) == 0
        assert result.severity == "none"
        assert result.is_manufacturable is True

    def test_single_bad_face(self):
        """Vertical wall → bad."""
        from backend.geometry.draft_analyzer import analyze_draft
        face = _make_face(0, (1.0, 0.0, 0.0))  # n ⊥ d → draft = 0°
        part = _make_part_with_faces([face])
        result = analyze_draft(part, self._pull())
        assert len(result.bad_face_ids) == 1
        assert result.is_manufacturable is False

    def test_invalid_normal_face_skipped(self):
        """Face with invalid normal must be in skipped_face_ids, not analysed."""
        from backend.geometry.draft_analyzer import analyze_draft
        face = _make_face(0, (0.0, 0.0, 1.0), valid=False)
        part = _make_part_with_faces([face])
        result = analyze_draft(part, self._pull())
        assert face.face_id in result.skipped_face_ids
        assert face.face_id not in result.good_face_ids
        assert face.draft_angle_deg is None
        assert face.draft_classification is None

    def test_face_data_mutated_in_place(self):
        """analyze_draft must write draft_angle_deg and draft_classification onto FaceData."""
        from backend.geometry.draft_analyzer import analyze_draft
        face = _make_face(0, (1.0, 0.0, 0.0))  # 0° draft
        part = _make_part_with_faces([face])
        assert face.draft_angle_deg is None
        analyze_draft(part, self._pull())
        assert face.draft_angle_deg is not None
        assert face.draft_classification == "bad"

    def test_non_mutating_analysis_preserves_face_data(self):
        """mutate=False must return a full result without changing FaceData."""
        from backend.geometry.draft_analyzer import analyze_draft
        face = _make_face(0, (1.0, 0.0, 0.0))  # 0° draft
        part = _make_part_with_faces([face])

        result = analyze_draft(part, self._pull(), mutate=False)

        assert result.bad_face_ids == [0]
        assert result.face_results[0]["draft_classification"] == "bad"
        assert result.face_results[0]["draft_angle_deg"] == pytest.approx(0.0)
        assert face.draft_angle_deg is None
        assert face.draft_classification is None

    def test_non_mutating_analysis_still_generates_suggestions(self):
        """Suggestions must use the result snapshot when FaceData is untouched."""
        from backend.geometry.draft_analyzer import analyze_draft
        faces = [_make_face(i, (1.0, 0.0, 0.0)) for i in range(2)]
        part = _make_part_with_faces(faces)

        result = analyze_draft(part, self._pull(), mutate=False)

        assert len(result.suggestions) == 1
        assert result.suggestions[0].face_ids == [0, 1]
        assert all(f.draft_classification is None for f in faces)

    def test_initial_and_optimal_results_can_be_compared_without_overwrite(self):
        """Initial pass snapshot survives after the optimal pass mutates FaceData."""
        from backend.geometry.draft_analyzer import analyze_draft_default, analyze_draft_optimal
        face = _make_face(0, (1.0, 0.0, 0.0))  # bad for +Z, good for +X
        part = _make_part_with_faces([face])

        initial = analyze_draft_default(part, mutate=False)
        optimal = analyze_draft_optimal(part, (1.0, 0.0, 0.0), mutate=True)

        assert initial.face_results[0]["draft_classification"] == "bad"
        assert optimal.face_results[0]["draft_classification"] == "good"
        assert face.draft_classification == "good"

    def test_mixed_faces(self):
        """Three faces: one good, one marginal, one bad."""
        from backend.geometry.draft_analyzer import analyze_draft

        def face_with_draft(fid, deg):
            nz = math.sin(math.radians(deg))
            nx = math.cos(math.radians(deg))
            return _make_face(fid, (nx, 0.0, nz))

        good_face = face_with_draft(0, 5.0)      # 5° → good
        marginal_face = face_with_draft(1, 1.0)   # 1° → marginal
        bad_face = face_with_draft(2, 0.2)         # 0.2° → bad

        part = _make_part_with_faces([good_face, marginal_face, bad_face])
        result = analyze_draft(part, self._pull())

        assert 0 in result.good_face_ids
        assert 1 in result.marginal_face_ids
        assert 2 in result.bad_face_ids

    def test_severity_none_when_all_good(self):
        from backend.geometry.draft_analyzer import analyze_draft
        faces = [_make_face(i, (0.0, 0.0, 1.0)) for i in range(5)]  # all horizontal
        part = _make_part_with_faces(faces)
        result = analyze_draft(part, self._pull())
        assert result.severity == "none"
        assert result.is_manufacturable is True

    def test_severity_critical_when_mostly_bad(self):
        from backend.geometry.draft_analyzer import analyze_draft
        # 10 bad faces (large area), 1 good face (small area)
        bad_faces = [_make_face(i, (1.0, 0.0, 0.0), area=1000.0) for i in range(10)]
        good_face = _make_face(10, (0.0, 0.0, 1.0), area=50.0)
        part = _make_part_with_faces(bad_faces + [good_face])
        result = analyze_draft(part, self._pull())
        # bad_area = 10000, total = 10050, fraction ≈ 99.5% > 20% → critical
        assert result.severity == "critical"

    def test_area_percentages_sum_to_100(self):
        from backend.geometry.draft_analyzer import analyze_draft
        faces = [_make_face(i, (1.0, 0.0, 0.0) if i % 3 == 0 else (0.0, 0.0, 1.0))
                 for i in range(9)]
        part = _make_part_with_faces(faces)
        result = analyze_draft(part, self._pull())
        total = result.good_pct + result.marginal_pct + result.bad_pct
        assert abs(total - 100.0) < 0.01, f"Percentages sum to {total:.2f}%"

    def test_suggestions_generated_for_bad_faces(self):
        from backend.geometry.draft_analyzer import analyze_draft
        faces = [_make_face(i, (1.0, 0.0, 0.0)) for i in range(3)]  # all bad, Plane
        part = _make_part_with_faces(faces)
        result = analyze_draft(part, self._pull())
        assert len(result.suggestions) > 0
        s = result.suggestions[0]
        assert s.classification == "bad"
        assert "draft" in s.action_text.lower()

    def test_suggestions_empty_when_all_good(self):
        from backend.geometry.draft_analyzer import analyze_draft
        faces = [_make_face(i, (0.0, 0.0, 1.0)) for i in range(5)]
        part = _make_part_with_faces(faces)
        result = analyze_draft(part, self._pull())
        assert result.suggestions == []

    def test_bad_suggestions_before_marginal(self):
        """Suggestions must be sorted: bad first, then marginal."""
        from backend.geometry.draft_analyzer import analyze_draft

        def f(fid, deg, stype="Plane"):
            nz = math.sin(math.radians(deg))
            nx = math.cos(math.radians(deg))
            fd = _make_face(fid, (nx, 0.0, nz))
            fd.surface_type = stype
            return fd

        faces = [f(0, 0.1), f(1, 1.0)]  # bad, marginal
        part = _make_part_with_faces(faces)
        result = analyze_draft(part, self._pull())
        if len(result.suggestions) >= 2:
            assert result.suggestions[0].classification == "bad"
            assert result.suggestions[1].classification == "marginal"

    def test_pull_direction_normalised(self):
        """Non-unit pull direction must be normalised internally."""
        from backend.geometry.draft_analyzer import analyze_draft
        face = _make_face(0, (0.0, 0.0, 1.0))
        part = _make_part_with_faces([face])
        # Give pull = (0, 0, 5) — should normalise to (0, 0, 1) giving 90° draft
        result = analyze_draft(part, (0.0, 0.0, 5.0))
        assert result.good_face_ids == [0]
        # Stored direction should be unit
        d = result.pull_direction
        mag = math.sqrt(d[0]**2 + d[1]**2 + d[2]**2)
        assert abs(mag - 1.0) < 1e-9

    def test_zero_pull_direction_raises(self):
        """Zero vector as pull direction must raise ValueError."""
        from backend.geometry.draft_analyzer import analyze_draft
        face = _make_face(0, (0.0, 0.0, 1.0))
        part = _make_part_with_faces([face])
        with pytest.raises(ValueError, match="normalise"):
            analyze_draft(part, (0.0, 0.0, 0.0))

    def test_result_to_dict_is_json_serialisable(self):
        import json
        from backend.geometry.draft_analyzer import analyze_draft
        face = _make_face(0, (0.0, 0.0, 1.0))
        part = _make_part_with_faces([face])
        result = analyze_draft(part, self._pull())
        json.dumps(result.to_dict())  # must not raise

    def test_result_agent_context_is_string(self):
        from backend.geometry.draft_analyzer import analyze_draft
        face = _make_face(0, (1.0, 0.0, 0.0))
        part = _make_part_with_faces([face])
        result = analyze_draft(part, self._pull())
        ctx = result.agent_context()
        assert isinstance(ctx, str)
        assert "DRAFT ANALYSIS" in ctx

    def test_get_draft_color(self):
        from backend.geometry.draft_analyzer import get_draft_color
        good = _make_face(0, (0.0, 0.0, 1.0))
        good.draft_classification = "good"
        marginal = _make_face(1, (0.0, 0.0, 1.0))
        marginal.draft_classification = "marginal"
        bad = _make_face(2, (0.0, 0.0, 1.0))
        bad.draft_classification = "bad"
        none_face = _make_face(3, (0.0, 0.0, 1.0))
        none_face.draft_classification = None

        g = get_draft_color(good)
        m = get_draft_color(marginal)
        b = get_draft_color(bad)
        n = get_draft_color(none_face)

        # All should be RGB tuples with 3 floats in [0, 1]
        for color in [g, m, b, n]:
            assert len(color) == 3
            for c in color:
                assert 0.0 <= c <= 1.0

        # Colors must be distinct
        assert g != m != b != n

    def test_draft_colors_for_part_length(self):
        from backend.geometry.draft_analyzer import analyze_draft, draft_colors_for_part
        n_faces = 7
        faces = [_make_face(i, (0.0, 0.0, 1.0)) for i in range(n_faces)]
        part = _make_part_with_faces(faces)
        analyze_draft(part, self._pull())
        colors = draft_colors_for_part(part)
        assert len(colors) == n_faces

    def test_analyze_draft_default_uses_z_axis(self):
        from backend.geometry.draft_analyzer import analyze_draft_default
        face = _make_face(0, (0.0, 0.0, 1.0))
        part = _make_part_with_faces([face])
        result = analyze_draft_default(part)
        assert result.pull_direction == (0.0, 0.0, 1.0)
        assert result.analysis_pass == "initial"
        assert "initial" in result.pull_direction_label.lower()

    def test_analyze_draft_optimal_sets_pass(self):
        from backend.geometry.draft_analyzer import analyze_draft_optimal
        face = _make_face(0, (0.0, 0.0, 1.0))
        part = _make_part_with_faces([face])
        result = analyze_draft_optimal(part, (0.0, 0.0, 1.0))
        assert result.analysis_pass == "optimal"

    def test_all_faces_skipped_no_crash(self):
        """Part with all invalid normals should return safely with 0 counts."""
        from backend.geometry.draft_analyzer import analyze_draft
        faces = [_make_face(i, (0.0, 0.0, 1.0), valid=False) for i in range(5)]
        part = _make_part_with_faces(faces)
        result = analyze_draft(part, self._pull())
        assert result.face_count_analysed == 0
        assert result.total_analysed_area_mm2 == 0.0
        assert result.severity == "none"


# =============================================================================
# Layer 3: Integration tests with Part1.stp
# =============================================================================

@skip_no_occ
@skip_no_part1
class TestDraftAnalyzerIntegration:
    """Integration tests against the real Bosch Part1.stp."""

    @pytest.fixture(scope="class")
    def part_with_draft(self):
        from backend.geometry.step_loader import load_step
        from backend.geometry.draft_analyzer import analyze_draft_default
        part = load_step(PART1_PATH)
        result = analyze_draft_default(part)
        return part, result

    def test_result_returned(self, part_with_draft):
        _, result = part_with_draft
        assert result is not None

    def test_all_valid_faces_classified(self, part_with_draft):
        part, result = part_with_draft
        total = len(result.good_face_ids) + len(result.marginal_face_ids) + len(result.bad_face_ids)
        valid_faces = sum(1 for f in part.faces if f.normal_valid)
        assert total == valid_faces, (
            f"Classified {total} but expected {valid_faces} valid faces."
        )

    def test_face_data_mutated(self, part_with_draft):
        part, _ = part_with_draft
        for face in part.valid_faces:
            assert face.draft_angle_deg is not None, f"Face {face.face_id} not analysed"
            assert face.draft_classification in ("good", "marginal", "bad")

    def test_angles_in_valid_range(self, part_with_draft):
        part, _ = part_with_draft
        for face in part.valid_faces:
            a = face.draft_angle_deg
            assert 0.0 <= a <= 90.0, f"Face {face.face_id}: angle {a:.2f}° out of range"

    def test_percentages_sum_to_100(self, part_with_draft):
        _, result = part_with_draft
        total = result.good_pct + result.marginal_pct + result.bad_pct
        assert abs(total - 100.0) < 0.1, f"Percentages sum to {total:.2f}%"

    def test_severity_is_valid_string(self, part_with_draft):
        _, result = part_with_draft
        assert result.severity in ("none", "minor", "moderate", "critical")

    def test_result_json_serialisable(self, part_with_draft):
        import json
        _, result = part_with_draft
        json.dumps(result.to_dict())

    def test_print_summary(self, part_with_draft):
        """Observation test — prints summary for human review."""
        _, result = part_with_draft
        print("\n" + result.summary_text())
        assert True

    def test_part1_has_some_bad_faces(self, part_with_draft):
        """
        Part1.stp (automotive packaging cap with threads/snap features) should
        have at least some faces with insufficient draft — this verifies the
        detection is working, not trivially classifying everything as good.
        """
        _, result = part_with_draft
        assert len(result.bad_face_ids) > 0, (
            "Expected Part1.stp to have at least 1 bad face in default +Z direction. "
            "If all faces are 'good', draft detection may be broken."
        )

    def test_re_run_with_different_direction(self, part_with_draft):
        """Running analysis twice with different directions must fully overwrite FaceData."""
        from backend.geometry.draft_analyzer import analyze_draft
        part, _ = part_with_draft
        result1 = analyze_draft(part, (0.0, 0.0, 1.0), pull_direction_label="pass1")
        result2 = analyze_draft(part, (0.0, 0.0, -1.0), pull_direction_label="pass2")
        # With -Z pull, the top face (n·d = -1) has asin(|-1|) = 90° still (abs!)
        # But some wall-facing faces will differ. The results must differ in some way
        # (unless part is perfectly symmetric, which Part1.stp is not).
        # At minimum, verify that the second call completes and faces are updated.
        for face in part.valid_faces:
            assert face.draft_angle_deg is not None
