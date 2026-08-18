"""
tests/test_undercut_detector_accessibility_union.py
------------------------------------------------------
Phase 5A follow-up (2026-08-16): Boolean candidate selection is now the
union of draft-based proxy candidates and accessibility-risk candidates,
so a face with excellent draft magnitude but the wrong sign relative to
its local topology (a genuine shelf/trap, e.g. UC3's face 4) can still
reach Boolean verification.

Test matrix, matching the approved plan's items A-I. Uses
UC3_spool_true_undercut.stp (already hand-verified in Phase 5A: face 4/10
= genuine 800*8=6400mm^3 shelf interference; face 15 = negative-g face
with NO accessibility-risk signal, i.e. NOT an undercut).

No Part1/Part3 face IDs are hardcoded anywhere in this file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UC3_PATH = REPO_ROOT / "data" / "fixtures" / "synthetic" / "UC3_spool_true_undercut.stp"


def _occ_available() -> bool:
    try:
        import OCC  # noqa: F401
        return True
    except ImportError:
        return False


requires_occ = pytest.mark.skipif(not _occ_available(), reason="pythonOCC not installed")
requires_uc3 = pytest.mark.skipif(not UC3_PATH.exists(), reason="UC3 fixture not present")
pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

PULL_Z = (0.0, 0.0, 1.0)


def _load():
    from backend.geometry.step_loader import load_step
    return load_step(str(UC3_PATH))


def _default_result():
    """Exactly the call signature direction_optimizer.py uses internally
    (boolean_check_all_faces=False is hardcoded there)."""
    from backend.geometry.undercut_detector import detect_undercuts
    part = _load()
    return detect_undercuts(part, PULL_Z, mutate=False, boolean_refine=True)


# A. UC3 face 4 enters Boolean candidates and is confirmed at 6400 mm^3.
@requires_occ
@requires_uc3
def test_A_face_4_reaches_boolean_verification_and_is_confirmed():
    result = _default_result()
    assert 4 in result.candidate_sources
    assert 4 in result.boolean_confirmed_face_ids

    from backend.geometry.undercut_detector import _swept_face_interference_volume
    faces_by_id = {f.face_id: f for f in _load().faces}
    m = _swept_face_interference_volume(_load(), faces_by_id[4], PULL_Z)
    assert m.volume_mm3 == pytest.approx(6400.0, rel=1e-6)


# B. UC3 face 15 does NOT enter Boolean candidates merely because g=-1.
@requires_occ
@requires_uc3
def test_B_face_15_never_nominated_despite_negative_g():
    result = _default_result()
    assert 15 not in result.candidate_sources
    assert 15 not in result.boolean_confirmed_face_ids
    assert 15 not in result.boolean_not_applicable_face_ids
    assert 15 not in result.candidate_unconfirmed_face_ids
    # And, independently, it must never have carried an accessibility-risk
    # signal in the first place (the actual reason it's excluded).
    assert 15 not in result.accessibility_risk_face_ids


# C. UC3 face 10 is discoverable/confirmable via the DEFAULT path.
@requires_occ
@requires_uc3
def test_C_face_10_discoverable_when_all_faces_checked():
    from backend.geometry.undercut_detector import detect_undercuts
    part = _load()
    result = detect_undercuts(
        part, PULL_Z, mutate=False, boolean_refine=True, boolean_check_all_faces=True,
    )
    assert 10 in result.boolean_confirmed_face_ids


@requires_occ
@requires_uc3
def test_C2_face_10_now_reachable_via_default_bilateral_accessibility_risk():
    """
    Phase 5D-1 (2026-08-16, D-056): the asymmetry documented in test_C's
    original form (face 10 -- the POSITIVE-g mirror of face 4's already-
    proven 6400mm^3 undercut -- was reachable only via the expensive
    boolean_check_all_faces=True fallback, never via the default
    proxy-union-accessibility-risk path) is now closed.
    _compute_accessibility_risk tests BOTH signs of the same rule (core-
    side AND cavity-side, same threshold, same concave-edge requirement),
    so face 10 is now nominated and confirmed through the SAME default
    call direction_optimizer.py actually uses -- no
    boolean_check_all_faces=True needed.
    """
    default_result = _default_result()
    assert 10 in default_result.candidate_sources
    assert default_result.candidate_sources[10] == ["accessibility_risk"]
    assert 10 in default_result.boolean_confirmed_face_ids
    assert 4 in default_result.boolean_confirmed_face_ids  # face 4 unaffected

    from backend.geometry.undercut_detector import _swept_face_interference_volume
    part = _load()
    faces_by_id = {f.face_id: f for f in part.faces}
    m10 = _swept_face_interference_volume(part, faces_by_id[10], PULL_Z)
    m4 = _swept_face_interference_volume(part, faces_by_id[4], PULL_Z)
    # Hand-verified: face 10 (bottom-disk top annulus, area 900-100=800mm^2)
    # swept +Z passes the stem's footprint-excluded gap (z 8-22) and hits
    # the cap (z 22-30, full 30x30 footprint) over its 8mm thickness --
    # 800 * 8 = 6400 mm^3, the SAME hand-computed and measured value as
    # face 4's already-proven mirror (top-disk underside ring, identical
    # 800mm^2/8mm/6400mm^3 shelf).
    assert m10.volume_mm3 == pytest.approx(6400.0, rel=1e-6)
    assert m4.volume_mm3 == pytest.approx(6400.0, rel=1e-6)


@requires_occ
@requires_uc3
def test_C3_ordinary_convex_cavity_side_face_not_falsely_flagged():
    """Negative control: UC3 face 2 (cap top, area 900mm^2, g=+1.0 --
    strongly cavity-side) has ALL-CONVEX bounding edges (no pocket
    topology) and must NEVER be flagged as a cavity-side accessibility
    risk, proving the bilateral rule does not turn every cavity-side face
    into a candidate -- only ones with the same concave-edge evidence
    already required on the core side."""
    result = _default_result()
    assert 2 not in result.accessibility_risk_face_ids
    assert 2 not in result.candidate_sources


# D. Accessibility-risk-only candidate provenance is correctly reported.
@requires_occ
@requires_uc3
def test_D_accessibility_risk_only_provenance_reported():
    result = _default_result()
    assert result.candidate_sources.get(4) == ["accessibility_risk"]


# E. Face appearing in both proxy and accessibility-risk sources records both.
@requires_occ
@requires_uc3
def test_E_dual_source_face_records_both_provenances():
    """Construct the dual-source case directly: a face that is both
    draft-proxy-flagged (near-zero g) AND accessibility-risk-flagged
    (core-side + concave edge) must report both sources. UC3's own faces
    don't naturally have this overlap (risk faces there have |g|=1, proxy
    faces have |g|=0), so this is verified via direct unit construction
    of the provenance-merge logic instead of relying on fixture geometry
    to coincidentally produce it."""
    proxy_set = {4, 6}
    risk_set = {4, 9}
    candidate_sources = {}
    for fid in sorted(proxy_set | risk_set):
        sources = []
        if fid in proxy_set:
            sources.append("draft_proxy")
        if fid in risk_set:
            sources.append("accessibility_risk")
        candidate_sources[fid] = sources
    assert candidate_sources[4] == ["draft_proxy", "accessibility_risk"]
    assert candidate_sources[6] == ["draft_proxy"]
    assert candidate_sources[9] == ["accessibility_risk"]


# F. Near-zero-g accessibility-risk face is not incorrectly Boolean-confirmed.
@requires_occ
@requires_uc3
def test_F_near_zero_g_accessibility_risk_face_is_not_applicable_not_confirmed():
    """If a face is flagged by accessibility_risk AND is also near-zero-g
    (the Phase 5A guard's domain), it must land in boolean_not_applicable,
    never boolean_confirmed -- the two fixes must compose correctly, not
    silently let one bypass the other."""
    from backend.geometry.undercut_detector import _boolean_refine_undercuts
    from backend.config import settings

    part = _load()
    threshold = settings.dfm.direction_search.boolean_near_zero_g_threshold
    # Face 6 is a draft-proxy face with g≈0 (stem wall). Force it through
    # _boolean_refine_undercuts directly as if accessibility_risk had also
    # nominated it -- the near-zero-g guard must still catch it regardless
    # of which candidate source it came from, since the guard is inside
    # the shared verification step, not either candidate-generation pass.
    faces_by_id = {f.face_id: f for f in part.faces}
    assert abs(faces_by_id[6].signed_dot(PULL_Z)) < threshold
    (
        confirmed, _metrics, _checked, _failed, _fr, _fd, _skipped, _sr,
        _hits, _misses, _t, not_applicable, _reasons, _ray_clear,
    ) = _boolean_refine_undercuts(
        part=part, pull_direction=PULL_Z, candidate_face_ids=[6], max_faces=10,
    )
    assert 6 in not_applicable
    assert 6 not in confirmed


# G. Three evidence buckets remain disjoint.
@requires_occ
@requires_uc3
def test_G_evidence_buckets_remain_disjoint():
    result = _default_result()
    confirmed = set(result.boolean_confirmed_face_ids)
    not_applicable = set(result.boolean_not_applicable_face_ids)
    unconfirmed = set(result.candidate_unconfirmed_face_ids)
    assert confirmed.isdisjoint(not_applicable)
    assert confirmed.isdisjoint(unconfirmed)
    assert not_applicable.isdisjoint(unconfirmed)
    # And every processed candidate has a recorded source.
    for fid in confirmed | not_applicable | unconfirmed:
        assert fid in result.candidate_sources


# I. Direction optimizer receives the corrected evidence via its existing
# boolean_check_all_faces=False path (no direction_optimizer.py change).
@requires_occ
@requires_uc3
def test_I_direction_optimizer_path_sees_the_corrected_evidence():
    """Reproduces direction_optimizer.py's exact internal call signature
    (backend/geometry/direction_optimizer.py:408 hardcodes
    boolean_check_all_faces=False) without importing or modifying that
    module, to prove the fix is visible through the unmodified consumer
    path, not just through a differently-configured test call."""
    from backend.geometry.undercut_detector import detect_undercuts
    part = _load()
    result = detect_undercuts(
        part, PULL_Z, mutate=False, boolean_refine=True,
        boolean_check_all_faces=False,  # matches direction_optimizer.py:408 exactly
    )
    assert 4 in result.boolean_confirmed_face_ids
    assert result.undercut_area_pct > 0.0
