"""
tests/test_parting_line_v2_region_balance.py
----------------------------------------------
Acceptance tests for the Phase 3A core/cavity engineering-quality layer:

  1. Region-balance/meaningfulness metrics on RegionClassification.
  2. Region data preserved for the best-ranked rejected H3-passing candidate.
  3. Corrected tooling-split-face area attribution (D-043), using real axial
     split geometry instead of the old mean_g-based 50/50 fallback.

Frozen invariant under test throughout: this phase adds OBSERVABILITY, not a
new feasibility gate. None of these tests may assert that a candidate's
feasibility, H3/H4/H5 outcome, or ranking changed because these metrics now
exist -- a small region does not prove infeasibility, and exposing the
metric must never silently convert a rejected candidate into a feasible one.

Note on numbers: the Phase 3 read-only investigation reported candidate
110's core area as ~2022.82 mm2 (39.8% of confident area). That figure was
itself computed via the naive mean_g-based 50/50 fallback this phase's item
3 explicitly requires fixing -- it was the artifact, not a target to
preserve. Post-fix, candidate 110's core area is ~1436.77 mm2 (28.2%),
verified directly below. Face membership, H3, H4, and the real PL are all
byte-identical to before; only the REPORTED area split for face 35 changed,
exactly as intended.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PART3_PATH = REPO_ROOT / "data" / "parts" / "Part3.stp"
PART1_PATH = REPO_ROOT / "data" / "parts" / "Part1.stp"

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _occ_available() -> bool:
    try:
        import OCC  # noqa: F401
        return True
    except ImportError:
        return False


requires_occ = pytest.mark.skipif(not _occ_available(), reason="pythonOCC not installed")
requires_part3 = pytest.mark.skipif(not PART3_PATH.exists(), reason="Part3.stp not present")
requires_part1 = pytest.mark.skipif(not PART1_PATH.exists(), reason="Part1.stp not present")

PULL_Z = (0.0, 0.0, 1.0)
PULL_X = (1.0, 0.0, 0.0)
PULL_Y = (0.0, 1.0, 0.0)
BORE_FACE_ID = 35
STACK1 = frozenset(range(0, 17))
STACK2 = frozenset(range(18, 35))


def _part3():
    from backend.geometry.step_loader import load_step
    return load_step(str(PART3_PATH))


def _part1():
    from backend.geometry.step_loader import load_step
    return load_step(str(PART1_PATH))


def _make_delegation(face_ids, direction, note):
    from backend.geometry.parting_line_v2.contracts import DelegatedSecondaryAction, DelegationEvidence
    return DelegatedSecondaryAction(
        face_ids=frozenset(face_ids), movement_direction=direction, movement_type="radial_slide",
        evidence=DelegationEvidence(source="manual_engineering", note=note),
    )


def _candidate_110_result(part):
    from backend.config import settings
    from backend.geometry.parting_line_v2 import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.contracts import CorePinFaceRef
    from backend.geometry.parting_line_v2.engine import analyse_parting_line

    refs = (CorePinFaceRef(BORE_FACE_ID, PULL_Z, "straight coaxial through-bore"),)
    valid = (
        _make_delegation(STACK1, (1.0, 0.0, 0.0), "original rib stack, radial outward +X"),
        _make_delegation(STACK2, (-1.0, 0.0, 0.0), "mirror rib stack, radial outward -X"),
    )
    return analyse_parting_line(
        part, PullDirectionInput(PULL_Z, "fixture"), cfg=settings.dfm.parting_line_v2,
        undercuts=UndercutInput.empty(), core_pin_face_refs=refs, delegations=valid,
    )


# ---------------------------------------------------------------------------
# 1. Region-balance metrics: present, internally consistent, correct
# ---------------------------------------------------------------------------

@requires_occ
@requires_part3
def test_1_region_balance_metrics_present_on_candidate_110():
    result = _candidate_110_result(_part3())
    assert result.selected is not None
    assert result.selected.candidate_id == 110
    regions = result.regions
    assert regions is not None

    # Topology unchanged from the frozen Phase 3 investigation.
    assert len(regions.cavity_face_ids) == 410
    assert len(regions.core_face_ids) == 5
    assert regions.core_face_ids == frozenset({35, 36, 37, 320, 321})
    assert BORE_FACE_ID in regions.cavity_face_ids
    assert BORE_FACE_ID in regions.core_face_ids  # still a member of BOTH

    # Balance metrics are internally consistent with each other.
    assert regions.confident_area_mm2 == pytest.approx(
        regions.cavity_area_mm2 + regions.core_area_mm2
    )
    assert regions.cavity_area_fraction_of_confident + regions.core_area_fraction_of_confident == \
        pytest.approx(1.0)
    assert regions.smaller_region_area_fraction == pytest.approx(
        min(regions.cavity_area_fraction_of_confident, regions.core_area_fraction_of_confident)
    )
    # ambiguous_area_fraction is untouched by this phase (Phase 3 finding,
    # re-verified): ~32.7%.
    assert regions.ambiguous_area_fraction == pytest.approx(0.3271748971395147, rel=1e-6)


@requires_occ
@requires_part3
def test_2_region_balance_does_not_gate_feasibility():
    """Observability only -- feasibility/H4/ranking outcome for candidate
    110 must be byte-identical to the value already frozen before Phase 3A."""
    result = _candidate_110_result(_part3())
    c = result.selected
    assert c.feasibility.passed is True
    assert c.feasibility.failed_gate is None
    assert c.feasibility.measurements["h4_orientation_violation_fraction"] == pytest.approx(
        0.004994890916885516, rel=1e-9
    )
    assert result.outcome == "feasible"


# ---------------------------------------------------------------------------
# 2. Region data preserved for rejected candidates (plumbing fix)
# ---------------------------------------------------------------------------

@requires_occ
@requires_part3
def test_3_part3_plus_x_exposes_regions_for_rejected_candidate_24():
    from backend.config import settings
    from backend.geometry.parting_line_v2 import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line

    part = _part3()
    result = analyse_parting_line(
        part, PullDirectionInput(PULL_X, "fixture"), cfg=settings.dfm.parting_line_v2,
        undercuts=UndercutInput.empty(),
    )
    # Feasibility semantics unchanged: still no feasible candidate for +X.
    assert result.outcome == "no_feasible_candidate"
    assert result.selected is None

    candidate_24 = next(c for c in result.candidates if c.candidate_id == 24)
    assert candidate_24.feasibility.failed_gate == "H4"
    assert candidate_24.feasibility.measurements["h3_region_count"] == 2.0
    assert candidate_24.regions is not None
    assert candidate_24.regions.smaller_region_area_fraction == pytest.approx(0.0089, abs=0.001)
    # The metric existing must NEVER silently make a rejected candidate feasible.
    assert candidate_24.feasibility.passed is False


@requires_occ
@requires_part3
def test_4_part3_plus_y_exposes_regions_for_rejected_candidate_3():
    from backend.config import settings
    from backend.geometry.parting_line_v2 import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line

    part = _part3()
    result = analyse_parting_line(
        part, PullDirectionInput(PULL_Y, "fixture"), cfg=settings.dfm.parting_line_v2,
        undercuts=UndercutInput.empty(),
    )
    assert result.outcome == "no_feasible_candidate"
    assert result.selected is None

    candidate_3 = next(c for c in result.candidates if c.candidate_id == 3)
    assert candidate_3.feasibility.failed_gate == "H4"
    assert candidate_3.feasibility.measurements["h3_region_count"] == 2.0
    assert candidate_3.regions is not None
    assert candidate_3.regions.smaller_region_area_fraction == pytest.approx(0.0603, abs=0.001)
    assert candidate_3.feasibility.passed is False


@requires_occ
@requires_part1
def test_5_part1_plus_z_region_balance_exposed_and_unchanged():
    from backend.config import settings
    from backend.geometry.parting_line_v2 import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line

    part = _part1()
    result = analyse_parting_line(
        part, PullDirectionInput(PULL_Z, "fixture"), cfg=settings.dfm.parting_line_v2,
        undercuts=UndercutInput.empty(),
    )
    assert result.selected is not None
    assert result.selected.candidate_id == 49
    assert result.outcome == "feasible"
    regions = result.regions
    assert regions is not None
    assert regions.cavity_area_fraction_of_confident == pytest.approx(0.2314, abs=0.001)
    assert regions.core_area_fraction_of_confident == pytest.approx(0.7686, abs=0.001)
    assert regions.ambiguous_area_fraction == pytest.approx(0.4557, abs=0.001)
    # No core-pin authorization on Part1 -- no "split" label anywhere.
    assert not any(f.label == "split" for f in regions.faces)


# ---------------------------------------------------------------------------
# 3. Tooling-split face area attribution uses real axial geometry (D-043)
# ---------------------------------------------------------------------------

@requires_occ
@requires_part3
def test_6_face_35_split_attribution_not_naive_50_50():
    result = _candidate_110_result(_part3())
    regions = result.regions
    face35 = next(f for f in regions.faces if f.face_id == 35)
    assert face35.label == "split"
    total = face35.cavity_area_mm2 + face35.core_area_mm2
    assert total == pytest.approx(1432.566, abs=0.5)
    # The whole point of the fix: no longer an exact 50/50 fallback.
    assert face35.cavity_area_mm2 != pytest.approx(face35.core_area_mm2, rel=0.01)
    assert face35.cavity_area_mm2 == pytest.approx(1302.33, abs=1.0)
    assert face35.core_area_mm2 == pytest.approx(130.23, abs=1.0)


@requires_occ
@requires_part3
def test_7_tooling_split_fix_does_not_change_topology_h3_h4_or_real_pl():
    """Critical invariant: only the REPORTED area split changed. Face
    membership, H3, H4, core-pin metadata, and the real Γ are exactly as
    before Phase 3A."""
    from backend.geometry.parting_line_v2.types import EdgeBacking, FaceBacking

    result = _candidate_110_result(_part3())
    c = result.selected
    assert c.candidate_id == 110
    assert c.discovered_by == "cycle_basis"
    assert len(c.segments) == 2
    assert all(isinstance(s.backing, EdgeBacking) for s in c.segments)
    assert not any(isinstance(s.backing, FaceBacking) for s in c.segments)
    assert dict(c.tooling_split_face_ids) == {35: 4.0}
    assert len(c.core_pin_interfaces) == 1
    assert c.core_pin_interfaces[0].face_id == 35
    assert c.core_pin_interfaces[0].split_param == pytest.approx(4.0)
    assert c.feasibility.measurements["h3_region_count"] == 2.0
    assert c.feasibility.measurements["h4_orientation_violation_fraction"] == pytest.approx(
        0.004994890916885516, rel=1e-9
    )


@requires_occ
@requires_part1
def test_8_no_tooling_split_no_regression_on_part1():
    """No core_pin_face_refs supplied -- classify_regions's new optional
    tooling_split_face_ids parameter must be fully inert here, matching
    every pre-existing call site."""
    from backend.config import settings
    from backend.geometry.parting_line_v2 import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line

    part = _part1()
    result = analyse_parting_line(
        part, PullDirectionInput(PULL_Z, "fixture"), cfg=settings.dfm.parting_line_v2,
        undercuts=UndercutInput.empty(),
    )
    assert result.selected is not None
    assert result.selected.candidate_id == 49
    assert result.selected.feasibility.passed is True


@requires_occ
@requires_part3
def test_9_to_dict_serializes_regions_with_new_balance_fields():
    result = _candidate_110_result(_part3())
    d = result.selected.to_dict()
    assert d["regions"] is not None
    for key in (
        "confident_area_mm2", "cavity_area_fraction_of_confident",
        "core_area_fraction_of_confident", "smaller_region_area_fraction",
    ):
        assert key in d["regions"]
    assert d["regions"]["core_area_mm2"] == pytest.approx(1436.77, abs=1.0)
    # No "meaningful"/"degenerate" classification label -- deliberately not
    # added (see RegionClassification docstring): raw metrics only.
    assert "classification" not in d["regions"]
    assert "meaningfulness" not in d["regions"]
