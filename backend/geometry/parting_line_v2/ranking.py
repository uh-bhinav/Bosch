"""
backend/geometry/parting_line_v2/ranking.py
-------------------------------------------
Lexicographic ranking of feasible candidates (plan §8).

**Not a weighted sum.** With ``Score = w₁·A + w₂·B + …`` the *weights* decide
the winner, and no weights are defensible yet — there is no labelled outcome
data to fit them to. A priority ordering instead encodes engineering
precedence, which can be argued from injection-molding first principles and
defended in front of a reviewer.

Tier order (plan §8), each a hard tie-break rather than a term:

=====  =========================  =====  ==================================
tier   key                        dir    why
=====  =========================  =====  ==================================
T1     coverage                   max    Nee (1998) §5 maximum-contour rule
T2     undercut_proximity         min    a loop skirting an undercut risks a
                                         side action however pretty it is
T3     pull_axis_span_mm          min    how far the mold must step; drives
                                         tooling cost and mismatch/flash risk
T4     ambiguous_area_fraction    min    separability — how much of the part
                                         is left undetermined
T5     excess_turning             min    manufacturability; 0 for a circle
                                         AND for a rectangle (see measures)
T6     length_3d_mm               min    less machining
T7     stable_id                  —      determinism under exact ties
=====  =========================  =====  ==================================

Comparison uses a per-tier tolerance band (``cfg.tier_epsilon``): a difference
within the band counts as a tie and falls through, so near-equal candidates
are never separated by numerical noise (plan point 15, fake precision).
"""

from __future__ import annotations

import hashlib
import math

from backend.geometry.parting_line_v2 import measures
from backend.geometry.parting_line_v2.contracts import UndercutInput
from backend.geometry.parting_line_v2.types import (
    CandidateScore,
    EdgeBacking,
    PartingLoopCandidate,
)
from backend.models.geometry_models import Vec3

__all__ = ["score_candidate", "rank_candidates", "TIER_ORDER"]

#: (attribute, "max"|"min", tier label). T7 is handled separately.
TIER_ORDER: tuple[tuple[str, str, str], ...] = (
    ("coverage", "max", "T1"),
    ("undercut_proximity", "min", "T2"),
    ("pull_axis_span_mm", "min", "T3"),
    ("ambiguous_area_fraction", "min", "T4"),
    ("excess_turning", "min", "T5"),
    ("length_3d_mm", "min", "T6"),
)


def _stable_id(candidate: PartingLoopCandidate) -> str:
    """
    Deterministic identity from the loop's real content.

    Built from the sorted backing edge ids, not from ``candidate_id`` (an
    enumeration artefact that shifts when the candidate set changes) and not
    from point coordinates (floating-point noise). Two runs over the same
    geometry produce the same id — which is what makes fixture F14's exact
    mirror tie break the same way every time.
    """
    edge_ids = sorted(
        s.backing.edge_id for s in candidate.segments if isinstance(s.backing, EdgeBacking)
    )
    payload = ",".join(str(e) for e in edge_ids) or f"seg:{len(candidate.segments)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _undercut_proximity(
    points: tuple[Vec3, ...], undercuts: UndercutInput, bbox_diagonal_mm: float
) -> float:
    """
    ``1 / (1 + d_min/bbox_diag)`` — smaller is better, dimensionless.

    Returns 0.0 when there are no undercut features with a location: no
    undercuts means no proximity risk, and 0 is the best possible score on a
    minimised tier. Loops running *through* an undercut never reach here —
    H5 already referred them to side-action analysis.
    """
    locations = [f.location for f in undercuts.features if f.location is not None]
    if not locations or not points:
        return 0.0
    d_min = min(math.dist(p, loc) for p in points for loc in locations)
    return 1.0 / (1.0 + d_min / max(bbox_diagonal_mm, 1e-9))


def score_candidate(
    candidate: PartingLoopCandidate,
    pull_direction: Vec3,
    *,
    undercuts: UndercutInput,
    bbox_diagonal_mm: float,
    part_projected_area_mm2: float,
    ambiguous_area_fraction: float,
    coverage_is_exact: bool = False,
) -> CandidateScore:
    """Build the full scorecard for one feasible candidate."""
    points = candidate.points
    projected_area = measures.largest_loop_projected_area(candidate.loops, pull_direction)
    coverage = projected_area / part_projected_area_mm2 if part_projected_area_mm2 > 0 else 0.0

    return CandidateScore(
        coverage=coverage,
        undercut_proximity=_undercut_proximity(points, undercuts, bbox_diagonal_mm),
        # Span over ALL component curves: the mold must accommodate every one
        # of them, so the step is set by the global extremes, not per loop.
        pull_axis_span_mm=measures.pull_axis_span(points, pull_direction),
        ambiguous_area_fraction=ambiguous_area_fraction,
        # Worst component curve: one zigzag loop makes the whole Γ hard to
        # machine, and averaging would let a tidy outer rim hide it.
        excess_turning=max(
            (measures.excess_turning(loop, closed=True) for loop in candidate.loops),
            default=0.0,
        ),
        length_3d_mm=sum(
            measures.polyline_length_3d(loop, closed=True) for loop in candidate.loops
        ),
        stable_id=_stable_id(candidate),
        coverage_is_exact=coverage_is_exact,
    )


def _compare(a: CandidateScore, b: CandidateScore, cfg: object) -> tuple[int, str]:
    """
    Compare two scorecards. Returns ``(-1|0|1, deciding_tier)``.

    ``-1`` means ``a`` beats ``b``.
    """
    epsilons = cfg.tier_epsilon
    for attribute, direction, tier in TIER_ORDER:
        value_a = getattr(a, attribute)
        value_b = getattr(b, attribute)
        band = getattr(epsilons, attribute, 0.0)
        if abs(value_a - value_b) <= band:
            continue                                  # a tie at this tier
        better_a = value_a > value_b if direction == "max" else value_a < value_b
        return (-1 if better_a else 1), tier
    if a.stable_id != b.stable_id:
        return (-1 if a.stable_id > b.stable_id else 1), "T7"
    return 0, "tie"


def rank_candidates(
    candidates: list[PartingLoopCandidate], cfg: object
) -> list[PartingLoopCandidate]:
    """
    Sort feasible candidates best-first and stamp ``won_at_tier`` on the
    winner.

    ``won_at_tier`` records **which tier decided it against the runner-up** —
    the single most useful field for explaining a choice. "Selected on
    coverage, 94.8% vs 91.0%" is a reason; "score 88.2" is not.
    """
    import functools

    scored = [c for c in candidates if c.score is not None]
    if not scored:
        return []

    ordered = sorted(
        scored,
        key=functools.cmp_to_key(lambda x, y: _compare(x.score, y.score, cfg)[0]),  # type: ignore[arg-type]
    )
    if len(ordered) >= 2:
        _, tier = _compare(ordered[0].score, ordered[1].score, cfg)  # type: ignore[arg-type]
        from dataclasses import replace
        ordered[0] = replace(ordered[0], score=replace(ordered[0].score, won_at_tier=tier))  # type: ignore[arg-type]
    elif ordered:
        from dataclasses import replace
        ordered[0] = replace(
            ordered[0], score=replace(ordered[0].score, won_at_tier="sole_feasible")  # type: ignore[arg-type]
        )
    return ordered
