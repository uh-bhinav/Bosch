"""
tests/test_parting_line_v2_face_g_stats_cache.py
-------------------------------------------------
O6 (2026-08-17): classify_regions() used to recompute its per-face
UV-grid g-sampling (_sample_face_g) from scratch on EVERY H3-topologically
-valid candidate loop, even though the result depends only on
(part, pull_direction, grid) -- never on the candidate/separation. O5's
forensic measurement found this 90-96% of analyse_parting_line's total
wall time on both Part1 and Part3 (real, unauthorized, and authorized
cases alike). O6 hoists it into `regions._sample_all_faces_g`, computed
once per analyse_parting_line() call and threaded through evaluate_gates()
into classify_regions() via the new `face_g_stats` parameter.

This module proves, at the unit level (no real OCC geometry required --
grid=1 forces _sample_face_g's deterministic non-OCC fallback path,
exercising the exact same code either way):

  A. value identity -- the precomputed helper and the pre-O6 inline loop
     produce byte-identical per-face statistics, AND classify_regions()
     called with vs. without a precomputed face_g_stats produces a
     byte-identical RegionClassification.
  B. call count -- _sample_face_g is invoked once per face for the
     precomputation, and NOT again inside classify_regions() when a
     precomputed face_g_stats is supplied.
  C. backward compatibility -- classify_regions() omitting face_g_stats
     still works and matches the precomputed-path result exactly.

Real Part1/Part3 frozen-behavior regression (this phase's D/E) and timing
(F) are covered by re-running the EXISTING real-geometry suites this
project already has for exactly these invariants
(tests/test_parting_line_v2_region_balance.py's candidate-110 fixture,
tests/test_direction_optimizer_parting_line_feasibility.py's Part1/Part3
single-direction feasibility checks) rather than duplicating them here.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _make_face(face_id: int, normal: tuple[float, float, float], area: float = 100.0):
    from backend.models.geometry_models import FaceData

    return FaceData(
        face_id=face_id,
        occ_face=MagicMock(),
        surface_type="Plane",
        normal=normal,
        centroid=(0.0, 0.0, 0.0),
        area=area,
        u_range=(0.0, 1.0),
        v_range=(0.0, 1.0),
        is_reversed=False,
        normal_valid=True,
    )


def _make_part(faces):
    from backend.models.geometry_models import BoundingBox, PartGeometry

    return PartGeometry(
        source_file="mock.stp",
        occ_shape=MagicMock(),
        faces=faces,
        bounding_box=BoundingBox(0.0, 0.0, 0.0, 10.0, 10.0, 10.0),
        face_count=len(faces),
        solid_count=1,
        shell_count=1,
    )


PULL_Z = (0.0, 0.0, 1.0)
#: grid=1 forces _sample_face_g's deterministic "stored_g" fallback (its
#: own `grid < 2` branch) -- no real OCC surface evaluation needed, so
#: this test suite runs identically with or without pythonOCC installed,
#: while still exercising the exact production code path (not a stub).
GRID = 1


def _make_cfg(grid=GRID):
    return SimpleNamespace(silhouette_epsilon=1e-3, face_sample_grid=grid)


def _make_separation(components):
    from backend.geometry.parting_line_v2.regions import SeparationResult

    return SeparationResult(component_count=len(components), components=tuple(components))


# ---------------------------------------------------------------------------
# TEST A -- value identity
# ---------------------------------------------------------------------------

def test_a_sample_all_faces_g_matches_old_inline_loop_per_face():
    from backend.geometry.parting_line_v2.regions import _sample_all_faces_g, _sample_face_g

    faces = [
        _make_face(1, (0.0, 0.0, 1.0)),
        _make_face(2, (0.0, 0.0, -1.0)),
        _make_face(3, (1.0, 0.0, 0.0)),
        _make_face(4, (0.7071067811865476, 0.0, 0.7071067811865476)),
    ]
    faces_by_id = {f.face_id: f for f in faces}

    # The exact pre-O6 inline loop, reproduced verbatim as the reference.
    old_style = {
        fid: _sample_face_g(face, PULL_Z, GRID)
        for fid, face in faces_by_id.items() if face.normal_valid
    }
    new_style = _sample_all_faces_g(faces_by_id, PULL_Z, GRID)

    assert new_style == old_style
    for fid in faces_by_id:
        assert new_style[fid] == old_style[fid], f"face {fid} statistics diverged"


def test_a_classify_regions_with_and_without_precomputed_stats_is_byte_identical():
    from backend.geometry.parting_line_v2.regions import _sample_all_faces_g, classify_regions

    faces = [
        _make_face(1, (0.0, 0.0, 1.0)),
        _make_face(2, (0.0, 0.0, 1.0)),
        _make_face(3, (0.0, 0.0, -1.0)),
        _make_face(4, (0.0, 0.0, -1.0)),
    ]
    part = _make_part(faces)
    cfg = _make_cfg()
    separation = _make_separation([frozenset({1, 2}), frozenset({3, 4})])

    without_precompute = classify_regions(
        part, separation, PULL_Z, loop_face_ids=frozenset(), cfg=cfg,
    )
    precomputed = _sample_all_faces_g(
        {f.face_id: f for f in faces}, PULL_Z, cfg.face_sample_grid,
    )
    with_precompute = classify_regions(
        part, separation, PULL_Z, loop_face_ids=frozenset(), cfg=cfg,
        face_g_stats=precomputed,
    )

    assert with_precompute.cavity_face_ids == without_precompute.cavity_face_ids
    assert with_precompute.core_face_ids == without_precompute.core_face_ids
    assert with_precompute.to_dict() == without_precompute.to_dict()


# ---------------------------------------------------------------------------
# TEST B -- call count
# ---------------------------------------------------------------------------

def test_b_precomputed_stats_prevent_resampling_inside_classify_regions(monkeypatch):
    """
    With a precomputed face_g_stats supplied, classify_regions() must not
    call _sample_face_g again -- the whole point of O6.
    """
    import backend.geometry.parting_line_v2.regions as regions_mod

    faces = [
        _make_face(1, (0.0, 0.0, 1.0)),
        _make_face(2, (0.0, 0.0, 1.0)),
        _make_face(3, (0.0, 0.0, -1.0)),
        _make_face(4, (0.0, 0.0, -1.0)),
    ]
    part = _make_part(faces)
    cfg = _make_cfg()
    separation = _make_separation([frozenset({1, 2}), frozenset({3, 4})])

    call_count = {"n": 0}
    real_sample_face_g = regions_mod._sample_face_g

    def counting_sample_face_g(*args, **kwargs):
        call_count["n"] += 1
        return real_sample_face_g(*args, **kwargs)

    precomputed = regions_mod._sample_all_faces_g(
        {f.face_id: f for f in faces}, PULL_Z, cfg.face_sample_grid,
    )
    assert call_count["n"] == 0  # precompute happened before the monkeypatch below

    monkeypatch.setattr(regions_mod, "_sample_face_g", counting_sample_face_g)

    # Call classify_regions() for THREE separate "candidates" (simulating
    # three H3-passing loops in one analyse_parting_line() call), all
    # sharing the one precomputed face_g_stats -- exactly like
    # engine.analyse_parting_line's three evaluate_gates() call sites.
    for _ in range(3):
        regions_mod.classify_regions(
            part, separation, PULL_Z, loop_face_ids=frozenset(), cfg=cfg,
            face_g_stats=precomputed,
        )

    assert call_count["n"] == 0, (
        f"classify_regions() called _sample_face_g {call_count['n']} times "
        "despite a precomputed face_g_stats being supplied"
    )


def test_b_omitting_precomputed_stats_still_samples_once_per_face_per_call():
    """
    Backward-compat control: WITHOUT face_g_stats, classify_regions() must
    still sample every normal_valid face exactly once per call (the
    pre-O6 behaviour) -- confirming test B's counter methodology itself is
    sound (it would have caught the old N-per-candidate redundancy).
    """
    import backend.geometry.parting_line_v2.regions as regions_mod

    faces = [
        _make_face(1, (0.0, 0.0, 1.0)),
        _make_face(2, (0.0, 0.0, 1.0)),
        _make_face(3, (0.0, 0.0, -1.0)),
        _make_face(4, (0.0, 0.0, -1.0)),
    ]
    part = _make_part(faces)
    cfg = _make_cfg()
    separation = _make_separation([frozenset({1, 2}), frozenset({3, 4})])

    call_count = {"n": 0}
    real_sample_face_g = regions_mod._sample_face_g

    def counting_sample_face_g(*args, **kwargs):
        call_count["n"] += 1
        return real_sample_face_g(*args, **kwargs)

    monkeypatch_target = regions_mod._sample_face_g
    regions_mod._sample_face_g = counting_sample_face_g
    try:
        regions_mod.classify_regions(
            part, separation, PULL_Z, loop_face_ids=frozenset(), cfg=cfg,
        )
    finally:
        regions_mod._sample_face_g = monkeypatch_target

    assert call_count["n"] == len(faces)


# ---------------------------------------------------------------------------
# TEST C -- backward compatibility
# ---------------------------------------------------------------------------

def test_c_classify_regions_without_new_parameter_still_works():
    from backend.geometry.parting_line_v2.regions import classify_regions

    faces = [
        _make_face(1, (0.0, 0.0, 1.0)),
        _make_face(2, (0.0, 0.0, -1.0)),
    ]
    part = _make_part(faces)
    cfg = _make_cfg()
    separation = _make_separation([frozenset({1}), frozenset({2})])

    result = classify_regions(part, separation, PULL_Z, loop_face_ids=frozenset(), cfg=cfg)

    assert result.cavity_face_ids | result.core_face_ids == {1, 2}
    assert result.warnings == ()


def test_c_evaluate_gates_signature_accepts_optional_face_g_stats():
    import inspect
    from backend.geometry.parting_line_v2.gates import evaluate_gates

    params = inspect.signature(evaluate_gates).parameters
    assert "face_g_stats" in params
    assert params["face_g_stats"].default is None
