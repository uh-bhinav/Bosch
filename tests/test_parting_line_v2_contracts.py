"""
tests/test_parting_line_v2_contracts.py
---------------------------------------
P0 acceptance tests for the v2 parting-line engine.

These test **contracts and invariants**, not algorithms — there is no algorithm
yet. Their job is to make the plan's structural rules impossible to violate
silently, because every rule here exists to stop a specific tempting shortcut:

* the ``side_core`` import ban stops "while we're here, just call Stage 4";
* the surface-provider ban stops "the split plane is right there, use it";
* the confidence-field ban stops "backfill it so the UI keeps working";
* the ``CurveSegment`` backing requirement stops the levitating parting line.

A rule documented only in Markdown does not survive contact with any of those.
"""

from __future__ import annotations

import ast
import json
import math
from pathlib import Path

import pytest

from backend.geometry.parting_line_v2 import (
    STAGE_ORDER,
    CandidateScore,
    ContractViolation,
    CurveSegment,
    EdgeBacking,
    FaceBacking,
    FeasibilityReport,
    OnSurfaceReport,
    PullDirectionInput,
    SideActionReferral,
    StageTimer,
    StageTimings,
    UndercutInput,
    percentile,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
V2_PACKAGE = REPO_ROOT / "backend" / "geometry" / "parting_line_v2"
SYNTHETIC_DIR = REPO_ROOT / "data" / "fixtures" / "synthetic"


def _v2_modules() -> list[Path]:
    return sorted(V2_PACKAGE.glob("*.py"))


def _imported_names(path: Path) -> set[str]:
    """Every module name imported by ``path``, via AST (no import side effects)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


# ---------------------------------------------------------------------------
# Module-boundary rules (plan §10.2 rule 1, §12.8)
# ---------------------------------------------------------------------------

def test_v2_package_exists_with_modules():
    modules = _v2_modules()
    assert modules, "parting_line_v2 package has no modules."
    names = {p.name for p in modules}
    assert {"__init__.py", "types.py", "contracts.py", "timing.py"} <= names


@pytest.mark.parametrize("module_path", _v2_modules(), ids=lambda p: p.name)
def test_no_module_imports_side_core(module_path: Path):
    """
    Plan §12.8: H5 emits a SideActionReferral; it NEVER routes during P0-P6.

    Calling Stage 4 would couple v2's candidate filter to a module with its own
    Boolean failure modes and tolerances, widening the milestone well past
    "make the parting line correct".
    """
    offenders = {n for n in _imported_names(module_path) if "side_core" in n}
    assert not offenders, (
        f"{module_path.name} imports side_core ({sorted(offenders)}). "
        "v2 emits SideActionReferral only — see plan §12.8 and H5 rule 5."
    )


@pytest.mark.parametrize("module_path", _v2_modules(), ids=lambda p: p.name)
def test_generation_and_ranking_never_import_a_surface_provider(module_path: Path):
    """
    Plan §10.2 rule 1: the selected parting line is a real geometric result,
    independent of how the mold is currently split.

    ``contracts.py`` DEFINES the Protocol, which is allowed and necessary; no
    generation/filtering/ranking module may import an implementation of it.
    """
    if module_path.name in {"contracts.py", "__init__.py"}:
        return
    offenders = {
        n for n in _imported_names(module_path)
        if "split_tool" in n or "core_cavity" in n or "PartingSurfaceProvider" in n
    }
    assert not offenders, (
        f"{module_path.name} imports a surface/split concern ({sorted(offenders)}). "
        "Candidate generation and ranking must not depend on the split tool."
    )


@pytest.mark.parametrize("module_path", _v2_modules(), ids=lambda p: p.name)
def test_no_module_imports_the_direction_optimizer(module_path: Path):
    """
    The pull direction is an EXTERNAL INPUT, never something this module
    derives.

    The optimizer is teammate-owned and currently under repair. If v2 could
    call it — even as a fallback — then "is our parting line correct?" and "is
    that direction correct?" would be permanently confounded, and an upstream
    regression would surface as an apparent bug in this module.

    ``contracts.from_optimizer_result`` adapts an optimizer RESULT a caller
    passes in. It is duck-typed and imports nothing, which is the distinction
    that matters: consuming a value is fine, reaching for the module is not.
    """
    offenders = {
        n for n in _imported_names(module_path)
        if "direction_optimizer" in n or "optimize_mold_direction" in n
    }
    assert not offenders, (
        f"{module_path.name} imports the direction optimizer ({sorted(offenders)}). "
        "The direction is an external input; this module must never derive it."
    )


def test_optimizer_directions_are_not_correctness_evidence():
    """
    A direction's provenance is recorded and load-bearing, not decorative.

    While the upstream optimizer is under repair, only explicitly specified
    directions can serve as evidence that THIS algorithm is right.
    """
    for source in ("fixture", "manual", "user_override"):
        assert PullDirectionInput((0, 0, 1), source).is_correctness_evidence
    assert not PullDirectionInput((0, 0, 1), "optimizer").is_correctness_evidence


def test_engine_signature_requires_an_explicit_direction():
    """There is no Vec3 overload and no default — a direction must be given."""
    import inspect

    from backend.geometry.parting_line_v2.engine import analyse_parting_line

    parameters = inspect.signature(analyse_parting_line).parameters
    assert parameters["pull_direction"].default is inspect.Parameter.empty
    assert parameters["pull_direction"].annotation == "PullDirectionInput"


def test_no_confidence_or_readiness_fields_anywhere_in_v2():
    """
    Plan §12.7: no probability-shaped output without labelled outcomes, and we
    have none — Bosch has not disclosed expected solutions.

    ``upstream_confidence`` on PullDirectionInput is the one permitted use: it
    carries a teammate's number through for provenance and is never computed,
    relabelled, or reported by v2 as its own.
    """
    banned = {"confidence", "readiness", "readiness_score", "confidence_score"}
    for module_path in _v2_modules():
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                assert node.target.id not in banned, (
                    f"{module_path.name} declares a banned field "
                    f"'{node.target.id}'. See plan §12.7."
                )


# ---------------------------------------------------------------------------
# D-001 / H0.1 — provenance is structural, not optional
# ---------------------------------------------------------------------------

def test_curve_segment_requires_a_backing():
    """A segment with no OCC backing must be unconstructable, not merely invalid."""
    with pytest.raises(TypeError):
        CurveSegment(0, ((0, 0, 0), (1, 0, 0)), kind="silhouette")  # type: ignore[call-arg]


def test_face_backed_segment_requires_one_uv_per_point():
    """
    Every face-backed point must be recoverable as S(u, v) for gate H0.3.
    A UV list that does not match the point list is exactly the silent drift
    H0 exists to catch.
    """
    with pytest.raises(ValueError, match="UV pair"):
        CurveSegment(
            0,
            ((0, 0, 0), (1, 0, 0), (2, 0, 0)),
            FaceBacking(7, ((0.0, 0.0), (0.5, 0.0))),
            "silhouette",
        )


def test_face_backed_segment_accepts_matching_uv():
    segment = CurveSegment(
        0,
        ((0, 0, 0), (1, 0, 0)),
        FaceBacking(7, ((0.0, 0.0), (0.5, 0.0))),
        "silhouette",
    )
    assert segment.provenance == "face"
    assert segment.to_dict()["backing"]["face_id"] == 7


def test_segment_rejects_degenerate_point_count():
    with pytest.raises(ValueError, match="at least 2 points"):
        CurveSegment(0, ((0, 0, 0),), EdgeBacking(1, 0.0, 1.0), "silhouette")


def test_provenance_mix_counts_both_tracks():
    from backend.geometry.parting_line_v2 import PartingLoopCandidate

    edge_seg = CurveSegment(0, ((0, 0, 0), (1, 0, 0)), EdgeBacking(1, 0.0, 1.0), "silhouette")
    face_seg = CurveSegment(
        1, ((1, 0, 0), (2, 0, 0)), FaceBacking(3, ((0.0, 0.0), (1.0, 0.0))), "silhouette"
    )
    candidate = PartingLoopCandidate(
        candidate_id=0,
        segments=(edge_seg, face_seg),
        points=((0, 0, 0), (1, 0, 0), (2, 0, 0)),
        is_closed=False,
        discovered_by="single_cycle",
    )
    assert candidate.provenance_mix == {"edge": 1, "face": 1}


# ---------------------------------------------------------------------------
# D-003 — inputs validate and refuse to default
# ---------------------------------------------------------------------------

def test_pull_direction_is_normalized_on_construction():
    d = PullDirectionInput((0.0, 0.0, 7.0), "fixture")
    assert d.direction == pytest.approx((0.0, 0.0, 1.0))
    assert math.isclose(sum(c * c for c in d.direction), 1.0, abs_tol=1e-12)


@pytest.mark.parametrize("bad", [
    (0.0, 0.0, 0.0),
    (float("nan"), 0.0, 1.0),
    (float("inf"), 0.0, 1.0),
])
def test_pull_direction_rejects_degenerate_vectors(bad):
    """
    No silent fallback to +Z. v1's classify_core_cavity defaults to +Z with a
    warning (core_cavity.py:137-139); a warning nobody blocks on is how a whole
    analysis gets computed against the wrong axis while every metric reads fine.
    """
    with pytest.raises(ContractViolation):
        PullDirectionInput(bad, "fixture")


def test_pull_direction_rejects_wrong_arity():
    with pytest.raises(ContractViolation):
        PullDirectionInput((0.0, 1.0), "fixture")  # type: ignore[arg-type]


def test_undercut_input_empty_is_legitimate():
    empty = UndercutInput.empty()
    assert empty.undercut_face_ids == frozenset()
    assert empty.features == ()


def test_undercut_adapter_rejects_a_result_without_the_expected_field():
    class Bogus:
        pass

    with pytest.raises(ContractViolation, match="undercut_face_ids"):
        UndercutInput.from_detection_result(Bogus())


def test_undercut_adapter_accepts_none_as_empty():
    assert UndercutInput.from_detection_result(None).features == ()


def test_undercut_validate_against_rejects_unknown_face_ids():
    class FakeFace:
        def __init__(self, fid): self.face_id = fid

    class FakePart:
        faces = [FakeFace(0), FakeFace(1)]

    context = UndercutInput(undercut_face_ids=frozenset({1, 99}))
    with pytest.raises(ContractViolation, match="not present"):
        context.validate_against(FakePart())  # type: ignore[arg-type]


def test_undercut_features_touching():
    from backend.geometry.parting_line_v2 import UndercutFeatureRef

    context = UndercutInput(
        undercut_face_ids=frozenset({1, 2, 5}),
        features=(
            UndercutFeatureRef(0, frozenset({1, 2}), "critical"),
            UndercutFeatureRef(1, frozenset({5}), "minor"),
        ),
    )
    assert {f.feature_id for f in context.features_touching(frozenset({2}))} == {0}
    assert context.features_touching(frozenset({77})) == ()


# ---------------------------------------------------------------------------
# H5 — referral is a finding, never infeasibility
# ---------------------------------------------------------------------------

def test_h5_referral_is_reported_as_requiring_a_side_action_not_as_failure():
    referral = SideActionReferral(
        feature_ids=(3,), conflicting_segment_ids=(11, 12), conflict_length_mm=4.2
    )
    report = FeasibilityReport(
        passed=False, failed_gate="H5",
        reason="requires_side_action", referral=referral,
    )
    assert report.requires_side_action
    assert report.outcome == "referred_to_side_action"
    assert "impossible" not in report.reason.lower()
    assert "infeasible" not in report.reason.lower()


def test_rejection_without_referral_is_a_plain_rejection():
    report = FeasibilityReport(
        passed=False, failed_gate="H3",
        reason="partitions the part into 3 regions",
    )
    assert report.outcome == "rejected"
    assert not report.requires_side_action


def test_feasible_report_outcome():
    assert FeasibilityReport(passed=True).outcome == "feasible"


# ---------------------------------------------------------------------------
# §8 — lexicographic ranking, not a weighted sum
# ---------------------------------------------------------------------------

def _score(**kw) -> CandidateScore:
    base = dict(
        coverage=0.5, undercut_proximity=0.5, pull_axis_span_mm=5.0,
        ambiguous_area_fraction=0.1, excess_turning=0.1, length_3d_mm=100.0,
        stable_id="aaa",
    )
    base.update(kw)
    return CandidateScore(**base)  # type: ignore[arg-type]


def test_coverage_dominates_every_lower_tier():
    """T1 is Nee's maximum-contour rule and outranks tidiness — the Bug-H fix."""
    big_but_messy = _score(coverage=0.95, excess_turning=0.9, length_3d_mm=999.0)
    small_but_tidy = _score(coverage=0.20, excess_turning=0.0, length_3d_mm=10.0)
    assert max([big_but_messy, small_but_tidy], key=lambda s: s.sort_key()) is big_but_messy


def test_lower_tiers_break_ties_in_order():
    a = _score(coverage=0.5, undercut_proximity=0.1)
    b = _score(coverage=0.5, undercut_proximity=0.9)
    assert max([a, b], key=lambda s: s.sort_key()) is a  # lower proximity wins


def test_stable_id_makes_exact_ties_deterministic():
    """
    Fixture F14 (mirror-symmetric) produces exactly equivalent loops; T7 must
    break the tie the same way on every run.
    """
    a, b = _score(stable_id="aaa"), _score(stable_id="bbb")
    assert max([a, b], key=lambda s: s.sort_key()) is b
    assert max([b, a], key=lambda s: s.sort_key()) is b  # order-independent


def test_score_has_no_single_headline_number():
    assert not hasattr(CandidateScore, "total")
    assert "confidence" not in CandidateScore.__dataclass_fields__


def test_coverage_exactness_is_reported():
    """
    §8.1: the cheap Cauchy denominator is an UPPER BOUND on non-convex parts,
    making coverage a conservative under-estimate. Callers must be able to tell
    which denominator was used.
    """
    assert _score().coverage_is_exact is False


# ---------------------------------------------------------------------------
# §12.5 — timing is a result field
# ---------------------------------------------------------------------------

def test_stage_timer_records_and_accumulates():
    timings = StageTimings()
    timer = StageTimer(timings)
    for _ in range(3):
        with timer("track_a"):
            pass
    assert timings.call_counts["track_a"] == 3
    assert timings.ran("track_a")
    assert not timings.ran("track_b")


def test_stage_timer_records_even_when_the_body_raises():
    """A stage that blew up slowly is exactly the one worth seeing."""
    timings = StageTimings()
    timer = StageTimer(timings)
    with pytest.raises(RuntimeError):
        with timer("filter"):
            raise RuntimeError("boom")
    assert timings.ran("filter")


def test_stages_that_never_ran_are_absent_not_zero():
    """'Did not run' and 'ran instantly' are different facts."""
    timings = StageTimings()
    StageTimings.record(timings, "load", 1.0)
    payload = timings.to_dict()
    assert [s["stage"] for s in payload["stages"]] == ["load"]
    assert "track_b" in payload["stages_not_run"]


def test_stage_order_is_the_full_pipeline():
    assert STAGE_ORDER[0] == "load"
    assert "track_a" in STAGE_ORDER and "track_b" in STAGE_ORDER
    assert len(set(STAGE_ORDER)) == len(STAGE_ORDER)


@pytest.mark.parametrize("q,expected", [(0.0, 1.0), (0.5, 3.0), (1.0, 5.0)])
def test_percentile(q, expected):
    assert percentile([5.0, 1.0, 3.0, 2.0, 4.0], q) == pytest.approx(expected)


def test_percentile_empty_and_bounds():
    assert percentile([], 0.5) == 0.0
    with pytest.raises(ValueError):
        percentile([1.0], 1.5)


# ---------------------------------------------------------------------------
# H0 report
# ---------------------------------------------------------------------------

def test_on_surface_not_run_is_a_failure_not_a_pass():
    """An unevaluated invariant must never read as a satisfied one."""
    report = OnSurfaceReport.not_run()
    assert report.passed is False
    assert report.to_dict()["passed"] is False


# ---------------------------------------------------------------------------
# Fixture corpus integrity (plan P0 exit gate)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not (SYNTHETIC_DIR / "manifest.json").exists(),
    reason="fixtures not generated; run scripts/generate_fixtures.py",
)
def test_fixture_manifest_is_complete_and_files_exist():
    manifest = json.loads((SYNTHETIC_DIR / "manifest.json").read_text())
    fixtures = manifest["fixtures"]
    assert len(fixtures) == 15, f"expected 15 synthetic fixtures, got {len(fixtures)}"

    ids = [f["fixture_id"] for f in fixtures]
    # F15/F16 are the two REAL parts and live in data/parts/, so the synthetic
    # ids run F1..F14 then jump to F17 (added during P1 to cover Track B).
    assert ids == [f"F{i}" for i in range(1, 15)] + ["F17"], f"unexpected ids: {ids}"

    for fixture in fixtures:
        path = SYNTHETIC_DIR / fixture["filename"]
        assert path.exists() and path.stat().st_size > 0, f"{fixture['fixture_id']} missing"
        for key in ("targets", "expected", "p1_expectation", "analytic", "stats"):
            assert fixture.get(key) not in (None, "", {}), \
                f"{fixture['fixture_id']} missing '{key}'"


@pytest.mark.skipif(
    not (SYNTHETIC_DIR / "manifest.json").exists(), reason="fixtures not generated"
)
def test_track_b_only_fixtures_are_marked_to_fail_at_p1():
    """
    Only F3, F4 and F17 have no edge-based silhouette, so only these three must
    report no feasible candidate at Level 0 rather than a plausible-looking
    wrong answer.

    F6 and F7 were originally listed here and P1 measurement PROVED THAT WRONG:
    F6's fillets span g in [0,1] and F7's loft faces are all g>0, so both only
    touch zero at a face BOUNDARY, where Track A already finds an edge. The
    real criterion is whether g CHANGES SIGN inside a face, not whether the
    face is curved. F17 was added to cover the case they do not.
    """
    manifest = json.loads((SYNTHETIC_DIR / "manifest.json").read_text())
    by_id = {f["fixture_id"]: f for f in manifest["fixtures"]}
    for fixture_id in ("F3", "F4", "F17"):
        assert by_id[fixture_id]["p1_expectation"] == "fail_loudly", (
            f"{fixture_id} must be expected to fail loudly at Level 0 — it is a "
            "face-interior silhouette that Track A cannot see."
        )


def test_fixtures_are_not_written_into_data_parts():
    """CLAUDE.md invariant #2: data/parts/ is read-only input."""
    assert SYNTHETIC_DIR.resolve() != (REPO_ROOT / "data" / "parts").resolve()
    assert (REPO_ROOT / "data" / "parts").resolve() not in SYNTHETIC_DIR.resolve().parents


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def test_engine_flag_defaults_to_v1():
    """v1 stays the default until v2 wins on measured metrics (plan P6)."""
    from backend.config import settings
    assert settings.dfm.parting_line.engine == "v1"


def test_v2_thresholds_load_from_config():
    from backend.config import settings
    v2 = settings.dfm.parting_line_v2
    assert v2.min_coverage_ratio == 0.50, "kappa_min is provisional 0.50 (plan §7.0)"
    assert v2.allow_smoothed_as_geometry is False, (
        "smoothed curves must be display-only by default (plan §9.5 rule 5)"
    )
    assert v2.silhouette_error_factor == 0.1
    assert v2.tier_epsilon.coverage == 0.01


def test_v1_settings_are_untouched_by_the_v2_block():
    """The flag must stay a genuine A/B; v1's payload shape does not move."""
    from backend.config import settings
    assert settings.dfm.parting_line.dot_tolerance == 0.01
    assert settings.dfm.parting_line.min_silhouette_coverage_ratio == 0.35
    assert settings.dfm.core_cavity.threshold == 0.05
