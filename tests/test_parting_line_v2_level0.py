"""
tests/test_parting_line_v2_level0.py
------------------------------------
P1 acceptance tests for the v2 Level 0 pipeline.

Two kinds of test here, and the second kind matters more:

* **Analytic** — fixtures whose answer is known in closed form (a cube's rim
  perimeter is exactly 4 × 40 mm), so a wrong answer is provably wrong rather
  than merely surprising.
* **Regression** — the bugs P1 measurement caught, pinned so they cannot
  return.

The original "fail-loudly" tests (F3/F4/F17 must report
``no_feasible_candidate``) asserted **Level 0** behaviour and were correct at
P1. Track B solves those fixtures from P2 onward, so the claim moved to
``test_parting_line_v2_level1.py`` in its still-true form: their answers
**require face-backed segments** and no edge-only method can produce them.

Every test that touches OCC is marked ``requires_occ`` per
``.claude/rules/testing.md``.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from backend.geometry.parting_line_v2 import measures

REPO_ROOT = Path(__file__).resolve().parent.parent
SYNTHETIC = REPO_ROOT / "data" / "fixtures" / "synthetic"

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _occ_available() -> bool:
    try:
        import OCC  # noqa: F401
        return True
    except ImportError:
        return False


requires_occ = pytest.mark.skipif(not _occ_available(), reason="pythonOCC not installed")
requires_fixtures = pytest.mark.skipif(
    not (SYNTHETIC / "manifest.json").exists(),
    reason="fixtures not generated; run scripts/generate_fixtures.py",
)


def _analyse(filename: str, direction=(0.0, 0.0, 1.0)):
    from backend.config import settings
    from backend.geometry.parting_line_v2 import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line
    from backend.geometry.step_loader import load_step

    part = load_step(str(SYNTHETIC / filename))
    return analyse_parting_line(
        part,
        PullDirectionInput(direction, "fixture"),
        undercuts=UndercutInput.empty(),
        cfg=settings.dfm.parting_line_v2,
    )


# ---------------------------------------------------------------------------
# measures — pure math, no OCC needed
# ---------------------------------------------------------------------------

def test_shoelace_area_of_a_unit_square():
    square = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    assert abs(measures.shoelace_area(square)) == pytest.approx(1.0)


def test_shoelace_beats_bounding_box_on_an_L_shape():
    """
    The reason T1's numerator is the shoelace area and not a bbox area
    (audit RC-5): an L-shape and a square of the same extent are identical to
    a bounding box and obviously different in reality.
    """
    l_shape = [(0, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2)]
    assert abs(measures.shoelace_area(l_shape)) == pytest.approx(3.0)
    assert measures.bbox_area_2d(l_shape) == pytest.approx(4.0)


def test_excess_turning_is_zero_for_a_circle():
    """
    A turned part's parting line IS a circle. It must NOT be penalised — this
    is why T5 measures EXCESS turning over 2π rather than curvature.
    """
    n = 128
    circle = tuple(
        (math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n), 0.0)
        for i in range(n)
    )
    assert measures.total_turning(circle, closed=True) == pytest.approx(2 * math.pi, abs=1e-9)
    assert measures.excess_turning(circle, closed=True) == pytest.approx(0.0, abs=1e-9)


def test_excess_turning_is_zero_for_a_rectangle():
    """A rectangular housing's outline is ideal too — 4 corners, K = 2π."""
    rectangle = ((0, 0, 0), (4, 0, 0), (4, 2, 0), (0, 2, 0))
    assert measures.excess_turning(rectangle, closed=True) == pytest.approx(0.0, abs=1e-12)


def test_excess_turning_penalises_a_zigzag():
    zigzag = tuple(
        (float(i), 1.0 if i % 2 else -1.0, 0.0) for i in range(12)
    ) + ((11.0, -6.0, 0.0), (0.0, -6.0, 0.0))
    assert measures.excess_turning(zigzag, closed=True) > 1.0


def test_pull_axis_span_is_zero_for_a_planar_loop():
    flat = ((0, 0, 5.0), (1, 0, 5.0), (1, 1, 5.0), (0, 1, 5.0))
    assert measures.pull_axis_span(flat, (0, 0, 1)) == pytest.approx(0.0)


def test_pull_axis_span_measures_the_mold_step():
    stepped = ((0, 0, 0.0), (1, 0, 3.0), (1, 1, 0.0))
    assert measures.pull_axis_span(stepped, (0, 0, 1)) == pytest.approx(3.0)


def test_cauchy_area_is_exact_for_a_cube():
    """
    A_cauchy = ½·Σ A_f·|g_f|. For a 40 mm cube pulled +Z: top and bottom
    contribute 1600 each, the four sides contribute 0, so A = 1600 — exactly
    the true projected outline. Cauchy is exact for a convex body.
    """
    areas = [1600.0] * 6
    g_values = [1.0, 1.0, 0.0, 0.0, 0.0, 0.0]
    assert measures.cauchy_projected_area(areas, g_values) == pytest.approx(1600.0)


def test_cauchy_area_rejects_mismatched_inputs():
    with pytest.raises(ValueError):
        measures.cauchy_projected_area([1.0, 2.0], [1.0])


def test_self_intersection_detects_a_figure_eight():
    bowtie = ((0, 0, 0), (2, 2, 0), (2, 0, 0), (0, 2, 0))
    intersects, _, confirmed = measures.self_intersection(
        bowtie, (0, 0, 1), closed=True, tolerance=1e-6
    )
    assert intersects and confirmed >= 1


def test_projection_only_crossing_is_not_a_3d_intersection():
    """
    Two curves can overlap in projection while passing at different heights.
    Projection is a conservative FILTER; 3-D is the decider.
    """
    bowtie_lifted = ((0, 0, 0), (2, 2, 0), (2, 0, 10.0), (0, 2, 10.0))
    intersects, checked, _ = measures.self_intersection(
        bowtie_lifted, (0, 0, 1), closed=True, tolerance=1e-6
    )
    assert checked > 0, "the 2-D filter should have flagged a pair"
    assert not intersects, "but 3-D must clear it — the curves pass 10 mm apart"


# ---------------------------------------------------------------------------
# F1 cube — the analytic ground truth
# ---------------------------------------------------------------------------

@requires_occ
@requires_fixtures
def test_cube_finds_its_analytic_parting_line():
    """
    A 40 mm cube pulled +Z. Top face g=+1, sides g=0, bottom g=-1.

    ``μ = E − V + P = 12 − 8 + 1 = 5`` — a property of the graph, not of the
    search, so it holds whichever strategy runs. The answer is a rim: 4 × 40 mm,
    planar, four corners.

    The candidate COUNT is deliberately not asserted. It is strategy-specific
    (5 under the cycle basis at P1, 28 under Johnson from P3) and asserting it
    would pin the test to an implementation choice rather than to the geometry.
    What must hold either way: every rejection is H4 — the cube's other cycles
    are geometrically valid loops that put the top (g=+1) and bottom (g=−1)
    faces in the SAME region, which is an orientation failure, not a
    topological one.
    """
    result = _analyse("F1_cube.stp")
    assert result.outcome == "feasible"
    assert result.bounds.cyclomatic_number == 5
    assert result.bounds.branch_node_count == 8

    score = result.selected.score
    assert score.coverage == pytest.approx(1.0, abs=1e-6)
    assert score.length_3d_mm == pytest.approx(160.0, abs=1e-6), "4 x 40 mm rim"
    assert score.pull_axis_span_mm == pytest.approx(0.0, abs=1e-9), "rim is planar"
    assert score.excess_turning == pytest.approx(0.0, abs=1e-9), "4 corners, K = 2pi"
    assert set(result.rejection_summary) <= {"H4"}, (
        f"expected only orientation rejections, got {result.rejection_summary}"
    )


@requires_occ
@requires_fixtures
def test_cube_equal_optima_are_broken_at_the_final_tier():
    """
    Top rim and bottom rim are *exactly* equivalent on every measurable tier —
    same coverage, same span, same turning, same length. Only T7's stable_id
    can separate them, and it must.
    """
    result = _analyse("F1_cube.stp")
    assert result.selected.score.won_at_tier == "T7"


@requires_occ
@requires_fixtures
def test_cube_core_cavity_falls_out_of_h3():
    """
    Classification is a byproduct of the separation test, not a separate
    normal-sign pass. For the cube's top rim: cavity = the top face alone.
    """
    result = _analyse("F1_cube.stp")
    regions = result.regions
    assert len(regions.cavity_face_ids) + len(regions.core_face_ids) == 6
    assert min(len(regions.cavity_face_ids), len(regions.core_face_ids)) == 1


# ---------------------------------------------------------------------------
# Fail-loudly — the fixtures Level 0 genuinely cannot solve
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Regressions for the two bugs P1 measurement caught
# ---------------------------------------------------------------------------

@requires_occ
@requires_fixtures
def test_inclusive_straddle_finds_the_cube_top_rim():
    """
    Regression for the strict-vs-inclusive silhouette condition.

    The condition is ``0 ∈ [g_a, g_b]``, not ``g_a·g_b < 0``. On a cube the
    top face has g=1 and the side g=0, so the strict product test gives
    ``1 × 0 = 0`` — not negative — and finds NO silhouette on the rim you
    plainly see looking down the pull axis. First implementation had this bug
    and returned 4 tangential segments and nothing else.
    """
    from backend.config import settings
    from backend.geometry.parting_line_v2.track_a import detect_edge_silhouettes
    from backend.geometry.step_loader import load_step

    part = load_step(str(SYNTHETIC / "F1_cube.stp"))
    result = detect_edge_silhouettes(
        part, (0.0, 0.0, 1.0),
        cfg=settings.dfm.parting_line_v2, bbox_diagonal_mm=69.282,
    )
    assert len(result.silhouette_segments) == 8, "top rim (4) + bottom rim (4)"
    assert len(result.tangential_segments) == 4, "the 4 vertical zero-draft edges"


@requires_occ
@requires_fixtures
@pytest.mark.parametrize("filename", [
    "F2_cylinder_axis_parallel_to_pull.stp",
    "F5_cone.stp",
])
def test_closed_circular_edges_survive_two_core_reduction(filename):
    """
    Regression: a closed circular edge welds both endpoints to ONE node — a
    graph self-loop. Recorded once it has degree 1, and the 2-core prune
    deletes it as a dangling end.

    That silently discarded these parts' correct parting lines (a cylinder rim,
    a cone's base rim), and also F9's hole rim. A self-loop contributes 2 to
    the degree by convention, and here the convention is load-bearing.
    """
    result = _analyse(filename)
    assert result.outcome == "feasible"
    assert result.selected.score.coverage > 0.9


# ---------------------------------------------------------------------------
# C1 corrected — Γ is a disjoint union of closed curves
# ---------------------------------------------------------------------------

@requires_occ
@requires_fixtures
def test_through_hole_needs_a_two_curve_parting_line():
    """
    Plan C1, corrected 2026-08-09.

    Cutting the outer rim alone leaves the top face connected to the bottom
    face THROUGH THE HOLE WALL, so H3 reports 1 region. The parting line that
    actually separates a holed part is outer rim ⊔ hole rim — two disjoint
    closed curves. A single-loop model makes any part with a through-hole
    unanalysable, and holes are ubiquitous in real plastic parts.
    """
    result = _analyse("F9_box_with_through_hole.stp")
    assert result.outcome == "feasible"
    assert result.selected.loop_count == 2, "outer rim + hole rim"
    assert result.selected.discovered_by == "loop_union"


@requires_occ
@requires_fixtures
def test_coverage_may_exceed_one_for_a_holed_part():
    """
    Not a bug. The outer rim ENCLOSES the hole, while the Cauchy denominator
    counts only where material projects. For F9 the rim encloses 40×40 = 1600
    mm² while the part projects 1600 − π·6² ≈ 1487 mm², giving ~107.6%.

    H7 is a *floor*, so a value above 1 never causes a rejection — but it must
    be reported honestly rather than silently clamped.
    """
    result = _analyse("F9_box_with_through_hole.stp")
    assert result.selected.score.coverage > 1.0
    assert result.selected.score.coverage_is_exact is False


# ---------------------------------------------------------------------------
# H0 — the on-surface invariant
# ---------------------------------------------------------------------------

@requires_occ
@requires_fixtures
@pytest.mark.parametrize("filename", [
    "F1_cube.stp", "F8_box_with_boss.stp", "F13_peanut_two_lobed.stp",
])
def test_h0_passes_and_the_curve_is_on_the_brep(filename):
    """
    Every point of Γ must be provably on the B-Rep, measured against the OCC
    curve — not the display mesh and not the camera projection.

    Points come from ``BRepAdaptor_Curve.Value(t)``, so the deviation should be
    at floating-point noise, and it is (measured ≤ 1.3e-14 mm across the
    corpus). v1 cannot make this claim at all: its displayed curve is
    unconstrained Chaikin output with no backing to check against.
    """
    result = _analyse(filename)
    report = result.selected.feasibility.on_surface
    assert report.passed
    assert report.unbacked_segment_count == 0
    assert report.max_edge_deviation_mm < 1e-9
    assert report.failed_subtests == ()


@requires_occ
@requires_fixtures
def test_every_segment_carries_a_resolvable_backing():
    from backend.geometry.parting_line_v2.types import EdgeBacking, FaceBacking

    result = _analyse("F1_cube.stp")
    for segment in result.selected.segments:
        assert isinstance(segment.backing, (EdgeBacking, FaceBacking))
        assert segment.provenance == "edge", "Level 0 is edge-only"


# ---------------------------------------------------------------------------
# Determinism (plan §8.3)
# ---------------------------------------------------------------------------

@requires_occ
@requires_fixtures
@pytest.mark.parametrize("filename", [
    "F1_cube.stp",
    "F14_mirror_symmetric.stp",
])
def test_repeated_runs_are_bit_identical(filename):
    """
    Same input ⇒ same loop, every time. F14 has two exactly mirror-equivalent
    loops, so it is the case where set-iteration order or an arbitrary
    tie-break would show up.
    """
    first, second = _analyse(filename), _analyse(filename)
    assert first.selected.score.stable_id == second.selected.score.stable_id
    assert first.selected.points == second.selected.points
    assert first.selected.score.won_at_tier == second.selected.score.won_at_tier


@requires_occ
@requires_fixtures
def test_stable_id_is_independent_of_candidate_numbering():
    """
    ``stable_id`` is derived from the loop's backing edge ids, not from
    ``candidate_id`` — an enumeration artefact that shifts whenever the
    candidate set changes.
    """
    result = _analyse("F1_cube.stp")
    ids = {c.score.stable_id for c in result.candidates if c.score}
    assert len(ids) == len([c for c in result.candidates if c.score])


# ---------------------------------------------------------------------------
# §12.7 — no confidence-shaped output
# ---------------------------------------------------------------------------

@requires_occ
@requires_fixtures
def test_result_reports_evidence_not_a_confidence_score():
    result = _analyse("F1_cube.stp")
    payload = result.to_dict()
    assert "confidence" not in payload
    assert "readiness" not in payload
    assert payload["outcome"] == "feasible"
    assert payload["selected"]["score"]["won_at_tier"]
    assert payload["timings"]["total_ms"] >= 0.0


@requires_occ
@requires_fixtures
def test_rejections_are_reported_with_named_gates():
    """
    Rejected candidates stay in the scorecard with their reason — the material
    the agent explains a choice with, and the material P3a calibrates from.
    """
    result = _analyse("F1_cube.stp")
    rejected = [c for c in result.candidates if c.feasibility and not c.feasibility.passed]
    assert rejected
    for candidate in rejected:
        assert candidate.feasibility.failed_gate in {
            "H0", "H1", "H2", "H3", "H4", "H5", "H6", "H7"
        }
        assert candidate.feasibility.reason
        assert candidate.feasibility.measurements


@requires_occ
@requires_fixtures
def test_stage_timings_are_recorded_per_stage():
    result = _analyse("F1_cube.stp")
    payload = result.timings.to_dict()
    recorded = {s["stage"] for s in payload["stages"]}
    assert {"track_a", "weld", "reduce", "enumerate", "filter", "rank"} <= recorded


# ---------------------------------------------------------------------------
# Input contract
# ---------------------------------------------------------------------------

@requires_occ
@requires_fixtures
def test_engine_refuses_an_undercut_context_from_a_different_part():
    from backend.geometry.parting_line_v2 import (
        ContractViolation,
        PullDirectionInput,
        UndercutInput,
    )
    from backend.geometry.parting_line_v2.engine import analyse_parting_line
    from backend.geometry.step_loader import load_step

    part = load_step(str(SYNTHETIC / "F1_cube.stp"))
    with pytest.raises(ContractViolation, match="not present"):
        analyse_parting_line(
            part,
            PullDirectionInput((0, 0, 1), "fixture"),
            undercuts=UndercutInput(undercut_face_ids=frozenset({999})),
        )
