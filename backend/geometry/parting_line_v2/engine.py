"""
backend/geometry/parting_line_v2/engine.py
------------------------------------------
Level 0 orchestration (plan P1).

Pipeline::

    Track A ──► weld ──► 2-core reduce ──► extract loops
                                               │
                                     ┌─────────┴─────────┐
                                     │  H0 ─► … ─► H7    │   every candidate
                                     └─────────┬─────────┘
                                               │  survivors only
                                          rank (T1..T7)
                                               │
                                    selected + full scorecard

**Deliberately NOT in Level 0** (plan P1): face-interior silhouette curves
(Track B, P2), Johnson enumeration and beam search (gated behind P3a's ``μ``
measurement), and bridging of any kind. Bridging in particular is v1's
mechanism for reassembling a fragmented silhouette out of unrelated edges —
the wrong fix for a candidate set that is missing curves, and the source of
much of v1's accumulated complexity.

Returning "no feasible candidate" is a **correct outcome**, not a failure. On
a sphere or a cylinder pulled across its axis, the true silhouette lives in a
face interior and Level 0 genuinely cannot see it; saying so is the honest
answer and the whole point of separating feasibility from scoring.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field, replace

from backend.geometry.parting_line_v2 import measures, ranking
from backend.geometry.parting_line_v2.contracts import (
    CorePinFaceRef,
    DelegatedSecondaryAction,
    PullDirectionInput,
    UndercutInput,
)
from backend.geometry.parting_line_v2.gates import evaluate_gates
from backend.geometry.parting_line_v2.graph import build_graph, extract_loops, reduce_to_two_core
from backend.geometry.parting_line_v2.regions import (
    RegionClassification,
    _sample_all_faces_g,
    check_core_pin_eligibility,
    find_bridge_faces,
    mean_abs_g,
    resolve_primary_split_param,
)
from backend.geometry.parting_line_v2.timing import StageTimer, StageTimings
from backend.geometry.parting_line_v2.track_a import detect_edge_silhouettes
from backend.geometry.parting_line_v2.stitch import stitch_tracks
from backend.geometry.parting_line_v2.track_b import detect_face_silhouettes
from backend.geometry.parting_line_v2.types import (
    CorePinInterface,
    EdgeBacking,
    EnumerationBounds,
    PartingLoopCandidate,
    SideActionReferral,
)
from backend.models.geometry_models import PartGeometry, dot3

__all__ = ["PartingLineV2Result", "analyse_parting_line"]


@dataclass(frozen=True)
class PartingLineV2Result:
    """
    Level 0 result.

    Note what is **absent**: no ``confidence``, no ``readiness`` (plan §12.7).
    Feasibility, ranking, validation and evidence are reported separately, and
    a caller wanting one number gets "which tier did it win at, and by how
    much" instead of an uncalibrated score.
    """

    level: str
    pull_direction: PullDirectionInput
    selected: PartingLoopCandidate | None
    candidates: tuple[PartingLoopCandidate, ...]
    bounds: EnumerationBounds
    regions: RegionClassification | None
    referrals: tuple[SideActionReferral, ...]
    timings: StageTimings
    part_projected_area_mm2: float
    coverage_is_exact: bool
    bbox_diagonal_mm: float
    #: Phase 4 (2026-08-16, D-049), diagnostic only. The already-computed
    #: RegionClassification of the best-ranked REJECTED H3-passing candidate
    #: (same selection as the pre-existing `best_rejected_id` local in
    #: `analyse_parting_line` -- this only exposes it, it does not change how
    #: it is chosen). Deliberately a SEPARATE field from `regions`, which
    #: continues to mean only "the accepted candidate's classification."
    #: `None` whenever no non-selected H3-passing candidate exists (e.g. a
    #: feasible result with nothing else worth showing, or zero candidates
    #: reached H3=2 at all). Never read by any gate, ranking, or selection --
    #: attaching/exposing it here never changes `selected`.
    best_rejected_candidate_id: int | None = None
    best_rejected_regions: RegionClassification | None = None
    best_rejected_failed_gate: str | None = None
    best_rejected_reason: str | None = None
    track_a_summary: dict = field(default_factory=dict)
    track_b_summary: dict = field(default_factory=dict)
    stitch_summary: dict = field(default_factory=dict)
    reduction: dict = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @property
    def outcome(self) -> str:
        if self.selected is not None:
            return "feasible"
        if self.referrals:
            return "referred_to_side_action"
        return "no_feasible_candidate"

    @property
    def rejection_summary(self) -> dict[str, int]:
        summary: dict[str, int] = {}
        for candidate in self.candidates:
            report = candidate.feasibility
            if report is None or report.passed:
                continue
            key = report.failed_gate or "unknown"
            summary[key] = summary.get(key, 0) + 1
        return summary

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "outcome": self.outcome,
            "pull_direction": self.pull_direction.to_dict(),
            "selected": self.selected.to_dict() if self.selected else None,
            "candidate_count": len(self.candidates),
            "scorecard": [c.to_dict() for c in self.candidates],
            "rejection_summary": self.rejection_summary,
            "bounds": self.bounds.to_dict(),
            "regions": self.regions.to_dict() if self.regions else None,
            # Phase 4 (D-049): diagnostic-only preview of the best-ranked
            # REJECTED H3-passing candidate. Never the accepted split --
            # consumers must not treat this as "regions" and must not
            # present it as feasible. See PartingLineV2Result docstring.
            "best_rejected_candidate_id": self.best_rejected_candidate_id,
            "best_rejected_regions": (
                self.best_rejected_regions.to_dict() if self.best_rejected_regions else None
            ),
            "best_rejected_failed_gate": self.best_rejected_failed_gate,
            "best_rejected_reason": self.best_rejected_reason,
            "referrals": [r.to_dict() for r in self.referrals],
            "track_a": self.track_a_summary,
            "track_b": self.track_b_summary,
            "stitch": self.stitch_summary,
            "reduction": self.reduction,
            "part_projected_area_mm2": round(self.part_projected_area_mm2, 4),
            "coverage_is_exact": self.coverage_is_exact,
            "bbox_diagonal_mm": round(self.bbox_diagonal_mm, 4),
            "timings": self.timings.to_dict(),
            "notes": list(self.notes),
        }


def _bbox_diagonal(part: PartGeometry) -> float:
    bbox = part.bounding_box
    if bbox is None:
        return 1.0
    return math.sqrt(
        (bbox.xmax - bbox.xmin) ** 2
        + (bbox.ymax - bbox.ymin) ** 2
        + (bbox.zmax - bbox.zmin) ** 2
    ) or 1.0


def _subset_unions(
    candidates: list[PartingLoopCandidate], *, limit: int, max_size: int
) -> list[tuple[PartingLoopCandidate, ...]]:
    """
    Segment-disjoint SUBSETS of candidate curves, ordered deterministically.

    ``Γ`` is a disjoint union of closed curves (D-007), and how many curves it
    takes is a property of the part's topology — a genus-``g`` part generally
    needs ``g + 1``. P1 bounded this to **pairs** as the smallest step that
    fixed a through-hole. P3 measurement showed pairs are not enough: Part3's
    reduced graph is 3 disjoint cycles with **zero branch nodes**, so Johnson
    can add nothing (with every degree 2, the components *are* the only simple
    cycles) and every single and every pair was rejected at H3. The remaining
    possibility is the triple.

    Enumerating subsets is cheap precisely because the reduction works: with
    ``n`` components there are ``2^n − 1`` subsets, and P3a measured ``n`` in
    the low single digits across the whole corpus. ``max_size`` and ``limit``
    keep a pathological part bounded, and both are reported.

    Ordered by size descending then by candidate id, so the cap never
    truncates arbitrarily and the result is reproducible.
    """
    subsets: list[tuple[PartingLoopCandidate, ...]] = []
    ceiling = min(max_size, len(candidates))
    for size in range(2, ceiling + 1):
        for combination in itertools.combinations(candidates, size):
            seen: set[int] = set()
            disjoint = True
            for candidate in combination:
                ids = {s.segment_id for s in candidate.segments}
                if ids & seen:
                    disjoint = False
                    break
                seen |= ids
            if disjoint:
                subsets.append(combination)
    # ASCENDING by size: prefer the FEWEST curves. A Γ of two curves is a
    # simpler and more likely answer than one of four, and the cap must not be
    # consumed by large subsets before small ones are even tried.
    #
    # Measured: with size-descending order and 16 joinable candidates, all 200
    # slots went to 4-subsets (C(16,4) = 1820) and F9's correct answer — a
    # PAIR, outer rim ⊔ hole rim — was never generated, turning a fixture that
    # passed at P1 into a failure.
    subsets.sort(key=lambda group: (len(group), tuple(c.candidate_id for c in group)))
    return subsets[:limit]


def analyse_parting_line(
    part: PartGeometry,
    pull_direction: PullDirectionInput,
    *,
    undercuts: UndercutInput | None = None,
    cfg: object | None = None,
    core_pin_face_refs: tuple[CorePinFaceRef, ...] = (),
    delegations: tuple[DelegatedSecondaryAction, ...] = (),
) -> PartingLineV2Result:
    """
    Run the Level 0 pipeline.

    ``pull_direction`` is a validated ``PullDirectionInput`` — there is no
    ``Vec3`` overload and no default. v1 silently falls back to ``+Z`` when no
    direction is supplied (``core_cavity.py:137-139``), and the P0 baseline
    measured what that costs: Part1 scores 4.1% coverage at ``+Z`` against
    94.8% at its optimal direction. A defaulted direction is not a
    convenience, it is a wrong answer that looks like a right one.

    ``core_pin_face_refs`` defaults to empty, in which case Round 1.5 (plan
    D-043) never engages and behaviour is byte-identical to before this
    mechanism existed — no face is ever treated as a core-pin candidate
    unless the caller explicitly authorizes it.

    ``delegations`` (plan D-044) defaults to empty, in which case H4 never
    excludes any face and behaviour is byte-identical to before this
    mechanism existed. Passed straight through to every ``evaluate_gates``
    call; each record is independently re-validated per candidate and per
    direction — kept completely separate from ``core_pin_face_refs``/
    ``CorePinInterface`` (primary PL topology for a continuous coaxial face)
    and from ``undercuts``/H5 (loop-touching routing, unchanged by this
    parameter).
    """
    if cfg is None:
        from backend.config import settings
        cfg = settings.dfm.parting_line_v2

    undercuts = undercuts or UndercutInput.empty()
    undercuts.validate_against(part)

    timings = StageTimings()
    timer = StageTimer(timings)
    direction = pull_direction.direction
    bbox_diagonal = _bbox_diagonal(part)
    notes: list[str] = []

    # Cauchy bound on the projected outline area (plan §8.1):
    #
    #       A_cauchy = ½ · Σ_f ∫_f |n̂·d̂| dA
    #
    # The integral matters. Using A_f·|n̂_centroid·d̂| instead — one normal
    # sample per face — is NOT the Cauchy formula and has no bounding property
    # at all: measured on F7 (a lofted spline lid) it produced coverage of
    # 104.4%, i.e. a loop "covering" more than the whole part, which is
    # impossible for a true upper bound. Each curved face's |g| is therefore
    # integrated by the same M x M sampling the region classifier uses.
    valid_faces = [f for f in part.faces if f.normal_valid]
    part_projected_area = measures.cauchy_projected_area(
        [f.area for f in valid_faces],
        [mean_abs_g(f, direction, cfg.face_sample_grid) for f in valid_faces],
    )
    notes.append(
        "coverage denominator is the Cauchy bound ½·Σ_f ∫_f |n̂·d̂| dA, with each "
        "face's |g| integrated by M x M sampling. It is EXACT for a convex solid "
        "and an OVERESTIMATE for a non-convex one (the boundary's projection "
        "covers some points more than twice), so coverage is a conservative "
        "under-estimate. The exact tessellation-union path is P3a's job."
    )

    with timer("track_a"):
        track_a = detect_edge_silhouettes(
            part, direction, cfg=cfg, bbox_diagonal_mm=bbox_diagonal
        )

    # Track B is complementary, not an alternative: Track A covers the
    # set-valued normal at sharp edges, Track B the continuous normal in face
    # interiors. Together they cover the silhouette; either alone does not.
    with timer("track_b"):
        track_b = detect_face_silhouettes(
            part, direction, cfg=cfg, bbox_diagonal_mm=bbox_diagonal,
            start_segment_id=len(track_a.segments),
        )

    # Stitch: split edge segments where face curves terminate on them, so a
    # graph node exists at every junction. Without this the two tracks touch
    # in space but never connect — measured on F3, where the rulings and the
    # cap rims share no node and 2-core reduction deletes both rulings.
    #
    # tolerance_mm uses stitch_snap_tolerance_rel, NOT weld_tolerance_rel — the
    # two answer different questions. weld_tolerance_rel bounds how close two
    # points must be to be the SAME point (point-to-point). This bounds how
    # far a Track-B curve's endpoint may be from the real bounding edge it
    # terminates on before the structurally-scoped snap search
    # (stitch._snap_face_endpoints_to_edges, restricted to
    # part.face_to_edges[face_id]) gives up.
    #
    # STATUS (2026-08-12, open): raising this from its old value stopped ZERO
    # segments from being pruned by 2-core reduction on either real part, on
    # any controlled direction tested. It is a real structural improvement
    # (scoped correctly, regression-clean) but NOT a demonstrated fix — see
    # backend/config.py's PartingLineV2Settings and D-022 in
    # docs/DECISIONS_AND_ALGORITHMS.md before citing this as resolved.
    with timer("weld"):
        stitched = stitch_tracks(
            part, track_a.segments, track_b.segments,
            tolerance_mm=max(cfg.stitch_snap_tolerance_rel * bbox_diagonal, 1e-6),
        )
    all_segments = stitched.segments
    if track_b.degenerate_face_ids:
        notes.append(
            f"{len(track_b.degenerate_face_ids)} face(s) are zero-draft bands "
            "(|g| <= eps over their whole area). No curve is emitted for them: the "
            "parting line's position within a band is a FREE PARAMETER, not a "
            "determined crossing (plan 4.3/5.3). Optimising within it is Level 3, "
            "out of scope for this milestone."
        )

    with timer("weld"):
        graph = build_graph(
            all_segments, bbox_diagonal_mm=bbox_diagonal, cfg=cfg
        )

    with timer("reduce"):
        stats = reduce_to_two_core(graph)

    with timer("enumerate"):
        raw_loops, strategy, cap_hit = extract_loops(
            graph, stats,
            max_candidates=cfg.max_candidates,
            mu_max_for_johnson=cfg.mu_max_for_johnson,
            time_budget_s=cfg.enumeration_time_budget_s,
            strategy=cfg.enumeration_strategy,
        )

    bounds = EnumerationBounds(
        strategy=strategy,  # type: ignore[arg-type]
        cyclomatic_number=stats.cyclomatic_number,
        node_count=stats.nodes_after,
        edge_count=stats.edges_after,
        branch_node_count=stats.branch_node_count,
        candidates_found=len(raw_loops),
        k_max=cfg.max_candidates,
        k_max_hit=cap_hit,
    )

    if not raw_loops:
        notes.append(
            "No candidate loop exists: the silhouette graph is empty after 2-core "
            "reduction. At Level 0 this is the expected, correct answer whenever the "
            "true silhouette lies in a face interior (a sphere, or a cylinder pulled "
            "across its axis) — Track B in P2 is what will see those."
        )
        return PartingLineV2Result(
            level="0", pull_direction=pull_direction, selected=None, candidates=(),
            bounds=bounds, regions=None, referrals=(), timings=timings,
            part_projected_area_mm2=part_projected_area, coverage_is_exact=False,
            bbox_diagonal_mm=bbox_diagonal,
            track_a_summary=track_a.to_dict(), track_b_summary=track_b.to_dict(), stitch_summary=stitched.to_dict(),
            reduction=stats.to_dict(), notes=tuple(notes),
        )

    candidates: list[PartingLoopCandidate] = []
    # Call-local, NOT module-level: the backend is stateless and re-analyses on
    # every request, so any cross-call scratch would leak one part's regions
    # into another's result.
    regions_by_candidate: dict[int, RegionClassification] = {}

    # O6 (2026-08-17): the per-face g-sampling classify_regions() needs is a
    # pure function of (part, direction, cfg.face_sample_grid) -- completely
    # independent of which candidate loop is being classified (see
    # regions._sample_all_faces_g's docstring; O5's forensic measurement
    # found this recomputed from scratch on every H3-topologically-valid
    # candidate, 90-96% of this function's total wall time on both Part1 and
    # Part3). Computed exactly once here, call-local (never cached across
    # analyse_parting_line invocations, matching the same statelessness
    # rationale as regions_by_candidate above), and threaded unchanged into
    # every evaluate_gates() call below -- Round 1, Round 1.5 (core-pin), and
    # Round 2 (loop unions) alike, so none of the three paths falls back to
    # recomputing it per candidate.
    face_g_stats = _sample_all_faces_g(
        {f.face_id: f for f in part.faces}, direction, cfg.face_sample_grid,
    )

    with timer("filter"):
        for index, (segment_ids, points) in enumerate(raw_loops):
            candidate = PartingLoopCandidate(
                candidate_id=index,
                segments=tuple(graph.segments_by_id[s] for s in segment_ids),
                points=points,
                is_closed=True,
                discovered_by=strategy,  # type: ignore[arg-type]
            )
            outcome = evaluate_gates(
                candidate, part, direction,
                undercuts=undercuts, cfg=cfg,
                bbox_diagonal_mm=bbox_diagonal,
                part_projected_area_mm2=part_projected_area,
                delegations=delegations,
                face_g_stats=face_g_stats,
            )
            candidate = replace(candidate, feasibility=outcome.report)
            # Plan Phase 3A: retained for ANY H3-passing candidate, not only
            # a fully-passing one -- classify_regions() already ran inside
            # evaluate_gates() regardless of whether H4/H5/H6/H7 later
            # rejected the candidate; this only stops discarding data that
            # was already computed. Score/ranking stay passed-only, unchanged.
            if outcome.regions is not None:
                regions_by_candidate[candidate.candidate_id] = outcome.regions
            if outcome.report.passed and outcome.regions is not None:
                candidate = replace(candidate, score=ranking.score_candidate(
                    candidate, direction,
                    undercuts=undercuts,
                    bbox_diagonal_mm=bbox_diagonal,
                    part_projected_area_mm2=part_projected_area,
                    ambiguous_area_fraction=outcome.regions.ambiguous_area_fraction,
                ))
            candidates.append(candidate)

    # --- Round 1.5: core-pin / tooling-split closure (plan D-043) -----------
    #
    # A face exactly coaxial with the pull direction (g = 0 along its ENTIRE
    # length — e.g. a straight through-bore) has no Track-B silhouette
    # crossing anywhere on it, so no candidate loop generated by Round 1 can
    # ever be closed by cutting through it. When such a face is the reason an
    # otherwise-real boundary fails H3 with exactly one region, and the face
    # is EXPLICITLY authorized as a core-pin candidate, its split point is
    # ASSIGNED to match the already-real boundary — never searched for.
    #
    # Bounded and deterministic, not a search:
    #   1. `find_bridge_faces` localizes which face(s) are the graph-
    #      theoretic cause of the failure — pure topology, no validity claim.
    #   2. Only faces that are BOTH a localized bridge AND explicitly
    #      authorized are even considered.
    #   3. `check_core_pin_eligibility` is the independent geometric gate —
    #      always run, never skipped, never satisfied merely by being a
    #      bridge or merely by being authorized.
    #   4. `resolve_primary_split_param` is called exactly once per candidate
    #      and its value is threaded, unchanged, into eligibility, the
    #      candidate's metadata, and CorePinInterface — never resampled.
    # No `.segments`/`.loops` curve is ever added; the real parting line is
    # unchanged (see PartingLoopCandidate.tooling_split_face_ids docstring).
    if core_pin_face_refs and not any(c.feasibility and c.feasibility.passed for c in candidates):
        authorized = {ref.face_id: ref for ref in core_pin_face_refs}
        with timer("filter"):
            for candidate in list(candidates):
                if (
                    candidate.feasibility is None
                    or candidate.feasibility.failed_gate != "H3"
                    or candidate.feasibility.measurements.get("h3_region_count") != 1.0
                ):
                    continue
                loop_edge_ids = frozenset(
                    s.backing.edge_id for s in candidate.segments if isinstance(s.backing, EdgeBacking)
                )
                bridge_candidates = find_bridge_faces(part, loop_edge_ids) & authorized.keys()
                if not bridge_candidates:
                    continue
                try:
                    split_param = resolve_primary_split_param(part, loop_edge_ids, direction)
                except ValueError:
                    continue

                chosen_face_id = None
                for face_id in sorted(bridge_candidates):
                    if check_core_pin_eligibility(part, face_id, direction, cfg, split_param).eligible:
                        chosen_face_id = face_id
                        break
                if chosen_face_id is None:
                    continue

                ref = authorized[chosen_face_id]
                closed = replace(
                    candidate,
                    candidate_id=len(candidates),
                    discovered_by=candidate.discovered_by,
                    tooling_split_face_ids=((chosen_face_id, split_param),),
                    core_pin_interfaces=(CorePinInterface(
                        face_id=chosen_face_id, split_param=split_param,
                        axis_direction=ref.axis_direction, reason=ref.reason,
                    ),),
                    feasibility=None, score=None,
                )
                outcome = evaluate_gates(
                    closed, part, direction, undercuts=undercuts, cfg=cfg,
                    bbox_diagonal_mm=bbox_diagonal, part_projected_area_mm2=part_projected_area,
                    delegations=delegations, face_g_stats=face_g_stats,
                )
                closed = replace(closed, feasibility=outcome.report)
                if outcome.regions is not None:
                    regions_by_candidate[closed.candidate_id] = outcome.regions
                if outcome.report.passed and outcome.regions is not None:
                    closed = replace(closed, score=ranking.score_candidate(
                        closed, direction,
                        undercuts=undercuts,
                        bbox_diagonal_mm=bbox_diagonal,
                        part_projected_area_mm2=part_projected_area,
                        ambiguous_area_fraction=outcome.regions.ambiguous_area_fraction,
                    ))
                candidates.append(closed)
        if any(c.core_pin_interfaces for c in candidates):
            notes.append(
                "A coaxial core-pin face closed an otherwise-real boundary via a "
                "tooling-assigned logical split (plan D-043, core_pin_interfaces on "
                "the affected candidate) rather than adding a curve to the parting "
                "line."
            )

    # --- Round 2: multi-loop Γ (plan C1, corrected 2026-08-09) --------------
    #
    # Γ is a DISJOINT UNION of closed curves, not one loop. A part with a
    # through-hole needs outer rim ⊔ hole rim: cutting the outer rim alone
    # leaves the top face connected to the bottom through the hole wall, so
    # H3 reports 1 region (measured on F9).
    #
    # Bounded deliberately: unions are formed ONLY from candidates that are
    # geometrically sound but failed H3 with exactly one region — i.e. curves
    # that individually do not separate — and only when round 1 produced
    # nothing feasible. A single loop that separates is simpler and always
    # preferred. Pairs only; higher-order unions wait for evidence that a
    # real part needs them.
    if not any(c.feasibility and c.feasibility.passed for c in candidates):
        joinable = [
            c for c in candidates
            if c.feasibility
            and c.feasibility.failed_gate == "H3"
            and c.feasibility.measurements.get("h3_region_count") == 1.0
        ]
        with timer("enumerate"):
            unions = _subset_unions(
                joinable, limit=cfg.max_candidates, max_size=cfg.max_loop_union_size
            )
        with timer("filter"):
            for offset, group in enumerate(unions):
                segments: tuple = ()
                points: tuple = ()
                loops: tuple = ()
                for member in group:
                    segments += member.segments
                    points += member.points
                    loops += member.loops
                union = PartingLoopCandidate(
                    candidate_id=len(candidates) + offset,
                    segments=segments, points=points, is_closed=True,
                    discovered_by="loop_union", loops=loops,
                )
                outcome = evaluate_gates(
                    union, part, direction,
                    undercuts=undercuts, cfg=cfg,
                    bbox_diagonal_mm=bbox_diagonal,
                    part_projected_area_mm2=part_projected_area,
                    delegations=delegations,
                    face_g_stats=face_g_stats,
                )
                union = replace(union, feasibility=outcome.report)
                if outcome.regions is not None:
                    regions_by_candidate[union.candidate_id] = outcome.regions
                if outcome.report.passed and outcome.regions is not None:
                    union = replace(union, score=ranking.score_candidate(
                        union, direction,
                        undercuts=undercuts,
                        bbox_diagonal_mm=bbox_diagonal,
                        part_projected_area_mm2=part_projected_area,
                        ambiguous_area_fraction=outcome.regions.ambiguous_area_fraction,
                    ))
                candidates.append(union)
        if unions:
            notes.append(
                f"No single closed curve separated the part, so {len(unions)} "
                f"multi-curve union(s) of up to {cfg.max_loop_union_size} curves were "
                "tried — Γ is a disjoint union of closed curves (plan C1), and a "
                "genus-g part generally needs g+1 of them."
            )

    with timer("rank"):
        feasible = [c for c in candidates if c.feasibility and c.feasibility.passed]
        ordered = ranking.rank_candidates(feasible, cfg)

    selected = ordered[0] if ordered else None
    regions = regions_by_candidate.get(selected.candidate_id) if selected else None
    referrals = tuple(
        c.feasibility.referral for c in candidates
        if c.feasibility and c.feasibility.referral is not None
    )

    if selected is None:
        notes.append(
            "Candidates were generated but none passed the hard filter. The "
            "per-candidate rejection reasons are in the scorecard — this is a "
            "reported outcome, not a silent failure."
        )

    # Plan Phase 3A, diagnostic only: also retain region data on the
    # best-ranked REJECTED H3-passing candidate (lowest H4 orientation
    # violation among those that reached H3=2 but did not fully pass), so
    # the API/frontend can show WHY a direction produced a degenerate or
    # genuine split even when `selected` is None. This never reads or
    # writes `selected`/`ordered`/ranking, which are already fixed above —
    # it is a second, independent, bounded choice made purely for
    # observability (bounded to one extra candidate so payload size stays
    # small; every H3-passing candidate's data is already sitting in
    # `regions_by_candidate` computed above, this just decides which ONE
    # non-selected candidate is worth exposing in full).
    best_rejected_id: int | None = None
    rejected_h3_valid = [
        c for c in candidates
        if c.candidate_id in regions_by_candidate
        and (selected is None or c.candidate_id != selected.candidate_id)
        and c.feasibility is not None and not c.feasibility.passed
    ]
    if rejected_h3_valid:
        best_rejected_id = min(
            rejected_h3_valid,
            key=lambda c: c.feasibility.measurements.get(
                "h4_orientation_violation_fraction", float("inf")
            ),
        ).candidate_id

    # Rebuild the candidate tuple so the ranked winner carries won_at_tier.
    by_id = {c.candidate_id: c for c in candidates}
    for candidate in ordered:
        by_id[candidate.candidate_id] = candidate
    if selected is not None and regions is not None:
        by_id[selected.candidate_id] = replace(by_id[selected.candidate_id], regions=regions)
        # `replace()` returns a NEW object -- `selected` must be repointed at
        # it too, or PartingLineV2Result.selected (returned below) would
        # carry the pre-attachment candidate while candidates[] carries the
        # updated one, silently disagreeing with each other.
        selected = by_id[selected.candidate_id]
    # Phase 4 (D-049): expose the same best-rejected-candidate data computed
    # above through explicitly named top-level fields, instead of leaving a
    # caller to scan the full scorecard for the one non-selected candidate
    # whose `.regions` happens to be populated. Purely additive -- reads
    # already-computed local state (`by_id`, `regions_by_candidate`), invents
    # no new selection criterion, and never touches `selected`/`regions`.
    best_rejected_regions_out = None
    best_rejected_failed_gate = None
    best_rejected_reason = None
    if best_rejected_id is not None:
        by_id[best_rejected_id] = replace(
            by_id[best_rejected_id], regions=regions_by_candidate[best_rejected_id]
        )
        best_rejected_regions_out = by_id[best_rejected_id].regions
        best_rejected_report = by_id[best_rejected_id].feasibility
        if best_rejected_report is not None:
            best_rejected_failed_gate = best_rejected_report.failed_gate
            best_rejected_reason = best_rejected_report.reason

    return PartingLineV2Result(
        level="0", pull_direction=pull_direction, selected=selected,
        candidates=tuple(by_id[i] for i in sorted(by_id)),
        bounds=bounds, regions=regions, referrals=referrals, timings=timings,
        part_projected_area_mm2=part_projected_area, coverage_is_exact=False,
        bbox_diagonal_mm=bbox_diagonal,
        best_rejected_candidate_id=best_rejected_id,
        best_rejected_regions=best_rejected_regions_out,
        best_rejected_failed_gate=best_rejected_failed_gate,
        best_rejected_reason=best_rejected_reason,
        track_a_summary=track_a.to_dict(), track_b_summary=track_b.to_dict(), stitch_summary=stitched.to_dict(),
        reduction=stats.to_dict(), notes=tuple(notes),
    )
