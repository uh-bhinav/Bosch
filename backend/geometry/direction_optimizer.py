"""
backend/geometry/direction_optimizer.py
---------------------------------------
Module 3, first production pass: optimal mold opening direction.

Scope of this implementation
----------------------------
This module implements a deterministic candidate-direction search using the
surface-normal accessibility prefilter used by Bassi et al. (2010):

    n · d ≈ 0  -> silhouette / parting region
    n · d < 0  -> core-side face
    n · d > 0  -> cavity-side face

For each candidate pull direction, we run non-mutating draft analysis and score
the direction by:
  1. Bad draft area fraction.
  2. Marginal draft area fraction.
  3. Count of bad/marginal faces.
  4. Tie-breaker favoring principal axes for mold simplicity.

Important honesty note
----------------------
This is not the full Bassi swept-surface + regularized Boolean interference
algorithm yet.  It is the fast accessibility/draft scoring stage that narrows
the search and gives Level 1 a robust initial best direction.  The Boolean
undercut-volume stage will be added in `undercut_detector.py` and then folded
into this score.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from backend.config import settings
from backend.geometry.draft_analyzer import (
    DraftAnalysisResult,
    FaceDirectionalMetrics,
    analyze_draft,
    precompute_directional_metrics,
)
from backend.geometry.undercut_detector import (
    BooleanVolumeCache,
    UndercutDetectionResult,
    detect_undercuts,
    undercut_result_from_plain,
)
from backend.models.geometry_models import PartGeometry, Vec3, cross3, dot3, normalize3

PartCacheSignature = tuple[int, int, int, int, int, int, int]


@dataclass(frozen=True)
class DirectionUndercutCacheKey:
    part_signature: PartCacheSignature
    direction_x: int
    direction_y: int
    direction_z: int
    boolean_refine: bool
    boolean_check_all_faces: bool
    max_boolean_faces: int


DirectionUndercutCache = dict[DirectionUndercutCacheKey, UndercutDetectionResult]


@dataclass(frozen=True)
class BooleanPruningSummary:
    """
    Explain why only selected candidate directions receive expensive Boolean checks.

    The optimizer first ranks all directions with the fast draft/accessibility
    prefilter, then applies this gate before Bassi-style swept Boolean
    refinement.  Keeping the gate explicit makes performance decisions tunable
    and reviewable in the API response.
    """

    strategy: str
    best_prefilter_score: float
    ratio_threshold: float
    near_tie_threshold: float
    uncertainty_threshold: float
    survivor_count: int
    promising_count: int
    pruned_count: int
    max_refine_count: int
    survivor_top_count: int
    min_boolean_candidates: int
    low_risk_candidate_count: int = 0
    principal_axis_guard_count: int = 0
    uncertainty_candidate_count: int = 0
    survivor_reasons: dict[str, list[str]] = field(default_factory=dict)
    pruned_examples: list[dict] = field(default_factory=list)
    #: Phase 5C-1 (D-051): the Stage-1+2 pool's own verified-best score,
    #: when supplied. None when no Stage-1+2 candidate exists to compare
    #: against (e.g. hierarchical_search_enabled=False, or Stage 1+2 found
    #: nothing at all) -- in that case the coverage fix is a no-op and
    #: behavior is byte-identical to before this phase.
    baseline_score: float | None = None
    baseline_ratio_threshold: float | None = None
    baseline_near_tie_threshold: float | None = None
    #: Candidates retained ONLY because they were competitive with
    #: baseline_score, not with the pool's own local best -- i.e. exactly
    #: the set this phase's fix newly rescues from pruning. Always 0 when
    #: baseline_score is None.
    baseline_rescued_candidate_count: int = 0

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "best_prefilter_score": round(self.best_prefilter_score, 6),
            "ratio_threshold": round(self.ratio_threshold, 6),
            "near_tie_threshold": round(self.near_tie_threshold, 6),
            "uncertainty_threshold": round(self.uncertainty_threshold, 6),
            "survivor_count": self.survivor_count,
            "promising_count": self.promising_count,
            "pruned_count": self.pruned_count,
            "max_refine_count": self.max_refine_count,
            "survivor_top_count": self.survivor_top_count,
            "min_boolean_candidates": self.min_boolean_candidates,
            "low_risk_candidate_count": self.low_risk_candidate_count,
            "principal_axis_guard_count": self.principal_axis_guard_count,
            "uncertainty_candidate_count": self.uncertainty_candidate_count,
            "survivor_reasons": self.survivor_reasons,
            "pruned_examples": self.pruned_examples,
            "baseline_score": (
                round(self.baseline_score, 6) if self.baseline_score is not None else None
            ),
            "baseline_ratio_threshold": (
                round(self.baseline_ratio_threshold, 6)
                if self.baseline_ratio_threshold is not None else None
            ),
            "baseline_near_tie_threshold": (
                round(self.baseline_near_tie_threshold, 6)
                if self.baseline_near_tie_threshold is not None else None
            ),
            "baseline_rescued_candidate_count": self.baseline_rescued_candidate_count,
        }


#: Phase 5B (2026-08-16): always present on every DirectionOptimizationResult
#: (see the note below and _evidence_tier's docstring further down this
#: file) -- a reminder that even "verified_acceptable" evidence is bounded
#: by the undercut detector's own documented, unfixed-in-this-phase
#: limitation (D-047: accessibility-risk candidate generation is
#: core-side-only). Defined here (ahead of the dataclasses below) purely so
#: it is available as a dataclass field default at class-definition time.
RESIDUAL_DETECTOR_LIMITATION_NOTE = (
    "Boolean-verified evidence (this phase, D-046/D-047) excludes near-"
    "zero-g degenerate sweeps and includes accessibility-risk candidates, "
    "but accessibility-risk candidate generation is core-side-only by "
    "design (a cavity-side/positive-g equivalent undercut is not "
    "generated as a candidate unless it is also draft-proxy-flagged). "
    "'verified_acceptable' means no undercut was found BY THIS METHOD, "
    "not that none exists."
)


@dataclass(frozen=True)
class DirectionCandidateResult:
    direction: Vec3
    label: str
    score: float
    bad_face_count: int
    marginal_face_count: int
    good_face_count: int
    bad_area_mm2: float
    marginal_area_mm2: float
    total_area_mm2: float
    bad_area_pct: float
    marginal_area_pct: float
    undercut_face_count: int
    undercut_feature_count: int
    undercut_area_pct: float
    boolean_refined: bool
    boolean_checked_count: int
    interference_volume_mm3: float
    principal_axis_alignment: float
    # Milestone 4: independent accessibility risk signal (heuristic — NOT proof of undercut)
    accessibility_risk_area_pct: float = 0.0
    # Phase 5B (2026-08-16): explicit evidence-state fields. confirmed_undercut_pct
    # is 0.0 when boolean_refined=False -- that means "never checked", NOT
    # "confirmed clean". evidence_tier is the authoritative classification;
    # see _evidence_tier()'s docstring for the three states.
    confirmed_undercut_pct: float = 0.0
    evidence_tier: str = "unverified"
    # Phase 5C-3 (D-053, renamed D-054): feature-level engineering-
    # consequence classification -- see _feature_acceptability()'s
    # docstring for the three states ("clean" /
    # "confirmed_undercut_secondary_tooling_candidate" /
    # "requires_manual_review"). DELIBERATELY separate from evidence_tier,
    # and DELIBERATELY not a feasibility claim: the middle state means "a
    # confirmed undercut exists and the detector has identified a
    # plausible mechanism CLASS for downstream engineering review" -- it
    # is NOT proof that the mechanism is feasible, collision-free,
    # actuated, or manufacturable, and must never be read as "how much
    # area is confirmed" or as a path already accepted. "clean" whenever
    # boolean_refined=False (never checked -- same honesty rule as
    # confirmed_undercut_pct above).
    feature_acceptability: str = "clean"
    #: Count of confirmed features whose feature_acceptability is
    #: "confirmed_undercut_secondary_tooling_candidate" -- candidates for
    #: downstream review, not a count of "resolved" features.
    secondary_tooling_feature_count: int = 0
    manual_review_feature_count: int = 0
    feature_acceptability_reason: str = ""
    # O22 (2026-08-17): propagated from a failed isolated-child undercut
    # evaluation (timeout/crash/malformed payload/STEP-load/OCC failure).
    # evidence_tier is forced to "unverified" alongside this -- a failed
    # candidate is excluded from _tiered_best/best_feasible/optimal_found
    # by the SAME existing evidence_tier check every other unverified
    # candidate already goes through, not a separate branch.
    evaluation_failed: bool = False
    evaluation_error: str = ""

    def to_dict(self) -> dict:
        return {
            "direction": [round(v, 6) for v in self.direction],
            "label": self.label,
            "score": round(self.score, 6),
            "face_counts": {
                "good": self.good_face_count,
                "marginal": self.marginal_face_count,
                "bad": self.bad_face_count,
            },
            "area_mm2": {
                "bad": round(self.bad_area_mm2, 3),
                "marginal": round(self.marginal_area_mm2, 3),
                "total": round(self.total_area_mm2, 3),
            },
            "percentages": {
                "bad_area_pct": round(self.bad_area_pct, 3),
                "marginal_area_pct": round(self.marginal_area_pct, 3),
                "undercut_area_pct": round(self.undercut_area_pct, 3),
                "accessibility_risk_area_pct": round(self.accessibility_risk_area_pct, 3),
            },
            "undercuts": {
                "face_count": self.undercut_face_count,
                "feature_count": self.undercut_feature_count,
                "boolean_refined": self.boolean_refined,
                "boolean_checked_count": self.boolean_checked_count,
                "interference_volume_mm3": round(self.interference_volume_mm3, 6),
                "confirmed_undercut_pct": round(self.confirmed_undercut_pct, 4),
            },
            "principal_axis_alignment": round(self.principal_axis_alignment, 6),
            "evidence_tier": self.evidence_tier,
            "feature_acceptability": self.feature_acceptability,
            "secondary_tooling_feature_count": self.secondary_tooling_feature_count,
            "manual_review_feature_count": self.manual_review_feature_count,
            "feature_acceptability_reason": self.feature_acceptability_reason,
            "evaluation_failed": self.evaluation_failed,
            "evaluation_error": self.evaluation_error,
        }


@dataclass(frozen=True)
class DirectionOptimizationResult:
    best_direction: Vec3
    best_label: str
    best_score: float
    initial_pull_direction: Vec3
    initial_label: str
    initial_draft: DraftAnalysisResult
    initial_undercuts: UndercutDetectionResult
    optimal_draft: DraftAnalysisResult
    optimal_undercuts: UndercutDetectionResult
    candidates: list[DirectionCandidateResult] = field(default_factory=list)
    method: str = "surface-normal draft + undercut adjacency prefilter"
    analysis_time_s: float = 0.0
    boolean_refined_candidate_count: int = 0
    boolean_pruned_candidate_count: int = 0
    boolean_survivor_candidate_count: int = 0
    boolean_promising_candidate_count: int = 0
    boolean_pruning_summary: BooleanPruningSummary | None = None
    direction_cache_hits: int = 0
    direction_cache_misses: int = 0
    direction_cache_entries: int = 0
    direction_cache_final_reused: bool = False
    boolean_volume_cache_entries: int = 0
    # Milestone 3: which search stage found the winner (1=principal,
    # 2=diagonal, 3=sphere). O4 (2026-08-17): 0=resolved directly from
    # initial_pull_direction when it is not one of Stage 1/2's configured
    # directions (a caller-supplied custom direction) -- distinct from 3
    # so a custom-but-seeded winner is never misreported as a Stage-3
    # spherical-grid result.
    search_stage_reached: int = 3
    # Phase 5B (2026-08-16): explicit optimum-validity reporting.
    # optimal_found=True iff best_direction's own evidence_tier is
    # "verified_acceptable" -- i.e. best_direction was ACTUALLY Boolean-
    # verified and found acceptable, not merely the lowest raw score among
    # whatever survived an early filter. When False, best_direction/
    # best_score/best_label still point at the best candidate found (for
    # backward compatibility with existing callers expecting a usable
    # Vec3), but best_unverified_candidate makes the same object available
    # explicitly-labeled as a diagnostic fallback, never a validated optimum.
    optimal_found: bool = True
    best_evidence_tier: str = "unverified"
    best_unverified_candidate: DirectionCandidateResult | None = None
    residual_detector_limitation_note: str = RESIDUAL_DETECTOR_LIMITATION_NOTE
    # O22 (2026-08-17): (direction_label, method, error) entries for every
    # candidate whose isolated undercut evaluation failed during this
    # search -- kept separate from "no feasible candidate exists" so the
    # two are never conflated. Always empty for the pre-O22 in-process
    # path (mock parts, or when nothing failed).
    evaluation_failures: list[dict] = field(default_factory=list)
    #: C12 (2026-08-17): every distinct (direction, SideActionReferral)
    #: pair encountered while evaluating parting-line feasibility during
    #: this search -- reporting only, never consumed to change
    #: optimal_found/best_feasible/candidate selection (H5's
    #: "requires_side_action" already excludes a direction from those via
    #: the existing, unmodified `if not feasibility.feasible: continue`
    #: checks; this field exists so that exclusion is never silently
    #: indistinguishable from "genuinely infeasible" -- see
    #: docs/PARTING_LINE_ALGORITHM_PLAN.md §12.8). Each entry is
    #: ``{"direction": [x,y,z], "direction_label": str, "referral": <the
    #: unmodified SideActionReferral.to_dict()>}`` -- SideActionReferral
    #: itself is never changed to carry optimizer provenance; the
    #: provenance lives in this wrapper dict instead. Deduplicated by
    #: (direction, referral) so O4/O10 caching/repeated evaluation of the
    #: same direction across the initial seed, Stage 1+2, and Stage 3/tail
    #: paths never produces duplicate diagnostics. Always empty when no
    #: candidate was ever referred (including every pre-C12 search).
    side_action_referrals: list[dict] = field(default_factory=list)

    def to_dict(self, include_all_candidates: bool = True) -> dict:
        cache_lookups = self.direction_cache_hits + self.direction_cache_misses
        initial_undercuts = self.initial_undercuts.to_dict()
        optimal_undercuts = self.optimal_undercuts.to_dict()
        return {
            "best_direction": [round(v, 6) for v in self.best_direction],
            "best_label": self.best_label,
            "best_score": round(self.best_score, 6),
            "initial_pull_direction": [round(v, 6) for v in self.initial_pull_direction],
            "initial_label": self.initial_label,
            "method": self.method,
            "search_stage_reached": self.search_stage_reached,
            "analysis_time_s": round(self.analysis_time_s, 4),
            "boolean_refined_candidate_count": self.boolean_refined_candidate_count,
            "boolean_pruned_candidate_count": self.boolean_pruned_candidate_count,
            "boolean_survivor_candidate_count": self.boolean_survivor_candidate_count,
            "boolean_promising_candidate_count": self.boolean_promising_candidate_count,
            "boolean_pruning_summary": (
                self.boolean_pruning_summary.to_dict()
                if self.boolean_pruning_summary is not None
                else None
            ),
            "direction_cache": {
                "hits": self.direction_cache_hits,
                "misses": self.direction_cache_misses,
                "entries": self.direction_cache_entries,
                "hit_rate": (
                    round(self.direction_cache_hits / cache_lookups, 4)
                    if cache_lookups
                    else 0.0
                ),
                "final_direction_reused": self.direction_cache_final_reused,
                "boolean_volume_cache_entries": self.boolean_volume_cache_entries,
            },
            "initial_draft": self.initial_draft.to_dict(),
            "initial_undercuts": initial_undercuts,
            "undercuts_initial_direction": initial_undercuts,
            "optimal_draft": self.optimal_draft.to_dict(),
            "optimal_undercuts": optimal_undercuts,
            "undercuts_optimal_direction": optimal_undercuts,
            "candidate_count": len(self.candidates),
            "candidates": [
                c.to_dict() for c in self.candidates
            ] if include_all_candidates else [
                c.to_dict() for c in self.candidates[:10]
            ],
            "evaluation_failures": self.evaluation_failures,
            "side_action_referrals": self.side_action_referrals,
        }


def _direction_label(direction: Vec3) -> str:
    axes = {
        "+X": (1.0, 0.0, 0.0),
        "-X": (-1.0, 0.0, 0.0),
        "+Y": (0.0, 1.0, 0.0),
        "-Y": (0.0, -1.0, 0.0),
        "+Z": (0.0, 0.0, 1.0),
        "-Z": (0.0, 0.0, -1.0),
    }
    for label, axis in axes.items():
        if abs(dot3(direction, axis) - 1.0) < 1e-9:
            return label
    return f"({direction[0]:+.3f}, {direction[1]:+.3f}, {direction[2]:+.3f})"


def _dedupe_direction(direction: Vec3, seen: set[tuple[int, int, int]]) -> bool:
    key = (
        round(direction[0], 6),
        round(direction[1], 6),
        round(direction[2], 6),
    )
    int_key = (int(key[0] * 1_000_000), int(key[1] * 1_000_000), int(key[2] * 1_000_000))
    if int_key in seen:
        return False
    seen.add(int_key)
    return True


def _part_cache_signature(part: PartGeometry) -> PartCacheSignature:
    """
    Compact geometry signature for direction-level cache safety.

    The cache is intended for one loaded part, but including topology and bbox
    dimensions prevents accidental reuse if a shared cache is introduced by the
    API or agent layer later.
    """
    dims = part.bounding_box.dimensions
    total_area = sum(max(face.area, 0.0) for face in part.faces)
    return (
        int(part.face_count),
        int(part.solid_count),
        int(part.shell_count),
        int(round(dims[0] * 1_000)),
        int(round(dims[1] * 1_000)),
        int(round(dims[2] * 1_000)),
        int(round(total_area * 1_000)),
    )


def _direction_cache_key(
    part: PartGeometry,
    direction: Vec3,
    boolean_refine: bool,
    boolean_check_all_faces: bool,
    max_boolean_faces: int,
) -> DirectionUndercutCacheKey:
    unit = normalize3(direction)
    return DirectionUndercutCacheKey(
        part_signature=_part_cache_signature(part),
        direction_x=int(round(unit[0] * 1_000_000)),
        direction_y=int(round(unit[1] * 1_000_000)),
        direction_z=int(round(unit[2] * 1_000_000)),
        boolean_refine=bool(boolean_refine),
        boolean_check_all_faces=bool(boolean_check_all_faces),
        max_boolean_faces=int(max_boolean_faces),
    )


def _same_direction_cache_scope(
    cached_key: DirectionUndercutCacheKey,
    requested_key: DirectionUndercutCacheKey,
) -> bool:
    return (
        cached_key.part_signature == requested_key.part_signature
        and cached_key.direction_x == requested_key.direction_x
        and cached_key.direction_y == requested_key.direction_y
        and cached_key.direction_z == requested_key.direction_z
        and cached_key.boolean_refine == requested_key.boolean_refine
    )


def _lookup_direction_cache(
    direction_cache: DirectionUndercutCache,
    requested_key: DirectionUndercutCacheKey,
) -> UndercutDetectionResult | None:
    exact = direction_cache.get(requested_key)
    if exact is not None:
        return exact

    reusable: list[tuple[int, UndercutDetectionResult]] = []
    for cached_key, cached_result in direction_cache.items():
        if not _same_direction_cache_scope(cached_key, requested_key):
            continue
        if requested_key.boolean_check_all_faces and not cached_key.boolean_check_all_faces:
            continue
        if cached_key.max_boolean_faces < requested_key.max_boolean_faces:
            continue
        reusable.append((cached_key.max_boolean_faces, cached_result))

    if not reusable:
        return None
    reusable.sort(key=lambda item: item[0])
    return reusable[0][1]


def _cached_undercuts_for_feasibility(
    part: PartGeometry,
    direction: Vec3,
    direction_cache: DirectionUndercutCache,
    max_boolean_faces: int,
) -> "UndercutDetectionResult | None":
    """
    C10 (2026-08-17): look up the ALREADY-COMPUTED ``UndercutDetectionResult``
    for ``(part, direction)`` from the existing ``direction_undercut_cache``
    -- never recomputes. By the time any of this function's three call
    sites inside ``optimize_mold_direction`` run, ``direction`` has already
    reached ``evidence_tier == "verified_acceptable"``, which is only ever
    set for a Boolean-refined candidate, meaning ``_cached_detect_boolean_
    undercuts`` has already populated this exact cache entry moments
    earlier in the same call. Returns ``None`` (never raises) if the
    lookup genuinely misses, so a caller can fall back to the pre-C10
    ``UndercutInput.empty()`` behavior rather than fail the whole search.
    """
    key = _direction_cache_key(
        part=part, direction=direction, boolean_refine=True,
        boolean_check_all_faces=False, max_boolean_faces=max_boolean_faces,
    )
    return _lookup_direction_cache(direction_cache, key)


def _apply_undercut_result_to_part(
    part: PartGeometry,
    result: UndercutDetectionResult,
) -> None:
    """
    Apply a cached undercut result to mutable face fields used by visualization.

    Cached direction results are produced with ``mutate=False`` during candidate
    ranking.  When the same direction becomes the final best direction, this
    function gives the UI the same face-level overlay without re-running the
    full swept Boolean direction analysis.
    """
    undercut_ids = set(result.undercut_face_ids)
    parting_ids = set(result.parting_face_ids)
    feature_by_face: dict[int, tuple[float, str]] = {}
    for feature in result.features:
        for face_id in feature.face_ids:
            feature_by_face[face_id] = (
                feature.depth_proxy_mm,
                feature.undercut_type,
            )

    for face in part.valid_faces:
        if face.face_id in undercut_ids:
            depth, undercut_type = feature_by_face.get(
                face.face_id,
                (0.0, "pending-feature-group"),
            )
            face.is_undercut = True
            face.undercut_depth_mm = depth
            face.undercut_type = undercut_type
        elif face.face_id not in parting_ids:
            face.is_undercut = False
            face.undercut_depth_mm = None
            face.undercut_type = None


_UNDERCUT_WORKER_SCRIPT = str(Path(__file__).with_name("undercut_isolation_worker.py"))

# O22 (2026-08-17): engineering-policy timeout for one isolated child's
# Boolean-refined undercut detection. This is NOT a mathematical guarantee
# that every possible worst-case sequential-children count stays under the
# 240s outer API budget -- Rule 6 (O22 spec) explicitly requires that
# honesty and O21 Guard 2 already established the ceiling is not provably
# derivable from available data. It IS derived from measured evidence:
#   - the worst healthy isolated Boolean-refined direction observed on
#     Part1 (the XY-diagonal candidate) cost ~61.4-65.2s, confirmed
#     independently 3x across O17/O21;
#   - fresh-subprocess spawn + STEP-reload overhead measured at ~2.3-3.2s
#     (O19/O21).
# 150s is ~2x that worst observed healthy cost, so ordinary runtime
# variance around the measured ceiling is never routinely mistaken for a
# hang. Whether the REAL number of sequential Boolean-refined (cache-miss)
# children in an actual end-to-end run keeps total wall time under 240s is
# exactly what this phase's required end-to-end Part1 measurement
# validates empirically -- it is not assumed true here.
UNDERCUT_CHILD_TIMEOUT_S = 150.0


def _failed_undercut_result(direction: Vec3, method: str, error: str) -> UndercutDetectionResult:
    """Smallest explicit failure representation (Rule 5) -- never clean/infeasible/verified."""
    return UndercutDetectionResult(
        pull_direction=direction,
        method=method,
        undercut_face_ids=[],
        accessible_face_ids=[],
        parting_face_ids=[],
        skipped_face_ids=[],
        evaluation_failed=True,
        evaluation_error=error,
    )


def _run_isolated_undercut_detection(
    part: PartGeometry,
    direction: Vec3,
    max_boolean_faces: int,
) -> UndercutDetectionResult:
    """
    Run Boolean-refined undercut detection for one direction in a fresh,
    single-use child OS process (O22) -- the mechanism that removes the
    O17-O19-proven process-lifetime OCC degradation from this function's
    long-running caller.

    Never raises. Every failure mode (spawn error, timeout, non-zero exit,
    malformed JSON, an explicit ``"ok": false`` payload, or a
    reconstruction error) becomes an ``UndercutDetectionResult`` with
    ``evaluation_failed=True`` and a populated ``evaluation_error`` --
    never a clean/no-undercut/infeasible/verified result (Rule 5).
    """
    request = json.dumps({
        "step_path": part.source_file,
        "direction": list(direction),
        "max_boolean_faces": max_boolean_faces,
    })
    try:
        proc = subprocess.run(
            [sys.executable, _UNDERCUT_WORKER_SCRIPT],
            input=request,
            capture_output=True,
            text=True,
            timeout=UNDERCUT_CHILD_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return _failed_undercut_result(
            direction, "isolated-child-timeout",
            f"child evaluation timed out after {UNDERCUT_CHILD_TIMEOUT_S}s",
        )
    except Exception as exc:
        return _failed_undercut_result(
            direction, "isolated-child-spawn-error",
            f"failed to spawn child: {type(exc).__name__}: {exc}",
        )

    if proc.returncode != 0:
        return _failed_undercut_result(
            direction, "isolated-child-nonzero-exit",
            f"child exited {proc.returncode}: {(proc.stderr or proc.stdout or '')[-2000:]}",
        )

    stdout_lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if not stdout_lines:
        return _failed_undercut_result(
            direction, "isolated-child-empty-output", "child produced no stdout output",
        )
    try:
        payload = json.loads(stdout_lines[-1])
    except Exception as exc:
        return _failed_undercut_result(
            direction, "isolated-child-malformed-output",
            f"could not parse child stdout as JSON: {exc}",
        )

    if not payload.get("ok"):
        return _failed_undercut_result(
            direction, "isolated-child-reported-failure",
            str(payload.get("error", "unknown child failure")),
        )

    try:
        return undercut_result_from_plain(payload["result"])
    except Exception as exc:
        return _failed_undercut_result(
            direction, "isolated-child-reconstruction-error",
            f"failed to reconstruct result: {type(exc).__name__}: {exc}",
        )


def _cached_detect_boolean_undercuts(
    part: PartGeometry,
    direction: Vec3,
    direction_cache: DirectionUndercutCache,
    boolean_volume_cache: BooleanVolumeCache,
    mutate: bool,
    max_boolean_faces: int,
) -> tuple[UndercutDetectionResult, bool]:
    """
    Run or reuse Boolean-refined undercut detection for one pull direction.

    The key includes direction and Boolean parameters, so cached results are not
    reused across different refinement scopes.

    O22 (2026-08-17): on a real cache miss, the expensive Boolean-refined
    detection runs in a fresh, single-use child OS process instead of
    in-process (see ``_run_isolated_undercut_detection``). Mock-safety
    guarded exactly like ``_cached_is_parting_line_feasible``: a non-OCC
    ``part.occ_shape`` (MagicMock-based unit tests) falls back unchanged to
    the original in-process ``detect_undercuts`` call, since a mock part
    has no real STEP file on disk for a child process to load.
    """
    key = _direction_cache_key(
        part=part,
        direction=direction,
        boolean_refine=True,
        boolean_check_all_faces=False,
        max_boolean_faces=max_boolean_faces,
    )
    cached = _lookup_direction_cache(direction_cache, key)
    if cached is not None:
        if mutate:
            _apply_undercut_result_to_part(part, cached)
        return cached, True

    from OCC.Core.TopoDS import TopoDS_Shape

    if isinstance(part.occ_shape, TopoDS_Shape) and part.source_file:
        result = _run_isolated_undercut_detection(part, direction, max_boolean_faces)
        if mutate and not result.evaluation_failed:
            _apply_undercut_result_to_part(part, result)
    else:
        result = detect_undercuts(
            part,
            direction,
            mutate=mutate,
            boolean_refine=True,
            max_boolean_faces=max_boolean_faces,
            boolean_volume_cache=boolean_volume_cache,
        )
    direction_cache[key] = result
    return result, False


def generate_candidate_directions(
    angular_step_deg: float | None = None,
    max_candidates: int | None = None,
) -> list[Vec3]:
    """
    Generate deterministic candidate mold directions.

    Includes principal axes first, then spherical samples.  Candidate count and
    angular spacing are configuration/API parameters, not algorithm constants.
    """
    cfg = settings.dfm.direction_search
    step = float(angular_step_deg or cfg.angular_step_deg)
    limit = int(max_candidates or cfg.max_candidates)
    if step <= 0:
        raise ValueError("angular_step_deg must be > 0")
    if limit < 6:
        raise ValueError("max_candidates must be at least 6")

    candidates: list[Vec3] = []
    seen: set[tuple[int, int, int]] = set()

    def add(direction: Vec3) -> None:
        unit = normalize3(direction)
        if _dedupe_direction(unit, seen):
            candidates.append(unit)

    for direction in [
        (1.0, 0.0, 0.0),
        (-1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, -1.0, 0.0),
        (0.0, 0.0, 1.0),
        (0.0, 0.0, -1.0),
    ]:
        add(direction)

    # Spherical sampling.  theta: polar angle from +Z; phi: azimuth in XY.
    theta = step
    while theta < 180.0 and len(candidates) < limit:
        sin_t = math.sin(math.radians(theta))
        cos_t = math.cos(math.radians(theta))
        phi = 0.0
        while phi < 360.0 and len(candidates) < limit:
            add((
                sin_t * math.cos(math.radians(phi)),
                sin_t * math.sin(math.radians(phi)),
                cos_t,
            ))
            phi += step
        theta += step

    return candidates[:limit]


def _principal_axis_alignment(direction: Vec3) -> float:
    return max(abs(direction[0]), abs(direction[1]), abs(direction[2]))


def _perpendicular_basis(direction: Vec3) -> tuple[Vec3, Vec3]:
    """Build a stable orthonormal 2-D basis perpendicular to `direction`."""
    reference = (0.0, 0.0, 1.0) if abs(direction[2]) < 0.9 else (1.0, 0.0, 0.0)
    u = normalize3(cross3(reference, direction))
    v = cross3(direction, u)
    return u, v


def generate_fine_candidate_directions(
    base_direction: Vec3,
    cone_half_angle_deg: float,
    angular_step_deg: float,
    seen: set[tuple[int, int, int]],
) -> list[Vec3]:
    """
    Sample a local cone of directions around `base_direction` (Roadmap
    Phase 1d, Gap 2: coarse-to-fine search).

    A uniform global grid at `angular_step_deg` (default 15°) cannot resolve
    an optimum that sits a few degrees off a sampled direction — real parts
    are frequently drafted at 1-3° from an axis. This mirrors
    `generate_candidate_directions`'s spherical sampling pattern, but bounded
    to a small cone around a specific coarse-stage winner instead of the
    whole sphere.

    `seen` is the SAME dedup set used for the coarse candidates (and, when
    called repeatedly for multiple coarse winners, across those calls too)
    so a fine sample that coincides with an existing candidate is skipped
    rather than double-scored.
    """
    base = normalize3(base_direction)
    if cone_half_angle_deg <= 0.0 or angular_step_deg <= 0.0:
        return []
    u_axis, v_axis = _perpendicular_basis(base)

    candidates: list[Vec3] = []

    def add(direction: Vec3) -> None:
        unit = normalize3(direction)
        if _dedupe_direction(unit, seen):
            candidates.append(unit)

    alpha = 0.0
    while alpha <= cone_half_angle_deg + 1e-9:
        sin_a = math.sin(math.radians(alpha))
        cos_a = math.cos(math.radians(alpha))
        if alpha < 1e-9:
            add(base)
            alpha += angular_step_deg
            continue
        phi = 0.0
        while phi < 360.0:
            cos_p = math.cos(math.radians(phi))
            sin_p = math.sin(math.radians(phi))
            direction = tuple(
                cos_a * base[i] + sin_a * (cos_p * u_axis[i] + sin_p * v_axis[i])
                for i in range(3)
            )
            add(direction)
            phi += angular_step_deg
        alpha += angular_step_deg

    return candidates


def _flash_risk_area_fraction(part: PartGeometry, direction: Vec3) -> float:
    """
    Fraction of analysed area on thin-walled faces nearly parallel to the
    pull direction (Roadmap Phase 1d).

    Flash (molten plastic escaping at the parting line) is dominated by a
    face lying nearly parallel to the pull direction near the silhouette:
    the two mold halves meet at a shallow angle there, and shut-off is
    unreliable. A thick structural rib at a shallow angle is not a flash
    risk the way a thin wall is — wall thickness isn't modeled here (that
    needs ray casting or medial-axis analysis), so a face's own area is used
    as a coarse proxy for thinness: gate on
    `area < flash_thin_area_factor * bbox_diagonal**2`.
    """
    cfg = settings.dfm.direction_search
    sin_threshold = math.sin(math.radians(cfg.flash_angle_threshold_deg))
    bbox_diagonal = max(part.bounding_box.diagonal, 1e-6)
    thin_area_limit = cfg.flash_thin_area_factor * bbox_diagonal * bbox_diagonal

    total_area = 0.0
    flash_area = 0.0
    for face in part.faces:
        if not face.normal_valid:
            continue
        total_area += face.area
        if abs(dot3(face.normal, direction)) < sin_threshold and face.area < thin_area_limit:
            flash_area += face.area

    if total_area <= 0.0:
        return 0.0
    return flash_area / total_area


def _score_candidate(
    draft: DraftAnalysisResult,
    undercuts: UndercutDetectionResult,
    direction: Vec3,
    part: PartGeometry,
) -> float:
    """
    Lower score is better.

    Milestone 4: Two independent scoring modes depending on whether
    Boolean refinement data is available.

    **Cheap stage** (``undercuts.boolean_refined=False``):
      Uses ``accessibility_risk_area_pct`` as the obstruction signal.
      This is independent of draft: a face with bad draft but all-convex
      edges contributes to ``bad_pct`` but NOT to ``accessibility_risk``.
      Conversely, a well-drafted core-side face with a concave edge
      contributes to ``accessibility_risk`` but NOT to ``bad_pct``.
      The two signals are genuinely orthogonal.

    **Boolean-refined stage** (``undercuts.boolean_refined=True``):
      Replaces the accessibility-risk proxy with Boolean-confirmed undercut
      area (computed from ``boolean_confirmed_face_ids``).  Interference
      volume is retained from existing Boolean measurement.

    **Prohibited equivalences** (enforced here by design):
    - ``bad draft`` ≠ ``accessibility_risk`` (different faces flagged)
    - ``accessibility_risk`` ≠ ``confirmed_undercut`` (heuristic vs geometric)
    - ``proxy_undercut_pct`` ≠ ``confirmed_undercut_pct`` (always)
    """
    cfg = settings.dfm.direction_search
    bad_pct = draft.bad_pct / 100.0
    marginal_pct = draft.marginal_pct / 100.0
    face_count = max(1, draft.face_count_analysed)
    bad_count_frac = len(draft.bad_face_ids) / face_count
    marginal_count_frac = len(draft.marginal_face_ids) / face_count
    dims = part.bounding_box.dimensions
    bbox_volume = max(dims[0] * dims[1] * dims[2], 1.0)
    interference_volume_frac = min(1.0, undercuts.interference_volume_mm3 / bbox_volume)
    flash_area_frac = _flash_risk_area_fraction(part, direction)
    non_axis_penalty = 1.0 - _principal_axis_alignment(direction)

    if undercuts.boolean_refined:
        # Boolean-refined stage: use confirmed undercut area only.
        # Compute confirmed area from boolean_confirmed_face_ids (authoritative).
        total_area = max(undercuts.total_analysed_area_mm2, 1.0)
        confirmed_area = sum(
            f.area for fid in undercuts.boolean_confirmed_face_ids
            if (f := part.get_face(fid)) is not None
        )
        confirmed_undercut_pct = confirmed_area / total_area
        return (
            cfg.scoring_confirmed_undercut * confirmed_undercut_pct
            + cfg.scoring_bad_draft * bad_pct
            + cfg.scoring_marginal_draft * marginal_pct
            + cfg.boolean_interference_weight * interference_volume_frac
            + cfg.flash_risk_weight * flash_area_frac
            + cfg.scoring_bad_draft_count * bad_count_frac
            + cfg.scoring_marginal_draft_count * marginal_count_frac
            + cfg.scoring_axis_preference * non_axis_penalty
        )
    else:
        # Cheap stage: use accessibility risk (heuristic, NOT proof of undercut).
        # This is independent from bad_pct — do NOT treat them as the same signal.
        risk_pct = undercuts.accessibility_risk_area_pct / 100.0
        risk_count_frac = len(undercuts.accessibility_risk_face_ids) / face_count
        return (
            cfg.scoring_accessibility_risk * risk_pct
            + cfg.scoring_bad_draft * bad_pct
            + cfg.scoring_marginal_draft * marginal_pct
            + cfg.flash_risk_weight * flash_area_frac
            + cfg.scoring_bad_draft_count * bad_count_frac
            + cfg.scoring_marginal_draft_count * marginal_count_frac
            + cfg.scoring_accessibility_risk_count * risk_count_frac
            + cfg.scoring_axis_preference * non_axis_penalty
        )


def _common_lower_bound(draft: DraftAnalysisResult, direction: Vec3, part: PartGeometry) -> float:
    """
    D-062 (2026-08-16): a mathematically exact lower bound on the eventual
    Boolean-refined ``_score_candidate`` score for this direction,
    computable entirely from the cheap (pre-Boolean, pre-ray-verification)
    stage.

    This is deliberately a SEPARATE function, not a refactor of
    ``_score_candidate`` (which is explicitly not to be modified) --
    duplicated on purpose, not by oversight.

    Proof (re-verified directly against the live ``_score_candidate``
    source before this function was written):

    ``_score_candidate``'s Boolean-refined branch is exactly

        common(bad_pct, marginal_pct, flash_area_frac, bad_count_frac,
               marginal_count_frac, non_axis_penalty)
      + scoring_confirmed_undercut * confirmed_undercut_pct
      + boolean_interference_weight * interference_volume_frac

    where ``common(...)`` is this function's own return value -- the sum
    of every term that is IDENTICAL between the cheap and Boolean-refined
    branches (bad_pct/marginal_pct/bad_count_frac/marginal_count_frac come
    from ``draft`` alone, unaffected by Boolean/ray status;
    flash_area_frac and non_axis_penalty depend only on ``(part,
    direction)``, never on undercut evidence at all).

    Every term ``_score_candidate`` adds ON TOP of ``common(...)`` in the
    Boolean-refined branch has a config weight confirmed strictly positive
    in ``config.yaml`` (``scoring_confirmed_undercut=1500.0``,
    ``boolean_interference_weight=4000.0``) multiplied by a quantity that
    is a ratio/fraction of non-negative physical quantities (confirmed
    area over total area; interference volume over bbox volume, clamped
    to ``[0, 1]``) and therefore itself always ``>= 0``.

    Therefore: ``final_score(candidate) >= common(...) `` for every
    candidate, always, with equality iff the eventual Boolean refinement
    finds zero confirmed undercut area AND zero interference volume.
    This is what makes bound-driven pruning in ``optimize_mold_direction``
    safe: a candidate whose ``common(...)`` already exceeds an established
    feasible incumbent's actual score cannot possibly beat it, regardless
    of what Boolean/ray verification would find.
    """
    cfg = settings.dfm.direction_search
    bad_pct = draft.bad_pct / 100.0
    marginal_pct = draft.marginal_pct / 100.0
    face_count = max(1, draft.face_count_analysed)
    bad_count_frac = len(draft.bad_face_ids) / face_count
    marginal_count_frac = len(draft.marginal_face_ids) / face_count
    flash_area_frac = _flash_risk_area_fraction(part, direction)
    non_axis_penalty = 1.0 - _principal_axis_alignment(direction)
    return (
        cfg.scoring_bad_draft * bad_pct
        + cfg.scoring_marginal_draft * marginal_pct
        + cfg.flash_risk_weight * flash_area_frac
        + cfg.scoring_bad_draft_count * bad_count_frac
        + cfg.scoring_marginal_draft_count * marginal_count_frac
        + cfg.scoring_axis_preference * non_axis_penalty
    )


@dataclass(frozen=True)
class PartingLineFeasibilityResult:
    """
    D-062/O3: the outcome of one ``_is_parting_line_feasible`` check,
    including diagnostics for the infeasible case -- reusing
    ``analyse_parting_line``'s OWN already-existing ``best_rejected_
    failed_gate``/``best_rejected_reason`` fields (the D-049 mechanism)
    rather than inventing any new failure semantics.

    C10 (2026-08-17): ``outcome`` mirrors ``PartingLineV2Result.outcome``
    exactly (``"feasible"`` / ``"referred_to_side_action"`` /
    ``"no_feasible_candidate"``) -- not a new vocabulary, the same one
    ``analyse_parting_line`` already exposes. ``feasible`` keeps its exact
    pre-C10 meaning (``True`` iff ``outcome == "feasible"``), so every
    EXISTING caller checking ``.feasible`` is unaffected in behavior;
    ``outcome`` is purely additive, for callers that need to distinguish
    "genuinely infeasible" from "disqualified as a main-split candidate,
    referred to side-action analysis" (docs/PARTING_LINE_ALGORITHM_PLAN.md
    §12.8: an H5 referral is explicitly "not part impossible" -- never to
    be reported as equivalent to infeasibility).
    """
    feasible: bool
    failed_gate: str | None = None
    reason: str | None = None
    outcome: str = "no_feasible_candidate"
    #: C12 (2026-08-17): the direction's SideActionReferral(s), preserved
    #: rather than discarded -- ``analyse_parting_line`` already collects
    #: these from every candidate for this direction, independent of which
    #: one (if any) is ``selected`` (see ``PartingLineV2Result.referrals``).
    #: Each entry is the EXISTING, unmodified ``SideActionReferral.to_dict()``
    #: -- no new fields invented, no optimizer provenance added onto the
    #: referral itself (that lives one level up, on
    #: ``DirectionOptimizationResult.side_action_referrals``, paired with
    #: the direction it came from).
    referrals: tuple[dict, ...] = ()


def _is_parting_line_feasible(
    part: PartGeometry,
    direction: Vec3,
    core_pin_face_refs: tuple = (),
    delegations: tuple = (),
    undercuts: "UndercutDetectionResult | None" = None,
) -> PartingLineFeasibilityResult:
    """
    D-062: the minimum downstream-feasibility signal missing from the
    pull-direction optimizer (see docs/DECISIONS_AND_ALGORITHMS.md D-062
    for the full audit). ``parting_line_v2`` remains a fully independent,
    downstream-only module -- this is a lazy import specifically to avoid
    any risk of a circular import (confirmed absent by direct repo search
    before this function was written: nothing under
    ``backend/geometry/parting_line_v2/`` imports from
    ``direction_optimizer``).

    C10 (2026-08-17): ``undercuts``, when supplied, is the ALREADY-COMPUTED
    ``UndercutDetectionResult`` for this exact ``(part, direction)`` --
    never recomputed here -- adapted via ``UndercutInput.
    from_detection_result()`` (the existing, previously-unused-in-
    production adapter in ``parting_line_v2.contracts``) and passed into
    ``analyse_parting_line`` so H5 can see real evidence instead of always
    receiving ``UndercutInput.empty()`` (Phase C9's central finding: every
    production call site previously passed empty evidence, so H5 -- the
    ONE gate that reads it -- was never actually exercised against a real
    part). ``undercuts=None`` (the default) preserves the exact pre-C10
    behavior byte-for-byte: ``analyse_parting_line`` itself already
    defaults to ``UndercutInput.empty()`` when its own ``undercuts``
    argument is omitted.

    O3 (2026-08-17): ``core_pin_face_refs``/``delegations`` are optional,
    caller-supplied ``CorePinFaceRef``/``DelegatedSecondaryAction`` tuples
    -- the EXACT existing types ``parting_line_v2`` already defines and
    its own ``/parting-line-v2`` API endpoint already accepts as
    authorization (never invented, never auto-discovered here). Passed
    straight through to ``analyse_parting_line`` unchanged; this function
    does not construct, infer, or validate them itself -- that remains
    entirely ``parting_line_v2``'s own job (H3's bridge-face check, H4's
    ``validate_delegation``). Defaulting to ``()`` on both keeps every
    existing call site (and Part1, which needs neither) byte-identical to
    before this parameter existed.

    Deliberately still minimal beyond that: does not independently re-run
    core/cavity classification, which is structurally derived from
    ``parting_line_v2``'s own accepted candidate, not an independent
    question this gate needs to re-ask (see D-062 hierarchy).

    Mock-safety (established project pattern, same reasoning as D-061's
    ``isinstance(face.occ_face, TopoDS_Face)`` guard): calling real
    SWIG-wrapped OCC functions on a non-OCC object (a ``MagicMock`` in
    mock-based unit tests) does not raise a catchable Python exception --
    it can hang at the native layer. Discovered directly this session:
    the existing mock-based ``test_direction_optimizer.py`` suite (3.7s
    before this function was wired into ``optimize_mold_direction``)
    hung indefinitely once it was -- confirming this guard is required,
    not optional, exactly as it was for D-061's ray verification.
    """
    from OCC.Core.TopoDS import TopoDS_Shape

    if not isinstance(part.occ_shape, TopoDS_Shape):
        # Cannot determine real feasibility against a non-OCC shape.
        # Conservative default: report NOT feasible rather than silently
        # guessing -- never claim a downstream-feasible optimum we could
        # not actually verify.
        return PartingLineFeasibilityResult(
            feasible=False, reason="occ_shape is not a real TopoDS_Shape",
            outcome="no_feasible_candidate",
        )

    from backend.geometry.parting_line_v2 import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line

    pull_direction = PullDirectionInput(direction=direction, source="optimizer")
    undercut_input = (
        UndercutInput.from_detection_result(undercuts)
        if undercuts is not None
        else UndercutInput.empty()
    )
    result = analyse_parting_line(
        part, pull_direction,
        undercuts=undercut_input,
        core_pin_face_refs=core_pin_face_refs,
        delegations=delegations,
    )
    referrals = tuple(r.to_dict() for r in result.referrals)
    if result.outcome == "feasible":
        return PartingLineFeasibilityResult(feasible=True, outcome="feasible", referrals=referrals)
    return PartingLineFeasibilityResult(
        feasible=False,
        failed_gate=result.best_rejected_failed_gate,
        reason=result.best_rejected_reason,
        outcome=result.outcome,
        referrals=referrals,
    )


#: O4 (2026-08-17): key for the feasibility memo below. Mirrors
#: ``DirectionUndercutCacheKey``'s existing shape (part signature +
#: rounded-integer direction) plus the two authorization tuples, since
#: ``_is_parting_line_feasible``'s result depends on all four -- a
#: direction that is feasible under one caller-supplied
#: ``core_pin_face_refs``/``delegations`` pair is not necessarily
#: feasible (or even meaningfully comparable) under another.
#: ``CorePinFaceRef``/``DelegatedSecondaryAction`` are both frozen
#: dataclasses with hashable fields (confirmed directly against
#: ``parting_line_v2/contracts.py`` before this was written), so the
#: tuples themselves are hashable without any custom serialization.
FeasibilityCacheKey = tuple[PartCacheSignature, int, int, int, tuple, tuple]
FeasibilityCache = dict[FeasibilityCacheKey, "PartingLineFeasibilityResult"]


def _feasibility_cache_key(
    part: PartGeometry,
    direction: Vec3,
    core_pin_face_refs: tuple,
    delegations: tuple,
) -> FeasibilityCacheKey:
    unit = normalize3(direction)
    return (
        _part_cache_signature(part),
        int(round(unit[0] * 1_000_000)),
        int(round(unit[1] * 1_000_000)),
        int(round(unit[2] * 1_000_000)),
        tuple(core_pin_face_refs),
        tuple(delegations),
    )


def _cached_is_parting_line_feasible(
    part: PartGeometry,
    direction: Vec3,
    core_pin_face_refs: tuple,
    delegations: tuple,
    cache: FeasibilityCache,
    undercuts: "UndercutDetectionResult | None" = None,
) -> "PartingLineFeasibilityResult":
    """
    O4 (2026-08-17): memoized wrapper around ``_is_parting_line_feasible``.

    Without this, seeding the search incumbent from ``initial_pull_direction``
    would cause the expensive H0-H7 ``analyse_parting_line`` pass to run
    TWICE for the common case where the initial direction coincides with a
    Stage-1 principal (e.g. the default +Z) -- once for the initial seed,
    once when Stage 1's own bound-ordered loop reaches the same direction.
    Calls the module-level ``_is_parting_line_feasible`` by name (not a
    bound/aliased reference) so existing test monkeypatches of that
    function continue to take effect through this wrapper unchanged.

    C10 (2026-08-17): ``undercuts``, when supplied, is threaded straight
    through to ``_is_parting_line_feasible`` -- not part of the cache KEY,
    because undercut evidence is itself a deterministic function of
    ``(part, direction)`` at the fixed ``max_boolean_faces`` used
    throughout one ``optimize_mold_direction`` call: a cache hit for
    ``(part, direction, core_pin_face_refs, delegations)`` always
    corresponds to the same undercut evidence too, so extending the key
    would be redundant, not safer.
    """
    key = _feasibility_cache_key(part, direction, core_pin_face_refs, delegations)
    cached = cache.get(key)
    if cached is not None:
        return cached
    result = _is_parting_line_feasible(
        part, direction, core_pin_face_refs, delegations, undercuts=undercuts,
    )
    cache[key] = result
    return result


def _select_boolean_refinement_candidates(
    scored: list[DirectionCandidateResult],
    baseline_score: float | None = None,
) -> tuple[list[DirectionCandidateResult], BooleanPruningSummary]:
    """
    Select candidates that deserve expensive swept-Boolean refinement.

    This gate is intentionally stricter than the original top-N-only pass:
    bad prefilter scores are removed by ratio/additive thresholds, the survivor
    pool is capped, and only near-ties proceed to Boolean.  A minimum keeps at
    least the best candidate refined so the final result still has geometric
    evidence.

    ``baseline_score`` (Phase 5C-1, D-051, optional): the Stage-1+2 pool's
    own already-Boolean-verified best score, when one exists. Without it,
    every threshold below is anchored ONLY to ``ordered[0]`` -- the
    cheapest score anywhere in ``scored`` -- which can itself be an
    unverified, optimistic Stage-3 cheap-only score. When that happens, a
    DIFFERENT Stage-3 candidate that is genuinely competitive with the
    real, verified baseline can be pruned purely because some unrelated
    candidate looked cheaper, never because it was actually a poor match
    for the question that matters: "could this candidate, if refined,
    change the final winner?" ``baseline_score`` gives every candidate a
    SECOND, independent chance to survive under the SAME existing
    ratio/near-tie constants, measured against that real baseline instead
    -- this can only ADD survivors relative to the no-baseline behavior,
    never remove one the existing logic already kept, and the existing
    ``max_refine``/``boolean_refine_top_candidates`` cap still applies
    afterward, so this stays bounded -- it does not make Stage 3
    exhaustive.
    """
    if not scored:
        return [], BooleanPruningSummary(
            strategy="smart-risk-gated prefilter",
            best_prefilter_score=float("inf"),
            ratio_threshold=float("inf"),
            near_tie_threshold=float("inf"),
            uncertainty_threshold=float("inf"),
            survivor_count=0,
            promising_count=0,
            pruned_count=0,
            max_refine_count=0,
            survivor_top_count=0,
            min_boolean_candidates=0,
        )

    cfg = settings.dfm.direction_search
    ordered = sorted(scored, key=lambda c: c.score)
    best_prefilter_score = ordered[0].score
    max_refine = max(0, int(cfg.boolean_refine_top_candidates))
    survivor_top_count = max(0, int(cfg.prefilter_survivor_top_count))
    min_boolean_candidates = max(0, int(cfg.prefilter_min_boolean_candidates))
    min_boolean_candidates = min(min_boolean_candidates, max_refine)
    score_margin = max(0.0, float(cfg.boolean_refine_score_margin))
    skip_factor = max(1.0, float(cfg.prefilter_skip_score_factor))
    zero_margin = max(0.0, float(cfg.prefilter_zero_score_margin))
    low_undercut_pct = max(0.0, float(cfg.prefilter_low_undercut_area_pct))
    low_bad_pct = max(0.0, float(cfg.prefilter_low_bad_area_pct))
    principal_keep_count = max(0, int(cfg.prefilter_principal_axis_keep_count))
    uncertainty_margin = max(0.0, float(cfg.prefilter_uncertainty_score_margin))

    if max_refine == 0:
        summary = BooleanPruningSummary(
            strategy="disabled",
            best_prefilter_score=best_prefilter_score,
            ratio_threshold=best_prefilter_score,
            near_tie_threshold=best_prefilter_score,
            uncertainty_threshold=best_prefilter_score,
            survivor_count=0,
            promising_count=0,
            pruned_count=len(ordered),
            max_refine_count=max_refine,
            survivor_top_count=survivor_top_count,
            min_boolean_candidates=min_boolean_candidates,
        )
        return [], summary

    if best_prefilter_score > 1e-9:
        ratio_threshold = best_prefilter_score * skip_factor
        near_tie_threshold = best_prefilter_score * (1.0 + score_margin)
    else:
        ratio_threshold = best_prefilter_score + zero_margin
        near_tie_threshold = best_prefilter_score + zero_margin

    # Phase 5C-1 (D-051): the SAME skip_factor/score_margin/zero_margin
    # constants used above, applied a second time against the Stage-1+2
    # verified baseline instead of ordered[0]. No new threshold is
    # invented here -- only a second anchor point for the existing ones.
    baseline_ratio_threshold: float | None = None
    baseline_near_tie_threshold: float | None = None
    if baseline_score is not None:
        if baseline_score > 1e-9:
            baseline_ratio_threshold = baseline_score * skip_factor
            baseline_near_tie_threshold = baseline_score * (1.0 + score_margin)
        else:
            baseline_ratio_threshold = baseline_score + zero_margin
            baseline_near_tie_threshold = baseline_score + zero_margin

    uncertainty_threshold = (
        near_tie_threshold * (1.0 + uncertainty_margin)
        if near_tie_threshold > 1e-9
        else near_tie_threshold + zero_margin * uncertainty_margin
    )
    survivor_reasons: dict[str, list[str]] = {}

    def add_reason(candidate: DirectionCandidateResult, reason: str) -> None:
        survivor_reasons.setdefault(candidate.label, [])
        if reason not in survivor_reasons[candidate.label]:
            survivor_reasons[candidate.label].append(reason)

    survivors_by_label: dict[str, DirectionCandidateResult] = {}
    baseline_rescued_labels: set[str] = set()
    for candidate in ordered:
        if candidate.score <= ratio_threshold:
            survivors_by_label[candidate.label] = candidate
            add_reason(candidate, "within ratio threshold")
        elif baseline_ratio_threshold is not None and candidate.score <= baseline_ratio_threshold:
            survivors_by_label[candidate.label] = candidate
            add_reason(
                candidate,
                f"within ratio threshold of Stage 1+2 verified baseline ({baseline_score:.6g})",
            )
            baseline_rescued_labels.add(candidate.label)

    low_risk_candidates = [
        candidate for candidate in ordered
        if (
            candidate.undercut_area_pct <= low_undercut_pct
            and candidate.bad_area_pct <= low_bad_pct
        )
    ]
    for candidate in low_risk_candidates:
        survivors_by_label[candidate.label] = candidate
        add_reason(
            candidate,
            (
                f"low-risk prefilter: undercut_area_pct={candidate.undercut_area_pct:.3f}, "
                f"bad_area_pct={candidate.bad_area_pct:.3f}"
            ),
        )

    principal_axis_candidates = [
        candidate for candidate in ordered
        if candidate.principal_axis_alignment >= 0.999
    ][:principal_keep_count]
    for candidate in principal_axis_candidates:
        survivors_by_label[candidate.label] = candidate
        add_reason(candidate, "principal-axis guard")

    uncertainty_candidates = [
        candidate for candidate in ordered
        if candidate.score <= uncertainty_threshold
    ]
    for candidate in uncertainty_candidates:
        survivors_by_label[candidate.label] = candidate
        add_reason(candidate, "near-tie uncertainty guard")

    survivors = sorted(survivors_by_label.values(), key=lambda c: c.score)
    if survivor_top_count > 0:
        survivors = survivors[:survivor_top_count]
    if len(survivors) < min_boolean_candidates:
        survivors = ordered[:min_boolean_candidates]
        for candidate in survivors:
            add_reason(candidate, "minimum Boolean candidate guard")

    guard_selected_labels = {
        label for label, reasons in survivor_reasons.items()
        if any(
            reason.startswith("low-risk prefilter")
            or reason == "principal-axis guard"
            or reason == "near-tie uncertainty guard"
            for reason in reasons
        )
    }
    promising = []
    baseline_rescued_promising_labels: set[str] = set()
    for candidate in survivors:
        if candidate.score <= near_tie_threshold or candidate.label in guard_selected_labels:
            promising.append(candidate)
        elif (
            baseline_near_tie_threshold is not None
            and candidate.score <= baseline_near_tie_threshold
        ):
            # Phase 5C-1 (D-051): competitive with the Stage 1+2 verified
            # baseline, even though not competitive with this pool's own
            # local best -- exactly the candidate this fix exists to stop
            # silently dropping.
            promising.append(candidate)
            baseline_rescued_promising_labels.add(candidate.label)
    if len(promising) < min_boolean_candidates:
        existing_labels = {candidate.label for candidate in promising}
        for candidate in survivors:
            if candidate.label not in existing_labels:
                promising.append(candidate)
                existing_labels.add(candidate.label)
            if len(promising) >= min_boolean_candidates:
                break
    for candidate in promising:
        add_reason(candidate, "selected for Boolean refinement")
    promising = promising[:max_refine]
    promising_labels = {candidate.label for candidate in promising}
    pruned_examples = []
    for candidate in ordered:
        if candidate.label in promising_labels:
            continue
        reason = "outside smart-pruning refinement set"
        if candidate.score > ratio_threshold:
            reason = "score above ratio threshold"
        elif survivor_top_count > 0 and candidate.label not in survivor_reasons:
            reason = "outside survivor guards"
        pruned_examples.append({
            "label": candidate.label,
            "score": round(candidate.score, 6),
            "reason": reason,
        })
        if len(pruned_examples) >= 8:
            break

    summary = BooleanPruningSummary(
        strategy="smart-risk-gated prefilter",
        best_prefilter_score=best_prefilter_score,
        ratio_threshold=ratio_threshold,
        near_tie_threshold=near_tie_threshold,
        uncertainty_threshold=uncertainty_threshold,
        survivor_count=len(survivors),
        promising_count=len(promising),
        pruned_count=max(0, len(ordered) - len(promising)),
        max_refine_count=max_refine,
        survivor_top_count=survivor_top_count,
        min_boolean_candidates=min_boolean_candidates,
        low_risk_candidate_count=len(low_risk_candidates),
        principal_axis_guard_count=len(principal_axis_candidates),
        uncertainty_candidate_count=len(uncertainty_candidates),
        survivor_reasons={
            label: survivor_reasons[label]
            for label in sorted(survivor_reasons)
            if label in {candidate.label for candidate in survivors}
        },
        pruned_examples=pruned_examples,
        baseline_score=baseline_score,
        baseline_ratio_threshold=baseline_ratio_threshold,
        baseline_near_tie_threshold=baseline_near_tie_threshold,
        baseline_rescued_candidate_count=len(
            baseline_rescued_promising_labels & {c.label for c in promising}
        ),
    )
    return promising, summary


def _score_direction_candidate(
    part: PartGeometry,
    direction: Vec3,
    draft_by_direction: dict[Vec3, DraftAnalysisResult],
) -> DirectionCandidateResult:
    """
    Prefilter-only scoring pass for one candidate direction.

    `mutate=False` throughout — this runs for every coarse AND fine
    candidate, and only the single final winner (in `optimize_mold_direction`)
    is ever scored with `mutate=True`. Shared by the coarse grid and the
    coarse-to-fine refinement (Phase 1d) so both use identical scoring.

    Directional metrics (n·d, draft_angle, mold_side, classification) are
    precomputed once and shared with both analyze_draft and detect_undercuts,
    eliminating the redundant per-face dot-product computations that those
    functions would otherwise each perform independently.
    """
    # Compute n·d for every face ONCE; pass the result to both consumers.
    precomputed = precompute_directional_metrics(part, direction)
    draft = analyze_draft(
        part=part,
        pull_direction=direction,
        pull_direction_label=f"candidate {_direction_label(direction)}",
        analysis_pass="candidate",
        mutate=False,
        precomputed_metrics=precomputed,
    )
    draft_by_direction[direction] = draft
    undercuts = detect_undercuts(
        part,
        direction,
        mutate=False,
        boolean_refine=False,
        precomputed_metrics=precomputed,
        draft_result=draft,
    )
    score = _score_candidate(draft, undercuts, direction, part)
    return DirectionCandidateResult(
        direction=direction,
        label=_direction_label(direction),
        score=score,
        bad_face_count=len(draft.bad_face_ids),
        marginal_face_count=len(draft.marginal_face_ids),
        good_face_count=len(draft.good_face_ids),
        bad_area_mm2=draft.bad_area_mm2,
        marginal_area_mm2=draft.marginal_area_mm2,
        total_area_mm2=draft.total_analysed_area_mm2,
        bad_area_pct=draft.bad_pct,
        marginal_area_pct=draft.marginal_pct,
        undercut_face_count=len(undercuts.undercut_face_ids),
        undercut_feature_count=len(undercuts.features),
        undercut_area_pct=undercuts.undercut_area_pct,
        boolean_refined=undercuts.boolean_refined,
        boolean_checked_count=len(undercuts.boolean_checked_face_ids),
        interference_volume_mm3=undercuts.interference_volume_mm3,
        principal_axis_alignment=_principal_axis_alignment(direction),
        accessibility_risk_area_pct=undercuts.accessibility_risk_area_pct,
    )


def _is_direction_suitable_cheap(
    candidate: DirectionCandidateResult,
    cfg: "DirectionSearchSettings",
) -> bool:
    """
    Provisional cheap suitability screen.

    A direction passes when BOTH component thresholds hold simultaneously:
    - ``bad_area_pct <= suitability_max_bad_draft_pct`` (surface orientation)
    - ``accessibility_risk_area_pct <= suitability_max_accessibility_risk_pct``
      (heuristic risk — NOT proof of undercut)

    CRITICAL NOTES:
    - All thresholds are PROVISIONAL engineering defaults, NOT Bosch
      requirements.  Bosch has not provided numerical thresholds for "suitable".
    - Passing this screen does NOT mean the direction is acceptable.  It only
      means the direction is a candidate for Boolean validation.
    - Only Boolean confirmation (``_is_direction_suitable_boolean``) determines
      actual acceptability.
    - This is a SCREENING step, never a final verdict.

    Phase 5B (2026-08-16): no longer called by ``optimize_mold_direction``'s
    Stage 1+2 (principal axes / configured diagonals), which the audit found
    this gate was excluding from Boolean verification entirely on real parts
    (e.g. every principal axis on Part1). Retained, unused, as a documented
    building block should a future phase want a similarly-shaped triage
    gate for the Stage 3 spherical grid (which currently uses the
    independent ``_select_boolean_refinement_candidates`` pruning instead).
    """
    return (
        candidate.bad_area_pct <= cfg.suitability_max_bad_draft_pct
        and candidate.accessibility_risk_area_pct <= cfg.suitability_max_accessibility_risk_pct
    )


def _is_direction_suitable_boolean(
    undercuts: UndercutDetectionResult,
    part: PartGeometry,
    cfg: "DirectionSearchSettings",
) -> bool:
    """
    Provisional Boolean-confirmation suitability check.

    Only authoritative when ``undercuts.boolean_refined=True``.  Computes
    confirmed undercut area from ``boolean_confirmed_face_ids`` ONLY —
    proxy faces (failed or skipped Boolean) are excluded.

    CRITICAL: This threshold is PROVISIONAL.  Bosch has not provided a
    numerical definition of "acceptable confirmed undercut area".  The check
    is a search-gating heuristic only — NOT a manufacturing guarantee.

    Phase 5C-3 (2026-08-16): like ``_is_direction_suitable_cheap``, this
    function's return value is currently discarded by its only call site
    (``_boolean_refine_candidates`` returns it as an unused second tuple
    element, ``refined_12, _ = _boolean_refine_candidates(...)``) — the
    authoritative acceptance decision is ``_evidence_tier``, which ALSO
    requires ``feature_acceptability == "clean"`` (D-053) and is therefore
    now stricter than this area-only check. Retained as a documented,
    currently-inert building block; do not re-wire it as an acceptance
    gate without also applying the feature-level check, or a small-but-
    critical feature (Issue #1's UC4 case) could pass here again.
    """
    if not undercuts.boolean_refined:
        return False
    return _confirmed_undercut_pct(undercuts, part) <= cfg.suitability_max_confirmed_undercut_pct


def _confirmed_undercut_pct(undercuts: UndercutDetectionResult, part: PartGeometry) -> float:
    """
    Percentage (0-100 scale, matching sibling ``*_area_pct`` fields on
    ``DirectionCandidateResult``) of analysed area confirmed as undercut via
    ``boolean_confirmed_face_ids`` ONLY -- real physical evidence, never
    proxy-only or not-applicable faces. Returns ``0.0`` when
    ``undercuts.boolean_refined`` is ``False`` -- that zero means "never
    checked", not "confirmed clean"; callers MUST consult
    ``boolean_refined``/``evidence_tier`` before reading this as evidence
    of cleanliness (Phase 5B, 2026-08-16).
    """
    if not undercuts.boolean_refined:
        return 0.0
    total_area = max(undercuts.total_analysed_area_mm2, 1.0)
    confirmed_area = sum(
        f.area for fid in undercuts.boolean_confirmed_face_ids
        if (f := part.get_face(fid)) is not None
    )
    return 100.0 * confirmed_area / total_area


# ---------------------------------------------------------------------------
# Phase 5C-3 (2026-08-16, D-053): feature-level acceptability.
#
# The Phase 5C-3 audit found `confirmed_undercut_pct`'s whole-part-area
# denominator lets a small but individually critical/major feature hide
# behind a large, otherwise-harmless part (UC4_small_deep_pocket_on_
# large_plate.stp: the exact same 800mm^2/8mm/6400mm^3 confirmed ring as
# UC3 -- identical severity="critical", is_major_feature=True,
# recommended_mold_action="draft-redesign-or-local-action-review" -- reads
# as 0.894% of UC4's much larger plate vs. 13.6% of UC3's smaller body,
# so the SAME feature is "verified_undercuts_present" on UC3 but
# "verified_acceptable" on UC4 under the pre-Phase-5C-3 area-only rule).
#
# The fix reuses undercut_detector.py's ALREADY-COMPUTED, already-tested
# per-feature classification (UndercutFeature.severity/
# recommended_mold_action/interference_volume_mm3/depth_proxy_mm, all
# derived from real Boolean-swept-volume geometry -- see
# _recommend_mold_action's docstring) instead of inventing a new
# depth/volume/severity threshold. No undercut-generation code is
# modified; only how the optimizer CONSUMES fields that already existed.
# ---------------------------------------------------------------------------

def _feature_acceptability(
    undercuts: UndercutDetectionResult,
) -> tuple[str, int, int, str]:
    """
    Classify a direction's CONFIRMED undercut features (Phase 5C-3). Three
    states, evaluated purely from already-computed per-feature evidence:

    ``"clean"``
        No feature has any Boolean-confirmed interference at all. The
        ONLY state eligible for ``evidence_tier="verified_acceptable"`` --
        matches the pre-existing "0% confirmed" case exactly, so a
        genuinely clean direction is completely unaffected by this phase.
    ``"confirmed_undercut_secondary_tooling_candidate"``
        At least one feature has confirmed interference, and every such
        feature's ``recommended_mold_action`` is a real, evidence-based
        mechanism-CLASS signal (``"side-action"``,
        ``"lifter-or-collapsible-core-review"``, or
        ``"draft-redesign-or-local-action-review"``) -- not a guess, and
        not "clean" either.

        Phase 5C-3 second investigation (2026-08-16, D-054): renamed from
        ``"secondary_tooling_required"``. That name implied a settled,
        resolvable requirement; the underlying evidence never supported
        that claim. ``recommended_mold_action`` proves only a geometric
        PATTERN (release-direction alignment class + severity) -- it is
        NOT proof that a mechanism is feasible, collision-free, actuated,
        or manufacturable. This project's own most authoritative,
        human-authorized layer (`parting_line_v2`'s
        ``DelegatedSecondaryAction`` / D-044) never claims more than
        ``geometric_verification="unverified"`` even after structural
        validation -- an unauthorized, fully-automatic heuristic here
        cannot claim more than that either. This state is therefore a
        CANDIDATE for downstream engineering review (a routing hint for
        which mechanism class to attempt authorizing via
        `parting_line_v2`'s core-pin/delegation architecture), never a
        resolvability claim. It is NOT eligible for
        ``evidence_tier="verified_acceptable"`` / ``optimal_found=True``
        on its own -- whether the direction is actually "viable with
        secondary tooling" is decided downstream, by H0-H7 plus real
        authorization, never asserted here.
    ``"requires_manual_review"``
        At least one confirmed feature's OWN evidence is unreliable
        (``recommended_mold_action == "manual-review"``, set only when
        Boolean refinement failed on that specific feature -- see
        ``_recommend_mold_action``). Distinct from ``evidence_tier ==
        "unverified"``: refinement WAS attempted for the direction as a
        whole and DID succeed for other faces; it specifically failed
        here, so this feature's severity/action cannot be trusted either
        way.

    Both non-clean states report the SINGLE most severe qualifying
    feature (by severity, then interference volume) as the explanatory
    reason -- "which feature caused this" must always be answerable, not
    buried in an aggregate percentage.

    Returns ``(state, secondary_tooling_candidate_feature_count,
    manual_review_feature_count, reason)``.
    """
    confirmed_features = [f for f in undercuts.features if f.boolean_confirmed_face_ids]
    if not confirmed_features:
        return "clean", 0, 0, ""

    manual_review = [f for f in confirmed_features if f.recommended_mold_action == "manual-review"]
    secondary_tooling_candidates = [
        f for f in confirmed_features if f.recommended_mold_action != "manual-review"
    ]

    def _severity_rank(f: "UndercutFeature") -> int:
        return {"critical": 2, "moderate": 1, "minor": 0}.get(f.severity, 0)

    if manual_review:
        worst = max(manual_review, key=lambda f: (_severity_rank(f), f.interference_volume_mm3))
        reason = (
            f"feature {worst.feature_id} ({len(worst.face_ids)} face(s), "
            f"severity={worst.severity}): Boolean refinement failed on at "
            f"least one of its faces -- evidence is unreliable here, not "
            f"merely unfavorable. {worst.action_reason}"
        )
        return (
            "requires_manual_review",
            len(secondary_tooling_candidates),
            len(manual_review),
            reason,
        )

    worst = max(secondary_tooling_candidates, key=lambda f: (_severity_rank(f), f.interference_volume_mm3))
    reason = (
        f"feature {worst.feature_id} ({len(worst.face_ids)} face(s), "
        f"severity={worst.severity}, is_major={worst.is_major_feature}, "
        f"action={worst.recommended_mold_action}, "
        f"depth~{worst.depth_proxy_mm:.2f}mm, "
        f"volume~{worst.interference_volume_mm3:.1f}mm3): {worst.action_reason} "
        f"NOT proof of feasibility -- a mechanism-class candidate for "
        f"downstream engineering review only."
    )
    return (
        "confirmed_undercut_secondary_tooling_candidate",
        len(secondary_tooling_candidates),
        0,
        reason,
    )


# ---------------------------------------------------------------------------
# Phase 5B (2026-08-16): explicit evidence-state classification.
#
# The Phase 5B audit found the dominant problem was not the detector (fixed
# in D-046/D-047) but the optimizer's search architecture: a raw-score sort
# across candidates with fundamentally different evidence quality (some
# never Boolean-verified at all) silently let an unverified candidate win
# over a verified one, and let ALL 6 principal axes on real parts (Part1,
# the UC3 fixture) be excluded from Boolean verification entirely by a
# sign-blind, easily-corrected draft-angle pre-filter. This is fixed by
# making evidence state an explicit, first-class property of every
# candidate, and comparing tier-first, score-second -- never comparing an
# unverified candidate's score against a verified one's.
# ---------------------------------------------------------------------------

#: Rank order for tiered comparison -- LOWER is better, exactly like score.
_EVIDENCE_TIER_RANK = {
    "verified_acceptable": 0,
    "verified_undercuts_present": 1,
    "unverified": 2,
}

def _evidence_tier(
    boolean_refined: bool,
    confirmed_undercut_pct: float,
    feature_acceptability: str,
    cfg: "DirectionSearchSettings",
) -> str:
    """
    Classify a candidate's evidence state (Phase 5B, extended Phase 5C-3).
    Three states -- the STRING VALUES and their rank in ``_EVIDENCE_TIER_RANK``
    are unchanged since Phase 5B; only the RULE for which one applies is
    updated:

    ``"verified_acceptable"``
        Boolean-verified, confirmed undercut area within the aggregate
        area threshold, AND ``feature_acceptability == "clean"`` (Phase
        5C-3: no individual feature has any confirmed interference at
        all, regardless of how small). The ONLY tier eligible to be
        reported as a validated optimum (``optimal_found=True``).
    ``"verified_undercuts_present"``
        Boolean-verified, but EITHER the aggregate area exceeds the
        threshold OR at least one feature has confirmed interference
        (``feature_acceptability != "clean"``) -- real, unfavorable
        evidence. This is deliberately the SAME tier for "large aggregate
        area", "small-but-real feature", AND "plausible secondary-tooling
        candidate" cases: all mean "not zero-action-required," and NONE
        of them is a proven-feasible claim (Phase 5C-3 second
        investigation, D-054 -- see ``_feature_acceptability``'s
        docstring: even this project's own human-authorized,
        structurally-validated ``DelegatedSecondaryAction`` mechanism
        never claims more than ``geometric_verification="unverified"``,
        so an automatic heuristic here cannot claim resolvability either).
        Read ``feature_acceptability`` alongside this tier for WHY it
        landed here -- ``"confirmed_undercut_secondary_tooling_candidate"``
        (a real, evidence-based mechanism-class signal worth a downstream
        engineering attempt) is a different diagnostic than
        ``"requires_manual_review"`` (evidence itself is unreliable) or a
        large confirmed area with no single dominant feature -- but none
        of the three is ``optimal_found``-eligible on its own; whether a
        direction is ACTUALLY viable with secondary tooling is decided
        downstream, by real H0-H7 evaluation plus authorization, never
        asserted here.
    ``"unverified"``
        Never Boolean-refined at all. ``confirmed_undercut_pct`` is 0.0
        here by construction, and that MUST NOT be read as "confirmed
        clean" -- it means the question was never asked.

    Phase 5C-3 (D-053) rationale: the aggregate area check alone let a
    small-but-critical feature (e.g. a 6400mm^3 confirmed interference
    that reads as 0.894% of a large plate) reach "verified_acceptable" --
    the exact same feature, on a smaller part, reads as 13.6% and
    correctly fails. Requiring BOTH checks means a genuinely clean
    direction (feature_acceptability=="clean") is completely unaffected;
    only directions that were WRONGLY "verified_acceptable" despite a
    real confirmed feature are corrected -- never the reverse.
    """
    if not boolean_refined:
        return "unverified"
    if (
        feature_acceptability == "clean"
        and confirmed_undercut_pct <= cfg.suitability_max_confirmed_undercut_pct
    ):
        return "verified_acceptable"
    return "verified_undercuts_present"


def _comparator_key(
    c: "DirectionCandidateResult",
) -> tuple[int, float, float, float, tuple[float, float, float]]:
    """
    Phase 5C-2 (D-052) decision hierarchy for "which candidate is optimal":

    1. Evidence tier (unchanged, Phase 5B) -- an unverified candidate can
       never outrank a verified one, regardless of score.
    2. Raw score (unchanged, Milestone 4's formula) -- decides between
       candidates in the same tier whenever their scores genuinely
       differ, by ANY amount. A materially better score always wins;
       nothing below this line is ever consulted unless tier AND score
       are BOTH exactly tied.
    3. accessibility_risk_area_pct -- real, already-computed geometric
       evidence (D-047) that the Boolean-refined score formula
       deliberately excludes once confirmed-undercut evidence exists
       (see _score_candidate's docstring: the two signals are kept
       independent by design). Previously discarded entirely once a
       score-level tie occurred (observed for real on Plastic Cover.STEP:
       three candidates tied at an identical score with risk ranging
       12%-44% between them, resolved before this phase by list order).
    4. Tooling-axis practicality (1 - principal_axis_alignment, i.e. 0 for
       a perfect principal axis, larger for an off-axis direction) --
       ONLY consulted once tier, score, AND accessibility risk are ALL
       exactly tied. This is deliberately NOT a weighted score term
       (Phase 5C-2 audit finding: at its previous weight,
       scoring_axis_preference=0.25, it could never be numerically
       decisive against terms weighted 200-4000x larger; raising the
       weight enough to matter would risk it overriding a real
       draft/undercut difference, violating requirement 3 below). As a
       lexicographic tie-breaker it is mathematically guaranteed to
       never activate unless every more-important signal has already
       failed to distinguish the candidates -- i.e. it can only ever
       decide among candidates that are otherwise equally good.
    5. direction (the candidate's own unique unit vector, guaranteed
       distinct per candidate by _dedupe_direction) -- a final,
       arbitrary-but-DETERMINISTIC tie-breaker for the residual case
       where two candidates are equal on every signal above (e.g.
       genuinely mirror-symmetric geometry). This is what guarantees
       requirement 5/6: exact ties never depend on list/iteration order,
       and repeated runs on the same input always pick the same winner,
       because Python's tuple comparison plus this fully-unique final
       field make the key a strict total order -- there is no longer any
       tie for `min()` to break arbitrarily.
    """
    return (
        _EVIDENCE_TIER_RANK[c.evidence_tier],
        c.score,
        c.accessibility_risk_area_pct,
        1.0 - c.principal_axis_alignment,
        c.direction,
    )


def _tiered_best(candidates: list["DirectionCandidateResult"]) -> "DirectionCandidateResult | None":
    """
    Best candidate by the full decision hierarchy in `_comparator_key`:
    evidence tier, then raw score, then accessibility risk, then
    tooling-axis practicality, then direction -- each level consulted
    only when every earlier level is exactly tied. Never lets an
    unverified candidate's score win against a verified one's, and never
    lets axis preference override a real tier/score/risk difference.
    """
    if not candidates:
        return None
    return min(candidates, key=_comparator_key)


def _build_refined_candidate(
    direction: Vec3,
    draft: DraftAnalysisResult,
    undercuts: UndercutDetectionResult,
    part: PartGeometry,
    cfg: "DirectionSearchSettings",
) -> DirectionCandidateResult:
    """Build a DirectionCandidateResult from Boolean-refined undercut data."""
    if undercuts.evaluation_failed:
        # O22 Rule 5/7: a failed isolated evaluation is neither clean nor
        # infeasible nor verified -- it gets the SAME "unverified" tier as
        # "never Boolean-refined" (see _evidence_tier's docstring), so the
        # existing `evidence_tier != "verified_acceptable"` checks at every
        # call site already exclude it from _tiered_best/best_feasible/
        # optimal_found with zero control-flow changes. score=inf ensures
        # it never outranks a genuinely-scored unverified candidate either.
        return DirectionCandidateResult(
            direction=direction,
            label=_direction_label(direction),
            score=float("inf"),
            bad_face_count=len(draft.bad_face_ids),
            marginal_face_count=len(draft.marginal_face_ids),
            good_face_count=len(draft.good_face_ids),
            bad_area_mm2=draft.bad_area_mm2,
            marginal_area_mm2=draft.marginal_area_mm2,
            total_area_mm2=draft.total_analysed_area_mm2,
            bad_area_pct=draft.bad_pct,
            marginal_area_pct=draft.marginal_pct,
            undercut_face_count=0,
            undercut_feature_count=0,
            undercut_area_pct=0.0,
            boolean_refined=False,
            boolean_checked_count=0,
            interference_volume_mm3=0.0,
            principal_axis_alignment=_principal_axis_alignment(direction),
            accessibility_risk_area_pct=undercuts.accessibility_risk_area_pct,
            confirmed_undercut_pct=0.0,
            evidence_tier="unverified",
            feature_acceptability="clean",
            secondary_tooling_feature_count=0,
            manual_review_feature_count=0,
            feature_acceptability_reason=f"evaluation failed: {undercuts.evaluation_error}",
            evaluation_failed=True,
            evaluation_error=undercuts.evaluation_error,
        )
    refined_score = _score_candidate(draft, undercuts, direction, part)
    confirmed_pct = _confirmed_undercut_pct(undercuts, part)
    acceptability, secondary_count, manual_review_count, acceptability_reason = (
        _feature_acceptability(undercuts)
    )
    return DirectionCandidateResult(
        direction=direction,
        label=_direction_label(direction),
        score=refined_score,
        bad_face_count=len(draft.bad_face_ids),
        marginal_face_count=len(draft.marginal_face_ids),
        good_face_count=len(draft.good_face_ids),
        bad_area_mm2=draft.bad_area_mm2,
        marginal_area_mm2=draft.marginal_area_mm2,
        total_area_mm2=draft.total_analysed_area_mm2,
        bad_area_pct=draft.bad_pct,
        marginal_area_pct=draft.marginal_pct,
        undercut_face_count=len(undercuts.undercut_face_ids),
        undercut_feature_count=len(undercuts.features),
        undercut_area_pct=undercuts.undercut_area_pct,
        boolean_refined=undercuts.boolean_refined,
        boolean_checked_count=len(undercuts.boolean_checked_face_ids),
        interference_volume_mm3=undercuts.interference_volume_mm3,
        principal_axis_alignment=_principal_axis_alignment(direction),
        accessibility_risk_area_pct=undercuts.accessibility_risk_area_pct,
        confirmed_undercut_pct=confirmed_pct,
        evidence_tier=_evidence_tier(undercuts.boolean_refined, confirmed_pct, acceptability, cfg),
        feature_acceptability=acceptability,
        secondary_tooling_feature_count=secondary_count,
        manual_review_feature_count=manual_review_count,
        feature_acceptability_reason=acceptability_reason,
    )


def _record_side_action_referrals(
    side_action_referrals: list[dict],
    seen_referral_keys: set[tuple],
    direction: Vec3,
    feasibility: "PartingLineFeasibilityResult",
) -> None:
    """
    C12 (2026-08-17): append (direction, SideActionReferral) diagnostics
    from ``feasibility.referrals`` (already the unmodified
    ``SideActionReferral.to_dict()`` output -- see
    ``PartingLineFeasibilityResult.referrals``) to ``side_action_referrals``,
    deduplicated via ``seen_referral_keys`` so the same direction visited
    more than once (the O4 initial-direction seed re-checking a direction
    Stage 1+2 also reaches, or any feasibility-cache hit) never produces a
    duplicate diagnostic entry. Mutates both list/set arguments in place;
    never touches ``SideActionReferral`` itself, never calls ``side_core``.
    """
    if not feasibility.referrals:
        return
    direction_key = tuple(int(round(v * 1_000_000)) for v in direction)
    for referral in feasibility.referrals:
        dedup_key = (
            direction_key,
            tuple(referral.get("feature_ids", ())),
            tuple(referral.get("conflicting_segment_ids", ())),
            round(float(referral.get("conflict_length_mm", 0.0)), 6),
        )
        if dedup_key in seen_referral_keys:
            continue
        seen_referral_keys.add(dedup_key)
        side_action_referrals.append({
            "direction": list(direction),
            "direction_label": _direction_label(direction),
            "referral": referral,
        })


def optimize_mold_direction(
    part: PartGeometry,
    angular_step_deg: float | None = None,
    max_candidates: int | None = None,
    initial_pull_direction: Vec3 = (0.0, 0.0, 1.0),
    initial_label: str | None = None,
    core_pin_face_refs: tuple = (),
    delegations: tuple = (),
) -> DirectionOptimizationResult:
    """
    Find the best candidate mold opening direction for Level 1.

    ``core_pin_face_refs``/``delegations`` (O3, 2026-08-17): optional,
    caller-supplied ``CorePinFaceRef``/``DelegatedSecondaryAction`` tuples
    -- the exact existing ``parting_line_v2.contracts`` authorization
    types, never invented or auto-discovered here. Threaded unchanged
    into every downstream-feasibility check
    (``_is_parting_line_feasible`` -> ``analyse_parting_line``). Default
    ``()`` on both is byte-identical to pre-O3 behavior: a part needing
    no authorization (e.g. Part1) is completely unaffected. A part whose
    H3/H4 gates structurally require authorization (e.g. Part3's coaxial
    bore) can only be found feasible here if the CALLER already holds
    that authorization and supplies it -- this function still never
    constructs, infers, or validates the authorization itself; that
    remains entirely ``parting_line_v2``'s own responsibility.

    Milestone 3: Hierarchical search (when ``hierarchical_search_enabled=True``).

    Stage 1 — 6 principal ±X/Y/Z directions (Bosch preferred):
      Cheap-screen each (draft + accessibility risk).  If any pass, Boolean
      refine them.  If Boolean confirms acceptability, return immediately.

    Stage 2 — Configurable diagonal directions (default: 12 face-diagonals):
      Score new directions cheaply.  Boolean-refine any cheap-screen passes
      not yet refined.  If Boolean confirms acceptability, return immediately.

    Stage 3 — Remaining spherical candidates (existing coarse-to-fine search):
      Score all remaining directions, run fine search around top-K, apply
      the existing Boolean pruning gate, and select the best available
      direction (even if no direction is fully acceptable).

    When ``hierarchical_search_enabled=False``, the flat 54-candidate
    behavior is preserved exactly (backward compatible).

    The initial-direction draft/undercut result is computed with
    ``mutate=False``; the final best direction result is computed with
    ``mutate=True``, so ``part.faces`` holds the active optimal overlay
    after this call.

    O4 (2026-08-17): when ``hierarchical_search_enabled=True``, the
    already-computed initial-direction evidence above is also used to seed
    the Stage 1+2 incumbent (``best_feasible``) -- but ONLY when it is
    itself both evidence-verified (``evidence_tier=="verified_acceptable"``)
    and parting_line_v2-feasible, exactly the same two gates every other
    candidate must pass. This changes WHEN an incumbent first exists (and
    therefore how much of the bound-ordered Stage 1+2 loop is prunable),
    never WHAT wins: the seeded candidate still competes against every
    other non-pruned candidate through the unmodified ``_tiered_best``
    comparator. ``initial_draft``/``initial_undercuts`` on the returned
    result keep their original "before optimization" meaning regardless.
    """
    t_start = time.perf_counter()
    cfg = settings.dfm.direction_search
    initial_direction = normalize3(initial_pull_direction)
    initial_direction_label = initial_label or f"initial {_direction_label(initial_direction)}"
    boolean_volume_cache: BooleanVolumeCache = {}
    direction_undercut_cache: DirectionUndercutCache = {}
    feasibility_cache: FeasibilityCache = {}
    direction_cache_hits = 0
    direction_cache_misses = 0
    evaluation_failures: list[dict] = []
    side_action_referrals: list[dict] = []
    seen_referral_keys: set[tuple] = set()

    initial = analyze_initial_draft_no_mutation(
        part,
        pull_direction=initial_direction,
        pull_direction_label=initial_direction_label,
    )
    initial_undercuts, cache_hit = _cached_detect_boolean_undercuts(
        part=part,
        direction=initial_direction,
        direction_cache=direction_undercut_cache,
        boolean_volume_cache=boolean_volume_cache,
        mutate=False,
        max_boolean_faces=cfg.boolean_refine_max_faces,
    )
    if cache_hit:
        direction_cache_hits += 1
    else:
        direction_cache_misses += 1
    if initial_undercuts.evaluation_failed:
        evaluation_failures.append({
            "direction_label": initial_direction_label,
            "method": initial_undercuts.method,
            "error": initial_undercuts.evaluation_error,
        })

    scored: list[DirectionCandidateResult] = []
    draft_by_direction: dict[Vec3, DraftAnalysisResult] = {}
    seen_directions: set[tuple[int, int, int]] = set()
    search_stage_reached = 3
    pruning_summary: BooleanPruningSummary | None = None
    # Populated inside the hierarchical-search block below; stay empty sets
    # (never None) when hierarchical_search_enabled=False so the final
    # tail's stage-attribution check is always safe to evaluate.
    stage1_labels: set[str] = set()
    stage2_labels: set[str] = set()
    # O4 (2026-08-17): labels resolved ONLY via the initial-direction seed
    # (i.e. initial_pull_direction is not one of Stage 1/2's configured
    # directions -- see the hierarchical-search block below). Stays empty
    # whenever the initial direction coincides with a Stage-1/2 candidate
    # (the common default-+Z case) or hierarchical search is disabled.
    initial_only_labels: set[str] = set()
    # Phase 5C-1 (D-051): same "always empty/None, never undefined" pattern
    # as stage1_labels/stage2_labels above -- winner_12 is only assigned
    # inside the hierarchical-search block, but the Stage-3 coverage fix
    # below needs to reference it (as an optional Boolean-refinement
    # pruning baseline) regardless of hierarchical_search_enabled.
    winner_12: "DirectionCandidateResult | None" = None
    # O4 (2026-08-17): the initial-direction candidate, built for free from
    # `initial`/`initial_undercuts` above (already computed regardless of
    # this phase), and the incumbent it seeds -- ONLY when the initial
    # direction is itself evidence-verified AND parting_line_v2-feasible,
    # exactly the same two gates every other candidate must pass (see
    # docs/DECISIONS_AND_ALGORITHMS.md D-062/O4). This does not receive any
    # special pruning treatment: it is compared against every other
    # candidate through the SAME unmodified _tiered_best comparator used
    # everywhere else in this function.
    best_feasible: "DirectionCandidateResult | None" = None
    if cfg.hierarchical_search_enabled:
        initial_candidate = _build_refined_candidate(
            initial_direction, initial, initial_undercuts, part, cfg,
        )
        if initial_candidate.evidence_tier == "verified_acceptable":
            initial_feasibility = _cached_is_parting_line_feasible(
                part, initial_direction, core_pin_face_refs, delegations,
                feasibility_cache, undercuts=initial_undercuts,
            )
            _record_side_action_referrals(
                side_action_referrals, seen_referral_keys, initial_direction, initial_feasibility,
            )
            if initial_feasibility.feasible:
                best_feasible = initial_candidate

    # ── Helper: Boolean-refine a list of cheap-screened candidates ────────
    def _boolean_refine_candidates(
        candidates_to_refine: list[DirectionCandidateResult],
    ) -> tuple[list[DirectionCandidateResult], list[DirectionCandidateResult]]:
        """
        Run Boolean refinement on candidates and return (refined_list, acceptable_list).

        ``refined_list`` contains the updated DirectionCandidateResults (Boolean data),
        in the SAME order as ``candidates_to_refine`` -- never child-completion
        order. ``acceptable_list`` contains those that also pass the Boolean
        suitability check (PROVISIONAL threshold — NOT a manufacturing guarantee).

        O24 (2026-08-17): internally evaluates up to
        ``cfg.direction_parallelism`` candidates concurrently, each via
        O22's isolated fresh-child mechanism (``_cached_detect_boolean_
        undercuts``). Threads only dispatch/await the child subprocess
        calls (which release the GIL) -- the expensive OCC work still runs
        in separate, single-use OS processes exactly as in strictly
        sequential (``direction_parallelism=1``) execution; this is
        "bounded parallel evaluation with conservative batch boundaries"
        (see docs/DECISIONS_AND_ALGORITHMS.md O24), not a redesign of the
        search algorithm. Each candidate in ``candidates_to_refine`` has
        already passed the caller's O2 pruning check against the CURRENT
        incumbent before being included here -- this function never
        re-applies or bypasses that check itself.

        Uses the shared caches; updates direction_cache_hits/misses via nonlocal.
        """
        nonlocal direction_cache_hits, direction_cache_misses
        parallelism = max(1, int(cfg.direction_parallelism))
        detect_results: list[tuple[UndercutDetectionResult, bool] | None] = (
            [None] * len(candidates_to_refine)
        )

        def _dispatch(slot: int, candidate: DirectionCandidateResult) -> None:
            detect_results[slot] = _cached_detect_boolean_undercuts(
                part=part,
                direction=candidate.direction,
                direction_cache=direction_undercut_cache,
                boolean_volume_cache=boolean_volume_cache,
                mutate=False,
                max_boolean_faces=cfg.boolean_refine_max_faces,
            )

        for chunk_start in range(0, len(candidates_to_refine), parallelism):
            chunk = candidates_to_refine[chunk_start:chunk_start + parallelism]
            threads = [
                threading.Thread(target=_dispatch, args=(chunk_start + j, c))
                for j, c in enumerate(chunk)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        refined: list[DirectionCandidateResult] = []
        acceptable: list[DirectionCandidateResult] = []
        for candidate, detected in zip(candidates_to_refine, detect_results):
            assert detected is not None
            undercuts, hit = detected
            direction = candidate.direction
            draft = draft_by_direction[direction]
            if hit:
                direction_cache_hits += 1
            else:
                direction_cache_misses += 1
            if undercuts.evaluation_failed:
                evaluation_failures.append({
                    "direction_label": candidate.label,
                    "method": undercuts.method,
                    "error": undercuts.evaluation_error,
                })
            updated = _build_refined_candidate(direction, draft, undercuts, part, cfg)
            refined.append(updated)
            if _is_direction_suitable_boolean(undercuts, part, cfg):
                acceptable.append(updated)
        return refined, acceptable

    if cfg.hierarchical_search_enabled:
        # ── Stage 1+2: principal axes + configured diagonals ───────────────
        # Phase 5B (2026-08-16): these are ALWAYS Boolean-refined now,
        # regardless of the cheap bad_pct/accessibility_risk_pct screen.
        # The Phase 5B audit found that gate excluded ALL 6 principal axes
        # from Boolean verification on real parts (Part1: bad_pct 43-72% on
        # every axis, all far over the 30% threshold) -- meaning the one
        # mechanism that can actually confirm or deny real undercut risk
        # was never even attempted for the directions with the strongest
        # manufacturing precedent (principal-axis tooling). The cheap
        # metrics (bad_pct, accessibility_risk_pct) are NOT removed -- they
        # remain in every candidate's score and report, and the cheap
        # screen still gates the Stage-3 spherical grid below, where
        # verifying every point really would be too expensive.
        principal_directions = [
            (1.0, 0.0, 0.0), (-1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0), (0.0, -1.0, 0.0),
            (0.0, 0.0, 1.0), (0.0, 0.0, -1.0),
        ]
        stage1_labels: set[str] = set()
        for raw_dir in principal_directions:
            d = normalize3(raw_dir)
            if _dedupe_direction(d, seen_directions):
                candidate = _score_direction_candidate(part, d, draft_by_direction)
                scored.append(candidate)
                stage1_labels.add(candidate.label)

        stage2_labels: set[str] = set()
        for raw_dir in cfg.stage2_directions:
            d = normalize3(raw_dir)
            if _dedupe_direction(d, seen_directions):
                candidate = _score_direction_candidate(part, d, draft_by_direction)
                scored.append(candidate)
                stage2_labels.add(candidate.label)

        stage12_candidates = [c for c in scored if c.label in stage1_labels or c.label in stage2_labels]

        # O4 (2026-08-17): a caller-supplied initial_pull_direction that is
        # NOT one of the 6 principals or cfg.stage2_directions must still
        # be a legitimate, fully-participating candidate -- it must not
        # silently disappear just because stage12_candidates above is
        # built from stage1_labels/stage2_labels alone. Checked via
        # _dedupe_direction against the SAME seen_directions set Stage 1/2
        # generation just populated (never pre-seeded before that
        # generation ran -- doing so would have suppressed the genuine
        # Stage-1 +Z candidate whenever initial_pull_direction defaults to
        # +Z, the common case). A True return here means the initial
        # direction is genuinely absent from the 18 configured directions;
        # it also marks it seen so the Stage-3 fallback below (if reached)
        # does not separately re-generate the same direction.
        if _dedupe_direction(initial_direction, seen_directions):
            stage12_candidates = stage12_candidates + [initial_candidate]
            scored = scored + [initial_candidate]
            initial_only_labels = {initial_candidate.label}
            # _common_lower_bound (used by the bound-ordered sort just
            # below) looks up draft_by_direction[c.direction] for every
            # stage12_candidates entry -- populate it here from the
            # already-computed `initial` draft, exactly as
            # _score_direction_candidate does for every other candidate.
            draft_by_direction[initial_direction] = initial

        # D-062 (2026-08-16): bound-driven adaptive evaluation, replacing
        # the previous unconditional batch Boolean-refinement of all 18
        # Stage 1+2 candidates. Ordered ascending by _common_lower_bound
        # (a mathematically exact lower bound on each candidate's eventual
        # Boolean-refined score -- see that function's docstring for the
        # proof, re-verified directly against the live _score_candidate
        # source before this was written). A candidate is fully evaluated
        # (Boolean/ray refinement, THEN parting_line_v2 feasibility -- the
        # missing downstream signal this phase adds) only if its bound is
        # still strictly less than the best FEASIBLE score found so far;
        # once every remaining candidate's bound is >= that incumbent, no
        # untested candidate can possibly beat it, so evaluation stops.
        # Deliberately a strict "<" comparison, not "<=": at an EXACT
        # bound/incumbent tie, the untested candidate's actual score could
        # still equal the incumbent's, in which case _tiered_best's own
        # further tiebreakers (accessibility risk, axis alignment,
        # direction -- unmodified) must be allowed to run, not be
        # bypassed by pruning.
        stage12_ordered = sorted(stage12_candidates, key=lambda c: _common_lower_bound(
            draft_by_direction[c.direction], c.direction, part,
        ))
        stage12_final: list[DirectionCandidateResult] = []
        # O4 (2026-08-17): NOT reset to None here -- best_feasible may
        # already be seeded from initial_pull_direction above. Evaluating
        # a candidate first is not pruning: this loop's own pruning
        # condition and _tiered_best update below are byte-identical to
        # before this phase, so the incumbent's origin (seed vs. discovered
        # here) never changes what gets pruned or who wins a tie.
        stage12_pruned_count = 0
        # O24 (2026-08-17): BOUNDED PARALLEL EVALUATION WITH CONSERVATIVE
        # BATCH BOUNDARIES -- not "O2-preserving pruning" (deliberately not
        # called that; see docs/DECISIONS_AND_ALGORITHMS.md O24). Candidates
        # are still walked in the SAME ascending bound order as strictly
        # sequential (direction_parallelism=1) execution, and the SAME
        # pruning check runs against the CURRENT best_feasible before a
        # candidate is ever added to a batch -- so nothing sequential would
        # prune is ever launched. Within one batch (size <=
        # cfg.direction_parallelism), a candidate's mid-batch batch-mates
        # may improve best_feasible AFTER this batch's candidates were
        # already dispatched; such a candidate is NOT re-checked until the
        # NEXT batch forms. This can evaluate a few extra candidates beyond
        # where strict sequential execution would have stopped -- but by
        # _common_lower_bound's own soundness proof, any such candidate's
        # bound already exceeded SOME valid incumbent score, so its true
        # score is provably no better than that incumbent; merging it via
        # the unmodified _tiered_best comparator below is therefore always
        # a safe no-op for the final winner, never a change to it. Batch
        # results are merged back in ORIGINAL bound order (never child-
        # completion order) via _boolean_refine_candidates's own ordering
        # guarantee, so who happens to finish first has no effect on
        # best_feasible/stage12_final.
        direction_parallelism = max(1, int(cfg.direction_parallelism))
        idx = 0
        n_ordered = len(stage12_ordered)
        while idx < n_ordered:
            batch: list[DirectionCandidateResult] = []
            while idx < n_ordered and len(batch) < direction_parallelism:
                candidate = stage12_ordered[idx]
                if best_feasible is not None and _common_lower_bound(
                    draft_by_direction[candidate.direction], candidate.direction, part,
                ) > best_feasible.score:
                    stage12_pruned_count += n_ordered - idx
                    idx = n_ordered
                    break
                batch.append(candidate)
                idx += 1
            if not batch:
                break
            refined_list, _ = _boolean_refine_candidates(batch)
            for refined_candidate in refined_list:
                stage12_final.append(refined_candidate)
                if refined_candidate.evidence_tier != "verified_acceptable":
                    continue
                # The missing downstream signal (D-062's core finding): a
                # direction reaching evidence_tier=="verified_acceptable" is
                # NOT automatically eligible to be the final optimum -- it
                # must also be feasible for parting_line_v2's own H0-H7 gates,
                # demonstrated (not assumed) to be a genuinely different
                # question on Part1 (a diagonal reaching verified_acceptable
                # while parting_line_v2 independently rejects it).
                candidate_undercuts = _cached_undercuts_for_feasibility(
                    part, refined_candidate.direction, direction_undercut_cache,
                    cfg.boolean_refine_max_faces,
                )
                feasibility = _cached_is_parting_line_feasible(
                    part, refined_candidate.direction, core_pin_face_refs, delegations,
                    feasibility_cache, undercuts=candidate_undercuts,
                )
                _record_side_action_referrals(
                    side_action_referrals, seen_referral_keys, refined_candidate.direction, feasibility,
                )
                if not feasibility.feasible:
                    continue
                if best_feasible is None:
                    best_feasible = refined_candidate
                else:
                    # Reuse the existing, unmodified comparator -- never a
                    # bespoke score-only comparison -- so accessibility-risk/
                    # axis/direction tiebreakers still apply exactly as before.
                    best_feasible = _tiered_best([best_feasible, refined_candidate])

        refined_map = {c.label: c for c in stage12_final}
        scored = [refined_map.get(c.label, c) for c in scored]

        winner_12 = best_feasible
        if winner_12 is not None:
            # Genuine early exit: a candidate that is BOTH evidence-
            # verified AND parting-line-feasible was found among the
            # principal axes / configured diagonals. Stage 3 is skipped,
            # preserving the original design's cost-saving intent -- the
            # difference is WHAT was required to exit early (verified AND
            # feasible) rather than merely "verified_acceptable" (D-062).
            # O4 (2026-08-17): explicit three-way check, not the old binary
            # ternary -- stage12_candidates can now also contain a
            # genuinely custom initial_pull_direction (absent from both
            # label sets), which must be attributed to "initial" (0), never
            # misreported as Stage 2.
            if winner_12.label in stage1_labels:
                search_stage_reached = 1
            elif winner_12.label in stage2_labels:
                search_stage_reached = 2
            else:
                search_stage_reached = 0
            best_direction = winner_12.direction
            best_score = winner_12.score
            optimal = analyze_draft(
                part=part,
                pull_direction=best_direction,
                pull_direction_label=f"best candidate {_direction_label(best_direction)}",
                analysis_pass="optimal",
                mutate=True,
            )
            optimal_undercuts, cache_hit = _cached_detect_boolean_undercuts(
                part=part,
                direction=best_direction,
                direction_cache=direction_undercut_cache,
                boolean_volume_cache=boolean_volume_cache,
                mutate=True,
                max_boolean_faces=cfg.boolean_refine_max_faces,
            )
            if cache_hit:
                direction_cache_hits += 1
            else:
                direction_cache_misses += 1
            part.optimal_pull_direction = best_direction
            part.direction_score = best_score
            part.inaccessible_face_ids = list(optimal_undercuts.undercut_face_ids)
            scored.sort(key=lambda c: c.score)
            return DirectionOptimizationResult(
                best_direction=best_direction,
                best_label=_direction_label(best_direction),
                best_score=best_score,
                initial_pull_direction=initial_direction,
                initial_label=initial_direction_label,
                initial_draft=initial,
                initial_undercuts=initial_undercuts,
                optimal_draft=optimal,
                optimal_undercuts=optimal_undercuts,
                candidates=scored,
                boolean_refined_candidate_count=sum(1 for c in scored if c.boolean_refined),
                boolean_pruned_candidate_count=stage12_pruned_count,
                boolean_survivor_candidate_count=sum(
                    1 for c in stage12_final if c.evidence_tier == "verified_acceptable"
                ),
                boolean_promising_candidate_count=len(stage12_final),
                boolean_pruning_summary=None,
                direction_cache_hits=direction_cache_hits,
                direction_cache_misses=direction_cache_misses,
                direction_cache_entries=len(direction_undercut_cache),
                direction_cache_final_reused=cache_hit,
                boolean_volume_cache_entries=len(boolean_volume_cache),
                search_stage_reached=search_stage_reached,
                analysis_time_s=time.perf_counter() - t_start,
                optimal_found=True,
                best_evidence_tier=winner_12.evidence_tier,
                best_unverified_candidate=None,
                evaluation_failures=evaluation_failures,
                side_action_referrals=side_action_referrals,
            )
        # No verified-acceptable candidate among Stage 1+2: fall through to
        # Stage 3. stage12_final (all Boolean-refined, tier known either
        # way) stays in `scored` and participates in the final tiered
        # comparison below alongside whatever Stage 3 finds.

        # ── Stage 3: Remaining spherical candidates (fallthrough) ─────────
        # Add any spherical candidates not yet in scored.

    # Generate full candidate set (all stages or flat search)
    all_candidates = generate_candidate_directions(angular_step_deg, max_candidates)
    if not all_candidates:
        raise ValueError("No candidate directions generated.")

    for direction in all_candidates:
        d = normalize3(direction)
        if _dedupe_direction(d, seen_directions):
            scored.append(_score_direction_candidate(part, d, draft_by_direction))

    scored.sort(key=lambda c: c.score)

    # ── Coarse-to-fine search (Roadmap Phase 1d, Gap 2) ─────────────────────
    # A uniform coarse grid can miss an optimum sitting a few degrees off a
    # sampled direction. Sample a local cone around each of the top-K coarse
    # winners, at a finer angular step, using the SAME prefilter-only scoring
    # (mutate=False, boolean_refine=False) as the coarse stage — no extra
    # Boolean cost here. Boolean refinement (below) still runs only on the
    # merged shortlist via the existing pruning guards.
    if cfg.fine_search_enabled and cfg.fine_search_top_k > 0:
        fine_directions: list[Vec3] = []
        for winner in scored[: cfg.fine_search_top_k]:
            fine_directions.extend(
                generate_fine_candidate_directions(
                    base_direction=winner.direction,
                    cone_half_angle_deg=cfg.fine_search_cone_half_angle_deg,
                    angular_step_deg=cfg.fine_angular_step_deg,
                    seen=seen_directions,
                )
            )
            if len(fine_directions) >= cfg.fine_search_max_candidates:
                break
        fine_directions = fine_directions[: cfg.fine_search_max_candidates]

        for direction in fine_directions:
            scored.append(_score_direction_candidate(part, direction, draft_by_direction))

        scored.sort(key=lambda c: c.score)

    # Phase 5C-1 (D-051): thread the Stage-1+2 pool's own verified-best
    # score (if any) through as the Stage-3 pruning baseline -- None when
    # hierarchical search is disabled, or Stage 1+2 produced no candidate
    # at all, in which case this is a no-op and behavior is unchanged.
    promising, pruning_summary = _select_boolean_refinement_candidates(
        scored, baseline_score=(winner_12.score if winner_12 is not None else None)
    )

    # O24: Stage 3's own refine loop has no incremental pruning (unlike
    # Stage 1+2 -- `promising` is a fixed list already fully decided by
    # `_select_boolean_refinement_candidates` above, and no candidate's
    # result here ever changes whether another candidate in the same list
    # gets evaluated). It is therefore safe to hand the WHOLE list to the
    # same bounded-parallel helper at once (internally chunked to
    # cfg.direction_parallelism) with no batch-boundary caveat at all.
    refined_list, _ = _boolean_refine_candidates(promising)
    refined_by_label: dict[str, DirectionCandidateResult] = {
        candidate.label: refined_candidate
        for candidate, refined_candidate in zip(promising, refined_list)
    }

    scored = [refined_by_label.get(candidate.label, candidate) for candidate in scored]
    scored.sort(key=lambda c: c.score)

    # Phase 5B (requirement D/E): final selection across the FULL
    # accumulated pool (Stage 1+2, always Boolean-refined above, plus
    # whichever Stage 3 candidates were promoted to Boolean refinement by
    # the existing pruning gate) is tier-first, score-second -- never a
    # bare `scored[0]` after a raw-score sort, which would silently let an
    # unverified candidate outrank a verified one whenever its cheap-only
    # score happened to be numerically lower.
    winner = _tiered_best(scored)
    assert winner is not None, "scored is never empty here -- generate_candidate_directions raises otherwise"
    best_direction = winner.direction
    best_score = winner.score
    # D-062: reached only when Stage 1+2's own bound-driven, feasibility-
    # gated loop above found nothing feasible (see that block) and Stage 3
    # ran. The existing Stage 3 candidate-generation/pruning mechanism
    # itself is unchanged (explicitly preserved) -- this applies the SAME
    # missing downstream-feasibility requirement to whichever single
    # candidate the unmodified comparator selects as best here. Known,
    # explicitly acknowledged scope limit: a lower-ranked Stage 3
    # candidate that would have been feasible is not separately searched
    # for in this phase -- bound-driven adaptive iteration WITHIN Stage 3
    # itself is out of scope here (Part1/Part3 both resolve at Stage <=2
    # in every measurement this session, so this limit does not affect
    # either validation target).
    winner_undercuts = (
        _cached_undercuts_for_feasibility(
            part, winner.direction, direction_undercut_cache, cfg.boolean_refine_max_faces,
        )
        if winner.evidence_tier == "verified_acceptable"
        else None
    )
    winner_feasibility = (
        _cached_is_parting_line_feasible(
            part, winner.direction, core_pin_face_refs, delegations,
            feasibility_cache, undercuts=winner_undercuts,
        )
        if winner.evidence_tier == "verified_acceptable"
        else None
    )
    if winner_feasibility is not None:
        _record_side_action_referrals(
            side_action_referrals, seen_referral_keys, winner.direction, winner_feasibility,
        )
    optimal_found = (
        winner.evidence_tier == "verified_acceptable"
        and winner_feasibility is not None
        and winner_feasibility.feasible
    )
    best_evidence_tier = winner.evidence_tier
    best_unverified_candidate = None if optimal_found else winner
    # O4 (2026-08-17): initial_only_labels added so a genuinely custom
    # initial_pull_direction that wins here (having survived to this tail
    # path only because it was NOT itself feasible -- see the block above
    # -- but is still the best cheap/unverified candidate overall) is
    # attributed to "initial" (0), not misreported as Stage 3.
    if winner.label in stage1_labels:
        search_stage_reached = 1
    elif winner.label in stage2_labels:
        search_stage_reached = 2
    elif winner.label in initial_only_labels:
        search_stage_reached = 0
    else:
        search_stage_reached = 3

    optimal = analyze_draft(
        part=part,
        pull_direction=best_direction,
        pull_direction_label=f"best candidate {_direction_label(best_direction)}",
        analysis_pass="optimal",
        mutate=True,
    )
    optimal_undercuts, cache_hit = _cached_detect_boolean_undercuts(
        part=part,
        direction=best_direction,
        direction_cache=direction_undercut_cache,
        boolean_volume_cache=boolean_volume_cache,
        mutate=True,
        max_boolean_faces=cfg.boolean_refine_max_faces,
    )
    if cache_hit:
        direction_cache_hits += 1
    else:
        direction_cache_misses += 1
    if optimal_undercuts.evaluation_failed:
        evaluation_failures.append({
            "direction_label": _direction_label(best_direction),
            "method": optimal_undercuts.method,
            "error": optimal_undercuts.evaluation_error,
        })
    final_direction_cache_reused = cache_hit

    part.optimal_pull_direction = best_direction
    part.direction_score = best_score
    part.inaccessible_face_ids = list(optimal_undercuts.undercut_face_ids)

    ps = pruning_summary or BooleanPruningSummary(
        strategy="no-Boolean-pruning", best_prefilter_score=0.0,
        ratio_threshold=0.0, near_tie_threshold=0.0, uncertainty_threshold=0.0,
        survivor_count=0, promising_count=0, pruned_count=0,
        max_refine_count=0, survivor_top_count=0, min_boolean_candidates=0,
    )
    return DirectionOptimizationResult(
        best_direction=best_direction,
        best_label=_direction_label(best_direction),
        best_score=best_score,
        initial_pull_direction=initial_direction,
        initial_label=initial_direction_label,
        initial_draft=initial,
        initial_undercuts=initial_undercuts,
        optimal_draft=optimal,
        optimal_undercuts=optimal_undercuts,
        candidates=scored,
        boolean_refined_candidate_count=sum(1 for c in scored if c.boolean_refined),
        boolean_pruned_candidate_count=ps.pruned_count,
        boolean_survivor_candidate_count=ps.survivor_count,
        boolean_promising_candidate_count=ps.promising_count,
        boolean_pruning_summary=pruning_summary,
        direction_cache_hits=direction_cache_hits,
        direction_cache_misses=direction_cache_misses,
        direction_cache_entries=len(direction_undercut_cache),
        direction_cache_final_reused=final_direction_cache_reused,
        boolean_volume_cache_entries=len(boolean_volume_cache),
        search_stage_reached=search_stage_reached,
        analysis_time_s=time.perf_counter() - t_start,
        optimal_found=optimal_found,
        best_evidence_tier=best_evidence_tier,
        best_unverified_candidate=best_unverified_candidate,
        evaluation_failures=evaluation_failures,
        side_action_referrals=side_action_referrals,
    )


def analyze_initial_draft_no_mutation(
    part: PartGeometry,
    pull_direction: Vec3 = (0.0, 0.0, 1.0),
    pull_direction_label: str = "initial +Z (default)",
) -> DraftAnalysisResult:
    """Small wrapper keeps initial-direction semantics explicit."""
    return analyze_draft(
        part=part,
        pull_direction=pull_direction,
        pull_direction_label=pull_direction_label,
        analysis_pass="initial",
        mutate=False,
    )


def analyze_draft_default_no_mutation(part: PartGeometry) -> DraftAnalysisResult:
    """Backward-compatible alias for older tests/callers."""
    return analyze_initial_draft_no_mutation(part)
