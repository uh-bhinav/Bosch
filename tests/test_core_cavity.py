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
# C5 (2026-08-17): _partition_meaningful_solids -- pure classification
# boundary tests. Uses the EXISTING min_solid_volume_fraction (0.01, from
# config.yaml), not a new/hardcoded threshold. `_solid_volume` is
# monkeypatched to a lookup dict keyed by plain sentinel objects, so these
# tests validate the real production partition logic without needing real
# OCC geometry.
# ---------------------------------------------------------------------------

_TOOLING_VOLUME_FOR_PARTITION_TESTS = 1000.0
_MIN_FRACTION_FOR_PARTITION_TESTS = 0.01  # matches config.yaml's default, reused not reinvented


def _empty_occ_shape():
    """A real (empty/null) TopoDS_Shape -- satisfies _shape_list's real
    TopTools_ListOfShape.Append() call, which rejects a plain object()
    sentinel outright. Content is irrelevant for these tests: the mocked
    BRepAlgoAPI_Common classes below never actually inspect the shapes."""
    from OCC.Core.TopoDS import TopoDS_Shape
    return TopoDS_Shape()


def _make_fake_solids(monkeypatch, *volumes):
    volume_by_id = {}
    solids = []
    for v in volumes:
        s = object()
        volume_by_id[id(s)] = v
        solids.append(s)
    monkeypatch.setattr(core_cavity, "_solid_volume", lambda s: volume_by_id[id(s)])
    return solids


def test_partition_2_meaningful_exactly_2_total(monkeypatch):
    a, b = _make_fake_solids(monkeypatch, 500.0, 400.0)
    meaningful, negligible = core_cavity._partition_meaningful_solids(
        [a, b], _TOOLING_VOLUME_FOR_PARTITION_TESTS, _MIN_FRACTION_FOR_PARTITION_TESTS,
    )
    assert meaningful == [a, b]
    assert negligible == []


def test_partition_2_meaningful_plus_1_negligible_is_a_candidate(monkeypatch):
    a, b, c = _make_fake_solids(monkeypatch, 500.0, 400.0, 5.0)
    meaningful, negligible = core_cavity._partition_meaningful_solids(
        [a, b, c], _TOOLING_VOLUME_FOR_PARTITION_TESTS, _MIN_FRACTION_FOR_PARTITION_TESTS,
    )
    assert set(meaningful) == {a, b}
    assert negligible == [c]


def test_partition_3_meaningful_is_rejected(monkeypatch):
    a, b, c = _make_fake_solids(monkeypatch, 400.0, 350.0, 250.0)
    meaningful, negligible = core_cavity._partition_meaningful_solids(
        [a, b, c], _TOOLING_VOLUME_FOR_PARTITION_TESTS, _MIN_FRACTION_FOR_PARTITION_TESTS,
    )
    assert len(meaningful) == 3
    assert negligible == []


def test_partition_1_meaningful_plus_2_negligible_is_rejected(monkeypatch):
    a, b, c = _make_fake_solids(monkeypatch, 900.0, 5.0, 3.0)
    meaningful, negligible = core_cavity._partition_meaningful_solids(
        [a, b, c], _TOOLING_VOLUME_FOR_PARTITION_TESTS, _MIN_FRACTION_FOR_PARTITION_TESTS,
    )
    assert meaningful == [a]
    assert len(negligible) == 2


def test_partition_all_negligible_is_rejected(monkeypatch):
    a, b, c = _make_fake_solids(monkeypatch, 3.0, 2.0, 1.0)
    meaningful, negligible = core_cavity._partition_meaningful_solids(
        [a, b, c], _TOOLING_VOLUME_FOR_PARTITION_TESTS, _MIN_FRACTION_FOR_PARTITION_TESTS,
    )
    assert meaningful == []
    assert len(negligible) == 3


def test_partition_exactly_at_1_percent_boundary_is_meaningful(monkeypatch):
    exact = _TOOLING_VOLUME_FOR_PARTITION_TESTS * _MIN_FRACTION_FOR_PARTITION_TESTS
    (a,) = _make_fake_solids(monkeypatch, exact)
    meaningful, negligible = core_cavity._partition_meaningful_solids(
        [a], _TOOLING_VOLUME_FOR_PARTITION_TESTS, _MIN_FRACTION_FOR_PARTITION_TESTS,
    )
    assert meaningful == [a]
    assert negligible == []


def test_partition_just_below_1_percent_boundary_is_negligible(monkeypatch):
    just_below = _TOOLING_VOLUME_FOR_PARTITION_TESTS * _MIN_FRACTION_FOR_PARTITION_TESTS - 1e-6
    (a,) = _make_fake_solids(monkeypatch, just_below)
    meaningful, negligible = core_cavity._partition_meaningful_solids(
        [a], _TOOLING_VOLUME_FOR_PARTITION_TESTS, _MIN_FRACTION_FOR_PARTITION_TESTS,
    )
    assert meaningful == []
    assert negligible == [a]


def test_check_meaningful_solids_disjoint_fails_closed_on_common_exception(monkeypatch):
    """E: mock BRepAlgoAPI_Common raising -- must fail closed, never treat
    as '0 intersection'."""
    if not core_cavity._OCC_SPLIT_AVAILABLE:
        pytest.skip("Requires real pythonOCC import surface for BRepAlgoAPI_Common.")

    class ExplodingCommon:
        def SetArguments(self, *a, **k):
            pass

        def SetTools(self, *a, **k):
            pass

        def Build(self):
            raise RuntimeError("simulated OCC crash")

    monkeypatch.setattr(core_cavity, "BRepAlgoAPI_Common", ExplodingCommon)
    ok, reason = core_cavity._check_meaningful_solids_disjoint(
        _empty_occ_shape(), _empty_occ_shape(), 1e-6,
    )
    assert ok is False
    assert reason is not None and "raised" in reason


def test_check_meaningful_solids_disjoint_fails_closed_on_has_errors(monkeypatch):
    """E (variant): Common completes but reports HasErrors() -- must still
    fail closed, not be silently treated as safe."""
    if not core_cavity._OCC_SPLIT_AVAILABLE:
        pytest.skip("Requires real pythonOCC import surface for BRepAlgoAPI_Common.")

    class FailedCommon:
        def SetArguments(self, *a, **k):
            pass

        def SetTools(self, *a, **k):
            pass

        def Build(self):
            pass

        def IsDone(self):
            return False

        def HasErrors(self):
            return True

    monkeypatch.setattr(core_cavity, "BRepAlgoAPI_Common", FailedCommon)
    ok, reason = core_cavity._check_meaningful_solids_disjoint(
        _empty_occ_shape(), _empty_occ_shape(), 1e-6,
    )
    assert ok is False
    assert reason is not None


def test_check_meaningful_solids_disjoint_fails_closed_on_volume_extraction_error(monkeypatch):
    """C7 F: Common completes successfully, but the resulting shape's
    volume cannot be measured -- must still fail closed."""
    if not core_cavity._OCC_SPLIT_AVAILABLE:
        pytest.skip("Requires real pythonOCC import surface for BRepAlgoAPI_Common.")

    class OkCommon:
        def SetArguments(self, *a, **k):
            pass

        def SetTools(self, *a, **k):
            pass

        def Build(self):
            pass

        def IsDone(self):
            return True

        def HasErrors(self):
            return False

        def Shape(self):
            raise RuntimeError("simulated shape-extraction failure")

    monkeypatch.setattr(core_cavity, "BRepAlgoAPI_Common", OkCommon)
    ok, reason = core_cavity._check_meaningful_solids_disjoint(
        _empty_occ_shape(), _empty_occ_shape(), 1e-6,
    )
    assert ok is False
    assert reason is not None and "could not be measured" in reason


def test_check_meaningful_solids_disjoint_c7_threshold_boundary(monkeypatch):
    """
    C7 D + E: the tolerance is now an explicit ``volume_tolerance`` value
    the caller supplies -- these test the comparison boundary directly,
    mocking Common's measured volume at the helper boundary (never
    fabricating OCC geometry), exactly matching C5's existing failure-test
    pattern.

    D: an intersection BELOW the old 1%-of-tooling threshold (which C5
       would have accepted) but ABOVE the new Boolean-volume tolerance ->
       must now be REJECTED.
    E: an intersection below the new Boolean-volume tolerance -> accepted.
    """
    if not core_cavity._OCC_SPLIT_AVAILABLE:
        pytest.skip("Requires real pythonOCC import surface for BRepAlgoAPI_Common.")

    class FakeShape:
        pass

    def make_common(measured_volume):
        class FakeCommon:
            def SetArguments(self, *a, **k):
                pass

            def SetTools(self, *a, **k):
                pass

            def Build(self):
                pass

            def IsDone(self):
                return True

            def HasErrors(self):
                return False

            def Shape(self):
                return FakeShape()

        return FakeCommon

    # C6's own dangerous-case numbers: old 1%-of-100,000 threshold = 1000;
    # 900 sits below that but is a real, non-negligible physical overlap.
    old_threshold_case_volume = 900.0
    # A tight, C7-style tolerance (order of magnitude of the
    # boolean_volume_tolerance_factor/boolean_min_volume_tolerance_mm3
    # pattern for a modestly-sized part) -- far below 900.
    new_tight_tolerance = 1e-3

    monkeypatch.setattr(core_cavity, "brepgprop_VolumeProperties", lambda shape, props: None)
    monkeypatch.setattr(
        core_cavity, "GProp_GProps",
        lambda: type("P", (), {"Mass": lambda self: old_threshold_case_volume})(),
    )
    monkeypatch.setattr(core_cavity, "BRepAlgoAPI_Common", make_common(old_threshold_case_volume))

    # D: 900 mm³ measured intersection, tight tolerance 1e-3 -> rejected.
    ok, reason = core_cavity._check_meaningful_solids_disjoint(
        _empty_occ_shape(), _empty_occ_shape(), new_tight_tolerance,
    )
    assert ok is False
    assert reason is not None and "noise-floor tolerance" in reason

    # E: a tiny measured intersection, well below the tight tolerance -> accepted.
    tiny_volume = 1e-7
    monkeypatch.setattr(
        core_cavity, "GProp_GProps",
        lambda: type("P", (), {"Mass": lambda self: tiny_volume})(),
    )
    monkeypatch.setattr(core_cavity, "BRepAlgoAPI_Common", make_common(tiny_volume))
    ok2, reason2 = core_cavity._check_meaningful_solids_disjoint(
        _empty_occ_shape(), _empty_occ_shape(), new_tight_tolerance,
    )
    assert ok2 is True
    assert reason2 is None


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


def test_export_reports_download_filename_only_for_the_default_export_dir(tmp_path, monkeypatch):
    """
    F6: `download_filename` (added for `GET /export/download/{filename}`)
    must appear ONLY when the file actually landed in the directory that
    endpoint serves from (`settings.dfm.core_cavity.export_dir`) -- a
    caller-supplied `output_dir` (as every pre-existing test in this file
    uses via `tmp_path`) produces a file the download endpoint cannot see,
    so offering a `download_filename` for one would be misleading.
    """
    if not core_cavity._OCC_SPLIT_AVAILABLE:
        pytest.skip("Requires real pythonOCC to construct a split_ok result.")

    # Two simple box primitives -- real TopoDS_Shape instances the STEP
    # writer can actually Transfer, without needing a full STEP-load +
    # Boolean-split pipeline just to test filename/path plumbing.
    from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox

    fake_result = core_cavity.CoreCavitySolidResult(
        solid_split_status="split_ok", split_solid_count=2,
        cavity_solid=BRepPrimAPI_MakeBox(10, 10, 10).Shape(),
        core_solid=BRepPrimAPI_MakeBox(5, 5, 5).Shape(),
    )

    # Custom output_dir (tmp_path) -- matches every other test in this file.
    custom_export = core_cavity.export_mold_halves(fake_result, output_dir=str(tmp_path), filename_prefix="custom")
    assert custom_export["status"] == "exported", custom_export.get("failure_reason")
    assert "download_filename" not in custom_export

    # Default export dir (settings.dfm.core_cavity.export_dir), redirected
    # to a temp directory. Settings dataclasses are frozen, so the module's
    # own `settings` name (not an attribute on the frozen object) is what
    # gets replaced -- the same pattern other tests use when a function
    # under test has no explicit `cfg=` override parameter to pass instead.
    import dataclasses

    from backend.config import settings as real_settings

    patched_core_cavity_settings = dataclasses.replace(real_settings.dfm.core_cavity, export_dir=str(tmp_path / "default_dir"))
    patched_dfm = dataclasses.replace(real_settings.dfm, core_cavity=patched_core_cavity_settings)
    patched_settings = dataclasses.replace(real_settings, dfm=patched_dfm)
    monkeypatch.setattr(core_cavity, "settings", patched_settings)

    default_export = core_cavity.export_mold_halves(fake_result, filename_prefix="default")
    assert default_export["status"] == "exported", default_export.get("failure_reason")
    assert default_export["download_filename"] == "default.stp"
    assert (tmp_path / "default_dir" / "default.stp").exists()


# ---------------------------------------------------------------------------
# C1 (2026-08-17): core/cavity connected to the authoritative parting_line_v2
# pipeline, replacing the legacy parting_line.py dependency. Targeted,
# single-direction tests only -- no full optimizer search for Part3 (its
# feasibility/authorization contract is already frozen and tested in
# tests/test_direction_optimizer_parting_line_feasibility.py; reused here,
# not re-derived).
# ---------------------------------------------------------------------------

PULL_Z = (0.0, 0.0, 1.0)
# The real, already-established O22-O25 winner for Part1 (score 742.31,
# verified_acceptable) -- used directly rather than re-running the full
# (expensive) optimizer search in this test file.
PART1_KNOWN_WINNER = (0.0, 0.0, -1.0)

BORE_FACE_ID = 35
STACK1 = frozenset(range(0, 17))
STACK2 = frozenset(range(18, 35))


def _candidate_110_authorization():
    """
    Reused verbatim from tests/test_direction_optimizer_parting_line_
    feasibility.py's `_candidate_110_authorization()` -- the frozen,
    already-verified Part3 candidate-110 authorization. Not invented here.
    """
    from backend.geometry.parting_line_v2.contracts import (
        CorePinFaceRef, DelegatedSecondaryAction, DelegationEvidence,
    )

    refs = (CorePinFaceRef(BORE_FACE_ID, PULL_Z, "straight coaxial through-bore"),)
    delegations = (
        DelegatedSecondaryAction(
            face_ids=STACK1, movement_direction=(1.0, 0.0, 0.0), movement_type="radial_slide",
            evidence=DelegationEvidence(source="manual_engineering", note="original rib stack, radial outward +X"),
        ),
        DelegatedSecondaryAction(
            face_ids=STACK2, movement_direction=(-1.0, 0.0, 0.0), movement_type="radial_slide",
            evidence=DelegationEvidence(source="manual_engineering", note="mirror rib stack, radial outward -X"),
        ),
    )
    return refs, delegations


def _resolve_v2(part, pull_direction, core_pin_face_refs=(), delegations=()):
    from backend.geometry.parting_line_v2 import PullDirectionInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line
    from backend.config import settings

    return analyse_parting_line(
        part, PullDirectionInput(pull_direction, "fixture"),
        cfg=settings.dfm.parting_line_v2,
        core_pin_face_refs=core_pin_face_refs, delegations=delegations,
    )


# A + D. Part1 known winner: v2-backed classification + split, zero
# unexplained inconsistent_face_ids (Phase 4B/D-050 baseline).
@skip_no_occ
@skip_no_part1
def test_a_part1_known_winner_reaches_core_cavity_via_v2():
    from backend.geometry.step_loader import load_step

    part = load_step(str(PART1_PATH))
    pl_result = _resolve_v2(part, PART1_KNOWN_WINNER)

    assert pl_result.selected is not None, "Part1's known winner must be v2-feasible."
    assert pl_result.regions is not None

    cc_result = core_cavity.classify_core_cavity(
        part, pull_direction=PART1_KNOWN_WINNER, mutate=False,
        region_classification=pl_result.regions,
    )
    assert cc_result.classification_source == "parting_line_v2"
    assert cc_result.cavity_face_ids
    assert cc_result.core_face_ids
    # D: straddling regression -- Part1 has zero known inconsistent faces
    # at this direction (Phase 4B/D-050 baseline). A nonzero count here
    # would be a real regression to investigate, not silently accepted.
    assert cc_result.inconsistent_face_ids == [], (
        f"Unexpected inconsistent faces on Part1: {cc_result.inconsistent_face_ids}"
    )

    # C1 originally discovered a gap here (investigated in C2/C3, not fixed
    # there by design: "do not redesign the planar approximation"): v2's
    # real, unsmoothed loop (45 points) makes BRepAlgoAPI_Splitter yield 3
    # solids instead of 2 at Part1's known winner, because the true, exact
    # parting height happens to coincide with a real flat face (C2/C3
    # evidence). C4 proved (not assumed) that the 3rd solid is a genuine,
    # tiny sliver (~105.44 mm^3, ~0.31% of tooling volume -- well under the
    # existing 1% min_solid_volume_fraction invariant), while the other two
    # solids independently pass every check available: volume conservation,
    # opposite-sidedness, zero pairwise BRepAlgoAPI_Common intersection, and
    # BRepCheck_Analyzer validity. C5 implements exactly that filter --
    # verify the NOW-CORRECT behavior here, not an assumed one.
    split_result = core_cavity.split_core_cavity_solids(
        part, pl_result.selected, PART1_KNOWN_WINNER,
        loop_points=list(pl_result.selected.points),
    )
    assert split_result.solid_split_status == "split_ok", split_result.failure_reason
    assert split_result.split_solid_count == 2
    assert split_result.split_tool_kind == "planar_approximation"
    assert split_result.discarded_sliver_count == 1
    # Not hardcoded to the exact historical 105.441 mm^3 figure -- pinned to
    # a wide, generous band so this test isn't brittle to tiny OCC-version
    # numerical drift, while still proving a real (not near-zero, not huge)
    # sliver was found and discarded.
    assert 50.0 < split_result.discarded_sliver_volume_mm3 < 500.0
    assert split_result.cavity_solid is not None
    assert split_result.core_solid is not None
    # split_ok already implies _validate_split_volumes passed (cavity+core
    # conserve the tooling volume within the existing 6% tolerance) -- this
    # additionally confirms the discarded sliver itself is a plausible,
    # bounded remainder rather than a wildly-wrong number.
    assert split_result.cavity_solid_volume_mm3 > split_result.core_solid_volume_mm3 > 0


# B. Part3 without authorization: v2 stays infeasible, split never runs.
@skip_no_occ
@skip_no_part3
def test_b_part3_unauthorized_stays_blocked_and_split_never_executes():
    from backend.geometry.step_loader import load_step

    part = load_step(str(PART3_PATH))
    pl_result = _resolve_v2(part, PULL_Z)  # no authorization

    assert pl_result.selected is None
    assert pl_result.outcome != "feasible"
    assert pl_result.regions is None

    # Ownership rule: core/cavity must not invent feasibility. With no
    # selected candidate, the caller passes parting_sheet=None -- the split
    # must block, never attempt a Boolean op, never fall back to legacy.
    split_result = core_cavity.split_core_cavity_solids(
        part, None, PULL_Z, loop_points=None,
    )
    assert split_result.solid_split_status == "blocked_by_parting_line"
    assert split_result.cavity_solid is None
    assert split_result.core_solid is None


# C + E (Part3 half). Part3 WITH candidate-110 authorization: split
# succeeds, exactly 2 solids, frozen candidate-110 region facts hold, and
# the exported STEP round-trips with 2 solids.
@skip_no_occ
@skip_no_part3
def test_c_part3_candidate_110_authorization_reaches_core_cavity_via_v2(tmp_path):
    from backend.geometry.step_loader import load_step

    part = load_step(str(PART3_PATH))
    refs, delegations = _candidate_110_authorization()
    pl_result = _resolve_v2(part, PULL_Z, refs, delegations)

    assert pl_result.selected is not None
    assert pl_result.outcome == "feasible"
    assert pl_result.selected.candidate_id == 110
    assert pl_result.regions is not None
    # Frozen candidate-110 region facts (tests/test_parting_line_v2_region_
    # balance.py / test_direction_optimizer_parting_line_feasibility.py) --
    # must remain consistent through this new call path.
    assert len(pl_result.regions.cavity_face_ids) == 410
    assert pl_result.regions.core_face_ids == frozenset({35, 36, 37, 320, 321})

    cc_result = core_cavity.classify_core_cavity(
        part, pull_direction=PULL_Z, mutate=False,
        region_classification=pl_result.regions,
    )
    assert cc_result.classification_source == "parting_line_v2"

    split_result = core_cavity.split_core_cavity_solids(
        part, pl_result.selected, PULL_Z, loop_points=list(pl_result.selected.points),
    )
    assert split_result.solid_split_status == "split_ok", split_result.failure_reason
    assert split_result.split_solid_count == 2
    # C5 D: ordinary 2-solid result -- no sliver filtering occurred, and
    # the new BRepAlgoAPI_Common disjointness check is skipped entirely
    # (discarded_sliver_count == 0) for this case, exactly as required.
    assert split_result.discarded_sliver_count == 0
    assert split_result.discarded_sliver_volume_mm3 == 0.0
    # Volumes match the C4 investigation's measured baseline (108,684.12 /
    # 271,423.40 mm^3) within a generous tolerance -- proves C5 did not
    # perturb the ordinary Part3 split at all.
    assert split_result.core_solid_volume_mm3 == pytest.approx(108684.12, rel=1e-3)
    assert split_result.cavity_solid_volume_mm3 == pytest.approx(271423.40, rel=1e-3)

    # E: STEP round-trip.
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
    assert solid_count == 2


# C7 G: ordinary 2-solid Splitter results (Part3's real, un-slivered case)
# must never invoke BRepAlgoAPI_Common at all -- proven here by making
# Common raise if called, using REAL Part3 geometry (not fabricated),
# reusing the exact same authorized path as test_c above. If the gate
# (`if discarded_sliver_count > 0`) were ever removed or broken, this
# split would now fail loudly instead of silently doing extra work.
@skip_no_occ
@skip_no_part3
def test_g_part3_ordinary_2_solid_split_never_invokes_common(monkeypatch):
    from backend.geometry.step_loader import load_step

    part = load_step(str(PART3_PATH))
    refs, delegations = _candidate_110_authorization()
    pl_result = _resolve_v2(part, PULL_Z, refs, delegations)
    assert pl_result.selected is not None

    def exploding_common(*args, **kwargs):
        raise AssertionError(
            "BRepAlgoAPI_Common must not be invoked for an ordinary "
            "2-solid split (discarded_sliver_count == 0)."
        )

    monkeypatch.setattr(core_cavity, "BRepAlgoAPI_Common", exploding_common)

    split_result = core_cavity.split_core_cavity_solids(
        part, pl_result.selected, PULL_Z, loop_points=list(pl_result.selected.points),
    )
    assert split_result.solid_split_status == "split_ok", split_result.failure_reason
    assert split_result.discarded_sliver_count == 0


# E (Part1 half), C5 (2026-08-17): Part1's v2-real loop now reaches
# split_ok via the sliver filter (see test_a's updated comment) -- this
# proves the fix all the way through STEP export and reload, not just the
# in-memory result. (test_c below covers the same round-trip on Part3,
# where v2 wiring already succeeded before C5 with no sliver involved.)
@skip_no_occ
@skip_no_part1
def test_e_part1_v2_split_now_succeeds_and_exports_via_sliver_filter(tmp_path):
    from backend.geometry.step_loader import load_step

    part = load_step(str(PART1_PATH))
    pl_result = _resolve_v2(part, PART1_KNOWN_WINNER)
    assert pl_result.selected is not None

    split_result = core_cavity.split_core_cavity_solids(
        part, pl_result.selected, PART1_KNOWN_WINNER,
        loop_points=list(pl_result.selected.points),
    )
    assert split_result.solid_split_status == "split_ok", split_result.failure_reason
    assert split_result.discarded_sliver_count == 1

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
    assert solid_count == 2, "Exported STEP file must reload with exactly 2 solids -- the sliver must never be exported."


# F. Backward compatibility: classify_core_cavity() without
# region_classification is byte-identical to pre-C1 behavior.
def test_f_classify_core_cavity_without_region_classification_is_unchanged():
    from unittest.mock import MagicMock

    from backend.models.geometry_models import BoundingBox, FaceData, PartGeometry

    face_cavity = FaceData(
        face_id=0, occ_face=MagicMock(), surface_type="Plane",
        normal=(0.0, 0.0, 1.0), centroid=(0.0, 0.0, 0.0), area=10.0,
        u_range=(0.0, 1.0), v_range=(0.0, 1.0), is_reversed=False, normal_valid=True,
    )
    face_core = FaceData(
        face_id=1, occ_face=MagicMock(), surface_type="Plane",
        normal=(0.0, 0.0, -1.0), centroid=(0.0, 0.0, 0.0), area=10.0,
        u_range=(0.0, 1.0), v_range=(0.0, 1.0), is_reversed=False, normal_valid=True,
    )
    face_parting = FaceData(
        face_id=2, occ_face=MagicMock(), surface_type="Plane",
        normal=(1.0, 0.0, 0.0), centroid=(0.0, 0.0, 0.0), area=10.0,
        u_range=(0.0, 1.0), v_range=(0.0, 1.0), is_reversed=False, normal_valid=True,
    )
    part = PartGeometry(
        source_file="mock.stp", occ_shape=MagicMock(),
        faces=[face_cavity, face_core, face_parting],
        bounding_box=BoundingBox(0.0, 0.0, 0.0, 10.0, 10.0, 10.0),
        face_count=3, solid_count=1, shell_count=1,
    )

    result = core_cavity.classify_core_cavity(
        part, pull_direction=(0.0, 0.0, 1.0), mutate=True,
    )
    assert result.classification_source == "single_normal"
    assert result.inconsistent_face_ids == []
    assert result.cavity_face_ids == [0]
    assert result.core_face_ids == [1]
    assert result.parting_face_ids == [2]
    assert face_cavity.cavity_or_core == "cavity"
    assert face_core.cavity_or_core == "core"
    assert face_parting.cavity_or_core == "parting"
