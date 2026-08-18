"""
tests/test_undercut_detector_classifier_hoist.py
--------------------------------------------------
O9 (2026-08-17): BRepClass3d_SolidClassifier(part.occ_shape)'s constructor
depends only on part.occ_shape -- never on the candidate face, ray origin/
direction, or pull direction -- yet was reconstructed once per ray inside
_material_intervals_along_ray(). O8's forensic measurement found ~1,200
such reconstructions per direction, 19-44% of detect_undercuts()'s total
runtime. O9 hoists it: ONE classifier is now built once in
_boolean_refine_undercuts() and threaded through
_ray_verify_face_clearance() -> _material_intervals_along_ray(), reused
across every ray. Both functions default the new `classifier` parameter to
None, which reproduces byte-identical pre-O9 behaviour (their own fresh
construction) for any caller that doesn't supply one.

Important discovery made WHILE building this test's A/B validation
(directly investigated, not assumed away): Part1's diagonal direction has
one candidate face (296, a leg-transition BSpline face -- the same face
class D-061's docstring already flags as Boolean-fragile) whose
BRepAlgoAPI_Common outcome (confirmed vs failed) is NOT deterministic
across repeated identical calls, confirmed by running the CURRENT
(post-O9, classifier-reused) code path twice in a row with nothing else
changed and observing different outcomes both times. Directly isolating
_ray_verify_face_clearance(296, ...) proved its own output (status,
sweep_distance_mm, samples_with_material) is IDENTICAL whether the
classifier is freshly constructed or reused -- the non-determinism lives
entirely downstream, inside the swept-face Boolean itself, and predates
and is independent of this hoist (O9 explicitly does not touch
BRepAlgoAPI_Common). test_4 below therefore excludes face 296 from its
strict equality checks, with this exact rationale documented at that
assertion.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PART1_PATH = REPO_ROOT / "data" / "parts" / "Part1.stp"


def _occ_available() -> bool:
    try:
        import OCC  # noqa: F401
        return True
    except ImportError:
        return False


requires_occ = pytest.mark.skipif(not _occ_available(), reason="pythonOCC not installed")
requires_part1 = pytest.mark.skipif(not PART1_PATH.exists(), reason="Part1.stp not present")
pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

PULL_Z = (0.0, 0.0, 1.0)
DIAGONAL = (-0.7071067811865475, 0.0, 0.7071067811865475)


def _load_part1():
    from backend.geometry.step_loader import load_step
    return load_step(str(PART1_PATH))


def _run_detect_undercuts(part, direction):
    from backend.geometry.draft_analyzer import analyze_draft, precompute_directional_metrics
    from backend.geometry.undercut_detector import detect_undercuts

    metrics = precompute_directional_metrics(part, direction)
    draft = analyze_draft(part=part, pull_direction=direction, mutate=False, precomputed_metrics=metrics)
    return detect_undercuts(
        part, direction, mutate=False, boolean_refine=True,
        precomputed_metrics=metrics, draft_result=draft,
    )


# ---------------------------------------------------------------------------
# TEST 1 -- constructor call-count
# ---------------------------------------------------------------------------

@requires_occ
@requires_part1
def test_1_classifier_constructed_once_per_detect_undercuts_call(monkeypatch):
    import backend.geometry.undercut_detector as ud

    real_classifier_cls = ud.BRepClass3d_SolidClassifier
    construct_count = {"n": 0}

    class CountingClassifier:
        def __init__(self, shape):
            construct_count["n"] += 1
            self._real = real_classifier_cls(shape)

        def Perform(self, p, tol):
            return self._real.Perform(p, tol)

        def State(self):
            return self._real.State()

    monkeypatch.setattr(ud, "BRepClass3d_SolidClassifier", CountingClassifier)

    part = _load_part1()
    _run_detect_undercuts(part, PULL_Z)

    assert construct_count["n"] == 1, (
        f"expected exactly one BRepClass3d_SolidClassifier construction per "
        f"detect_undercuts() call, got {construct_count['n']}"
    )


def test_1b_ray_verify_face_clearance_signature_accepts_optional_classifier():
    import inspect
    from backend.geometry.undercut_detector import _ray_verify_face_clearance, _material_intervals_along_ray

    params = inspect.signature(_ray_verify_face_clearance).parameters
    assert "classifier" in params
    assert params["classifier"].default is None

    params2 = inspect.signature(_material_intervals_along_ray).parameters
    assert "classifier" in params2
    assert params2["classifier"].default is None


# ---------------------------------------------------------------------------
# TEST 2 -- classification identity: reused classifier vs fresh-per-point
# ---------------------------------------------------------------------------

@requires_occ
@requires_part1
def test_2_reused_classifier_matches_fresh_classifier_per_point():
    """
    Direct proof that .Perform()/.State() on a REUSED classifier instance
    gives identical results, point by point, to a FRESH classifier built
    for each individual point -- the exact correctness contract O9 relies
    on. Uses several representative points spanning inside/outside/near
    Part1's own solid, not just one trivial case.
    """
    from OCC.Core.gp import gp_Pnt
    from OCC.Core.BRepClass3d import BRepClass3d_SolidClassifier

    part = _load_part1()
    shape = part.occ_shape
    bbox = part.bounding_box

    cx = (bbox.xmin + bbox.xmax) / 2.0
    cy = (bbox.ymin + bbox.ymax) / 2.0
    cz = (bbox.zmin + bbox.zmax) / 2.0
    points = [
        (cx, cy, cz),                          # bbox center -- likely inside
        (bbox.xmin - 10.0, bbox.ymin - 10.0, bbox.zmin - 10.0),  # far outside
        (bbox.xmax + 10.0, cy, cz),            # outside, offset from center
        (cx, cy, bbox.zmin),                   # on/near the bbox boundary
        (bbox.xmin, bbox.ymin, bbox.zmin),   # bbox corner
    ]
    tol = 1e-6

    fresh_states = []
    for p in points:
        c = BRepClass3d_SolidClassifier(shape)
        c.Perform(gp_Pnt(*p), tol)
        fresh_states.append(c.State())

    reused = BRepClass3d_SolidClassifier(shape)
    reused_states = []
    for p in points:
        reused.Perform(gp_Pnt(*p), tol)
        reused_states.append(reused.State())

    assert reused_states == fresh_states, (
        "a reused BRepClass3d_SolidClassifier must classify each point "
        "identically to a freshly-constructed one for the same point"
    )


@requires_occ
@requires_part1
def test_2b_material_intervals_along_ray_identical_with_and_without_reused_classifier():
    """Same identity proof, one level up: _material_intervals_along_ray's
    actual return value (material intervals), not just raw classifier
    state, must be identical whether it builds its own classifier or is
    given a pre-built one."""
    from OCC.Core.BRepClass3d import BRepClass3d_SolidClassifier
    from backend.geometry.undercut_detector import _material_intervals_along_ray, _face_uv_grid_points

    part = _load_part1()
    face = part.get_face(296)
    assert face is not None

    points = _face_uv_grid_points(face.occ_face, 3)
    assert points, "face 296 must yield UV sample points for this test to be meaningful"
    access = (-1.0, 0.0, 1.0)  # arbitrary fixed direction, not tied to any candidate logic
    max_w = max(part.bounding_box.diagonal, 1.0)

    shared = BRepClass3d_SolidClassifier(part.occ_shape)
    for origin in points:
        without = _material_intervals_along_ray(part.occ_shape, origin, access, face.occ_face, max_w)
        with_shared = _material_intervals_along_ray(
            part.occ_shape, origin, access, face.occ_face, max_w, classifier=shared,
        )
        assert with_shared == without, f"interval mismatch at origin={origin}"


# ---------------------------------------------------------------------------
# TESTS 3/4 -- Part1 +Z / diagonal regression (dynamic old-vs-new A/B)
# ---------------------------------------------------------------------------

def _run_with_forced_fresh_classifier(part, direction):
    """Simulates pre-O9 behaviour exactly: _ray_verify_face_clearance is
    called the same way, but with classifier forced to None, so
    _material_intervals_along_ray falls back to its own per-ray
    construction -- byte-identical to the code path before this phase."""
    import backend.geometry.undercut_detector as ud

    real_ray_verify = ud._ray_verify_face_clearance

    def forced(part, face, pull_direction, cfg, classifier=None):
        return real_ray_verify(part, face, pull_direction, cfg, classifier=None)

    ud._ray_verify_face_clearance = forced
    try:
        return _run_detect_undercuts(part, direction)
    finally:
        ud._ray_verify_face_clearance = real_ray_verify


REGRESSION_FIELDS = [
    "boolean_confirmed_face_ids", "boolean_failed_face_ids",
    "boolean_skipped_face_ids", "ray_verified_clear_face_ids",
    "candidate_unconfirmed_face_ids", "accessibility_risk_face_ids",
    "boolean_checked_face_ids", "undercut_face_ids", "parting_face_ids",
    "boolean_not_applicable_face_ids",
]


@requires_occ
@requires_part1
def test_3_part1_z_evidence_unchanged_by_classifier_hoist():
    part = _load_part1()
    old = _run_with_forced_fresh_classifier(part, PULL_Z)
    new = _run_detect_undercuts(part, PULL_Z)

    for field in REGRESSION_FIELDS:
        assert sorted(getattr(new, field)) == sorted(getattr(old, field)), (
            f"{field} changed between pre-O9 (fresh classifier per ray) and "
            f"post-O9 (reused classifier) for Part1 +Z"
        )


@requires_occ
@requires_part1
def test_4_part1_diagonal_evidence_unchanged_by_classifier_hoist_excluding_known_flaky_face():
    """
    Face 296 is EXCLUDED from these comparisons -- not because the
    classifier hoist is suspected of affecting it, but because it was
    directly proven NOT to (see this module's docstring and the isolated
    _ray_verify_face_clearance(296, ...) check performed during this
    phase's own investigation: identical status/sweep_distance_mm/
    samples_with_material whether the classifier is fresh or reused).
    Its swept-face BOOLEAN outcome (confirmed vs failed) was independently
    proven non-deterministic ACROSS REPEATED CALLS OF THE SAME (post-O9)
    code path -- a pre-existing BRepAlgoAPI_Common sensitivity this phase
    does not touch, investigate, or fix (explicitly out of scope). Asserting
    face 296's exact bucket here would make this test flaky for a reason
    unrelated to what it verifies.
    """
    part = _load_part1()
    old = _run_with_forced_fresh_classifier(part, DIAGONAL)
    new = _run_detect_undercuts(part, DIAGONAL)

    known_flaky_faces = {296}
    for field in REGRESSION_FIELDS:
        old_ids = set(getattr(old, field)) - known_flaky_faces
        new_ids = set(getattr(new, field)) - known_flaky_faces
        assert new_ids == old_ids, (
            f"{field} changed (outside the known pre-existing flaky face "
            f"{known_flaky_faces}) between pre-O9 and post-O9 for Part1 diagonal"
        )

    # Face 296 must still land in EXACTLY ONE of {confirmed, failed,
    # candidate_unconfirmed} in both runs -- never silently dropped from
    # evidence-tracking altogether, whichever way the flaky Boolean landed.
    def bucket_of_296(result):
        if 296 in result.boolean_confirmed_face_ids:
            return "confirmed"
        if 296 in result.boolean_failed_face_ids:
            return "failed"
        if 296 in result.candidate_unconfirmed_face_ids:
            return "candidate_unconfirmed"
        return None

    assert bucket_of_296(old) is not None
    assert bucket_of_296(new) is not None
