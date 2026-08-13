"""
tests/test_core_cavity.py
--------------------------
Tests for backend/geometry/core_cavity.py — Level 1 face classification and
Level 2 Boolean solid split / AP214 export.

This file did not exist before 2026-07-28. Milestones 1.10/1.11 were marked
complete in an earlier session on "tests pass" with zero dedicated tests for
either the solid split or the STEP export — exactly the process gap described
in docs/ENGINE_AUDIT_2026-07-27.md. Two real bugs were hiding behind that
gap for the entire time the feature was "implemented":

1. `from OCC.Core.Interface_Static import Interface_Static` — that module
   path does not exist (the real one is `OCC.Core.Interface`). A bare
   `except (ImportError, Exception): _OCC_SPLIT_AVAILABLE = False` swallowed
   this with no logging, so every call silently reported the
   environment-sounding "pythonOCC Boolean APIs not available in this
   environment" instead of the real `ModuleNotFoundError`.
2. `BRepAlgoAPI_Cut().SetArguments([blank])` — this pythonOCC binding's
   `SetArguments`/`SetTools` require a real `TopTools_ListOfShape`, not a
   plain Python list; passing a list raises `TypeError`, caught by the
   retry loop's `except Exception` and reported as a generic
   "failed after all fuzzy-tolerance retries".

Both are fixed. `test_occ_split_apis_import_successfully` below is the
regression guard for #1 — it is the single test that would have caught it
immediately. It only runs meaningfully when pythonocc-core is installed
(Docker/conda); it is a no-op assertion of the current (degraded) state
otherwise, so it never fails a non-OCC CI run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.geometry import core_cavity

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PART1_PATH = PROJECT_ROOT / "data" / "parts" / "Part1.stp"
PART3_PATH = PROJECT_ROOT / "data" / "parts" / "Part3.stp"
HAS_OCC = True
try:
    import OCC  # noqa: F401
except ImportError:
    HAS_OCC = False

skip_no_occ = pytest.mark.skipif(not HAS_OCC, reason="pythonocc-core not installed")
skip_no_part1 = pytest.mark.skipif(
    not PART1_PATH.exists(), reason=f"Part1.stp not found at {PART1_PATH}"
)
skip_no_part3 = pytest.mark.skipif(
    not PART3_PATH.exists(), reason=f"Part3.stp not found at {PART3_PATH}"
)


# ---------------------------------------------------------------------------
# Regression guard for the Interface_Static import bug (Stage 2, 2026-07-28)
# ---------------------------------------------------------------------------


def test_occ_split_apis_import_successfully():
    """
    `_OCC_SPLIT_AVAILABLE` must be True whenever real pythonOCC is installed.

    This is the exact test that would have caught the `Interface_Static`
    import bug (see module docstring) the moment it was introduced, instead
    of it hiding for as long as core/cavity solid split was "implemented".
    If pythonocc-core genuinely is not installed in this environment, this
    is not a failure — but it must be for the right reason (no `OCC` module
    at all), not because a real import inside the try/except is broken.
    """
    try:
        import OCC.Core  # noqa: F401
    except ImportError:
        pytest.skip("pythonocc-core is not installed in this environment.")

    assert core_cavity._OCC_SPLIT_AVAILABLE is True, (
        "pythonOCC is installed but core_cavity's Boolean-split imports "
        "failed. Check for an import error in the try/except block at the "
        "top of backend/geometry/core_cavity.py — it used to silently "
        "hide a ModuleNotFoundError for OCC.Core.Interface_Static."
    )


# ---------------------------------------------------------------------------
# _validate_split_volumes — pure-function unit tests (no OCC required)
# ---------------------------------------------------------------------------


def test_validate_split_volumes_accepts_a_clean_split():
    result = core_cavity._validate_split_volumes(
        cavity_volume=17000.0,
        core_volume=17500.0,
        tooling_volume=34500.0,
        min_volume_fraction=0.01,
        conservation_tolerance=0.02,
    )
    assert result is None


def test_validate_split_volumes_rejects_a_degenerate_sliver():
    """
    Reproduces the exact measured failure on Part1 before this check
    existed: one solid keeps almost the entire tooling volume, the other is
    a near-zero/negative-volume artifact of a parting sheet that doesn't
    fully bisect the tooling.
    """
    result = core_cavity._validate_split_volumes(
        cavity_volume=34509.89,
        core_volume=-0.164,
        tooling_volume=34509.89,
        min_volume_fraction=0.01,
        conservation_tolerance=0.02,
    )
    assert result is not None
    assert "degenerate" in result


def test_validate_split_volumes_rejects_a_small_sliver_even_if_positive():
    """A tiny but positive sliver (e.g. 0.1% of tooling volume) must still fail."""
    result = core_cavity._validate_split_volumes(
        cavity_volume=34475.0,
        core_volume=34.5,  # 0.1% of tooling volume, below the 1% floor
        tooling_volume=34509.5,
        min_volume_fraction=0.01,
        conservation_tolerance=0.02,
    )
    assert result is not None
    assert "degenerate" in result


def test_validate_split_volumes_rejects_non_conserving_volumes():
    """Two individually-plausible volumes that don't sum to the tooling volume."""
    result = core_cavity._validate_split_volumes(
        cavity_volume=15000.0,
        core_volume=15000.0,
        tooling_volume=34500.0,  # cavity+core is ~13% short of tooling
        min_volume_fraction=0.01,
        conservation_tolerance=0.02,
    )
    assert result is not None
    assert "conserve" in result


def test_validate_split_volumes_conservation_tolerance_is_respected():
    """A split within the configured tolerance must pass, not just an exact match."""
    result = core_cavity._validate_split_volumes(
        cavity_volume=17000.0,
        core_volume=17200.0,  # sums to 34200, ~0.87% short of 34500
        tooling_volume=34500.0,
        min_volume_fraction=0.01,
        conservation_tolerance=0.02,
    )
    assert result is None


# ---------------------------------------------------------------------------
# split_core_cavity_solids — structural paths (no OCC required)
# ---------------------------------------------------------------------------


def test_split_blocked_without_a_parting_sheet():
    result = core_cavity.split_core_cavity_solids(
        part=None,  # never touched — the parting_sheet=None check short-circuits first
        parting_sheet=None,
    )
    assert result.solid_split_status == "blocked_by_parting_line"
    assert result.cavity_solid is None
    assert result.core_solid is None


def test_split_blocked_without_loop_points():
    """
    Stage 2b: the Boolean splitter tool is built from loop_points (a flat
    plane through their centroid), not from parting_sheet directly. A caller
    that has a parting sheet but no loop points cannot build that tool.
    """
    if not core_cavity._OCC_SPLIT_AVAILABLE:
        pytest.skip("Requires real pythonOCC to reach past the availability check.")
    result = core_cavity.split_core_cavity_solids(
        part=None,
        parting_sheet=object(),  # non-None, just needs to pass the first gate
        loop_points=None,
    )
    assert result.solid_split_status == "blocked_by_parting_line"
    assert "loop points" in result.failure_reason.lower()


# ---------------------------------------------------------------------------
# build_planar_split_tool — pure geometry, real OCC required
# ---------------------------------------------------------------------------


@skip_no_occ
def test_build_planar_split_tool_produces_a_valid_face():
    from OCC.Core.BRepCheck import BRepCheck_Analyzer
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core.GProp import GProp_GProps

    shape = core_cavity.build_planar_split_tool(
        centroid=(0.0, 0.0, 0.0),
        pull_direction=(0.0, 0.0, 1.0),
        half_size_mm=100.0,
    )
    assert BRepCheck_Analyzer(shape).IsValid() is True

    props = GProp_GProps()
    brepgprop.SurfaceProperties(shape, props)
    # A 100mm half-size square spans 200x200mm.
    assert props.Mass() == pytest.approx(200.0 * 200.0, rel=1e-6)


@skip_no_occ
def test_build_planar_split_tool_normal_is_perpendicular_to_pull_direction():
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.GeomLProp import GeomLProp_SLProps

    pull_direction = (0.2313, 0.3569, 0.9048)  # a real measured Part1 direction
    shape = core_cavity.build_planar_split_tool(
        centroid=(1.0, 2.0, 3.0), pull_direction=pull_direction, half_size_mm=50.0
    )
    surface = BRep_Tool.Surface(shape)
    slprops = GeomLProp_SLProps(surface, 0.0, 0.0, 1, 1e-9)
    normal = slprops.Normal()
    mag = sum(v * v for v in pull_direction) ** 0.5
    unit_pull = tuple(v / mag for v in pull_direction)
    dot = abs(
        normal.X() * unit_pull[0]
        + normal.Y() * unit_pull[1]
        + normal.Z() * unit_pull[2]
    )
    assert dot == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# End-to-end integration: real Part1.stp/Part3.stp through the full
# pipeline (direction -> parting line -> Boolean split -> AP214 export ->
# reload). This is the test that actually proves Milestones 1.10 and 1.11
# work, not just that their guard/failure paths are structurally correct —
# no such test existed before Stage 2b, since no real split had ever
# succeeded (see the module docstring's Interface_Static/SetArguments bugs,
# and CHANGELOG.md 2026-07-28 "Stage 2b" for why the real BRepFill_Filling
# parting surface still can't be used as the Boolean tool).
# ---------------------------------------------------------------------------


def _split_and_export_real_part(part_path: Path, tmp_path: Path) -> dict:
    from backend.geometry.step_loader import load_step
    from backend.geometry.direction_optimizer import optimize_mold_direction
    from backend.geometry.parting_line import detect_parting_line_candidates

    part = load_step(part_path)
    direction_result = optimize_mold_direction(part)
    pull_direction = direction_result.best_direction
    pl_result = detect_parting_line_candidates(
        part, pull_direction, undercut_context=direction_result.optimal_undercuts,
        mutate=False,
    )
    parting_sheet = (
        pl_result.parting_surface.occ_shape
        if pl_result.parting_surface.status.startswith("generated")
        else None
    )
    split_result = core_cavity.split_core_cavity_solids(
        part, parting_sheet, pull_direction, loop_points=pl_result.wire_points,
    )
    assert split_result.solid_split_status == "split_ok", split_result.failure_reason
    assert split_result.split_solid_count == 2
    assert split_result.split_tool_kind == "planar_approximation"

    export = core_cavity.export_mold_halves(split_result, output_dir=str(tmp_path))
    assert export["status"] == "exported", export.get("failure_reason")
    assert export["solid_count"] == 2

    from OCC.Core.STEPControl import STEPControl_Reader
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_SOLID

    reader = STEPControl_Reader()
    reader.ReadFile(export["output_path"])
    reader.TransferRoots()
    reloaded = reader.OneShape()
    solid_count = 0
    explorer = TopExp_Explorer(reloaded, TopAbs_SOLID)
    while explorer.More():
        solid_count += 1
        explorer.Next()
    assert solid_count == 2, "Exported STEP file must reload with exactly 2 solids (TODO.md S2.4)."
    return export


@skip_no_occ
@skip_no_part1
def test_real_split_and_export_round_trips_on_part1(tmp_path):
    _split_and_export_real_part(PART1_PATH, tmp_path)


@skip_no_occ
@skip_no_part3
def test_real_split_and_export_round_trips_on_part3(tmp_path):
    _split_and_export_real_part(PART3_PATH, tmp_path)


# ---------------------------------------------------------------------------
# export_mold_halves — structural paths + the data/parts/ safety guard
# ---------------------------------------------------------------------------


def test_export_refuses_a_non_split_ok_result():
    if not core_cavity._OCC_SPLIT_AVAILABLE:
        pytest.skip("Requires real pythonOCC to reach past the availability check.")
    bad_result = core_cavity.CoreCavitySolidResult(solid_split_status="failed")
    export = core_cavity.export_mold_halves(bad_result)
    assert export["status"] == "failed"
    assert "solid split status is 'failed'" in export["failure_reason"]


def test_export_refuses_to_write_into_data_parts(tmp_path, monkeypatch):
    """
    CLAUDE.md invariant #2: never modify files in data/parts/. This is the
    only test covering that guard — it had zero coverage before 2026-07-28
    despite being a safety-critical, explicitly-documented invariant.
    """
    if not core_cavity._OCC_SPLIT_AVAILABLE:
        pytest.skip("Requires real pythonOCC to construct a split_ok result.")

    # Point the guard's "data/parts" reference at a real, empty directory so
    # the test doesn't depend on the actual repo layout or cwd.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "parts").mkdir(parents=True)

    fake_result = core_cavity.CoreCavitySolidResult(
        solid_split_status="split_ok",
        split_solid_count=2,
        cavity_solid=object(),
        core_solid=object(),
    )
    export = core_cavity.export_mold_halves(
        fake_result, output_dir=str(tmp_path / "data" / "parts" / "sneaky")
    )
    assert export["status"] == "failed"
    assert "forbidden" in export["failure_reason"]
