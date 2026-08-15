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

import logging
import math
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

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
        }


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
            },
            "principal_axis_alignment": round(self.principal_axis_alignment, 6),
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
    # Milestone 3: which search stage found the winner (1=principal, 2=diagonal, 3=sphere)
    search_stage_reached: int = 3
    # R1: True if the final direction came from the cheap-only pool (no Boolean-validated
    # candidate was available). False means the direction was selected from the
    # Boolean-validated pool — the preferred outcome.
    validation_fallback: bool = False

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
            "validation_fallback": self.validation_fallback,
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
    reused across different refinement scopes. The final pass for the winning
    direction uses the SAME parameters as the per-candidate scoring pass, so it
    always gets a cache hit (zero additional Boolean ops).
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


def _select_boolean_refinement_candidates(
    scored: list[DirectionCandidateResult],
) -> tuple[list[DirectionCandidateResult], BooleanPruningSummary]:
    """
    Select candidates that deserve expensive swept-Boolean refinement.

    This gate is intentionally stricter than the original top-N-only pass:
    bad prefilter scores are removed by ratio/additive thresholds, the survivor
    pool is capped, and only near-ties proceed to Boolean.  A minimum keeps at
    least the best candidate refined so the final result still has geometric
    evidence.
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
    for candidate in ordered:
        if candidate.score <= ratio_threshold:
            survivors_by_label[candidate.label] = candidate
            add_reason(candidate, "within ratio threshold")

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
    promising = [
        candidate for candidate in survivors
        if (
            candidate.score <= near_tie_threshold
            or candidate.label in guard_selected_labels
        )
    ]
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
    Provisional cheap suitability screen for the hierarchical search.

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
    """
    if not undercuts.boolean_refined:
        return False
    # R4: Do not accept a direction with incomplete Boolean validation.
    # Incomplete validation means some candidates were skipped due to budget
    # or area thresholds — the actual undercut count may be higher.
    # "0 confirmed undercuts with 40 unvalidated candidates" is NOT acceptable.
    if not undercuts.boolean_validation_complete:
        return False
    total_area = max(undercuts.total_analysed_area_mm2, 1.0)
    confirmed_area = sum(
        f.area for fid in undercuts.boolean_confirmed_face_ids
        if (f := part.get_face(fid)) is not None
    )
    confirmed_pct = 100.0 * confirmed_area / total_area
    return confirmed_pct <= cfg.suitability_max_confirmed_undercut_pct


def _build_refined_candidate(
    direction: Vec3,
    draft: DraftAnalysisResult,
    undercuts: UndercutDetectionResult,
    part: PartGeometry,
) -> DirectionCandidateResult:
    """Build a DirectionCandidateResult from Boolean-refined undercut data."""
    refined_score = _score_candidate(draft, undercuts, direction, part)
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
    )


def optimize_mold_direction(
    part: PartGeometry,
    angular_step_deg: float | None = None,
    max_candidates: int | None = None,
    initial_pull_direction: Vec3 = (0.0, 0.0, 1.0),
    initial_label: str | None = None,
) -> DirectionOptimizationResult:
    """
    Find the best candidate mold opening direction for Level 1.

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
    """
    t_start = time.perf_counter()
    cfg = settings.dfm.direction_search
    initial_direction = normalize3(initial_pull_direction)
    initial_direction_label = initial_label or f"initial {_direction_label(initial_direction)}"
    boolean_volume_cache: BooleanVolumeCache = {}
    direction_undercut_cache: DirectionUndercutCache = {}
    direction_cache_hits = 0
    direction_cache_misses = 0

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

    scored: list[DirectionCandidateResult] = []
    draft_by_direction: dict[Vec3, DraftAnalysisResult] = {}
    seen_directions: set[tuple[int, int, int]] = set()
    search_stage_reached = 3
    pruning_summary: BooleanPruningSummary | None = None

    # ── Helper: Boolean-refine a list of cheap-screened candidates ────────
    def _boolean_refine_candidates(
        candidates_to_refine: list[DirectionCandidateResult],
    ) -> tuple[list[DirectionCandidateResult], list[DirectionCandidateResult]]:
        """
        Run Boolean refinement on candidates and return (refined_list, acceptable_list).

        ``refined_list`` contains the updated DirectionCandidateResults (Boolean data).
        ``acceptable_list`` contains those that also pass the Boolean suitability check
        (PROVISIONAL threshold — NOT a manufacturing guarantee).

        Uses the shared caches; updates direction_cache_hits/misses via nonlocal.
        """
        nonlocal direction_cache_hits, direction_cache_misses
        refined: list[DirectionCandidateResult] = []
        acceptable: list[DirectionCandidateResult] = []
        for candidate in candidates_to_refine:
            direction = candidate.direction
            draft = draft_by_direction[direction]
            undercuts, hit = _cached_detect_boolean_undercuts(
                part=part,
                direction=direction,
                direction_cache=direction_undercut_cache,
                boolean_volume_cache=boolean_volume_cache,
                mutate=False,
                max_boolean_faces=cfg.boolean_refine_max_faces,
            )
            if hit:
                direction_cache_hits += 1
            else:
                direction_cache_misses += 1
            suitable = _is_direction_suitable_boolean(undercuts, part, cfg)
            logger.info(
                "direction_optimizer boolean_refine dir=%s candidate_total=%d "
                "checked=%d validation_complete=%s suitability=%s cache_hit=%s",
                _direction_label(direction),
                undercuts.boolean_candidate_count,
                len(undercuts.boolean_checked_face_ids),
                undercuts.boolean_validation_complete,
                "pass" if suitable else "fail",
                hit,
            )
            updated = _build_refined_candidate(direction, draft, undercuts, part)
            refined.append(updated)
            if suitable:
                acceptable.append(updated)
        return refined, acceptable

    if cfg.hierarchical_search_enabled:
        # ── Stage 1: Bosch preferred ±X/Y/Z directions ───────────────────
        for raw_dir in [
            (1.0, 0.0, 0.0), (-1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0), (0.0, -1.0, 0.0),
            (0.0, 0.0, 1.0), (0.0, 0.0, -1.0),
        ]:
            d = normalize3(raw_dir)
            if _dedupe_direction(d, seen_directions):
                scored.append(_score_direction_candidate(part, d, draft_by_direction))

        # Check cheap suitability for Stage 1 candidates
        s1_suitable = [c for c in scored if _is_direction_suitable_cheap(c, cfg)]
        logger.info(
            "direction_optimizer stage=1 scored=%d cheap_suitable=%d",
            len(scored), len(s1_suitable),
        )
        if s1_suitable:
            refined_s1, acceptable_s1 = _boolean_refine_candidates(s1_suitable)
            # Update scored with Boolean-refined results
            refined_map = {c.label: c for c in refined_s1}
            scored = [refined_map.get(c.label, c) for c in scored]
            if acceptable_s1:
                # Early exit: Stage 1 produced a Boolean-confirmed acceptable direction
                search_stage_reached = 1
                best = min(acceptable_s1, key=lambda c: c.score)
                best_direction = best.direction
                best_score = best.score
                optimal = analyze_draft(
                    part=part,
                    pull_direction=best_direction,
                    pull_direction_label=f"best candidate {_direction_label(best_direction)}",
                    analysis_pass="optimal",
                    mutate=True,
                )
                # Final pass: same params as scoring → guaranteed cache hit (zero cost).
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
                    boolean_pruned_candidate_count=0,
                    boolean_survivor_candidate_count=len(acceptable_s1),
                    boolean_promising_candidate_count=len(s1_suitable),
                    boolean_pruning_summary=None,
                    direction_cache_hits=direction_cache_hits,
                    direction_cache_misses=direction_cache_misses,
                    direction_cache_entries=len(direction_undercut_cache),
                    direction_cache_final_reused=cache_hit,
                    boolean_volume_cache_entries=len(boolean_volume_cache),
                    search_stage_reached=search_stage_reached,
                    validation_fallback=False,
                    analysis_time_s=time.perf_counter() - t_start,
                )
            # Stage 1 cheap-passes exist but all failed Boolean: fall through to Stage 2

        # ── Stage 2: Configurable diagonal directions ──────────────────────
        for raw_dir in cfg.stage2_directions:
            d = normalize3(raw_dir)
            if _dedupe_direction(d, seen_directions):
                scored.append(_score_direction_candidate(part, d, draft_by_direction))

        # Check all not-yet-Boolean-refined candidates that pass cheap screen
        s2_candidates = [
            c for c in scored
            if not c.boolean_refined and _is_direction_suitable_cheap(c, cfg)
        ]
        logger.info(
            "direction_optimizer stage=2 scored=%d cheap_suitable=%d",
            len(scored), len(s2_candidates),
        )
        if s2_candidates:
            refined_s2, acceptable_s2 = _boolean_refine_candidates(s2_candidates)
            refined_map = {c.label: c for c in refined_s2}
            scored = [refined_map.get(c.label, c) for c in scored]
            if acceptable_s2:
                # Early exit: Stage 2 produced a Boolean-confirmed acceptable direction
                search_stage_reached = 2
                best = min(acceptable_s2, key=lambda c: c.score)
                best_direction = best.direction
                best_score = best.score
                optimal = analyze_draft(
                    part=part,
                    pull_direction=best_direction,
                    pull_direction_label=f"best candidate {_direction_label(best_direction)}",
                    analysis_pass="optimal",
                    mutate=True,
                )
                # Final pass: same params as scoring → guaranteed cache hit (zero cost).
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
                    boolean_pruned_candidate_count=0,
                    boolean_survivor_candidate_count=len(acceptable_s2),
                    boolean_promising_candidate_count=len(s2_candidates),
                    boolean_pruning_summary=None,
                    direction_cache_hits=direction_cache_hits,
                    direction_cache_misses=direction_cache_misses,
                    direction_cache_entries=len(direction_undercut_cache),
                    direction_cache_final_reused=cache_hit,
                    boolean_volume_cache_entries=len(boolean_volume_cache),
                    search_stage_reached=search_stage_reached,
                    validation_fallback=False,
                    analysis_time_s=time.perf_counter() - t_start,
                )
            # Stage 2 cheap-passes exist but all failed Boolean: fall through to Stage 3

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

    promising, pruning_summary = _select_boolean_refinement_candidates(scored)

    refined_by_label: dict[str, DirectionCandidateResult] = {}
    for candidate in promising:
        direction = candidate.direction
        draft = draft_by_direction[direction]
        undercuts, cache_hit = _cached_detect_boolean_undercuts(
            part=part,
            direction=direction,
            direction_cache=direction_undercut_cache,
            boolean_volume_cache=boolean_volume_cache,
            mutate=False,
            max_boolean_faces=cfg.boolean_refine_max_faces,
        )
        if cache_hit:
            direction_cache_hits += 1
        else:
            direction_cache_misses += 1
        refined_by_label[candidate.label] = _build_refined_candidate(
            direction, draft, undercuts, part
        )

    scored = [refined_by_label.get(candidate.label, candidate) for candidate in scored]

    # R1: Final direction must come from Boolean-validated pool.
    # Cheap scores are for screening/ranking only — they cannot determine the
    # final result because their undercut evidence is unvalidated.
    validated = [c for c in scored if c.boolean_refined]
    validation_fallback = False
    if validated:
        validated.sort(key=lambda c: c.score)
        best_direction = validated[0].direction
        best_score = validated[0].score
    else:
        # Fallback: no validated candidate exists (all Boolean failed, or OCC
        # unavailable). Use cheap-best but flag as unvalidated.
        scored.sort(key=lambda c: c.score)
        best_direction = scored[0].direction
        best_score = scored[0].score
        validation_fallback = True

    scored.sort(key=lambda c: c.score)
    optimal = analyze_draft(
        part=part,
        pull_direction=best_direction,
        pull_direction_label=f"best candidate {_direction_label(best_direction)}",
        analysis_pass="optimal",
        mutate=True,
    )
    # Final pass: same params as per-candidate scoring → guaranteed cache hit (zero cost).
    # The winning direction was already Boolean-refined during candidate evaluation with
    # identical parameters, so _lookup_direction_cache finds a matching entry.
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
        validation_fallback=validation_fallback,
        analysis_time_s=time.perf_counter() - t_start,
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
