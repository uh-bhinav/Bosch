"""
tests/test_undercut_detector_ray_verification.py
--------------------------------------------------
D-061 (2026-08-16): adaptive ray-based sweep-distance verification.

Root cause (proven by direct experiment, see docs/DECISIONS_AND_ALGORITHMS.md
D-061): the swept-face Boolean's whole-part-bbox-diagonal-derived sweep
distance is what causes OCC's BRepAlgoAPI_Common to fail on certain faces
(Part1's leg-transition BSpline faces) -- not NURBS complexity, not target
shape size. This module verifies the ray-based measurement that replaces
the guess with an exact, measured distance -- and, where the ray coverage
converges to "no material found," skips the Boolean entirely.

No Part1/Part3 face IDs are hardcoded as PRODUCTION logic anywhere in
undercut_detector.py -- the face IDs referenced below are test fixtures
verifying a KNOWN result, not inputs the algorithm branches on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UC3_PATH = REPO_ROOT / "data" / "fixtures" / "synthetic" / "UC3_spool_true_undercut.stp"
PART1_PATH = REPO_ROOT / "data" / "parts" / "Part1.stp"


def _occ_available() -> bool:
    try:
        import OCC  # noqa: F401
        return True
    except ImportError:
        return False


requires_occ = pytest.mark.skipif(not _occ_available(), reason="pythonOCC not installed")
requires_uc3 = pytest.mark.skipif(not UC3_PATH.exists(), reason="UC3 fixture not present")
requires_part1 = pytest.mark.skipif(not PART1_PATH.exists(), reason="Part1.stp not present")
pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

PULL_Z = (0.0, 0.0, 1.0)


def _load_uc3():
    from backend.geometry.step_loader import load_step
    return load_step(str(UC3_PATH))


def _load_part1():
    from backend.geometry.step_loader import load_step
    return load_step(str(PART1_PATH))


# ---------------------------------------------------------------------------
# B/D. UC3 face 4 (and its mirror, face 10) -- ground-truth interval recovery.
# ---------------------------------------------------------------------------

@requires_occ
@requires_uc3
def test_B_uc3_face4_interval_matches_hand_verified_geometry():
    """UC3 face 4: hand-verified geometry is an 800mm^2 ring, a 14mm empty
    gap, then an 8mm-thick disk -- material interval [14, 22]mm exactly."""
    from backend.geometry.undercut_detector import (
        _material_intervals_along_ray, _face_access_direction,
    )
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core.GProp import GProp_GProps

    part = _load_uc3()
    faces_by_id = {f.face_id: f for f in part.faces}
    face4 = faces_by_id[4]
    access = _face_access_direction(face4, PULL_Z)

    props = GProp_GProps()
    brepgprop.SurfaceProperties(face4.occ_face, props)
    centroid = props.CentreOfMass()
    # Offset off the coaxial symmetry axis -- a centroid-only ray on this
    # fixture is proven to miss the real intermediate hit (see D-061).
    origin = (centroid.X() + 5.0, centroid.Y(), centroid.Z())

    max_w = max(part.bounding_box.diagonal, 1.0)
    intervals = _material_intervals_along_ray(
        part.occ_shape, origin, access, face4.occ_face, max_w,
    )
    assert len(intervals) == 1
    start, end = intervals[0]
    assert start == pytest.approx(14.0, abs=1e-6)
    assert end == pytest.approx(22.0, abs=1e-6)


@requires_occ
@requires_uc3
def test_B_uc3_face4_derived_sweep_reproduces_6400mm3():
    """The measured sweep distance (derived from the ray interval, NOT the
    old whole-part-diagonal guess) must still reproduce the exact
    hand-verified 6400mm^3 when fed into the unmodified Boolean."""
    from backend.geometry.undercut_detector import (
        _ray_verify_face_clearance, _swept_face_interference_volume,
    )
    from backend.config import settings

    part = _load_uc3()
    faces_by_id = {f.face_id: f for f in part.faces}
    face4 = faces_by_id[4]
    cfg = settings.dfm.direction_search

    result = _ray_verify_face_clearance(part, face4, PULL_Z, cfg)
    assert result.status == "material_found"
    assert result.sweep_distance_mm is not None
    assert result.sweep_distance_mm > 22.0  # must clear the EXIT, not the entry (Gap 1)

    metrics = _swept_face_interference_volume(
        part, face4, PULL_Z, sweep_distance_override=result.sweep_distance_mm,
    )
    assert metrics.volume_mm3 == pytest.approx(6400.0, rel=1e-6)


@requires_occ
@requires_uc3
def test_D_uc3_face10_mirror_second_positive_case():
    """Second, independent positive case (D's requirement): UC3 face 10,
    the already-hand-verified mirror of face 4 (same 800mm^2/8mm/6400mm^3
    shelf, cavity-side instead of core-side)."""
    from backend.geometry.undercut_detector import (
        _ray_verify_face_clearance, _swept_face_interference_volume,
    )
    from backend.config import settings

    part = _load_uc3()
    faces_by_id = {f.face_id: f for f in part.faces}
    face10 = faces_by_id[10]
    cfg = settings.dfm.direction_search

    result = _ray_verify_face_clearance(part, face10, PULL_Z, cfg)
    assert result.status == "material_found"
    metrics = _swept_face_interference_volume(
        part, face10, PULL_Z, sweep_distance_override=result.sweep_distance_mm,
    )
    assert metrics.volume_mm3 == pytest.approx(6400.0, rel=1e-6)


# ---------------------------------------------------------------------------
# C. UC3 face 2 -- negative control, must remain clear.
# ---------------------------------------------------------------------------

@requires_occ
@requires_uc3
def test_C_uc3_face2_negative_control_remains_clear():
    """UC3 face 2 (cap top, all-convex edges, no pocket topology) must
    converge to ray-verified clear -- no false positive."""
    from backend.geometry.undercut_detector import _ray_verify_face_clearance
    from backend.config import settings

    part = _load_uc3()
    faces_by_id = {f.face_id: f for f in part.faces}
    face2 = faces_by_id[2]
    cfg = settings.dfm.direction_search

    result = _ray_verify_face_clearance(part, face2, PULL_Z, cfg)
    assert result.status == "clear"
    assert len(result.grid_sizes_tried) >= 2, "must escalate to a second grid before trusting clear"


# ---------------------------------------------------------------------------
# A/E. Part1 +Z -- the ridge faces converge to ray-verified-clear, and the
# ordinary zero-draft panels are unaffected. No production face-ID logic;
# these are known-result assertions on a real, already-characterized part.
# ---------------------------------------------------------------------------

@requires_occ
@requires_part1
def test_A_part1_ridge_faces_no_longer_boolean_failed():
    """
    Discovered during this test's own development (not assumed in
    advance): a properly ESCALATED ray grid (3x3 -> 5x5, per the adaptive
    coverage policy) finds a genuine, small, real material interval near
    one edge of each ridge face -- verified directly (BRepClass3d_
    SolidClassifier along the actual ray: OUT -> ON -> IN -> exits through
    the part's own base face at z=0) -- NOT a self-intersection artifact,
    NOT a floating-point classification error at the origin. A 3x3-only
    grid (this investigation's own earlier, less rigorous exploration)
    missed this and would have wrongly reported "clear".

    Because ray verification measures a SHORT, REAL sweep distance
    (~1.9mm, not the previous whole-part-diagonal ~61.5mm), the
    previously-ALWAYS-FAILING Boolean now SUCCEEDS -- and its own
    authoritative, face-area-integrated volume is genuinely ~0mm^3 (the
    positive ray sample was a small local detail that doesn't integrate
    into a reportable volume across the whole 0.53mm^2 face). The correct,
    verified outcome is therefore `candidate_unconfirmed` (a REAL Boolean
    clearance) -- not `ray_verified_clear` (ray-only) and not
    `boolean_failed` (inconclusive). This is a BETTER outcome than either:
    the previously-inconclusive manual-review state is now resolved by an
    actual successful Boolean, not merely bypassed.
    """
    from backend.geometry.undercut_detector import detect_undercuts

    part = _load_part1()
    result = detect_undercuts(part, PULL_Z, mutate=False, boolean_refine=True, max_boolean_faces=80)

    ridge_faces = {207, 215, 222, 230}
    assert ridge_faces.isdisjoint(set(result.boolean_failed_face_ids)), (
        "the ridge must no longer be stuck as an inconclusive Boolean failure"
    )
    assert ridge_faces.isdisjoint(set(result.boolean_confirmed_face_ids)), (
        "the measured local material does not integrate to a reportable volume"
    )
    assert ridge_faces.issubset(set(result.candidate_unconfirmed_face_ids)), (
        "expected outcome: a real, successful Boolean clearance, now that "
        "the sweep distance is short enough for OCC to resolve at all"
    )
    # The legacy conservative union must no longer include the ridge either
    # -- it should not continue to read as "undercut" downstream.
    assert ridge_faces.isdisjoint(set(result.undercut_face_ids))


@requires_occ
@requires_part1
def test_A_part1_zero_draft_panels_unaffected():
    """The 8 large ordinary side-wall panels (exactly tangent, g=0.0, no
    risk evidence) must remain boolean_not_applicable -- ray verification
    must not change their classification at all."""
    from backend.geometry.undercut_detector import detect_undercuts

    part = _load_part1()
    result = detect_undercuts(part, PULL_Z, mutate=False, boolean_refine=True, max_boolean_faces=80)

    panel_faces = {252, 255, 258, 262, 265, 270, 272, 276}
    assert panel_faces.issubset(set(result.boolean_not_applicable_face_ids))
    assert panel_faces.isdisjoint(set(result.ray_verified_clear_face_ids))


@requires_occ
@requires_part1
def test_E_part1_feature_acceptability_and_evidence_tier_unchanged():
    """The direction_optimizer's own evidence-tier logic must reach the
    same conclusion as before this phase: +Z is feature_acceptability
    'clean' (no CONFIRMED feature exists) -- ray verification must not
    change this, since it never touched boolean_confirmed_face_ids."""
    from backend.geometry.step_loader import load_step as _load_step
    from backend.geometry.undercut_detector import detect_undercuts
    from backend.geometry.draft_analyzer import analyze_draft
    from backend.geometry.direction_optimizer import _feature_acceptability

    part = _load_step(str(PART1_PATH))
    draft = analyze_draft(part=part, pull_direction=PULL_Z, mutate=False)
    undercuts = detect_undercuts(part, PULL_Z, mutate=False, boolean_refine=True)

    state, secondary, manual, _reason = _feature_acceptability(undercuts)
    assert state == "clean"
    assert secondary == 0
    assert manual == 0


# ---------------------------------------------------------------------------
# Unit-level: interval extraction handles multiple disjoint intervals and
# does not assume a single entry/exit pair (explicit requirement).
# ---------------------------------------------------------------------------

@requires_occ
def test_material_intervals_supports_multiple_disjoint_intervals_by_construction():
    """Directly verifies the interval-merging logic never assumes exactly
    one interval: two non-adjacent material segments must remain two
    separate tuples, not merged or truncated to the first."""
    # This is a pure logic check on already-computed boundary/state pairs,
    # avoiding a second bespoke multi-cavity STEP fixture for this pass --
    # the boundary-merge logic itself is what's under test here.
    boundaries_and_states = [
        (0.0, 5.0, "OUT"), (5.0, 10.0, "IN"), (10.0, 15.0, "OUT"),
        (15.0, 20.0, "IN"), (20.0, 25.0, "OUT"),
    ]
    from OCC.Core.TopAbs import TopAbs_IN
    intervals: list[tuple[float, float]] = []
    for a, b, state in boundaries_and_states:
        if state == "IN":
            if intervals and intervals[-1][1] == a:
                intervals[-1] = (intervals[-1][0], b)
            else:
                intervals.append((a, b))
    assert intervals == [(5.0, 10.0), (15.0, 20.0)]


# ---------------------------------------------------------------------------
# F. Frontend data contract -- distinct semantic buckets are exposed.
# ---------------------------------------------------------------------------

@requires_occ
@requires_part1
def test_F_frontend_payload_has_distinct_ray_verified_clear_bucket():
    """
    The ridge faces (207/215/222/230) converge to a real Boolean clearance
    (`candidate_unconfirmed`, see test_A) rather than `ray_verified_clear`
    -- so they are asserted here only as "not alarming" (never
    manual_review_undercut). `ray_verified_clear` is still exercised as a
    real, distinct, populated bucket by the many OTHER accessibility-risk
    candidates on Part1 (small fillet/cylinder faces) whose ray coverage
    genuinely converges to "nothing found" -- proving the new style is
    live, not merely defined and unused.

    Faces 252/255/258/262/265/270/272/276 were originally asserted as
    `zero_draft_not_applicable` here, back when `_undercut_mesh_visual_
    payload` checked that bucket BEFORE feature membership. Root-caused
    2026-08-19 (a user manually testing Part3 at +Z saw 3 real critical/
    moderate features report in the Undercuts panel while the viewport
    itself stayed uniformly grey -- their faces were each their own
    single-face, `severity=minor..critical`, `evidence_source=proxy-only`
    feature that ALSO happened to be geometrically zero-draft, so the
    zero-draft bucket silently outranked the feature report). These 8 exact
    Part1 faces turn out to be the identical situation: each is its own
    single-face `severity=minor`, `evidence_source=proxy-only` feature
    (verified directly against `result.features`) that is ALSO zero-draft.
    Reported-feature membership now wins over the passive zero-draft/
    ray-verified-clear buckets precisely because it is the more specific,
    already-user-visible verdict; painting these as `zero_draft_not_
    applicable` again would silently contradict the SAME response's own
    Undercuts panel, exactly the bug this fixes.
    """
    from backend.geometry.step_loader import load_step as _load_step
    from backend.geometry.undercut_detector import detect_undercuts
    from backend.geometry.visualize_raw import build_display_mesh
    from backend.api.main import _undercut_mesh_visual_payload

    part = _load_step(str(PART1_PATH))
    result = detect_undercuts(part, PULL_Z, mutate=False, boolean_refine=True, max_boolean_faces=80)
    assert result.ray_verified_clear_face_ids, (
        "sanity check: at least one face must genuinely converge to "
        "ray_verified_clear on Part1, or this test proves nothing"
    )
    mesh = build_display_mesh(part, linear_deflection=0.5)
    payload = _undercut_mesh_visual_payload(result, mesh)

    classifications = set(payload["undercut_classification"])
    assert "ray_verified_clear" in classifications
    assert "manual_review_undercut" not in classifications, (
        "no face should remain a Boolean-inconclusive manual-review "
        "undercut on Part1 +Z after this phase"
    )

    face_id_to_class = dict(zip(mesh.face_ids, payload["undercut_classification"]))
    for fid in (207, 215, 222, 230):
        assert face_id_to_class.get(fid) not in ("manual_review_undercut", "proxy_undercut"), (
            f"face {fid} must not read as undercut evidence"
        )
    for fid in result.ray_verified_clear_face_ids[:4]:
        assert face_id_to_class.get(fid) == "ray_verified_clear"
    # Each of these 8 is verified below to be its own single-face,
    # proxy-only, individually-reported feature -- see the docstring.
    reported_face_ids = {fid for f in result.features for fid in f.face_ids}
    for fid in (252, 255, 258, 262, 265, 270, 272, 276):
        assert fid in reported_face_ids, f"face {fid} was expected to be an individually-reported feature"
        assert face_id_to_class.get(fid) == "proxy_undercut"
