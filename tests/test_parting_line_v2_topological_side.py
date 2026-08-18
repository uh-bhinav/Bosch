"""
tests/test_parting_line_v2_topological_side.py
-------------------------------------------------
Phase 4 (D-055): FaceClassification.topological_side.

The Phase 4 forensic audit found that H3's separate_surface() already
determines every ordinary face's cavity/core component membership by pure
graph connectivity, completely independent of that face's own g value --
and that classify_regions() already retains this membership unconditionally
in RegionClassification.cavity_face_ids/core_face_ids, but DISCARDED it when
producing the per-face label for a zero-draft ("ambiguous") face. Measured
directly on real geometry: every one of Part1's 70 and Part3 candidate
110's 95 ambiguous faces already has a known topological side (Part1:
18 cavity / 52 core; Part3: 95 cavity / 0 core; 0 unknown in both cases).

`topological_side` is a PURELY ADDITIVE field: it answers "which side of
the primary parting topology does this face belong to" -- a different
question from `label`, which answers "is this face's own local draft/g
confidently assigned." An "ambiguous"-labelled face having a known
topological_side is the expected, common case, not a contradiction.
`label`, `cavity_face_ids`/`core_face_ids`, `cavity_area_mm2`/
`core_area_mm2`/`ambiguous_area_mm2`, and every H0-H7 gate computation are
UNCHANGED by this phase.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PART1_PATH = REPO_ROOT / "data" / "parts" / "Part1.stp"
PART3_PATH = REPO_ROOT / "data" / "parts" / "Part3.stp"

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _occ_available() -> bool:
    try:
        import OCC  # noqa: F401
        return True
    except ImportError:
        return False


requires_occ = pytest.mark.skipif(not _occ_available(), reason="pythonOCC not installed")
requires_part1 = pytest.mark.skipif(not PART1_PATH.exists(), reason="Part1.stp not present")
requires_part3 = pytest.mark.skipif(not PART3_PATH.exists(), reason="Part3.stp not present")

PULL_Z = (0.0, 0.0, 1.0)


def _make_face(face_id: int, normal, area: float = 100.0):
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


def _cfg():
    """
    A PartingLineV2Settings with face_sample_grid forced below 2. This
    keeps _sample_face_g() on its cheap stored_g fallback path
    (`if not _OCC_AVAILABLE or grid < 2: return stored_g, ...`) instead of
    calling real OCC (`breptools.UVBounds`) on these tests' MagicMock
    occ_face objects -- passing a mock into a real C++ OCC binding doesn't
    raise a clean, catchable Python exception the way a pure-Python mock
    call does, and was observed to hang rather than fail fast. This
    affects only HOW mean_g/min_g/max_g are sampled (here, exactly
    dot(normal, pull_direction) via the stored-normal fallback, still
    fully deterministic and sufficient to exercise every branch these
    tests target) -- it does not change any topological_side logic, which
    depends only on H3 component membership, not on sample_count.
    """
    from backend.config import settings
    import dataclasses

    return dataclasses.replace(settings.dfm.parting_line_v2, face_sample_grid=1)


# ---------------------------------------------------------------------------
# A/B/C/D. Mock-level unit tests -- isolate the exact rule.
# ---------------------------------------------------------------------------

def test_A_ordinary_cavity_side_ambiguous_face_reports_cavity():
    """A face with normal perpendicular to the pull (mean_g ~ 0, so it's
    label=='ambiguous'), whose face_id is in H3's cavity_component, must
    report topological_side=='cavity'."""
    from backend.geometry.parting_line_v2.regions import classify_regions, SeparationResult

    zero_draft = _make_face(0, (1.0, 0.0, 0.0))  # perpendicular to +Z pull -> mean_g = 0
    cavity_seed = _make_face(1, (0.0, 0.0, 1.0))  # +Z normal -> positive g, defines "cavity"
    part = _make_part([zero_draft, cavity_seed])

    separation = SeparationResult(component_count=2, components=(frozenset({0, 1}), frozenset({2})))
    # face_id 2 doesn't exist -- an empty second component is fine, it just
    # means core_component's area-weighted mean is 0 and cavity wins by >=.
    regions = classify_regions(
        part, separation, PULL_Z, loop_face_ids=frozenset(), cfg=_cfg(),
    )
    face0 = next(f for f in regions.faces if f.face_id == 0)
    assert face0.label == "ambiguous"
    assert face0.topological_side == "cavity"


def test_B_ordinary_core_side_ambiguous_face_reports_core():
    """Same shape, but the zero-draft face's component is the one with the
    NEGATIVE area-weighted mean g -- must report topological_side=='core'."""
    from backend.geometry.parting_line_v2.regions import classify_regions, SeparationResult

    zero_draft = _make_face(0, (1.0, 0.0, 0.0))  # perpendicular -> mean_g = 0
    core_seed = _make_face(1, (0.0, 0.0, -1.0))  # -Z normal -> negative g, defines "core"
    cavity_seed = _make_face(2, (0.0, 0.0, 1.0))  # +Z normal, separate component -> "cavity"
    part = _make_part([zero_draft, core_seed, cavity_seed])

    separation = SeparationResult(
        component_count=2,
        components=(frozenset({0, 1}), frozenset({2})),
    )
    regions = classify_regions(
        part, separation, PULL_Z, loop_face_ids=frozenset(), cfg=_cfg(),
    )
    face0 = next(f for f in regions.faces if f.face_id == 0)
    assert face0.label == "ambiguous"
    assert face0.topological_side == "core"


def test_C_face_in_neither_component_reports_unknown():
    """Defensive fallback: a face reaching classification without landing in
    EITHER H3 component (not producible by a real separate_surface() call --
    every usable face lands in exactly one of exactly-two components by
    construction -- but classify_regions() must not silently guess "cavity"
    or "core" if this invariant is ever violated)."""
    from backend.geometry.parting_line_v2.regions import classify_regions, SeparationResult

    orphan = _make_face(0, (1.0, 0.0, 0.0))
    other = _make_face(1, (0.0, 0.0, 1.0))
    part = _make_part([orphan, other])

    # Hand-crafted SeparationResult: exactly 2 components (so the len==2
    # precondition passes), but face_id 0 is in NEITHER of them.
    separation = SeparationResult(
        component_count=2,
        components=(frozenset({1}), frozenset({99})),
    )
    regions = classify_regions(
        part, separation, PULL_Z, loop_face_ids=frozenset(), cfg=_cfg(),
    )
    face0 = next(f for f in regions.faces if f.face_id == 0)
    assert face0.topological_side == "unknown"


def test_D_split_face_topological_side_mirrors_label_exactly():
    """A face the loop cuts through (in BOTH cavity_component and
    core_component) gets label=='split' -- topological_side must mirror
    that exactly, never computed independently."""
    from backend.geometry.parting_line_v2.regions import classify_regions, SeparationResult

    split_face = _make_face(0, (1.0, 0.0, 0.0), area=100.0)
    cavity_seed = _make_face(1, (0.0, 0.0, 1.0))
    core_seed = _make_face(2, (0.0, 0.0, -1.0))
    part = _make_part([split_face, cavity_seed, core_seed])

    separation = SeparationResult(
        component_count=2,
        # face_id 0 in BOTH components -> split.
        components=(frozenset({0, 1}), frozenset({0, 2})),
    )
    regions = classify_regions(
        part, separation, PULL_Z, loop_face_ids=frozenset(), cfg=_cfg(),
    )
    face0 = next(f for f in regions.faces if f.face_id == 0)
    assert face0.label == "split"
    assert face0.topological_side == "split"


def test_ordinary_cavity_and_core_labels_also_report_matching_topological_side():
    """Sanity: a face confidently labelled "cavity" or "core" (not
    ambiguous) must have topological_side equal to that same label -- the
    two fields must never disagree for a non-split face."""
    from backend.geometry.parting_line_v2.regions import classify_regions, SeparationResult

    cavity_face = _make_face(0, (0.0, 0.0, 1.0))  # strong +Z -> confidently "cavity"
    core_face = _make_face(1, (0.0, 0.0, -1.0))  # strong -Z -> confidently "core"
    part = _make_part([cavity_face, core_face])

    separation = SeparationResult(component_count=2, components=(frozenset({0}), frozenset({1})))
    regions = classify_regions(
        part, separation, PULL_Z, loop_face_ids=frozenset(), cfg=_cfg(),
    )
    f0 = next(f for f in regions.faces if f.face_id == 0)
    f1 = next(f for f in regions.faces if f.face_id == 1)
    assert f0.label == "cavity" and f0.topological_side == "cavity"
    assert f1.label == "core" and f1.topological_side == "core"


def test_h3_failure_produces_no_faces_at_all_topological_side_never_constructed():
    """When H3 doesn't produce exactly 2 components, classify_regions()
    returns immediately with faces=() -- topological_side is never even
    instantiated for that (non-)result, which is a DIFFERENT situation from
    test_C's per-face fallback."""
    from backend.geometry.parting_line_v2.regions import classify_regions, SeparationResult

    part = _make_part([_make_face(0, (1.0, 0.0, 0.0))])
    separation = SeparationResult(component_count=1, components=(frozenset({0}),))
    regions = classify_regions(
        part, separation, PULL_Z, loop_face_ids=frozenset(), cfg=_cfg(),
    )
    assert regions.faces == ()
    assert regions.cavity_face_ids == frozenset()
    assert regions.core_face_ids == frozenset()


def test_to_dict_serializes_topological_side():
    from backend.geometry.parting_line_v2.regions import classify_regions, SeparationResult

    zero_draft = _make_face(0, (1.0, 0.0, 0.0))
    cavity_seed = _make_face(1, (0.0, 0.0, 1.0))
    part = _make_part([zero_draft, cavity_seed])
    separation = SeparationResult(component_count=2, components=(frozenset({0, 1}), frozenset({99})))
    regions = classify_regions(part, separation, PULL_Z, loop_face_ids=frozenset(), cfg=_cfg())
    d = regions.to_dict()
    face0_dict = next(f for f in d["faces"] if f["face_id"] == 0)
    assert face0_dict["topological_side"] == "cavity"
    assert face0_dict["label"] == "ambiguous"


# ---------------------------------------------------------------------------
# Real-fixture characterization: Part1, Part3 candidate 110.
# ---------------------------------------------------------------------------

def _part1_result():
    from backend.config import settings
    from backend.geometry.parting_line_v2 import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line
    from backend.geometry.step_loader import load_step

    part = load_step(str(PART1_PATH))
    return analyse_parting_line(
        part, PullDirectionInput(PULL_Z, "fixture"), cfg=settings.dfm.parting_line_v2,
        undercuts=UndercutInput.empty(),
    )


def _part3_candidate_110_result():
    from backend.config import settings
    from backend.geometry.parting_line_v2 import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.contracts import (
        CorePinFaceRef, DelegatedSecondaryAction, DelegationEvidence,
    )
    from backend.geometry.parting_line_v2.engine import analyse_parting_line
    from backend.geometry.step_loader import load_step

    def make_delegation(face_ids, direction, note):
        return DelegatedSecondaryAction(
            face_ids=frozenset(face_ids), movement_direction=direction, movement_type="radial_slide",
            evidence=DelegationEvidence(source="manual_engineering", note=note),
        )

    part = load_step(str(PART3_PATH))
    refs = (CorePinFaceRef(35, PULL_Z, "straight coaxial through-bore"),)
    valid = (
        make_delegation(range(0, 17), (1.0, 0.0, 0.0), "original rib stack, radial outward +X"),
        make_delegation(range(18, 35), (-1.0, 0.0, 0.0), "mirror rib stack, radial outward -X"),
    )
    return analyse_parting_line(
        part, PullDirectionInput(PULL_Z, "fixture"), cfg=settings.dfm.parting_line_v2,
        undercuts=UndercutInput.empty(), core_pin_face_refs=refs, delegations=valid,
    )


@requires_occ
@requires_part1
def test_part1_ambiguous_topological_side_breakdown_matches_measured_baseline():
    result = _part1_result()
    assert result.selected is not None
    assert result.selected.candidate_id == 49
    regions = result.regions
    ambiguous = [f for f in regions.faces if f.label == "ambiguous"]
    assert len(ambiguous) == 70
    cavity_side = [f for f in ambiguous if f.topological_side == "cavity"]
    core_side = [f for f in ambiguous if f.topological_side == "core"]
    unknown_side = [f for f in ambiguous if f.topological_side == "unknown"]
    assert len(cavity_side) == 18
    assert len(core_side) == 52
    assert len(unknown_side) == 0

    # Frozen values (Phase 4B / D-050) unchanged by this purely-additive field.
    assert regions.cavity_area_fraction_of_confident == pytest.approx(0.2314, abs=0.001)
    assert regions.core_area_fraction_of_confident == pytest.approx(0.7686, abs=0.001)
    assert regions.ambiguous_area_fraction == pytest.approx(0.4557, abs=0.001)
    assert not any(f.label == "split" for f in regions.faces)


@requires_occ
@requires_part3
def test_part3_candidate_110_ambiguous_topological_side_breakdown_matches_measured_baseline():
    result = _part3_candidate_110_result()
    assert result.selected is not None
    assert result.selected.candidate_id == 110
    regions = result.regions
    ambiguous = [f for f in regions.faces if f.label == "ambiguous"]
    assert len(ambiguous) == 95
    cavity_side = [f for f in ambiguous if f.topological_side == "cavity"]
    core_side = [f for f in ambiguous if f.topological_side == "core"]
    unknown_side = [f for f in ambiguous if f.topological_side == "unknown"]
    assert len(cavity_side) == 95
    assert len(core_side) == 0
    assert len(unknown_side) == 0

    # Frozen Phase 3A/4A values, unchanged by this purely-additive field.
    assert len(regions.cavity_face_ids) == 410
    assert regions.core_face_ids == frozenset({35, 36, 37, 320, 321})
    assert regions.ambiguous_area_fraction == pytest.approx(0.3271748971395147, rel=1e-6)

    face35 = next(f for f in regions.faces if f.face_id == 35)
    assert face35.label == "split"
    assert face35.topological_side == "split"
    assert face35.cavity_area_mm2 == pytest.approx(1302.33, abs=1.0)
    assert face35.core_area_mm2 == pytest.approx(130.23, abs=1.0)
