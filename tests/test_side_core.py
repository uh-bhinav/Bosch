"""
tests/test_side_core.py
------------------------
Tests for backend/geometry/side_core.py — Stage 4 (Bosch criterion #5)
side-core / lifter solid generation, first increment per
docs/ARCHITECTURE_ROADMAP.md §4.4.

See side_core.py's module docstring for the two real sizing/tolerance bugs
found and fixed while prototyping this against real Part1/Part3 geometry
(footprint sizing via face Bnd_Box corners, not centroids or vertices; a
single, reused fuzzy tolerance across the Common and the following Cut).
The end-to-end tests below are the regression guard for both.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.geometry import core_cavity, side_core

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


def test_occ_side_core_apis_import_successfully():
    """
    Mirrors test_core_cavity.py's Interface_Static regression guard: if real
    pythonocc-core is installed, `_OCC_SIDE_CORE_AVAILABLE` must be True. A
    silent import bug here would report the generic "not available in this
    environment" for every request instead of the real error.
    """
    try:
        import OCC.Core  # noqa: F401
    except ImportError:
        pytest.skip("pythonocc-core is not installed in this environment.")

    assert side_core._OCC_SIDE_CORE_AVAILABLE is True, (
        "pythonOCC is installed but side_core's Boolean imports still report "
        "unavailable — check the logged import exception."
    )


# ---------------------------------------------------------------------------
# select_primary_side_core_feature — pure selection logic, no OCC required
# ---------------------------------------------------------------------------


class _FakeFeature:
    def __init__(self, feature_id, severity, interference_volume_mm3):
        self.feature_id = feature_id
        self.severity = severity
        self.interference_volume_mm3 = interference_volume_mm3


class _FakeUndercutResult:
    def __init__(self, features):
        self.features = features


def test_select_primary_feature_returns_none_when_no_features():
    assert side_core.select_primary_side_core_feature(_FakeUndercutResult([])) is None


def test_select_primary_feature_prefers_critical_severity():
    features = [
        _FakeFeature(0, "moderate", 9999.0),
        _FakeFeature(1, "critical", 10.0),
    ]
    chosen = side_core.select_primary_side_core_feature(_FakeUndercutResult(features))
    assert chosen.feature_id == 1, "A critical feature must win even with lower interference volume."


def test_select_primary_feature_falls_back_to_any_severity():
    features = [
        _FakeFeature(0, "minor", 5.0),
        _FakeFeature(1, "moderate", 50.0),
    ]
    chosen = side_core.select_primary_side_core_feature(_FakeUndercutResult(features))
    assert chosen.feature_id == 1, "With no critical feature, the highest-interference one wins."


def test_select_primary_feature_picks_max_interference_among_criticals():
    features = [
        _FakeFeature(0, "critical", 100.0),
        _FakeFeature(1, "critical", 500.0),
        _FakeFeature(2, "critical", 200.0),
    ]
    chosen = side_core.select_primary_side_core_feature(_FakeUndercutResult(features))
    assert chosen.feature_id == 1


# ---------------------------------------------------------------------------
# generate_side_core — guard clauses (no real OCC solids needed for these)
# ---------------------------------------------------------------------------


def test_generate_side_core_blocked_without_split_ok():
    if not side_core._OCC_SIDE_CORE_AVAILABLE:
        pytest.skip("Requires real pythonOCC to reach past the availability check.")
    bad_split = core_cavity.CoreCavitySolidResult(solid_split_status="failed")
    feature = _FakeFeature(0, "critical", 100.0)
    result = side_core.generate_side_core(part=None, feature=feature, split_result=bad_split)
    assert result.status == "blocked_by_core_cavity_split"
    assert "solid split status is 'failed'" in result.failure_reason


def test_generate_side_core_blocked_when_solids_are_none():
    if not side_core._OCC_SIDE_CORE_AVAILABLE:
        pytest.skip("Requires real pythonOCC to reach past the availability check.")
    split_ok_but_no_solids = core_cavity.CoreCavitySolidResult(
        solid_split_status="split_ok", split_solid_count=2,
    )
    feature = _FakeFeature(0, "critical", 100.0)
    result = side_core.generate_side_core(
        part=None, feature=feature, split_result=split_ok_but_no_solids,
    )
    assert result.status == "blocked_by_core_cavity_split"
    assert "None" in result.failure_reason


def test_generate_primary_side_core_reports_no_feature():
    split_ok = core_cavity.CoreCavitySolidResult(
        solid_split_status="split_ok",
        cavity_solid=object(),
        core_solid=object(),
    )
    result = side_core.generate_primary_side_core(
        part=None, undercut_result=_FakeUndercutResult([]), split_result=split_ok,
    )
    assert result.status == "no_feature"


def test_side_core_result_to_dict_is_json_safe():
    result = side_core.SideCoreResult(
        status="generated",
        feature_id=0,
        containing_half="core",
        side_core_volume_mm3=1234.5678,
        reduced_half_volume_mm3=9876.5432,
        conservation_error=0.0001234,
        side_core_solid=object(),
        reduced_half_solid=object(),
    )
    payload = result.to_dict()
    assert "side_core_solid" not in payload, "Raw OCC shapes must never appear in to_dict()."
    assert "reduced_half_solid" not in payload, "Raw OCC shapes must never appear in to_dict()."
    assert payload["status"] == "generated"
    assert payload["containing_half"] == "core"


# ---------------------------------------------------------------------------
# End-to-end integration: real Part1.stp/Part3.stp through the full pipeline
# (undercuts -> parting line -> Boolean split -> side core -> AP214 export
# with the reduced half + side core -> reload). This is the test that proves
# the roadmap's Stage 4 §4.4 gate: "the three solids (cavity, core, side
# core) reload from STEP, and their volumes are consistent with the blank
# minus the part."
#
# Both real parts' OPTIMAL pull direction eliminates undercuts by design (the
# direction optimizer specifically searches for undercut-free directions),
# so there is nothing for a side core to demonstrate there. Matching the
# roadmap's own §4.2 worked example (which uses Part1's default +Z after
# finding the optimal direction empty), these tests use a fixed non-optimal
# pull direction that is known to produce a real critical undercut feature:
# Part1 @ (0, 0, 1), Part3 @ (0, 0, -1) — measured during Stage 4 prototyping
# (2026-07-28).
# ---------------------------------------------------------------------------


def _generate_and_export_side_core(part_path: Path, pull_direction, tmp_path: Path) -> dict:
    from backend.geometry.step_loader import load_step
    from backend.geometry.undercut_detector import detect_undercuts
    from backend.geometry.parting_line import detect_parting_line_candidates

    part = load_step(part_path)
    undercuts = detect_undercuts(
        part, pull_direction, mutate=False, boolean_refine=True, max_boolean_faces=20,
    )
    assert undercuts.features, (
        f"Expected at least one undercut feature at pull_direction={pull_direction} "
        "for this test to demonstrate anything — if this fails, the fixed "
        "test direction no longer produces undercuts on this fixture."
    )

    pl_result = detect_parting_line_candidates(
        part, pull_direction, undercut_context=undercuts, mutate=False,
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

    side_result = side_core.generate_primary_side_core(part, undercuts, split_result)
    assert side_result.status == "generated", side_result.failure_reason
    assert side_result.side_core_volume_mm3 > 0.0
    assert side_result.conservation_error <= settings_side_core_tolerance()

    original_total = (
        split_result.cavity_solid_volume_mm3 + split_result.core_solid_volume_mm3
    )
    if side_result.containing_half == "cavity":
        new_total = (
            side_result.reduced_half_volume_mm3
            + split_result.core_solid_volume_mm3
            + side_result.side_core_volume_mm3
        )
    else:
        new_total = (
            side_result.reduced_half_volume_mm3
            + split_result.cavity_solid_volume_mm3
            + side_result.side_core_volume_mm3
        )
    total_error = abs(new_total - original_total) / original_total
    assert total_error <= settings_side_core_tolerance(), (
        f"Reduced half + untouched half + side core ({new_total:.3f}) must "
        f"match the original cavity+core total ({original_total:.3f}) within "
        f"tolerance; got {total_error * 100:.4f}% error."
    )

    overrides = {side_result.containing_half: side_result.reduced_half_solid}
    extra = [(side_result.side_core_solid, f"side_core_{side_result.feature_id}")]
    export = core_cavity.export_mold_halves(
        split_result,
        output_dir=str(tmp_path),
        solid_overrides=overrides,
        extra_solids=extra,
    )
    assert export["status"] == "exported", export.get("failure_reason")
    assert export["solid_count"] == 3

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
    assert solid_count == 3, (
        "Exported STEP file must reload with exactly 3 solids "
        "(cavity, core, side core) per roadmap Stage 4 §4.4's gate."
    )
    return export


def settings_side_core_tolerance() -> float:
    from backend.config import settings
    return settings.dfm.side_core.volume_conservation_tolerance


@skip_no_occ
@skip_no_part1
def test_real_side_core_generation_and_export_round_trips_on_part1(tmp_path):
    _generate_and_export_side_core(PART1_PATH, (0.0, 0.0, 1.0), tmp_path)


@skip_no_occ
@skip_no_part3
def test_real_side_core_generation_and_export_round_trips_on_part3(tmp_path):
    _generate_and_export_side_core(PART3_PATH, (0.0, 0.0, -1.0), tmp_path)


# ---------------------------------------------------------------------------
# S4.3 (2026-07-29): multi-feature generalization. Part1 @ (0,0,1) has 1
# critical + 7 minor undercut features at default detect_undercuts()
# settings -- a real multi-feature case, not a synthetic one.
#
# The gate here is deliberately NOT "exactly N solids reload" the way
# Stage 4's single-feature gate was -- diagnosed 2026-07-29 that a combined
# multi-feature side-core body can legitimately be a multi-piece compound
# (Part1's case: 6 disconnected pieces -- 5 inherited from feature 0's own
# complex 11-face Boolean result, 1 fused blob from features 1-7, which
# mutually overlap in pairs and so fuse into a single connected region).
# That is real geometry, not a defect. The gate that DOES matter and IS
# asserted: cavity and the reduced half each stay exactly 1 solid (Boolean
# Cut does not fragment the MAIN mold halves), and total volume conserves
# against the original tooling volume within tolerance -- unlike exporting
# each feature's raw side_core_solid as a SEPARATE body, which measured a
# real ~0.38% inflation from double-counted overlap between adjacent
# features (see side_core.py's module docstring and
# combine_side_cores_per_half's docstring).
# ---------------------------------------------------------------------------


@skip_no_occ
@skip_no_part1
def test_real_multi_feature_side_core_combines_and_exports_on_part1(tmp_path):
    from backend.geometry.step_loader import load_step
    from backend.geometry.undercut_detector import detect_undercuts
    from backend.geometry.parting_line import detect_parting_line_candidates
    from OCC.Core.STEPControl import STEPControl_Reader
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_SOLID

    pull_direction = (0.0, 0.0, 1.0)
    part = load_step(PART1_PATH)
    undercuts = detect_undercuts(part, pull_direction, mutate=False, boolean_refine=True)
    assert len(undercuts.features) >= 2, (
        "Expected multiple undercut features at this pull direction for a "
        "multi-feature test to demonstrate anything."
    )

    pl_result = detect_parting_line_candidates(
        part, pull_direction, undercut_context=undercuts, mutate=False,
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

    multi = side_core.generate_side_cores_for_features(
        part, undercuts, split_result, severities=("critical", "minor"),
    )
    assert len(multi.generated_results) >= 2, (
        "Expected at least 2 successfully-generated side cores for this to "
        "exercise the combine path."
    )

    combined = side_core.combine_side_cores_per_half(split_result, multi)
    assert combined, "Expected at least one half to have a combined result."

    tolerance = settings_side_core_tolerance()
    solid_overrides: dict = {}
    extra_solids: list = []
    for half, result in combined.items():
        assert result.status == "generated", result.failure_reason
        assert result.conservation_error <= tolerance, (
            f"{half} half combined conservation error {result.conservation_error * 100:.4f}% "
            f"exceeds tolerance {tolerance * 100:.1f}%."
        )
        solid_overrides[half] = result.reduced_half_solid
        extra_solids.append((result.side_core_solid, f"side_core_combined_{half}"))

    original_total = split_result.cavity_solid_volume_mm3 + split_result.core_solid_volume_mm3

    export = core_cavity.export_mold_halves(
        split_result,
        output_dir=str(tmp_path),
        solid_overrides=solid_overrides,
        extra_solids=extra_solids,
    )
    assert export["status"] == "exported", export.get("failure_reason")

    reader = STEPControl_Reader()
    reader.ReadFile(export["output_path"])
    reader.TransferRoots()
    reloaded = reader.OneShape()
    solid_count = 0
    total_volume = 0.0
    explorer = TopExp_Explorer(reloaded, TopAbs_SOLID)
    while explorer.More():
        solid_count += 1
        total_volume += core_cavity._solid_volume(explorer.Current())
        explorer.Next()

    assert solid_count >= 2 + len(extra_solids), (
        "Reloaded STEP file must have at least one solid per main half plus "
        "one per combined side-core body (a combined body MAY legitimately "
        "be a multi-piece compound -- see module docstring -- so this is a "
        "floor, not an exact count)."
    )

    total_error = abs(total_volume - original_total) / original_total
    assert total_error <= tolerance, (
        f"Reloaded total volume ({total_volume:.3f}) must match the original "
        f"cavity+core total ({original_total:.3f}) within tolerance; got "
        f"{total_error * 100:.4f}% error."
    )

    # The main halves themselves (as opposed to the combined side-core
    # bodies) must never fragment -- a Boolean Cut against a well-formed
    # tool should keep the remaining half as one connected solid.
    def _count_solids(shape) -> int:
        n = 0
        exp = TopExp_Explorer(shape, TopAbs_SOLID)
        while exp.More():
            n += 1
            exp.Next()
        return n

    assert _count_solids(split_result.cavity_solid) == 1
    for half, result in combined.items():
        assert _count_solids(result.reduced_half_solid) == 1, (
            f"Reduced {half} half fragmented into multiple solids; expected 1."
        )
