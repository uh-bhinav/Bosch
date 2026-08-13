"""
backend/geometry/parting_line_v2/types.py
-----------------------------------------
Result and data types for the v2 parting-line engine.

P0 scope: **types only.** No algorithm lives here. Every dataclass below is
frozen and JSON-serializable via ``to_dict()``; live OCC handles are never
stored on these objects (CLAUDE.md data-flow invariant).

The type design encodes two plan invariants structurally, so violating them is
a construction error rather than a validation failure:

* **H0.1 provenance** — ``CurveSegment`` requires a ``backing`` (an OCC edge
  curve or a face + UV points). A segment with no backing cannot be built, so
  the "curve that is not on the part" defect (audit RC-7) is unrepresentable.
  See ``docs/DECISIONS_AND_ALGORITHMS.md`` D-001.
* **§12.7 confidence ban** — there is no ``confidence`` or ``readiness`` field
  anywhere in this module. Feasibility, ranking, validation and evidence are
  four separate reported things.

References: ``docs/PARTING_LINE_ALGORITHM_PLAN.md`` §6.3, §7, §8.4, §9.2, H0, H5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from backend.models.geometry_models import Vec3

__all__ = [
    "EdgeBacking",
    "FaceBacking",
    "SegmentBacking",
    "SegmentKind",
    "CurveSegment",
    "OnSurfaceReport",
    "SideActionReferral",
    "FeasibilityReport",
    "CandidateScore",
    "PartingLoopCandidate",
    "FaceClassification",
    "EnumerationBounds",
    "GateId",
    "HARD_GATES",
]


# ---------------------------------------------------------------------------
# Provenance — the H0.1 backing types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EdgeBacking:
    """
    A segment lying on a real B-Rep edge.

    ``t_start``/``t_end`` are parameters on the OCC edge's own 3-D curve, so
    any point of the segment can be recovered as ``C(t)`` and checked against
    the curve (gate H0.2).
    """

    edge_id: int
    t_start: float
    t_end: float

    @property
    def kind(self) -> Literal["edge"]:
        return "edge"

    def to_dict(self) -> dict:
        return {
            "kind": "edge",
            "edge_id": self.edge_id,
            "t_start": round(self.t_start, 9),
            "t_end": round(self.t_end, 9),
        }


@dataclass(frozen=True)
class FaceBacking:
    """
    A segment lying in the interior of a real B-Rep face.

    ``uv`` holds one ``(u, v)`` pair per point of the owning ``CurveSegment``,
    in the same order, so any point can be recovered as ``S(u, v)`` and checked
    against the surface *and* against the face's trimmed region (gate H0.3).

    The 1:1 length correspondence with ``CurveSegment.points`` is enforced in
    ``CurveSegment.__post_init__`` — a UV list that does not match its point
    list is exactly the kind of silent drift H0 exists to catch.
    """

    face_id: int
    uv: tuple[tuple[float, float], ...]

    @property
    def kind(self) -> Literal["face"]:
        return "face"

    def to_dict(self) -> dict:
        return {
            "kind": "face",
            "face_id": self.face_id,
            "uv": [[round(u, 9), round(v, 9)] for u, v in self.uv],
            "uv_count": len(self.uv),
        }


SegmentBacking = EdgeBacking | FaceBacking


SegmentKind = Literal[
    "silhouette",       # a genuine g = 0 crossing
    "tangential",       # |g| <= eps on BOTH sides — a zero-draft edge
    "zero_draft_band",  # medial curve of a collapsed degenerate band (plan 5.3)
    "boundary",         # single-adjacent-face rim edge
]


@dataclass(frozen=True)
class CurveSegment:
    """
    One silhouette curve segment, always backed by real OCC geometry.

    ``points`` are exact 3-D points obtained from the backing — ``C(t)`` for an
    edge, ``S(u, v)`` for a face. They are NEVER produced by fitting,
    projecting, or smoothing (plan H0.4 / §9.5).
    """

    segment_id: int
    points: tuple[Vec3, ...]
    backing: SegmentBacking
    kind: SegmentKind
    #: Signed dot ``g = n·d`` sampled at each point. Used by H0.3's
    #: ``|g| <= tau_silhouette`` check and by the ranking stage; stored rather
    #: than recomputed so the validator can check it independently.
    g_values: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            raise ValueError(
                f"CurveSegment {self.segment_id} needs at least 2 points, got {len(self.points)}."
            )
        if isinstance(self.backing, FaceBacking) and len(self.backing.uv) != len(self.points):
            raise ValueError(
                f"CurveSegment {self.segment_id}: FaceBacking has {len(self.backing.uv)} UV "
                f"pair(s) but the segment has {len(self.points)} point(s). Every face-backed "
                "point must be recoverable as S(u, v) — see gate H0.3."
            )
        if self.g_values and len(self.g_values) != len(self.points):
            raise ValueError(
                f"CurveSegment {self.segment_id}: {len(self.g_values)} g value(s) for "
                f"{len(self.points)} point(s)."
            )

    @property
    def start(self) -> Vec3:
        return self.points[0]

    @property
    def end(self) -> Vec3:
        return self.points[-1]

    @property
    def provenance(self) -> Literal["edge", "face"]:
        return self.backing.kind

    def to_dict(self) -> dict:
        return {
            "segment_id": self.segment_id,
            "kind": self.kind,
            "provenance": self.provenance,
            "backing": self.backing.to_dict(),
            "point_count": len(self.points),
            "points": [[round(c, 6) for c in p] for p in self.points],
            "g_values": [round(g, 9) for g in self.g_values],
        }


# ---------------------------------------------------------------------------
# H0 — on-surface validity
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OnSurfaceReport:
    """
    Measured result of gate H0 (plan §7, H0).

    Every field is a MEASUREMENT against the B-Rep — never against the display
    tessellation and never against a camera projection. A candidate whose
    ``passed`` is False is not ranked, not rendered as a parting line, and not
    passed to the surface provider.
    """

    passed: bool
    max_surface_deviation_mm: float
    max_edge_deviation_mm: float
    max_silhouette_error: float
    off_face_point_count: int
    unbacked_segment_count: int
    #: ``(segment_id, point)`` of the worst deviation, for the UI overlay.
    worst_offender: tuple[int, Vec3] | None = None
    failed_subtests: tuple[str, ...] = ()      # e.g. ("H0.3",)
    notes: tuple[str, ...] = ()

    @classmethod
    def not_run(cls, reason: str = "H0 was not evaluated.") -> "OnSurfaceReport":
        return cls(
            passed=False,
            max_surface_deviation_mm=float("nan"),
            max_edge_deviation_mm=float("nan"),
            max_silhouette_error=float("nan"),
            off_face_point_count=0,
            unbacked_segment_count=0,
            notes=(reason,),
        )

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "max_surface_deviation_mm": self.max_surface_deviation_mm,
            "max_edge_deviation_mm": self.max_edge_deviation_mm,
            "max_silhouette_error": self.max_silhouette_error,
            "off_face_point_count": self.off_face_point_count,
            "unbacked_segment_count": self.unbacked_segment_count,
            "worst_offender": (
                {"segment_id": self.worst_offender[0],
                 "point": [round(c, 6) for c in self.worst_offender[1]]}
                if self.worst_offender is not None else None
            ),
            "failed_subtests": list(self.failed_subtests),
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# H5 — side-action referral (emit only; never routed during P0-P6)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SideActionReferral:
    """
    A loop disqualified as a MAIN-SPLIT candidate because it crosses an
    undercut — routed onward, **not** declared infeasible (plan H5, §12.8).

    Carries everything Stage 4 (``side_core.py``) would need, so enabling
    automatic routing later adds a call site rather than changing this type.
    **Nothing in this package may import ``side_core``** — enforced by test.

    ``release_direction_hint`` is a DIRECTION, never a tooling mechanism. Per
    ``.claude/rules/honesty-and-scope.md``, deciding lifter vs. slide vs.
    collapsible core is explicitly not something this project does.
    """

    feature_ids: tuple[int, ...]
    conflicting_segment_ids: tuple[int, ...]
    conflict_length_mm: float
    release_direction_hint: Vec3 | None = None
    note: str = (
        "Main parting line cannot pass cleanly through this feature; "
        "requires a side action."
    )

    def to_dict(self) -> dict:
        return {
            "feature_ids": list(self.feature_ids),
            "conflicting_segment_ids": list(self.conflicting_segment_ids),
            "conflict_length_mm": round(self.conflict_length_mm, 4),
            "release_direction_hint": (
                [round(c, 6) for c in self.release_direction_hint]
                if self.release_direction_hint is not None else None
            ),
            "note": self.note,
        }


# ---------------------------------------------------------------------------
# Hard feasibility filter
# ---------------------------------------------------------------------------

GateId = Literal["H0", "H1", "H2", "H3", "H4", "H5", "H6", "H7"]

#: Ordered exactly as the filter runs them. H0 first regardless of cost —
#: every later test measures a curve that must first be proven to be on the
#: part (plan §7).
HARD_GATES: tuple[GateId, ...] = ("H0", "H1", "H2", "H3", "H4", "H5", "H6", "H7")


@dataclass(frozen=True)
class FeasibilityReport:
    """
    Outcome of gates H0-H7 for one candidate (plan §7).

    ``measurements`` holds EVERY gate's measured value, pass or fail — the
    material P3a calibrates ``kappa_min`` from, and the material the agent
    explains rejections with.

    ``referral`` is set (and ``failed_gate == "H5"``) when the candidate was
    routed to side-action analysis rather than rejected outright. Callers MUST
    distinguish these: a referral is a finding, not a failure.
    """

    passed: bool
    failed_gate: GateId | None = None
    reason: str = ""
    measurements: dict[str, float] = field(default_factory=dict)
    on_surface: OnSurfaceReport | None = None
    referral: SideActionReferral | None = None

    @property
    def requires_side_action(self) -> bool:
        return self.referral is not None

    @property
    def outcome(self) -> Literal["feasible", "referred_to_side_action", "rejected"]:
        if self.passed:
            return "feasible"
        if self.requires_side_action:
            return "referred_to_side_action"
        return "rejected"

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "outcome": self.outcome,
            "failed_gate": self.failed_gate,
            "reason": self.reason,
            "measurements": {k: v for k, v in sorted(self.measurements.items())},
            "on_surface": self.on_surface.to_dict() if self.on_surface else None,
            "referral": self.referral.to_dict() if self.referral else None,
        }


# ---------------------------------------------------------------------------
# Ranking — a scorecard, never a score
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CandidateScore:
    """
    The lexicographic ranking tiers T1-T7 (plan §8), reported as a scorecard.

    Deliberately NOT combined into a single number: with a weighted sum the
    weights decide the winner, and no weights are defensible yet. ``sort_key``
    returns the tuple the comparison actually uses.

    There is no ``confidence`` field here and there never will be — see plan
    §12.7. If a caller wants one number, the honest answer is "which tier did
    it win at, and by how much".
    """

    coverage: float                    # T1 max
    undercut_proximity: float          # T2 min
    pull_axis_span_mm: float           # T3 min
    ambiguous_area_fraction: float     # T4 min
    excess_turning: float              # T5 min
    length_3d_mm: float                # T6 min
    stable_id: str                     # T7 deterministic final tie-break
    #: Which tier decided this candidate's rank against the runner-up.
    won_at_tier: str | None = None
    #: True when ``coverage``'s denominator was the exact tessellation-union
    #: area rather than the cheap Cauchy upper bound. When False, ``coverage``
    #: is a CONSERVATIVE UNDER-ESTIMATE and must be reported as such (§8.1).
    coverage_is_exact: bool = False

    def sort_key(self) -> tuple:
        """Lexicographic key; ``max()`` over this reproduces plan §8's order."""
        return (
            self.coverage,                    # T1 max
            -self.undercut_proximity,         # T2 min
            -self.pull_axis_span_mm,          # T3 min
            -self.ambiguous_area_fraction,    # T4 min
            -self.excess_turning,             # T5 min
            -self.length_3d_mm,               # T6 min
            self.stable_id,                   # T7 deterministic
        )

    def to_dict(self) -> dict:
        return {
            "coverage": round(self.coverage, 6),
            "coverage_is_exact": self.coverage_is_exact,
            "undercut_proximity": round(self.undercut_proximity, 6),
            "pull_axis_span_mm": round(self.pull_axis_span_mm, 4),
            "ambiguous_area_fraction": round(self.ambiguous_area_fraction, 6),
            "excess_turning": round(self.excess_turning, 6),
            "length_3d_mm": round(self.length_3d_mm, 4),
            "stable_id": self.stable_id,
            "won_at_tier": self.won_at_tier,
        }


@dataclass(frozen=True)
class EnumerationBounds:
    """
    How the candidate set was produced, and whether any bound was hit.

    Reported because v1's search limits were hardcoded in a function body
    (``parting_line.py:3238-3239``) and invisible in the result — so a part
    that silently fell back to a degraded strategy looked identical to one
    that did not (audit RC-9/RC-10).
    """

    strategy: Literal["single_cycle", "cycle_basis", "johnson", "beam", "none"]
    cyclomatic_number: int
    node_count: int
    edge_count: int
    branch_node_count: int
    candidates_found: int
    k_max: int
    k_max_hit: bool = False
    time_budget_s: float = 0.0
    time_budget_hit: bool = False

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "cyclomatic_number": self.cyclomatic_number,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "branch_node_count": self.branch_node_count,
            "candidates_found": self.candidates_found,
            "k_max": self.k_max,
            "k_max_hit": self.k_max_hit,
            "time_budget_s": self.time_budget_s,
            "time_budget_hit": self.time_budget_hit,
        }


@dataclass(frozen=True)
class PartingLoopCandidate:
    """
    One candidate closed loop (plan §6.3).

    ``segments`` are the ordered, real, on-surface segments; ``points`` is the
    concatenated polyline. Both come from OCC geometry — this object holds no
    smoothed or fitted representation. A display-only smoothed variant, if one
    is ever produced, lives elsewhere and is tagged ``display_only`` (§9.5).
    """

    candidate_id: int
    segments: tuple[CurveSegment, ...]
    points: tuple[Vec3, ...]
    is_closed: bool
    #: How this loop was found; mirrors ``EnumerationBounds.strategy``.
    discovered_by: Literal["single_cycle", "cycle_basis", "johnson", "beam", "loop_union"]
    #: The ordered polyline of EACH component curve. ``Γ`` is a **disjoint
    #: union** of closed curves (plan C1, corrected 2026-08-09), not a single
    #: loop: a part with a through-hole needs outer rim ⊔ hole rim, because
    #: cutting the outer rim alone leaves the top face connected to the bottom
    #: through the hole wall. Defaults to ``(points,)`` for a single loop.
    loops: tuple[tuple[Vec3, ...], ...] = ()
    feasibility: FeasibilityReport | None = None
    score: CandidateScore | None = None

    def __post_init__(self) -> None:
        if not self.loops:
            object.__setattr__(self, "loops", (self.points,))

    @property
    def loop_count(self) -> int:
        return len(self.loops)

    @property
    def provenance_mix(self) -> dict[str, int]:
        """Segment counts by provenance — the P5 overlay colours use this."""
        mix: dict[str, int] = {"edge": 0, "face": 0}
        for segment in self.segments:
            mix[segment.provenance] += 1
        return mix

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "discovered_by": self.discovered_by,
            "is_closed": self.is_closed,
            "loop_count": self.loop_count,
            "loop_point_counts": [len(loop) for loop in self.loops],
            "segment_count": len(self.segments),
            "point_count": len(self.points),
            "provenance_mix": self.provenance_mix,
            "segments": [s.to_dict() for s in self.segments],
            "points": [[round(c, 6) for c in p] for p in self.points],
            "feasibility": self.feasibility.to_dict() if self.feasibility else None,
            "score": self.score.to_dict() if self.score else None,
        }


# ---------------------------------------------------------------------------
# Core/cavity — derived from H3's regions, never from a normal-sign test
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FaceClassification:
    """
    Per-face core/cavity result (plan §9.2).

    ``"split"`` is a first-class label: a face cut by the parting loop reports
    BOTH sub-areas and is never forced onto one side. v1's single UV-centroid
    normal silently picks one (audit RC-8), which is wrong for exactly the
    large curved flank faces where it matters most.

    ``min_g``/``max_g`` come from an M x M multi-sample of the face; a face
    labelled anything other than ``"split"`` whose g values straddle zero is an
    inconsistency, counted and reported rather than hidden.
    """

    face_id: int
    label: Literal["cavity", "core", "split", "ambiguous"]
    cavity_area_mm2: float
    core_area_mm2: float
    mean_g: float
    min_g: float
    max_g: float
    sample_count: int

    @property
    def straddles_zero(self) -> bool:
        return self.min_g < 0.0 < self.max_g

    @property
    def is_inconsistent(self) -> bool:
        """A non-split face whose sampled normals straddle the parting plane."""
        return self.label in ("cavity", "core") and self.straddles_zero

    def to_dict(self) -> dict:
        return {
            "face_id": self.face_id,
            "label": self.label,
            "cavity_area_mm2": round(self.cavity_area_mm2, 4),
            "core_area_mm2": round(self.core_area_mm2, 4),
            "mean_g": round(self.mean_g, 6),
            "min_g": round(self.min_g, 6),
            "max_g": round(self.max_g, 6),
            "sample_count": self.sample_count,
            "straddles_zero": self.straddles_zero,
            "is_inconsistent": self.is_inconsistent,
        }
