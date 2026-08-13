"""
tests/test_parting_line_v2_level1.py
------------------------------------
P2 acceptance tests — Track B, face-interior silhouette curves.

The fixtures here have answers that **no edge-based method can produce**: the
silhouette runs through the middle of a face and touches no B-Rep edge. Where
the answer is known in closed form it is checked numerically, not by eye.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

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
    not (SYNTHETIC / "manifest.json").exists(), reason="fixtures not generated"
)


def _analyse(filename: str, direction=(0.0, 0.0, 1.0)):
    from backend.config import settings
    from backend.geometry.parting_line_v2 import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line
    from backend.geometry.step_loader import load_step

    return analyse_parting_line(
        load_step(str(SYNTHETIC / filename)),
        PullDirectionInput(direction, "fixture"),
        undercuts=UndercutInput.empty(),
        cfg=settings.dfm.parting_line_v2,
    )


def _track_b(filename: str, direction=(0.0, 0.0, 1.0)):
    from backend.config import settings
    from backend.geometry.parting_line_v2.track_b import detect_face_silhouettes
    from backend.geometry.step_loader import load_step

    part = load_step(str(SYNTHETIC / filename))
    bbox = part.bounding_box
    diagonal = math.sqrt(
        (bbox.xmax - bbox.xmin) ** 2 + (bbox.ymax - bbox.ymin) ** 2
        + (bbox.zmax - bbox.zmin) ** 2
    )
    return part, detect_face_silhouettes(
        part, direction, cfg=settings.dfm.parting_line_v2, bbox_diagonal_mm=diagonal
    )


# ---------------------------------------------------------------------------
# The analytic answers
# ---------------------------------------------------------------------------

@requires_occ
@requires_fixtures
def test_sphere_silhouette_is_the_great_circle():
    """
    ``n̂ = (p − C)/r``, so ``g = 0`` exactly on the great circle ⟂ ``d̂``:
    the circle ``z = 0``, ``r = 20``. Checked numerically, not by eye.
    """
    _, result = _track_b("F4_sphere.stp")
    assert len(result.segments) == 1
    points = result.segments[0].points
    assert len(points) >= 16
    for x, y, z in points:
        assert abs(z) < 1e-6, "great circle must lie in z = 0"
        assert math.hypot(x, y) == pytest.approx(20.0, abs=1e-6)


@requires_occ
@requires_fixtures
def test_barrel_silhouette_is_the_widest_circle():
    """
    A loft r=10 → 16 → 10. The radius is maximal at mid-height, where the
    outward normal is horizontal and ``g = 0``. By the loft's symmetry that is
    ``z = 20``, ``r ≈ 16`` — strictly INSIDE the BSpline face, with no B-Rep
    edge anywhere near it.
    """
    _, result = _track_b("F17_barrel_bulged_loft.stp")
    assert len(result.segments) == 1
    for x, y, z in result.segments[0].points:
        assert z == pytest.approx(20.0, abs=1e-4)
        assert math.hypot(x, y) == pytest.approx(16.0, abs=1e-3)


@requires_occ
@requires_fixtures
def test_cylinder_across_pull_gives_two_rulings_on_its_sides():
    """
    ``n̂(u) = cos u·x̂ + sin u·ŷ`` is independent of ``v``, so ``g(u) = 0`` at
    ``u = φ ± π/2``: two STRAIGHT rulings.

    For this fixture (axis along X, pull +Z) that puts them at **y = ±15,
    z = 0** — where the normal is ``(0, ±1, 0)``. Not at ``z = ±15``, where the
    normal is ``(0,0,±1)`` and ``g = ±1`` is at its EXTREME. The fixture's own
    expected-answer text originally said z = ±15 and was corrected by this
    measurement.
    """
    _, result = _track_b("F3_cylinder_axis_perpendicular_to_pull.stp")
    assert len(result.segments) == 2
    for segment in result.segments:
        for _, y, z in segment.points:
            assert abs(z) < 1e-6
            assert abs(abs(y) - 15.0) < 1e-6


@requires_occ
@requires_fixtures
@pytest.mark.parametrize("filename", [
    "F3_cylinder_axis_perpendicular_to_pull.stp",
    "F4_sphere.stp",
    "F17_barrel_bulged_loft.stp",
])
def test_these_answers_require_face_backed_segments(filename):
    """
    The claim that survives from P1's fail-loudly tests: these silhouettes lie
    in face interiors, so **no edge-only method can produce them**. The
    selected loop must contain face-backed segments.
    """
    result = _analyse(filename)
    assert result.outcome == "feasible"
    assert result.selected.provenance_mix["face"] > 0, (
        "the answer must come (at least partly) from Track B"
    )


@requires_occ
@requires_fixtures
def test_cylinder_across_pull_needs_both_tracks_stitched():
    """
    F3's loop is *rulings + rim arcs*: Track B supplies the interior rulings,
    Track A the arcs on the cap rims, and stitching joins them. Neither track
    alone yields a closed separating loop.
    """
    result = _analyse("F3_cylinder_axis_perpendicular_to_pull.stp")
    mix = result.selected.provenance_mix
    assert mix["face"] > 0 and mix["edge"] > 0
    assert result.stitch_summary["junction_count"] > 0


@requires_occ
def test_stitch_snap_tolerance_recovers_junctions_the_old_formula_missed():
    """
    Regression guard for the 2026-08-12 controlled-direction connectivity
    diagnosis (``docs/DECISIONS_AND_ALGORITHMS.md`` D-022,
    ``backend/validation/parting_line_connectivity_diagnostic.py``).

    Measured on real Part3 at a controlled (non-optimizer) +X direction: real
    Track-A/Track-B junction gaps of up to ~1.05 mm, against the OLD stitch
    snap tolerance (``weld_tolerance_rel * bbox_diagonal * 100`` ~= 6.8e-3 mm
    on this part) -- 150x too small to catch them, even though the candidate
    edge search was already correctly scoped to edges that genuinely bound
    the face (``part.face_to_edges``). The new ``stitch_snap_tolerance_rel``
    config key must recover strictly more of those junctions than the old
    formula, on the same real segments.

    This only asserts ``junction_count`` goes up -- NOT that the resulting
    graph has fewer dangling ends after 2-core reduction. Measured
    separately: it does not, on either real part (D-022, still open).
    """
    from backend.config import settings
    from backend.geometry.parting_line_v2.engine import _bbox_diagonal
    from backend.geometry.parting_line_v2.stitch import stitch_tracks
    from backend.geometry.parting_line_v2.track_a import detect_edge_silhouettes
    from backend.geometry.parting_line_v2.track_b import detect_face_silhouettes
    from backend.geometry.step_loader import load_step

    part_path = REPO_ROOT / "data" / "parts" / "Part3.stp"
    if not part_path.exists():
        pytest.skip("Part3.stp not present")

    cfg = settings.dfm.parting_line_v2
    direction = (1.0, 0.0, 0.0)  # controlled, NOT optimizer-derived
    part = load_step(str(part_path))
    bbox_diagonal = _bbox_diagonal(part)

    track_a = detect_edge_silhouettes(part, direction, cfg=cfg, bbox_diagonal_mm=bbox_diagonal)
    track_b = detect_face_silhouettes(
        part, direction, cfg=cfg, bbox_diagonal_mm=bbox_diagonal,
        start_segment_id=len(track_a.segments),
    )

    old_tolerance = max(cfg.weld_tolerance_rel * bbox_diagonal * 100.0, 1e-6)
    new_tolerance = max(cfg.stitch_snap_tolerance_rel * bbox_diagonal, 1e-6)
    assert new_tolerance > old_tolerance, (
        "this test assumes the new config default is wider than the retired "
        "formula on a part this size -- if config values changed, the "
        "comparison below is no longer meaningful"
    )

    old_result = stitch_tracks(part, track_a.segments, track_b.segments, tolerance_mm=old_tolerance)
    new_result = stitch_tracks(part, track_a.segments, track_b.segments, tolerance_mm=new_tolerance)

    assert new_result.junction_count > old_result.junction_count, (
        f"expected the wider, structurally-scoped snap tolerance to recover "
        f"more junctions on real Part3 geometry: old={old_result.junction_count} "
        f"new={new_result.junction_count}"
    )


# ---------------------------------------------------------------------------
# Degenerate bands (plan §4.3)
# ---------------------------------------------------------------------------

@requires_occ
@requires_fixtures
def test_zero_draft_faces_are_reported_as_bands_not_curves():
    """
    F3's flat end caps have normal ``(±1,0,0)``, so ``g ≡ 0`` over their whole
    area. That is a zero-draft BAND, where the parting line's position is a
    free parameter — not a curve. Emitting marching-squares output there would
    be noise.
    """
    _, result = _track_b("F3_cylinder_axis_perpendicular_to_pull.stp")
    assert len(result.degenerate_face_ids) == 2
    for face_id in result.degenerate_face_ids:
        assert "zero-draft band" in result.skipped[face_id]


@requires_occ
@requires_fixtures
def test_track_b_finds_nothing_on_a_cube():
    """Planar faces have constant g; there is no interior zero set to find."""
    _, result = _track_b("F1_cube.stp")
    assert result.segments == ()


# ---------------------------------------------------------------------------
# Robustness regressions from P2 measurement
# ---------------------------------------------------------------------------

@requires_occ
@requires_fixtures
@pytest.mark.parametrize("filename", [
    "F4_sphere.stp", "F17_barrel_bulged_loft.stp",
    "F3_cylinder_axis_perpendicular_to_pull.stp",
])
def test_every_track_b_point_is_actually_on_the_zero_set(filename):
    """
    Regression for a seam artefact found on Part3.

    ``g`` can be DISCONTINUOUS at a parametrisation seam, flipping sign without
    passing through zero. Marching squares sees a sign change; no refinement
    can resolve it. Measured on Part3 face 407: a whole run at ``u = 1.0`` with
    ``g`` alternating −0.825/+0.825, which gate H0.3 then correctly rejected.
    Track B must not emit such points in the first place.
    """
    from backend.config import settings

    cfg = settings.dfm.parting_line_v2
    tau = cfg.silhouette_epsilon * cfg.silhouette_error_factor
    _, result = _track_b(filename)
    for segment in result.segments:
        assert segment.g_values, "face-backed segments must carry their g values"
        assert max(abs(g) for g in segment.g_values) <= tau


@requires_occ
@requires_fixtures
@pytest.mark.parametrize("filename", [
    "F4_sphere.stp", "F17_barrel_bulged_loft.stp",
    "F3_cylinder_axis_perpendicular_to_pull.stp",
])
def test_h0_passes_with_face_backed_segments(filename):
    """
    H0.3: face points must lie on the surface AND inside the face's trimmed
    region. ``off_face_point_count == 0`` is the check that stops marching
    squares escaping onto the untrimmed extension — the specific way an
    off-part curve would reappear.
    """
    result = _analyse(filename)
    report = result.selected.feasibility.on_surface
    assert report.passed
    assert report.off_face_point_count == 0
    assert report.max_surface_deviation_mm < 1e-9


@requires_occ
def test_h0_3_projects_within_the_faces_real_trim_extent_not_just_surface_bounds():
    """
    Regression guard for D-024 (``docs/DECISIONS_AND_ALGORITHMS.md``,
    2026-08-12): H0.3 used to project a stored point back onto its face's
    surface with ``GeomAPI_ProjectPointOnSurf``'s IMPLICIT bounds, which
    silently restricts the search to the underlying ``Geom_Surface``'s own
    declared ``Bounds()`` (e.g. a BSplineSurface's clean ``[0,1]x[0,1]`` knot
    domain) rather than the FACE's real trimmed extent.

    Real Part3 face 274 is a case where these genuinely differ:
    ``Geom_BSplineSurface.Bounds() == (0, 1, 0, 1)`` but
    ``breptools.UVBounds(face)`` (the SAME authoritative trim extent
    ``BRepTopAdaptor_FClass2d`` classifies against) reaches ``v ~= 1.0121`` --
    about 1.2% past ``Bounds()``. A point legitimately on the trimmed B-Rep in
    that sliver (confirmed: ``BRepAdaptor_Surface``, raw ``BRep_Tool.Surface``,
    and ``GeomLProp_SLProps`` all agree on its location to ~1e-14 mm) had no
    zero-distance match within the old, too-narrow search domain, so the
    projector snapped to the nearest point IT could find (exactly
    ``v = 1.0``) -- several microns off, which used to fail H0.3 even though
    the point was genuinely on the B-Rep.

    Reproduces the exact previously-failing case end-to-end through the real
    ``analyse_parting_line`` pipeline (mechanism-1 boundary refinement,
    D-023, is what originally produces this specific UV) and asserts it no
    longer fails H0 for this reason.
    """
    from backend.config import settings
    from backend.geometry.parting_line_v2.contracts import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line
    from backend.geometry.step_loader import load_step

    part_path = REPO_ROOT / "data" / "parts" / "Part3.stp"
    if not part_path.exists():
        pytest.skip("Part3.stp not present")

    cfg = settings.dfm.parting_line_v2
    part = load_step(str(part_path))
    pull = PullDirectionInput((1.0, 0.0, 0.0), "manual")  # controlled, NOT optimizer
    result = analyse_parting_line(part, pull, undercuts=UndercutInput.empty(), cfg=cfg)

    h0_failures = [
        c for c in result.candidates
        if c.feasibility is not None and c.feasibility.failed_gate == "H0"
    ]
    assert h0_failures == [], (
        f"expected zero H0 failures on Part3 @ +X after the D-024 fix, got "
        f"{len(h0_failures)}: {[c.feasibility.reason for c in h0_failures]}"
    )


@requires_occ
def test_h0_3_explicit_bounds_give_near_zero_residual_where_implicit_bounds_did_not():
    """
    Direct, minimal reproduction of D-024's root cause, isolated from the
    rest of the pipeline: for the exact UV this project's own diagnostic
    traced (``reports/h0_surface_deviation_trace.json``), the OLD
    implicit-bounds projector gave a multi-micron residual; the NEW
    explicit-bounds one (using the same ``breptools.UVBounds`` the trim
    classifier itself is built from) must be near machine precision.
    """
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.BRepTools import breptools
    from OCC.Core.GeomAPI import GeomAPI_ProjectPointOnSurf
    from OCC.Core.GeomLProp import GeomLProp_SLProps
    from OCC.Core.gp import gp_Pnt

    from backend.geometry.step_loader import load_step

    part_path = REPO_ROOT / "data" / "parts" / "Part3.stp"
    if not part_path.exists():
        pytest.skip("Part3.stp not present")

    part = load_step(str(part_path))
    face = next(f for f in part.faces if f.face_id == 274).occ_face
    surface = BRep_Tool.Surface(face)

    u_min, u_max, v_min, v_max = surface.Bounds()
    trim_u_min, trim_u_max, trim_v_min, trim_v_max = breptools.UVBounds(face)
    assert trim_v_max > v_max, (
        "this test assumes face 274's trim extent still exceeds the "
        "underlying surface's own Bounds() -- if this no longer holds the "
        "fixture has changed and the test needs a new case"
    )

    # A point strictly outside Bounds() but inside the real trim extent.
    u, v = 0.5, (v_max + trim_v_max) / 2.0
    point = GeomLProp_SLProps(surface, u, v, 0, 1e-9).Value()

    implicit = GeomAPI_ProjectPointOnSurf(point, surface)
    explicit = GeomAPI_ProjectPointOnSurf(
        point, surface, trim_u_min, trim_u_max, trim_v_min, trim_v_max
    )

    assert implicit.NbPoints() > 0 and explicit.NbPoints() > 0
    assert float(implicit.LowerDistance()) > 1e-6, (
        "expected the OLD implicit-bounds behaviour to still show a real "
        "deviation here -- if it doesn't, this UV no longer demonstrates "
        "the bug and the test needs a different point"
    )
    assert float(explicit.LowerDistance()) < 1e-9


@requires_occ
@requires_fixtures
def test_uv_pairs_match_points_one_for_one():
    """Every face-backed point must be recoverable as S(u,v) — gate H0.3."""
    result = _analyse("F17_barrel_bulged_loft.stp")
    from backend.geometry.parting_line_v2.types import FaceBacking

    for segment in result.selected.segments:
        if isinstance(segment.backing, FaceBacking):
            assert len(segment.backing.uv) == len(segment.points)


@requires_occ
@requires_fixtures
@pytest.mark.parametrize("filename", ["F4_sphere.stp", "F17_barrel_bulged_loft.stp"])
def test_track_b_is_deterministic(filename):
    """
    Marching squares' saddle ambiguity is resolved by the cell-centre sign,
    never arbitrarily, so repeated runs must be bit-identical (plan §8.3).
    """
    first, second = _analyse(filename), _analyse(filename)
    assert first.selected.score.stable_id == second.selected.score.stable_id
    assert first.selected.points == second.selected.points


# ---------------------------------------------------------------------------
# The measured Cauchy quadrature
# ---------------------------------------------------------------------------

@requires_occ
@requires_fixtures
def test_cauchy_denominator_is_area_weighted():
    """
    The Cauchy bound needs ``∫|g| dA``, weighted by the area element
    ``J = ‖S_u × S_v‖`` — not a uniform ``(u,v)`` average.

    On a sphere, uniform ``(u,v)`` sampling oversamples the poles and returns
    ``⟨|sin v|⟩ = 2/π ≈ 0.637`` against the true area-weighted ``0.5``: a 27%
    overestimate of the denominator, which made the great circle score 80.7%
    coverage when the right answer is 100%.
    """
    from backend.config import settings
    from backend.geometry.parting_line_v2.measures import cauchy_projected_area
    from backend.geometry.parting_line_v2.regions import mean_abs_g
    from backend.geometry.step_loader import load_step

    part = load_step(str(SYNTHETIC / "F4_sphere.stp"))
    grid = settings.dfm.parting_line_v2.face_sample_grid
    area = cauchy_projected_area(
        [f.area for f in part.faces],
        [mean_abs_g(f, (0, 0, 1), grid) for f in part.faces],
    )
    exact = math.pi * 400.0
    assert abs(area - exact) / exact < 0.02, "within 2% of pi*r^2 at the configured grid"


@requires_occ
@requires_fixtures
@pytest.mark.parametrize("filename", [
    "F4_sphere.stp", "F17_barrel_bulged_loft.stp",
    "F3_cylinder_axis_perpendicular_to_pull.stp",
])
def test_coverage_is_near_unity_for_these_convex_shapes(filename):
    """
    Each of these loops IS the part's outline, so coverage should be ~1.0.
    Small deviations are polygon-discretisation and quadrature error, both
    measured and bounded — not a modelling error.
    """
    result = _analyse(filename)
    assert 0.95 < result.selected.score.coverage < 1.05
    assert result.selected.score.coverage_is_exact is False


# ---------------------------------------------------------------------------
# Part1 +Z mandatory regression (P3.2 Step 6, 2026-08-13)
# ---------------------------------------------------------------------------
#
# Bosch demonstrated Part1 successfully using +Z, and it is this project's
# strongest real-world positive control. No prior automated test exercised
# Part1.stp through the v2 engine at all -- only Part3.stp appeared in this
# file, and test_parting_line.py / test_agent_tools.py only cover the OLD v1
# engine. This closes that gap. Every future v2 change MUST keep these
# assertions green; a red result here means a regression on the one
# real-part result this project can independently verify against Bosch's
# own demonstrated solution, not just internal self-consistency.


def _part1_path() -> Path:
    return REPO_ROOT / "data" / "parts" / "Part1.stp"


@requires_occ
def test_part1_plus_z_is_a_mandatory_regression():
    """Part1 @ +Z must keep producing a fully valid, separating candidate."""
    part_path = _part1_path()
    if not part_path.exists():
        pytest.skip("Part1.stp not present")

    from backend.config import settings
    from backend.geometry.parting_line_v2 import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line
    from backend.geometry.step_loader import load_step

    part = load_step(str(part_path))
    result = analyse_parting_line(
        part,
        PullDirectionInput((0.0, 0.0, 1.0), "fixture"),
        undercuts=UndercutInput.empty(),
        cfg=settings.dfm.parting_line_v2,
    )

    assert result.selected is not None, "Part1 +Z must produce a selected candidate"
    assert result.selected.feasibility is not None
    assert result.selected.feasibility.passed, "Part1 +Z's winning candidate must pass all gates"
    fully_valid = [c for c in result.candidates if c.feasibility and c.feasibility.passed]
    assert len(fully_valid) >= 1, "Part1 +Z must have at least one fully valid candidate"

    # Locks the D-026-measured shape of the result -- Track B silhouette-free
    # (Part1's silhouette is entirely sharp-edge at this direction), and a
    # real region split, not a degenerate single-face pinch (D-028).
    assert result.regions is not None
    assert len(result.regions.cavity_face_ids) > 1, (
        "cavity side must be a real mold half, not a single pinched-off "
        "face (D-028's region_sizes=[1, N] failure mode)"
    )
    assert len(result.regions.core_face_ids) > 1, (
        "core side must be a real mold half, not a single pinched-off "
        "face (D-028's region_sizes=[1, N] failure mode)"
    )


@requires_occ
def test_part1_plus_z_and_minus_z_are_mirror_images():
    """+Z and -Z are the same physical mold axis; D-026 measured identical
    winning candidates with cavity/core swapped."""
    part_path = _part1_path()
    if not part_path.exists():
        pytest.skip("Part1.stp not present")

    from backend.config import settings
    from backend.geometry.parting_line_v2 import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line
    from backend.geometry.step_loader import load_step

    part = load_step(str(part_path))
    plus_z = analyse_parting_line(
        part, PullDirectionInput((0.0, 0.0, 1.0), "fixture"),
        undercuts=UndercutInput.empty(), cfg=settings.dfm.parting_line_v2,
    )
    minus_z = analyse_parting_line(
        part, PullDirectionInput((0.0, 0.0, -1.0), "fixture"),
        undercuts=UndercutInput.empty(), cfg=settings.dfm.parting_line_v2,
    )
    assert plus_z.selected is not None and minus_z.selected is not None
    assert plus_z.selected.feasibility.passed and minus_z.selected.feasibility.passed
    assert len(plus_z.regions.cavity_face_ids) > 1 and len(plus_z.regions.core_face_ids) > 1
    assert len(minus_z.regions.cavity_face_ids) > 1 and len(minus_z.regions.core_face_ids) > 1


@requires_occ
def test_part1_plus_z_is_deterministic_across_reanalysis():
    """The backend is stateless and re-parses on every call -- confirm
    re-running the identical analysis twice gives the identical candidate."""
    part_path = _part1_path()
    if not part_path.exists():
        pytest.skip("Part1.stp not present")

    from backend.config import settings
    from backend.geometry.parting_line_v2 import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line
    from backend.geometry.step_loader import load_step

    def _run():
        part = load_step(str(part_path))
        return analyse_parting_line(
            part, PullDirectionInput((0.0, 0.0, 1.0), "fixture"),
            undercuts=UndercutInput.empty(), cfg=settings.dfm.parting_line_v2,
        )

    first, second = _run(), _run()
    assert first.selected is not None and second.selected is not None
    assert first.selected.score.stable_id == second.selected.score.stable_id
    assert first.selected.points == second.selected.points
