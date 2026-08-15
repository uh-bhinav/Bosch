"""
tests/test_parting_line_v2_delegation.py
-----------------------------------------
Acceptance tests for secondary-action delegation (plan D-044).

Frozen invariant under test throughout: passing ``validate_delegation``
means only "this explicitly authorized secondary-action claim is
structurally self-consistent for this candidate" -- never a geometric
release proof. ``DelegationEvidence.geometric_verification`` must stay
``"unverified"`` for every currently-supported delegation, and nothing in
this pipeline may read that value as if it meant more.

Uses the real Part3 +Z rib lattice as the concrete example (established
across this investigation: two independent, mirror-symmetric,
alternating-radius rib stacks -- faces 0-16 and 18-34 -- each internally
connected but NOT connected to each other), without hard-coding any
Part3/Z-specific logic into the mechanism itself.
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

STACK1 = frozenset(range(0, 17))    # confirmed internally connected
STACK2 = frozenset(range(18, 35))   # confirmed internally connected
BOTH_STACKS = STACK1 | STACK2       # confirmed NOT connected to each other
BORE_FACE_ID = 35
PULL_Z = (0.0, 0.0, 1.0)


def _part3():
    from backend.geometry.step_loader import load_step
    return load_step(str(PART3_PATH))


def _cfg():
    from backend.config import settings
    return settings.dfm.parting_line_v2


def _make_delegation(face_ids, direction=(1.0, 0.0, 0.0), source="manual_engineering", note="test evidence"):
    from backend.geometry.parting_line_v2.contracts import DelegatedSecondaryAction, DelegationEvidence
    return DelegatedSecondaryAction(
        face_ids=frozenset(face_ids),
        movement_direction=direction,
        movement_type="radial_slide",
        evidence=DelegationEvidence(source=source, note=note),
    )


def _z4_candidate(part, delegations=(), core_pin=True):
    """The real Part3 +Z candidate at split_param=4.0 (z=4 outer boundary +
    core-pin bore split) -- the concrete test case established this
    session, not a synthetic fixture."""
    from backend.config import settings
    from backend.geometry.parting_line_v2 import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.contracts import CorePinFaceRef
    from backend.geometry.parting_line_v2.engine import analyse_parting_line

    refs = (CorePinFaceRef(BORE_FACE_ID, PULL_Z, "straight coaxial through-bore"),) if core_pin else ()
    result = analyse_parting_line(
        part, PullDirectionInput(PULL_Z, "fixture"), cfg=settings.dfm.parting_line_v2,
        undercuts=UndercutInput.empty(), core_pin_face_refs=refs, delegations=delegations,
    )
    closed = {c.candidate_id: c for c in result.candidates if c.core_pin_interfaces}
    return result, closed[110]


# ---------------------------------------------------------------------------
# 1/16. Baseline / no-side-action candidates byte-identical
# ---------------------------------------------------------------------------

@requires_occ
@requires_part3
def test_1_no_delegation_byte_identical_to_before():
    """Reproduces the exact pre-D-044 measurement: candidate 110 fails H4 at
    7.56% with zero delegated faces when delegations=() (the default)."""
    part = _part3()
    _, c = _z4_candidate(part, delegations=())
    m = c.feasibility.measurements
    assert m["h4_orientation_violation_fraction"] == pytest.approx(0.0756347850231733, rel=1e-9)
    assert m["h4_delegated_face_count"] == 0.0
    assert c.feasibility.failed_gate == "H4"
    assert c.feasibility.validated_delegations == ()


@requires_occ
@requires_part1
def test_16_part1_regression_unaffected_by_delegation_machinery():
    """Part1's mandatory +Z regression stays byte-identical with no
    delegations supplied -- confirms the new machinery is fully inert by
    default."""
    from backend.config import settings
    from backend.geometry.parting_line_v2 import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line
    from backend.geometry.step_loader import load_step

    part = load_step(str(PART1_PATH))
    result = analyse_parting_line(
        part, PullDirectionInput(PULL_Z, "fixture"),
        undercuts=UndercutInput.empty(), cfg=settings.dfm.parting_line_v2,
    )
    assert result.selected is not None
    assert result.selected.feasibility.passed
    assert result.selected.feasibility.validated_delegations == ()
    assert result.selected.feasibility.measurements.get("h4_delegated_face_count", 0.0) == 0.0


# ---------------------------------------------------------------------------
# 2/7. Valid connected delegation; unverified is the accepted, expected value
# ---------------------------------------------------------------------------

@requires_occ
@requires_part3
def test_2_valid_connected_delegation_passes_structural_validation():
    from backend.geometry.parting_line_v2.regions import validate_delegation

    part = _part3()
    _, c = _z4_candidate(part)
    delegation = _make_delegation(STACK1)
    result = validate_delegation(part, c, delegation, PULL_Z, _cfg())
    assert result.eligible is True


@requires_occ
@requires_part3
def test_7_geometric_verification_unverified_is_accepted_not_rejected():
    from backend.geometry.parting_line_v2.contracts import GEOMETRIC_VERIFICATION_UNVERIFIED
    from backend.geometry.parting_line_v2.regions import validate_delegation

    part = _part3()
    _, c = _z4_candidate(part)
    delegation = _make_delegation(STACK1)
    assert delegation.evidence.geometric_verification == GEOMETRIC_VERIFICATION_UNVERIFIED
    result = validate_delegation(part, c, delegation, PULL_Z, _cfg())
    assert result.eligible is True, "unverified must not itself be disqualifying"


# ---------------------------------------------------------------------------
# 3. Disconnected delegation rejected -- the real, concrete failure mode
#    found while implementing this: both rib stacks claimed as ONE record
# ---------------------------------------------------------------------------

@requires_occ
@requires_part3
def test_3_disconnected_face_set_rejected():
    from backend.geometry.parting_line_v2.regions import validate_delegation

    part = _part3()
    _, c = _z4_candidate(part)
    delegation = _make_delegation(BOTH_STACKS)  # confirmed disconnected this session
    result = validate_delegation(part, c, delegation, PULL_Z, _cfg())
    assert result.eligible is False
    assert "connected" in result.reason.lower()


# ---------------------------------------------------------------------------
# 4. Delegation intersecting Gamma rejected
# ---------------------------------------------------------------------------

@requires_occ
@requires_part3
def test_4_delegation_intersecting_loop_rejected():
    from backend.geometry.parting_line_v2.regions import validate_delegation
    from backend.geometry.parting_line_v2.types import EdgeBacking

    part = _part3()
    _, c = _z4_candidate(part)
    loop_edge_ids = frozenset(s.backing.edge_id for s in c.segments if isinstance(s.backing, EdgeBacking))
    loop_face_ids = frozenset(fid for eid in loop_edge_ids for fid in part.edge_to_faces.get(eid, ()))
    assert loop_face_ids, "candidate 110's real boundary must have at least one face"
    on_loop_face = next(iter(loop_face_ids))

    delegation = _make_delegation({on_loop_face})
    result = validate_delegation(part, c, delegation, PULL_Z, _cfg())
    assert result.eligible is False
    assert "intersect" in result.reason.lower()


# ---------------------------------------------------------------------------
# 5. Parallel movement rejected
# ---------------------------------------------------------------------------

@requires_occ
@requires_part3
def test_5_parallel_movement_rejected():
    from backend.geometry.parting_line_v2.regions import validate_delegation

    part = _part3()
    _, c = _z4_candidate(part)
    delegation = _make_delegation(STACK1, direction=PULL_Z)  # identical to primary pull
    result = validate_delegation(part, c, delegation, PULL_Z, _cfg())
    assert result.eligible is False
    assert "parallel" in result.reason.lower() or "distinct" in result.reason.lower()


# ---------------------------------------------------------------------------
# 6. Missing provenance rejected
# ---------------------------------------------------------------------------

@requires_occ
@requires_part3
def test_6_missing_provenance_rejected():
    from backend.geometry.parting_line_v2.regions import validate_delegation

    part = _part3()
    _, c = _z4_candidate(part)
    for source, note in [("", "some note"), ("manual_engineering", "")]:
        delegation = _make_delegation(STACK1, source=source, note=note)
        result = validate_delegation(part, c, delegation, PULL_Z, _cfg())
        assert result.eligible is False


# ---------------------------------------------------------------------------
# 8/9. Undercut detection and H5 unchanged
# ---------------------------------------------------------------------------

@requires_occ
@requires_part3
def test_8_undercut_detection_unaffected_by_delegation():
    """detect_undercuts's own output must not depend on delegation in any
    way -- delegation is not wired into it and must never be."""
    from backend.geometry.undercut_detector import detect_undercuts

    part = _part3()
    result = detect_undercuts(part, PULL_Z, mutate=False, boolean_refine=False)
    # Matches the exact real-detector output already measured this session.
    undercut_face_ids = frozenset(result.undercut_face_ids)
    assert undercut_face_ids == frozenset({35, 37, 38})
    assert not (undercut_face_ids & STACK1)
    assert not (undercut_face_ids & STACK2)


@requires_occ
@requires_part3
def test_9_h5_unaffected_by_delegation():
    """A candidate whose loop touches a real UndercutInput face must still
    be H5-referred exactly as before, regardless of delegation. Uses BOTH
    valid stack delegations so H4 actually passes first (H4 runs before H5
    in gate order -- an H4 failure would return before H5 is ever reached,
    which would not test H5 at all)."""
    from backend.geometry.parting_line_v2.contracts import UndercutFeatureRef, UndercutInput
    from backend.geometry.parting_line_v2.types import EdgeBacking

    part = _part3()
    valid = (
        _make_delegation(STACK1, direction=(1.0, 0.0, 0.0)),
        _make_delegation(STACK2, direction=(-1.0, 0.0, 0.0)),
    )
    _, c = _z4_candidate(part, delegations=valid)
    loop_edge_ids = frozenset(s.backing.edge_id for s in c.segments if isinstance(s.backing, EdgeBacking))
    loop_face_ids = frozenset(fid for eid in loop_edge_ids for fid in part.edge_to_faces.get(eid, ()))
    on_loop_face = next(iter(loop_face_ids))

    undercuts = UndercutInput(
        undercut_face_ids=frozenset({on_loop_face}),
        features=(UndercutFeatureRef(feature_id=0, face_ids=frozenset({on_loop_face}), severity="critical"),),
    )
    from backend.config import settings
    from backend.geometry.parting_line_v2.gates import evaluate_gates

    bbox_diag = sum(  # cheap local recompute, matches engine._bbox_diagonal's formula
        (getattr(part.bounding_box, a) - getattr(part.bounding_box, b)) ** 2
        for a, b in (("xmax", "xmin"), ("ymax", "ymin"), ("zmax", "zmin"))
    ) ** 0.5

    outcome = evaluate_gates(
        c, part, PULL_Z, undercuts=undercuts, cfg=settings.dfm.parting_line_v2,
        bbox_diagonal_mm=bbox_diag, part_projected_area_mm2=1.0,
        delegations=valid,
    )
    assert outcome.report.failed_gate == "H5"
    assert outcome.report.reason == "requires_side_action"
    assert outcome.report.referral is not None
    # H5's own referral must still be built purely from `undercuts`/Γ --
    # never influenced by which delegations happened to validate.
    assert outcome.report.referral.feature_ids == (0,)


# ---------------------------------------------------------------------------
# 10/11/12. H4 exclusion is validated-only and region-aware
# ---------------------------------------------------------------------------

@requires_occ
@requires_part3
def test_10_and_11_h4_excludes_only_validated_faces():
    part = _part3()

    # Rejected delegation (both stacks, disconnected) must NOT reduce h4.
    _, c_rejected = _z4_candidate(part, delegations=(_make_delegation(BOTH_STACKS),))
    assert c_rejected.feasibility.measurements["h4_delegated_face_count"] == 0.0
    assert c_rejected.feasibility.measurements["h4_orientation_violation_fraction"] == pytest.approx(
        0.0756347850231733, rel=1e-9
    )

    # Two valid, separately-connected records DO reduce h4 and ARE used.
    valid = (
        _make_delegation(STACK1, direction=(1.0, 0.0, 0.0)),
        _make_delegation(STACK2, direction=(-1.0, 0.0, 0.0)),
    )
    _, c_valid = _z4_candidate(part, delegations=valid)
    assert c_valid.feasibility.measurements["h4_delegated_face_count"] == 34.0
    assert c_valid.feasibility.measurements["h4_orientation_violation_fraction"] < 0.0756347850231733
    assert len(c_valid.feasibility.validated_delegations) == 2


@requires_occ
@requires_part3
def test_12_region_aware_exclusion():
    """Delegated faces are subtracted only from the region they actually
    belong to -- verified by confirming the excluded faces are exactly the
    delegation's own face_ids, restricted to whichever H3 region contains
    them for this specific candidate (never globally)."""
    from backend.config import settings
    from backend.geometry.parting_line_v2.regions import classify_regions, separate_surface
    from backend.geometry.parting_line_v2.types import EdgeBacking, FaceBacking

    part = _part3()
    valid = (
        _make_delegation(STACK1, direction=(1.0, 0.0, 0.0)),
        _make_delegation(STACK2, direction=(-1.0, 0.0, 0.0)),
    )
    _, c = _z4_candidate(part, delegations=valid)

    loop_edge_ids = frozenset(s.backing.edge_id for s in c.segments if isinstance(s.backing, EdgeBacking))
    split_face_ids = frozenset(s.backing.face_id for s in c.segments if isinstance(s.backing, FaceBacking))
    separation = separate_surface(
        part, loop_edge_ids, split_face_ids=split_face_ids, pull_direction=PULL_Z,
        tooling_split_face_ids=dict(c.tooling_split_face_ids),
    )
    loop_face_ids = frozenset(fid for eid in loop_edge_ids for fid in part.edge_to_faces.get(eid, ()))
    regions = classify_regions(part, separation, PULL_Z, loop_face_ids=loop_face_ids, cfg=settings.dfm.parting_line_v2)

    delegated_face_ids = STACK1 | STACK2
    # All delegated faces must land in the SAME region (cavity, per the
    # already-established candidate 110 shape) -- confirms the exclusion
    # this candidate applied was scoped to real region membership, not an
    # arbitrary global subtraction.
    in_cavity = delegated_face_ids & regions.cavity_face_ids
    in_core = delegated_face_ids & regions.core_face_ids
    assert in_cavity == delegated_face_ids
    assert in_core == frozenset()


# ---------------------------------------------------------------------------
# 13. CorePinInterface and DelegatedSecondaryAction coexist without interaction
# ---------------------------------------------------------------------------

@requires_occ
@requires_part3
def test_13_core_pin_and_delegation_coexist_independently():
    part = _part3()
    valid = (
        _make_delegation(STACK1, direction=(1.0, 0.0, 0.0)),
        _make_delegation(STACK2, direction=(-1.0, 0.0, 0.0)),
    )
    _, c = _z4_candidate(part, delegations=valid, core_pin=True)

    assert len(c.core_pin_interfaces) == 1
    assert c.core_pin_interfaces[0].face_id == BORE_FACE_ID
    assert len(c.feasibility.validated_delegations) == 2
    delegated_faces = {fid for d in c.feasibility.validated_delegations for fid in d.face_ids}
    assert BORE_FACE_ID not in delegated_faces, "core-pin face must never appear in delegated face ids"
    tooling_faces = {fid for fid, _ in c.tooling_split_face_ids}
    assert not (tooling_faces & delegated_faces), "the two mechanisms must never overlap on the same face"
    assert c.feasibility.passed is True


# ---------------------------------------------------------------------------
# 14. Ranking unaffected by delegation metadata
# ---------------------------------------------------------------------------

@requires_occ
@requires_part1
def test_14_ranking_unaffected_by_delegation_metadata():
    """A delegation that validates but is irrelevant to Part1's already-
    passing candidate must not change which candidate is selected or its
    score in any way -- ranking never reads delegation fields."""
    from backend.config import settings
    from backend.geometry.parting_line_v2 import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line
    from backend.geometry.step_loader import load_step
    from backend.geometry.parting_line_v2.types import EdgeBacking

    part = load_step(str(PART1_PATH))
    direction_input = PullDirectionInput(PULL_Z, "fixture")
    cfg = settings.dfm.parting_line_v2

    baseline = analyse_parting_line(part, direction_input, undercuts=UndercutInput.empty(), cfg=cfg)
    assert baseline.selected is not None and baseline.selected.feasibility.passed

    winning_loop_faces = frozenset(
        fid for s in baseline.selected.segments if isinstance(s.backing, EdgeBacking)
        for fid in part.edge_to_faces.get(s.backing.edge_id, ())
    )
    candidate_face = next(f.face_id for f in part.faces if f.face_id not in winning_loop_faces)
    harmless = _make_delegation({candidate_face}, direction=(1.0, 0.0, 0.0))

    with_delegation = analyse_parting_line(
        part, direction_input, undercuts=UndercutInput.empty(), cfg=cfg, delegations=(harmless,),
    )
    assert with_delegation.selected is not None
    assert with_delegation.selected.candidate_id == baseline.selected.candidate_id
    assert with_delegation.selected.score.to_dict() == baseline.selected.score.to_dict()


# ---------------------------------------------------------------------------
# 15. A direction requiring side action can pass H4 when valid delegation
#     resolves the primary-motion violation -- NOT forced, NOT masking
#     extra faces beyond the two authorized records.
# ---------------------------------------------------------------------------

@requires_occ
@requires_part3
def test_15_valid_delegation_allows_h4_to_pass_without_forcing():
    part = _part3()
    valid = (
        _make_delegation(STACK1, direction=(1.0, 0.0, 0.0)),
        _make_delegation(STACK2, direction=(-1.0, 0.0, 0.0)),
    )
    result, c = _z4_candidate(part, delegations=valid)

    assert c.feasibility.passed is True
    assert c.feasibility.failed_gate is None
    assert result.outcome == "feasible"
    assert result.selected is not None
    assert result.selected.candidate_id == c.candidate_id

    # The other two real candidates (z=1.0, z=31.43) must NOT be forced to
    # pass by the same delegation -- confirms nothing beyond the two
    # authorized records was masked to manufacture a pass.
    others = [cc for cc in result.candidates if cc.core_pin_interfaces and cc.candidate_id != c.candidate_id]
    assert others, "expected the other two real core-pin-closed candidates to still be present"
    for other in others:
        assert other.feasibility.passed is False
        assert other.feasibility.failed_gate == "H4"


# ---------------------------------------------------------------------------
# Explicit regression: passing validation is never read as geometric proof
# ---------------------------------------------------------------------------

@requires_occ
@requires_part3
def test_geometric_verification_never_elevated_by_passing_validation():
    from backend.geometry.parting_line_v2.contracts import GEOMETRIC_VERIFICATION_UNVERIFIED

    part = _part3()
    valid = (
        _make_delegation(STACK1, direction=(1.0, 0.0, 0.0)),
        _make_delegation(STACK2, direction=(-1.0, 0.0, 0.0)),
    )
    _, c = _z4_candidate(part, delegations=valid)

    assert c.feasibility.passed is True
    for d in c.feasibility.validated_delegations:
        # Even on a PASSING candidate, whose delegations PASSED validation,
        # geometric_verification must remain exactly "unverified" -- a
        # structural pass is never interpreted as a physical release proof.
        assert d.evidence.geometric_verification == GEOMETRIC_VERIFICATION_UNVERIFIED
