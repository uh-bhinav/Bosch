"""
tests/test_parting_line_v2_best_rejected.py
--------------------------------------------
Phase 4 (D-049) acceptance tests: exposing the best-ranked REJECTED
H3-passing candidate's already-computed RegionClassification through new,
explicitly named diagnostic fields on PartingLineV2Result.

Frozen invariant under test throughout: this is a pure information-exposure
addition. `regions` continues to mean ONLY "the accepted candidate's
core/cavity classification" -- never overloaded with rejected-candidate data.
No change to separate_surface(), classify_regions(), H0-H7, ranking, the
pull-direction optimizer, undercut detection, core-pin semantics, or
delegation semantics. The frozen Phase 3A Part3-candidate-110 and Part1
regression values (tests/test_parting_line_v2_region_balance.py) must not
move.
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


def _part3_no_auth_result():
    from backend.config import settings
    from backend.geometry.parting_line_v2 import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line
    return analyse_parting_line(
        _part3(), PullDirectionInput(PULL_Z, "fixture"), cfg=settings.dfm.parting_line_v2,
        undercuts=UndercutInput.empty(),
    )


def _part3_candidate_110_result():
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
        _part3(), PullDirectionInput(PULL_Z, "fixture"), cfg=settings.dfm.parting_line_v2,
        undercuts=UndercutInput.empty(), core_pin_face_refs=refs, delegations=valid,
    )


def _part1_result():
    from backend.config import settings
    from backend.geometry.parting_line_v2 import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line
    return analyse_parting_line(
        _part1(), PullDirectionInput(PULL_Z, "fixture"), cfg=settings.dfm.parting_line_v2,
        undercuts=UndercutInput.empty(),
    )


# ---------------------------------------------------------------------------
# 1. A feasible selected candidate still exposes `.regions` exactly as before
# ---------------------------------------------------------------------------

@requires_occ
@requires_part1
def test_1_feasible_candidate_regions_unchanged():
    result = _part1_result()
    assert result.outcome == "feasible"
    assert result.selected is not None
    assert result.selected.candidate_id == 49
    regions = result.regions
    assert regions is not None
    assert regions.cavity_area_fraction_of_confident == pytest.approx(0.2314, abs=0.001)
    assert regions.core_area_fraction_of_confident == pytest.approx(0.7686, abs=0.001)
    assert regions.ambiguous_area_fraction == pytest.approx(0.4557, abs=0.001)
    assert not any(f.label == "split" for f in regions.faces)
    # New fields present but never displace the pre-existing contract.
    d = result.to_dict()
    assert d["regions"] is not None
    assert "best_rejected_candidate_id" in d
    assert "best_rejected_regions" in d
    assert "best_rejected_failed_gate" in d
    assert "best_rejected_reason" in d


# ---------------------------------------------------------------------------
# 2. A no-feasible-candidate result can expose `best_rejected_regions`
# ---------------------------------------------------------------------------

@requires_occ
@requires_part3
def test_2_no_feasible_candidate_exposes_best_rejected_regions():
    result = _part3_no_auth_result()
    assert result.outcome == "no_feasible_candidate"
    assert result.selected is None
    assert result.best_rejected_candidate_id is not None
    assert result.best_rejected_regions is not None
    br = result.best_rejected_regions
    assert br.total_area_mm2 > 0
    assert br.cavity_area_mm2 + br.core_area_mm2 + br.ambiguous_area_mm2 == pytest.approx(
        br.total_area_mm2, rel=1e-6
    )
    labels = {f.label for f in br.faces}
    assert labels <= {"cavity", "core", "split", "ambiguous"}


# ---------------------------------------------------------------------------
# 3. `best_rejected_regions` does NOT populate `.regions`
# ---------------------------------------------------------------------------

@requires_occ
@requires_part3
def test_3_best_rejected_regions_never_populates_regions_field():
    result = _part3_no_auth_result()
    assert result.regions is None
    assert result.best_rejected_regions is not None
    assert result.regions is not result.best_rejected_regions

    d = result.to_dict()
    assert d["regions"] is None
    assert d["best_rejected_regions"] is not None
    assert d["selected"] is None


# ---------------------------------------------------------------------------
# 4. The rejected candidate remains explicitly marked rejected/preview-only
# ---------------------------------------------------------------------------

@requires_occ
@requires_part3
def test_4_best_rejected_candidate_stays_marked_rejected():
    result = _part3_no_auth_result()
    best_id = result.best_rejected_candidate_id
    assert best_id is not None
    candidate = next(c for c in result.candidates if c.candidate_id == best_id)

    # It is genuinely rejected, never the selected/accepted one.
    assert candidate.feasibility is not None
    assert candidate.feasibility.passed is False
    assert result.selected is None or candidate.candidate_id != result.selected.candidate_id

    # The top-level diagnostic fields agree with the candidate's own record
    # -- no separate, potentially-diverging copy of the rejection reason.
    assert result.best_rejected_failed_gate == candidate.feasibility.failed_gate
    assert result.best_rejected_reason == candidate.feasibility.reason
    assert result.best_rejected_failed_gate is not None
    assert result.best_rejected_reason


# ---------------------------------------------------------------------------
# 5. Part3 +Z without authorization exposes the best H3-passing rejected
#    candidate's region data specifically (not just any rejected candidate)
# ---------------------------------------------------------------------------

@requires_occ
@requires_part3
def test_5_part3_no_auth_best_rejected_is_h3_passing():
    result = _part3_no_auth_result()
    best_id = result.best_rejected_candidate_id
    candidate = next(c for c in result.candidates if c.candidate_id == best_id)
    assert candidate.feasibility.measurements.get("h3_region_count") == 2.0
    # Region data was genuinely retained (Phase 3A's regions_by_candidate),
    # not fabricated for the diagnostic field.
    assert candidate.regions is result.best_rejected_regions


# ---------------------------------------------------------------------------
# 6. Part3 +Z with authorization remains unchanged for accepted candidate 110
# ---------------------------------------------------------------------------

@requires_occ
@requires_part3
def test_6_part3_candidate_110_authorized_unchanged():
    result = _part3_candidate_110_result()
    assert result.outcome == "feasible"
    assert result.selected is not None
    assert result.selected.candidate_id == 110

    regions = result.regions
    assert regions is not None
    assert len(regions.cavity_face_ids) == 410
    assert regions.core_face_ids == frozenset({35, 36, 37, 320, 321})
    assert regions.ambiguous_area_fraction == pytest.approx(0.3271748971395147, rel=1e-6)

    face35 = next(f for f in regions.faces if f.face_id == 35)
    assert face35.label == "split"
    assert face35.cavity_area_mm2 == pytest.approx(1302.33, abs=1.0)
    assert face35.core_area_mm2 == pytest.approx(130.23, abs=1.0)

    assert result.selected.feasibility.measurements["h4_orientation_violation_fraction"] == \
        pytest.approx(0.004994890916885516, rel=1e-9)

    # New diagnostic fields must not shadow or alter the accepted result.
    d = result.to_dict()
    assert d["regions"]["core_face_count"] == 5
    assert d["regions"]["cavity_face_count"] == 410
    assert d["selected"]["candidate_id"] == 110


# ---------------------------------------------------------------------------
# 7. Part1 remains unchanged
# ---------------------------------------------------------------------------

@requires_occ
@requires_part1
def test_7_part1_fully_unchanged():
    result = _part1_result()
    assert result.selected is not None
    assert result.selected.candidate_id == 49
    assert result.outcome == "feasible"
    regions = result.regions
    assert regions.cavity_area_fraction_of_confident == pytest.approx(0.2314, abs=0.001)
    assert regions.core_area_fraction_of_confident == pytest.approx(0.7686, abs=0.001)
    assert regions.ambiguous_area_fraction == pytest.approx(0.4557, abs=0.001)
    assert not any(f.label == "split" for f in regions.faces)


# ---------------------------------------------------------------------------
# 8. No H0-H7 / ranking / direction / undercut / core-pin / delegation
#    semantics changed by this purely-additive exposure.
# ---------------------------------------------------------------------------

@requires_occ
@requires_part3
def test_8_gate_evaluation_semantics_unchanged_on_part3_no_auth():
    result = _part3_no_auth_result()
    # Same gate-rejection counts as the pre-change forensic audit run:
    # H3 rejects 159, H4 rejects 151, nothing else -- proves H0-H7
    # evaluation itself was not touched by this change.
    assert len(result.candidates) == 310
    assert result.rejection_summary == {"H3": 159, "H4": 151}
    assert result.outcome == "no_feasible_candidate"


@requires_occ
@requires_part3
def test_8b_core_pin_and_delegation_semantics_unchanged_on_candidate_110():
    from backend.geometry.parting_line_v2.types import EdgeBacking, FaceBacking

    result = _part3_candidate_110_result()
    c = result.selected
    assert c.discovered_by == "cycle_basis"
    assert len(c.segments) == 2
    assert all(isinstance(s.backing, EdgeBacking) for s in c.segments)
    assert not any(isinstance(s.backing, FaceBacking) for s in c.segments)
    assert dict(c.tooling_split_face_ids) == {35: 4.0}
    assert len(c.core_pin_interfaces) == 1
    assert c.core_pin_interfaces[0].face_id == 35
    assert c.core_pin_interfaces[0].split_param == pytest.approx(4.0)
    validated = c.feasibility.validated_delegations
    assert len(validated) == 2
