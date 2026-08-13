"""
backend/geometry/parting_line.py
--------------------------------
Initial parting-line candidate detection.

This module implements the first, low-risk part of the Nee/Hou pipeline:

* Nee-style silhouette edge detection from adjacent face normals relative to a
  pull direction.
* Boundary/near-parting edge candidate capture for open rims or vertical faces.
* Simple connected-component grouping over candidate edges.
* Ordered-wire construction and projection-aware component selection.
* First-pass graph-weighted refinement and display smoothing.

It does not yet implement the full Hou optimization paper.  The refinement
implemented here is a conservative, deterministic graph cleanup layer that
prepares stable candidate curves for visualization and later optimization.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Callable, Literal

try:
    import networkx as nx  # type: ignore[import-untyped]
    _NX_AVAILABLE = True
except ImportError:
    _NX_AVAILABLE = False
    nx = None  # type: ignore[assignment]

try:
    import numpy as _np  # type: ignore[import-untyped]
    from OCC.Core.BRepBuilderAPI import (
        BRepBuilderAPI_MakeEdge,
        BRepBuilderAPI_MakeFace,
        BRepBuilderAPI_MakeWire,
    )
    from OCC.Core.BRepFill import BRepFill_Filling
    from OCC.Core.BRepGProp import brepgprop_SurfaceProperties
    from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.gp import gp_Dir, gp_Pln, gp_Pnt, gp_Vec
    _OCC_SURFACE_AVAILABLE = True
except (ImportError, Exception):
    _OCC_SURFACE_AVAILABLE = False
    _np = None  # type: ignore[assignment]

from backend.models.geometry_models import (
    EdgeData,
    PartGeometry,
    Vec3,
    cross3,
    dot3,
    mag3,
    normalize3,
)


PartingCandidateKind = Literal[
    "silhouette",
    "near_parting",
    "boundary",
    "non_manifold",
    "skipped",
]


@dataclass(frozen=True)
class PartingLineEdgeCandidate:
    """One edge classified for initial parting-line candidacy."""

    edge_id: int
    adjacent_face_ids: list[int]
    kind: PartingCandidateKind
    score: float
    length_mm: float
    signed_dots: list[float] = field(default_factory=list)
    reason: str = ""

    @property
    def is_candidate(self) -> bool:
        return self.kind in {"silhouette", "near_parting", "boundary", "non_manifold"}

    def to_dict(self) -> dict:
        return {
            "edge_id": self.edge_id,
            "adjacent_face_ids": self.adjacent_face_ids,
            "kind": self.kind,
            "is_candidate": self.is_candidate,
            "score": round(self.score, 6),
            "length_mm": round(self.length_mm, 4),
            "signed_dots": [round(value, 6) for value in self.signed_dots],
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PartingLineCandidateNoise:
    """Noise/risk estimate for one connected component of candidate edges."""

    score: float
    level: str
    factors: list[str] = field(default_factory=list)

    @classmethod
    def empty(cls) -> "PartingLineCandidateNoise":
        return cls(score=0.0, level="none", factors=[])

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 4),
            "level": self.level,
            "factors": self.factors,
        }


@dataclass(frozen=True)
class PartingLineComponent:
    """Connected component of candidate parting/silhouette edges."""

    component_id: int
    edge_ids: list[int]
    total_length_mm: float
    candidate_kinds: dict[str, int]
    point_count: int
    noise: PartingLineCandidateNoise = field(default_factory=PartingLineCandidateNoise.empty)

    def to_dict(self) -> dict:
        return {
            "component_id": self.component_id,
            "edge_ids": self.edge_ids,
            "edge_count": len(self.edge_ids),
            "total_length_mm": round(self.total_length_mm, 4),
            "candidate_kinds": self.candidate_kinds,
            "point_count": self.point_count,
            "noise": self.noise.to_dict(),
        }


@dataclass(frozen=True)
class PartingLineProjection:
    """2-D projection metrics for a candidate wire in the pull-normal plane."""

    u_axis: Vec3
    v_axis: Vec3
    signed_area_mm2: float
    abs_area_mm2: float
    bbox_area_mm2: float
    perimeter_mm: float
    point_count: int
    is_projected_closed: bool
    quality: str

    @classmethod
    def empty(cls) -> "PartingLineProjection":
        return cls(
            u_axis=(1.0, 0.0, 0.0),
            v_axis=(0.0, 1.0, 0.0),
            signed_area_mm2=0.0,
            abs_area_mm2=0.0,
            bbox_area_mm2=0.0,
            perimeter_mm=0.0,
            point_count=0,
            is_projected_closed=False,
            quality="empty",
        )

    def to_dict(self) -> dict:
        return {
            "u_axis": [round(value, 6) for value in self.u_axis],
            "v_axis": [round(value, 6) for value in self.v_axis],
            "signed_area_mm2": round(self.signed_area_mm2, 4),
            "abs_area_mm2": round(self.abs_area_mm2, 4),
            "bbox_area_mm2": round(self.bbox_area_mm2, 4),
            "perimeter_mm": round(self.perimeter_mm, 4),
            "point_count": self.point_count,
            "is_projected_closed": self.is_projected_closed,
            "quality": self.quality,
        }


@dataclass(frozen=True)
class PartingLineUndercutConflict:
    """Undercut-feature conflict summary for one candidate parting wire."""

    checked: bool
    conflict_score: float
    conflict_level: str
    conflicting_feature_ids: list[int] = field(default_factory=list)
    conflicting_face_ids: list[int] = field(default_factory=list)
    direct_edge_face_conflict_ids: list[int] = field(default_factory=list)
    near_feature_conflicts: list[dict] = field(default_factory=list)
    method: str = "not-run"
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def not_checked(cls, reason: str = "No undercut context supplied.") -> "PartingLineUndercutConflict":
        return cls(
            checked=False,
            conflict_score=0.0,
            conflict_level="not_checked",
            method="not-run",
            warnings=[reason],
        )

    def to_dict(self) -> dict:
        return {
            "checked": self.checked,
            "conflict_score": round(self.conflict_score, 4),
            "conflict_level": self.conflict_level,
            "conflicting_feature_ids": self.conflicting_feature_ids,
            "conflicting_face_ids": self.conflicting_face_ids,
            "direct_edge_face_conflict_ids": self.direct_edge_face_conflict_ids,
            "near_feature_conflicts": self.near_feature_conflicts,
            "method": self.method,
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class PartingLineQualityAssessment:
    """Selection-quality assessment for one candidate parting wire."""

    score: float
    level: str
    factors: list[str] = field(default_factory=list)
    penalties: dict[str, float] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> "PartingLineQualityAssessment":
        return cls(score=0.0, level="empty", factors=["no ordered wire"], penalties={})

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 4),
            "level": self.level,
            "factors": self.factors,
            "penalties": {
                key: round(value, 4)
                for key, value in self.penalties.items()
            },
        }


@dataclass(frozen=True)
class PartingLineGraphCleanup:
    """Structured report for the Hou-style weighted graph cleanup pass."""

    status: str
    strategy: str
    input_edge_count: int
    orderable_edge_count: int
    retained_edge_count: int
    removed_edge_count: int
    branch_point_count: int
    retained_edge_ids: list[int] = field(default_factory=list)
    removed_edge_ids: list[int] = field(default_factory=list)
    conflict_penalized_edge_ids: list[int] = field(default_factory=list)
    retained_conflict_edge_ids: list[int] = field(default_factory=list)
    removed_conflict_edge_ids: list[int] = field(default_factory=list)
    search_state_count: int = 0
    search_state_limit: int = 0
    search_edge_limit: int = 0
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def not_run(cls, reason: str = "Graph cleanup was not required.") -> "PartingLineGraphCleanup":
        return cls(
            status="not_run",
            strategy="not-run",
            input_edge_count=0,
            orderable_edge_count=0,
            retained_edge_count=0,
            removed_edge_count=0,
            branch_point_count=0,
            warnings=[reason] if reason else [],
        )

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "strategy": self.strategy,
            "input_edge_count": self.input_edge_count,
            "orderable_edge_count": self.orderable_edge_count,
            "retained_edge_count": self.retained_edge_count,
            "removed_edge_count": self.removed_edge_count,
            "branch_point_count": self.branch_point_count,
            "retained_edge_ids": self.retained_edge_ids,
            "removed_edge_ids": self.removed_edge_ids,
            "conflict_penalized_edge_ids": self.conflict_penalized_edge_ids,
            "retained_conflict_edge_ids": self.retained_conflict_edge_ids,
            "removed_conflict_edge_ids": self.removed_conflict_edge_ids,
            "search_state_count": self.search_state_count,
            "search_state_limit": self.search_state_limit,
            "search_edge_limit": self.search_edge_limit,
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class PartingLineWire:
    """Ordered wire approximation built from one candidate component."""

    component_id: int | None
    ordered_edge_ids: list[int]
    points: list[Vec3]
    is_closed: bool
    branch_point_count: int
    gap_count: int
    skipped_edge_ids: list[int]
    quality: str
    projection: PartingLineProjection = field(default_factory=PartingLineProjection.empty)
    undercut_conflict: PartingLineUndercutConflict = field(
        default_factory=PartingLineUndercutConflict.not_checked
    )
    quality_assessment: PartingLineQualityAssessment = field(
        default_factory=PartingLineQualityAssessment.empty
    )
    selection_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "component_id": self.component_id,
            "ordered_edge_ids": self.ordered_edge_ids,
            "edge_count": len(self.ordered_edge_ids),
            "points": [
                [round(coord, 4) for coord in point]
                for point in self.points
            ],
            "point_count": len(self.points),
            "is_closed": self.is_closed,
            "branch_point_count": self.branch_point_count,
            "gap_count": self.gap_count,
            "skipped_edge_ids": self.skipped_edge_ids,
            "quality": self.quality,
            "projection": self.projection.to_dict(),
            "undercut_conflict": self.undercut_conflict.to_dict(),
            "quality_assessment": self.quality_assessment.to_dict(),
            "selection_score": round(self.selection_score, 4),
        }


@dataclass(frozen=True)
class PartingLineRefinement:
    """Graph-refined and display-smoothed parting-curve candidate."""

    status: str
    method: str
    refined_edge_ids: list[int]
    removed_edge_ids: list[int]
    raw_points: list[Vec3]
    refined_points: list[Vec3]
    smoothing_iterations: int
    confidence: float
    quality: str
    projection: PartingLineProjection = field(default_factory=PartingLineProjection.empty)
    display_metrics: dict[str, float | int] = field(default_factory=dict)
    graph_cleanup: PartingLineGraphCleanup = field(default_factory=PartingLineGraphCleanup.not_run)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        rounded_metrics: dict[str, float | int] = {}
        for key, value in self.display_metrics.items():
            if isinstance(value, int):
                rounded_metrics[key] = value
            elif isinstance(value, float):
                rounded_metrics[key] = round(value, 4)
            else:
                rounded_metrics[key] = value
        return {
            "status": self.status,
            "method": self.method,
            "refined_edge_ids": self.refined_edge_ids,
            "removed_edge_ids": self.removed_edge_ids,
            "raw_points": [
                [round(coord, 4) for coord in point]
                for point in self.raw_points
            ],
            "refined_points": [
                [round(coord, 4) for coord in point]
                for point in self.refined_points
            ],
            "raw_point_count": len(self.raw_points),
            "refined_point_count": len(self.refined_points),
            "smoothing_iterations": self.smoothing_iterations,
            "confidence": round(self.confidence, 4),
            "quality": self.quality,
            "projection": self.projection.to_dict(),
            "display_metrics": rounded_metrics,
            "graph_cleanup": self.graph_cleanup.to_dict(),
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class PartingLineReadiness:
    """Demo/report readiness summary for the selected parting-line candidate."""

    status: str
    score: float
    label: str
    reasons: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "score": round(self.score, 4),
            "label": self.label,
            "reasons": self.reasons,
            "blockers": self.blockers,
        }


@dataclass(frozen=True)
class PartingLineDiagnosticGate:
    """
    Operational gate for downstream consumers of the parting-line result.

    ``readiness`` is the geometric quality score.  This gate translates that
    score into practical decisions for the UI, validation harness, report
    export, and future core/cavity module.
    """

    status: str
    can_display_curve: bool
    can_use_for_report: bool
    blocks_core_cavity: bool
    requires_manual_review: bool
    severity: str
    summary: str
    recovery_hint: str
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "can_display_curve": self.can_display_curve,
            "can_use_for_report": self.can_use_for_report,
            "blocks_core_cavity": self.blocks_core_cavity,
            "requires_manual_review": self.requires_manual_review,
            "severity": self.severity,
            "summary": self.summary,
            "recovery_hint": self.recovery_hint,
            "limitations": self.limitations,
        }


@dataclass(frozen=True)
class PartingLineDiagnostics:
    """Structured failure/warning context for parting-line detection."""

    status: str
    failure_code: str | None
    recovery_hint: str
    skipped_edge_count: int
    skipped_reasons: dict[str, int] = field(default_factory=dict)
    unorderable_edge_count: int = 0
    branch_point_count: int = 0
    gap_count: int = 0
    warning_count: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "failure_code": self.failure_code,
            "recovery_hint": self.recovery_hint,
            "skipped_edge_count": self.skipped_edge_count,
            "skipped_reasons": self.skipped_reasons,
            "unorderable_edge_count": self.unorderable_edge_count,
            "branch_point_count": self.branch_point_count,
            "gap_count": self.gap_count,
            "warning_count": self.warning_count,
            "notes": self.notes,
        }


@dataclass
class PartingSurfaceResult:
    """
    Result of parting surface generation (Milestone 1.9).

    The ``occ_shape`` field holds the raw OCC surface for downstream use
    (core/cavity Boolean split in Milestone 1.10).  It is NOT JSON-safe —
    use ``to_dict()`` for API/frontend serialization.
    """

    status: str          # "generated_planar" | "generated_filling" | "failed" | "not_attempted"
    strategy: str        # "pca_planar" | "brepfill_filling" | "none"
    planar_deviation_mm: float = 0.0
    extension_factor: float = 1.5
    area_mm2: float = 0.0
    failure_reason: str | None = None
    occ_shape: object = None  # TopoDS_Shape (not serialized)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "strategy": self.strategy,
            "planar_deviation_mm": round(self.planar_deviation_mm, 6),
            "extension_factor": self.extension_factor,
            "area_mm2": round(self.area_mm2, 4),
            "failure_reason": self.failure_reason,
            "occ_available": _OCC_SURFACE_AVAILABLE,
        }


@dataclass(frozen=True)
class PartingLineResult:
    """Initial parting-line detection result."""

    pull_direction: Vec3
    method: str
    candidates: list[PartingLineEdgeCandidate]
    components: list[PartingLineComponent]
    component_wires: list[PartingLineWire]
    selected_component_id: int | None
    selected_edge_ids: list[int]
    wire_points: list[Vec3]
    selected_wire: PartingLineWire
    refinement: PartingLineRefinement
    refined_undercut_conflict: PartingLineUndercutConflict
    readiness: PartingLineReadiness
    diagnostic_gate: PartingLineDiagnosticGate
    diagnostics: PartingLineDiagnostics
    warnings: list[str] = field(default_factory=list)
    # Milestone 1.8: closure guarantee
    closure_error_mm: float = 0.0
    closure_guaranteed: bool = False
    #: Number of real B-Rep edges spliced in to close an otherwise-open loop.
    #: 0 means the wire was already closed (or closure was not achieved).
    #: Surfaced so an engineer can see the curve was completed through part
    #: geometry rather than assumed closed.
    closure_bridge_edge_count: int = 0
    #: Selected loop's projected bounding-box area divided by the part's
    #: projected bounding-box area, both in the pull-normal plane.
    #: A main parting line wraps the outer silhouette, so this should be
    #: close to 1.0.  A small value means the engine selected a local feature
    #: loop (a hole rim, a boss) rather than the main parting line — the
    #: failure mode that Bug H made silently invisible.
    silhouette_coverage_ratio: float = 0.0
    #: What component bridging (Milestone 1.7) did:
    #:   "not_needed"                  – a closed loop was already selected
    #:   "applied"                     – bridging improved the wire and was kept
    #:   "discarded_not_an_improvement" – bridging ran but made things worse
    #:   "unavailable"                 – networkx missing
    #:   "disabled"                    – caller passed bridge_components=False
    bridging_status: str = "not_needed"
    # Milestone 1.9: parting surface
    parting_surface: PartingSurfaceResult = field(
        default_factory=lambda: PartingSurfaceResult(status="not_attempted", strategy="none")
    )

    @property
    def candidate_edge_ids(self) -> list[int]:
        return [candidate.edge_id for candidate in self.candidates if candidate.is_candidate]

    @property
    def silhouette_edge_ids(self) -> list[int]:
        return [
            candidate.edge_id
            for candidate in self.candidates
            if candidate.kind == "silhouette"
        ]

    @property
    def undercut_conflict(self) -> PartingLineUndercutConflict:
        return self.refined_undercut_conflict

    @property
    def selection_quality(self) -> PartingLineQualityAssessment:
        return self.selected_wire.quality_assessment

    def to_dict(self) -> dict:
        return {
            "pull_direction": [round(value, 6) for value in self.pull_direction],
            "method": self.method,
            "edge_counts": {
                "classified": len(self.candidates),
                "candidate": len(self.candidate_edge_ids),
                "silhouette": len(self.silhouette_edge_ids),
                "selected": len(self.selected_edge_ids),
            },
            "component_count": len(self.components),
            "selected_component_id": self.selected_component_id,
            "selected_edge_ids": self.selected_edge_ids,
            "selected_wire": self.selected_wire.to_dict(),
            "selection_quality": self.selected_wire.quality_assessment.to_dict(),
            "undercut_conflict": self.refined_undercut_conflict.to_dict(),
            "selected_wire_undercut_conflict": self.selected_wire.undercut_conflict.to_dict(),
            "refined_undercut_conflict": self.refined_undercut_conflict.to_dict(),
            "refinement": self.refinement.to_dict(),
            "readiness": self.readiness.to_dict(),
            "diagnostic_gate": self.diagnostic_gate.to_dict(),
            "diagnostics": self.diagnostics.to_dict(),
            "refined_wire_points": [
                [round(coord, 4) for coord in point]
                for point in self.refinement.refined_points
            ],
            "component_wires": [wire.to_dict() for wire in self.component_wires],
            "wire_points": [
                [round(coord, 4) for coord in point]
                for point in self.wire_points
            ],
            "warnings": self.warnings,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "components": [component.to_dict() for component in self.components],
            "closure_error_mm": round(self.closure_error_mm, 6),
            "closure_guaranteed": self.closure_guaranteed,
            "closure_bridge_edge_count": self.closure_bridge_edge_count,
            "bridging_status": self.bridging_status,
            "silhouette_coverage_ratio": round(self.silhouette_coverage_ratio, 4),
            "parting_surface": self.parting_surface.to_dict(),
        }


def _face_signed_dot(part: PartGeometry, face_id: int, pull_direction: Vec3) -> float | None:
    face = part.get_face(face_id)
    if face is None or not face.normal_valid:
        return None
    return dot3(face.normal, pull_direction)


def _classify_edge(
    part: PartGeometry,
    edge: EdgeData,
    pull_direction: Vec3,
    *,
    dot_tolerance: float,
    boundary_dot_tolerance: float,
    include_boundary: bool,
) -> PartingLineEdgeCandidate:
    adjacent_face_ids = list(edge.adjacent_face_ids)
    signed_dots: list[float] = []
    missing_or_invalid = 0

    for face_id in adjacent_face_ids:
        value = _face_signed_dot(part, face_id, pull_direction)
        if value is None:
            missing_or_invalid += 1
        else:
            signed_dots.append(value)

    if missing_or_invalid:
        return PartingLineEdgeCandidate(
            edge_id=edge.edge_id,
            adjacent_face_ids=adjacent_face_ids,
            kind="skipped",
            score=0.0,
            length_mm=edge.length,
            signed_dots=signed_dots,
            reason=f"{missing_or_invalid} adjacent face normal(s) unavailable",
        )

    if len(adjacent_face_ids) == 1:
        if include_boundary:
            if abs(signed_dots[0]) > boundary_dot_tolerance:
                return PartingLineEdgeCandidate(
                    edge_id=edge.edge_id,
                    adjacent_face_ids=adjacent_face_ids,
                    kind="skipped",
                    score=0.0,
                    length_mm=edge.length,
                    signed_dots=signed_dots,
                    reason=(
                        "boundary edge ignored because its adjacent face is not "
                        "near the pull-direction parting plane"
                    ),
                )
            near_parting_score = 1.0 - min(1.0, abs(signed_dots[0]) / boundary_dot_tolerance)
            return PartingLineEdgeCandidate(
                edge_id=edge.edge_id,
                adjacent_face_ids=adjacent_face_ids,
                kind="boundary",
                score=max(0.15, near_parting_score),
                length_mm=edge.length,
                signed_dots=signed_dots,
                reason="single-face boundary/rim edge retained as parting candidate",
            )
        return PartingLineEdgeCandidate(
            edge_id=edge.edge_id,
            adjacent_face_ids=adjacent_face_ids,
            kind="skipped",
            score=0.0,
            length_mm=edge.length,
            signed_dots=signed_dots,
            reason="boundary edge ignored by configuration",
        )

    if len(adjacent_face_ids) > 2:
        return PartingLineEdgeCandidate(
            edge_id=edge.edge_id,
            adjacent_face_ids=adjacent_face_ids,
            kind="non_manifold",
            score=0.25,
            length_mm=edge.length,
            signed_dots=signed_dots,
            reason="non-manifold edge retained for review",
        )

    if len(signed_dots) != 2:
        return PartingLineEdgeCandidate(
            edge_id=edge.edge_id,
            adjacent_face_ids=adjacent_face_ids,
            kind="skipped",
            score=0.0,
            length_mm=edge.length,
            signed_dots=signed_dots,
            reason="expected two valid adjacent face normal dots",
        )

    dot_a, dot_b = signed_dots
    crosses_pull_plane = (
        (dot_a > dot_tolerance and dot_b < -dot_tolerance)
        or (dot_b > dot_tolerance and dot_a < -dot_tolerance)
    )
    if crosses_pull_plane:
        separation = min(1.0, abs(dot_a - dot_b) / 2.0)
        return PartingLineEdgeCandidate(
            edge_id=edge.edge_id,
            adjacent_face_ids=adjacent_face_ids,
            kind="silhouette",
            score=0.75 + 0.25 * separation,
            length_mm=edge.length,
            signed_dots=signed_dots,
            reason="adjacent face normals straddle pull direction",
        )

    near_parting = abs(dot_a) <= dot_tolerance or abs(dot_b) <= dot_tolerance
    if near_parting:
        closeness = 1.0 - min(1.0, min(abs(dot_a), abs(dot_b)) / dot_tolerance)
        return PartingLineEdgeCandidate(
            edge_id=edge.edge_id,
            adjacent_face_ids=adjacent_face_ids,
            kind="near_parting",
            score=0.35 + 0.25 * closeness,
            length_mm=edge.length,
            signed_dots=signed_dots,
            reason="at least one adjacent face lies near the parting plane",
        )

    return PartingLineEdgeCandidate(
        edge_id=edge.edge_id,
        adjacent_face_ids=adjacent_face_ids,
        kind="skipped",
        score=0.0,
        length_mm=edge.length,
        signed_dots=signed_dots,
        reason="adjacent faces do not straddle pull direction",
    )


def _noise_level(score: float) -> str:
    if score >= 0.65:
        return "high"
    if score >= 0.35:
        return "medium"
    if score > 0.0:
        return "low"
    return "none"


def _component_noise(candidate_kinds: dict[str, int]) -> PartingLineCandidateNoise:
    total = max(1, sum(candidate_kinds.values()))
    boundary_count = candidate_kinds.get("boundary", 0)
    non_manifold_count = candidate_kinds.get("non_manifold", 0)
    silhouette_count = candidate_kinds.get("silhouette", 0)
    near_count = candidate_kinds.get("near_parting", 0)
    score = 0.0
    factors: list[str] = []

    boundary_ratio = boundary_count / total
    non_manifold_ratio = non_manifold_count / total
    if boundary_count:
        contribution = 0.18 + 0.34 * boundary_ratio
        score += contribution
        factors.append(f"{boundary_count} boundary edge(s), ratio {boundary_ratio:.2f}")
    if non_manifold_count:
        contribution = 0.30 + 0.45 * non_manifold_ratio
        score += contribution
        factors.append(f"{non_manifold_count} non-manifold edge(s), ratio {non_manifold_ratio:.2f}")
    if silhouette_count == 0 and (boundary_count or non_manifold_count):
        score += 0.22
        factors.append("component has no strong silhouette edges")
    if near_count and silhouette_count == 0:
        score += 0.08
        factors.append("component is near-parting only")

    score = max(0.0, min(1.0, score))
    return PartingLineCandidateNoise(
        score=score,
        level=_noise_level(score),
        factors=factors,
    )


def _point_key(point: Vec3, tolerance: float) -> tuple[int, int, int]:
    scale = 1.0 / tolerance
    return (
        int(round(point[0] * scale)),
        int(round(point[1] * scale)),
        int(round(point[2] * scale)),
    )


def _candidate_components(
    edges_by_id: dict[int, EdgeData],
    candidates: list[PartingLineEdgeCandidate],
    *,
    point_tolerance: float,
) -> tuple[list[PartingLineComponent], dict[int, list[Vec3]]]:
    candidate_by_id = {
        candidate.edge_id: candidate
        for candidate in candidates
        if candidate.is_candidate
    }
    if not candidate_by_id:
        return [], {}

    point_to_edges: dict[tuple[int, int, int], set[int]] = {}
    edge_points: dict[int, list[Vec3]] = {}
    for edge_id in candidate_by_id:
        edge = edges_by_id.get(edge_id)
        if edge is None:
            continue
        points = [
            point
            for point in (edge.start_vertex, edge.end_vertex)
            if point is not None
        ]
        edge_points[edge_id] = points
        for point in points:
            point_to_edges.setdefault(_point_key(point, point_tolerance), set()).add(edge_id)

    neighbors: dict[int, set[int]] = {edge_id: set() for edge_id in candidate_by_id}
    for connected_edges in point_to_edges.values():
        for edge_id in connected_edges:
            neighbors[edge_id].update(connected_edges - {edge_id})

    components: list[PartingLineComponent] = []
    component_points: dict[int, list[Vec3]] = {}
    visited: set[int] = set()

    for start_edge_id in sorted(candidate_by_id):
        if start_edge_id in visited:
            continue
        stack = [start_edge_id]
        visited.add(start_edge_id)
        edge_ids: list[int] = []
        unique_points: dict[tuple[int, int, int], Vec3] = {}

        while stack:
            edge_id = stack.pop()
            edge_ids.append(edge_id)
            for point in edge_points.get(edge_id, []):
                unique_points.setdefault(_point_key(point, point_tolerance), point)
            for neighbor_id in sorted(neighbors.get(edge_id, ())):
                if neighbor_id not in visited:
                    visited.add(neighbor_id)
                    stack.append(neighbor_id)

        kind_counts: dict[str, int] = {}
        for edge_id in edge_ids:
            kind = candidate_by_id[edge_id].kind
            kind_counts[kind] = kind_counts.get(kind, 0) + 1

        component_id = len(components)
        total_length = sum(
            edges_by_id[edge_id].length
            for edge_id in edge_ids
            if edge_id in edges_by_id
        )
        components.append(PartingLineComponent(
            component_id=component_id,
            edge_ids=sorted(edge_ids),
            total_length_mm=total_length,
            candidate_kinds=kind_counts,
            point_count=len(unique_points),
            noise=_component_noise(kind_counts),
        ))
        component_points[component_id] = list(unique_points.values())

    components.sort(
        key=lambda component: (
            -component.total_length_mm,
            -component.candidate_kinds.get("silhouette", 0),
            component.component_id,
        )
    )
    remapped_points: dict[int, list[Vec3]] = {}
    remapped_components: list[PartingLineComponent] = []
    for new_id, component in enumerate(components):
        remapped_components.append(PartingLineComponent(
            component_id=new_id,
            edge_ids=component.edge_ids,
            total_length_mm=component.total_length_mm,
            candidate_kinds=component.candidate_kinds,
            point_count=component.point_count,
            noise=component.noise,
        ))
        remapped_points[new_id] = component_points[component.component_id]

    return remapped_components, remapped_points


def _bridge_via_angular_ring(
    components: list[PartingLineComponent],
    component_points: dict[int, list[Vec3]],
    edges_by_id: dict[int, EdgeData],
    candidate_by_id: dict[int, PartingLineEdgeCandidate],
    *,
    G_all: object,
    comp_endpoints: dict[int, list[tuple[int, int, int]]],
    sssp_cache: dict[tuple[int, int, int], tuple[dict, dict]],
    point_tolerance: float,
    u_axis: Vec3,
    v_axis: Vec3,
    part_extent_area: float,
    min_component_coverage_for_ring: float = 0.001,
) -> tuple[list[PartingLineComponent], dict[int, list[Vec3]], list[str]] | None:
    """
    Bug H-2 root-cause fix: bridge components into a RING (cycle), not a
    spanning tree.

    `_bridge_disconnected_components`'s original strategy always merges via
    union-find (`if _find(ci) == _find(cj): continue` before every merge) —
    textbook MST construction, which by definition produces a spanning tree
    over the components: N-1 bridges for N components, zero cycles among
    them. A tree can never contain a closed loop, so no wire tracer, however
    exhaustive, can ever find one through it — proven on Part3: an
    exhaustive 177,032-state search over the tree-bridged graph found none.

    This instead orders components by angle around their collective
    centroid (in the pull-normal plane) and bridges each to its next
    angular neighbor, wrapping around — N bridges for N components,
    explicitly closing the cycle. The wire tracer (which now does a real
    exact/contracted search, see Bug B) can then search for the best closed
    sub-loop within that cycle, including skipping some of it if a better
    closed sub-loop exists — this function only needs to make closure
    *possible*, not find the optimal loop itself.

    Components whose own individual projected extent is below
    `min_component_coverage_for_ring` (0.1% of the part's extent by default —
    deliberately low: real silhouette fragments are often individually small
    without being local features, and excluding too many turns the ring into
    disconnected arcs that still can't close, exactly the failure this
    function exists to avoid) are excluded before ring construction: this
    targets genuinely degenerate fragments (near-zero-area point pairs), not
    "small relative to the largest piece." Measured on Part3's real 22
    components: coverage ranged from 18.6% down to a heavy tail of
    sub-1% fragments that are still real parts of a fragmented silhouette —
    only 2 of 22 were truly degenerate (~0%). If the absolute threshold would
    exclude everything, falls back to 1% of the single largest component's
    extent, and if that still excludes everything, keeps every component
    rather than ring nothing.

    Returns None if there is nothing sensible to ring (fewer than 2
    qualifying components, or every angular link is unreachable) so the
    caller can fall back to the tree-based strategy.
    """
    def component_coverage(comp_id: int) -> float:
        pts = component_points.get(comp_id, [])
        if len(pts) < 2 or part_extent_area <= 0.0:
            return 0.0
        us = [dot3(p, u_axis) for p in pts]
        vs = [dot3(p, v_axis) for p in pts]
        area = (max(us) - min(us)) * (max(vs) - min(vs))
        return area / part_extent_area

    coverages = {c.component_id: component_coverage(c.component_id) for c in components}
    largest_coverage = max(coverages.values(), default=0.0)
    ring_candidates = [
        c for c in components
        if coverages[c.component_id] >= min_component_coverage_for_ring
        or (largest_coverage > 0.0 and coverages[c.component_id] >= 0.01 * largest_coverage)
    ]
    if len(ring_candidates) < 2:
        ring_candidates = [c for c in components if comp_endpoints.get(c.component_id)]
    if len(ring_candidates) < 2:
        return None

    def representative_point(comp_id: int) -> Vec3:
        pts = component_points.get(comp_id, [])
        n = len(pts)
        if n == 0:
            return (0.0, 0.0, 0.0)
        return (
            sum(p[0] for p in pts) / n,
            sum(p[1] for p in pts) / n,
            sum(p[2] for p in pts) / n,
        )

    reps = {c.component_id: representative_point(c.component_id) for c in ring_candidates}
    center_u = sum(dot3(reps[cid], u_axis) for cid in reps) / len(reps)
    center_v = sum(dot3(reps[cid], v_axis) for cid in reps) / len(reps)

    def angle_of(comp_id: int) -> float:
        u = dot3(reps[comp_id], u_axis)
        v = dot3(reps[comp_id], v_axis)
        return math.atan2(v - center_v, u - center_u)

    ring_order = sorted(ring_candidates, key=lambda c: angle_of(c.component_id))
    n = len(ring_order)

    candidate_edge_ids = set(candidate_by_id)

    def cheapest_path(
        comp_i_id: int, comp_j_id: int
    ) -> tuple[float | None, list[tuple[int, int, int]] | None]:
        best_cost: float | None = None
        best_path: list[tuple[int, int, int]] | None = None
        for ep_i in comp_endpoints.get(comp_i_id, []):
            dist_from_i, paths_from_i = sssp_cache.get(ep_i, ({}, {}))
            if not dist_from_i:
                continue
            for ep_j in comp_endpoints.get(comp_j_id, []):
                if ep_i == ep_j:
                    continue
                cost = dist_from_i.get(ep_j)
                if cost is None:
                    continue
                if best_cost is None or cost < best_cost:
                    best_cost = cost
                    best_path = paths_from_i[ep_j]
        return best_cost, best_path

    def add_bridge(comp_i_id: int, comp_j_id: int, cost: float, path: list, suffix: str = "") -> None:
        bridge_eids = [
            G_all[path[k]][path[k + 1]]["edge_id"]  # type: ignore[index]
            for k in range(len(path) - 1)
        ]
        new_bridge_eids = [e for e in bridge_eids if e not in candidate_edge_ids]
        ring_bridge_edge_ids.update(bridge_eids)
        link_messages.append(
            f"Ring bridge: component {comp_i_id} → {comp_j_id} via "
            f"{len(new_bridge_eids)} bridge edge(s) (path cost {cost:.3f} mm).{suffix}"
        )

    # Adaptive ring walk: start at index 0 in angular order and try to link
    # to the next unvisited node; if it is unreachable (e.g. blocked by an
    # undercut-face exclusion in G_all), skip it — it joins `dropped` — and
    # try the next one, continuing all the way around. This guarantees a
    # fully CLOSED cycle over whatever subset of `ring_candidates` ends up
    # mutually reachable, instead of a fixed angular-neighbor ring left
    # permanently broken at any unreachable link (measured on Part3: a fixed
    # ring left 2 gaps and 2 disconnected open arcs; this walk closes fully).
    ring_bridge_edge_ids: set[int] = set()
    link_messages: list[str] = []
    ringed_component_ids: list[int] = [ring_order[0].component_id]
    dropped: list[int] = []
    visited_indices = {0}
    anchor_idx = 0
    current_id = ring_order[0].component_id

    while len(visited_indices) < n:
        next_idx = None
        for offset in range(1, n + 1):
            candidate_idx = (anchor_idx + offset) % n
            if candidate_idx not in visited_indices:
                next_idx = candidate_idx
                break
        if next_idx is None:
            break
        next_id = ring_order[next_idx].component_id
        visited_indices.add(next_idx)
        cost, path = cheapest_path(current_id, next_id)
        if path is None:
            dropped.append(next_id)
            continue
        add_bridge(current_id, next_id, cost, path)
        ringed_component_ids.append(next_id)
        anchor_idx = next_idx
        current_id = next_id

    successful_links = len(link_messages)
    if successful_links == 0:
        return None

    # Close the cycle: connect the last successfully-attached component back
    # to the first one.
    start_id = ring_order[0].component_id
    ring_closed = False
    if current_id == start_id:
        ring_closed = True  # only possible if n == 1, already excluded above
    else:
        cost, path = cheapest_path(current_id, start_id)
        if path is not None:
            add_bridge(current_id, start_id, cost, path, suffix=" (closes the ring)")
            successful_links += 1
            ring_closed = True
        else:
            link_messages.append(
                f"Ring closing bridge {current_id} → {start_id} unreachable; ring could not fully close."
            )

    kept_candidate_edges: set[int] = set()
    for cid in ringed_component_ids:
        comp = next((c for c in components if c.component_id == cid), None)
        if comp is not None:
            kept_candidate_edges.update(comp.edge_ids)
    all_edge_ids = sorted(kept_candidate_edges | ring_bridge_edge_ids)

    total_length = sum(edges_by_id[eid].length for eid in all_edge_ids if eid in edges_by_id)
    all_pts: dict[tuple[int, int, int], Vec3] = {}
    for eid in all_edge_ids:
        edge = edges_by_id.get(eid)
        if edge is None:
            continue
        for pt in (edge.start_vertex, edge.end_vertex):
            if pt is not None:
                all_pts.setdefault(_point_key(pt, point_tolerance), pt)

    kind_counts: dict[str, int] = {}
    for eid in all_edge_ids:
        cand = candidate_by_id.get(eid)
        kind = cand.kind if cand is not None else "bridge"
        kind_counts[kind] = kind_counts.get(kind, 0) + 1

    merged_component = PartingLineComponent(
        component_id=0,
        edge_ids=all_edge_ids,
        total_length_mm=total_length,
        candidate_kinds=kind_counts,
        point_count=len(all_pts),
        noise=_component_noise(kind_counts),
    )

    summary = (
        f"Ring-bridged {len(ringed_component_ids)} of {len(components)} components into 1 "
        f"via {successful_links} ring link(s) following real B-Rep geometry — "
        f"a {'closed cycle' if ring_closed else 'broken cycle'}, not a spanning tree."
    )
    if dropped:
        summary += (
            f" {len(dropped)} component(s) dropped from the ring as unreachable from "
            "their angular neighbor (likely blocked by undercut exclusion or a genuine "
            "topological gap)."
        )
    pre_filtered_count = len(components) - len(ring_candidates)
    if pre_filtered_count:
        summary += (
            f" {pre_filtered_count} component(s) excluded before ring construction as "
            "probable local features (near-degenerate projected extent)."
        )
    if not ring_closed:
        summary += " The ring did not fully close."

    warnings = [summary, *link_messages]
    return [merged_component], {0: list(all_pts.values())}, warnings


def _bridge_disconnected_components(
    components: list[PartingLineComponent],
    component_points: dict[int, list[Vec3]],
    edges_by_id: dict[int, EdgeData],
    candidate_by_id: dict[int, PartingLineEdgeCandidate],
    *,
    point_tolerance: float,
    undercut_face_ids: set[int],
    bridge_penalty_factor: float = 4.0,
    boundary_bridge_factor: float = 0.6,
    part_extent_area: float = 0.0,
    projection_basis: tuple[Vec3, Vec3] | None = None,
    min_coverage_ratio: float = 0.0,
) -> tuple[list[PartingLineComponent], dict[int, list[Vec3]], list[str]]:
    """
    Bridge disconnected silhouette components through real B-Rep edges (Milestone 1.7).

    Routes between disconnected candidate components via the full part edge graph,
    using weighted shortest paths. Bridges follow real B-Rep edges — never straight
    lines that do not lie on the part. Only operates when networkx is available and
    there are 2+ disconnected components.

    bridge_cost per edge:
      candidate edge      → 1.0 × length   (free to reuse)
      boundary edge       → boundary_bridge_factor × length   (often where PL should run)
      non-candidate manif → bridge_penalty_factor × length
      undercut-overlapping→ +inf (never crossed)

    Bug H-2 (root cause fixed): when `part_extent_area`/`projection_basis`
    are supplied, this first tries `_bridge_via_angular_ring` — bridging
    components into a CYCLE (ordered by angle around their collective
    centroid) rather than the tree the strategy below always produces. A
    spanning tree (guaranteed by this function's union-find merge, see
    below) can never contain a closed loop; a ring can. Ring bridging also
    excludes probable local features (small components far from the
    silhouette) before construction. Only when ring bridging is inapplicable
    (no projection context) or fails entirely (nothing reachable) does this
    fall through to the strategy below.

    Fallback strategy (tree-based, original Milestone 1.7): greedily add the
    globally cheapest bridge between any two not-yet-merged components each
    round, via union-find, until nothing more is reachable. When
    `min_coverage_ratio` is also supplied, tracks the projected-extent
    coverage of the tree it is growing and stops as soon as that tree
    crosses it — leaving remaining components (probably local features)
    unmerged — rather than merging everything indiscriminately. Without
    projection context (`part_extent_area`/`projection_basis` both falsy),
    merges everything reachable with no early stop.

    Returns (merged_components, merged_points, warning_list). If bridging is not
    possible (networkx unavailable, unreachable components, < 2 components),
    returns the originals unchanged.
    """
    if not _NX_AVAILABLE or len(components) < 2:
        return components, component_points, []

    warnings: list[str] = []
    candidate_edge_ids = set(candidate_by_id)

    # Build G_all over ALL part edges with bridge costs.
    G_all: object = nx.Graph()  # type: ignore[union-attr]
    for edge in edges_by_id.values():
        if edge.start_vertex is None or edge.end_vertex is None:
            continue
        sk = _point_key(edge.start_vertex, point_tolerance)
        ek = _point_key(edge.end_vertex, point_tolerance)
        if sk == ek:
            continue  # degenerate or seam edge

        # Infinite cost for edges adjacent to any undercut face.
        if any(fid in undercut_face_ids for fid in edge.adjacent_face_ids):
            continue  # skip — don't route through undercut geometry

        if edge.edge_id in candidate_edge_ids:
            cost = 1.0 * edge.length
        elif edge.is_boundary:
            cost = boundary_bridge_factor * max(edge.length, 1e-9)
        else:
            cost = bridge_penalty_factor * max(edge.length, 1e-9)

        G_all.add_edge(sk, ek, edge_id=edge.edge_id, cost=cost)  # type: ignore[union-attr]

    if G_all.number_of_nodes() == 0:  # type: ignore[union-attr]
        return components, component_points, []

    # Map each component's point set to quantized keys present in G_all.
    comp_endpoints: dict[int, list[tuple[int, int, int]]] = {}
    for comp in components:
        pts = component_points.get(comp.component_id, [])
        comp_endpoints[comp.component_id] = [
            _point_key(p, point_tolerance)
            for p in pts
            if _point_key(p, point_tolerance) in G_all  # type: ignore[operator]
        ]

    # Precompute one single-source Dijkstra per unique component endpoint
    # (Bug D fix). `G_all` never changes across bridging rounds — only which
    # components are already merged does — so the shortest-path tree from
    # each endpoint is reusable for every round. The old code called
    # `nx.shortest_path(source, target)` freshly for every (ep_i, ep_j) pair
    # on every round: O(rounds x pairs x |ep_i| x |ep_j|) full Dijkstra runs.
    # On Part3 (22 components) that measured at >373,000 Dijkstra calls and
    # did not finish in 10+ minutes. Running Dijkstra once per source and
    # reusing the resulting distance/path maps as O(1) lookups collapses this
    # to O(total endpoints) Dijkstra runs plus O(rounds x pairs) dict lookups.
    all_endpoint_keys = sorted({ep for eps in comp_endpoints.values() for ep in eps})
    sssp_cache: dict[tuple[int, int, int], tuple[dict, dict]] = {}
    for ep in all_endpoint_keys:
        try:
            dist, paths = nx.single_source_dijkstra(G_all, ep, weight="cost")  # type: ignore[union-attr]
        except (nx.NodeNotFound, nx.exception.NetworkXError):  # type: ignore[union-attr]
            dist, paths = {}, {}
        sssp_cache[ep] = (dist, paths)

    # Bug H-2 root-cause fix: try ring bridging (a cycle over components)
    # before falling back to the tree-based greedy strategy below. A tree
    # (the old strategy's guaranteed output — see its union-find guard) can
    # never contain a closed loop; a ring can. Only engages when the caller
    # supplied projection context; otherwise skip straight to the fallback.
    if part_extent_area > 0.0 and projection_basis is not None:
        ring_u_axis, ring_v_axis = projection_basis
        ring_result = _bridge_via_angular_ring(
            components,
            component_points,
            edges_by_id,
            candidate_by_id,
            G_all=G_all,
            comp_endpoints=comp_endpoints,
            sssp_cache=sssp_cache,
            point_tolerance=point_tolerance,
            u_axis=ring_u_axis,
            v_axis=ring_v_axis,
            part_extent_area=part_extent_area,
        )
        if ring_result is not None:
            return ring_result

    # Union-find to track which components have been merged.
    parent: dict[int, int] = {comp.component_id: comp.component_id for comp in components}

    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    track_coverage = part_extent_area > 0.0 and projection_basis is not None and min_coverage_ratio > 0.0
    u_axis, v_axis = projection_basis if projection_basis is not None else ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    # Per-CURRENT-root edge-id sets, looked up via `_find()` so they are
    # never read through a stale pre-merge id (see `comp_endpoints`'s
    # dual-write pattern above, which this deliberately avoids).
    tree_edge_ids: dict[int, set[int]] = {
        comp.component_id: set(comp.edge_ids) for comp in components
    }

    def _tree_coverage(edge_ids: set[int]) -> float:
        pts: list[Vec3] = []
        for eid in edge_ids:
            edge = edges_by_id.get(eid)
            if edge is None:
                continue
            for p in (edge.start_vertex, edge.end_vertex):
                if p is not None:
                    pts.append(p)
        if len(pts) < 3:
            return 0.0
        us = [dot3(p, u_axis) for p in pts]
        vs = [dot3(p, v_axis) for p in pts]
        return ((max(us) - min(us)) * (max(vs) - min(vs))) / part_extent_area

    best_tree_edge_ids: set[int] | None = None
    best_tree_coverage = -1.0

    # Greedily add cheapest bridges until all reachable components are connected.
    bridge_edge_ids: list[int] = []
    merged_edge_ids: set[int] = set(candidate_edge_ids)
    max_rounds = len(components) - 1
    stopped_early = False
    round_bridge_messages: list[tuple[set[int], str]] = []

    for _ in range(max_rounds):
        best: tuple[float, list[int], int, int] | None = None

        for i, ci in enumerate(components):
            for cj in components[i + 1 :]:
                if _find(ci.component_id) == _find(cj.component_id):
                    continue
                eps_i = comp_endpoints.get(ci.component_id, [])
                eps_j = comp_endpoints.get(cj.component_id, [])
                if not eps_i or not eps_j:
                    continue

                for ep_i in eps_i:
                    dist_from_i, paths_from_i = sssp_cache.get(ep_i, ({}, {}))
                    if not dist_from_i:
                        continue
                    for ep_j in eps_j:
                        if ep_i == ep_j:
                            continue
                        path_cost = dist_from_i.get(ep_j)
                        if path_cost is None:
                            continue
                        if best is None or path_cost < best[0]:
                            path = paths_from_i[ep_j]
                            bridge_eids = [
                                G_all[path[k]][path[k + 1]]["edge_id"]  # type: ignore[index]
                                for k in range(len(path) - 1)
                            ]
                            best = (path_cost, bridge_eids, ci.component_id, cj.component_id)

        if best is None:
            break

        _, bridge_eids, ci_id, cj_id = best
        new_bridge_eids = [e for e in bridge_eids if e not in candidate_edge_ids]
        bridge_edge_ids.extend(new_bridge_eids)
        merged_edge_ids.update(bridge_eids)

        # Merge the two components' endpoint sets under one root.
        root_before_i = _find(ci_id)
        root_before_j = _find(cj_id)
        parent[root_before_i] = root_before_j
        root = _find(cj_id)
        merged_eps = list(set(
            comp_endpoints.get(ci_id, []) + comp_endpoints.get(cj_id, [])
        ))
        comp_endpoints[root] = merged_eps
        # Also update the ci_id key so future lookups find the same set.
        comp_endpoints[ci_id] = merged_eps

        round_bridge_messages.append((
            set(new_bridge_eids),
            f"Bridge: connected component {ci_id} → {cj_id} via "
            f"{len(new_bridge_eids)} bridge edge(s) (path cost {best[0]:.3f} mm).",
        ))

        if track_coverage:
            merged_tree_edges = (
                tree_edge_ids.get(root_before_i, set())
                | tree_edge_ids.get(root_before_j, set())
                | set(new_bridge_eids)
            )
            tree_edge_ids[root] = merged_tree_edges
            coverage = _tree_coverage(merged_tree_edges)
            if coverage > best_tree_coverage:
                best_tree_coverage = coverage
                best_tree_edge_ids = set(merged_tree_edges)
            if coverage >= min_coverage_ratio:
                warnings.append(
                    f"Bridging stopped early: the growing loop reached "
                    f"{coverage * 100:.1f}% of the part's projected extent, "
                    "which is enough to be the main parting line. Remaining "
                    "disconnected components were left unmerged as probable "
                    "local features rather than folded indiscriminately "
                    "into one blob."
                )
                stopped_early = True
                break

    if not bridge_edge_ids:
        return components, component_points, warnings

    # Assemble the merged component. If coverage tracking picked a specific
    # (possibly partial) tree, use exactly that edge set — never the
    # everything-merged fallback — so unrelated local features stay separate.
    all_edge_ids = sorted(best_tree_edge_ids) if track_coverage and best_tree_edge_ids else sorted(merged_edge_ids)
    total_length = sum(
        edges_by_id[eid].length for eid in all_edge_ids if eid in edges_by_id
    )
    all_pts: dict[tuple[int, int, int], Vec3] = {}
    for eid in all_edge_ids:
        edge = edges_by_id.get(eid)
        if edge is None:
            continue
        for pt in (edge.start_vertex, edge.end_vertex):
            if pt is not None:
                all_pts.setdefault(_point_key(pt, point_tolerance), pt)

    kind_counts: dict[str, int] = {}
    for eid in all_edge_ids:
        cand = candidate_by_id.get(eid)
        kind = cand.kind if cand is not None else "bridge"
        kind_counts[kind] = kind_counts.get(kind, 0) + 1

    merged_component = PartingLineComponent(
        component_id=0,
        edge_ids=all_edge_ids,
        total_length_mm=total_length,
        candidate_kinds=kind_counts,
        point_count=len(all_pts),
        noise=_component_noise(kind_counts),
    )
    kept_edge_set = set(all_edge_ids)
    folded_component_count = sum(
        1 for comp in components if set(comp.edge_ids) & kept_edge_set
    )
    final_bridge_edge_count = len(kept_edge_set - candidate_edge_ids)
    left_unmerged = len(components) - folded_component_count
    summary = (
        f"Bridged {folded_component_count} disconnected components into 1 via "
        f"{final_bridge_edge_count} bridge edge(s) following real B-Rep geometry."
    )
    if stopped_early and left_unmerged > 0:
        summary += f" {left_unmerged} component(s) left unmerged (coverage target reached)."
    # Only report the per-round bridge messages that actually contributed to
    # the tree we kept — when coverage tracking discarded other in-progress
    # trees, their bridge messages would otherwise be noise.
    kept_round_messages = [
        message for edge_ids, message in round_bridge_messages
        if not track_coverage or (edge_ids & kept_edge_set)
    ]
    warnings.extend(kept_round_messages)
    warnings.insert(0, summary)
    return [merged_component], {0: list(all_pts.values())}, warnings


def _edge_endpoint_keys(
    edge: EdgeData,
    point_tolerance: float,
) -> tuple[tuple[int, int, int], tuple[int, int, int]] | None:
    if edge.start_vertex is None or edge.end_vertex is None:
        return None
    return (
        _point_key(edge.start_vertex, point_tolerance),
        _point_key(edge.end_vertex, point_tolerance),
    )


def _sample_closed_edge_points(edge: EdgeData, *, sample_count: int = 32) -> list[Vec3]:
    """
    Sample a closed OCC edge when the STEP topology has no distinct endpoints.

    Full circles and periodic B-Rep curves commonly have ``start_vertex`` and
    ``end_vertex`` set to ``None``.  For those edges, endpoint graph ordering is
    impossible, but the edge itself can still be a valid closed parting curve.
    Sampling is intentionally lazy and best-effort so pure tests and non-OCC
    runtimes keep using the warning/fallback path.
    """
    has_same_endpoint = (
        edge.start_vertex is not None
        and edge.end_vertex is not None
        and edge.start_vertex == edge.end_vertex
    )
    if not (edge.is_closed or has_same_endpoint) or edge.occ_edge is None or sample_count < 4:
        return []

    try:
        from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
        from OCC.Core.TopoDS import TopoDS_Edge
    except ImportError:
        return []

    if not isinstance(edge.occ_edge, TopoDS_Edge):
        # BUG G: a mock/invalid object as `occ_edge` (unit tests without
        # real OCC data) must never reach the SWIG-wrapped C++ call below.
        # `BRepAdaptor_Curve(mock)` can hang indefinitely at the native
        # layer — no Python try/except can catch or interrupt a hang inside
        # the C++ side of a SWIG binding. This isinstance check is a normal,
        # fast Python-level check that fails cleanly before ever reaching it.
        return []

    try:
        curve = BRepAdaptor_Curve(edge.occ_edge)
        first = float(curve.FirstParameter())
        last = float(curve.LastParameter())
        if not math.isfinite(first) or not math.isfinite(last) or first == last:
            return []

        point_count = max(4, sample_count)
        points: list[Vec3] = []
        for index in range(point_count):
            t = index / float(point_count)
            parameter = first + (last - first) * t
            point = curve.Value(parameter)
            points.append((float(point.X()), float(point.Y()), float(point.Z())))
        points.append(points[0])
        return points
    except Exception:
        return []


def _wire_quality(
    *,
    ordered_edge_ids: list[int],
    skipped_edge_ids: list[int],
    is_closed: bool,
    branch_point_count: int,
    gap_count: int,
) -> str:
    """
    Bug H-3: `skipped_edge_ids` describes data-quality issues in the SOURCE
    component (edges whose endpoints could not be parsed at all) — it is
    not evidence that THIS wire has a problem. On a large bridged
    super-component (e.g. Part3's 269-edge ring-bridged result), a handful
    of unrelated unparseable edges elsewhere in the component used to force
    "partial" even when the actual selected wire was a verified, genuinely
    closed loop — capping its score at 0.25 regardless of how good the find
    was. `skipped_edge_ids` still degrades the numeric score (see
    `_assess_wire_quality`'s `missing_endpoints` penalty) — it just no
    longer overrides an otherwise-earned "closed_loop"/"open_chain" label.
    `gap_count` is different: it means the walk building THIS wire itself
    had to jump, which is a real property of this wire, not the component.
    """
    if not ordered_edge_ids:
        return "empty"
    if gap_count:
        return "partial"
    if branch_point_count:
        return "branched"
    if is_closed:
        return "closed_loop"
    return "open_chain"


def _part_projected_bbox_area(part: PartGeometry, pull_direction: Vec3) -> float:
    """
    Area of the part's bounding box projected into the pull-normal plane.

    Used as the reference for `silhouette_coverage_ratio`: a main parting line
    should wrap the part's outer silhouette, so its own projected extent
    should be a large fraction of this.
    """
    bbox = part.bounding_box
    if bbox is None:
        return 0.0
    u_axis, v_axis = _projection_basis(pull_direction)
    corners = [
        (x, y, z)
        for x in (bbox.xmin, bbox.xmax)
        for y in (bbox.ymin, bbox.ymax)
        for z in (bbox.zmin, bbox.zmax)
    ]
    us = [dot3(c, u_axis) for c in corners]
    vs = [dot3(c, v_axis) for c in corners]
    return max(0.0, (max(us) - min(us)) * (max(vs) - min(vs)))


def _projection_basis(pull_direction: Vec3) -> tuple[Vec3, Vec3]:
    """
    Build a stable orthonormal 2-D basis perpendicular to the pull direction.

    Nee's projection step reasons about the silhouette in a plane normal to the
    mold opening direction.  The basis choice is arbitrary, but it must be
    deterministic and avoid a reference vector that is parallel to the pull.
    """
    direction = normalize3(pull_direction)
    reference: Vec3 = (0.0, 0.0, 1.0)
    if abs(dot3(direction, reference)) > 0.9:
        reference = (1.0, 0.0, 0.0)
    u_axis = normalize3(cross3(reference, direction))
    v_axis = normalize3(cross3(direction, u_axis))
    return u_axis, v_axis


def _project_points(points: list[Vec3], u_axis: Vec3, v_axis: Vec3) -> list[tuple[float, float]]:
    return [(dot3(point, u_axis), dot3(point, v_axis)) for point in points]


def _polyline_length_2d(points: list[tuple[float, float]]) -> float:
    if len(points) < 2:
        return 0.0
    return sum(
        mag3((b[0] - a[0], b[1] - a[1], 0.0))
        for a, b in zip(points, points[1:])
    )


def _polygon_signed_area(points: list[tuple[float, float]]) -> float:
    if len(points) < 4:
        return 0.0
    area_twice = 0.0
    for a, b in zip(points, points[1:]):
        area_twice += a[0] * b[1] - b[0] * a[1]
    return 0.5 * area_twice


def _bbox_area_2d(points: list[tuple[float, float]]) -> float:
    if not points:
        return 0.0
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return max(0.0, max(xs) - min(xs)) * max(0.0, max(ys) - min(ys))


def _projection_quality(
    *,
    points: list[Vec3],
    is_closed: bool,
    abs_area_mm2: float,
    bbox_area_mm2: float,
) -> str:
    if not points:
        return "empty"
    if is_closed and abs_area_mm2 > 1e-9:
        return "closed_area"
    if is_closed:
        return "closed_degenerate"
    if bbox_area_mm2 > 1e-9:
        return "open_extent"
    return "open_degenerate"


def _wire_projection(
    points: list[Vec3],
    pull_direction: Vec3,
    *,
    is_closed: bool,
) -> PartingLineProjection:
    if not points:
        return PartingLineProjection.empty()

    u_axis, v_axis = _projection_basis(pull_direction)
    projected = _project_points(points, u_axis, v_axis)
    is_projected_closed = (
        is_closed
        and len(projected) > 2
        and mag3((
            projected[0][0] - projected[-1][0],
            projected[0][1] - projected[-1][1],
            0.0,
        )) <= 1e-6
    )
    signed_area = _polygon_signed_area(projected) if is_projected_closed else 0.0
    abs_area = abs(signed_area)
    bbox_area = _bbox_area_2d(projected)
    perimeter = _polyline_length_2d(projected)
    quality = _projection_quality(
        points=points,
        is_closed=is_projected_closed,
        abs_area_mm2=abs_area,
        bbox_area_mm2=bbox_area,
    )
    return PartingLineProjection(
        u_axis=u_axis,
        v_axis=v_axis,
        signed_area_mm2=signed_area,
        abs_area_mm2=abs_area,
        bbox_area_mm2=bbox_area,
        perimeter_mm=perimeter,
        point_count=len(points),
        is_projected_closed=is_projected_closed,
        quality=quality,
    )


def _get_value(obj: object, name: str, default: object = None) -> object:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _as_int_list(value: object) -> list[int]:
    if not isinstance(value, (list, tuple, set)):
        return []
    ids: list[int] = []
    for item in value:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


def _as_vec3(value: object) -> Vec3 | None:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError):
        return None


def _undercut_features_from_context(undercut_context: object | None) -> list[object]:
    if undercut_context is None:
        return []
    if isinstance(undercut_context, (list, tuple)):
        return list(undercut_context)
    raw_features = _get_value(undercut_context, "features", [])
    return list(raw_features) if isinstance(raw_features, (list, tuple)) else []


def _undercut_face_ids_from_context(undercut_context: object | None) -> set[int]:
    if undercut_context is None:
        return set()
    face_ids = set(_as_int_list(_get_value(undercut_context, "undercut_face_ids", [])))
    for feature in _undercut_features_from_context(undercut_context):
        face_ids.update(_as_int_list(_get_value(feature, "face_ids", [])))
        face_ids.update(_as_int_list(_get_value(feature, "boolean_confirmed_face_ids", [])))
        face_ids.update(_as_int_list(_get_value(feature, "boolean_intersection_face_ids", [])))
    return face_ids


def _is_major_undercut_feature(feature: object) -> bool:
    if bool(_get_value(feature, "is_major_feature", False)):
        return True
    severity = str(_get_value(feature, "severity", "") or "").lower()
    action = str(_get_value(feature, "recommended_mold_action", "") or "").lower()
    confidence = str(_get_value(feature, "action_confidence_label", "") or "").lower()
    face_count = len(_as_int_list(_get_value(feature, "face_ids", [])))
    if severity == "critical":
        return True
    return action == "side-action" and confidence in {"high", "medium"} and face_count >= 3


def _major_undercut_face_ids_from_context(undercut_context: object | None) -> set[int]:
    face_ids: set[int] = set()
    for feature in _undercut_features_from_context(undercut_context):
        if not _is_major_undercut_feature(feature):
            continue
        face_ids.update(_as_int_list(_get_value(feature, "face_ids", [])))
        face_ids.update(_as_int_list(_get_value(feature, "boolean_confirmed_face_ids", [])))
        face_ids.update(_as_int_list(_get_value(feature, "boolean_intersection_face_ids", [])))
    return face_ids


def _edge_undercut_conflict_penalty(
    edge: EdgeData,
    *,
    undercut_face_ids: set[int],
    major_undercut_face_ids: set[int],
) -> float:
    adjacent = set(edge.adjacent_face_ids)
    if adjacent & major_undercut_face_ids:
        return 1.15
    if adjacent & undercut_face_ids:
        return 0.65
    return 0.0


def _severity_weight(severity: object) -> float:
    return {
        "critical": 0.62,
        "moderate": 0.38,
        "minor": 0.18,
    }.get(str(severity or "minor").lower(), 0.16)


def _feature_radius_mm(feature: object, part: PartGeometry) -> float:
    area = max(0.0, float(_get_value(feature, "total_area_mm2", 0.0) or 0.0))
    depth = max(0.0, float(_get_value(feature, "depth_proxy_mm", 0.0) or 0.0))
    area_radius = math.sqrt(area / math.pi) * 0.35 if area > 0.0 else 0.0
    return max(
        1.0,
        part.bounding_box.max_dimension * 0.02,
        area_radius,
        depth * 1.75,
    )


def _distance_point_to_segment(point: Vec3, start: Vec3, end: Vec3) -> float:
    ab = (end[0] - start[0], end[1] - start[1], end[2] - start[2])
    ap = (point[0] - start[0], point[1] - start[1], point[2] - start[2])
    denom = dot3(ab, ab)
    if denom <= 1e-12:
        return mag3(ap)
    t = max(0.0, min(1.0, dot3(ap, ab) / denom))
    closest = (
        start[0] + ab[0] * t,
        start[1] + ab[1] * t,
        start[2] + ab[2] * t,
    )
    return mag3((point[0] - closest[0], point[1] - closest[1], point[2] - closest[2]))


def _projected_point_distance(point: Vec3, path_points: list[Vec3], pull_direction: Vec3) -> float:
    if len(path_points) < 2:
        return float("inf")
    u_axis, v_axis = _projection_basis(pull_direction)
    projected_path = [
        (dot3(path_point, u_axis), dot3(path_point, v_axis), 0.0)
        for path_point in path_points
    ]
    projected_point = (dot3(point, u_axis), dot3(point, v_axis), 0.0)
    return min(
        _distance_point_to_segment(projected_point, start, end)
        for start, end in zip(projected_path, projected_path[1:])
    )


def _axis_distance_to_path(point: Vec3, path_points: list[Vec3], pull_direction: Vec3) -> float:
    if not path_points:
        return float("inf")
    point_axis = dot3(point, pull_direction)
    return min(abs(dot3(path_point, pull_direction) - point_axis) for path_point in path_points)


def _conflict_level(score: float) -> str:
    if score >= 0.6:
        return "high"
    if score >= 0.3:
        return "medium"
    if score > 0.0:
        return "low"
    return "none"


def _wire_undercut_conflict(
    wire: PartingLineWire,
    part: PartGeometry,
    edges_by_id: dict[int, EdgeData],
    pull_direction: Vec3,
    undercut_context: object | None,
) -> PartingLineUndercutConflict:
    if undercut_context is None:
        return PartingLineUndercutConflict.not_checked()

    undercut_face_ids = _undercut_face_ids_from_context(undercut_context)
    features = _undercut_features_from_context(undercut_context)
    if not undercut_face_ids and not features:
        return PartingLineUndercutConflict(
            checked=True,
            conflict_score=0.0,
            conflict_level="none",
            method="edge-face-overlap + projected-feature-proximity",
        )

    direct_conflict_faces: set[int] = set()
    direct_conflict_edges: set[int] = set()
    for edge_id in wire.ordered_edge_ids:
        edge = edges_by_id.get(edge_id)
        if edge is None:
            continue
        overlap = set(edge.adjacent_face_ids) & undercut_face_ids
        if overlap:
            direct_conflict_edges.add(edge_id)
            direct_conflict_faces.update(overlap)

    score = min(0.7, 0.18 * len(direct_conflict_edges) + 0.08 * len(direct_conflict_faces))
    conflicting_features: set[int] = set()
    near_feature_conflicts: list[dict] = []
    path_points = wire.points

    for feature in features:
        feature_face_ids = set(_as_int_list(_get_value(feature, "face_ids", [])))
        feature_face_ids.update(_as_int_list(_get_value(feature, "boolean_confirmed_face_ids", [])))
        feature_id = int(_get_value(feature, "feature_id", len(near_feature_conflicts)) or 0)
        location = _as_vec3(_get_value(feature, "location", None))
        if location is None:
            faces = [part.get_face(face_id) for face_id in feature_face_ids]
            valid_faces = [face for face in faces if face is not None]
            if valid_faces:
                n = float(len(valid_faces))
                location = (
                    sum(face.centroid[0] for face in valid_faces) / n,
                    sum(face.centroid[1] for face in valid_faces) / n,
                    sum(face.centroid[2] for face in valid_faces) / n,
                )
        feature_direct = bool(feature_face_ids & direct_conflict_faces)
        if feature_direct:
            conflicting_features.add(feature_id)
            score += _severity_weight(_get_value(feature, "severity", "minor")) * 0.55

        if location is None or len(path_points) < 2:
            continue
        radius = _feature_radius_mm(feature, part)
        projected_distance = _projected_point_distance(location, path_points, pull_direction)
        axial_distance = _axis_distance_to_path(location, path_points, pull_direction)
        depth = max(0.0, float(_get_value(feature, "depth_proxy_mm", 0.0) or 0.0))
        axial_limit = max(radius * 2.0, depth * 3.0, 1.0)
        if projected_distance <= radius and axial_distance <= axial_limit:
            proximity = 1.0 - min(1.0, projected_distance / radius)
            contribution = _severity_weight(_get_value(feature, "severity", "minor")) * (0.25 + 0.75 * proximity)
            score += contribution
            conflicting_features.add(feature_id)
            near_feature_conflicts.append({
                "feature_id": feature_id,
                "severity": str(_get_value(feature, "severity", "unknown")),
                "location": [round(coord, 4) for coord in location],
                "projected_distance_mm": round(projected_distance, 4),
                "axis_distance_mm": round(axial_distance, 4),
                "influence_radius_mm": round(radius, 4),
                "score_contribution": round(contribution, 4),
            })

    score = max(0.0, min(1.0, score))
    return PartingLineUndercutConflict(
        checked=True,
        conflict_score=score,
        conflict_level=_conflict_level(score),
        conflicting_feature_ids=sorted(conflicting_features),
        conflicting_face_ids=sorted(direct_conflict_faces),
        direct_edge_face_conflict_ids=sorted(direct_conflict_edges),
        near_feature_conflicts=near_feature_conflicts,
        method="edge-face-overlap + projected-feature-proximity",
    )


def _quality_level(score: float) -> str:
    if score >= 0.78:
        return "high"
    if score >= 0.52:
        return "medium"
    if score > 0.0:
        return "low"
    return "empty"


def _assess_wire_quality(
    wire: PartingLineWire,
    component: PartingLineComponent | None,
    conflict: PartingLineUndercutConflict,
) -> PartingLineQualityAssessment:
    if not wire.ordered_edge_ids:
        return PartingLineQualityAssessment.empty()

    score = {
        "closed_loop": 0.86,
        "open_chain": 0.60,
        "branched": 0.38,
        "partial": 0.25,
        "empty": 0.0,
    }.get(wire.quality, 0.25)
    factors = [f"wire quality is {wire.quality}"]
    penalties: dict[str, float] = {}

    projection_bonus = {
        "closed_area": 0.10,
        "closed_degenerate": -0.08,
        "open_extent": 0.04,
        "open_degenerate": -0.10,
        "empty": -0.20,
    }.get(wire.projection.quality, 0.0)
    score += projection_bonus
    factors.append(f"projection quality is {wire.projection.quality}")

    if wire.branch_point_count:
        penalties["branches"] = min(0.25, 0.08 * wire.branch_point_count)
    if wire.gap_count:
        penalties["gaps"] = min(0.30, 0.12 * wire.gap_count)
    if wire.skipped_edge_ids:
        penalties["missing_endpoints"] = min(0.22, 0.04 * len(wire.skipped_edge_ids))
    if component is not None:
        non_manifold_count = component.candidate_kinds.get("non_manifold", 0)
        boundary_count = component.candidate_kinds.get("boundary", 0)
        if component.noise.score:
            penalties["candidate_noise"] = min(0.34, 0.34 * component.noise.score)
            factors.append(f"candidate noise is {component.noise.level}")
        if non_manifold_count:
            penalties["non_manifold_edges"] = min(0.20, 0.06 * non_manifold_count)
        if boundary_count and not component.candidate_kinds.get("silhouette", 0):
            penalties["boundary_only_component"] = min(0.18, 0.04 * boundary_count)

    if conflict.checked and conflict.conflict_score:
        penalties["undercut_conflict"] = 0.42 * conflict.conflict_score
        factors.append(f"undercut conflict is {conflict.conflict_level}")
    elif conflict.checked:
        factors.append("no undercut conflict detected")
    else:
        factors.append("undercut conflict not checked")

    score -= sum(penalties.values())
    score = max(0.0, min(1.0, score))
    return PartingLineQualityAssessment(
        score=score,
        level=_quality_level(score),
        factors=factors,
        penalties=penalties,
    )


def _apply_wire_assessments(
    wires: list[PartingLineWire],
    components: list[PartingLineComponent],
    part: PartGeometry,
    edges_by_id: dict[int, EdgeData],
    pull_direction: Vec3,
    undercut_context: object | None,
) -> list[PartingLineWire]:
    component_by_id = {component.component_id: component for component in components}
    assessed: list[PartingLineWire] = []
    for wire in wires:
        component = component_by_id.get(wire.component_id) if wire.component_id is not None else None
        conflict = _wire_undercut_conflict(
            wire,
            part,
            edges_by_id,
            pull_direction,
            undercut_context,
        )
        quality = _assess_wire_quality(wire, component, conflict)
        assessed.append(replace(
            wire,
            undercut_conflict=conflict,
            quality_assessment=quality,
            selection_score=quality.score,
        ))
    return assessed


def _build_ordered_wire(
    component: PartingLineComponent | None,
    edges_by_id: dict[int, EdgeData],
    candidate_by_id: dict[int, PartingLineEdgeCandidate],
    *,
    point_tolerance: float,
    pull_direction: Vec3,
) -> PartingLineWire:
    """
    Build a deterministic ordered wire from one connected edge component.

    This is a graph traversal over edge endpoints.  It is intentionally modest:
    it orders simple open chains and closed loops well, reports branches/gaps,
    and skips curves without explicit start/end vertices instead of inventing
    topology.  Hou-style graph optimization will later replace the greedy walk
    for complex branched candidate graphs.
    """
    if component is None:
        return PartingLineWire(
            component_id=None,
            ordered_edge_ids=[],
            points=[],
            is_closed=False,
            branch_point_count=0,
            gap_count=0,
            skipped_edge_ids=[],
            quality="empty",
            projection=PartingLineProjection.empty(),
        )

    endpoint_keys_by_edge: dict[int, tuple[tuple[int, int, int], tuple[int, int, int]]] = {}
    point_to_edges: dict[tuple[int, int, int], set[int]] = {}
    point_coords: dict[tuple[int, int, int], Vec3] = {}
    skipped_edge_ids: list[int] = []
    sampled_closed_wire: PartingLineWire | None = None

    for edge_id in component.edge_ids:
        edge = edges_by_id.get(edge_id)
        if edge is None:
            skipped_edge_ids.append(edge_id)
            continue
        keys = _edge_endpoint_keys(edge, point_tolerance)
        is_single_edge_component = len(component.edge_ids) == 1
        same_endpoint_key = keys is not None and keys[0] == keys[1]
        if is_single_edge_component and (keys is None or same_endpoint_key):
            # The ONLY edge in this component has no distinct start/end (a
            # full closed curve, e.g. a circle) — sampling its own curve
            # geometry is the only way to get a wire out of it at all.
            # `_sample_closed_edge_points` makes real OCC calls, so it must
            # only ever be invoked for this genuine single-edge case — never
            # for an unparseable edge sitting inside a larger multi-edge
            # component (see the plain `keys is None` skip below), where
            # there is no "whole closed wire" to sample into and calling it
            # anyway is both pointless and (on a mocked/invalid OCC object)
            # can hang indefinitely.
            sampled_points = _sample_closed_edge_points(edge)
            if sampled_points:
                sampled_closed_wire = PartingLineWire(
                    component_id=component.component_id,
                    ordered_edge_ids=[edge_id],
                    points=sampled_points,
                    is_closed=True,
                    branch_point_count=0,
                    gap_count=0,
                    skipped_edge_ids=[],
                    quality="closed_loop",
                    projection=_wire_projection(
                        sampled_points,
                        pull_direction,
                        is_closed=True,
                    ),
                )
                continue
            skipped_edge_ids.append(edge_id)
            continue
        if keys is None:
            skipped_edge_ids.append(edge_id)
            continue
        start_key, end_key = keys
        endpoint_keys_by_edge[edge_id] = keys
        point_to_edges.setdefault(start_key, set()).add(edge_id)
        point_to_edges.setdefault(end_key, set()).add(edge_id)
        if edge.start_vertex is not None:
            point_coords.setdefault(start_key, edge.start_vertex)
        if edge.end_vertex is not None:
            point_coords.setdefault(end_key, edge.end_vertex)

    if not endpoint_keys_by_edge:
        if sampled_closed_wire is not None:
            return sampled_closed_wire
        return PartingLineWire(
            component_id=component.component_id,
            ordered_edge_ids=[],
            points=[],
            is_closed=False,
            branch_point_count=0,
            gap_count=0,
            skipped_edge_ids=sorted(skipped_edge_ids),
            quality="empty",
            projection=PartingLineProjection.empty(),
        )

    branch_point_count = sum(1 for edge_ids in point_to_edges.values() if len(edge_ids) > 2)

    def edge_rank(edge_id: int) -> tuple[float, float, int]:
        edge = edges_by_id[edge_id]
        candidate = candidate_by_id.get(edge_id)
        score = candidate.score if candidate is not None else 0.0
        return (score, edge.length, -edge_id)

    def start_rank(point_key: tuple[int, int, int], unused_edges: set[int]) -> tuple[int, float, float, int]:
        connected = point_to_edges.get(point_key, set()) & unused_edges
        if not connected:
            return (0, 0.0, 0.0, 0)
        best_edge = max(connected, key=edge_rank)
        best_score, best_length, best_neg_id = edge_rank(best_edge)
        is_open_endpoint = 1 if len(point_to_edges.get(point_key, set())) == 1 else 0
        return (is_open_endpoint, best_score, best_length, best_neg_id)

    unused = set(endpoint_keys_by_edge)
    ordered_edge_ids: list[int] = []
    ordered_point_keys: list[tuple[int, int, int]] = []
    gap_count = 0
    start_key = max(point_to_edges, key=lambda key: start_rank(key, unused))
    current_key = start_key
    ordered_point_keys.append(current_key)

    while unused:
        available = sorted(
            point_to_edges.get(current_key, set()) & unused,
            key=edge_rank,
            reverse=True,
        )
        if not available:
            remaining_points = {
                key
                for edge_id in unused
                for key in endpoint_keys_by_edge[edge_id]
            }
            if not remaining_points:
                break
            gap_count += 1
            current_key = max(remaining_points, key=lambda key: start_rank(key, unused))
            ordered_point_keys.append(current_key)
            continue

        edge_id = available[0]
        unused.remove(edge_id)
        start_endpoint, end_endpoint = endpoint_keys_by_edge[edge_id]
        next_key = end_endpoint if current_key == start_endpoint else start_endpoint
        ordered_edge_ids.append(edge_id)
        current_key = next_key
        ordered_point_keys.append(current_key)

    is_closed = (
        len(ordered_point_keys) > 2
        and ordered_point_keys[0] == ordered_point_keys[-1]
        and gap_count == 0
        and not unused
    )

    if not is_closed and len(endpoint_keys_by_edge) >= 3:
        # Bug B fix: the greedy walk above never backtracks, so a branch
        # point can strand it without ever finding a closed loop that a
        # smarter search would have found through the same edges (this is
        # exactly what let a bridged 259-edge super-component score 0.00 and
        # get discarded on Part3 — see BUG H-2). Try the shared exact/
        # contracted search as a second pass, purely additive: only replace
        # the greedy result when the search finds a genuine closed loop the
        # greedy walk missed; otherwise keep the greedy result unchanged.
        def _search_edge_weight(edge_id: int) -> tuple[float, float, int]:
            return edge_rank(edge_id)

        def _search_edge_scalar_weight(edge_id: int) -> float:
            score, length, _ = edge_rank(edge_id)
            return max(0.01, score) * max(1e-6, length)

        def _search_point_to_edges_of(key: tuple[int, int, int]) -> set[int]:
            return point_to_edges.get(key, set())

        search_all_nodes = list(point_coords)
        search_open_points = [
            key for key in search_all_nodes if len(point_to_edges.get(key, set())) == 1
        ]
        search_start_points = sorted(
            search_open_points or search_all_nodes,
            key=lambda key: start_rank(key, set(endpoint_keys_by_edge)),
            reverse=True,
        )

        searched_edges, searched_keys, searched_is_closed, _state_count, _strategy, _hit_limit = (
            _best_path_with_contraction_fallback(
                endpoint_keys_by_edge,
                edge_weight=_search_edge_weight,
                edge_scalar_weight=_search_edge_scalar_weight,
                point_to_edges_of=_search_point_to_edges_of,
                start_points=search_start_points,
                all_nodes=search_all_nodes,
            )
        )
        if searched_is_closed and searched_edges:
            ordered_edge_ids = searched_edges
            ordered_point_keys = searched_keys
            is_closed = True
            gap_count = 0
            # Bug H-3: `branch_point_count` computed further below from the
            # WHOLE component's structure describes the messy graph this
            # loop was searched OUT OF, not the loop itself — a search-
            # verified closed simple loop is, by construction, branch-free
            # within its own edges (it never reuses a point except to close
            # back to the start). Recompute scoped to just the selected
            # subset so a clean find isn't penalised for the haystack.
            selected_point_degree: dict[tuple[int, int, int], int] = {}
            for selected_edge_id in searched_edges:
                for endpoint_key in endpoint_keys_by_edge.get(selected_edge_id, ()):
                    selected_point_degree[endpoint_key] = selected_point_degree.get(endpoint_key, 0) + 1
            branch_point_count = sum(1 for degree in selected_point_degree.values() if degree > 2)

    if not is_closed and ordered_edge_ids:
        reversed_edge_ids = list(reversed(ordered_edge_ids))
        if tuple(reversed_edge_ids) < tuple(ordered_edge_ids):
            ordered_edge_ids = reversed_edge_ids
            ordered_point_keys = list(reversed(ordered_point_keys))
    points = [point_coords[key] for key in ordered_point_keys if key in point_coords]
    quality = _wire_quality(
        ordered_edge_ids=ordered_edge_ids,
        skipped_edge_ids=skipped_edge_ids,
        is_closed=is_closed,
        branch_point_count=branch_point_count,
        gap_count=gap_count,
    )

    projection = _wire_projection(
        points,
        pull_direction,
        is_closed=is_closed,
    )

    return PartingLineWire(
        component_id=component.component_id,
        ordered_edge_ids=ordered_edge_ids,
        points=points,
        is_closed=is_closed,
        branch_point_count=branch_point_count,
        gap_count=gap_count,
        skipped_edge_ids=sorted(skipped_edge_ids),
        quality=quality,
        projection=projection,
    )


def _wire_selection_key(
    wire: PartingLineWire,
    component_by_id: dict[int, PartingLineComponent],
) -> tuple[float, ...]:
    component = component_by_id.get(wire.component_id) if wire.component_id is not None else None
    total_length = component.total_length_mm if component is not None else 0.0
    silhouette_count = (
        component.candidate_kinds.get("silhouette", 0)
        if component is not None
        else 0
    )
    quality_rank = {
        "closed_loop": 4.0,
        "open_chain": 2.0,
        "branched": 1.0,
        "partial": 0.0,
        "empty": -1.0,
    }.get(wire.quality, 0.0)
    projection_rank = {
        "closed_area": 4.0,
        "closed_degenerate": 2.0,
        "open_extent": 1.0,
        "open_degenerate": 0.0,
        "empty": -1.0,
    }.get(wire.projection.quality, 0.0)

    # Ordering follows Nee et al. (1998) §5, which selects the parting loop by:
    #   1. largest projected area  ("maximum contour rule")
    #   2. fewest sharp turns / highest flatness
    #   3. avoidance of critical regions
    #
    # Two deliberate adjustments to that order:
    #
    # * `projection_rank` stays first as a VALIDITY GATE, not a preference — a
    #   wire that does not project to a usable contour cannot be a parting
    #   line at any area.
    # * Undercut conflict (criterion 3) is placed ABOVE area, because a loop
    #   that runs through an undercut is not manufacturable however large it
    #   is. This is asserted by
    #   `test_undercut_conflict_penalty_prefers_clean_parting_loop`.
    #
    # Projected area then ranks ABOVE wire quality. It previously sat 5th,
    # behind `quality_assessment.score` and `quality_rank`, which inverted the
    # paper: a small tidy loop outranked the true main silhouette. Measured on
    # the real parts, that picked a loop covering 27.6% of Part1's projected
    # extent and just 1.0% of Part3's (a hole rim, not a parting line), while
    # every reported metric read "ready / high quality". Quality is a
    # tiebreaker between contours of comparable size, not a reason to prefer a
    # small one — a branched-but-dominant contour is handed to the graph
    # refinement stage, which exists precisely to resolve branching.
    return (
        projection_rank,                              # validity gate
        -wire.undercut_conflict.conflict_score,       # Nee 3: avoid critical regions
        wire.projection.abs_area_mm2,                 # Nee 1: MAXIMUM CONTOUR RULE
        wire.quality_assessment.score,                # Nee 2: flatness / cleanliness
        quality_rank,
        wire.projection.bbox_area_mm2,
        float(silhouette_count),
        total_length,
        -float(wire.branch_point_count + wire.gap_count),
        -float(len(wire.skipped_edge_ids)),
    )


def _select_projected_wire(
    wires: list[PartingLineWire],
    components: list[PartingLineComponent],
) -> PartingLineWire:
    if not wires:
        return PartingLineWire(
            component_id=None,
            ordered_edge_ids=[],
            points=[],
            is_closed=False,
            branch_point_count=0,
            gap_count=0,
            skipped_edge_ids=[],
            quality="empty",
            projection=PartingLineProjection.empty(),
        )
    component_by_id = {component.component_id: component for component in components}
    return max(wires, key=lambda wire: _wire_selection_key(wire, component_by_id))


def _lerp3(a: Vec3, b: Vec3, t: float) -> Vec3:
    return (
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
    )


def _polyline_length_3d(points: list[Vec3]) -> float:
    if len(points) < 2:
        return 0.0
    return sum(
        mag3((b[0] - a[0], b[1] - a[1], b[2] - a[2]))
        for a, b in zip(points, points[1:])
    )


def _closure_error_mm(points: list[Vec3], *, is_closed: bool) -> float:
    if not is_closed or len(points) < 2:
        return 0.0
    start = points[0]
    end = points[-1]
    return mag3((end[0] - start[0], end[1] - start[1], end[2] - start[2]))


def _turn_angle_stats(points: list[Vec3], *, is_closed: bool) -> tuple[float, float]:
    if len(points) < 3:
        return 0.0, 0.0

    working = points[:-1] if is_closed and points[0] == points[-1] else list(points)
    if len(working) < 3:
        return 0.0, 0.0

    angles: list[float] = []
    if is_closed:
        index_range = range(len(working))
        for index in index_range:
            prev_point = working[index - 1]
            point = working[index]
            next_point = working[(index + 1) % len(working)]
            before = (
                prev_point[0] - point[0],
                prev_point[1] - point[1],
                prev_point[2] - point[2],
            )
            after = (
                next_point[0] - point[0],
                next_point[1] - point[1],
                next_point[2] - point[2],
            )
            before_len = mag3(before)
            after_len = mag3(after)
            if before_len <= 1e-12 or after_len <= 1e-12:
                continue
            cosine = max(-1.0, min(1.0, dot3(before, after) / (before_len * after_len)))
            angles.append(math.degrees(math.acos(cosine)))
    else:
        for prev_point, point, next_point in zip(working, working[1:], working[2:]):
            before = (
                prev_point[0] - point[0],
                prev_point[1] - point[1],
                prev_point[2] - point[2],
            )
            after = (
                next_point[0] - point[0],
                next_point[1] - point[1],
                next_point[2] - point[2],
            )
            before_len = mag3(before)
            after_len = mag3(after)
            if before_len <= 1e-12 or after_len <= 1e-12:
                continue
            cosine = max(-1.0, min(1.0, dot3(before, after) / (before_len * after_len)))
            angles.append(math.degrees(math.acos(cosine)))

    if not angles:
        return 0.0, 0.0
    return sum(angles) / len(angles), max(angles)


def _sample_on_segments(
    segments: list[tuple[Vec3, Vec3, float]],
    distance_mm: float,
) -> Vec3:
    remaining = max(0.0, distance_mm)
    for start, end, length in segments:
        if length <= 1e-12:
            continue
        if remaining <= length:
            return _lerp3(start, end, remaining / length)
        remaining -= length
    return segments[-1][1] if segments else (0.0, 0.0, 0.0)


def _resample_polyline(
    points: list[Vec3],
    *,
    is_closed: bool,
    target_point_count: int,
) -> list[Vec3]:
    if len(points) < 2 or target_point_count <= len(points):
        return list(points)

    if is_closed:
        cycle = points[:-1] if points[0] == points[-1] else list(points)
        if len(cycle) < 2:
            return list(points)
        segments = [
            (
                start,
                end,
                mag3((end[0] - start[0], end[1] - start[1], end[2] - start[2])),
            )
            for start, end in zip(cycle, cycle[1:] + [cycle[0]])
        ]
        total_length = sum(length for _, _, length in segments)
        if total_length <= 1e-12:
            return list(points)
        unique_target = max(3, target_point_count - 1)
        resampled = [
            _sample_on_segments(segments, total_length * index / unique_target)
            for index in range(unique_target)
        ]
        resampled.append(resampled[0])
        return resampled

    segments = [
        (
            start,
            end,
            mag3((end[0] - start[0], end[1] - start[1], end[2] - start[2])),
        )
        for start, end in zip(points, points[1:])
    ]
    total_length = sum(length for _, _, length in segments)
    if total_length <= 1e-12:
        return list(points)
    target = max(2, target_point_count)
    return [
        _sample_on_segments(segments, total_length * index / (target - 1))
        for index in range(target)
    ]


def _estimated_chaikin_point_count(
    point_count: int,
    *,
    is_closed: bool,
    iterations: int,
) -> int:
    estimated = max(0, point_count)
    for _ in range(max(0, iterations)):
        if estimated < 3:
            break
        estimated = estimated * 2 - (0 if is_closed else 2)
    return estimated


def _parting_display_metrics(
    *,
    raw_points: list[Vec3],
    resampled_points: list[Vec3],
    refined_points: list[Vec3],
    is_closed: bool,
    requested_smoothing_iterations: int,
    applied_smoothing_iterations: int,
    max_refined_display_points: int,
) -> dict[str, float | int]:
    raw_length = _polyline_length_3d(raw_points)
    resampled_length = _polyline_length_3d(resampled_points)
    refined_length = _polyline_length_3d(refined_points)
    raw_mean_turn, raw_max_turn = _turn_angle_stats(raw_points, is_closed=is_closed)
    refined_mean_turn, refined_max_turn = _turn_angle_stats(refined_points, is_closed=is_closed)
    length_change_pct = (
        100.0 * (refined_length - raw_length) / raw_length
        if raw_length > 1e-12
        else 0.0
    )
    max_turn_reduction_pct = (
        100.0 * (raw_max_turn - refined_max_turn) / raw_max_turn
        if raw_max_turn > 1e-12
        else 0.0
    )
    return {
        "raw_point_count": len(raw_points),
        "resampled_point_count": len(resampled_points),
        "refined_point_count": len(refined_points),
        "raw_length_mm": raw_length,
        "resampled_length_mm": resampled_length,
        "refined_length_mm": refined_length,
        "length_change_pct": length_change_pct,
        "closure_error_mm": _closure_error_mm(refined_points, is_closed=is_closed),
        "raw_mean_turn_angle_deg": raw_mean_turn,
        "refined_mean_turn_angle_deg": refined_mean_turn,
        "raw_max_turn_angle_deg": raw_max_turn,
        "refined_max_turn_angle_deg": refined_max_turn,
        "max_turn_reduction_pct": max_turn_reduction_pct,
        "requested_smoothing_iterations": requested_smoothing_iterations,
        "applied_smoothing_iterations": applied_smoothing_iterations,
        "max_refined_display_points": max_refined_display_points,
    }


def _chaikin_smooth(points: list[Vec3], *, is_closed: bool, iterations: int) -> list[Vec3]:
    """
    Smooth display polyline using Chaikin corner cutting.

    This is only a visualization/refinement aid.  It does not alter the exact
    selected B-Rep edge IDs and should not be interpreted as a CAD edit.
    """
    if iterations <= 0 or len(points) < 3:
        return list(points)

    smoothed = list(points)
    for _ in range(iterations):
        if len(smoothed) < 3:
            break

        if is_closed:
            cycle = smoothed[:-1] if smoothed[0] == smoothed[-1] else smoothed
            if len(cycle) < 3:
                break
            next_points: list[Vec3] = []
            for index, point in enumerate(cycle):
                next_point = cycle[(index + 1) % len(cycle)]
                next_points.append(_lerp3(point, next_point, 0.25))
                next_points.append(_lerp3(point, next_point, 0.75))
            next_points.append(next_points[0])
            smoothed = next_points
        else:
            next_points = [smoothed[0]]
            for point, next_point in zip(smoothed, smoothed[1:]):
                next_points.append(_lerp3(point, next_point, 0.25))
                next_points.append(_lerp3(point, next_point, 0.75))
            next_points.append(smoothed[-1])
            smoothed = next_points

    return smoothed


def _search_best_closed_or_open_path(
    endpoint_keys_by_edge: dict[int, tuple[tuple[int, int, int], tuple[int, int, int]]],
    *,
    edge_weight: Callable[[int], tuple[float, float, int]],
    edge_scalar_weight: Callable[[int], float],
    point_to_edges_of: Callable[[tuple[int, int, int]], set[int]],
    start_points: list[tuple[int, int, int]],
    search_edge_limit: int,
    max_search_states: int,
    min_closing_edges: int = 3,
) -> tuple[list[int], list[tuple[int, int, int]], bool, int]:
    """
    Exhaustive-but-bounded search for the best weighted closed (preferred) or
    open trail through a graph of "edges" identified by integer id.

    `min_closing_edges` is the fewest edges a path may use before it is
    allowed to count as closed (default 3, matching the original raw B-Rep
    edge search — a valid geometric loop needs at least a triangle). Callers
    searching a contracted hyper-edge graph pass 1, since a single hyper-edge
    can already represent a legitimate large ring of many raw edges.

    This is the exact search body Milestone 1.6 always claimed to have
    replaced with a real graph algorithm — extracted so it can run over
    either raw B-Rep edges (small components) or a topologically contracted
    graph (Bug B fix, see `_contract_degree2_chains`) without duplicating the
    DFS/record-path logic for each.

    Returns (best_path_edges, best_path_keys, best_is_closed, state_count).
    Empty `best_path_edges` means the search found nothing (caller decides
    the fallback).
    """
    best_path_edges: list[int] = []
    best_path_keys: list[tuple[int, int, int]] = []
    best_is_closed = False
    best_key: tuple[float, int, int, int, int] | None = None
    state_count = 0

    if len(endpoint_keys_by_edge) > search_edge_limit or not endpoint_keys_by_edge:
        return best_path_edges, best_path_keys, best_is_closed, state_count

    def record_path(
        path_edges: list[int],
        path_keys: list[tuple[int, int, int]],
        total_weight: float,
        is_closed: bool,
    ) -> None:
        nonlocal best_path_edges, best_path_keys, best_is_closed, best_key
        if not path_edges:
            return
        candidate_key = (
            round(total_weight, 9),
            len(path_edges),
            1 if is_closed else 0,
            -sum(path_edges),
            -path_edges[0],
        )
        if best_key is None or candidate_key > best_key:
            best_key = candidate_key
            best_path_edges = list(path_edges)
            best_path_keys = list(path_keys)
            best_is_closed = is_closed

    def dfs(
        *,
        start_key: tuple[int, int, int],
        current_key: tuple[int, int, int],
        used_edges: set[int],
        path_edges: list[int],
        path_keys: list[tuple[int, int, int]],
        total_weight: float,
    ) -> None:
        nonlocal state_count
        state_count += 1
        if state_count > max_search_states:
            return

        if path_edges:
            record_path(
                path_edges,
                path_keys,
                total_weight,
                is_closed=len(path_keys) > min_closing_edges - 1 and path_keys[-1] == start_key,
            )

        available = sorted(
            [
                edge_id
                for edge_id in point_to_edges_of(current_key)
                if edge_id not in used_edges
            ],
            key=edge_weight,
            reverse=True,
        )
        for edge_id in available:
            start_endpoint, end_endpoint = endpoint_keys_by_edge[edge_id]
            next_key = end_endpoint if current_key == start_endpoint else start_endpoint
            next_edges = path_edges + [edge_id]
            next_keys = path_keys + [next_key]
            next_weight = total_weight + edge_scalar_weight(edge_id)
            closes_loop = next_key == start_key and len(next_edges) >= min_closing_edges
            record_path(next_edges, next_keys, next_weight, is_closed=closes_loop)
            if closes_loop:
                continue
            dfs(
                start_key=start_key,
                current_key=next_key,
                used_edges=used_edges | {edge_id},
                path_edges=next_edges,
                path_keys=next_keys,
                total_weight=next_weight,
            )

    for start_key in start_points:
        if state_count > max_search_states:
            break
        dfs(
            start_key=start_key,
            current_key=start_key,
            used_edges=set(),
            path_edges=[],
            path_keys=[start_key],
            total_weight=0.0,
        )

    return best_path_edges, best_path_keys, best_is_closed, state_count


def _contract_degree2_chains(
    endpoint_keys_by_edge: dict[int, tuple[tuple[int, int, int], tuple[int, int, int]]],
    point_to_edges_of: Callable[[tuple[int, int, int]], set[int]],
    all_nodes: list[tuple[int, int, int]],
) -> list[dict]:
    """
    Bug B fix: collapse maximal chains of degree-2 nodes into single
    "hyper-edges" so the best-loop search scales with the number of real
    branch points, not the number of raw B-Rep edges.

    A candidate-edge graph traced from real geometry is mostly a simple
    curve with occasional branches — measured on Part3's 254-edge merged
    bridging result, only 36 of 236 nodes were actual junctions (degree != 2);
    the other 200 were plain interior points of a chain with no real choice
    to make.  The exhaustive search only needs to reason about the 36
    junctions, not the 254 edges between them.

    Self-loop hyper-edges (a chain that leaves and returns to the SAME
    junction without touching any other junction) are kept, not dropped.
    They look like dead-end spurs (a small hole rim hanging off one point of
    the main silhouette) but are NOT always that: a genuine closed loop can
    attach to the rest of the graph at only a single junction, in which case
    it self-loops there by construction — dropping it would silently discard
    the answer. Measured directly: on a real ring-bridged Part3 component,
    `nx.find_cycle` found a genuine 15-edge cycle that an earlier version of
    this function (which dropped self-loops) caused the exact search to miss
    entirely, despite running to full completion. Keeping every hyper-edge
    guarantees the search sees the complete graph topology; avoiding
    detours into genuinely irrelevant small features is handled upstream
    (per-component filtering in `_bridge_via_angular_ring`) and by the
    search's own preference for higher-scoring paths, not by removing edges
    before the search can even see them.

    Returns a list of dicts: {a, b, edge_chain (raw edge ids, a->b order),
    point_chain (raw point keys, a->b order, inclusive)}.
    """
    degrees = {node: len(point_to_edges_of(node)) for node in all_nodes}
    junctions = {node for node, degree in degrees.items() if degree != 2}

    hyper_edges: list[dict] = []
    visited_edges: set[int] = set()

    def walk_chain(start_node: tuple[int, int, int], first_edge_id: int) -> dict:
        chain_edges = [first_edge_id]
        visited_edges.add(first_edge_id)
        s_key, e_key = endpoint_keys_by_edge[first_edge_id]
        current_node = e_key if s_key == start_node else s_key
        point_chain = [start_node, current_node]
        previous_edge_id = first_edge_id
        max_chain_length = len(endpoint_keys_by_edge) + 1
        # Stop at a real junction OR back at our own anchor — the latter is
        # required when `junctions` is empty (the whole component is one
        # simple ring with no branch points at all): `current_node not in
        # junctions` would otherwise never become false and this would loop
        # forever re-walking the same ring. `max_chain_length` is a hard
        # backstop against any other unforeseen non-termination.
        while current_node not in junctions and current_node != start_node:
            if len(chain_edges) > max_chain_length:
                break
            next_candidates = point_to_edges_of(current_node) - {previous_edge_id}
            if not next_candidates:
                break  # dead end inside what should be a degree-2 run (defensive)
            next_edge_id = next(iter(next_candidates))
            if next_edge_id in visited_edges:
                break  # defensive: would otherwise re-walk an already-used edge
            visited_edges.add(next_edge_id)
            chain_edges.append(next_edge_id)
            ns_key, ne_key = endpoint_keys_by_edge[next_edge_id]
            current_node = ne_key if ns_key == current_node else ns_key
            point_chain.append(current_node)
            previous_edge_id = next_edge_id
        return {"a": start_node, "b": current_node, "edge_chain": chain_edges, "point_chain": point_chain}

    for start_node in sorted(junctions):
        for first_edge_id in sorted(point_to_edges_of(start_node)):
            if first_edge_id in visited_edges:
                continue
            hyper_edges.append(walk_chain(start_node, first_edge_id))

    # Leftover edges belong to junction-free simple loops entirely detached
    # from every junction found above (only possible if the WHOLE component
    # has no junctions at all — handled by the caller before this runs — or
    # a disjoint sub-loop slipped through; anchor arbitrarily and include it).
    remaining_starts = {
        endpoint_keys_by_edge[eid][0]
        for eid in endpoint_keys_by_edge
        if eid not in visited_edges
    }
    for start_node in sorted(remaining_starts):
        for first_edge_id in sorted(point_to_edges_of(start_node)):
            if first_edge_id in visited_edges:
                continue
            hyper_edges.append(walk_chain(start_node, first_edge_id))

    return hyper_edges


def _find_any_cycle_via_networkx(
    endpoint_keys_by_edge: dict[int, tuple[tuple[int, int, int], tuple[int, int, int]]],
    edge_scalar_weight: Callable[[int], float] | None = None,
) -> tuple[list[int], list[tuple[int, int, int]]] | None:
    """
    Last-resort guarantee: the exhaustive best-weighted-path search solves a
    near-NP-hard problem (optimal weighted closed trail) and can exhaust its
    state budget on a large graph without ever resolving whether a closed
    loop exists at all. `nx.find_cycle`/`nx.cycle_basis` answer that in
    polynomial time. Measured directly on a real ring-bridged Part3
    component: the exhaustive search hit its 3,000,000-state budget
    inconclusively while these found genuine cycles in under a second.

    `nx.find_cycle` alone returns whichever cycle its internal DFS happens
    to stumble on first — on Part3 that was a real but small 15-of-269-edge
    cycle, too small to beat the alternative it was being compared against.
    When `edge_scalar_weight` is supplied, this instead scores every cycle
    in `nx.cycle_basis` (a polynomial-time, near-instant enumeration of
    independent cycles — not exhaustive of every possible cycle, but a much
    richer candidate set than "the first one found") and returns the
    highest-scoring one. Falls back to plain `nx.find_cycle` if the basis is
    empty or no weight function is given.

    Still not guaranteed optimal — just a much better-than-arbitrary correct
    answer, fast. Whether it's actually USED is still gated by the caller's
    normal accept/reject comparison against the alternative (e.g. the
    un-bridged selection), so this can only ever improve outcomes, never
    force a worse result to be accepted. Returns None if networkx is
    unavailable or no cycle exists.
    """
    if not _NX_AVAILABLE or not endpoint_keys_by_edge:
        return None

    pair_to_edges: dict[frozenset, list[int]] = {}
    for eid, (sk, ek) in endpoint_keys_by_edge.items():
        pair_to_edges.setdefault(frozenset((sk, ek)), []).append(eid)

    def reconstruct(node_cycle: list[tuple[int, int, int]]) -> tuple[list[int], list[tuple[int, int, int]]] | None:
        if len(node_cycle) < 3:
            return None
        closed_nodes = list(node_cycle) + [node_cycle[0]]
        remaining = {pair: list(eids) for pair, eids in pair_to_edges.items()}
        path_edges: list[int] = []
        path_keys: list[tuple[int, int, int]] = [closed_nodes[0]]
        for u, v in zip(closed_nodes, closed_nodes[1:]):
            available = remaining.get(frozenset((u, v)))
            if not available:
                return None
            path_edges.append(available.pop())
            path_keys.append(v)
        return path_edges, path_keys

    if edge_scalar_weight is not None:
        try:
            G_simple: object = nx.Graph()  # type: ignore[union-attr]
            for sk, ek in endpoint_keys_by_edge.values():
                if sk != ek:
                    G_simple.add_edge(sk, ek)  # type: ignore[union-attr]
            basis = nx.cycle_basis(G_simple)  # type: ignore[union-attr]
        except nx.exception.NetworkXError:  # type: ignore[union-attr]
            basis = []
        best: tuple[list[int], list[tuple[int, int, int]]] | None = None
        best_score = float("-inf")
        for node_cycle in basis:
            candidate = reconstruct(node_cycle)
            if candidate is None:
                continue
            score = sum(edge_scalar_weight(e) for e in candidate[0])
            if score > best_score:
                best_score = score
                best = candidate
        if best is not None:
            return best

    G_cycle: object = nx.MultiGraph()  # type: ignore[union-attr]
    for eid, (sk, ek) in endpoint_keys_by_edge.items():
        G_cycle.add_edge(sk, ek, key=eid)  # type: ignore[union-attr]
    try:
        cycle = nx.find_cycle(G_cycle, orientation="ignore")  # type: ignore[union-attr]
    except (nx.NetworkXNoCycle, nx.exception.NetworkXError):  # type: ignore[union-attr]
        return None
    if not cycle:
        return None

    used: set[int] = set()
    path_edges: list[int] = []
    path_keys: list[tuple[int, int, int]] = [cycle[0][0]]
    for entry in cycle:
        u, v = entry[0], entry[1]
        eid = entry[2] if len(entry) >= 3 and entry[2] in endpoint_keys_by_edge else None
        if eid is None or eid in used:
            eid = None
            for candidate_eid, (sk, ek) in endpoint_keys_by_edge.items():
                if candidate_eid in used:
                    continue
                if {sk, ek} == {u, v}:
                    eid = candidate_eid
                    break
        if eid is None:
            return None  # could not reconstruct a valid edge sequence; bail out safely
        used.add(eid)
        path_edges.append(eid)
        path_keys.append(v)
    return path_edges, path_keys


def _best_path_with_contraction_fallback(
    endpoint_keys_by_edge: dict[int, tuple[tuple[int, int, int], tuple[int, int, int]]],
    *,
    edge_weight: Callable[[int], tuple[float, float, int]],
    edge_scalar_weight: Callable[[int], float],
    point_to_edges_of: Callable[[tuple[int, int, int]], set[int]],
    start_points: list[tuple[int, int, int]],
    all_nodes: list[tuple[int, int, int]],
    search_edge_limit: int = 22,
    contracted_search_edge_limit: int = 90,
    max_search_states: int = 75_000,
    contracted_max_search_states: int = 3_000_000,
) -> tuple[list[int], list[tuple[int, int, int]], bool, int, str, bool]:
    """
    Bug B fix, shared dispatcher: exact search on the raw graph when it is
    small; otherwise contract degree-2 chains into hyper-edges (see
    `_contract_degree2_chains`) and run the exact search on that instead —
    the search space scales with the number of real branch points, not raw
    edge count. Falls back to an empty result (caller decides what to do,
    typically a plain greedy walk) only when neither is feasible.

    Used by both `_trace_best_weighted_path` (refinement of an already
    selected wire) and `_build_ordered_wire` (initial per-component
    ordering, including bridged super-components) — the two previously had
    separate, inconsistent search sophistication; this is the one exact/
    contracted search both now share.

    `contracted_max_search_states` is deliberately much larger than
    `max_search_states`: the contracted graph is already far smaller (tens of
    hyper-edges, not hundreds of raw edges), so a much bigger state budget is
    affordable there. Measured need: Part3's real 259-edge bridged
    super-component contracts to 50 hyper-edges, and the default 75,000-state
    budget (calibrated for the raw graph) was exhausted mid-search without
    finding a closed loop that a larger budget does find.

    Whenever a search (raw or contracted) fails to produce a closed result —
    empty, or open only — this falls through to
    `_find_any_cycle_via_networkx` before giving up: finding the OPTIMAL
    weighted closed trail is near-NP-hard and can exhaust any finite state
    budget on a large enough graph, but finding SOME cycle is polynomial.
    Guaranteed correct if used; whether it's actually accepted is still up
    to the caller's normal comparison against the alternative.

    Returns (best_path_edges, best_path_keys, best_is_closed, state_count,
    strategy, hit_state_limit) — `hit_state_limit` is measured against
    whichever budget actually applied (`max_search_states` for the raw
    search, `contracted_max_search_states` for the hyper-edge search), so
    callers never need to guess which constant to compare against.
    """
    if len(endpoint_keys_by_edge) <= search_edge_limit:
        edges, keys, closed, state_count = _search_best_closed_or_open_path(
            endpoint_keys_by_edge,
            edge_weight=edge_weight,
            edge_scalar_weight=edge_scalar_weight,
            point_to_edges_of=point_to_edges_of,
            start_points=start_points,
            search_edge_limit=search_edge_limit,
            max_search_states=max_search_states,
        )
        if not closed:
            fallback = _find_any_cycle_via_networkx(endpoint_keys_by_edge, edge_scalar_weight)
            if fallback is not None:
                return (
                    fallback[0], fallback[1], True, state_count,
                    "networkx-cycle-fallback", state_count > max_search_states,
                )
        return edges, keys, closed, state_count, "bounded-dfs", state_count > max_search_states

    hyper_edges = _contract_degree2_chains(endpoint_keys_by_edge, point_to_edges_of, all_nodes)
    if not hyper_edges or len(hyper_edges) > contracted_search_edge_limit:
        return [], [], False, 0, "greedy-fallback", False

    hyper_by_id = dict(enumerate(hyper_edges))
    hyper_endpoint_keys = {hid: (h["a"], h["b"]) for hid, h in hyper_by_id.items()}
    hyper_scalar_weight_cache = {
        hid: sum(edge_scalar_weight(e) for e in h["edge_chain"]) for hid, h in hyper_by_id.items()
    }
    hyper_priority_cache = {
        hid: (
            sum(edge_weight(e)[0] for e in h["edge_chain"]) / len(h["edge_chain"]),
            sum(edge_weight(e)[1] for e in h["edge_chain"]),
            -min(h["edge_chain"]),
        )
        for hid, h in hyper_by_id.items()
    }
    hyper_adjacency: dict[tuple[int, int, int], set[int]] = {}
    for hid, h in hyper_by_id.items():
        hyper_adjacency.setdefault(h["a"], set()).add(hid)
        hyper_adjacency.setdefault(h["b"], set()).add(hid)

    def hyper_edge_weight(hid: int) -> tuple[float, float, int]:
        return hyper_priority_cache[hid]

    def hyper_edge_scalar_weight(hid: int) -> float:
        return hyper_scalar_weight_cache[hid]

    def hyper_point_to_edges_of(node: tuple[int, int, int]) -> set[int]:
        return hyper_adjacency.get(node, set())

    hyper_nodes = list(hyper_adjacency)
    hyper_open_points = [n for n in hyper_nodes if len(hyper_adjacency[n]) == 1]
    hyper_start_points = sorted(
        hyper_open_points or hyper_nodes,
        key=lambda n: (
            1 if len(hyper_adjacency.get(n, set())) == 1 else 0,
            max((hyper_edge_weight(h) for h in hyper_adjacency.get(n, set())), default=(0.0, 0.0, 0)),
        ),
        reverse=True,
    )

    hyper_path, hyper_path_keys, hyper_is_closed, state_count = _search_best_closed_or_open_path(
        hyper_endpoint_keys,
        edge_weight=hyper_edge_weight,
        edge_scalar_weight=hyper_edge_scalar_weight,
        point_to_edges_of=hyper_point_to_edges_of,
        start_points=hyper_start_points,
        search_edge_limit=contracted_search_edge_limit,
        max_search_states=contracted_max_search_states,
        min_closing_edges=1,
    )
    if not hyper_path or not hyper_is_closed:
        fallback = _find_any_cycle_via_networkx(endpoint_keys_by_edge, edge_scalar_weight)
        if fallback is not None:
            return (
                fallback[0], fallback[1], True, state_count,
                "networkx-cycle-fallback", state_count > contracted_max_search_states,
            )
    if not hyper_path:
        return [], [], False, state_count, "greedy-fallback", state_count > contracted_max_search_states

    # Expand the winning hyper-edge sequence back into raw edges and the
    # full-fidelity point chain — never collapse a long chain's interior
    # polyline down to just its junction points.
    expanded_edges: list[int] = []
    expanded_keys: list[tuple[int, int, int]] = [hyper_path_keys[0]]
    cursor = hyper_path_keys[0]
    for hid in hyper_path:
        h = hyper_by_id[hid]
        forward = h["a"] == cursor
        chain_edges = h["edge_chain"] if forward else list(reversed(h["edge_chain"]))
        chain_points = h["point_chain"] if forward else list(reversed(h["point_chain"]))
        expanded_edges.extend(chain_edges)
        expanded_keys.extend(chain_points[1:])
        cursor = chain_points[-1]
    return (
        expanded_edges,
        expanded_keys,
        hyper_is_closed,
        state_count,
        "contracted-graph-search",
        state_count > contracted_max_search_states,
    )


def _trace_best_weighted_path(
    component: PartingLineComponent,
    edges_by_id: dict[int, EdgeData],
    candidate_by_id: dict[int, PartingLineEdgeCandidate],
    *,
    point_tolerance: float,
    undercut_face_ids: set[int] | None = None,
    major_undercut_face_ids: set[int] | None = None,
) -> tuple[list[int], list[Vec3], bool, list[int], list[str], PartingLineGraphCleanup]:
    """
    Extract one high-confidence path from a possibly branched component.

    Hou-style methods treat candidate parting edges as a graph and optimize a
    curve through that graph.  This scoped implementation keeps the highest
    weighted connected trace and reports discarded branches instead of trying
    to solve a global ambiguous graph in one step.
    """
    endpoint_keys_by_edge: dict[int, tuple[tuple[int, int, int], tuple[int, int, int]]] = {}
    point_coords: dict[tuple[int, int, int], Vec3] = {}
    warnings: list[str] = []
    undercut_ids = set(undercut_face_ids or set())
    major_undercut_ids = set(major_undercut_face_ids or set())

    for edge_id in component.edge_ids:
        edge = edges_by_id.get(edge_id)
        if edge is None:
            continue
        keys = _edge_endpoint_keys(edge, point_tolerance)
        if keys is None:
            continue
        start_key, end_key = keys
        endpoint_keys_by_edge[edge_id] = keys
        if edge.start_vertex is not None:
            point_coords.setdefault(start_key, edge.start_vertex)
        if edge.end_vertex is not None:
            point_coords.setdefault(end_key, edge.end_vertex)

    # --- networkx graph (F4 resolution) -----------------------------------
    # Build a MultiGraph over quantized vertex keys so networkx provides the
    # adjacency structure instead of a hand-rolled dict.  We keep a lightweight
    # dict fallback for environments where networkx is unavailable, though the
    # dependency is pinned in requirements.txt (networkx==3.3).
    if _NX_AVAILABLE and endpoint_keys_by_edge:
        _G: object = nx.MultiGraph()
        for _eid, (_sk, _ek) in endpoint_keys_by_edge.items():
            _G.add_edge(_sk, _ek, key=_eid, edge_id=_eid)  # type: ignore[union-attr]

        def _neighbors_of(key: tuple[int, int, int]) -> set[int]:
            return {d["edge_id"] for _, _, d in _G.edges(key, data=True)}  # type: ignore[union-attr]

        def _branch_point_count() -> int:
            return sum(1 for n in _G.nodes() if _G.degree(n) > 2)  # type: ignore[union-attr]

    else:
        # Fallback: plain adjacency dict (networkx not installed).
        _pt2e: dict[tuple[int, int, int], set[int]] = {}
        for _eid, (_sk, _ek) in endpoint_keys_by_edge.items():
            _pt2e.setdefault(_sk, set()).add(_eid)
            _pt2e.setdefault(_ek, set()).add(_eid)

        def _neighbors_of(key: tuple[int, int, int]) -> set[int]:  # type: ignore[misc]
            return _pt2e.get(key, set())

        def _branch_point_count() -> int:  # type: ignore[misc]
            return sum(1 for edge_ids in _pt2e.values() if len(edge_ids) > 2)

    # Compatibility alias so the DFS body reads clearly.
    point_to_edges_of = _neighbors_of

    if not endpoint_keys_by_edge:
        warnings.append("No endpoint graph was available for refinement.")
        return (
            [],
            [],
            False,
            list(component.edge_ids),
            warnings,
            PartingLineGraphCleanup(
                status="failed",
                strategy="endpoint-graph-unavailable",
                input_edge_count=len(component.edge_ids),
                orderable_edge_count=0,
                retained_edge_count=0,
                removed_edge_count=len(component.edge_ids),
                branch_point_count=0,
                retained_edge_ids=[],
                removed_edge_ids=list(component.edge_ids),
                warnings=warnings,
            ),
        )

    conflict_penalized_edge_ids = sorted(
        edge_id
        for edge_id in endpoint_keys_by_edge
        if _edge_undercut_conflict_penalty(
            edges_by_id[edge_id],
            undercut_face_ids=undercut_ids,
            major_undercut_face_ids=major_undercut_ids,
        ) > 0.0
    )

    def edge_weight(edge_id: int) -> tuple[float, float, int]:
        edge = edges_by_id[edge_id]
        candidate = candidate_by_id.get(edge_id)
        score = candidate.score if candidate is not None else 0.0
        kind_bonus = {
            "silhouette": 0.35,
            "near_parting": 0.12,
            "boundary": 0.05,
            "non_manifold": -0.15,
        }.get(candidate.kind if candidate is not None else "skipped", -0.25)
        conflict_penalty = _edge_undercut_conflict_penalty(
            edge,
            undercut_face_ids=undercut_ids,
            major_undercut_face_ids=major_undercut_ids,
        )
        return (score + kind_bonus - conflict_penalty, edge.length, -edge_id)

    def edge_scalar_weight(edge_id: int) -> float:
        score, length, _ = edge_weight(edge_id)
        return max(0.01, score) * max(1e-6, length)

    def start_weight(point_key: tuple[int, int, int]) -> tuple[int, float, float, int]:
        connected = point_to_edges_of(point_key)
        if not connected:
            return (0, 0.0, 0.0, 0)
        best_edge = max(connected, key=edge_weight)
        edge_score, edge_length, neg_edge_id = edge_weight(best_edge)
        is_open_endpoint = 1 if len(connected) == 1 else 0
        return (is_open_endpoint, edge_score, edge_length, neg_edge_id)

    # Identify open endpoints (degree-1 nodes) using the networkx-backed accessor.
    all_vertex_keys = list(point_coords)
    open_points = [key for key in all_vertex_keys if len(point_to_edges_of(key)) == 1]
    start_points = sorted(open_points or all_vertex_keys, key=start_weight, reverse=True)
    search_edge_limit = 22
    max_search_states = 75_000

    best_path_edges, best_path_keys, best_is_closed, state_count, strategy, hit_state_limit = (
        _best_path_with_contraction_fallback(
            endpoint_keys_by_edge,
            edge_weight=edge_weight,
            edge_scalar_weight=edge_scalar_weight,
            point_to_edges_of=point_to_edges_of,
            start_points=start_points,
            all_nodes=all_vertex_keys,
            search_edge_limit=search_edge_limit,
            max_search_states=max_search_states,
        )
    )
    if strategy == "greedy-fallback":
        warnings.append(
            "Refinement candidate graph is large; bounded search skipped and greedy fallback used."
        )
    elif hit_state_limit:
        warnings.append(
            "Refinement path search hit the state limit; best path found so far was retained."
        )

    if not best_path_edges:
        if open_points:
            start_key = max(open_points, key=start_weight)
        else:
            best_edge_id = max(endpoint_keys_by_edge, key=edge_weight)
            start_key = endpoint_keys_by_edge[best_edge_id][0]

        best_path_edges = []
        best_path_keys = [start_key]
        used_edges: set[int] = set()
        current_key = start_key

        while True:
            available = [
                edge_id
                for edge_id in point_to_edges_of(current_key)
                if edge_id not in used_edges
            ]
            if not available:
                break
            edge_id = max(available, key=edge_weight)
            used_edges.add(edge_id)
            start_endpoint, end_endpoint = endpoint_keys_by_edge[edge_id]
            next_key = end_endpoint if current_key == start_endpoint else start_endpoint
            best_path_edges.append(edge_id)
            best_path_keys.append(next_key)
            current_key = next_key
            if current_key == start_key:
                break
        best_is_closed = len(best_path_keys) > 2 and best_path_keys[0] == best_path_keys[-1]

    all_orderable_edges = set(endpoint_keys_by_edge)
    removed_edges = sorted(all_orderable_edges - set(best_path_edges))
    retained_conflict_edge_ids = sorted(set(best_path_edges) & set(conflict_penalized_edge_ids))
    removed_conflict_edge_ids = sorted(set(removed_edges) & set(conflict_penalized_edge_ids))
    if removed_edges:
        warnings.append(
            "Refinement discarded lower-weight branch/disconnected edge candidates."
        )
    if removed_conflict_edge_ids:
        warnings.append(
            "Refinement removed candidate edge(s) that overlapped undercut evidence."
        )

    points = [point_coords[key] for key in best_path_keys if key in point_coords]
    cleanup_status = "optimized" if best_path_edges else "failed"
    graph_cleanup = PartingLineGraphCleanup(
        status=cleanup_status,
        strategy=strategy,
        input_edge_count=len(component.edge_ids),
        orderable_edge_count=len(endpoint_keys_by_edge),
        retained_edge_count=len(best_path_edges),
        removed_edge_count=len(removed_edges),
        branch_point_count=_branch_point_count(),
        retained_edge_ids=best_path_edges,
        removed_edge_ids=removed_edges,
        conflict_penalized_edge_ids=conflict_penalized_edge_ids,
        retained_conflict_edge_ids=retained_conflict_edge_ids,
        removed_conflict_edge_ids=removed_conflict_edge_ids,
        search_state_count=state_count,
        search_state_limit=max_search_states,
        search_edge_limit=search_edge_limit,
        warnings=warnings,
    )
    return best_path_edges, points, best_is_closed, removed_edges, warnings, graph_cleanup


def _refinement_quality(
    *,
    status: str,
    is_closed: bool,
    removed_edge_count: int,
    refined_point_count: int,
) -> str:
    if status == "empty" or refined_point_count < 2:
        return "empty"
    if status == "fallback":
        return "fallback"
    if removed_edge_count:
        return "graph_cleaned_closed" if is_closed else "graph_cleaned_open"
    return "refined_closed" if is_closed else "refined_open"


def _points_are_closed(points: list[Vec3], point_tolerance: float) -> bool:
    if len(points) < 3:
        return False
    start = points[0]
    end = points[-1]
    return mag3((end[0] - start[0], end[1] - start[1], end[2] - start[2])) <= point_tolerance


def _wire_for_refined_conflict(
    selected_wire: PartingLineWire,
    refinement: PartingLineRefinement,
    *,
    point_tolerance: float,
) -> PartingLineWire:
    refined_edge_ids = list(refinement.refined_edge_ids or selected_wire.ordered_edge_ids)
    refined_points = list(refinement.raw_points or selected_wire.points)
    if not refined_edge_ids:
        return selected_wire

    is_closed = _points_are_closed(refined_points, point_tolerance)
    cleanup_changed_edges = set(refined_edge_ids) != set(selected_wire.ordered_edge_ids)
    return replace(
        selected_wire,
        ordered_edge_ids=refined_edge_ids,
        points=refined_points,
        is_closed=is_closed,
        branch_point_count=0 if cleanup_changed_edges else selected_wire.branch_point_count,
        gap_count=0 if cleanup_changed_edges else selected_wire.gap_count,
        skipped_edge_ids=[] if cleanup_changed_edges else selected_wire.skipped_edge_ids,
    )


def _refine_selected_wire(
    selected_wire: PartingLineWire,
    components: list[PartingLineComponent],
    edges_by_id: dict[int, EdgeData],
    candidate_by_id: dict[int, PartingLineEdgeCandidate],
    pull_direction: Vec3,
    *,
    undercut_context: object | None,
    point_tolerance: float,
    smoothing_iterations: int,
    display_resample_min_points: int,
    max_refined_display_points: int,
) -> PartingLineRefinement:
    if selected_wire.component_id is None or not selected_wire.ordered_edge_ids:
        return PartingLineRefinement(
            status="empty",
            method="Hou-inspired graph cleanup not run; no selected wire.",
            refined_edge_ids=[],
            removed_edge_ids=[],
            raw_points=list(selected_wire.points),
            refined_points=[],
            smoothing_iterations=0,
            confidence=0.0,
            quality="empty",
            projection=PartingLineProjection.empty(),
            display_metrics=_parting_display_metrics(
                raw_points=list(selected_wire.points),
                resampled_points=list(selected_wire.points),
                refined_points=[],
                is_closed=False,
                requested_smoothing_iterations=smoothing_iterations,
                applied_smoothing_iterations=0,
                max_refined_display_points=max_refined_display_points,
            ),
            graph_cleanup=PartingLineGraphCleanup.not_run("No selected parting wire was available."),
            warnings=["No selected parting wire was available for refinement."],
        )

    component_by_id = {component.component_id: component for component in components}
    component = component_by_id.get(selected_wire.component_id)
    warnings: list[str] = []

    if component is None:
        raw_points = list(selected_wire.points)
        resample_target = max(len(raw_points), display_resample_min_points)
        resampled_points = _resample_polyline(
            raw_points,
            is_closed=selected_wire.is_closed,
            target_point_count=resample_target,
        )
        requested_smoothing = max(0, smoothing_iterations)
        applied_smoothing = requested_smoothing
        while (
            applied_smoothing > 0
            and _estimated_chaikin_point_count(
                len(resampled_points),
                is_closed=selected_wire.is_closed,
                iterations=applied_smoothing,
            ) > max_refined_display_points
        ):
            applied_smoothing -= 1
        refined_points = _chaikin_smooth(
            resampled_points,
            is_closed=selected_wire.is_closed,
            iterations=applied_smoothing,
        )
        projection = _wire_projection(
            refined_points,
            pull_direction,
            is_closed=selected_wire.is_closed,
        )
        return PartingLineRefinement(
            status="fallback",
            method="Display smoothing only; selected component metadata unavailable.",
            refined_edge_ids=list(selected_wire.ordered_edge_ids),
            removed_edge_ids=[],
            raw_points=raw_points,
            refined_points=refined_points,
            smoothing_iterations=applied_smoothing,
            confidence=0.45,
            quality=_refinement_quality(
                status="fallback",
                is_closed=selected_wire.is_closed,
                removed_edge_count=0,
                refined_point_count=len(refined_points),
            ),
            projection=projection,
            display_metrics=_parting_display_metrics(
                raw_points=raw_points,
                resampled_points=resampled_points,
                refined_points=refined_points,
                is_closed=selected_wire.is_closed,
                requested_smoothing_iterations=requested_smoothing,
                applied_smoothing_iterations=applied_smoothing,
                max_refined_display_points=max_refined_display_points,
            ),
            graph_cleanup=PartingLineGraphCleanup.not_run("Selected component metadata was unavailable."),
            warnings=[
                "Selected component metadata was unavailable.",
                *(
                    ["Display smoothing was reduced to stay within the parting-curve point budget."]
                    if applied_smoothing < requested_smoothing
                    else []
                ),
            ],
        )

    graph_cleanup = PartingLineGraphCleanup.not_run()
    if selected_wire.branch_point_count or selected_wire.gap_count or selected_wire.skipped_edge_ids:
        refined_edge_ids, raw_points, is_closed, removed_edge_ids, graph_warnings, graph_cleanup = _trace_best_weighted_path(
            component,
            edges_by_id,
            candidate_by_id,
            point_tolerance=point_tolerance,
            undercut_face_ids=_undercut_face_ids_from_context(undercut_context),
            major_undercut_face_ids=_major_undercut_face_ids_from_context(undercut_context),
        )
        warnings.extend(graph_warnings)
        status = "accepted" if refined_edge_ids and len(raw_points) >= 2 else "fallback"
        if status == "fallback":
            refined_edge_ids = list(selected_wire.ordered_edge_ids)
            raw_points = list(selected_wire.points)
            is_closed = selected_wire.is_closed
            removed_edge_ids = []
            graph_cleanup = PartingLineGraphCleanup(
                status="fallback",
                strategy=graph_cleanup.strategy,
                input_edge_count=graph_cleanup.input_edge_count,
                orderable_edge_count=graph_cleanup.orderable_edge_count,
                retained_edge_count=len(refined_edge_ids),
                removed_edge_count=0,
                branch_point_count=graph_cleanup.branch_point_count,
                retained_edge_ids=refined_edge_ids,
                removed_edge_ids=[],
                conflict_penalized_edge_ids=graph_cleanup.conflict_penalized_edge_ids,
                retained_conflict_edge_ids=sorted(
                    set(refined_edge_ids) & set(graph_cleanup.conflict_penalized_edge_ids)
                ),
                removed_conflict_edge_ids=[],
                search_state_count=graph_cleanup.search_state_count,
                search_state_limit=graph_cleanup.search_state_limit,
                search_edge_limit=graph_cleanup.search_edge_limit,
                warnings=[*graph_cleanup.warnings, "Graph cleanup fallback retained the raw selected wire."],
            )
            warnings.append("Graph cleanup did not produce a valid trace; raw selected wire retained.")
    else:
        refined_edge_ids = list(selected_wire.ordered_edge_ids)
        raw_points = list(selected_wire.points)
        is_closed = selected_wire.is_closed
        removed_edge_ids = []
        status = "accepted"

    resample_target = max(len(raw_points), display_resample_min_points)
    resampled_points = _resample_polyline(
        raw_points,
        is_closed=is_closed,
        target_point_count=resample_target,
    )
    requested_smoothing = max(0, smoothing_iterations)
    applied_smoothing = requested_smoothing
    while (
        applied_smoothing > 0
        and _estimated_chaikin_point_count(
            len(resampled_points),
            is_closed=is_closed,
            iterations=applied_smoothing,
        ) > max_refined_display_points
    ):
        applied_smoothing -= 1
    if applied_smoothing < requested_smoothing:
        warnings.append("Display smoothing was reduced to stay within the parting-curve point budget.")
    refined_points = _chaikin_smooth(
        resampled_points,
        is_closed=is_closed,
        iterations=applied_smoothing,
    )
    projection = _wire_projection(refined_points, pull_direction, is_closed=is_closed)

    confidence = 0.9 if is_closed else 0.72
    if removed_edge_ids:
        confidence -= 0.12
    if status == "fallback":
        confidence = min(confidence, 0.45)
    if selected_wire.skipped_edge_ids:
        confidence -= 0.08
    confidence = max(0.0, min(1.0, confidence))

    return PartingLineRefinement(
        status=status,
        method=(
            "Hou-inspired graph-weighted cleanup plus Chaikin display smoothing; "
            "not full Hou global optimization."
        ),
        refined_edge_ids=refined_edge_ids,
        removed_edge_ids=removed_edge_ids,
        raw_points=raw_points,
        refined_points=refined_points,
        smoothing_iterations=applied_smoothing,
        confidence=confidence,
        quality=_refinement_quality(
            status=status,
            is_closed=is_closed,
            removed_edge_count=len(removed_edge_ids),
            refined_point_count=len(refined_points),
        ),
        projection=projection,
        display_metrics=_parting_display_metrics(
            raw_points=raw_points,
            resampled_points=resampled_points,
            refined_points=refined_points,
            is_closed=is_closed,
            requested_smoothing_iterations=requested_smoothing,
            applied_smoothing_iterations=applied_smoothing,
            max_refined_display_points=max_refined_display_points,
        ),
        graph_cleanup=graph_cleanup,
        warnings=warnings,
    )


def _readiness_status(score: float, blockers: list[str]) -> tuple[str, str]:
    if blockers:
        return "failed", "No reliable parting-line candidate"
    if score >= 0.78:
        return "ready", "Ready for Level 1 review"
    if score >= 0.52:
        return "review", "Usable candidate, review recommended"
    return "weak", "Weak candidate, manual review required"


def _parting_line_readiness(
    selected_wire: PartingLineWire,
    refinement: PartingLineRefinement,
    warnings: list[str],
) -> PartingLineReadiness:
    blockers: list[str] = []
    reasons: list[str] = []
    score = 0.0

    if not selected_wire.ordered_edge_ids:
        blockers.append("no selected candidate edges")
    if len(refinement.refined_points) < 2:
        blockers.append("refinement produced fewer than two points")

    if blockers:
        status, label = _readiness_status(0.0, blockers)
        return PartingLineReadiness(
            status=status,
            score=0.0,
            label=label,
            reasons=["parting-line candidate was not usable"],
            blockers=blockers,
        )

    score = 0.45
    if selected_wire.is_closed:
        score += 0.18
        reasons.append("selected wire is closed")
    elif selected_wire.quality == "open_chain":
        score += 0.08
        reasons.append("selected wire is an open chain")

    score += 0.28 * selected_wire.quality_assessment.score
    reasons.append(f"selection quality is {selected_wire.quality_assessment.level}")

    if refinement.status == "accepted":
        score += 0.08
        reasons.append("refinement accepted")
    elif refinement.status == "fallback":
        score -= 0.10
        reasons.append("refinement fell back to raw wire")
    elif refinement.status == "disabled":
        score -= 0.16
        reasons.append("refinement disabled")

    if selected_wire.branch_point_count:
        penalty = min(0.16, 0.05 * selected_wire.branch_point_count)
        score -= penalty
        reasons.append(f"{selected_wire.branch_point_count} branch point(s)")
    if selected_wire.gap_count:
        penalty = min(0.20, 0.08 * selected_wire.gap_count)
        score -= penalty
        reasons.append(f"{selected_wire.gap_count} gap(s)")
    if selected_wire.skipped_edge_ids:
        penalty = min(0.12, 0.03 * len(selected_wire.skipped_edge_ids))
        score -= penalty
        reasons.append("some selected edges lack endpoint data")

    if selected_wire.undercut_conflict.checked:
        conflict_penalty = 0.32 * selected_wire.undercut_conflict.conflict_score
        if conflict_penalty:
            score -= conflict_penalty
            reasons.append(f"undercut conflict is {selected_wire.undercut_conflict.conflict_level}")
        else:
            reasons.append("no selected-wire undercut conflict detected")
    else:
        score -= 0.04
        reasons.append("undercut conflict not checked")

    if selected_wire.projection.quality in {"closed_area", "open_extent"}:
        score += 0.05
        reasons.append(f"projection is {selected_wire.projection.quality}")
    else:
        score -= 0.08
        reasons.append(f"projection is {selected_wire.projection.quality}")

    if warnings:
        score -= min(0.08, 0.015 * len(warnings))

    score = max(0.0, min(1.0, score))
    status, label = _readiness_status(score, blockers)
    return PartingLineReadiness(
        status=status,
        score=score,
        label=label,
        reasons=reasons,
        blockers=blockers,
    )


def _parting_line_diagnostic_gate(
    readiness: PartingLineReadiness,
    selected_wire: PartingLineWire,
    refinement: PartingLineRefinement,
    warnings: list[str],
) -> PartingLineDiagnosticGate:
    display_point_count = len(refinement.refined_points) or len(selected_wire.points)
    can_display_curve = display_point_count >= 2
    has_high_conflict = (
        selected_wire.undercut_conflict.checked
        and selected_wire.undercut_conflict.conflict_level == "high"
    )
    has_topology_instability = bool(
        selected_wire.branch_point_count
        or selected_wire.gap_count
        or selected_wire.skipped_edge_ids
    )

    limitations = [
        "Candidate is a parting-line approximation, not a final mold split surface.",
        "Full Hou global optimization is not applied in this Level 1 layer.",
    ]
    if selected_wire.undercut_conflict.checked:
        limitations.append(
            "Undercut conflict uses edge/face overlap and feature proximity heuristics."
        )
    else:
        limitations.append("Undercut conflict was not checked for this result.")
    if refinement.status == "disabled":
        limitations.append("Graph cleanup/refinement was disabled by caller.")
    if has_topology_instability:
        limitations.append("Selected wire has branch, gap, or endpoint-data instability.")
    if warnings:
        limitations.append("Structured warnings are present and should be reviewed.")

    if readiness.status == "failed":
        return PartingLineDiagnosticGate(
            status="failed",
            can_display_curve=can_display_curve,
            can_use_for_report=False,
            blocks_core_cavity=True,
            requires_manual_review=True,
            severity="error",
            summary="No reliable parting-line candidate was produced.",
            recovery_hint=(
                "Inspect STEP topology, try the optimal mold direction, and review "
                "candidate edge extraction before using this result downstream."
            ),
            limitations=limitations,
        )

    if readiness.status == "weak":
        return PartingLineDiagnosticGate(
            status="weak",
            can_display_curve=can_display_curve,
            can_use_for_report=False,
            blocks_core_cavity=True,
            requires_manual_review=True,
            severity="warning",
            summary="A weak candidate is available for visual inspection only.",
            recovery_hint=(
                "Use the overlay as a diagnostic aid, then review branches, gaps, "
                "projection quality, and undercut conflict before reporting."
            ),
            limitations=limitations,
        )

    if readiness.status == "review" or has_high_conflict or has_topology_instability:
        return PartingLineDiagnosticGate(
            status="review",
            can_display_curve=can_display_curve,
            can_use_for_report=True,
            blocks_core_cavity=has_high_conflict,
            requires_manual_review=True,
            severity="info" if not has_high_conflict else "warning",
            summary="Candidate is usable for Level 1 reporting with manual review.",
            recovery_hint=(
                "Check selected/refined curves against highlighted undercuts and "
                "confirm the selected loop before core/cavity work."
            ),
            limitations=limitations,
        )

    return PartingLineDiagnosticGate(
        status="ready",
        can_display_curve=can_display_curve,
        can_use_for_report=True,
        blocks_core_cavity=False,
        requires_manual_review=False,
        severity="success",
        summary="Candidate is ready for Level 1 demo/report review.",
        recovery_hint=(
            "Proceed with visualization/reporting; still treat it as a candidate "
            "until final mold split surface extraction exists."
        ),
        limitations=limitations,
    )


def _parting_line_diagnostics(
    candidates: list[PartingLineEdgeCandidate],
    selected_wire: PartingLineWire,
    refinement: PartingLineRefinement,
    readiness: PartingLineReadiness,
    warnings: list[str],
) -> PartingLineDiagnostics:
    skipped_reasons: dict[str, int] = {}
    for candidate in candidates:
        if candidate.kind != "skipped":
            continue
        reason = candidate.reason or "unspecified"
        skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1

    notes: list[str] = []
    failure_code: str | None = None
    recovery_hint = (
        "Review the selected/refined curve and warnings before using this "
        "candidate for reporting or downstream core/cavity work."
    )

    if not candidates:
        failure_code = "no_edges_classified"
        recovery_hint = "Confirm the STEP loader extracted topology edges for this part."
    elif not any(candidate.is_candidate for candidate in candidates):
        failure_code = "no_candidate_edges"
        recovery_hint = (
            "Try the optimized mold direction, relax parting-line tolerances, "
            "or inspect whether the model has valid adjacent face normals."
        )
    elif not selected_wire.ordered_edge_ids:
        failure_code = "selected_wire_unorderable"
        recovery_hint = (
            "Inspect candidate edges without endpoints and verify OCC curve "
            "sampling is available in the Docker/conda runtime."
        )
    elif len(refinement.refined_points) < 2:
        failure_code = "refinement_no_display_curve"
        recovery_hint = "Use raw candidate diagnostics and inspect endpoint topology."

    if selected_wire.branch_point_count:
        notes.append("Selected candidate contains branch points.")
    if selected_wire.gap_count:
        notes.append("Selected candidate contains disconnected gaps.")
    if selected_wire.skipped_edge_ids:
        notes.append("Some selected candidate edges were not orderable.")
    if refinement.status == "fallback":
        notes.append("Refinement fell back to the raw selected wire.")
    if refinement.status == "disabled":
        notes.append("Refinement was disabled by caller.")

    if readiness.status == "failed":
        status = "failed"
    elif warnings or readiness.status in {"weak", "review"}:
        status = "warning"
    else:
        status = "ok"

    return PartingLineDiagnostics(
        status=status,
        failure_code=failure_code,
        recovery_hint=recovery_hint,
        skipped_edge_count=sum(skipped_reasons.values()),
        skipped_reasons=skipped_reasons,
        unorderable_edge_count=len(selected_wire.skipped_edge_ids),
        branch_point_count=selected_wire.branch_point_count,
        gap_count=selected_wire.gap_count,
        warning_count=len(warnings),
        notes=notes,
    )


def _decimate_closed_loop(points: list[Vec3], max_segments: int) -> list[Vec3]:
    """
    Reduce a dense display curve to at most ``max_segments`` segments while
    preserving closure.

    The refined parting curve is a *display* polyline — Chaikin smoothing plus
    resampling leaves ~24,000 points on a real part.  ``BRepFill_Filling``
    takes one edge constraint per segment, so feeding it the raw curve means
    ~24,000 constraints, which is unusable.  Uniform index sampling keeps the
    loop's shape while making the constraint set tractable.
    """
    if max_segments < 3 or len(points) <= max_segments + 1:
        return list(points)

    closed = len(points) > 2 and points[0] == points[-1]
    body = points[:-1] if closed else list(points)
    if len(body) <= max_segments:
        return list(points)

    step = len(body) / float(max_segments)
    sampled = [body[int(round(i * step)) % len(body)] for i in range(max_segments)]

    # Drop consecutive duplicates introduced by rounding.
    deduped: list[Vec3] = []
    for p in sampled:
        if not deduped or p != deduped[-1]:
            deduped.append(p)
    if len(deduped) < 3:
        return list(points)
    deduped.append(deduped[0])  # re-close
    return deduped


def _build_parting_surface(
    loop_points: list[Vec3],
    bbox_diagonal_mm: float,
    *,
    pull_direction: Vec3 | None = None,
    planar_tolerance_mm: float = 0.25,
    planar_pull_alignment_min: float = 0.90,
    extension_factor: float = 1.5,
    filling_max_degree: int = 3,
    filling_tolerance_mm: float = 0.01,
    filling_max_constraint_edges: int = 120,
) -> PartingSurfaceResult:
    """
    Build a B-Rep parting surface from a closed parting-line loop (Milestone 1.9).

    Tries two strategies in order:

    1. **PCA planar extrusion** — only when the loop is genuinely flat *and*
       its best-fit plane is a valid parting plane.
    2. **BRepFill_Filling** — an N-sided patch through the loop, for the
       ordinary case of a real 3-D parting line.

    Why the planar path needs a pull-direction check
    ------------------------------------------------
    A mold opens along the pull direction, so a parting plane's normal must be
    roughly parallel to it.  PCA finds the plane that best *fits* the points,
    which is not the same thing.  Measured on Part3: PCA fits the loop to
    0.74 mm, but its normal sits ~60° off the pull axis — using it would slice
    the mold diagonally instead of separating cavity from core.  So the planar
    strategy additionally requires ``|dot(plane_normal, pull)| >=
    planar_pull_alignment_min``.

    Most real parting lines are not planar at all.  Measured pull-axis span of
    the parting loop: Part1 16.16 mm on a 30.78 mm part, Part3 7.14 mm on
    68.12 mm.  Nee et al. (1998) is titled "Automatic Determination of *3-D*
    Parting Lines and Surfaces" for exactly this reason — the filling path is
    the normal path, not an exotic fallback.

    The returned ``PartingSurfaceResult.occ_shape`` is the reported/displayed
    parting-line candidate surface — it is NOT what Milestone 1.10's Boolean
    solid split uses as its splitting tool. Returns ``status="failed"`` with
    a ``failure_reason`` on any OCC error — never raises.

    Stage 2 (S2.3) tried extending this patch to the blank's walls with a
    lofted "shoulder" collar and confirmed (via ``BRepCheck_Analyzer`` plus
    ``ShapeFix_Shape``/``ShapeFix_Face``/``BRepBuilderAPI_Sewing`` healing
    attempts, all unsuccessful) that the underlying ``BRepFill_Filling``
    patch is topologically invalid on both real parts *independent of any
    extension* — see CHANGELOG.md 2026-07-28 "Stage 2b". Milestone 1.10 now
    builds its own separate, always-valid planar splitting tool instead
    (``core_cavity.build_planar_split_tool``); this function's output is
    unaffected by that and stays exactly what Milestone 1.9 always returned.

    Only callable when ``_OCC_SURFACE_AVAILABLE`` is True.
    """
    if not _OCC_SURFACE_AVAILABLE:
        return PartingSurfaceResult(
            status="not_attempted",
            strategy="none",
            failure_reason="pythonOCC surface APIs not available in this environment.",
        )

    pts = [p for p in loop_points if p is not None]
    if len(pts) < 3:
        return PartingSurfaceResult(
            status="failed",
            strategy="none",
            failure_reason=f"Insufficient loop points ({len(pts)}) for surface generation.",
        )

    # --- PCA to find best-fit plane ---
    pts_arr = _np.array(pts, dtype=float)
    centroid = pts_arr.mean(axis=0)
    centered = pts_arr - centroid
    try:
        _, _, V = _np.linalg.svd(centered, full_matrices=False)
        normal_arr = V[-1]  # last row = smallest singular vector = plane normal
        # Ensure normal has unit length
        nlen = _np.linalg.norm(normal_arr)
        if nlen < 1e-12:
            raise ValueError("Degenerate point cloud — zero normal.")
        normal_arr = normal_arr / nlen
    except Exception as exc:
        return PartingSurfaceResult(
            status="failed",
            strategy="none",
            failure_reason=f"PCA failed: {exc}",
        )

    # Compute max deviation from the PCA plane
    deviations = _np.abs(centered @ normal_arr)
    max_deviation = float(deviations.max())

    # A flat loop is only a valid PARTING plane if the plane's normal is
    # roughly parallel to the pull direction (see docstring).
    pull_alignment: float | None = None
    if pull_direction is not None:
        pull_arr = _np.array([float(v) for v in pull_direction], dtype=float)
        pull_norm = _np.linalg.norm(pull_arr)
        if pull_norm > 1e-12:
            pull_alignment = float(abs(normal_arr @ (pull_arr / pull_norm)))

    planar_is_flat = max_deviation <= planar_tolerance_mm
    planar_is_valid_orientation = (
        pull_alignment is None or pull_alignment >= planar_pull_alignment_min
    )

    # --- Strategy 1: Planar extrusion (if loop is sufficiently flat) ---
    if planar_is_flat and planar_is_valid_orientation:
        try:
            # Build OCC wire from consecutive loop points
            wire_builder = BRepBuilderAPI_MakeWire()
            prev_pt = gp_Pnt(*[float(v) for v in pts[-1]])
            for pt in pts:
                curr_pt = gp_Pnt(*[float(v) for v in pt])
                if prev_pt.Distance(curr_pt) < 1e-9:
                    prev_pt = curr_pt
                    continue
                edge = BRepBuilderAPI_MakeEdge(prev_pt, curr_pt)
                if not edge.IsDone():
                    prev_pt = curr_pt
                    continue
                wire_builder.Add(edge.Edge())
                prev_pt = curr_pt
            if not wire_builder.IsDone():
                raise RuntimeError("Wire construction failed for planar extrusion.")

            # Build the bounded planar face
            plane_normal = gp_Dir(*[float(v) for v in normal_arr])
            plane_origin = gp_Pnt(*[float(v) for v in centroid])
            plane = gp_Pln(plane_origin, plane_normal)
            face_builder = BRepBuilderAPI_MakeFace(plane, wire_builder.Wire(), True)
            if not face_builder.IsDone():
                raise RuntimeError("MakeFace failed — wire may not lie on plane.")

            # Extrude past bbox by extension_factor in both ±normal directions
            ext_dist = bbox_diagonal_mm * extension_factor
            ext_vec = gp_Vec(
                float(normal_arr[0]) * ext_dist,
                float(normal_arr[1]) * ext_dist,
                float(normal_arr[2]) * ext_dist,
            )
            prism = BRepPrimAPI_MakePrism(face_builder.Face(), ext_vec, True)
            prism.Build()
            if not prism.IsDone():
                raise RuntimeError("MakePrism extrusion failed.")

            surface_shape = prism.Shape()

            # Compute area for verification
            props = GProp_GProps()
            brepgprop_SurfaceProperties(surface_shape, props)
            area = float(props.Mass())

            return PartingSurfaceResult(
                status="generated_planar",
                strategy="pca_planar",
                planar_deviation_mm=max_deviation,
                extension_factor=extension_factor,
                area_mm2=area,
                occ_shape=surface_shape,
            )

        except Exception as exc:
            # Fall through to BRepFill_Filling strategy
            planar_failure = str(exc)
    elif not planar_is_flat:
        planar_failure = (
            f"Loop is non-planar (max deviation {max_deviation:.3f} mm > "
            f"tolerance {planar_tolerance_mm} mm)"
        )
    else:
        planar_failure = (
            f"Best-fit plane is flat ({max_deviation:.3f} mm) but is not a valid "
            f"parting plane: |dot(normal, pull)| = {pull_alignment:.3f} < "
            f"{planar_pull_alignment_min} — the plane is tilted relative to the "
            f"mold opening direction"
        )

    # --- Strategy 2: BRepFill_Filling (N-sided patch through the loop) ---
    # The refined curve is a dense DISPLAY polyline (~24k points on a real
    # part).  Filling takes one edge constraint per segment, so it must be
    # decimated first or the solver is swamped.
    fill_pts = _decimate_closed_loop(pts, filling_max_constraint_edges)
    try:
        # Positional signature is
        #   (Degree, NbPtsOnCur, NbIter, Anisotropie, Tol2d, Tol3d, ...)
        # The previous call passed NbPtsOnCur=0 and NbIter=0, which OCC
        # rejects outright with
        #   "Standard_ConstructionErrorGeomPlate : Number of iteration must be >= 1"
        # so the filling path could never run.  Use OCC's own defaults for the
        # solver knobs and put the caller's tolerance on Tol3d (a 3-D distance),
        # not Tol2d (a parametric tolerance).
        filling = BRepFill_Filling(
            filling_max_degree,   # Degree
            15,                   # NbPtsOnCur  (OCC default)
            2,                    # NbIter      (OCC default; MUST be >= 1)
            False,                # Anisotropie
            1e-5,                 # Tol2d       (OCC default)
            float(filling_tolerance_mm),  # Tol3d
        )
        constraint_edges = 0
        prev_pt = gp_Pnt(*[float(v) for v in fill_pts[-1]])
        for pt in fill_pts:
            curr_pt = gp_Pnt(*[float(v) for v in pt])
            if prev_pt.Distance(curr_pt) < 1e-9:
                prev_pt = curr_pt
                continue
            edge = BRepBuilderAPI_MakeEdge(prev_pt, curr_pt)
            if edge.IsDone():
                filling.Add(edge.Edge(), 0)  # GeomAbs_C0 = 0
                constraint_edges += 1
            prev_pt = curr_pt

        if constraint_edges < 3:
            raise RuntimeError(
                f"Only {constraint_edges} usable constraint edge(s) after decimation."
            )

        filling.Build()
        if not filling.IsDone():
            raise RuntimeError("BRepFill_Filling did not converge.")

        surface_shape = filling.Face()
        props = GProp_GProps()
        brepgprop_SurfaceProperties(surface_shape, props)
        area = float(props.Mass())
        if not (area > 0.0):
            raise RuntimeError(f"Filling produced a degenerate face (area {area}).")

        # Stage 2 (S2.3) tried extending this patch to the blank's walls with
        # a lofted "shoulder" collar (see CHANGELOG.md 2026-07-28 "Stage 2b").
        # It genuinely worked as *area extension* (measured 2,352->20,226 mm^2
        # on Part1, 603->71,308 mm^2 on Part3) but did not fix the real
        # problem: BRepCheck_Analyzer confirms this BRepFill_Filling patch is
        # topologically invalid on its own, before any extension is applied,
        # on both real parts. ShapeFix_Shape, ShapeFix_Face, and
        # BRepBuilderAPI_Sewing were all tried directly against the raw patch
        # and against the shoulder-extended/sewn compound; none produced a
        # valid shape. BRepAlgoAPI_Splitter cannot reliably consume an
        # invalid tool shape, so extending it further does not help. The
        # Boolean split (Milestone 1.10) now uses a separate, always-valid
        # planar tool instead (`core_cavity.build_planar_split_tool`) — this
        # surface remains purely the reported/displayed parting-line
        # candidate, unchanged from before Stage 2.
        return PartingSurfaceResult(
            status="generated_filling",
            strategy="brepfill_filling",
            planar_deviation_mm=max_deviation,
            extension_factor=1.0,  # Filling doesn't extrude
            area_mm2=area,
            occ_shape=surface_shape,
        )

    except Exception as exc:
        return PartingSurfaceResult(
            status="failed",
            strategy="none",
            planar_deviation_mm=max_deviation,
            failure_reason=(
                f"Planar strategy: {planar_failure}. "
                f"Filling fallback ({len(fill_pts)} decimated pts): {exc}"
            ),
        )


def _attempt_loop_closure(
    refined_points: list[Vec3],
    is_closed: bool,
    edges_by_id: dict[int, EdgeData],
    candidate_by_id: dict[int, PartingLineEdgeCandidate],
    *,
    point_tolerance: float,
    undercut_face_ids: set[int],
    bridge_penalty_factor: float,
    boundary_bridge_factor: float,
    max_closure_error_mm: float,
) -> tuple[bool, float, list[Vec3], int, list[str]]:
    """
    Assess loop closure and actually close the wire when possible (Milestone 1.8).

    Returns
    -------
    ``(closure_guaranteed, closure_error_mm, closed_points, bridge_edge_count, warnings)``

    ``closed_points`` is the FULL point list the caller must use downstream.
    When a closing path is found, it is ``refined_points`` plus the real
    B-Rep vertices along that path plus an exact repeat of the first point,
    so the returned curve is genuinely closed.  When closure is not achieved
    it is ``refined_points`` unchanged and ``closure_guaranteed`` is False.

    ``closure_error_mm`` always describes the FINAL state of
    ``closed_points`` — it is measured, never assumed.

    Honesty contract
    ----------------
    This function must never report ``closure_guaranteed=True`` unless the
    points it returns are measurably closed within ``max_closure_error_mm``.
    A previous implementation computed the closing path and then discarded
    it, returning ``(True, 0.0)`` while handing back a curve with a 17 mm
    gap; the parting *surface* was then built from that open curve and every
    downstream stage silently trusted the false guarantee.  The final
    measured re-check below exists specifically to make that class of bug
    impossible.
    """
    raw_error = _closure_error_mm(refined_points, is_closed=is_closed)

    if is_closed:
        return True, raw_error, list(refined_points), 0, []

    if not refined_points:
        return False, 0.0, [], 0, []

    start = refined_points[0]
    end = refined_points[-1]
    error = mag3((end[0] - start[0], end[1] - start[1], end[2] - start[2]))

    if error <= max_closure_error_mm:
        return True, error, list(refined_points), 0, [
            f"Closure error {error:.4f} mm ≤ threshold {max_closure_error_mm} mm; "
            "wire treated as closed."
        ]

    if not _NX_AVAILABLE:
        return False, error, list(refined_points), 0, [
            f"Wire is open (closure error {error:.4f} mm > {max_closure_error_mm} mm); "
            "loop-closure requires networkx (unavailable)."
        ]

    # Rebuild G_all to find a closing path (same edge graph used in bridging).
    # `key_to_point` lets us map the resulting path of quantized node keys
    # back to real 3-D coordinates — without it the path cannot be spliced
    # into the curve, which is exactly how the original defect arose.
    G_cls: object = nx.Graph()  # type: ignore[union-attr]
    key_to_point: dict[tuple[int, int, int], Vec3] = {}
    candidate_edge_ids = set(candidate_by_id)
    for edge in edges_by_id.values():
        if edge.start_vertex is None or edge.end_vertex is None:
            continue
        sk = _point_key(edge.start_vertex, point_tolerance)
        ek = _point_key(edge.end_vertex, point_tolerance)
        if sk == ek:
            continue
        if any(fid in undercut_face_ids for fid in edge.adjacent_face_ids):
            continue
        key_to_point.setdefault(sk, edge.start_vertex)
        key_to_point.setdefault(ek, edge.end_vertex)
        if edge.edge_id in candidate_edge_ids:
            cost = 1.0 * max(edge.length, 1e-9)
        elif edge.is_boundary:
            cost = boundary_bridge_factor * max(edge.length, 1e-9)
        else:
            cost = bridge_penalty_factor * max(edge.length, 1e-9)
        G_cls.add_edge(sk, ek, cost=cost)  # type: ignore[union-attr]

    start_key = _point_key(start, point_tolerance)
    end_key = _point_key(end, point_tolerance)

    if start_key not in G_cls or end_key not in G_cls:  # type: ignore[operator]
        return False, error, list(refined_points), 0, [
            f"Wire is open (closure error {error:.4f} mm > {max_closure_error_mm} mm); "
            "endpoint keys not in part edge graph — cannot force closure.",
            "Readiness downgraded to 'review': loop cannot be closed automatically.",
        ]

    try:
        path = nx.shortest_path(  # type: ignore[union-attr]
            G_cls, source=end_key, target=start_key, weight="cost"
        )
    except (nx.NetworkXNoPath, nx.NodeNotFound, nx.exception.NetworkXError):  # type: ignore[union-attr]
        return False, error, list(refined_points), 0, [
            f"Wire is open (closure error {error:.4f} mm > {max_closure_error_mm} mm); "
            "no path found in part edge graph to close the loop.",
            "Readiness downgraded to 'review': loop closure required but failed.",
        ]

    # Splice the closing path into the curve.  `path` runs end_key -> ... ->
    # start_key; path[0] duplicates the existing last point and path[-1]
    # duplicates the first, so only the interior nodes are appended.  The
    # loop is then closed exactly by repeating the original first point.
    interior_keys = path[1:-1]
    missing = [k for k in interior_keys if k not in key_to_point]
    if missing:
        return False, error, list(refined_points), 0, [
            f"Wire is open (closure error {error:.4f} mm > {max_closure_error_mm} mm); "
            f"{len(missing)} closing-path vertex coordinate(s) unavailable — "
            "cannot splice a closing path.",
            "Readiness downgraded to 'review': loop closure required but failed.",
        ]

    closed_points = list(refined_points)
    closed_points.extend(key_to_point[k] for k in interior_keys)
    closed_points.append(refined_points[0])
    bridge_edge_count = len(path) - 1

    # Measured re-check: never trust the construction, verify it.
    final_error = mag3((
        closed_points[-1][0] - closed_points[0][0],
        closed_points[-1][1] - closed_points[0][1],
        closed_points[-1][2] - closed_points[0][2],
    ))
    if final_error > max_closure_error_mm:
        return False, final_error, list(refined_points), 0, [
            f"Loop-closure splice did not converge: residual gap {final_error:.4f} mm "
            f"still exceeds {max_closure_error_mm} mm. Original curve retained.",
            "Readiness downgraded to 'review': loop closure required but failed.",
        ]

    return True, final_error, closed_points, bridge_edge_count, [
        f"Loop closed via {bridge_edge_count} additional B-Rep edge(s); "
        f"original open gap was {error:.4f} mm, residual gap is {final_error:.6f} mm "
        f"(≤ {max_closure_error_mm} mm)."
    ]


def detect_parting_line_candidates(
    part: PartGeometry,
    pull_direction: Vec3 | None = None,
    *,
    undercut_context: object | None = None,
    dot_tolerance: float = 0.01,
    boundary_dot_tolerance: float = 0.15,
    point_tolerance: float = 1e-4,
    include_boundary: bool = True,
    refine: bool = True,
    smoothing_iterations: int = 8,
    display_resample_min_points: int = 96,
    max_refined_display_points: int = 32_000,
    bridge_components: bool = True,
    bridge_penalty_factor: float = 4.0,
    boundary_bridge_factor: float = 0.6,
    max_closure_error_mm: float = 0.05,
    mutate: bool = True,
) -> PartingLineResult:
    """
    Detect initial silhouette/parting edge candidates for a pull direction.

    This follows the first Nee-style step: an edge is a strong silhouette
    candidate when the two adjacent face normals have opposite signed dot
    values relative to the pull direction.  Near-zero signed dots are retained
    as weaker parting-region candidates because real CAD models often place the
    final parting curve on vertical/near-vertical transition faces.
    """
    if dot_tolerance <= 0.0:
        raise ValueError("dot_tolerance must be positive.")
    if boundary_dot_tolerance <= 0.0:
        raise ValueError("boundary_dot_tolerance must be positive.")
    if point_tolerance <= 0.0:
        raise ValueError("point_tolerance must be positive.")
    if smoothing_iterations < 0:
        raise ValueError("smoothing_iterations must be non-negative.")
    if display_resample_min_points < 2:
        raise ValueError("display_resample_min_points must be at least 2.")
    if max_refined_display_points < 2:
        raise ValueError("max_refined_display_points must be at least 2.")

    direction = normalize3(pull_direction or part.optimal_pull_direction or (0.0, 0.0, 1.0))
    edges_by_id = {edge.edge_id: edge for edge in part.edges}
    candidates = [
        _classify_edge(
            part,
            edge,
            direction,
            dot_tolerance=dot_tolerance,
            boundary_dot_tolerance=boundary_dot_tolerance,
            include_boundary=include_boundary,
        )
        for edge in part.edges
    ]
    components, component_points = _candidate_components(
        edges_by_id,
        candidates,
        point_tolerance=point_tolerance,
    )

    candidate_by_id = {candidate.edge_id: candidate for candidate in candidates if candidate.is_candidate}

    def _build_and_select(
        comps: list[PartingLineComponent],
    ) -> tuple[list[PartingLineWire], PartingLineWire]:
        wires = [
            _build_ordered_wire(
                component,
                edges_by_id,
                candidate_by_id,
                point_tolerance=point_tolerance,
                pull_direction=direction,
            )
            for component in comps
        ]
        wires = _apply_wire_assessments(
            wires, comps, part, edges_by_id, direction, undercut_context
        )
        return wires, _select_projected_wire(wires, comps)

    # Select from the ORIGINAL components first.
    component_wires, selected_wire = _build_and_select(components)

    # Milestone 1.7: bridge disconnected silhouette components through real
    # B-Rep edges — but only as a FALLBACK.
    #
    # Bridging exists to turn disconnected silhouette fragments into a closed
    # loop.  When `_select_projected_wire` has already found a clean closed
    # loop among the individual components, bridging has nothing to add and
    # measurably destroys the result: it merges every component into one
    # branchy super-component.  Measured on Part1 at its optimal direction —
    # identical inputs, bridging the only variable:
    #
    #     bridging OFF : ready(1.000)  quality high(0.96)  closed=True
    #                    0 branch pts / 0 gaps   0.2 s
    #     bridging ON  : weak (0.080)  quality empty(0.0)  closed=False
    #                    11 branch pts / 15 gaps  49.8 s
    #
    # So: skip bridging when the selected wire is already closed — UNLESS
    # that closed loop is implausibly small (Bug H-2).  A closed loop is not
    # automatically the main parting line: on Part3 the pre-bridge selection
    # was a closed 47-edge loop covering only 18% of the part's projected
    # extent — a real closed loop, just the wrong one (its true silhouette is
    # fragmented across 22 components with no single one covering it). Gate
    # the fast path on coverage, not just closedness, and when we do bridge,
    # keep the result only if it actually improves on what we had.
    from backend.config import settings as _bridge_cfg_s
    _min_coverage = _bridge_cfg_s.dfm.parting_line.min_silhouette_coverage_ratio
    _part_extent_area = _part_projected_bbox_area(part, direction)
    _cov_u_axis, _cov_v_axis = _projection_basis(direction)

    def _coverage_ratio(points: list[Vec3]) -> float:
        if _part_extent_area <= 0.0 or len(points) < 3:
            return 0.0
        us = [dot3(p, _cov_u_axis) for p in points]
        vs = [dot3(p, _cov_v_axis) for p in points]
        return ((max(us) - min(us)) * (max(vs) - min(vs))) / _part_extent_area

    original_coverage = _coverage_ratio(selected_wire.points)

    bridge_warnings: list[str] = []
    bridging_status = "disabled" if not bridge_components else "not_needed"
    if bridge_components and len(components) > 1 and not _NX_AVAILABLE:
        bridging_status = "unavailable"
    if bridge_components and len(components) > 1 and _NX_AVAILABLE:
        if selected_wire.is_closed and original_coverage >= _min_coverage:
            # Healthy fast path — deliberately NOT a warning, so it does not
            # penalise the readiness score. Reported via `bridging_status`.
            bridging_status = "not_needed"
        else:
            undercut_ids_for_bridge: set[int] = set()
            if undercut_context is not None and hasattr(undercut_context, "undercut_face_ids"):
                undercut_ids_for_bridge = set(undercut_context.undercut_face_ids or [])
            bridged_components, bridged_points, attempt_warnings = _bridge_disconnected_components(
                components,
                component_points,
                edges_by_id,
                candidate_by_id,
                point_tolerance=point_tolerance,
                undercut_face_ids=undercut_ids_for_bridge,
                bridge_penalty_factor=bridge_penalty_factor,
                boundary_bridge_factor=boundary_bridge_factor,
                part_extent_area=_part_extent_area,
                projection_basis=(_cov_u_axis, _cov_v_axis),
                min_coverage_ratio=_min_coverage,
            )
            bridged_wires, bridged_selected = _build_and_select(bridged_components)
            bridged_coverage = _coverage_ratio(bridged_selected.points)

            # Accept the bridged result only if it is genuinely better:
            # closing the loop (when it wasn't) or materially improving
            # coverage (when it already was, but too small) is the win
            # condition; otherwise fall back to the higher-quality wire
            # rather than blindly taking the merge.
            improved = bridged_selected.is_closed and (
                not selected_wire.is_closed
                or bridged_coverage > original_coverage + 0.05
            )
            not_worse = (
                bridged_selected.quality_assessment.score
                >= selected_wire.quality_assessment.score
                and bridged_coverage >= original_coverage - 0.02
            )
            if improved or not_worse:
                components = bridged_components
                component_points = bridged_points
                component_wires = bridged_wires
                selected_wire = bridged_selected
                bridge_warnings = attempt_warnings
                bridging_status = "applied"
            else:
                bridging_status = "discarded_not_an_improvement"
                closure_note = (
                    "closed the loop but did not improve coverage or quality enough"
                    if bridged_selected.is_closed
                    else "did not close the loop"
                )
                bridge_warnings = attempt_warnings + [
                    "Component bridging discarded: the bridged wire scored "
                    f"{bridged_selected.quality_assessment.score:.2f} vs "
                    f"{selected_wire.quality_assessment.score:.2f} for the "
                    f"unbridged selection ({closure_note}, "
                    f"coverage {bridged_coverage * 100:.1f}% vs {original_coverage * 100:.1f}%). "
                    "Original selection retained."
                ]
    selected_component_id = selected_wire.component_id
    selected_edge_ids = selected_wire.ordered_edge_ids
    wire_points = selected_wire.points
    if not wire_points and selected_component_id is not None:
        wire_points = component_points.get(selected_component_id, [])

    if refine:
        refinement = _refine_selected_wire(
            selected_wire,
            components,
            edges_by_id,
            candidate_by_id,
            direction,
            undercut_context=undercut_context,
            point_tolerance=point_tolerance,
            smoothing_iterations=smoothing_iterations,
            display_resample_min_points=display_resample_min_points,
            max_refined_display_points=max_refined_display_points,
        )
    else:
        projection = _wire_projection(
            selected_wire.points,
            direction,
            is_closed=selected_wire.is_closed,
        )
        refinement = PartingLineRefinement(
            status="disabled",
            method="Parting-line refinement disabled by caller.",
            refined_edge_ids=list(selected_wire.ordered_edge_ids),
            removed_edge_ids=[],
            raw_points=list(selected_wire.points),
            refined_points=list(selected_wire.points),
            smoothing_iterations=0,
            confidence=0.0,
            quality="disabled",
            projection=projection,
            display_metrics=_parting_display_metrics(
                raw_points=list(selected_wire.points),
                resampled_points=list(selected_wire.points),
                refined_points=list(selected_wire.points),
                is_closed=selected_wire.is_closed,
                requested_smoothing_iterations=0,
                applied_smoothing_iterations=0,
                max_refined_display_points=max_refined_display_points,
            ),
            graph_cleanup=PartingLineGraphCleanup.not_run("Parting-line refinement disabled by caller."),
            warnings=[],
        )

    refined_conflict_wire = _wire_for_refined_conflict(
        selected_wire,
        refinement,
        point_tolerance=point_tolerance,
    )
    refined_undercut_conflict = _wire_undercut_conflict(
        refined_conflict_wire,
        part,
        edges_by_id,
        direction,
        undercut_context,
    )
    effective_selected_wire = replace(
        selected_wire,
        undercut_conflict=refined_undercut_conflict,
    )

    # Milestone 1.8: assess and attempt loop closure on the refined wire.
    undercut_ids_for_closure: set[int] = set()
    if undercut_context is not None and hasattr(undercut_context, "undercut_face_ids"):
        undercut_ids_for_closure = set(undercut_context.undercut_face_ids or [])
    refined_pts = refinement.refined_points if refinement.refined_points else list(wire_points)
    (
        closure_guaranteed,
        closure_error_mm,
        closed_pts,
        closure_bridge_edge_count,
        closure_warnings,
    ) = _attempt_loop_closure(
        refined_pts,
        is_closed=selected_wire.is_closed,
        edges_by_id=edges_by_id,
        candidate_by_id=candidate_by_id,
        point_tolerance=point_tolerance,
        undercut_face_ids=undercut_ids_for_closure,
        bridge_penalty_factor=bridge_penalty_factor,
        boundary_bridge_factor=boundary_bridge_factor,
        max_closure_error_mm=max_closure_error_mm,
    )

    # The spliced curve is the authoritative one from here on: the parting
    # surface, the API payload and the UI overlay must all see the CLOSED
    # points, not the original open ones.  Rebuilding `refinement` keeps
    # `refinement.refined_points` (what `main.py` serialises for the viewer)
    # consistent with what the surface was actually built from.
    if closure_bridge_edge_count > 0 and closed_pts != refined_pts:
        refined_pts = closed_pts
        if refinement.refined_points:
            refinement = replace(refinement, refined_points=closed_pts)
    else:
        refined_pts = closed_pts

    # Milestone 1.9: build a parting surface if the loop is closed and OCC is available.
    from backend.config import settings as _cfg_s
    _ps_cfg = _cfg_s.dfm.parting_surface
    bbox = part.bounding_box
    bbox_diagonal = (
        (bbox.xmax - bbox.xmin) ** 2
        + (bbox.ymax - bbox.ymin) ** 2
        + (bbox.zmax - bbox.zmin) ** 2
    ) ** 0.5 if bbox is not None else 100.0
    if closure_guaranteed and refined_pts:
        parting_surface = _build_parting_surface(
            refined_pts,
            bbox_diagonal,
            pull_direction=direction,
            planar_tolerance_mm=_ps_cfg.planar_tolerance_mm,
            planar_pull_alignment_min=_ps_cfg.planar_pull_alignment_min,
            extension_factor=_ps_cfg.extension_factor,
            filling_max_degree=_ps_cfg.filling_max_degree,
            filling_tolerance_mm=_ps_cfg.filling_tolerance_mm,
            filling_max_constraint_edges=_ps_cfg.filling_max_constraint_edges,
        )
    else:
        parting_surface = PartingSurfaceResult(
            status="not_attempted",
            strategy="none",
            failure_reason=(
                "Parting surface skipped: loop closure not guaranteed."
                if not closure_guaranteed
                else "Parting surface skipped: no loop points available."
            ),
        )

    warnings: list[str] = list(bridge_warnings)  # prepend any bridge status messages
    warnings.extend(closure_warnings)
    if parting_surface.status == "failed":
        warnings.append(f"Parting surface generation failed: {parting_surface.failure_reason}")
    if not part.edges:
        warnings.append("Part has no extracted edges; cannot detect parting candidates.")
    if not selected_edge_ids:
        warnings.append("No silhouette or parting edge candidates were detected.")
    if selected_wire.branch_point_count:
        warnings.append(
            "Selected parting candidate component is branched; graph-cleaned result should be reviewed."
        )
    if selected_wire.gap_count:
        warnings.append(
            "Selected parting wire contains disconnected gaps; graph-cleaned result should be reviewed."
        )
    if selected_wire.skipped_edge_ids:
        warnings.append(
            "Some selected component edges could not be ordered because endpoint data is unavailable."
        )
    if refined_undercut_conflict.checked and refined_undercut_conflict.conflict_score:
        warnings.append(
            "Refined parting-line path has undercut conflict risk; review the conflict summary."
        )
    if (
        selected_wire.undercut_conflict.checked
        and selected_wire.undercut_conflict.conflict_score
        and refined_undercut_conflict.checked
        and refined_undercut_conflict.conflict_score < selected_wire.undercut_conflict.conflict_score
    ):
        warnings.append(
            "Graph cleanup reduced undercut-conflict risk versus the raw selected wire."
        )
    warnings.extend(refinement.warnings)

    # Bug H guard: a main parting line wraps the outer silhouette.  If the
    # selected loop's projected extent is a small fraction of the part's own,
    # the engine picked a local feature loop (hole rim, boss) and every
    # downstream result — surface, core/cavity split, export — is built on the
    # wrong curve.  Rather than fail silently, measure it and say so.
    silhouette_coverage_ratio = 0.0
    _part_extent_area = _part_projected_bbox_area(part, pull_direction)
    _loop_points = refinement.refined_points or wire_points
    if _part_extent_area > 0.0 and len(_loop_points) >= 3:
        _u_axis, _v_axis = _projection_basis(pull_direction)
        _us = [dot3(p, _u_axis) for p in _loop_points]
        _vs = [dot3(p, _v_axis) for p in _loop_points]
        _loop_area = (max(_us) - min(_us)) * (max(_vs) - min(_vs))
        silhouette_coverage_ratio = _loop_area / _part_extent_area
        min_coverage = _cfg_s.dfm.parting_line.min_silhouette_coverage_ratio
        if silhouette_coverage_ratio < min_coverage:
            warnings.append(
                f"Selected parting loop spans only {silhouette_coverage_ratio * 100:.1f}% of the "
                f"part's projected extent (expected at least {min_coverage * 100:.0f}%); it is "
                f"likely a local feature loop rather than the main parting line. "
                f"The silhouette may be fragmented across {len(components)} components that "
                f"could not be assembled into one loop."
            )

    readiness = _parting_line_readiness(effective_selected_wire, refinement, warnings)
    diagnostic_gate = _parting_line_diagnostic_gate(
        readiness,
        effective_selected_wire,
        refinement,
        warnings,
    )
    diagnostics = _parting_line_diagnostics(
        candidates,
        effective_selected_wire,
        refinement,
        readiness,
        warnings,
    )

    if mutate:
        selected_set = set(selected_edge_ids)
        for candidate in candidates:
            edge = edges_by_id.get(candidate.edge_id)
            if edge is None:
                continue
            edge.is_silhouette = candidate.kind == "silhouette"
            edge.is_parting_edge = edge.edge_id in selected_set
        part.parting_edge_ids = list(selected_edge_ids)
        part.parting_wire_points = list(wire_points)

    return PartingLineResult(
        pull_direction=direction,
        method=(
            "Nee-style adjacent-normal silhouette detection with projection-aware "
            "component selection, Hou-inspired graph cleanup, component bridging "
            "(Milestone 1.7), and loop-closure guarantee (Milestone 1.8); "
            "full Hou global optimization not yet applied"
        ),
        candidates=candidates,
        components=components,
        component_wires=component_wires,
        selected_component_id=selected_component_id,
        selected_edge_ids=selected_edge_ids,
        wire_points=wire_points,
        selected_wire=selected_wire,
        refinement=refinement,
        refined_undercut_conflict=refined_undercut_conflict,
        readiness=readiness,
        diagnostic_gate=diagnostic_gate,
        diagnostics=diagnostics,
        warnings=warnings,
        closure_error_mm=closure_error_mm,
        closure_guaranteed=closure_guaranteed,
        closure_bridge_edge_count=closure_bridge_edge_count,
        bridging_status=bridging_status,
        silhouette_coverage_ratio=silhouette_coverage_ratio,
        parting_surface=parting_surface,
    )
