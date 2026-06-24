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
from typing import Literal

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
    except ImportError:
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
    if not ordered_edge_ids:
        return "empty"
    if skipped_edge_ids or gap_count:
        return "partial"
    if branch_point_count:
        return "branched"
    if is_closed:
        return "closed_loop"
    return "open_chain"


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
        if keys is None or (same_endpoint_key and is_single_edge_component):
            sampled_points = _sample_closed_edge_points(edge)
            if sampled_points and is_single_edge_component:
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
            if same_endpoint_key:
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

    return (
        projection_rank,
        wire.quality_assessment.score,
        -wire.undercut_conflict.conflict_score,
        quality_rank,
        wire.projection.abs_area_mm2,
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
    point_to_edges: dict[tuple[int, int, int], set[int]] = {}
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
        point_to_edges.setdefault(start_key, set()).add(edge_id)
        point_to_edges.setdefault(end_key, set()).add(edge_id)
        if edge.start_vertex is not None:
            point_coords.setdefault(start_key, edge.start_vertex)
        if edge.end_vertex is not None:
            point_coords.setdefault(end_key, edge.end_vertex)

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
        connected = point_to_edges.get(point_key, set())
        if not connected:
            return (0, 0.0, 0.0, 0)
        best_edge = max(connected, key=edge_weight)
        edge_score, edge_length, neg_edge_id = edge_weight(best_edge)
        is_open_endpoint = 1 if len(connected) == 1 else 0
        return (is_open_endpoint, edge_score, edge_length, neg_edge_id)

    open_points = [key for key, edge_ids in point_to_edges.items() if len(edge_ids) == 1]
    start_points = sorted(open_points or list(point_to_edges), key=start_weight, reverse=True)
    search_edge_limit = 22
    max_search_states = 75_000
    strategy = "bounded-dfs"

    best_path_edges: list[int] = []
    best_path_keys: list[tuple[int, int, int]] = []
    best_is_closed = False
    best_key: tuple[float, int, int, int, int] | None = None

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

    if len(endpoint_keys_by_edge) <= search_edge_limit:
        state_count = 0

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
                    is_closed=len(path_keys) > 2 and path_keys[-1] == start_key,
                )

            available = sorted(
                [
                    edge_id
                    for edge_id in point_to_edges.get(current_key, set())
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
                closes_loop = next_key == start_key and len(next_edges) >= 3
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

        if state_count > max_search_states:
            warnings.append(
                "Refinement path search hit the state limit; best path found so far was retained."
            )
    else:
        state_count = 0
        strategy = "greedy-fallback"
        warnings.append(
            "Refinement candidate graph is large; bounded search skipped and greedy fallback used."
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
                for edge_id in point_to_edges.get(current_key, set())
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
        branch_point_count=sum(1 for edge_ids in point_to_edges.values() if len(edge_ids) > 2),
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

    candidate_by_id = {candidate.edge_id: candidate for candidate in candidates}
    component_wires = [
        _build_ordered_wire(
            component,
            edges_by_id,
            candidate_by_id,
            point_tolerance=point_tolerance,
            pull_direction=direction,
        )
        for component in components
    ]
    component_wires = _apply_wire_assessments(
        component_wires,
        components,
        part,
        edges_by_id,
        direction,
        undercut_context,
    )
    selected_wire = _select_projected_wire(component_wires, components)
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

    warnings: list[str] = []
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
            "component selection and Hou-inspired graph cleanup; full Hou global "
            "optimization not yet applied"
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
    )
