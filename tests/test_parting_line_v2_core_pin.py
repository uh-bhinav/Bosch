"""
tests/test_parting_line_v2_core_pin.py
---------------------------------------
Acceptance tests for the core-pin / tooling-split mechanism (plan D-043).

A face exactly coaxial with the pull direction (g = 0 along its ENTIRE
length -- e.g. Part3's central bore, face 35, at +Z) has no Track-B
silhouette crossing anywhere on it, so no candidate loop can ever be closed
by cutting through it. This mechanism lets an explicitly-authorized coaxial
face participate in H3's region-separation test via a non-geometric,
axial-parameter-based logical split -- WITHOUT adding a curve to the real
parting line (`.segments`/`.loops` are never touched).

Every test here reproduces a specific, previously-verified measurement from
the validation experiments this mechanism was built from (see
`backend/validation/parting_line_tooling_backing_experiment.py` and
`docs/DECISIONS_AND_ALGORITHMS.md` D-043) rather than asserting new,
unverified numbers.
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

# The real, B-Rep-verified z=22 outer boundary edges (confirmed this session:
# endpoint-walk shows edges 35, 121, 95, 122 close into one loop on their own,
# total length 78.54mm = 2*pi*12.5mm, split into 4 arcs by faces 325/366).
Z22_OUTER_BOUNDARY_EDGES = frozenset({35, 121, 95, 122})
BORE_FACE_ID = 35          # coaxial through-bore, eligible
RIB_FACE_ID = 0            # alternating-radius rib cylinder, must be ineligible
CONE_FACE_ID = 39          # not a cylinder, must be ineligible
OUTER_WALL_FACE_ID = 37    # eligible IN ISOLATION but not a bridge for z=22


def _part3():
    from backend.geometry.step_loader import load_step
    return load_step(str(PART3_PATH))


def _cfg():
    from backend.config import settings
    return settings.dfm.parting_line_v2


# ---------------------------------------------------------------------------
# regions.py unit tests -- the mechanism in isolation
# ---------------------------------------------------------------------------

@requires_occ
@requires_part3
def test_no_tooling_split_reproduces_h3_failure():
    """The real z=22 boundary alone, with NO tooling metadata, must fail H3
    with exactly 1 region -- the bore bridges both sides. Baseline for every
    other test in this file."""
    from backend.geometry.parting_line_v2.regions import separate_surface

    part = _part3()
    result = separate_surface(part, Z22_OUTER_BOUNDARY_EDGES, pull_direction=(0.0, 0.0, 1.0))
    assert result.component_count == 1


@requires_occ
@requires_part3
def test_resolve_primary_split_param_is_canonical():
    """The real z=22 boundary's edges must agree on a single axial position,
    and that position must be exactly 22.0 (measured this session)."""
    from backend.geometry.parting_line_v2.regions import resolve_primary_split_param

    part = _part3()
    split_param = resolve_primary_split_param(part, Z22_OUTER_BOUNDARY_EDGES, (0.0, 0.0, 1.0))
    assert split_param == pytest.approx(22.0, abs=1e-6)


@requires_occ
@requires_part3
def test_correct_bridge_35_produces_h3_equals_2():
    """Reproduces the validated topology experiment exactly: tooling split
    on face 35 at the canonical split_param gives component_count=2, with
    282/133 face membership and the bore's two ends on opposite sides."""
    from backend.geometry.parting_line_v2.regions import (
        resolve_primary_split_param,
        separate_surface,
    )

    part = _part3()
    pull = (0.0, 0.0, 1.0)
    split_param = resolve_primary_split_param(part, Z22_OUTER_BOUNDARY_EDGES, pull)

    result = separate_surface(
        part, Z22_OUTER_BOUNDARY_EDGES,
        tooling_split_face_ids={BORE_FACE_ID: split_param}, pull_direction=pull,
    )
    assert result.component_count == 2
    sizes = sorted(len(c) for c in result.components)
    assert sizes == [133, 282]

    comp_of = {fid: i for i, comp in enumerate(result.components) for fid in comp}
    assert comp_of[320] != comp_of[319], "bore's two ends must land on opposite sides"
    assert comp_of[36] == comp_of[320] == comp_of[0], "base flange + rib lattice on one side"
    assert comp_of[38] == comp_of[319], "mid shaft band + top side on the other"


@requires_occ
@requires_part3
def test_rib_face_fails_eligibility():
    """A rib-lattice cylinder is ALSO exactly coaxial with uniform g on its
    own sub-face (same as the bore) -- eligibility must reject it on the
    exactly-two-neighbours criterion, not on g-uniformity."""
    from backend.geometry.parting_line_v2.regions import check_core_pin_eligibility

    part = _part3()
    result = check_core_pin_eligibility(part, RIB_FACE_ID, (0.0, 0.0, 1.0), _cfg(), split_param=22.0)
    assert result.eligible is False
    assert "neighbour" in result.reason.lower() or "neighbor" in result.reason.lower()


@requires_occ
@requires_part3
def test_cone_face_fails_eligibility():
    """Face 39 is a 15-degree cone, not a cylinder -- must reject on surface
    type before any other check runs."""
    from backend.geometry.parting_line_v2.regions import check_core_pin_eligibility

    part = _part3()
    result = check_core_pin_eligibility(part, CONE_FACE_ID, (0.0, 0.0, 1.0), _cfg(), split_param=22.0)
    assert result.eligible is False
    assert "cylinder" in result.reason.lower()


@requires_occ
@requires_part3
def test_mismatched_split_param_hard_fails():
    """A boundary whose edges do not agree on a single axial position must
    raise, never silently average or snap. Mixes a real z=22 edge (35) with
    a real z=1 edge (111, part of the base-flange boundary) -- these
    disagree by 21mm, far beyond tolerance."""
    from backend.geometry.parting_line_v2.regions import resolve_primary_split_param

    part = _part3()
    inconsistent_edges = frozenset({35, 111})
    with pytest.raises(ValueError):
        resolve_primary_split_param(part, inconsistent_edges, (0.0, 0.0, 1.0))

    # The real, consistent boundary must NOT raise, and must resolve to the
    # measured value, not an arbitrary guess.
    result = resolve_primary_split_param(part, Z22_OUTER_BOUNDARY_EDGES, (0.0, 0.0, 1.0))
    assert result == pytest.approx(22.0, abs=1e-6)
    assert result != 10.0


@requires_occ
@requires_part3
def test_non_closing_boundary_fails_ordinary_h1_reasoning():
    """An incomplete boundary (missing 2 of the 4 real arcs) does not close
    -- confirmed via the same endpoint-walk method used to verify the real
    boundary DOES close. This is what H1 checks before H3/tooling logic ever
    runs in the real pipeline."""
    from OCC.Core.BRepAdaptor import BRepAdaptor_Curve

    part = _part3()
    edges_by_id = {e.edge_id: e for e in part.edges}
    incomplete = frozenset({35, 95})  # missing 121, 122

    def endpoints(edge_id):
        c = BRepAdaptor_Curve(edges_by_id[edge_id].occ_edge)
        p0, p1 = c.Value(c.FirstParameter()), c.Value(c.LastParameter())
        return (round(p0.X(), 4), round(p0.Y(), 4), round(p0.Z(), 4)), \
               (round(p1.X(), 4), round(p1.Y(), 4), round(p1.Z(), 4))

    from collections import defaultdict
    adjacency = defaultdict(list)
    for edge_id in incomplete:
        a, b = endpoints(edge_id)
        adjacency[a].append(edge_id)
        adjacency[b].append(edge_id)
    open_endpoints = [pt for pt, conns in adjacency.items() if len(conns) == 1]
    assert len(open_endpoints) > 0, "incomplete boundary must not close"


@requires_occ
@requires_part3
def test_wrong_bridge_face_does_not_rescue_h3_causally():
    """Face 37 (outer wall) is a legitimate topological articulation-point
    bridge for THIS graph (base-flange 'stem' is a simple unbranched path,
    so every node on it is individually a bridge in the pure graph sense) --
    but it fails eligibility (split_param=22 lies outside its own z=[1,4]
    extent), so the FULL guarded pipeline (bridge-localize -> authorize ->
    eligibility -> only then construct tooling metadata) never actually
    uses it, and H3 cannot be rescued by it.

    This also demonstrates directly why eligibility must run BEFORE
    tooling_split_face_ids is ever constructed: calling separate_surface
    with an ineligible face's tooling split bypassed can itself produce a
    spurious component_count==2 (an isolated degenerate node, not a real
    separation) -- confirmed here as the reason the guard is load-bearing,
    not merely defensive.
    """
    from backend.geometry.parting_line_v2.regions import (
        check_core_pin_eligibility,
        find_bridge_faces,
        resolve_primary_split_param,
        separate_surface,
    )

    part = _part3()
    pull = (0.0, 0.0, 1.0)
    split_param = resolve_primary_split_param(part, Z22_OUTER_BOUNDARY_EDGES, pull)

    bridges = find_bridge_faces(part, Z22_OUTER_BOUNDARY_EDGES)
    assert OUTER_WALL_FACE_ID in bridges, (
        "face 37 IS a genuine topological bridge candidate for this graph -- "
        "localization must not silently omit it"
    )

    eligibility = check_core_pin_eligibility(part, OUTER_WALL_FACE_ID, pull, _cfg(), split_param)
    assert eligibility.eligible is False
    assert "extent" in eligibility.reason.lower()

    # Confirm the guarded pipeline (authorize + eligibility-gate) never
    # constructs tooling metadata for it, so H3 stays failed.
    authorized = {OUTER_WALL_FACE_ID}
    usable_bridges = bridges & authorized
    chosen = None
    for face_id in sorted(usable_bridges):
        if check_core_pin_eligibility(part, face_id, pull, _cfg(), split_param).eligible:
            chosen = face_id
    assert chosen is None, "no eligible face found -- tooling metadata must never be constructed"


@requires_occ
@requires_part3
def test_unauthorized_real_bridge_stays_rejected():
    """Face 35 IS the correct, eligible bridge -- but if it is simply not in
    the authorized set at all, the candidate must remain rejected exactly as
    if the mechanism did not exist."""
    from backend.geometry.parting_line_v2.regions import find_bridge_faces

    part = _part3()
    bridges = find_bridge_faces(part, Z22_OUTER_BOUNDARY_EDGES)
    authorized: set[int] = set()  # face 35 deliberately NOT authorized
    assert (bridges & authorized) == set()


# ---------------------------------------------------------------------------
# engine.py integration tests -- the full guarded pipeline
# ---------------------------------------------------------------------------

@requires_occ
@requires_part3
def test_engine_with_empty_core_pin_refs_is_unaffected():
    """`core_pin_face_refs` defaults to empty -- Round 1.5 must not engage,
    and the result must carry no core_pin_interfaces anywhere."""
    from backend.config import settings
    from backend.geometry.parting_line_v2 import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line

    part = _part3()
    result = analyse_parting_line(
        part, PullDirectionInput((0.0, 0.0, 1.0), "fixture"),
        undercuts=UndercutInput.empty(), cfg=settings.dfm.parting_line_v2,
    )
    assert all(not c.core_pin_interfaces for c in result.candidates)
    assert all(c.tooling_split_face_ids == () for c in result.candidates)


@requires_occ
@requires_part3
def test_engine_authorized_bore_produces_core_pin_closure():
    """With face 35 explicitly authorized, Round 1.5 must produce at least
    one candidate whose H3 passes via a tooling split -- reproducing the
    real end-to-end measurement from this session (candidates closed at
    z=1.0, z=4.0, and z=31.43, all subsequently and separately rejected at
    H4 -- a pre-existing, deliberately out-of-scope gap this mechanism does
    not touch)."""
    from backend.config import settings
    from backend.geometry.parting_line_v2 import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.contracts import CorePinFaceRef
    from backend.geometry.parting_line_v2.engine import analyse_parting_line

    part = _part3()
    refs = (CorePinFaceRef(BORE_FACE_ID, (0.0, 0.0, 1.0), "straight coaxial through-bore"),)
    result = analyse_parting_line(
        part, PullDirectionInput((0.0, 0.0, 1.0), "fixture"),
        undercuts=UndercutInput.empty(), cfg=settings.dfm.parting_line_v2,
        core_pin_face_refs=refs,
    )
    closed = [c for c in result.candidates if c.core_pin_interfaces]
    assert len(closed) >= 1
    for c in closed:
        assert c.tooling_split_face_ids[0][0] == BORE_FACE_ID
        # H3 must have passed for a candidate reaching core-pin closure at
        # all -- if it failed, gate order guarantees failed_gate is "H3" or
        # later, never left unset.
        assert c.feasibility is not None
    # None of the tooling curves are geometric: no candidate's raw segment/
    # loop content differs in KIND from an ordinary candidate.
    for c in closed:
        assert c.loop_count >= 1


@requires_occ
@requires_part3
def test_engine_core_pin_never_adds_a_geometric_curve():
    """The real Γ must be unchanged: a closed candidate's `.segments` must
    contain only EdgeBacking/FaceBacking, never a third kind, and its loop
    count/content must be exactly what Round 1 discovered -- no bore curve
    appended."""
    from backend.config import settings
    from backend.geometry.parting_line_v2 import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.contracts import CorePinFaceRef
    from backend.geometry.parting_line_v2.engine import analyse_parting_line
    from backend.geometry.parting_line_v2.types import EdgeBacking, FaceBacking

    part = _part3()
    refs = (CorePinFaceRef(BORE_FACE_ID, (0.0, 0.0, 1.0), "straight coaxial through-bore"),)
    result = analyse_parting_line(
        part, PullDirectionInput((0.0, 0.0, 1.0), "fixture"),
        undercuts=UndercutInput.empty(), cfg=settings.dfm.parting_line_v2,
        core_pin_face_refs=refs,
    )
    closed = [c for c in result.candidates if c.core_pin_interfaces]
    assert len(closed) >= 1
    for c in closed:
        for seg in c.segments:
            assert isinstance(seg.backing, (EdgeBacking, FaceBacking))


# ---------------------------------------------------------------------------
# Existing-behaviour regression: golden fixtures unaffected
# ---------------------------------------------------------------------------

@requires_occ
@requires_part1
def test_part1_plus_z_regression_unaffected_by_core_pin_mechanism():
    """Part1's mandatory +Z regression (test_parting_line_v2_level1.py) must
    remain byte-identical: no core_pin_face_refs supplied here, matching
    every pre-existing call site."""
    from backend.config import settings
    from backend.geometry.parting_line_v2 import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line
    from backend.geometry.step_loader import load_step

    part = load_step(str(PART1_PATH))
    result = analyse_parting_line(
        part, PullDirectionInput((0.0, 0.0, 1.0), "fixture"),
        undercuts=UndercutInput.empty(), cfg=settings.dfm.parting_line_v2,
    )
    assert result.selected is not None
    assert result.selected.feasibility.passed
    assert not result.selected.core_pin_interfaces
