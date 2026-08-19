"""
backend/geometry/undercut_detector.py
-------------------------------------
Module 4, first production pass: undercut/accessibility recognition.

Scope of this implementation
----------------------------
This is a STEP-native, face-level undercut recognizer.  It first builds a fast
normal/draft/adjacency pre-classification and can optionally refine likely
undercut faces with an OCC swept-face Boolean interference check:

  1. Pull-direction draft angle.
  2. Signed normal side (core/cavity/parting).
  3. Face adjacency grouping.
  4. Simple depth proxy from centroid projection along the pull direction.
  5. Optional swept-face intersection volume proxy.

This gives the optimizer and UI a real undercut/accessibility result object
today.  The Boolean step is still a conservative first implementation of Bassi's
swept-surface accessibility idea, not yet the fully regularized production
algorithm with volumetric decomposition.

Paper alignment
---------------
* Bassi et al. (2010): uses n·d surface accessibility as the fast filter before
  expensive sweep/Boolean operations.
* Sangolli et al. (2021): groups recognized undercut faces into feature-level
  outputs with location, type, depth proxy, and release direction.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from backend.config import settings
from backend.geometry.draft_analyzer import (
    DraftAnalysisResult,
    FaceDirectionalMetrics,
    analyze_draft,
)
from backend.models.geometry_models import FaceData, PartGeometry, Vec3, dot3, mag3, normalize3

try:
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.BRepBndLib import brepbndlib
    from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCC.Core.BRepClass3d import BRepClass3d_SolidClassifier
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core.BRepIntCurveSurface import BRepIntCurveSurface_Inter
    from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCC.Core.BRepTools import breptools
    from OCC.Core.GeomLProp import GeomLProp_SLProps
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.TopAbs import TopAbs_EDGE, TopAbs_IN, TopAbs_VERTEX
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopoDS import TopoDS_Face, TopoDS_Shape, topods
    from OCC.Core.gp import gp_Dir, gp_Lin, gp_Pnt, gp_Trsf, gp_Vec

    _OCC_BOOLEAN_AVAILABLE = True
except ImportError:
    _OCC_BOOLEAN_AVAILABLE = False


@dataclass(frozen=True)
class BooleanShapeAnalysis:
    available: bool = False
    vertex_count: int = 0
    edge_count: int = 0
    bbox_min: Vec3 | None = None
    bbox_max: Vec3 | None = None
    bbox_center: Vec3 | None = None
    bbox_dimensions: Vec3 | None = None
    center_of_mass: Vec3 | None = None
    volume_mm3: float = 0.0
    method: str = "not-available"
    failure_reason: str = ""

    def to_dict(self) -> dict:
        def rounded_vec(value: Vec3 | None) -> list[float] | None:
            if value is None:
                return None
            return [round(component, 4) for component in value]

        return {
            "available": self.available,
            "vertex_count": self.vertex_count,
            "edge_count": self.edge_count,
            "bbox_min": rounded_vec(self.bbox_min),
            "bbox_max": rounded_vec(self.bbox_max),
            "bbox_center": rounded_vec(self.bbox_center),
            "bbox_dimensions": rounded_vec(self.bbox_dimensions),
            "center_of_mass": rounded_vec(self.center_of_mass),
            "volume_mm3": round(self.volume_mm3, 6),
            "method": self.method,
            "failure_reason": self.failure_reason,
        }


@dataclass(frozen=True)
class BooleanRegionGeometry:
    available: bool = False
    shape_count: int = 0
    source_face_ids: list[int] = field(default_factory=list)
    vertex_count: int = 0
    edge_count: int = 0
    bbox_min: Vec3 | None = None
    bbox_max: Vec3 | None = None
    bbox_center: Vec3 | None = None
    bbox_dimensions: Vec3 | None = None
    center_of_mass: Vec3 | None = None
    volume_mm3: float = 0.0
    analyses: list[BooleanShapeAnalysis] = field(default_factory=list)
    failure_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        def rounded_vec(value: Vec3 | None) -> list[float] | None:
            if value is None:
                return None
            return [round(component, 4) for component in value]

        return {
            "available": self.available,
            "shape_count": self.shape_count,
            "source_face_ids": self.source_face_ids,
            "vertex_count": self.vertex_count,
            "edge_count": self.edge_count,
            "bbox_min": rounded_vec(self.bbox_min),
            "bbox_max": rounded_vec(self.bbox_max),
            "bbox_center": rounded_vec(self.bbox_center),
            "bbox_dimensions": rounded_vec(self.bbox_dimensions),
            "center_of_mass": rounded_vec(self.center_of_mass),
            "volume_mm3": round(self.volume_mm3, 6),
            "failure_reasons": self.failure_reasons,
            "analyses": [analysis.to_dict() for analysis in self.analyses],
        }


@dataclass(frozen=True)
class GeometryReleaseDepthEstimate:
    release_direction: Vec3
    depth_mm: float
    release_direction_method: str
    depth_method: str
    factors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BooleanDepthEstimate:
    depth_mm: float
    method: str
    reference_depth_mm: float
    span_depth_mm: float
    evidence: dict = field(default_factory=dict)
    factors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "depth_mm": round(self.depth_mm, 6),
            "method": self.method,
            "reference_depth_mm": round(self.reference_depth_mm, 6),
            "span_depth_mm": round(self.span_depth_mm, 6),
            "evidence": self.evidence,
            "factors": self.factors,
        }


@dataclass(frozen=True)
class GeometricFeatureClassification:
    feature_type: str
    confidence: float
    confidence_label: str
    method: str
    factors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ActionConfidenceTerm:
    code: str
    impact: float
    explanation: str

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "impact": round(self.impact, 3),
            "explanation": self.explanation,
        }


@dataclass(frozen=True)
class ActionConfidenceBreakdown:
    base_score: float
    final_score: float
    label: str
    terms: list[ActionConfidenceTerm] = field(default_factory=list)

    @property
    def positive_terms(self) -> list[ActionConfidenceTerm]:
        return [term for term in self.terms if term.impact > 0.0]

    @property
    def negative_terms(self) -> list[ActionConfidenceTerm]:
        return [term for term in self.terms if term.impact < 0.0]

    @property
    def factors(self) -> list[str]:
        return [term.explanation for term in self.terms]

    def summary(self) -> str:
        positives = sorted(self.positive_terms, key=lambda term: abs(term.impact), reverse=True)
        negatives = sorted(self.negative_terms, key=lambda term: abs(term.impact), reverse=True)
        positive_text = ", ".join(term.explanation for term in positives[:3])
        negative_text = ", ".join(term.explanation for term in negatives[:2])

        if positive_text and negative_text:
            return (
                f"{self.label.title()} confidence: {positive_text}; reduced by "
                f"{negative_text}."
            )
        if positive_text:
            return f"{self.label.title()} confidence: {positive_text}."
        if negative_text:
            return f"{self.label.title()} confidence: limited by {negative_text}."
        return f"{self.label.title()} confidence: base rule evidence only."

    def to_dict(self) -> dict:
        return {
            "base_score": round(self.base_score, 3),
            "final_score": round(self.final_score, 3),
            "label": self.label,
            "terms": [term.to_dict() for term in self.terms],
            "positive_terms": [term.to_dict() for term in self.positive_terms],
            "negative_terms": [term.to_dict() for term in self.negative_terms],
            "summary": self.summary(),
        }


@dataclass(frozen=True)
class FeatureGroupingResult:
    groups: list[list[int]]
    method: str
    factors: list[str] = field(default_factory=list)
    proximity_link_count: int = 0
    overlap_pair_count: int = 0
    nested_pair_count: int = 0
    interaction_pair_count: int = 0


@dataclass(frozen=True)
class BooleanAttemptInfo:
    attempt_index: int
    offset_mm: float
    fuzzy_value: float
    status: str
    error: str = ""
    elapsed_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "attempt_index": self.attempt_index,
            "offset_mm": round(self.offset_mm, 8),
            "fuzzy_value": round(self.fuzzy_value, 8),
            "status": self.status,
            "error": self.error,
            "elapsed_s": round(self.elapsed_s, 6),
        }


@dataclass(frozen=True)
class BooleanInterferenceMetrics:
    volume_mm3: float
    depth_mm: float
    elapsed_s: float = 0.0
    attempt_count: int = 1
    offset_mm: float = 0.0
    fuzzy_value: float = 0.0
    depth_method: str = "unknown"
    reference_depth_mm: float = 0.0
    span_depth_mm: float = 0.0
    intersection_shape: object | None = field(default=None, repr=False, compare=False)
    shape_analysis: BooleanShapeAnalysis = field(default_factory=BooleanShapeAnalysis)
    status: str = "ok"
    warnings: list[str] = field(default_factory=list)
    attempts: list[BooleanAttemptInfo] = field(default_factory=list)
    depth_evidence: dict = field(default_factory=dict)
    depth_factors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BooleanFailureInfo:
    reason: str
    failure_class: str = "unknown"
    attempt_count: int = 0
    last_error: str = ""
    attempts: list[BooleanAttemptInfo] = field(default_factory=list)
    fallback_action: str = "proxy-retained"

    def to_dict(self) -> dict:
        return {
            "reason": self.reason,
            "failure_class": self.failure_class,
            "attempt_count": self.attempt_count,
            "last_error": self.last_error,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "fallback_action": self.fallback_action,
        }


class BooleanOperationError(RuntimeError):
    """Structured wrapper for OCC Boolean failures after all retry attempts."""

    def __init__(self, info: BooleanFailureInfo):
        self.info = info
        super().__init__(info.last_error or info.reason)


@dataclass(frozen=True)
class BooleanPerformanceSummary:
    checked_count: int
    successful_count: int
    failed_count: int
    skipped_count: int
    cache_hits: int
    cache_misses: int
    elapsed_s: float
    avg_success_elapsed_s: float
    max_success_elapsed_s: float
    total_success_attempts: int
    total_failed_attempts: int
    slow_faces: list[dict] = field(default_factory=list)

    @property
    def cache_hit_rate(self) -> float:
        total = self.cache_hits + self.cache_misses
        if total <= 0:
            return 0.0
        return self.cache_hits / total

    @property
    def avg_attempts_per_success(self) -> float:
        if self.successful_count <= 0:
            return 0.0
        return self.total_success_attempts / self.successful_count

    def to_dict(self) -> dict:
        return {
            "checked_count": self.checked_count,
            "successful_count": self.successful_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_rate": round(self.cache_hit_rate, 4),
            "elapsed_s": round(self.elapsed_s, 6),
            "avg_success_elapsed_s": round(self.avg_success_elapsed_s, 6),
            "max_success_elapsed_s": round(self.max_success_elapsed_s, 6),
            "total_success_attempts": self.total_success_attempts,
            "total_failed_attempts": self.total_failed_attempts,
            "avg_attempts_per_success": round(self.avg_attempts_per_success, 4),
            "slow_faces": self.slow_faces,
        }


@dataclass(frozen=True)
class BooleanReliabilitySummary:
    enabled: bool
    reliability_score: float
    reliability_label: str
    reliability_level: str
    checked_count: int
    confirmed_count: int
    failed_count: int
    skipped_count: int
    proxy_retained_face_count: int
    proxy_retained_failed_count: int
    proxy_retained_skipped_count: int
    successful_operation_ratio: float
    confirmed_ratio: float
    failure_ratio: float
    fallback_ratio: float
    failure_class_counts: dict[str, int] = field(default_factory=dict)
    skip_reason_counts: dict[str, int] = field(default_factory=dict)
    summary: str = ""
    recommended_action: str = ""

    @property
    def has_proxy_retained_evidence(self) -> bool:
        return self.proxy_retained_face_count > 0

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "reliability_score": round(self.reliability_score, 3),
            "reliability_label": self.reliability_label,
            "reliability_level": self.reliability_level,
            "checked_count": self.checked_count,
            "confirmed_count": self.confirmed_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "proxy_retained_face_count": self.proxy_retained_face_count,
            "proxy_retained_failed_count": self.proxy_retained_failed_count,
            "proxy_retained_skipped_count": self.proxy_retained_skipped_count,
            "successful_operation_ratio": round(self.successful_operation_ratio, 4),
            "confirmed_ratio": round(self.confirmed_ratio, 4),
            "failure_ratio": round(self.failure_ratio, 4),
            "fallback_ratio": round(self.fallback_ratio, 4),
            "failure_class_counts": dict(sorted(self.failure_class_counts.items())),
            "skip_reason_counts": dict(sorted(self.skip_reason_counts.items())),
            "has_proxy_retained_evidence": self.has_proxy_retained_evidence,
            "summary": self.summary,
            "recommended_action": self.recommended_action,
        }


@dataclass(frozen=True)
class MoldActionRecommendation:
    side_action_candidate: bool
    action: str
    reason: str
    pull_alignment: float
    confidence: float
    confidence_label: str
    confidence_factors: list[str]
    confidence_breakdown: dict = field(default_factory=dict)
    explanation: str = ""


@dataclass(frozen=True)
class UndercutTypeClassification:
    undercut_type: str
    method: str
    score: float
    factors: list[str]


BooleanVolumeCache = dict[tuple[int, int, int, int], Optional[BooleanInterferenceMetrics]]


@dataclass(frozen=True)
class UndercutFeature:
    """
    Feature-level undercut representation (Sangolli 2021 adaptation).

    Depth: two metrics, two different jobs (TEAM DECISION, 2026-07-27)
    -----------------------------------------------------------------
    The project intentionally maintains two depth numbers with *different
    objectives*.  This is a deliberate separation of concerns, not an
    inconsistency to be "fixed":

    ``BooleanInterferenceMetrics.depth_mm``  (per-face)  -> PRECISION
        Highest-confidence interference depth for an individual face,
        intended for precise engineering measurement.  Prefers exact
        Boolean-vertex evidence, falling back to bbox/volume-area only when
        exact evidence is unavailable.

    ``UndercutFeature.depth_proxy_mm``  (per-feature)  -> CONSERVATIVE SEVERITY
        Conservative UPPER-BOUND estimate of overall undercut feature depth,
        intended for severity ranking and DfM decision support.  Takes the
        *maximum* across available estimators (Boolean depth, centroid
        projection, bounding-box span).  This value MAY intentionally exceed
        the precise Boolean depth, to reduce the risk of under-reporting a
        manufacturability issue.

    Rationale: in DfM workflows a false positive (flagging a feature that
    turns out fine) is far cheaper than a false negative (missing an
    undercut, producing a mold that will not release).  Over-estimating
    depth costs a conservative tooling allowance; under-estimating it costs
    a stuck part at demold.

    DO NOT resurrect the reverted change that made ``depth_proxy_mm`` prefer
    precision (attempted and reverted during Milestone 1.3 — it broke three
    tests that assert this behaviour deliberately).  See
    ``docs/ARCHITECTURE_ROADMAP.md`` Milestone 1.3 note and ``TODO.md``
    for the full decision record.

    Use ``boolean_depth_proxy_mm`` when you specifically need the
    Boolean-geometry-grounded depth estimate for a feature.
    """

    feature_id: int
    face_ids: list[int]
    undercut_type: str
    severity: str
    evidence_source: str
    type_classification_method: str
    type_classification_score: float
    type_classification_factors: list[str]
    release_direction: Vec3
    location: Vec3
    depth_proxy_mm: float
    total_area_mm2: float
    min_draft_angle_deg: float
    grouping_method: str = "face-adjacency"
    grouping_factors: list[str] = field(default_factory=list)
    release_direction_method: str = "normal-transverse"
    release_direction_factors: list[str] = field(default_factory=list)
    depth_estimation_method: str = "projection-or-boolean-depth"
    geometric_feature_type: str = "unclassified"
    geometric_feature_confidence: float = 0.0
    geometric_feature_confidence_label: str = "unknown"
    geometric_feature_method: str = "not-run"
    geometric_feature_factors: list[str] = field(default_factory=list)
    boolean_depth_proxy_mm: float = 0.0
    boolean_depth_method: str = "none"
    boolean_depth_evidence: dict = field(default_factory=dict)
    boolean_depth_factors: list[str] = field(default_factory=list)
    interference_volume_mm3: float = 0.0
    interaction_type: str = "none"
    interaction_factors: list[str] = field(default_factory=list)
    boolean_confirmed_face_ids: list[int] = field(default_factory=list)
    boolean_failed_face_ids: list[int] = field(default_factory=list)
    boolean_skipped_face_ids: list[int] = field(default_factory=list)
    # D-042 fix (2026-08-16): faces in this feature that are geometrically
    # tangent to the pull direction -- the sweep test was never attempted
    # for them, so they contribute no positive OR negative evidence to this
    # feature's confirmation status.
    boolean_not_applicable_face_ids: list[int] = field(default_factory=list)
    boolean_intersection_face_ids: list[int] = field(default_factory=list)
    boolean_intersection_shapes: list[object] = field(
        default_factory=list,
        repr=False,
        compare=False,
    )
    boolean_region_geometry: BooleanRegionGeometry = field(default_factory=BooleanRegionGeometry)
    side_action_candidate: bool = True
    recommended_mold_action: str = "side-action-review"
    action_reason: str = ""
    pull_alignment: float = 0.0
    action_confidence: float = 0.0
    action_confidence_label: str = "unknown"
    action_confidence_factors: list[str] = field(default_factory=list)
    action_confidence_breakdown: dict = field(default_factory=dict)
    action_explanation: str = ""

    @property
    def boolean_intersection_shape(self) -> object | None:
        """Return the primary in-memory Boolean intersection shape, if present."""
        return self.boolean_intersection_shapes[0] if self.boolean_intersection_shapes else None

    @property
    def is_major_feature(self) -> bool:
        """Feature-level risk flag used by API/UI summaries and reports."""
        return (
            self.severity == "critical"
            or self.recommended_mold_action == "side-action"
            or (
                self.action_confidence_label == "high"
                and self.depth_proxy_mm >= 2.0
            )
        )

    def to_dict(self) -> dict:
        return {
            "feature_id": self.feature_id,
            "face_ids": self.face_ids,
            "face_count": len(self.face_ids),
            "is_major_feature": self.is_major_feature,
            "undercut_type": self.undercut_type,
            "type_classification_method": self.type_classification_method,
            "type_classification_score": round(self.type_classification_score, 3),
            "type_classification_factors": self.type_classification_factors,
            "severity": self.severity,
            "evidence_source": self.evidence_source,
            "grouping_method": self.grouping_method,
            "grouping_factors": self.grouping_factors,
            "side_action_candidate": self.side_action_candidate,
            "recommended_mold_action": self.recommended_mold_action,
            "action_reason": self.action_reason,
            "pull_alignment": round(self.pull_alignment, 6),
            "action_confidence": round(self.action_confidence, 3),
            "action_confidence_label": self.action_confidence_label,
            "action_confidence_factors": self.action_confidence_factors,
            "action_confidence_breakdown": self.action_confidence_breakdown,
            "action_explanation": self.action_explanation,
            "release_direction": [round(v, 6) for v in self.release_direction],
            "release_direction_method": self.release_direction_method,
            "release_direction_factors": self.release_direction_factors,
            "location": [round(v, 4) for v in self.location],
            "depth_proxy_mm": round(self.depth_proxy_mm, 4),
            "depth_estimation_method": self.depth_estimation_method,
            "geometric_feature_type": self.geometric_feature_type,
            "geometric_feature_confidence": round(self.geometric_feature_confidence, 3),
            "geometric_feature_confidence_label": self.geometric_feature_confidence_label,
            "geometric_feature_method": self.geometric_feature_method,
            "geometric_feature_factors": self.geometric_feature_factors,
            "boolean_depth_proxy_mm": round(self.boolean_depth_proxy_mm, 4),
            "boolean_depth_method": self.boolean_depth_method,
            "boolean_depth_evidence": self.boolean_depth_evidence,
            "boolean_depth_factors": self.boolean_depth_factors,
            "interference_volume_mm3": round(self.interference_volume_mm3, 6),
            "interaction_type": self.interaction_type,
            "interaction_factors": self.interaction_factors,
            "total_area_mm2": round(self.total_area_mm2, 3),
            "min_draft_angle_deg": round(self.min_draft_angle_deg, 3),
            "boolean_confirmed_face_ids": self.boolean_confirmed_face_ids,
            "boolean_failed_face_ids": self.boolean_failed_face_ids,
            "boolean_skipped_face_ids": self.boolean_skipped_face_ids,
            "boolean_not_applicable_face_ids": self.boolean_not_applicable_face_ids,
            "boolean_intersection": {
                "available": bool(self.boolean_intersection_shapes),
                "shape_count": len(self.boolean_intersection_shapes),
                "face_ids": self.boolean_intersection_face_ids,
                "geometry": self.boolean_region_geometry.to_dict(),
            },
        }


@dataclass(frozen=True)
class UndercutDetectionResult:
    pull_direction: Vec3
    method: str
    undercut_face_ids: list[int]
    accessible_face_ids: list[int]
    parting_face_ids: list[int]
    skipped_face_ids: list[int]
    convexity_suppressed_face_ids: list[int] = field(default_factory=list)
    features: list[UndercutFeature] = field(default_factory=list)
    undercut_area_mm2: float = 0.0
    total_analysed_area_mm2: float = 0.0
    boolean_refined: bool = False
    boolean_checked_face_ids: list[int] = field(default_factory=list)
    boolean_confirmed_face_ids: list[int] = field(default_factory=list)
    boolean_failed_face_ids: list[int] = field(default_factory=list)
    boolean_failure_reasons: dict[int, str] = field(default_factory=dict)
    boolean_failure_details: dict[int, dict] = field(default_factory=dict)
    boolean_skipped_face_ids: list[int] = field(default_factory=list)
    boolean_skip_reasons: dict[int, str] = field(default_factory=dict)
    interference_volume_mm3: float = 0.0
    boolean_depth_proxy_mm: float = 0.0
    boolean_depth_method: str = "none"
    boolean_cache_hits: int = 0
    boolean_cache_misses: int = 0
    boolean_time_s: float = 0.0
    boolean_performance: BooleanPerformanceSummary | None = None
    boolean_reliability: BooleanReliabilitySummary | None = None
    # Milestone 2: independent accessibility risk (heuristic — NOT proof of undercut)
    # A face is flagged when it is core-side (n·d < -threshold) AND has at
    # least one concave bounding edge.  This is strictly independent from
    # draft: a face with good draft can still be flagged; a face with bad
    # draft but all-convex edges is NOT flagged.  Only Boolean swept-volume
    # validation confirms actual physical obstruction.
    accessibility_risk_face_ids: list[int] = field(default_factory=list)
    accessibility_risk_area_mm2: float = 0.0
    analysis_time_s: float = 0.0
    # D-042 fix (2026-08-15/16, Phase 5A + follow-up): three-bucket evidence
    # semantics. Disjoint by construction and, restricted to the full
    # Boolean-candidate population (draft-proxy faces UNION
    # accessibility-risk faces), exhaustive. `undercut_face_ids` (above) is
    # kept for backward compatibility and remains a conservative union that
    # includes `boolean_not_applicable_face_ids` (still flagged, still
    # uncertain) -- it must never be read as "confirmed."
    #
    # Phase 5A follow-up (2026-08-16): renamed from `proxy_only_face_ids`
    # (had zero external consumers at the time of rename, verified by
    # repo-wide search) because a face can now be a Boolean candidate via
    # accessibility_risk alone, without ever being a draft-proxy candidate
    # -- "proxy_only" would misdescribe such a face. `candidate_sources`
    # records, per processed face, which candidate-generation pass(es)
    # nominated it ("draft_proxy", "accessibility_risk", or both;
    # "all_faces" when boolean_check_all_faces=True bypassed both passes).
    candidate_unconfirmed_face_ids: list[int] = field(default_factory=list)
    candidate_sources: dict[int, list[str]] = field(default_factory=dict)
    boolean_not_applicable_face_ids: list[int] = field(default_factory=list)
    boolean_not_applicable_reasons: dict[int, str] = field(default_factory=dict)
    # D-061 (2026-08-16): faces verified geometrically clear by adaptive
    # ray-based coverage BEFORE any swept-face Boolean was attempted --
    # never Boolean-confirmed, never Boolean-failed (the Boolean was
    # skipped entirely), and explicitly NOT folded into
    # candidate_unconfirmed_face_ids (a Boolean-pipeline field with a
    # different meaning) or the legacy undercut_face_ids union. A
    # positive, bounded-confidence geometric result -- NOT Boolean proof.
    # See RayVerificationResult's docstring for the exact convergence
    # policy (two independent grid densities must both find nothing).
    ray_verified_clear_face_ids: list[int] = field(default_factory=list)
    # O22 (2026-08-17): process-isolation failure semantics. A failed child
    # evaluation (timeout, crash, malformed payload, STEP-load failure) is
    # represented here explicitly -- it is NEVER folded into "clean" or
    # "no undercuts". Default False/"" is byte-identical to pre-O22
    # behavior for every existing in-process call site.
    evaluation_failed: bool = False
    evaluation_error: str = ""

    @property
    def undercut_area_pct(self) -> float:
        if self.total_analysed_area_mm2 <= 0:
            return 0.0
        return 100.0 * self.undercut_area_mm2 / self.total_analysed_area_mm2

    @property
    def has_undercuts(self) -> bool:
        return bool(self.undercut_face_ids)

    @property
    def major_undercut_features_count(self) -> int:
        return sum(1 for feature in self.features if feature.is_major_feature)

    @property
    def has_critical_undercut(self) -> bool:
        return any(feature.severity == "critical" for feature in self.features)

    @property
    def accessibility_risk_area_pct(self) -> float:
        """
        Fraction of total analysed area flagged as accessibility risk (heuristic).

        IMPORTANT: This is a heuristic risk signal (core-side face + concave
        bounding edge), NOT proof of undercut.  Only Boolean swept-volume
        validation can confirm actual physical obstruction.  Do NOT use this
        value as a substitute for ``undercut_area_pct``.
        """
        if self.total_analysed_area_mm2 <= 0:
            return 0.0
        return 100.0 * self.accessibility_risk_area_mm2 / self.total_analysed_area_mm2

    def to_dict(self) -> dict:
        return {
            "pull_direction": [round(v, 6) for v in self.pull_direction],
            "method": self.method,
            "has_undercuts": self.has_undercuts,
            "has_critical_undercut": self.has_critical_undercut,
            "face_counts": {
                "undercut": len(self.undercut_face_ids),
                "accessible": len(self.accessible_face_ids),
                "parting": len(self.parting_face_ids),
                "skipped": len(self.skipped_face_ids),
                "convexity_suppressed": len(self.convexity_suppressed_face_ids),
            },
            "face_ids": {
                "undercut": self.undercut_face_ids,
                "accessible": self.accessible_face_ids,
                "parting": self.parting_face_ids,
                "skipped": self.skipped_face_ids,
                "convexity_suppressed": self.convexity_suppressed_face_ids,
            },
            "area_mm2": {
                "undercut": round(self.undercut_area_mm2, 3),
                "total_analysed": round(self.total_analysed_area_mm2, 3),
            },
            "percentages": {
                "undercut_area_pct": round(self.undercut_area_pct, 3),
            },
            "feature_count": len(self.features),
            "major_undercut_features_count": self.major_undercut_features_count,
            "features": [feature.to_dict() for feature in self.features],
            # D-042 fix + Phase 5A follow-up: the honest evidence summary.
            # Disjoint by construction -- never merge these when consuming
            # this payload. candidate_unconfirmed + boolean_not_applicable
            # are NOT confirmed undercuts; only boolean_confirmed_face_ids
            # is real physical evidence. candidate_sources answers "why was
            # this face sent to Boolean verification" per face.
            "evidence": {
                "candidate_unconfirmed_face_ids": self.candidate_unconfirmed_face_ids,
                "candidate_sources": self.candidate_sources,
                "boolean_confirmed_face_ids": self.boolean_confirmed_face_ids,
                "boolean_not_applicable_face_ids": self.boolean_not_applicable_face_ids,
                "boolean_not_applicable_reasons": self.boolean_not_applicable_reasons,
                "ray_verified_clear_face_ids": self.ray_verified_clear_face_ids,
            },
            "boolean_refinement": {
                "enabled": self.boolean_refined,
                "checked_face_ids": self.boolean_checked_face_ids,
                "confirmed_face_ids": self.boolean_confirmed_face_ids,
                "failed_face_ids": self.boolean_failed_face_ids,
                "failure_reasons": self.boolean_failure_reasons,
                "failure_details": self.boolean_failure_details,
                "skipped_face_ids": self.boolean_skipped_face_ids,
                "skip_reasons": self.boolean_skip_reasons,
                "checked_count": len(self.boolean_checked_face_ids),
                "confirmed_count": len(self.boolean_confirmed_face_ids),
                "failed_count": len(self.boolean_failed_face_ids),
                "skipped_count": len(self.boolean_skipped_face_ids),
                "interference_volume_mm3": round(self.interference_volume_mm3, 6),
                "boolean_depth_proxy_mm": round(self.boolean_depth_proxy_mm, 4),
                "boolean_depth_method": self.boolean_depth_method,
                "cache_hits": self.boolean_cache_hits,
                "cache_misses": self.boolean_cache_misses,
                "time_s": round(self.boolean_time_s, 4),
                "performance": (
                    self.boolean_performance.to_dict()
                    if self.boolean_performance is not None
                    else None
                ),
                "reliability": (
                    self.boolean_reliability.to_dict()
                    if self.boolean_reliability is not None
                    else None
                ),
            },
            "accessibility_risk": {
                "face_ids": self.accessibility_risk_face_ids,
                "face_count": len(self.accessibility_risk_face_ids),
                "area_mm2": round(self.accessibility_risk_area_mm2, 3),
                "area_pct": round(self.accessibility_risk_area_pct, 3),
                "note": (
                    "heuristic risk signal (core-side face + concave bounding "
                    "edge) — NOT proof of undercut; Boolean validation is required"
                ),
            },
            "analysis_time_s": round(self.analysis_time_s, 4),
            "evaluation_failed": self.evaluation_failed,
            "evaluation_error": self.evaluation_error,
        }


def undercut_result_to_plain(result: UndercutDetectionResult) -> dict:
    """
    Serialize an ``UndercutDetectionResult`` to a plain, JSON-safe dict for
    crossing a process boundary (O22 process-isolated undercut detection).

    Explicitly excludes ``UndercutFeature.boolean_intersection_shapes`` --
    the only live-OCC-handle field anywhere in this dataclass tree (verified
    by field-by-field audit, O21 Guard 4). Everything else here is already
    plain scalars/lists/dicts/nested dataclasses with no OCC references.
    """

    def shape_analysis(a: BooleanShapeAnalysis) -> dict:
        return {
            "available": a.available,
            "vertex_count": a.vertex_count,
            "edge_count": a.edge_count,
            "bbox_min": list(a.bbox_min) if a.bbox_min is not None else None,
            "bbox_max": list(a.bbox_max) if a.bbox_max is not None else None,
            "bbox_center": list(a.bbox_center) if a.bbox_center is not None else None,
            "bbox_dimensions": list(a.bbox_dimensions) if a.bbox_dimensions is not None else None,
            "center_of_mass": list(a.center_of_mass) if a.center_of_mass is not None else None,
            "volume_mm3": a.volume_mm3,
            "method": a.method,
            "failure_reason": a.failure_reason,
        }

    def region_geometry(g: BooleanRegionGeometry) -> dict:
        return {
            "available": g.available,
            "shape_count": g.shape_count,
            "source_face_ids": list(g.source_face_ids),
            "vertex_count": g.vertex_count,
            "edge_count": g.edge_count,
            "bbox_min": list(g.bbox_min) if g.bbox_min is not None else None,
            "bbox_max": list(g.bbox_max) if g.bbox_max is not None else None,
            "bbox_center": list(g.bbox_center) if g.bbox_center is not None else None,
            "bbox_dimensions": list(g.bbox_dimensions) if g.bbox_dimensions is not None else None,
            "center_of_mass": list(g.center_of_mass) if g.center_of_mass is not None else None,
            "volume_mm3": g.volume_mm3,
            "analyses": [shape_analysis(a) for a in g.analyses],
            "failure_reasons": list(g.failure_reasons),
        }

    def performance(p: BooleanPerformanceSummary | None) -> dict | None:
        if p is None:
            return None
        return {
            "checked_count": p.checked_count,
            "successful_count": p.successful_count,
            "failed_count": p.failed_count,
            "skipped_count": p.skipped_count,
            "cache_hits": p.cache_hits,
            "cache_misses": p.cache_misses,
            "elapsed_s": p.elapsed_s,
            "avg_success_elapsed_s": p.avg_success_elapsed_s,
            "max_success_elapsed_s": p.max_success_elapsed_s,
            "total_success_attempts": p.total_success_attempts,
            "total_failed_attempts": p.total_failed_attempts,
            "slow_faces": list(p.slow_faces),
        }

    def reliability(r: BooleanReliabilitySummary | None) -> dict | None:
        if r is None:
            return None
        return {
            "enabled": r.enabled,
            "reliability_score": r.reliability_score,
            "reliability_label": r.reliability_label,
            "reliability_level": r.reliability_level,
            "checked_count": r.checked_count,
            "confirmed_count": r.confirmed_count,
            "failed_count": r.failed_count,
            "skipped_count": r.skipped_count,
            "proxy_retained_face_count": r.proxy_retained_face_count,
            "proxy_retained_failed_count": r.proxy_retained_failed_count,
            "proxy_retained_skipped_count": r.proxy_retained_skipped_count,
            "successful_operation_ratio": r.successful_operation_ratio,
            "confirmed_ratio": r.confirmed_ratio,
            "failure_ratio": r.failure_ratio,
            "fallback_ratio": r.fallback_ratio,
            "failure_class_counts": dict(r.failure_class_counts),
            "skip_reason_counts": dict(r.skip_reason_counts),
            "summary": r.summary,
            "recommended_action": r.recommended_action,
        }

    def feature(f: UndercutFeature) -> dict:
        return {
            "feature_id": f.feature_id,
            "face_ids": list(f.face_ids),
            "undercut_type": f.undercut_type,
            "severity": f.severity,
            "evidence_source": f.evidence_source,
            "type_classification_method": f.type_classification_method,
            "type_classification_score": f.type_classification_score,
            "type_classification_factors": list(f.type_classification_factors),
            "release_direction": list(f.release_direction),
            "location": list(f.location),
            "depth_proxy_mm": f.depth_proxy_mm,
            "total_area_mm2": f.total_area_mm2,
            "min_draft_angle_deg": f.min_draft_angle_deg,
            "grouping_method": f.grouping_method,
            "grouping_factors": list(f.grouping_factors),
            "release_direction_method": f.release_direction_method,
            "release_direction_factors": list(f.release_direction_factors),
            "depth_estimation_method": f.depth_estimation_method,
            "geometric_feature_type": f.geometric_feature_type,
            "geometric_feature_confidence": f.geometric_feature_confidence,
            "geometric_feature_confidence_label": f.geometric_feature_confidence_label,
            "geometric_feature_method": f.geometric_feature_method,
            "geometric_feature_factors": list(f.geometric_feature_factors),
            "boolean_depth_proxy_mm": f.boolean_depth_proxy_mm,
            "boolean_depth_method": f.boolean_depth_method,
            "boolean_depth_evidence": dict(f.boolean_depth_evidence),
            "boolean_depth_factors": list(f.boolean_depth_factors),
            "interference_volume_mm3": f.interference_volume_mm3,
            "interaction_type": f.interaction_type,
            "interaction_factors": list(f.interaction_factors),
            "boolean_confirmed_face_ids": list(f.boolean_confirmed_face_ids),
            "boolean_failed_face_ids": list(f.boolean_failed_face_ids),
            "boolean_skipped_face_ids": list(f.boolean_skipped_face_ids),
            "boolean_not_applicable_face_ids": list(f.boolean_not_applicable_face_ids),
            "boolean_intersection_face_ids": list(f.boolean_intersection_face_ids),
            # boolean_intersection_shapes deliberately excluded -- OCC handles.
            "boolean_region_geometry": region_geometry(f.boolean_region_geometry),
            "side_action_candidate": f.side_action_candidate,
            "recommended_mold_action": f.recommended_mold_action,
            "action_reason": f.action_reason,
            "pull_alignment": f.pull_alignment,
            "action_confidence": f.action_confidence,
            "action_confidence_label": f.action_confidence_label,
            "action_confidence_factors": list(f.action_confidence_factors),
            "action_confidence_breakdown": dict(f.action_confidence_breakdown),
            "action_explanation": f.action_explanation,
        }

    r = result
    return {
        "pull_direction": list(r.pull_direction),
        "method": r.method,
        "undercut_face_ids": list(r.undercut_face_ids),
        "accessible_face_ids": list(r.accessible_face_ids),
        "parting_face_ids": list(r.parting_face_ids),
        "skipped_face_ids": list(r.skipped_face_ids),
        "convexity_suppressed_face_ids": list(r.convexity_suppressed_face_ids),
        "features": [feature(f) for f in r.features],
        "undercut_area_mm2": r.undercut_area_mm2,
        "total_analysed_area_mm2": r.total_analysed_area_mm2,
        "boolean_refined": r.boolean_refined,
        "boolean_checked_face_ids": list(r.boolean_checked_face_ids),
        "boolean_confirmed_face_ids": list(r.boolean_confirmed_face_ids),
        "boolean_failed_face_ids": list(r.boolean_failed_face_ids),
        "boolean_failure_reasons": {str(k): v for k, v in r.boolean_failure_reasons.items()},
        "boolean_failure_details": {str(k): v for k, v in r.boolean_failure_details.items()},
        "boolean_skipped_face_ids": list(r.boolean_skipped_face_ids),
        "boolean_skip_reasons": {str(k): v for k, v in r.boolean_skip_reasons.items()},
        "interference_volume_mm3": r.interference_volume_mm3,
        "boolean_depth_proxy_mm": r.boolean_depth_proxy_mm,
        "boolean_depth_method": r.boolean_depth_method,
        "boolean_cache_hits": r.boolean_cache_hits,
        "boolean_cache_misses": r.boolean_cache_misses,
        "boolean_time_s": r.boolean_time_s,
        "boolean_performance": performance(r.boolean_performance),
        "boolean_reliability": reliability(r.boolean_reliability),
        "accessibility_risk_face_ids": list(r.accessibility_risk_face_ids),
        "accessibility_risk_area_mm2": r.accessibility_risk_area_mm2,
        "analysis_time_s": r.analysis_time_s,
        "candidate_unconfirmed_face_ids": list(r.candidate_unconfirmed_face_ids),
        "candidate_sources": {str(k): list(v) for k, v in r.candidate_sources.items()},
        "boolean_not_applicable_face_ids": list(r.boolean_not_applicable_face_ids),
        "boolean_not_applicable_reasons": {str(k): v for k, v in r.boolean_not_applicable_reasons.items()},
        "ray_verified_clear_face_ids": list(r.ray_verified_clear_face_ids),
        "evaluation_failed": r.evaluation_failed,
        "evaluation_error": r.evaluation_error,
    }


def undercut_result_from_plain(data: dict) -> UndercutDetectionResult:
    """
    Reconstruct an ``UndercutDetectionResult`` from the plain dict produced
    by ``undercut_result_to_plain`` (round-tripped through JSON -- so all
    dict keys arrive as strings and must be converted back to int keys).

    Inverse of ``undercut_result_to_plain``. ``boolean_intersection_shapes``
    is never present in the input and is left at its dataclass default
    (``[]``) on every reconstructed ``UndercutFeature``.
    """

    def vec(v) -> tuple | None:
        return tuple(v) if v is not None else None

    def shape_analysis(d: dict) -> BooleanShapeAnalysis:
        return BooleanShapeAnalysis(
            available=d.get("available", False),
            vertex_count=d.get("vertex_count", 0),
            edge_count=d.get("edge_count", 0),
            bbox_min=vec(d.get("bbox_min")),
            bbox_max=vec(d.get("bbox_max")),
            bbox_center=vec(d.get("bbox_center")),
            bbox_dimensions=vec(d.get("bbox_dimensions")),
            center_of_mass=vec(d.get("center_of_mass")),
            volume_mm3=d.get("volume_mm3", 0.0),
            method=d.get("method", "not-available"),
            failure_reason=d.get("failure_reason", ""),
        )

    def region_geometry(d: dict) -> BooleanRegionGeometry:
        return BooleanRegionGeometry(
            available=d.get("available", False),
            shape_count=d.get("shape_count", 0),
            source_face_ids=list(d.get("source_face_ids", [])),
            vertex_count=d.get("vertex_count", 0),
            edge_count=d.get("edge_count", 0),
            bbox_min=vec(d.get("bbox_min")),
            bbox_max=vec(d.get("bbox_max")),
            bbox_center=vec(d.get("bbox_center")),
            bbox_dimensions=vec(d.get("bbox_dimensions")),
            center_of_mass=vec(d.get("center_of_mass")),
            volume_mm3=d.get("volume_mm3", 0.0),
            analyses=[shape_analysis(a) for a in d.get("analyses", [])],
            failure_reasons=list(d.get("failure_reasons", [])),
        )

    def performance(d: dict | None) -> BooleanPerformanceSummary | None:
        if d is None:
            return None
        return BooleanPerformanceSummary(
            checked_count=d.get("checked_count", 0),
            successful_count=d.get("successful_count", 0),
            failed_count=d.get("failed_count", 0),
            skipped_count=d.get("skipped_count", 0),
            cache_hits=d.get("cache_hits", 0),
            cache_misses=d.get("cache_misses", 0),
            elapsed_s=d.get("elapsed_s", 0.0),
            avg_success_elapsed_s=d.get("avg_success_elapsed_s", 0.0),
            max_success_elapsed_s=d.get("max_success_elapsed_s", 0.0),
            total_success_attempts=d.get("total_success_attempts", 0),
            total_failed_attempts=d.get("total_failed_attempts", 0),
            slow_faces=list(d.get("slow_faces", [])),
        )

    def reliability(d: dict | None) -> BooleanReliabilitySummary | None:
        if d is None:
            return None
        return BooleanReliabilitySummary(
            enabled=d.get("enabled", False),
            reliability_score=d.get("reliability_score", 0.0),
            reliability_label=d.get("reliability_label", ""),
            reliability_level=d.get("reliability_level", ""),
            checked_count=d.get("checked_count", 0),
            confirmed_count=d.get("confirmed_count", 0),
            failed_count=d.get("failed_count", 0),
            skipped_count=d.get("skipped_count", 0),
            proxy_retained_face_count=d.get("proxy_retained_face_count", 0),
            proxy_retained_failed_count=d.get("proxy_retained_failed_count", 0),
            proxy_retained_skipped_count=d.get("proxy_retained_skipped_count", 0),
            successful_operation_ratio=d.get("successful_operation_ratio", 0.0),
            confirmed_ratio=d.get("confirmed_ratio", 0.0),
            failure_ratio=d.get("failure_ratio", 0.0),
            fallback_ratio=d.get("fallback_ratio", 0.0),
            failure_class_counts=dict(d.get("failure_class_counts", {})),
            skip_reason_counts=dict(d.get("skip_reason_counts", {})),
            summary=d.get("summary", ""),
            recommended_action=d.get("recommended_action", ""),
        )

    def feature(d: dict) -> UndercutFeature:
        return UndercutFeature(
            feature_id=d["feature_id"],
            face_ids=list(d["face_ids"]),
            undercut_type=d["undercut_type"],
            severity=d["severity"],
            evidence_source=d["evidence_source"],
            type_classification_method=d["type_classification_method"],
            type_classification_score=d["type_classification_score"],
            type_classification_factors=list(d["type_classification_factors"]),
            release_direction=vec(d["release_direction"]),
            location=vec(d["location"]),
            depth_proxy_mm=d["depth_proxy_mm"],
            total_area_mm2=d["total_area_mm2"],
            min_draft_angle_deg=d["min_draft_angle_deg"],
            grouping_method=d.get("grouping_method", "face-adjacency"),
            grouping_factors=list(d.get("grouping_factors", [])),
            release_direction_method=d.get("release_direction_method", "normal-transverse"),
            release_direction_factors=list(d.get("release_direction_factors", [])),
            depth_estimation_method=d.get("depth_estimation_method", "projection-or-boolean-depth"),
            geometric_feature_type=d.get("geometric_feature_type", "unclassified"),
            geometric_feature_confidence=d.get("geometric_feature_confidence", 0.0),
            geometric_feature_confidence_label=d.get("geometric_feature_confidence_label", "unknown"),
            geometric_feature_method=d.get("geometric_feature_method", "not-run"),
            geometric_feature_factors=list(d.get("geometric_feature_factors", [])),
            boolean_depth_proxy_mm=d.get("boolean_depth_proxy_mm", 0.0),
            boolean_depth_method=d.get("boolean_depth_method", "none"),
            boolean_depth_evidence=dict(d.get("boolean_depth_evidence", {})),
            boolean_depth_factors=list(d.get("boolean_depth_factors", [])),
            interference_volume_mm3=d.get("interference_volume_mm3", 0.0),
            interaction_type=d.get("interaction_type", "none"),
            interaction_factors=list(d.get("interaction_factors", [])),
            boolean_confirmed_face_ids=list(d.get("boolean_confirmed_face_ids", [])),
            boolean_failed_face_ids=list(d.get("boolean_failed_face_ids", [])),
            boolean_skipped_face_ids=list(d.get("boolean_skipped_face_ids", [])),
            boolean_not_applicable_face_ids=list(d.get("boolean_not_applicable_face_ids", [])),
            boolean_intersection_face_ids=list(d.get("boolean_intersection_face_ids", [])),
            boolean_intersection_shapes=[],
            boolean_region_geometry=region_geometry(d.get("boolean_region_geometry", {})),
            side_action_candidate=d.get("side_action_candidate", True),
            recommended_mold_action=d.get("recommended_mold_action", "side-action-review"),
            action_reason=d.get("action_reason", ""),
            pull_alignment=d.get("pull_alignment", 0.0),
            action_confidence=d.get("action_confidence", 0.0),
            action_confidence_label=d.get("action_confidence_label", "unknown"),
            action_confidence_factors=list(d.get("action_confidence_factors", [])),
            action_confidence_breakdown=dict(d.get("action_confidence_breakdown", {})),
            action_explanation=d.get("action_explanation", ""),
        )

    d = data
    return UndercutDetectionResult(
        pull_direction=vec(d["pull_direction"]),
        method=d["method"],
        undercut_face_ids=list(d["undercut_face_ids"]),
        accessible_face_ids=list(d["accessible_face_ids"]),
        parting_face_ids=list(d["parting_face_ids"]),
        skipped_face_ids=list(d["skipped_face_ids"]),
        convexity_suppressed_face_ids=list(d.get("convexity_suppressed_face_ids", [])),
        features=[feature(f) for f in d.get("features", [])],
        undercut_area_mm2=d.get("undercut_area_mm2", 0.0),
        total_analysed_area_mm2=d.get("total_analysed_area_mm2", 0.0),
        boolean_refined=d.get("boolean_refined", False),
        boolean_checked_face_ids=list(d.get("boolean_checked_face_ids", [])),
        boolean_confirmed_face_ids=list(d.get("boolean_confirmed_face_ids", [])),
        boolean_failed_face_ids=list(d.get("boolean_failed_face_ids", [])),
        boolean_failure_reasons={int(k): v for k, v in d.get("boolean_failure_reasons", {}).items()},
        boolean_failure_details={int(k): v for k, v in d.get("boolean_failure_details", {}).items()},
        boolean_skipped_face_ids=list(d.get("boolean_skipped_face_ids", [])),
        boolean_skip_reasons={int(k): v for k, v in d.get("boolean_skip_reasons", {}).items()},
        interference_volume_mm3=d.get("interference_volume_mm3", 0.0),
        boolean_depth_proxy_mm=d.get("boolean_depth_proxy_mm", 0.0),
        boolean_depth_method=d.get("boolean_depth_method", "none"),
        boolean_cache_hits=d.get("boolean_cache_hits", 0),
        boolean_cache_misses=d.get("boolean_cache_misses", 0),
        boolean_time_s=d.get("boolean_time_s", 0.0),
        boolean_performance=performance(d.get("boolean_performance")),
        boolean_reliability=reliability(d.get("boolean_reliability")),
        accessibility_risk_face_ids=list(d.get("accessibility_risk_face_ids", [])),
        accessibility_risk_area_mm2=d.get("accessibility_risk_area_mm2", 0.0),
        analysis_time_s=d.get("analysis_time_s", 0.0),
        candidate_unconfirmed_face_ids=list(d.get("candidate_unconfirmed_face_ids", [])),
        candidate_sources={int(k): list(v) for k, v in d.get("candidate_sources", {}).items()},
        boolean_not_applicable_face_ids=list(d.get("boolean_not_applicable_face_ids", [])),
        boolean_not_applicable_reasons={
            int(k): v for k, v in d.get("boolean_not_applicable_reasons", {}).items()
        },
        ray_verified_clear_face_ids=list(d.get("ray_verified_clear_face_ids", [])),
        evaluation_failed=d.get("evaluation_failed", False),
        evaluation_error=d.get("evaluation_error", ""),
    )


def _project(point: Vec3, direction: Vec3) -> float:
    return dot3(point, direction)


def _sub3(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _scale3(v: Vec3, factor: float) -> Vec3:
    return (v[0] * factor, v[1] * factor, v[2] * factor)


def _safe_normalize3(v: Vec3, fallback: Vec3) -> Vec3:
    if mag3(v) < 1e-12:
        return fallback
    return normalize3(v)


def _average_point(faces: list[FaceData]) -> Vec3:
    if not faces:
        return (0.0, 0.0, 0.0)
    total_area = sum(max(face.area, 0.0) for face in faces)
    if total_area <= 0:
        n = float(len(faces))
        return (
            sum(face.centroid[0] for face in faces) / n,
            sum(face.centroid[1] for face in faces) / n,
            sum(face.centroid[2] for face in faces) / n,
        )
    return (
        sum(face.centroid[0] * face.area for face in faces) / total_area,
        sum(face.centroid[1] * face.area for face in faces) / total_area,
        sum(face.centroid[2] * face.area for face in faces) / total_area,
    )


def _average_normal(faces: list[FaceData]) -> Vec3:
    valid = [face for face in faces if face.normal_valid]
    if not valid:
        return (0.0, 0.0, 0.0)
    total_area = sum(max(face.area, 0.0) for face in valid)
    if total_area <= 0.0:
        n = float(len(valid))
        return _safe_normalize3((
            sum(face.normal[0] for face in valid) / n,
            sum(face.normal[1] for face in valid) / n,
            sum(face.normal[2] for face in valid) / n,
        ), (0.0, 0.0, 1.0))
    return _safe_normalize3((
        sum(face.normal[0] * face.area for face in valid) / total_area,
        sum(face.normal[1] * face.area for face in valid) / total_area,
        sum(face.normal[2] * face.area for face in valid) / total_area,
    ), (0.0, 0.0, 1.0))


def _severity(depth_proxy_mm: float, area_mm2: float) -> str:
    if depth_proxy_mm > 5.0 or area_mm2 > 1000.0:
        return "critical"
    if depth_proxy_mm > 2.0 or area_mm2 > 250.0:
        return "moderate"
    return "minor"


def _normalized_bbox_axis_position(point: Vec3, direction: Vec3, part: PartGeometry) -> float:
    bbox_points = [
        (x, y, z)
        for x in (part.bounding_box.xmin, part.bounding_box.xmax)
        for y in (part.bounding_box.ymin, part.bounding_box.ymax)
        for z in (part.bounding_box.zmin, part.bounding_box.zmax)
    ]
    projections = [_project(corner, direction) for corner in bbox_points]
    span = max(projections) - min(projections)
    if span <= 1e-9:
        return 0.5
    return max(0.0, min(1.0, (_project(point, direction) - min(projections)) / span))


def _classification_score(base: float, *components: float) -> float:
    return max(0.05, min(0.98, base + sum(components)))


def _classify_undercut_type(
    faces: list[FaceData],
    pull_direction: Vec3,
    part: PartGeometry,
) -> UndercutTypeClassification:
    """
    Classify a grouped undercut feature using layered geometric evidence.

    Primary evidence is area-weighted signed face normal relative to the main
    pull.  Secondary evidence uses radial normal direction and feature location
    when normals are mixed.  True side-wall/silhouette groups are preserved when
    most area is near perpendicular to the pull and there is no axial polarity.
    """
    valid = [face for face in faces if face.normal_valid]
    if not valid:
        return UndercutTypeClassification(
            undercut_type="unknown",
            method="no-valid-normals",
            score=0.0,
            factors=["no valid face normals"],
        )

    total_area = sum(max(face.area, 0.0) for face in valid)
    if total_area <= 0.0:
        total_area = float(len(valid))
        weights = {face.face_id: 1.0 for face in valid}
    else:
        weights = {face.face_id: max(face.area, 0.0) for face in valid}

    signed_by_face = {face.face_id: face.signed_dot(pull_direction) for face in valid}
    weighted_signed = sum(
        signed_by_face[face.face_id] * weights[face.face_id]
        for face in valid
    ) / total_area
    positive_area = sum(
        weights[face.face_id] for face in valid if signed_by_face[face.face_id] > 0.05
    )
    negative_area = sum(
        weights[face.face_id] for face in valid if signed_by_face[face.face_id] < -0.05
    )
    silhouette_area = max(0.0, total_area - positive_area - negative_area)
    positive_ratio = positive_area / total_area
    negative_ratio = negative_area / total_area
    silhouette_ratio = silhouette_area / total_area
    consensus_ratio = max(positive_ratio, negative_ratio)
    polarity_gap = abs(positive_ratio - negative_ratio)
    opposing_ratio = min(positive_ratio, negative_ratio)

    center = _average_point(valid)
    pull_axis_position = _normalized_bbox_axis_position(center, pull_direction, part)
    factors = [
        f"area-weighted signed n.d={weighted_signed:.3f}",
        f"positive_area_ratio={positive_ratio:.3f}",
        f"negative_area_ratio={negative_ratio:.3f}",
        f"silhouette_area_ratio={silhouette_ratio:.3f}",
        f"polarity_gap={polarity_gap:.3f}",
        f"pull_axis_position={pull_axis_position:.3f}",
    ]

    if weighted_signed < -0.12 and negative_ratio >= 0.60:
        location_bonus = 0.03 if pull_axis_position <= 0.45 else 0.0
        return UndercutTypeClassification(
            undercut_type="internal/core-side",
            method="area-weighted-normal-consensus",
            score=_classification_score(
                0.52,
                0.34 * consensus_ratio,
                0.10 * abs(weighted_signed),
                location_bonus,
            ),
            factors=factors + ["negative signed-normal consensus"],
        )
    if weighted_signed > 0.12 and positive_ratio >= 0.60:
        location_bonus = 0.03 if pull_axis_position >= 0.55 else 0.0
        return UndercutTypeClassification(
            undercut_type="external/cavity-side",
            method="area-weighted-normal-consensus",
            score=_classification_score(
                0.52,
                0.34 * consensus_ratio,
                0.10 * abs(weighted_signed),
                location_bonus,
            ),
            factors=factors + ["positive signed-normal consensus"],
        )

    pure_silhouette = (
        silhouette_ratio >= 0.70
        and positive_ratio < 0.20
        and negative_ratio < 0.20
        and abs(weighted_signed) <= 0.06
    )
    if pure_silhouette:
        return UndercutTypeClassification(
            undercut_type="side-wall/silhouette",
            method="silhouette-normal-distribution",
            score=min(0.88, 0.48 + 0.42 * silhouette_ratio),
            factors=factors + ["dominant near-zero pull-axis normals without axial polarity"],
        )

    part_center = part.bounding_box.center
    radial = _sub3(center, part_center)
    axial = _scale3(pull_direction, dot3(radial, pull_direction))
    transverse_radial = _sub3(radial, axial)
    if mag3(transverse_radial) > max(part.bounding_box.diagonal * 1e-6, 1e-6):
        radial_dir = normalize3(transverse_radial)
        avg_normal = _average_normal(valid)
        radial_alignment = dot3(avg_normal, radial_dir)
        factors.append(f"radial_normal_alignment={radial_alignment:.3f}")
        radial_applicable = (
            opposing_ratio >= 0.15
            or silhouette_ratio < 0.70
            or polarity_gap >= 0.20
        )
        if radial_applicable:
            factors.append("radial evidence applicable to mixed/non-pure-silhouette feature")
        else:
            factors.append("radial evidence suppressed for pure side-wall silhouette")
        if radial_applicable and radial_alignment > 0.35:
            polarity_bonus = 0.04 if positive_ratio >= negative_ratio else 0.0
            location_bonus = 0.03 if pull_axis_position >= 0.50 else 0.0
            return UndercutTypeClassification(
                undercut_type="external/cavity-side",
                method="radial-normal-secondary",
                score=_classification_score(
                    0.44,
                    0.34 * abs(radial_alignment),
                    polarity_bonus,
                    location_bonus,
                ),
                factors=factors + [
                    "feature normals point away from part center",
                    "radial evidence indicates external/cavity-side accessibility",
                ],
            )
        if radial_applicable and radial_alignment < -0.35:
            polarity_bonus = 0.04 if negative_ratio >= positive_ratio else 0.0
            location_bonus = 0.03 if pull_axis_position <= 0.50 else 0.0
            return UndercutTypeClassification(
                undercut_type="internal/core-side",
                method="radial-normal-secondary",
                score=_classification_score(
                    0.44,
                    0.34 * abs(radial_alignment),
                    polarity_bonus,
                    location_bonus,
                ),
                factors=factors + [
                    "feature normals point toward part center",
                    "radial evidence indicates internal/core-side accessibility",
                ],
            )

    if silhouette_ratio >= 0.60 or abs(weighted_signed) <= 0.03:
        return UndercutTypeClassification(
            undercut_type="side-wall/silhouette",
            method="silhouette-normal-distribution",
            score=min(0.82, 0.42 + 0.38 * silhouette_ratio + 0.10 * (1.0 - polarity_gap)),
            factors=factors + ["near-zero pull-axis normal distribution after radial check"],
        )

    if negative_ratio > positive_ratio:
        return UndercutTypeClassification(
            undercut_type="internal/core-side",
            method="weak-area-majority",
            score=_classification_score(
                0.42,
                0.25 * (negative_ratio - positive_ratio),
                0.03 if pull_axis_position <= 0.45 else 0.0,
            ),
            factors=factors + ["weak negative signed-normal majority"],
        )
    if positive_ratio > negative_ratio:
        return UndercutTypeClassification(
            undercut_type="external/cavity-side",
            method="weak-area-majority",
            score=_classification_score(
                0.42,
                0.25 * (positive_ratio - negative_ratio),
                0.03 if pull_axis_position >= 0.55 else 0.0,
            ),
            factors=factors + ["weak positive signed-normal majority"],
        )

    return UndercutTypeClassification(
        undercut_type="side-wall/silhouette",
        method="ambiguous-balanced-distribution",
        score=0.35,
        factors=factors + ["balanced or ambiguous signed-normal evidence"],
    )


def _estimate_release_direction(faces: list[FaceData], pull_direction: Vec3) -> Vec3:
    """
    Estimate a local release direction for an undercut feature.

    This is a rule-based geometric estimate, not mold-action synthesis.  We use
    the area-weighted feature normal, remove its component along the main pull,
    and treat the remaining transverse vector as the side-release direction.
    If the transverse vector is too small, we fall back to the mold half side
    implied by n·d.
    """
    avg_normal = _average_normal(faces)
    axial = _scale3(pull_direction, dot3(avg_normal, pull_direction))
    transverse = _sub3(avg_normal, axial)
    if mag3(transverse) > 1e-6:
        return normalize3(transverse)

    signed = dot3(avg_normal, pull_direction)
    if signed < 0.0:
        return (-pull_direction[0], -pull_direction[1], -pull_direction[2])
    return pull_direction


def _bbox_corners(bbox_min: Vec3 | None, bbox_max: Vec3 | None) -> list[Vec3]:
    if bbox_min is None or bbox_max is None:
        return []
    return [
        (x, y, z)
        for x in (bbox_min[0], bbox_max[0])
        for y in (bbox_min[1], bbox_max[1])
        for z in (bbox_min[2], bbox_max[2])
    ]


def _remove_axial_component(vector: Vec3, axis: Vec3) -> Vec3:
    return _sub3(vector, _scale3(axis, dot3(vector, axis)))


def _align_with_reference(direction: Vec3, reference: Vec3) -> Vec3:
    if mag3(reference) < 1e-12:
        return direction
    if dot3(direction, reference) < 0.0:
        return (-direction[0], -direction[1], -direction[2])
    return direction


def _estimate_release_and_depth_from_boolean_geometry(
    faces: list[FaceData],
    pull_direction: Vec3,
    part: PartGeometry,
    geometry: BooleanRegionGeometry,
    fallback_release_direction: Vec3,
    fallback_depth_mm: float,
) -> GeometryReleaseDepthEstimate:
    """
    Refine local release direction/depth from the Boolean intersection region.

    The swept Boolean region should lie in the blocked/access direction for the
    tested face.  We use its center relative to the grouped feature center as
    primary evidence, remove the main-pull component, and keep the existing
    normal-based estimate as a stable fallback.
    """
    fallback_release = _safe_normalize3(fallback_release_direction, pull_direction)
    factors = ["normal-based fallback available"]
    if not geometry.available:
        return GeometryReleaseDepthEstimate(
            release_direction=fallback_release,
            depth_mm=fallback_depth_mm,
            release_direction_method="normal-transverse-fallback",
            depth_method="projection-or-boolean-depth",
            factors=factors + ["Boolean region geometry unavailable"],
        )

    pull_dir = normalize3(pull_direction)
    feature_center = _average_point(faces)
    region_center = geometry.center_of_mass or geometry.bbox_center
    candidates: list[tuple[float, Vec3, str, str]] = []
    min_vector_mag = max(part.bounding_box.diagonal * 1e-6, 1e-6)

    if region_center is not None:
        feature_to_region = _remove_axial_component(
            _sub3(region_center, feature_center),
            pull_dir,
        )
        if mag3(feature_to_region) > min_vector_mag:
            candidates.append((
                mag3(feature_to_region),
                feature_to_region,
                "boolean-region-center-transverse",
                "region center offset from feature center",
            ))

        part_to_region = _remove_axial_component(
            _sub3(region_center, part.bounding_box.center),
            pull_dir,
        )
        if mag3(part_to_region) > min_vector_mag:
            candidates.append((
                0.5 * mag3(part_to_region),
                part_to_region,
                "boolean-region-radial-secondary",
                "region center offset from part center",
            ))

    if candidates:
        _, vector, release_method, reason = max(candidates, key=lambda item: item[0])
        release_direction = _align_with_reference(normalize3(vector), fallback_release)
        factors.append(reason)
    else:
        release_direction = fallback_release
        release_method = "normal-transverse-fallback"
        factors.append("Boolean region center has no clear transverse offset")

    bbox_points = _bbox_corners(geometry.bbox_min, geometry.bbox_max)
    release_span = _projection_span(bbox_points, release_direction)
    pull_span = _projection_span(bbox_points, pull_dir)
    bbox_max_dimension = max(geometry.bbox_dimensions or (0.0, 0.0, 0.0))

    depth_candidates = [
        (fallback_depth_mm, "projection-or-boolean-depth"),
        (release_span, "boolean-region-release-span"),
        (pull_span, "boolean-region-pull-span"),
        (bbox_max_dimension, "boolean-region-max-bbox-dimension"),
    ]
    depth_mm, depth_method = max(depth_candidates, key=lambda item: item[0])
    if depth_method != "projection-or-boolean-depth":
        factors.append(f"depth refined from {depth_method}")

    return GeometryReleaseDepthEstimate(
        release_direction=release_direction,
        depth_mm=max(0.0, depth_mm),
        release_direction_method=release_method,
        depth_method=depth_method,
        factors=factors,
    )


def _part_bbox_points(part: PartGeometry) -> list[Vec3]:
    box = part.bounding_box
    return [
        (x, y, z)
        for x in (box.xmin, box.xmax)
        for y in (box.ymin, box.ymax)
        for z in (box.zmin, box.zmax)
    ]


def _classify_boolean_geometric_feature(
    geometry: BooleanRegionGeometry,
    pull_direction: Vec3,
    release_direction: Vec3,
    part: PartGeometry,
    undercut_type: str,
    face_count: int,
) -> GeometricFeatureClassification:
    """
    Conservative rule-based typing for Boolean-confirmed undercut regions.

    This is not full volumetric feature recognition.  It gives useful candidate
    labels from local Boolean-region geometry only: bbox proportions, topology
    counts, volume fill ratio, source-face count, and spans along pull/release.
    """
    if not geometry.available or geometry.bbox_dimensions is None:
        return GeometricFeatureClassification(
            feature_type="unclassified",
            confidence=0.10,
            confidence_label="low",
            method="boolean-geometry-unavailable",
            factors=["Boolean region geometry unavailable"],
        )

    dims = tuple(max(0.0, value) for value in geometry.bbox_dimensions)
    max_dim = max(dims)
    min_dim = min(dims)
    sorted_dims = sorted(dims, reverse=True)
    mid_dim = sorted_dims[1] if len(sorted_dims) > 1 else 0.0
    bbox_volume = dims[0] * dims[1] * dims[2]
    fill_ratio = (
        min(1.0, max(0.0, geometry.volume_mm3 / bbox_volume))
        if bbox_volume > 1e-9
        else 0.0
    )
    flatness_ratio = min_dim / max_dim if max_dim > 1e-9 else 0.0
    balance_ratio = max_dim / mid_dim if mid_dim > 1e-9 else float("inf")
    elongation_ratio = max_dim / min_dim if min_dim > 1e-9 else float("inf")
    bbox_points = _bbox_corners(geometry.bbox_min, geometry.bbox_max)
    release_span = _projection_span(bbox_points, release_direction)
    pull_span = _projection_span(bbox_points, pull_direction)
    part_pull_span = max(_projection_span(_part_bbox_points(part), pull_direction), 1.0)
    source_count = len(geometry.source_face_ids)
    release_to_pull_ratio = release_span / max(pull_span, 1e-6)
    pull_to_part_ratio = pull_span / part_pull_span
    topology_density = (
        (geometry.edge_count + geometry.vertex_count) / max(source_count, 1)
    )
    factors = [
        f"bbox_dimensions={dims[0]:.3f},{dims[1]:.3f},{dims[2]:.3f}",
        f"fill_ratio={fill_ratio:.3f}",
        f"flatness_ratio={flatness_ratio:.3f}",
        f"balance_ratio={balance_ratio:.3f}",
        f"elongation_ratio={elongation_ratio:.3f}",
        f"release_span={release_span:.3f}",
        f"pull_span={pull_span:.3f}",
        f"release_to_pull_ratio={release_to_pull_ratio:.3f}",
        f"pull_to_part_ratio={pull_to_part_ratio:.3f}",
        f"topology_density={topology_density:.3f}",
        f"source_face_count={source_count}",
        f"edge_count={geometry.edge_count}",
        f"vertex_count={geometry.vertex_count}",
        f"semantic_undercut_type={undercut_type}",
    ]

    if (
        geometry.shape_count >= 3
        or source_count >= 4
        or (geometry.edge_count >= 32 and geometry.vertex_count >= 20)
    ):
        confidence = 0.62
        if geometry.shape_count >= 3:
            confidence += 0.08
        if source_count >= 4:
            confidence += 0.05
        return GeometricFeatureClassification(
            feature_type="complex/interacting-candidate",
            confidence=min(0.82, confidence),
            confidence_label=_confidence_label(min(0.82, confidence)),
            method="boolean-region-complexity-rules",
            factors=factors + ["multiple shapes/faces or high topology complexity"],
        )

    if (
        pull_to_part_ratio >= 0.65
        and pull_span >= max(1.25 * release_span, 1e-6)
        and geometry.edge_count >= 8
    ):
        confidence = min(0.78, 0.48 + 0.30 * min(1.0, pull_span / part_pull_span))
        return GeometricFeatureClassification(
            feature_type="through-feature-candidate",
            confidence=confidence,
            confidence_label=_confidence_label(confidence),
            method="boolean-region-through-span-rule",
            factors=factors + [
                "Boolean region spans a large fraction of the part along pull",
                "pull span dominates release span",
            ],
        )

    if (
        geometry.edge_count >= 16
        and geometry.vertex_count >= 8
        and balance_ratio <= 1.25
        and flatness_ratio <= 0.55
        and topology_density >= 24.0
    ):
        confidence = 0.55
        if fill_ratio <= 0.60:
            confidence += 0.08
        if balance_ratio <= 1.10:
            confidence += 0.04
        return GeometricFeatureClassification(
            feature_type="annular/ring-candidate",
            confidence=min(0.78, confidence),
            confidence_label=_confidence_label(min(0.78, confidence)),
            method="boolean-region-balanced-topology-rule",
            factors=factors + [
                "balanced transverse dimensions with richer edge topology",
                "moderate/low fill ratio suggests ring-like void or annular interference",
            ],
        )

    if (
        release_to_pull_ratio >= 1.5
        and flatness_ratio <= 0.35
        and balance_ratio > 1.35
    ):
        confidence = 0.62
        if release_to_pull_ratio >= 2.0:
            confidence += 0.08
        if undercut_type == "side-wall/silhouette":
            confidence += 0.04
        return GeometricFeatureClassification(
            feature_type="hook/undercut-ledge-candidate",
            confidence=min(0.82, confidence),
            confidence_label=_confidence_label(min(0.82, confidence)),
            method="boolean-region-release-span-flatness-rule",
            factors=factors + [
                "flat region with dominant release-direction span",
                "elongated profile separates ledge/hook from annular feature",
            ],
        )

    if (
        source_count <= 2
        and pull_to_part_ratio < 0.50
        and elongation_ratio <= 2.40
    ):
        confidence = 0.50
        if fill_ratio >= 0.35:
            confidence += 0.10
        if flatness_ratio > 0.25:
            confidence += 0.05
        if elongation_ratio <= 1.80:
            confidence += 0.03
        return GeometricFeatureClassification(
            feature_type="pocket/blind-undercut-candidate",
            confidence=min(0.72, confidence),
            confidence_label=_confidence_label(min(0.72, confidence)),
            method="boolean-region-local-compactness-rule",
            factors=factors + [
                "local compact Boolean region without through-span evidence",
                "bounded elongation supports blind-pocket classification",
            ],
        )

    return GeometricFeatureClassification(
        feature_type="complex/interacting-candidate",
        confidence=0.45,
        confidence_label=_confidence_label(0.45),
        method="boolean-region-fallback-rule",
        factors=factors + ["geometry did not match simple pocket/hook/ring/through rules"],
    )


def _confidence_label(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def _clamp_confidence(score: float) -> float:
    return max(0.05, min(0.98, score))


def _build_action_confidence_breakdown(
    undercut_type: str,
    severity: str,
    evidence_source: str,
    pull_alignment: float,
    depth_proxy_mm: float,
    interference_volume_mm3: float,
    boolean_depth_method: str,
    type_classification_score: float = 0.5,
    type_classification_method: str = "",
) -> ActionConfidenceBreakdown:
    """
    Explainable confidence breakdown for rule-based mold-action suggestions.

    This is not statistical model confidence.  It is an engineering confidence
    score based on evidence quality and geometric clarity.
    """
    base_score = 0.50
    score = base_score
    terms: list[ActionConfidenceTerm] = []

    def add(code: str, impact: float, explanation: str) -> None:
        nonlocal score
        score += impact
        terms.append(ActionConfidenceTerm(
            code=code,
            impact=impact,
            explanation=explanation,
        ))

    if evidence_source == "boolean-confirmed":
        add("evidence.boolean_confirmed", 0.25, "Boolean-confirmed interference")
    elif evidence_source.startswith("mixed-boolean"):
        add("evidence.mixed_boolean_proxy", 0.15, "mixed Boolean/proxy evidence")
    elif "failure" in evidence_source:
        add("evidence.boolean_failure", -0.25, "Boolean failure reduced confidence")
    elif "skip" in evidence_source:
        add("evidence.boolean_skip", -0.15, "Boolean skipped small/sliver face")
    elif evidence_source == "proxy-only":
        add("evidence.proxy_only", 0.0, "proxy-only evidence")

    if boolean_depth_method.startswith("vertex"):
        add("depth.vertex", 0.12, f"depth from {boolean_depth_method}")
    elif boolean_depth_method.startswith("bbox"):
        add("depth.bbox", 0.07, f"depth from {boolean_depth_method}")
    elif boolean_depth_method in {"volume-area", "feature-volume-area"}:
        add("depth.volume_area", 0.03, "depth from volume/area fallback")
    elif boolean_depth_method in {"none", "unknown"}:
        add("depth.none", -0.05, "no Boolean depth method")

    if severity == "critical":
        add("severity.critical", 0.08, "critical severity")
    elif severity == "moderate":
        add("severity.moderate", 0.04, "moderate severity")

    if depth_proxy_mm > 2.0:
        add("geometry.depth", 0.05, "measurable undercut depth")
    if interference_volume_mm3 > 0.0:
        add("geometry.interference_volume", 0.05, "non-zero interference volume")

    if pull_alignment < 0.25:
        add("release.clear_transverse", 0.08, "clear transverse release direction")
    elif pull_alignment < 0.50:
        add("release.mostly_transverse", 0.04, "mostly transverse release direction")
    elif 0.45 <= pull_alignment <= 0.65:
        add("release.ambiguous", -0.05, "ambiguous release alignment")
    elif pull_alignment > 0.85:
        add("release.clear_main_pull", 0.04, "clear main-pull alignment")

    if undercut_type in {"internal/core-side", "external/cavity-side"}:
        add("type.core_cavity_side", 0.05, f"classified as {undercut_type}")
    elif undercut_type == "side-wall/silhouette":
        add("type.silhouette", -0.03, "silhouette category is inherently ambiguous")
    else:
        add("type.unknown", -0.15, "unknown undercut type")

    if type_classification_score >= 0.75:
        add(
            "type_confidence.strong",
            0.08,
            f"strong type classification via {type_classification_method}",
        )
    elif type_classification_score >= 0.55:
        add(
            "type_confidence.moderate",
            0.03,
            f"moderate type classification via {type_classification_method}",
        )
    elif type_classification_score < 0.45:
        add(
            "type_confidence.weak",
            -0.08,
            f"weak type classification via {type_classification_method}",
        )

    confidence = _clamp_confidence(score)
    return ActionConfidenceBreakdown(
        base_score=base_score,
        final_score=confidence,
        label=_confidence_label(confidence),
        terms=terms,
    )


def _score_action_confidence(
    undercut_type: str,
    severity: str,
    evidence_source: str,
    pull_alignment: float,
    depth_proxy_mm: float,
    interference_volume_mm3: float,
    boolean_depth_method: str,
    type_classification_score: float = 0.5,
    type_classification_method: str = "",
) -> tuple[float, list[str]]:
    """
    Backwards-compatible score/factors API for tests and callers.
    """
    breakdown = _build_action_confidence_breakdown(
        undercut_type=undercut_type,
        severity=severity,
        evidence_source=evidence_source,
        pull_alignment=pull_alignment,
        depth_proxy_mm=depth_proxy_mm,
        interference_volume_mm3=interference_volume_mm3,
        boolean_depth_method=boolean_depth_method,
        type_classification_score=type_classification_score,
        type_classification_method=type_classification_method,
    )
    return breakdown.final_score, breakdown.factors


def _recommend_mold_action(
    undercut_type: str,
    severity: str,
    evidence_source: str,
    release_direction: Vec3,
    pull_direction: Vec3,
    depth_proxy_mm: float,
    interference_volume_mm3: float,
    boolean_depth_method: str,
    type_classification_score: float,
    type_classification_method: str,
) -> MoldActionRecommendation:
    """
    Basic mold-action recommendation for Phase 2.

    The rule is intentionally conservative: it flags side action when the
    feature's estimated release direction is transverse to the main pull.  It
    escalates internal/core-side severe features to lifter/collapsible-core
    review because the exact mechanism depends on geometry we have not yet
    decomposed volumetrically.
    """
    alignment = abs(dot3(release_direction, pull_direction))
    has_boolean_evidence = "boolean" in evidence_source and "failure" not in evidence_source
    has_material_interference = interference_volume_mm3 > 0.0 or has_boolean_evidence
    breakdown = _build_action_confidence_breakdown(
        undercut_type=undercut_type,
        severity=severity,
        evidence_source=evidence_source,
        pull_alignment=alignment,
        depth_proxy_mm=depth_proxy_mm,
        interference_volume_mm3=interference_volume_mm3,
        boolean_depth_method=boolean_depth_method,
        type_classification_score=type_classification_score,
        type_classification_method=type_classification_method,
    )
    confidence = breakdown.final_score
    factors = breakdown.factors

    def make_recommendation(
        side_action_candidate: bool,
        action: str,
        reason: str,
    ) -> MoldActionRecommendation:
        explanation = (
            f"{reason} {breakdown.summary()} "
            f"Release alignment to main pull is {alignment:.3f}; "
            f"estimated depth is {depth_proxy_mm:.3f} mm."
        )
        if interference_volume_mm3 > 0.0:
            explanation += f" Boolean interference volume is {interference_volume_mm3:.3f} mm^3."
        return MoldActionRecommendation(
            side_action_candidate=side_action_candidate,
            action=action,
            reason=reason,
            pull_alignment=alignment,
            confidence=confidence,
            confidence_label=breakdown.label,
            confidence_factors=factors,
            confidence_breakdown=breakdown.to_dict(),
            explanation=explanation,
        )

    if "failure" in evidence_source:
        return make_recommendation(
            side_action_candidate=True,
            action="manual-review",
            reason=(
                "Boolean refinement failed on at least one face; proxy evidence "
                "was retained for a conservative manual review."
            ),
        )

    if alignment < 0.5:
        if undercut_type == "internal/core-side" and (severity == "critical" or depth_proxy_mm > 2.0):
            return make_recommendation(
                side_action_candidate=True,
                action="lifter-or-collapsible-core-review",
                reason=(
                    "Internal core-side undercut releases transverse to the main "
                    "pull, so lifter or collapsible-core review is recommended."
                ),
            )
        return make_recommendation(
            side_action_candidate=True,
            action="side-action",
            reason=(
                "Feature release direction is transverse to the main mold "
                "opening direction."
            ),
        )

    if has_material_interference:
        return make_recommendation(
            side_action_candidate=True,
            action="draft-redesign-or-local-action-review",
            reason=(
                "Boolean interference exists even though the estimated release "
                "direction is near the main pull."
            ),
        )

    return make_recommendation(
        side_action_candidate=False,
        action="draft-redesign-review",
        reason=(
            "Proxy undercut evidence indicates low draft; no transverse "
            "Boolean-confirmed action is available yet."
        ),
    )


def _feature_evidence_source(
    group: list[int],
    boolean_was_run: bool,
    boolean_confirmed: set[int],
    boolean_failed: set[int],
    boolean_skipped: set[int],
) -> str:
    if not boolean_was_run:
        return "proxy-only"

    group_set = set(group)
    confirmed_count = len(group_set & boolean_confirmed)
    failed_count = len(group_set & boolean_failed)
    skipped_count = len(group_set & boolean_skipped)
    if confirmed_count == len(group_set) and confirmed_count > 0:
        return "boolean-confirmed"
    if confirmed_count > 0 and failed_count > 0:
        return "mixed-boolean-and-failed-proxy"
    if confirmed_count > 0 and skipped_count > 0:
        return "mixed-boolean-and-skipped-proxy"
    if confirmed_count > 0:
        return "mixed-boolean-and-proxy"
    if failed_count > 0:
        return "proxy-retained-after-boolean-failure"
    if skipped_count > 0:
        return "proxy-retained-after-boolean-skip"
    return "proxy-only"


def _dominant_depth_method(metrics: list[BooleanInterferenceMetrics]) -> str:
    if not metrics:
        return "none"
    return max(
        metrics,
        key=lambda metric: (metric.depth_mm, metric.volume_mm3),
    ).depth_method


def _dominant_depth_metric(metrics: list[BooleanInterferenceMetrics]) -> BooleanInterferenceMetrics | None:
    if not metrics:
        return None
    return max(metrics, key=lambda metric: (metric.depth_mm, metric.volume_mm3))


def _build_boolean_performance_summary(
    checked_face_ids: list[int],
    failed_face_ids: list[int],
    skipped_face_ids: list[int],
    metrics_by_face: dict[int, BooleanInterferenceMetrics],
    failure_details: dict[int, BooleanFailureInfo],
    cache_hits: int,
    cache_misses: int,
    elapsed_s: float,
) -> BooleanPerformanceSummary:
    success_metrics = list(metrics_by_face.items())
    success_elapsed = [max(0.0, metric.elapsed_s) for _, metric in success_metrics]
    total_success_attempts = sum(max(0, metric.attempt_count) for _, metric in success_metrics)
    total_failed_attempts = sum(
        max(0, detail.attempt_count)
        for detail in failure_details.values()
    )
    avg_success_elapsed = (
        sum(success_elapsed) / len(success_elapsed)
        if success_elapsed
        else 0.0
    )
    max_success_elapsed = max(success_elapsed) if success_elapsed else 0.0

    slow_faces = []
    for face_id, metric in sorted(
        success_metrics,
        key=lambda item: item[1].elapsed_s,
        reverse=True,
    )[:5]:
        slow_faces.append({
            "face_id": face_id,
            "elapsed_s": round(max(0.0, metric.elapsed_s), 6),
            "attempt_count": metric.attempt_count,
            "status": metric.status,
            "volume_mm3": round(metric.volume_mm3, 6),
            "depth_method": metric.depth_method,
        })

    return BooleanPerformanceSummary(
        checked_count=len(checked_face_ids),
        successful_count=len(metrics_by_face),
        failed_count=len(failed_face_ids),
        skipped_count=len(skipped_face_ids),
        cache_hits=cache_hits,
        cache_misses=cache_misses,
        elapsed_s=elapsed_s,
        avg_success_elapsed_s=avg_success_elapsed,
        max_success_elapsed_s=max_success_elapsed,
        total_success_attempts=total_success_attempts,
        total_failed_attempts=total_failed_attempts,
        slow_faces=slow_faces,
    )


def _classify_boolean_skip_reason(reason: str) -> str:
    lower = reason.lower()
    if "sliver" in lower or "below boolean" in lower or "too small" in lower:
        return "sliver-or-small-face"
    if "budget" in lower or "limit" in lower or "max" in lower:
        return "boolean-budget-limit"
    if "normal" in lower or "invalid" in lower:
        return "invalid-face-normal"
    return "other-skip"


def _count_failure_classes(
    failure_details: dict[int, BooleanFailureInfo],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for detail in failure_details.values():
        failure_class = detail.failure_class or "unknown"
        counts[failure_class] = counts.get(failure_class, 0) + 1
    return counts


def _count_skip_reasons(skip_reasons: dict[int, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for reason in skip_reasons.values():
        skip_class = _classify_boolean_skip_reason(reason)
        counts[skip_class] = counts.get(skip_class, 0) + 1
    return counts


def _boolean_reliability_label(score: float, fallback_ratio: float, enabled: bool) -> tuple[str, str]:
    if not enabled:
        return ("Not run", "neutral")
    if score >= 0.82 and fallback_ratio <= 0.10:
        return ("High Boolean reliability", "high")
    if score >= 0.58 and fallback_ratio <= 0.35:
        return ("Mixed Boolean reliability", "medium")
    return ("Proxy-heavy Boolean evidence", "low")


def _build_boolean_reliability_summary(
    *,
    enabled: bool,
    undercut_face_ids: list[int],
    checked_face_ids: list[int],
    confirmed_face_ids: list[int],
    failed_face_ids: list[int],
    skipped_face_ids: list[int],
    failure_details: dict[int, BooleanFailureInfo],
    skip_reasons: dict[int, str],
) -> BooleanReliabilitySummary:
    undercut_set = set(undercut_face_ids)
    confirmed_set = set(confirmed_face_ids)
    failed_set = set(failed_face_ids)
    skipped_set = set(skipped_face_ids)
    checked_count = len(set(checked_face_ids))
    confirmed_count = len(confirmed_set)
    failed_count = len(failed_set)
    skipped_count = len(skipped_set)
    proxy_failed = len(undercut_set & failed_set)
    proxy_skipped = len(undercut_set & skipped_set)
    proxy_retained = proxy_failed + proxy_skipped
    attempted_count = max(checked_count + skipped_count, 0)
    successful_operation_count = max(0, checked_count - failed_count)
    successful_operation_ratio = (
        successful_operation_count / checked_count
        if checked_count > 0
        else 0.0
    )

    if not enabled:
        confirmed_ratio = 0.0
        failure_ratio = 0.0
        fallback_ratio = 0.0
        score = 0.0
        label, level = _boolean_reliability_label(score, fallback_ratio, enabled)
        summary = "Swept Boolean refinement was not run for this undercut result."
        recommended_action = (
            "Use draft/proxy undercut evidence only, or rerun in the locked OCC Docker "
            "environment with Boolean refinement enabled."
        )
        return BooleanReliabilitySummary(
            enabled=False,
            reliability_score=score,
            reliability_label=label,
            reliability_level=level,
            checked_count=checked_count,
            confirmed_count=confirmed_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            proxy_retained_face_count=proxy_retained,
            proxy_retained_failed_count=proxy_failed,
            proxy_retained_skipped_count=proxy_skipped,
            successful_operation_ratio=successful_operation_ratio,
            confirmed_ratio=confirmed_ratio,
            failure_ratio=failure_ratio,
            fallback_ratio=fallback_ratio,
            failure_class_counts=_count_failure_classes(failure_details),
            skip_reason_counts=_count_skip_reasons(skip_reasons),
            summary=summary,
            recommended_action=recommended_action,
        )

    if attempted_count <= 0:
        confirmed_ratio = 0.0
        failure_ratio = 0.0
        fallback_ratio = 0.0
        score = 0.25
    else:
        confirmed_ratio = confirmed_count / attempted_count
        failure_ratio = failed_count / attempted_count
        fallback_ratio = proxy_retained / attempted_count
        score = max(
            0.0,
            min(
                1.0,
                0.15
                + 0.80 * successful_operation_ratio
                + 0.20 * confirmed_ratio
                - 0.45 * failure_ratio
                - 0.25 * fallback_ratio,
            ),
        )

    label, level = _boolean_reliability_label(score, fallback_ratio, enabled)
    if checked_count <= 0 and skipped_count > 0:
        summary = (
            f"Boolean refinement skipped {skipped_count} face(s), usually because "
            "they were too small for stable swept-volume checks; proxy evidence was retained."
        )
        recommended_action = (
            "Review the skipped small-face evidence visually and keep it in the report as "
            "conservative proxy evidence."
        )
    elif failed_count > 0 and confirmed_count > 0:
        summary = (
            f"Boolean confirmed {confirmed_count} face(s) and retained "
            f"{proxy_retained} proxy face(s) after failure/skip."
        )
        recommended_action = (
            "Trust confirmed interference regions first, then review retained proxy faces "
            "as conservative manual-check evidence."
        )
    elif failed_count > 0:
        summary = (
            f"Boolean attempted {checked_count} face(s), but {failed_count} failed; "
            "the detector retained proxy evidence instead of dropping possible undercuts."
        )
        recommended_action = (
            "Treat this as proxy-heavy evidence and inspect the listed face failures before "
            "using the result for final mold-action decisions."
        )
    elif confirmed_count > 0:
        summary = f"Boolean confirmed interference on {confirmed_count} face(s)."
        recommended_action = (
            "Use the confirmed Boolean regions as primary undercut evidence."
        )
    else:
        summary = (
            "Boolean refinement completed without confirming interference above the "
            "configured volume tolerance."
        )
        recommended_action = (
            "Use the draft result as the main evidence; no Boolean-confirmed residual "
            "undercut was found for this pull direction."
        )

    return BooleanReliabilitySummary(
        enabled=True,
        reliability_score=score,
        reliability_label=label,
        reliability_level=level,
        checked_count=checked_count,
        confirmed_count=confirmed_count,
        failed_count=failed_count,
        skipped_count=skipped_count,
        proxy_retained_face_count=proxy_retained,
        proxy_retained_failed_count=proxy_failed,
        proxy_retained_skipped_count=proxy_skipped,
        successful_operation_ratio=successful_operation_ratio,
        confirmed_ratio=confirmed_ratio,
        failure_ratio=failure_ratio,
        fallback_ratio=fallback_ratio,
        failure_class_counts=_count_failure_classes(failure_details),
        skip_reason_counts=_count_skip_reasons(skip_reasons),
        summary=summary,
        recommended_action=recommended_action,
    )


def _group_adjacent_faces(part: PartGeometry, face_ids: list[int]) -> list[list[int]]:
    target = set(face_ids)
    visited: set[int] = set()
    groups: list[list[int]] = []

    for start in face_ids:
        if start in visited:
            continue
        group: list[int] = []
        queue: deque[int] = deque([start])
        visited.add(start)

        while queue:
            fid = queue.popleft()
            group.append(fid)
            for nbr in part.face_adjacency.get(fid, []):
                if nbr in target and nbr not in visited:
                    visited.add(nbr)
                    queue.append(nbr)

        groups.append(sorted(group))

    return groups


def _bbox_gap_mm(
    a_min: Vec3 | None,
    a_max: Vec3 | None,
    b_min: Vec3 | None,
    b_max: Vec3 | None,
) -> float | None:
    if a_min is None or a_max is None or b_min is None or b_max is None:
        return None
    dx = max(0.0, max(a_min[0] - b_max[0], b_min[0] - a_max[0]))
    dy = max(0.0, max(a_min[1] - b_max[1], b_min[1] - a_max[1]))
    dz = max(0.0, max(a_min[2] - b_max[2], b_min[2] - a_max[2]))
    return mag3((dx, dy, dz))


def _bbox_diag(dimensions: Vec3 | None) -> float:
    if dimensions is None:
        return 0.0
    return mag3(dimensions)


def _bbox_volume(dimensions: Vec3 | None) -> float:
    if dimensions is None:
        return 0.0
    return max(0.0, dimensions[0]) * max(0.0, dimensions[1]) * max(0.0, dimensions[2])


def _bbox_intersection_dimensions(
    a_min: Vec3 | None,
    a_max: Vec3 | None,
    b_min: Vec3 | None,
    b_max: Vec3 | None,
) -> Vec3 | None:
    if a_min is None or a_max is None or b_min is None or b_max is None:
        return None
    return (
        max(0.0, min(a_max[0], b_max[0]) - max(a_min[0], b_min[0])),
        max(0.0, min(a_max[1], b_max[1]) - max(a_min[1], b_min[1])),
        max(0.0, min(a_max[2], b_max[2]) - max(a_min[2], b_min[2])),
    )


def _bbox_overlap_ratio(analysis_a: BooleanShapeAnalysis, analysis_b: BooleanShapeAnalysis) -> float:
    intersection_dimensions = _bbox_intersection_dimensions(
        analysis_a.bbox_min,
        analysis_a.bbox_max,
        analysis_b.bbox_min,
        analysis_b.bbox_max,
    )
    intersection_volume = _bbox_volume(intersection_dimensions)
    min_volume = min(
        _bbox_volume(analysis_a.bbox_dimensions),
        _bbox_volume(analysis_b.bbox_dimensions),
    )
    if min_volume <= 1e-12:
        return 0.0
    return max(0.0, min(1.0, intersection_volume / min_volume))


def _bbox_size_ratio(analysis_a: BooleanShapeAnalysis, analysis_b: BooleanShapeAnalysis) -> float:
    volumes = sorted([
        _bbox_volume(analysis_a.bbox_dimensions),
        _bbox_volume(analysis_b.bbox_dimensions),
    ])
    if volumes[0] <= 1e-12:
        return 1.0
    return volumes[1] / volumes[0]


def _boolean_region_pair_interaction(
    analysis_a: BooleanShapeAnalysis,
    analysis_b: BooleanShapeAnalysis,
) -> tuple[str, float]:
    """
    Classify pair-level Boolean-region interaction from bbox overlap.

    This is a lightweight Phase 3 heuristic, not full volumetric decomposition.
    It flags nested/overlapping interference volumes so the feature can be
    treated as complex instead of a simple isolated side-action candidate.
    """
    overlap_ratio = _bbox_overlap_ratio(analysis_a, analysis_b)
    if overlap_ratio <= 0.0:
        return ("none", 0.0)

    size_ratio = _bbox_size_ratio(analysis_a, analysis_b)
    if overlap_ratio >= 0.85 and size_ratio >= 1.40:
        return ("nested", overlap_ratio)
    if overlap_ratio >= 0.20:
        return ("overlapping", overlap_ratio)
    return ("touching", overlap_ratio)


def _feature_interaction_summary(
    group: list[int],
    interference_by_face: dict[int, BooleanInterferenceMetrics],
) -> tuple[str, list[str]]:
    boolean_face_ids = [
        face_id for face_id in sorted(group)
        if (
            face_id in interference_by_face
            and interference_by_face[face_id].shape_analysis.available
        )
    ]
    if len(boolean_face_ids) < 2:
        return ("none", ["single or no Boolean-confirmed region in feature"])

    nested_pairs: list[str] = []
    overlapping_pairs: list[str] = []
    touching_pairs: list[str] = []

    for index, face_a in enumerate(boolean_face_ids):
        analysis_a = interference_by_face[face_a].shape_analysis
        for face_b in boolean_face_ids[index + 1:]:
            analysis_b = interference_by_face[face_b].shape_analysis
            interaction_type, overlap_ratio = _boolean_region_pair_interaction(
                analysis_a,
                analysis_b,
            )
            description = (
                f"{interaction_type} pair {face_a}-{face_b}: "
                f"bbox_overlap_ratio={overlap_ratio:.3f}"
            )
            if interaction_type == "nested":
                nested_pairs.append(description)
            elif interaction_type == "overlapping":
                overlapping_pairs.append(description)
            elif interaction_type == "touching":
                touching_pairs.append(description)

    factors = [
        f"boolean_region_count={len(boolean_face_ids)}",
        f"nested_pair_count={len(nested_pairs)}",
        f"overlapping_pair_count={len(overlapping_pairs)}",
        f"touching_pair_count={len(touching_pairs)}",
    ]
    factors.extend(nested_pairs[:5])
    factors.extend(overlapping_pairs[:5])
    factors.extend(touching_pairs[:5])

    if nested_pairs:
        return ("nested", factors)
    if overlapping_pairs:
        return ("overlapping", factors)
    if touching_pairs:
        return ("touching", factors)
    return ("none", factors + ["no overlapping or nested Boolean regions inside feature"])


def _group_undercut_faces_with_boolean_proximity(
    part: PartGeometry,
    face_ids: list[int],
    interference_by_face: dict[int, BooleanInterferenceMetrics],
) -> FeatureGroupingResult:
    """
    Group undercut faces using topology plus Boolean-region proximity.

    Face adjacency remains the baseline.  Boolean proximity adds edges between
    disconnected faces when their confirmed interference volumes overlap or lie
    very near one another.  This keeps proxy-only behavior stable and improves
    grouping only where local volumetric evidence exists.
    """
    target = set(face_ids)
    if not target:
        return FeatureGroupingResult(groups=[], method="face-adjacency")

    graph: dict[int, set[int]] = {face_id: set() for face_id in sorted(target)}
    topology_edges = 0
    for face_id in target:
        for neighbor_id in part.face_adjacency.get(face_id, []):
            if neighbor_id in target:
                graph[face_id].add(neighbor_id)
                graph[neighbor_id].add(face_id)
                topology_edges += 1

    cfg = settings.dfm.direction_search
    proximity_factor = max(0.0, float(cfg.boolean_grouping_proximity_factor))
    min_proximity = max(0.0, float(cfg.boolean_grouping_min_proximity_mm))
    boolean_face_ids = [
        face_id for face_id in sorted(target)
        if (
            face_id in interference_by_face
            and interference_by_face[face_id].shape_analysis.available
        )
    ]
    proximity_links: list[tuple[int, int, float, float]] = []
    overlap_links: list[tuple[int, int, str, float]] = []
    nested_links: list[tuple[int, int, str, float]] = []

    for index, face_a in enumerate(boolean_face_ids):
        analysis_a = interference_by_face[face_a].shape_analysis
        for face_b in boolean_face_ids[index + 1:]:
            analysis_b = interference_by_face[face_b].shape_analysis
            interaction_type, overlap_ratio = _boolean_region_pair_interaction(
                analysis_a,
                analysis_b,
            )
            if interaction_type in {"overlapping", "touching", "nested"}:
                overlap_links.append((face_a, face_b, interaction_type, overlap_ratio))
                if interaction_type == "nested":
                    nested_links.append((face_a, face_b, interaction_type, overlap_ratio))
            if face_b in graph[face_a]:
                continue
            gap = _bbox_gap_mm(
                analysis_a.bbox_min,
                analysis_a.bbox_max,
                analysis_b.bbox_min,
                analysis_b.bbox_max,
            )
            if gap is None:
                continue
            local_size = max(
                _bbox_diag(analysis_a.bbox_dimensions),
                _bbox_diag(analysis_b.bbox_dimensions),
                part.bounding_box.diagonal * 1e-6,
            )
            threshold = max(min_proximity, local_size * proximity_factor)
            if gap <= threshold:
                graph[face_a].add(face_b)
                graph[face_b].add(face_a)
                proximity_links.append((face_a, face_b, gap, threshold))

    visited: set[int] = set()
    groups: list[list[int]] = []
    for start in sorted(target):
        if start in visited:
            continue
        group: list[int] = []
        queue: deque[int] = deque([start])
        visited.add(start)
        while queue:
            face_id = queue.popleft()
            group.append(face_id)
            for neighbor_id in sorted(graph[face_id]):
                if neighbor_id not in visited:
                    visited.add(neighbor_id)
                    queue.append(neighbor_id)
        groups.append(sorted(group))

    factors = [
        f"topology_edge_count={topology_edges // 2}",
        f"boolean_candidate_face_count={len(boolean_face_ids)}",
        f"proximity_link_count={len(proximity_links)}",
        f"overlap_pair_count={len(overlap_links)}",
        f"nested_pair_count={len(nested_links)}",
        f"proximity_factor={proximity_factor:.3f}",
        f"min_proximity_mm={min_proximity:.3f}",
    ]
    for face_a, face_b, gap, threshold in proximity_links[:10]:
        factors.append(
            f"linked {face_a}-{face_b}: bbox_gap_mm={gap:.4f} <= threshold_mm={threshold:.4f}"
        )
    for face_a, face_b, interaction_type, overlap_ratio in overlap_links[:10]:
        factors.append(
            f"{interaction_type} {face_a}-{face_b}: bbox_overlap_ratio={overlap_ratio:.3f}"
        )

    method = (
        "face-adjacency + boolean-region-proximity/interactions"
        if proximity_links and overlap_links
        else "face-adjacency + boolean-region-proximity"
        if proximity_links
        else "face-adjacency + boolean-region-interactions"
        if overlap_links
        else "face-adjacency"
    )
    return FeatureGroupingResult(
        groups=groups,
        method=method,
        factors=factors,
        proximity_link_count=len(proximity_links),
        overlap_pair_count=len(overlap_links),
        nested_pair_count=len(nested_links),
        interaction_pair_count=len(overlap_links),
    )


def _concave_neighbor_closure(
    part: PartGeometry,
    face_ids: list[int],
    baseline_groups: list[list[int]],
) -> set[int]:
    """
    Discovered 2026-08-19 (Part1 +Z diagnostic pass, see CHANGELOG.md): a
    face with genuine undercut evidence can share a CONCAVE edge with an
    immediately adjacent face that, evaluated entirely on its own, clears
    (e.g. `ray_verified_clear`) -- Part1's rim rosette is the concrete case:
    each near-zero-draft "critical" face's one ~45deg-backward neighbor
    passes its own ray-clearance check along ITS natural access direction
    (`_face_access_direction`), yet the two faces share a concave crease --
    the actual geometric signature of a notch/pocket (a convex or tangent
    edge is an ordinary outward corner, never this). Individually-correct
    per-face evidence for the neighbor is not in question and is left
    completely untouched by this function (it never touches `undercut_ids`,
    `is_undercut`, or any area/percentage total) -- this ONLY widens the
    candidate pool handed to feature GROUPING, so the two faces can be
    reported as the single physical feature they actually are, via the
    EXISTING, unmodified adjacency-based grouping BFS in
    `_group_undercut_faces_with_boolean_proximity`.

    ``baseline_groups`` (the SAME grouping function's own output on the
    UN-widened ``face_ids``, computed by the caller first) is the guard a
    first version of this function (2026-08-19) was missing, and it is not
    optional: Part1's 4 cantilever legs each independently satisfied the
    "concave edge to an already-flagged face" test against the SAME central
    stepped-boss face (a real, single face genuinely concave-bordering all
    4 legs, per D-057's part description) -- a naive per-face closure
    silently fused all 4 legs (and separately, two adjacent rim features)
    into one giant feature through that shared hub face. A closure
    candidate is only a genuine single-feature "completion" if it concave-
    borders flagged faces from EXACTLY ONE pre-existing baseline group; one
    that concave-borders two or more groups is a structural connector
    BETWEEN distinct physical features (e.g. the boss, or a rim transition),
    never part of just one of them, and must never be added -- doing so
    would silently misrepresent N independent problems as one.

    Deliberately narrow and NOT face-ID-specific: any face directly
    (one-hop) adjacent to an already-flagged face via a concave shared edge
    qualifies (subject to the single-group guard above), regardless of part
    or location.
    """
    group_of: dict[int, int] = {}
    for group_index, group in enumerate(baseline_groups):
        for fid in group:
            group_of[fid] = group_index

    candidate_sources: dict[int, set[int]] = {}
    flagged = set(face_ids)
    for face_id in face_ids:
        own_edges = {e.edge_id: e for e in part.get_face_edges(face_id)}
        if not own_edges:
            continue
        for neighbor_id in part.face_adjacency.get(face_id, []):
            if neighbor_id in flagged:
                continue
            neighbor_edge_ids = {e.edge_id for e in part.get_face_edges(neighbor_id)}
            shared = set(own_edges) & neighbor_edge_ids
            if not shared:
                continue
            if any(own_edges[eid].convexity == "concave" for eid in shared):
                candidate_sources.setdefault(neighbor_id, set()).add(group_of.get(face_id, face_id))

    return {
        neighbor_id
        for neighbor_id, source_groups in candidate_sources.items()
        if len(source_groups) == 1
    }


def _face_access_direction(face: FaceData, pull_direction: Vec3) -> Vec3:
    """
    Choose which mold half should access this face.

    Positive n·d faces are tested along +d; negative faces along -d.  Near
    parting faces default to +d because they are already tracked separately.
    """
    signed = face.signed_dot(pull_direction)
    if signed < 0.0:
        return (-pull_direction[0], -pull_direction[1], -pull_direction[2])
    return pull_direction


# ---------------------------------------------------------------------------
# D-061 (2026-08-16): adaptive ray-based sweep-distance verification.
#
# Root cause established by direct experiment (see docs/DECISIONS_AND_
# ALGORITHMS.md D-061): the swept-face Boolean's whole-part-bbox-diagonal-
# derived sweep distance is what causes OCC's BRepAlgoAPI_Common to fail on
# certain faces (empirically, Part1's leg-transition BSpline faces) -- not
# NURBS complexity, not target-shape size (a local-clipped target fails
# identically). A short sweep succeeds; the failure is non-monotonic with
# distance, consistent with the swept prism's far end grazing unrelated,
# distant part geometry. This section MEASURES a safe sweep distance
# directly via ray-casting instead of guessing one, before ever
# constructing the (expensive, sometimes-failing) swept prism.
#
# Two OCC failure modes were proven and must NOT be reintroduced:
#   1. IntCurveSurface's own Transition() (IN/OUT/Tangent) is NOT reliable
#      for entry/exit pairing -- tested directly on UC3's known [14,22]mm
#      interval and BOTH boundaries reported "IN". Do not use it for
#      interval logic.
#   2. A ray cast from a face's exact UV centroid can silently MISS a real
#      intersection when the ray runs exactly along an axis of rotational
#      symmetry (proven on UC3 face 4: centroid ray found only the far
#      exit at 22mm, missing the real entry at 14mm; a 5mm-offset ray
#      found both). This is why coverage uses a structured multi-point
#      grid, never a single centroid sample.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RayVerificationResult:
    """
    Outcome of adaptive ray-based clearance verification for one candidate
    face, evaluated BEFORE any swept-face Boolean is attempted.

    ``status``:
      ``"clear"``           -- two independent grid densities (initial and
                                escalated) both found zero material anywhere
                                sampled. A bounded-confidence geometric
                                result, NOT a Boolean proof -- see D-061.
      ``"material_found"``  -- at least one sample ray found a genuine
                                material interval. Trusted immediately (a
                                positive finding is exact local evidence,
                                not a coverage question) -- never re-checked
                                at a denser grid merely to "confirm" it.
      ``"inconclusive"``    -- samples disagree on existence (some find
                                material, some don't) even at the maximum
                                configured grid density. Must fall back to
                                the existing whole-part-diagonal Boolean,
                                never silently resolved either way.
    """
    status: str
    sweep_distance_mm: float | None = None
    max_interval_end_mm: float | None = None
    grid_sizes_tried: tuple[int, ...] = ()
    sample_count: int = 0
    samples_with_material: int = 0
    elapsed_s: float = 0.0
    reason: str = ""


def _face_uv_grid_points(occ_face: object, grid: int) -> list[Vec3]:
    """
    Structured ``grid x grid`` UV-sample points on a face's own surface.

    Reuses the exact UVBounds-grid pattern already used and tested by
    ``parting_line_v2.regions._sample_face_g`` (same rationale: "a single
    UV-centroid sample cannot see [local variation] by construction") --
    evaluated here for the 3-D point (``GeomLProp_SLProps.Value()``)
    instead of the surface normal, since ray origins are needed, not
    orientation data. Kept local to this module rather than sharing a
    cross-module helper for a five-line OCC call.
    """
    try:
        u_min, u_max, v_min, v_max = breptools.UVBounds(occ_face)
    except Exception:
        return []
    if not all(math.isfinite(x) for x in (u_min, u_max, v_min, v_max)):
        return []
    try:
        surface = BRep_Tool.Surface(occ_face)
    except Exception:
        return []

    points: list[Vec3] = []
    for i in range(grid):
        for j in range(grid):
            u = u_min + (u_max - u_min) * (i + 0.5) / grid
            v = v_min + (v_max - v_min) * (j + 0.5) / grid
            try:
                props = GeomLProp_SLProps(surface, u, v, 1, 1e-9)
                if not props.IsNormalDefined():
                    continue
                p = props.Value()
                points.append((p.X(), p.Y(), p.Z()))
            except Exception:
                continue
    return points


def _material_intervals_along_ray(
    shape: object,
    origin: Vec3,
    direction: Vec3,
    origin_face: object,
    max_w: float,
    tol: float = 1e-6,
    self_tol: float | None = None,
    classifier: object | None = None,
) -> list[tuple[float, float]]:
    """
    Exact material intervals along an infinite ray, via direct solid
    point-classification -- NOT via IntCurveSurface's own Transition()
    (proven unreliable for this, see module docstring above).

    ``classifier`` (O9, 2026-08-17): an already-constructed
    ``BRepClass3d_SolidClassifier(shape)``, when the caller has one.
    ``BRepClass3d_SolidClassifier``'s constructor depends only on
    ``shape`` -- never on the ray's origin/direction or the candidate
    face -- so a single instance built once for ``part.occ_shape`` is
    safe to reuse across every ray this function is called for within
    one ``detect_undercuts()`` call (O8's forensic measurement found this
    reconstructed ~1,200 times per direction, 19-44% of total runtime).
    Reuse changes nothing about ``.Perform()``/``.State()``'s per-point
    result -- OCC's own API contract for this class is exactly
    "construct once against a solid, ``.Perform()`` many times".
    Defaults to ``None``, in which case this function constructs its own
    (byte-identical to pre-O9 behaviour) -- every existing direct caller
    (tests, the validation scripts) is unaffected.

    1. Collect every intersection of the ray with ``shape``
       (``BRepIntCurveSurface_Inter`` -- ``W()``/``Pnt()``/``Face()``).
    2. Filter self-hits: any hit at or below ``self_tol``, and any hit
       whose face IS (``TopoDS_Shape.IsSame``) ``origin_face`` -- proven
       necessary: a curved candidate face re-intersects itself under a
       laterally offset ray (a curvature artifact, not real geometry).
    3. Classify the MIDPOINT of every segment between consecutive
       remaining boundaries (``self_tol``, hit_1, ..., hit_n, max_w) with
       ``BRepClass3d_SolidClassifier`` -- a segment is material iff its
       midpoint classifies ``TopAbs_IN``. Adjacent material segments are
       merged into one interval. Supports any number of disjoint
       intervals; does not assume a single entry/exit pair.

    The FIRST boundary is ``self_tol``, never exactly 0 -- avoids
    classifying a point exactly ON the origin face's own surface (a
    degenerate case for point-in-solid classification), the same "don't
    count the original face contact as interference" concern
    ``_swept_face_interference_volume``'s own offset-epsilon step already
    exists to avoid. ``self_tol`` defaults to that same epsilon scale
    (``boolean_offset_factor``/``boolean_min_offset_mm``), not an
    arbitrary constant. NOTE: this is a small, defensive margin only --
    real, GENUINE material starting very close to the origin (verified
    directly on Part1 face 207: OUT at w=0.01, ON at w=0.1, IN from
    w=0.5 onward) is NOT filtered by this and must not be; only the
    literal on-surface degenerate point is excluded.

    Exact-match-verified against UC3's hand-computed ground truth
    (interval [14.0, 22.0]mm, the known 8mm-thick/14mm-gap geometry).
    """
    if self_tol is None:
        cfg = settings.dfm.direction_search
        self_tol = max(max_w * cfg.boolean_offset_factor, cfg.boolean_min_offset_mm)

    line = gp_Lin(gp_Pnt(*origin), gp_Dir(*direction))
    inter = BRepIntCurveSurface_Inter()
    inter.Init(shape, line, tol)
    boundaries: list[float] = [self_tol]
    while inter.More():
        w = inter.W()
        if w > self_tol and w <= max_w and not inter.Face().IsSame(origin_face):
            boundaries.append(w)
        inter.Next()
    boundaries.append(max_w)
    boundaries = sorted(set(b for b in boundaries if b >= self_tol))

    classifier = classifier if classifier is not None else BRepClass3d_SolidClassifier(shape)
    intervals: list[tuple[float, float]] = []
    for i in range(len(boundaries) - 1):
        a, b = boundaries[i], boundaries[i + 1]
        mid = (a + b) / 2.0
        p = gp_Pnt(
            origin[0] + direction[0] * mid,
            origin[1] + direction[1] * mid,
            origin[2] + direction[2] * mid,
        )
        classifier.Perform(p, tol)
        if classifier.State() == TopAbs_IN:
            if intervals and intervals[-1][1] == a:
                intervals[-1] = (intervals[-1][0], b)
            else:
                intervals.append((a, b))
    return intervals


def _ray_verify_face_clearance(
    part: PartGeometry,
    face: FaceData,
    pull_direction: Vec3,
    cfg: object,
    classifier: object | None = None,
) -> RayVerificationResult:
    """
    Adaptive ray-based clearance check for one candidate face (D-061).

    ``classifier`` (O9, 2026-08-17): passed straight through to every
    ``_material_intervals_along_ray`` call below -- see that function's
    docstring. ``None`` (the default) preserves the exact pre-O9 behaviour
    of constructing a fresh classifier per ray.

    Escalation policy, chosen to satisfy "never silently convert
    insufficient coverage into clean":
      - ANY sample, at ANY grid density, finding a genuine material
        interval is trusted immediately -- a positive finding is exact
        local evidence (verified against UC3's ground truth), not a
        coverage question, so it is never re-checked at a denser grid
        merely to "confirm" it. The reported sweep distance is the
        SAFE MAXIMUM interval end across every sample that found one
        (never the first hit -- see D-061 Gap 1).
      - Only a unanimous "nothing found" across ALL samples at the
        CURRENT grid density is treated as provisional. If the escalated
        (denser) grid also finds nothing, both independent densities
        agree and the face converges to "clear". If the maximum
        configured grid is reached and samples still disagree (mixed
        found/not-found), the result is "inconclusive" -- never resolved
        either way, per explicit instruction.

    Mock-safety (established project pattern, e.g. ``parting_line.py``'s
    ``isinstance(edge.occ_edge, TopoDS_Edge)`` guard): calling real SWIG-
    wrapped OCC C++ functions on a non-OCC object (a ``MagicMock`` in
    mock-based unit tests) does not raise a catchable Python exception --
    it can hang at the native layer, uncatchable by any try/except. A
    fast, pure-Python ``isinstance`` check before any OCC call is the only
    safe guard. Existing mock-based Boolean tests patch
    ``_swept_face_interference_volume`` itself (never reaching real OCC),
    which does NOT protect this new, earlier call site -- this guard is
    required, not optional.
    """
    if not isinstance(face.occ_face, TopoDS_Face):
        return RayVerificationResult(
            status="inconclusive",
            reason="occ_face is not a real TopoDS_Face; ray verification skipped.",
        )
    t0 = time.perf_counter()
    max_w = max(part.bounding_box.diagonal, 1.0)
    margin = max(
        max_w * settings.dfm.direction_search.boolean_offset_factor,
        settings.dfm.direction_search.boolean_min_offset_mm,
    )
    access = _face_access_direction(face, pull_direction)

    grid_sizes = sorted({
        max(1, int(getattr(cfg, "ray_verification_initial_grid", 3))),
        max(1, int(getattr(cfg, "ray_verification_max_grid", 5))),
    })

    tried: list[int] = []
    total_samples = 0
    for grid in grid_sizes:
        tried.append(grid)
        points = _face_uv_grid_points(face.occ_face, grid)
        if not points:
            continue
        total_samples = len(points)
        max_end = None
        samples_with_material = 0
        for origin in points:
            intervals = _material_intervals_along_ray(
                part.occ_shape, origin, access, face.occ_face, max_w,
                classifier=classifier,
            )
            if intervals:
                samples_with_material += 1
                interval_max_end = max(end for _, end in intervals)
                max_end = interval_max_end if max_end is None else max(max_end, interval_max_end)

        if samples_with_material == 0:
            # Unanimous "clear" at this density -- escalate to the next
            # configured grid (if any) before trusting it.
            if grid == grid_sizes[-1]:
                return RayVerificationResult(
                    status="clear",
                    grid_sizes_tried=tuple(tried),
                    sample_count=total_samples,
                    samples_with_material=0,
                    elapsed_s=time.perf_counter() - t0,
                    reason=(
                        f"{len(tried)} independent grid densities "
                        f"({tried}) unanimously found zero material."
                    ),
                )
            continue  # escalate

        if samples_with_material == total_samples:
            # Unanimous "material found" -- trust immediately, no escalation.
            return RayVerificationResult(
                status="material_found",
                sweep_distance_mm=max_end + margin,
                max_interval_end_mm=max_end,
                grid_sizes_tried=tuple(tried),
                sample_count=total_samples,
                samples_with_material=samples_with_material,
                elapsed_s=time.perf_counter() - t0,
                reason=f"all {total_samples} samples at grid={grid} found material.",
            )

        # Mixed within this grid: a positive finding is still trusted
        # immediately (never discard real evidence), using the safe max.
        return RayVerificationResult(
            status="material_found",
            sweep_distance_mm=max_end + margin,
            max_interval_end_mm=max_end,
            grid_sizes_tried=tuple(tried),
            sample_count=total_samples,
            samples_with_material=samples_with_material,
            elapsed_s=time.perf_counter() - t0,
            reason=(
                f"{samples_with_material}/{total_samples} samples at "
                f"grid={grid} found material; using the safe maximum extent."
            ),
        )

    return RayVerificationResult(
        status="inconclusive",
        grid_sizes_tried=tuple(tried),
        sample_count=total_samples,
        elapsed_s=time.perf_counter() - t0,
        reason="No usable UV sample points across any configured grid density.",
    )


def _boolean_cache_key(face_id: int, pull_direction: Vec3) -> tuple[int, int, int, int]:
    return (
        face_id,
        int(round(pull_direction[0] * 1_000_000)),
        int(round(pull_direction[1] * 1_000_000)),
        int(round(pull_direction[2] * 1_000_000)),
    )


def _shape_volume(shape: object) -> float:
    props = GProp_GProps()
    brepgprop.VolumeProperties(shape, props)
    return max(0.0, float(props.Mass()))


def _count_shape_subshapes(shape: object, top_abs_kind: object) -> int:
    count = 0
    explorer = TopExp_Explorer(shape, top_abs_kind)
    while explorer.More():
        count += 1
        explorer.Next()
    return count


def _shape_center_of_mass(shape: object) -> Vec3 | None:
    props = GProp_GProps()
    brepgprop.VolumeProperties(shape, props)
    point = props.CentreOfMass()
    return (float(point.X()), float(point.Y()), float(point.Z()))


def _analyze_boolean_shape(shape: object | None) -> BooleanShapeAnalysis:
    """
    Extract lightweight geometry metadata from a Boolean intersection shape.

    Raw OCC shapes stay in memory.  This function returns only serializable
    measurements that later steps can use for typing, release direction, and
    visualization metadata.
    """
    if shape is None:
        return BooleanShapeAnalysis(
            available=False,
            method="no-shape",
            failure_reason="No Boolean intersection shape was captured.",
        )
    if not _OCC_BOOLEAN_AVAILABLE:
        return BooleanShapeAnalysis(
            available=False,
            method="occ-unavailable",
            failure_reason="OCC geometry analysis tools are unavailable in this runtime.",
        )

    try:
        bbox_points = _shape_bbox_points(shape)
        if bbox_points:
            xs = [point[0] for point in bbox_points]
            ys = [point[1] for point in bbox_points]
            zs = [point[2] for point in bbox_points]
            bbox_min = (min(xs), min(ys), min(zs))
            bbox_max = (max(xs), max(ys), max(zs))
            bbox_dimensions = (
                bbox_max[0] - bbox_min[0],
                bbox_max[1] - bbox_min[1],
                bbox_max[2] - bbox_min[2],
            )
            bbox_center = (
                (bbox_min[0] + bbox_max[0]) * 0.5,
                (bbox_min[1] + bbox_max[1]) * 0.5,
                (bbox_min[2] + bbox_max[2]) * 0.5,
            )
        else:
            bbox_min = None
            bbox_max = None
            bbox_dimensions = None
            bbox_center = None

        return BooleanShapeAnalysis(
            available=True,
            vertex_count=_count_shape_subshapes(shape, TopAbs_VERTEX),
            edge_count=_count_shape_subshapes(shape, TopAbs_EDGE),
            bbox_min=bbox_min,
            bbox_max=bbox_max,
            bbox_center=bbox_center,
            bbox_dimensions=bbox_dimensions,
            center_of_mass=_shape_center_of_mass(shape),
            volume_mm3=_shape_volume(shape),
            method="occ-topology-bbox-mass",
        )
    except Exception as exc:  # noqa: BLE001
        return BooleanShapeAnalysis(
            available=False,
            method="analysis-failed",
            failure_reason=str(exc) or exc.__class__.__name__,
        )


def _combine_boolean_region_geometry(
    source_face_ids: list[int],
    analyses: list[BooleanShapeAnalysis],
) -> BooleanRegionGeometry:
    valid = [analysis for analysis in analyses if analysis.available]
    failure_reasons = [
        analysis.failure_reason
        for analysis in analyses
        if analysis.failure_reason
    ]
    if not valid:
        return BooleanRegionGeometry(
            available=False,
            shape_count=len(analyses),
            source_face_ids=source_face_ids,
            analyses=analyses,
            failure_reasons=failure_reasons,
        )

    bbox_mins = [analysis.bbox_min for analysis in valid if analysis.bbox_min is not None]
    bbox_maxs = [analysis.bbox_max for analysis in valid if analysis.bbox_max is not None]
    if bbox_mins and bbox_maxs:
        bbox_min = (
            min(point[0] for point in bbox_mins),
            min(point[1] for point in bbox_mins),
            min(point[2] for point in bbox_mins),
        )
        bbox_max = (
            max(point[0] for point in bbox_maxs),
            max(point[1] for point in bbox_maxs),
            max(point[2] for point in bbox_maxs),
        )
        bbox_dimensions = (
            bbox_max[0] - bbox_min[0],
            bbox_max[1] - bbox_min[1],
            bbox_max[2] - bbox_min[2],
        )
        bbox_center = (
            (bbox_min[0] + bbox_max[0]) * 0.5,
            (bbox_min[1] + bbox_max[1]) * 0.5,
            (bbox_min[2] + bbox_max[2]) * 0.5,
        )
    else:
        bbox_min = None
        bbox_max = None
        bbox_dimensions = None
        bbox_center = None

    total_volume = sum(max(0.0, analysis.volume_mm3) for analysis in valid)
    centers = [
        (analysis.center_of_mass, max(0.0, analysis.volume_mm3))
        for analysis in valid
        if analysis.center_of_mass is not None
    ]
    if centers and total_volume > 0.0:
        center_of_mass = (
            sum(center[0] * weight for center, weight in centers) / total_volume,
            sum(center[1] * weight for center, weight in centers) / total_volume,
            sum(center[2] * weight for center, weight in centers) / total_volume,
        )
    elif centers:
        count = float(len(centers))
        center_of_mass = (
            sum(center[0] for center, _ in centers) / count,
            sum(center[1] for center, _ in centers) / count,
            sum(center[2] for center, _ in centers) / count,
        )
    else:
        center_of_mass = bbox_center

    return BooleanRegionGeometry(
        available=True,
        shape_count=len(valid),
        source_face_ids=source_face_ids,
        vertex_count=sum(analysis.vertex_count for analysis in valid),
        edge_count=sum(analysis.edge_count for analysis in valid),
        bbox_min=bbox_min,
        bbox_max=bbox_max,
        bbox_center=bbox_center,
        bbox_dimensions=bbox_dimensions,
        center_of_mass=center_of_mass,
        volume_mm3=total_volume,
        analyses=analyses,
        failure_reasons=failure_reasons,
    )


def _face_area_tolerance(part: PartGeometry) -> float:
    cfg = settings.dfm.direction_search
    diagonal = max(part.bounding_box.diagonal, 1.0)
    return max(
        cfg.boolean_min_face_area_mm2,
        diagonal * diagonal * cfg.boolean_min_face_area_factor,
    )


def _projection_span(points: list[Vec3], direction: Vec3) -> float:
    if not points:
        return 0.0
    projections = [_project(point, direction) for point in points]
    return max(0.0, max(projections) - min(projections))


def _reference_projection_depth(points: list[Vec3], direction: Vec3, reference: Vec3) -> float:
    if not points:
        return 0.0
    reference_projection = _project(reference, direction)
    max_projection = max(_project(point, direction) for point in points)
    return max(0.0, max_projection - reference_projection)


def _shape_bbox_points(shape: object) -> list[Vec3]:
    box = Bnd_Box()
    brepbndlib.Add(shape, box)
    if box.IsVoid():
        return []
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return [
        (x, y, z)
        for x in (xmin, xmax)
        for y in (ymin, ymax)
        for z in (zmin, zmax)
    ]


def _shape_vertex_points(shape: object) -> list[Vec3]:
    """
    Return unique B-Rep vertices from a Boolean result shape.

    Vertices give an oriented projection estimate that is usually tighter than
    projecting the axis-aligned bounding box corners.  Curved-only regions can
    still have sparse vertices, so callers keep bbox and volume/area fallbacks.
    """
    points: list[Vec3] = []
    seen: set[tuple[int, int, int]] = set()
    explorer = TopExp_Explorer(shape, TopAbs_VERTEX)
    while explorer.More():
        vertex = topods.Vertex(explorer.Current())
        point = BRep_Tool.Pnt(vertex)
        coords = (float(point.X()), float(point.Y()), float(point.Z()))
        key = (
            int(round(coords[0] * 1_000_000)),
            int(round(coords[1] * 1_000_000)),
            int(round(coords[2] * 1_000_000)),
        )
        if key not in seen:
            seen.add(key)
            points.append(coords)
        explorer.Next()
    return points


def _select_boolean_depth(
    vertex_reference_depth: float,
    vertex_span_depth: float,
    bbox_reference_depth: float,
    bbox_span_depth: float,
    volume_area_depth: float,
) -> tuple[float, str, float, float]:
    estimate = _select_boolean_depth_details(
        vertex_reference_depth=vertex_reference_depth,
        vertex_span_depth=vertex_span_depth,
        bbox_reference_depth=bbox_reference_depth,
        bbox_span_depth=bbox_span_depth,
        volume_area_depth=volume_area_depth,
    )
    return (
        estimate.depth_mm,
        estimate.method,
        estimate.reference_depth_mm,
        estimate.span_depth_mm,
    )


def _select_boolean_depth_details(
    vertex_reference_depth: float,
    vertex_span_depth: float,
    bbox_reference_depth: float,
    bbox_span_depth: float,
    volume_area_depth: float,
) -> BooleanDepthEstimate:
    """
    Choose the best available Boolean depth proxy.

    Priority:
      1. Vertex reference depth, because it measures travel beyond the offset
         source face in the access direction.
      2. Vertex span depth when reference depth is zero but the region has real
         extent along access direction.
      3. BBox reference/span fallback when vertices are unavailable.
      4. Volume/area only as a dimensional fallback.

    Volume/area deliberately no longer overrides geometric reference/span
    evidence.  It is useful when topology is sparse, but it can exaggerate
    true release depth on broad shallow regions.
    """
    evidence = {
        "vertex_reference_depth_mm": round(max(0.0, vertex_reference_depth), 6),
        "vertex_span_depth_mm": round(max(0.0, vertex_span_depth), 6),
        "bbox_reference_depth_mm": round(max(0.0, bbox_reference_depth), 6),
        "bbox_span_depth_mm": round(max(0.0, bbox_span_depth), 6),
        "volume_area_depth_mm": round(max(0.0, volume_area_depth), 6),
    }
    factors: list[str] = []

    vertex_reference = max(0.0, vertex_reference_depth)
    vertex_span = max(0.0, vertex_span_depth)
    bbox_reference = max(0.0, bbox_reference_depth)
    bbox_span = max(0.0, bbox_span_depth)
    volume_area = max(0.0, volume_area_depth)

    if vertex_reference > 0.0:
        if vertex_span > vertex_reference * 1.5:
            factors.append("vertex span exceeds reference depth; retained reference depth to avoid span overestimate")
        if volume_area > vertex_reference * 1.5:
            factors.append("volume/area fallback exceeded vertex reference and was not allowed to override geometry")
        return BooleanDepthEstimate(
            depth_mm=vertex_reference,
            method="vertex-reference",
            reference_depth_mm=vertex_reference,
            span_depth_mm=vertex_span,
            evidence=evidence,
            factors=factors + ["selected vertex reference depth"],
        )

    if vertex_span > 0.0:
        if volume_area > vertex_span * 1.5:
            factors.append("volume/area fallback exceeded vertex span and was not allowed to override geometry")
        return BooleanDepthEstimate(
            depth_mm=vertex_span,
            method="vertex-span",
            reference_depth_mm=vertex_reference,
            span_depth_mm=vertex_span,
            evidence=evidence,
            factors=factors + ["selected vertex span because reference depth was zero"],
        )

    if bbox_reference > 0.0:
        if bbox_span > bbox_reference * 1.5:
            factors.append("bbox span exceeds reference depth; retained reference depth to avoid bbox overestimate")
        if volume_area > bbox_reference * 1.5:
            factors.append("volume/area fallback exceeded bbox reference and was not allowed to override geometry")
        return BooleanDepthEstimate(
            depth_mm=bbox_reference,
            method="bbox-reference",
            reference_depth_mm=bbox_reference,
            span_depth_mm=bbox_span,
            evidence=evidence,
            factors=factors + ["selected bbox reference depth"],
        )

    if bbox_span > 0.0:
        if volume_area > bbox_span * 1.5:
            factors.append("volume/area fallback exceeded bbox span and was not allowed to override geometry")
        return BooleanDepthEstimate(
            depth_mm=bbox_span,
            method="bbox-span",
            reference_depth_mm=bbox_reference,
            span_depth_mm=bbox_span,
            evidence=evidence,
            factors=factors + ["selected bbox span because reference depth was zero"],
        )

    if volume_area > 0.0:
        return BooleanDepthEstimate(
            depth_mm=volume_area,
            method="volume-area",
            reference_depth_mm=0.0,
            span_depth_mm=0.0,
            evidence=evidence,
            factors=["selected volume/area fallback because no projection depth was available"],
        )

    return BooleanDepthEstimate(
        depth_mm=0.0,
        method="none",
        reference_depth_mm=0.0,
        span_depth_mm=0.0,
        evidence=evidence,
        factors=["no usable Boolean depth evidence"],
    )


def _estimate_boolean_depth(
    shape: object,
    face: FaceData,
    access_direction: Vec3,
    offset_mm: float,
    volume_mm3: float,
) -> tuple[float, str, float, float]:
    estimate = _estimate_boolean_depth_details(
        shape=shape,
        face=face,
        access_direction=access_direction,
        offset_mm=offset_mm,
        volume_mm3=volume_mm3,
    )
    return (
        estimate.depth_mm,
        estimate.method,
        estimate.reference_depth_mm,
        estimate.span_depth_mm,
    )


def _estimate_boolean_depth_details(
    shape: object,
    face: FaceData,
    access_direction: Vec3,
    offset_mm: float,
    volume_mm3: float,
) -> BooleanDepthEstimate:
    reference_point = (
        face.centroid[0] + access_direction[0] * offset_mm,
        face.centroid[1] + access_direction[1] * offset_mm,
        face.centroid[2] + access_direction[2] * offset_mm,
    )
    volume_area_depth = volume_mm3 / face.area if face.area > 0.0 else 0.0

    vertex_points: list[Vec3] = []
    try:
        vertex_points = _shape_vertex_points(shape)
    except Exception:  # noqa: BLE001
        vertex_points = []

    bbox_points: list[Vec3] = []
    try:
        bbox_points = _shape_bbox_points(shape)
    except Exception:  # noqa: BLE001
        bbox_points = []

    estimate = _select_boolean_depth_details(
        vertex_reference_depth=_reference_projection_depth(
            vertex_points,
            access_direction,
            reference_point,
        ),
        vertex_span_depth=_projection_span(vertex_points, access_direction),
        bbox_reference_depth=_reference_projection_depth(
            bbox_points,
            access_direction,
            reference_point,
        ),
        bbox_span_depth=_projection_span(bbox_points, access_direction),
        volume_area_depth=volume_area_depth,
    )
    point_factors = [
        f"vertex_point_count={len(vertex_points)}",
        f"bbox_point_count={len(bbox_points)}",
        f"volume_area_depth={volume_area_depth:.6g}",
    ]
    return BooleanDepthEstimate(
        depth_mm=estimate.depth_mm,
        method=estimate.method,
        reference_depth_mm=estimate.reference_depth_mm,
        span_depth_mm=estimate.span_depth_mm,
        evidence={
            **estimate.evidence,
            "vertex_point_count": len(vertex_points),
            "bbox_point_count": len(bbox_points),
            "face_area_mm2": round(max(face.area, 0.0), 6),
            "offset_mm": round(max(offset_mm, 0.0), 8),
            "volume_mm3": round(max(volume_mm3, 0.0), 6),
        },
        factors=point_factors + estimate.factors,
    )


def _coerce_boolean_metrics(value: object) -> BooleanInterferenceMetrics:
    if isinstance(value, BooleanInterferenceMetrics):
        return value
    return BooleanInterferenceMetrics(volume_mm3=max(0.0, float(value)), depth_mm=0.0)


def _shape_is_null(shape: object | None) -> bool:
    if shape is None:
        return True
    try:
        return bool(hasattr(shape, "IsNull") and shape.IsNull())
    except Exception:  # noqa: BLE001
        return False


def _classify_boolean_error(message: str) -> str:
    lower = message.lower()
    if "unavailable" in lower or "not available" in lower or "importerror" in lower:
        return "occ-runtime-unavailable"
    if "timeout" in lower or "timed out" in lower or "performance" in lower:
        return "timeout-or-performance-risk"
    if "tolerance" in lower or "sliver" in lower or "degenerated" in lower or "degenerate" in lower:
        return "tolerance-or-sliver-instability"
    if "transform" in lower or "offset face" in lower:
        return "transform-failure"
    if "prism" in lower or "sweep" in lower:
        return "sweep-construction-failure"
    if "common" in lower or "build" in lower or "boolean common" in lower:
        return "boolean-common-failure"
    if "shape is null" in lower or "null shape" in lower:
        return "null-shape"
    if "null" in lower:
        return "null-shape"
    if "volume" in lower or "mass" in lower:
        return "volume-evaluation-failure"
    return "unknown"


def _failure_info_from_attempts(
    attempts: list[BooleanAttemptInfo],
    reason: str = "OCC swept Boolean failed.",
) -> BooleanFailureInfo:
    last_error = attempts[-1].error if attempts else "No OCC error detail."
    failure_class = _classify_boolean_error(last_error)
    return BooleanFailureInfo(
        reason=reason,
        failure_class=failure_class,
        attempt_count=len(attempts),
        last_error=last_error,
        attempts=attempts,
        fallback_action="proxy-retained-after-boolean-failure",
    )


def _failure_info_from_exception(exc: Exception) -> BooleanFailureInfo:
    if isinstance(exc, BooleanOperationError):
        return exc.info
    last_error = str(exc) or exc.__class__.__name__
    return BooleanFailureInfo(
        reason="OCC swept Boolean failed.",
        failure_class=_classify_boolean_error(last_error),
        attempt_count=len(settings.dfm.direction_search.boolean_retry_offset_multipliers),
        last_error=last_error,
        attempts=[],
        fallback_action="proxy-retained-after-boolean-failure",
    )


def _raise_boolean_failure(attempts: list[BooleanAttemptInfo]) -> None:
    raise BooleanOperationError(_failure_info_from_attempts(attempts))


def _swept_face_interference_volume(
    part: PartGeometry,
    face: FaceData,
    pull_direction: Vec3,
    sweep_distance_override: float | None = None,
) -> BooleanInterferenceMetrics:
    """
    Approximate Bassi-style accessibility by sweeping a face away from the part.

    Steps:
      1. Pick access direction from signed normal side.
      2. Offset the face slightly outward to avoid counting the original face
         contact as interference.
      3. Sweep the offset face beyond the bounding box diagonal (or, when
         ``sweep_distance_override`` is supplied by D-061's ray-verification
         step, beyond the ray-measured material exit -- a shorter, MEASURED
         distance, never a guess; see the module docstring above
         ``RayVerificationResult``. The Boolean algorithm itself, and the
         retry/tolerance ladder below, are completely unchanged).
      4. Intersect the swept volume with the part.
      5. Return the intersection volume proxy.

    This is intentionally conservative.  OCC Booleans can fail on difficult
    NURBS/topology, so callers catch exceptions and keep the proxy result.
    """
    if not _OCC_BOOLEAN_AVAILABLE:
        raise RuntimeError("OCC Boolean tools are unavailable in this runtime.")

    access = _face_access_direction(face, pull_direction)
    cfg = settings.dfm.direction_search
    diagonal = max(part.bounding_box.diagonal, 1.0)
    sweep_distance = (
        max(sweep_distance_override, cfg.boolean_min_sweep_distance_mm)
        if sweep_distance_override is not None
        else max(diagonal * cfg.boolean_sweep_distance_factor, cfg.boolean_min_sweep_distance_mm)
    )
    max_offset = (
        cfg.boolean_max_offset_mm
        if cfg.boolean_max_offset_mm > 0.0
        else max(cfg.boolean_min_offset_mm, 1e-4)
    )
    max_fuzzy = (
        cfg.boolean_max_fuzzy_value_mm
        if cfg.boolean_max_fuzzy_value_mm > 0.0
        else max(cfg.boolean_min_offset_mm * cfg.boolean_fuzzy_factor, 1e-7)
    )
    t_start = time.perf_counter()
    attempts: list[BooleanAttemptInfo] = []
    multipliers = cfg.boolean_retry_offset_multipliers or (1.0,)

    for attempt_index, multiplier in enumerate(multipliers, start=1):
        attempt_start = time.perf_counter()
        raw_epsilon = max(
            diagonal * cfg.boolean_offset_factor,
            cfg.boolean_min_offset_mm,
        )
        epsilon = min(max(raw_epsilon * multiplier, 1e-9), max_offset)
        fuzzy_value = min(
            max(epsilon * cfg.boolean_fuzzy_factor, 1e-7),
            max_fuzzy,
        )
        try:
            offset = gp_Trsf()
            offset.SetTranslation(gp_Vec(
                access[0] * epsilon,
                access[1] * epsilon,
                access[2] * epsilon,
            ))
            moved_face = BRepBuilderAPI_Transform(face.occ_face, offset, True).Shape()
            if _shape_is_null(moved_face):
                raise RuntimeError("offset face is null")

            prism_vec = gp_Vec(
                access[0] * sweep_distance,
                access[1] * sweep_distance,
                access[2] * sweep_distance,
            )
            swept = BRepPrimAPI_MakePrism(moved_face, prism_vec, True, True).Shape()
            if _shape_is_null(swept):
                raise RuntimeError("swept prism is null")

            common = BRepAlgoAPI_Common(part.occ_shape, swept)
            if hasattr(common, "SetFuzzyValue"):
                common.SetFuzzyValue(fuzzy_value)
            common.Build()
            if not common.IsDone():
                raise RuntimeError("OCC common operation failed")

            common_shape = common.Shape()
            if _shape_is_null(common_shape):
                attempt = BooleanAttemptInfo(
                    attempt_index=attempt_index,
                    offset_mm=epsilon,
                    fuzzy_value=fuzzy_value,
                    status="empty-intersection",
                    elapsed_s=time.perf_counter() - attempt_start,
                )
                return BooleanInterferenceMetrics(
                    volume_mm3=0.0,
                    depth_mm=0.0,
                    elapsed_s=time.perf_counter() - t_start,
                    attempt_count=attempt_index,
                    offset_mm=epsilon,
                    fuzzy_value=fuzzy_value,
                    depth_method="none",
                    reference_depth_mm=0.0,
                    span_depth_mm=0.0,
                    intersection_shape=None,
                    shape_analysis=_analyze_boolean_shape(None),
                    status="empty-intersection",
                    warnings=["Boolean common completed with no intersection shape."],
                    attempts=[*attempts, attempt],
                )
            volume = _shape_volume(common_shape)
            depth_estimate = _estimate_boolean_depth_details(
                shape=common_shape,
                face=face,
                access_direction=access,
                offset_mm=epsilon,
                volume_mm3=volume,
            )
            attempt = BooleanAttemptInfo(
                attempt_index=attempt_index,
                offset_mm=epsilon,
                fuzzy_value=fuzzy_value,
                status="success",
                elapsed_s=time.perf_counter() - attempt_start,
            )
            return BooleanInterferenceMetrics(
                volume_mm3=volume,
                depth_mm=max(0.0, depth_estimate.depth_mm),
                elapsed_s=time.perf_counter() - t_start,
                attempt_count=attempt_index,
                offset_mm=epsilon,
                fuzzy_value=fuzzy_value,
                depth_method=depth_estimate.method,
                reference_depth_mm=depth_estimate.reference_depth_mm,
                span_depth_mm=depth_estimate.span_depth_mm,
                intersection_shape=common_shape,
                shape_analysis=_analyze_boolean_shape(common_shape),
                status="ok",
                attempts=[*attempts, attempt],
                depth_evidence=depth_estimate.evidence,
                depth_factors=depth_estimate.factors,
            )
        except Exception as exc:  # noqa: BLE001
            attempts.append(BooleanAttemptInfo(
                attempt_index=attempt_index,
                offset_mm=epsilon,
                fuzzy_value=fuzzy_value,
                status="failed",
                error=str(exc) or exc.__class__.__name__,
                elapsed_s=time.perf_counter() - attempt_start,
            ))

    _raise_boolean_failure(attempts)


def _boolean_refine_undercuts(
    part: PartGeometry,
    pull_direction: Vec3,
    candidate_face_ids: list[int],
    max_faces: int,
    volume_cache: Optional[BooleanVolumeCache] = None,
) -> tuple[
    set[int],
    dict[int, BooleanInterferenceMetrics],
    list[int],
    list[int],
    dict[int, str],
    dict[int, BooleanFailureInfo],
    list[int],
    dict[int, str],
    int,
    int,
    float,
    list[int],
    dict[int, str],
    list[int],
]:
    """
    Run swept-face Boolean checks for candidate faces.

    D-042 fix (2026-08-16): a face whose signed g = n.d is within
    ``cfg.boolean_near_zero_g_threshold`` of exactly zero is geometrically
    tangent to the pull direction -- ``BRepPrimAPI_MakePrism``'s sweep is not
    well-posed for a sweep vector lying in the face's own plane (empirically:
    the true danger zone is at or below floating-point noise, ~1e-15; the
    threshold has 9+ orders of magnitude of margin). Such faces are never
    passed to ``_swept_face_interference_volume`` at all -- they are
    reported as ``not_applicable``, never fabricated as confirmed OR clean.
    This also structurally resolves the D-042 sign-flip concern in
    ``_face_access_direction`` (its one call site, inside
    ``_swept_face_interference_volume``, is now never reached with a
    near-zero, noise-dominated sign).

    D-061 (2026-08-16): before attempting the swept-face Boolean, every
    remaining candidate is first checked by ``_ray_verify_face_clearance``
    (when ``cfg.ray_verification_enabled``). A "clear" ray result records
    the face into ``ray_verified_clear`` and SKIPS the Boolean entirely --
    the failure mode this closes (OCC's Common op failing on a whole-part-
    diagonal-length sweep for certain faces, proven unrelated to target
    complexity) never has a chance to trigger. A "material_found" ray
    result measures a safe, exact sweep distance and passes it into
    ``_swept_face_interference_volume`` -- the Boolean itself, its retry
    ladder, and its confirmed/failed semantics are completely unchanged.
    An "inconclusive" ray result falls through to today's existing
    whole-part-diagonal Boolean, unmodified, exactly as before this phase.

    Returns:
        confirmed_ids, volume_by_face, checked_ids, failed_ids,
        failure_reasons, failure_details, skipped_ids, skip_reasons,
        cache_hits, cache_misses, boolean_time_s, not_applicable_ids,
        not_applicable_reasons, ray_verified_clear_ids
    """
    cache = volume_cache if volume_cache is not None else {}
    confirmed: set[int] = set()
    metrics_by_face: dict[int, BooleanInterferenceMetrics] = {}
    checked: list[int] = []
    failed: list[int] = []
    failure_reasons: dict[int, str] = {}
    failure_details: dict[int, BooleanFailureInfo] = {}
    skipped: list[int] = []
    skip_reasons: dict[int, str] = {}
    not_applicable: list[int] = []
    not_applicable_reasons: dict[int, str] = {}
    ray_verified_clear: list[int] = []
    cache_hits = 0
    cache_misses = 0
    boolean_time_s = 0.0
    cfg = settings.dfm.direction_search
    volume_tolerance = max(
        part.bounding_box.diagonal ** 3 * cfg.boolean_volume_tolerance_factor,
        cfg.boolean_min_volume_tolerance_mm3,
    )
    face_area_tolerance = _face_area_tolerance(part)
    near_zero_g_threshold = cfg.boolean_near_zero_g_threshold

    # O9 (2026-08-17): BRepClass3d_SolidClassifier(part.occ_shape)'s
    # constructor depends only on part.occ_shape -- never on the
    # candidate face, ray, or pull direction -- so ONE instance built
    # here is reused for every ray this call's ray verification casts
    # (O8 measured ~1,200 redundant reconstructions per direction, 19-44%
    # of total detect_undercuts() runtime). Mock-safety guarded the same
    # way _ray_verify_face_clearance already guards face.occ_face:
    # constructing a real OCC classifier against a non-OCC object (a
    # MagicMock in mock-based tests) does not raise a catchable Python
    # exception, it can hang at the native layer. None here falls
    # through to _material_intervals_along_ray's own per-ray fallback
    # construction, byte-identical to pre-O9 behaviour.
    ray_classifier: object | None = None
    if (
        cfg.ray_verification_enabled and _OCC_BOOLEAN_AVAILABLE
        and isinstance(part.occ_shape, TopoDS_Shape)
    ):
        ray_classifier = BRepClass3d_SolidClassifier(part.occ_shape)

    for face_id in candidate_face_ids[:max_faces]:
        face = part.get_face(face_id)
        if face is None or not face.normal_valid:
            continue
        if face.area <= face_area_tolerance:
            skipped.append(face_id)
            skip_reasons[face_id] = (
                f"Face area {face.area:.6g} mm^2 is below Boolean sliver "
                f"threshold {face_area_tolerance:.6g} mm^2."
            )
            continue
        signed_g = face.signed_dot(pull_direction)
        if abs(signed_g) < near_zero_g_threshold:
            not_applicable.append(face_id)
            not_applicable_reasons[face_id] = (
                f"|g|={abs(signed_g):.3g} is below the near-zero-draft "
                f"tangency threshold {near_zero_g_threshold:.3g}; the "
                "directional sweep test is not geometrically well-posed for "
                "a face tangent to the pull direction (D-042) -- not "
                "verified, not confirmed clean."
            )
            continue

        sweep_distance_override: float | None = None
        if cfg.ray_verification_enabled and _OCC_BOOLEAN_AVAILABLE:
            ray_result = _ray_verify_face_clearance(
                part, face, pull_direction, cfg, classifier=ray_classifier,
            )
            if ray_result.status == "clear":
                # The Boolean itself was never attempted for this face --
                # excluded from boolean_checked_face_ids, matching the
                # existing not_applicable precedent immediately above
                # (that branch also never appends to `checked`).
                ray_verified_clear.append(face_id)
                continue
            if ray_result.status == "material_found":
                sweep_distance_override = ray_result.sweep_distance_mm
            # "inconclusive" falls through to the existing whole-part Boolean below.

        checked.append(face_id)
        key = _boolean_cache_key(face_id, pull_direction)
        if key in cache:
            cache_hits += 1
            cached_volume = cache[key]
            if cached_volume is None:
                failed.append(face_id)
                failure_reasons[face_id] = "Cached OCC Boolean failure."
                failure_details[face_id] = BooleanFailureInfo(
                    reason="Cached OCC Boolean failure.",
                    failure_class="cached-failure",
                    attempt_count=0,
                    last_error="Previously failed for this face and direction.",
                    attempts=[],
                    fallback_action="proxy-retained-after-boolean-failure",
                )
                continue
            metrics = _coerce_boolean_metrics(cached_volume)
        else:
            cache_misses += 1
            try:
                raw_metrics = _swept_face_interference_volume(
                    part, face, pull_direction,
                    sweep_distance_override=sweep_distance_override,
                )
                metrics = _coerce_boolean_metrics(raw_metrics)
            except Exception as exc:  # noqa: BLE001
                cache[key] = None
                failed.append(face_id)
                failure_info = _failure_info_from_exception(exc)
                failure_reasons[face_id] = failure_info.last_error
                failure_details[face_id] = failure_info
                continue
            cache[key] = metrics
        boolean_time_s += metrics.elapsed_s
        metrics_by_face[face_id] = metrics
        if metrics.volume_mm3 > volume_tolerance:
            confirmed.add(face_id)

    return (
        confirmed,
        metrics_by_face,
        checked,
        failed,
        failure_reasons,
        failure_details,
        skipped,
        skip_reasons,
        cache_hits,
        cache_misses,
        boolean_time_s,
        not_applicable,
        not_applicable_reasons,
        ray_verified_clear,
    )


def _rank_boolean_candidate_faces(
    part: PartGeometry,
    pull_direction: Vec3,
    candidate_face_ids: list[int],
    draft_face_results: dict[int, dict],
) -> list[int]:
    """
    Prioritize faces for expensive Boolean checks.

    The score favors coherent adjacent feature groups first, then severe faces
    inside those groups.  This is a practical Sangolli-style feature-first step:
    spend the early Boolean budget on faces that represent likely undercut
    components, while still ranking by draft severity, area, silhouette
    behavior, and suspicious adjacency.
    """
    candidate_set = set(candidate_face_ids)
    if not candidate_set:
        return []

    def draft_deficit(face_id: int) -> float:
        result = draft_face_results.get(face_id, {})
        angle = float(result.get("draft_angle_deg", 0.0))
        return max(0.0, settings.dfm.draft.marginal_threshold_deg - angle)

    def silhouette_value(face: FaceData) -> float:
        signed = abs(face.signed_dot(pull_direction)) if face.normal_valid else 0.0
        return 1.0 - min(1.0, signed)

    def face_score(face_id: int, group_size: int) -> tuple[float, int]:
        face = part.get_face(face_id)
        if face is None:
            return (0.0, -face_id)
        area_term = max(face.area, 0.0)
        neighbors = part.face_adjacency.get(face_id, [])
        suspicious_neighbors = sum(1 for nbr in neighbors if nbr in candidate_set)
        priority = (
            1000.0 * draft_deficit(face_id)
            + 0.05 * area_term
            + 8.0 * suspicious_neighbors
            + 2.0 * max(0, group_size - 1)
            + silhouette_value(face)
        )
        return (priority, -face_id)

    def group_score(group: list[int]) -> tuple[float, int, int]:
        valid_faces = [part.get_face(fid) for fid in group]
        valid_faces = [face for face in valid_faces if face is not None]
        if not valid_faces:
            return (0.0, 0, 0)
        area = sum(max(face.area, 0.0) for face in valid_faces)
        max_deficit = max(draft_deficit(face.face_id) for face in valid_faces)
        avg_silhouette = (
            sum(silhouette_value(face) for face in valid_faces) / len(valid_faces)
        )
        adjacency_density = 0
        group_set = set(group)
        for face_id in group:
            adjacency_density += sum(
                1 for nbr in part.face_adjacency.get(face_id, [])
                if nbr in group_set
            )
        priority = (
            1500.0 * max_deficit
            + 0.10 * area
            + 25.0 * len(valid_faces)
            + 3.0 * adjacency_density
            + avg_silhouette
        )
        return (priority, len(valid_faces), -min(group))

    groups = _group_adjacent_faces(part, sorted(candidate_set))
    ranked_groups: list[tuple[tuple[float, int, int], list[int]]] = []
    for group in groups:
        valid_group = [face_id for face_id in group if part.get_face(face_id) is not None]
        if not valid_group:
            continue
        ranked_faces = sorted(
            valid_group,
            key=lambda face_id: face_score(face_id, len(valid_group)),
            reverse=True,
        )
        ranked_groups.append((group_score(valid_group), ranked_faces))

    ranked_groups.sort(key=lambda item: item[0], reverse=True)
    if not ranked_groups:
        return []

    ordered: list[int] = []
    selected: set[int] = set()
    seed_faces = max(1, int(settings.dfm.direction_search.boolean_feature_seed_faces_per_group))

    for seed_index in range(seed_faces):
        for _, ranked_faces in ranked_groups:
            if seed_index < len(ranked_faces):
                face_id = ranked_faces[seed_index]
                if face_id not in selected:
                    selected.add(face_id)
                    ordered.append(face_id)

    depth = seed_faces
    added = True
    while added:
        added = False
        for _, ranked_faces in ranked_groups:
            if depth < len(ranked_faces):
                face_id = ranked_faces[depth]
                if face_id not in selected:
                    selected.add(face_id)
                    ordered.append(face_id)
                    added = True
        depth += 1

    return ordered


def _compute_accessibility_risk(
    part: PartGeometry,
    pull_dir: Vec3,
    precomputed_metrics: Optional[dict[int, FaceDirectionalMetrics]],
    *,
    side: str = "core",
) -> tuple[list[int], float]:
    """
    Identify faces that are heuristic accessibility risks for a pull direction.

    A face is flagged when BOTH conditions hold simultaneously:

    1. **On the requested side**: ``side="core"`` (default) flags
       ``signed_dot (n·d) < -threshold`` — the face normal broadly opposes
       the pull direction, physically on the "away" side of the mold
       opening. ``side="cavity"`` flags the mirror condition,
       ``signed_dot (n·d) > +threshold`` — normal broadly ALIGNED with the
       pull direction.

       Phase 5D-1 (2026-08-16, D-056): both sides use the exact same
       threshold and the exact same concave-edge requirement below — this
       is a single symmetric rule, parameterized by sign, not two
       different heuristics. The reason core-side was historically the
       only side tested is a real, provable geometric fact, NOT an
       arbitrary implementation shortcut: for a face F with n·d > 0,
       sweeping F along the pull direction moves away from F's OWN
       adjacent solid for an initial segment (a basic outward-normal
       property of a manifold boundary), so F's own sweep cannot find
       LOCAL self-interference. What it CAN still find is interference
       with DISTANT material further along the sweep -- e.g. a cavity-side
       shelf swept upward into an overhang positioned above it. Testing
       both sides makes the resulting "not confirmed" conclusion mean "we
       checked this geometric signature on both sides and found nothing,"
       not "we only ever looked in one direction." See
       ``docs/DECISIONS_AND_ALGORITHMS.md`` D-056 for the full derivation
       and the UC3 face-10/face-4 mirror-pair proof (both independently
       confirm the identical 6400 mm^3, hand-verified).

    2. **At least one confirmed concave bounding edge**: geometric evidence
       of a pocket, hook, or slot that could obstruct mold withdrawal.
       Faces whose ALL bounding edges are convex or tangent are NOT flagged —
       no concave edge means no pocket regardless of centroid orientation.
       UNCHANGED by D-056 -- reused identically for both sides.

    CRITICAL NOTES:

    - This is a **HEURISTIC risk signal only**, NOT proof of undercut (either
      direction).
    - It is **independent of draft angle**: a face with 5° draft (good) can
      still be flagged if on the requested side with a concave edge; a face
      with 0.1° draft (bad) on a convex boss is NOT flagged (no concave edge).
    - Only Boolean swept-volume validation (``_boolean_refine_undercuts``)
      can confirm actual physical obstruction.
    - The returned face IDs are for scoring purposes; they must NOT be
      treated as ``undercut_face_ids``.

    Uses ``precomputed_metrics`` (from ``precompute_directional_metrics()``)
    when available to avoid a redundant dot-product per face.  Falls back to
    calling ``face.signed_dot()`` when precomputed data is absent.

    Parameters
    ----------
    part               : Loaded PartGeometry.
    pull_dir           : Normalised pull direction (unit vector).
    precomputed_metrics : Optional precomputed per-face directional metrics.
    side               : "core" (default, pre-D-056 behaviour, byte-identical
                          when this is the only call made) or "cavity".

    Returns
    -------
    (risk_face_ids, risk_area_mm2) — face IDs and their combined area.
    """
    threshold = settings.dfm.undercut.accessibility_risk_core_side_threshold
    risk_ids: list[int] = []
    risk_area: float = 0.0

    for face in part.faces:
        if not face.normal_valid:
            continue

        # Get signed_dot: prefer precomputed to avoid a redundant dot product.
        if precomputed_metrics is not None and face.face_id in precomputed_metrics:
            signed = precomputed_metrics[face.face_id].signed_dot
        else:
            signed = face.signed_dot(pull_dir)

        # Condition 1: face is on the requested side. "core" keeps
        # signed < -threshold (original, unchanged rule); "cavity" keeps
        # the sign-mirrored signed > +threshold -- same threshold, same
        # magnitude requirement, opposite side.
        directional = signed if side == "cavity" else -signed
        if directional <= threshold:
            continue

        # Condition 2: at least one confirmed concave bounding edge.
        # Positive evidence (concave edge exists) is required — absence of
        # a concave edge does NOT flag the face.
        face_edges = part.get_face_edges(face.face_id)
        if not face_edges:
            continue
        has_concave = any(e.convexity == "concave" for e in face_edges)
        if not has_concave:
            continue

        risk_ids.append(face.face_id)
        risk_area += face.area

    return risk_ids, risk_area


def detect_undercuts(
    part: PartGeometry,
    pull_direction: Vec3,
    mutate: bool = True,
    boolean_refine: bool = True,
    boolean_check_all_faces: bool = False,
    max_boolean_faces: int = 120,
    boolean_volume_cache: Optional[BooleanVolumeCache] = None,
    precomputed_metrics: Optional[dict[int, FaceDirectionalMetrics]] = None,
    draft_result: Optional[DraftAnalysisResult] = None,
) -> UndercutDetectionResult:
    """
    Detect likely undercut/accessibility problem faces for a pull direction.

    Current pipeline:
      - Fast proxy marks valid faces with draft below the marginal threshold as
        likely undercut/accessibility problem faces.
      - Near-zero signed normal faces are separately tracked as parting-region
        faces.
      - Convexity-gated suppression (Sangolli 2021) removes proxy-undercut
        faces whose bounding edges are all convex/tangent — no concave edge
        means no genuine pocket, regardless of what the centroid normal
        alone suggests. Suppressed faces skip Boolean refinement entirely.
        Disable via config: dfm.undercut.convexity_suppression_enabled.
      - Optional Boolean refinement sweeps candidate faces along their access
        direction and keeps faces with non-zero intersection volume.

    The result is intentionally structured like the future Sangolli/Bassi result
    so the API, frontend, and optimizer do not need to change when Boolean
    volume scoring is added.
    """
    t_start = time.perf_counter()
    pull_dir = normalize3(pull_direction)

    # Use provided draft_result when available (e.g. passed from direction
    # optimizer to avoid a redundant analyze_draft call).  Fall back to
    # computing it internally when not supplied.
    if draft_result is not None:
        draft = draft_result
    else:
        draft = analyze_draft(
            part=part,
            pull_direction=pull_dir,
            pull_direction_label="undercut detection direction",
            analysis_pass="undercut",
            mutate=mutate,
            precomputed_metrics=precomputed_metrics,
        )
    marginal_threshold = settings.dfm.draft.marginal_threshold_deg

    proxy_undercut_ids: list[int] = []
    accessible_ids: list[int] = []
    parting_ids: list[int] = []
    skipped_ids = list(draft.skipped_face_ids)

    parting_dot_threshold = 0.01
    total_area = 0.0
    undercut_area = 0.0

    for face in part.faces:
        if not face.normal_valid:
            continue
        total_area += face.area
        angle = float(draft.face_results[face.face_id]["draft_angle_deg"])
        # Use precomputed signed_dot when available to avoid a second dot
        # product per face.  signed_dot = n·d is already available from the
        # metrics dict that was passed to analyze_draft above.
        if precomputed_metrics is not None and face.face_id in precomputed_metrics:
            signed = precomputed_metrics[face.face_id].signed_dot
        else:
            signed = face.signed_dot(pull_dir)

        if abs(signed) <= parting_dot_threshold:
            parting_ids.append(face.face_id)

        if angle < marginal_threshold:
            proxy_undercut_ids.append(face.face_id)
        else:
            accessible_ids.append(face.face_id)
            if mutate:
                face.is_undercut = False
                face.undercut_depth_mm = None
                face.undercut_type = None

    # ── Convexity-gated false-positive suppression (Sangolli 2021) ─────────
    # A centroid-normal draft angle below threshold is a poor signal on
    # curved faces (e.g. a cylindrical boss nearly aligned with the pull
    # direction): the centroid normal can register as negative draft even
    # though every point on the face is fully accessible. Edge convexity
    # (computed once at load time in step_loader.py, independent of pull
    # direction) resolves this: a genuine pocket always has at least one
    # concave bounding edge. A proxy-undercut face with an unclassified
    # (None) or missing edge is NOT suppressed — suppression requires
    # positive evidence, not merely the absence of a concave edge.
    convexity_suppressed_ids: list[int] = []
    if settings.dfm.undercut.convexity_suppression_enabled:
        still_undercut_ids: list[int] = []
        for fid in proxy_undercut_ids:
            face_edges = part.get_face_edges(fid)
            if face_edges and all(e.convexity in ("convex", "tangent") for e in face_edges):
                convexity_suppressed_ids.append(fid)
            else:
                still_undercut_ids.append(fid)
        proxy_undercut_ids = still_undercut_ids

        # A suppressed face is, by construction, almost always ALSO within
        # parting_dot_threshold of the parting region: sin(marginal_threshold)
        # is smaller than parting_dot_threshold for the shipped defaults
        # (0.5° → |n·d| ≈ 0.0087 < 0.01), so nearly every proxy-undercut face
        # satisfies both tests at once. The final mutate block below only
        # clears is_undercut to False for faces NOT in parting_ids — for a
        # suppressed-and-parting face that leaves it at its uninitialised
        # None. Suppression is a definitive "not an undercut" determination,
        # so mutate it explicitly here rather than relying on that block.
        if mutate and convexity_suppressed_ids:
            for fid in convexity_suppressed_ids:
                face = part.get_face(fid)
                if face is not None:
                    face.is_undercut = False
                    face.undercut_depth_mm = None
                    face.undercut_type = None

    # ── Accessibility risk (Milestone 2, bilateral since Phase 5D-1/D-056) ───
    # Core-side AND cavity-side faces with at least one concave bounding edge
    # are flagged as heuristic accessibility risks -- the same rule, sign-
    # mirrored (see _compute_accessibility_risk's docstring for the
    # geometric argument for why this is a completeness fix, not merely
    # "symmetry for its own sake": core-side is the ONLY side whose own
    # sweep can find LOCAL self-interference, but a cavity-side face can
    # still register real interference with DISTANT material further along
    # the sweep -- e.g. a shelf swept upward into an overhang above it
    # (hand-verified on UC3's face 10, mirroring face 4's already-proven
    # 6400 mm^3 ground truth exactly). This signal is INDEPENDENT of the
    # proxy_undercut_ids list above: a face with good draft can be flagged
    # here; a face with bad draft but all-convex edges is NOT. This is NOT
    # proof of undercut — Boolean validation remains authoritative.
    core_side_risk_ids, core_side_risk_area = _compute_accessibility_risk(
        part=part,
        pull_dir=pull_dir,
        precomputed_metrics=precomputed_metrics,
        side="core",
    )
    cavity_side_risk_ids, cavity_side_risk_area = _compute_accessibility_risk(
        part=part,
        pull_dir=pull_dir,
        precomputed_metrics=precomputed_metrics,
        side="cavity",
    )
    # Union by construction: a face cannot satisfy both signed_dot < -t AND
    # signed_dot > +t simultaneously (t > 0), so the two id sets are
    # disjoint and areas simply add -- no double-counting is possible.
    risk_face_ids = sorted(set(core_side_risk_ids) | set(cavity_side_risk_ids))
    risk_area_mm2 = core_side_risk_area + cavity_side_risk_area

    boolean_checked: list[int] = []
    boolean_confirmed: set[int] = set()
    boolean_failed: list[int] = []
    boolean_failure_reasons: dict[int, str] = {}
    boolean_failure_details: dict[int, BooleanFailureInfo] = {}
    boolean_skipped: list[int] = []
    boolean_skip_reasons: dict[int, str] = {}
    interference_by_face: dict[int, BooleanInterferenceMetrics] = {}
    boolean_cache_hits = 0
    boolean_cache_misses = 0
    boolean_time_s = 0.0
    boolean_was_run = bool(boolean_refine and _OCC_BOOLEAN_AVAILABLE)
    candidate_sources: dict[int, list[str]] = {}
    if boolean_was_run:
        if boolean_check_all_faces:
            check_ids = [face.face_id for face in part.valid_faces]
        else:
            # Phase 5A follow-up (2026-08-16): Boolean candidacy is the union
            # of draft-based proxy candidates and accessibility-risk
            # candidates. A face with excellent draft magnitude (|g|~1) but
            # the wrong sign relative to its local topology -- a genuine
            # shelf/trap, e.g. UC3's face 4 -- has draft_angle_deg=90 and is
            # NEVER in proxy_undercut_ids, so it would never reach
            # verification otherwise. Neither candidate-generation pass
            # (draft proxy, accessibility risk) is modified here -- only
            # which of their outputs feed the unchanged Boolean step.
            check_ids = sorted(set(proxy_undercut_ids) | set(risk_face_ids))
        check_ids = _rank_boolean_candidate_faces(
            part=part,
            pull_direction=pull_dir,
            candidate_face_ids=check_ids,
            draft_face_results=draft.face_results,
        )
        # Provenance for exactly the faces that will actually be processed
        # by _boolean_refine_undercuts (it truncates to max_boolean_faces
        # internally too -- mirrored here so provenance matches reality).
        proxy_set = set(proxy_undercut_ids)
        risk_set = set(risk_face_ids)
        for fid in check_ids[:max_boolean_faces]:
            sources: list[str] = []
            if fid in proxy_set:
                sources.append("draft_proxy")
            if fid in risk_set:
                sources.append("accessibility_risk")
            candidate_sources[fid] = sources or ["all_faces"]
        (
            boolean_confirmed,
            interference_by_face,
            boolean_checked,
            boolean_failed,
            boolean_failure_reasons,
            boolean_failure_details,
            boolean_skipped,
            boolean_skip_reasons,
            boolean_cache_hits,
            boolean_cache_misses,
            boolean_time_s,
            boolean_not_applicable,
            boolean_not_applicable_reasons,
            ray_verified_clear,
        ) = (
            _boolean_refine_undercuts(
                part=part,
                pull_direction=pull_dir,
                candidate_face_ids=check_ids,
                max_faces=max_boolean_faces,
                volume_cache=boolean_volume_cache,
            )
        )
    else:
        boolean_not_applicable = []
        boolean_not_applicable_reasons = {}
        ray_verified_clear = []

    # The full nominated Boolean-candidate population (union of both
    # candidate-generation sources), independent of ranking/truncation --
    # used below for the legacy union and the honest evidence buckets.
    all_candidate_ids = set(proxy_undercut_ids) | set(risk_face_ids)

    if boolean_was_run and boolean_checked:
        # Keep Boolean-confirmed faces.  If OCC failed on a candidate face,
        # keep it flagged instead of silently dropping a possible issue.
        # Sliver faces skipped before Boolean are also retained when EITHER
        # candidate source marked them suspicious; they are too small for
        # reliable swept Booleans.
        # D-042 fix: not_applicable faces (near-zero-g, sweep never
        # attempted) stay in this conservative legacy union too -- they
        # remain flagged, uncertain, never silently cleared -- but never
        # enter boolean_confirmed_face_ids, which stays real physical
        # evidence only.
        undercut_id_set = set(boolean_confirmed)
        undercut_id_set.update(fid for fid in all_candidate_ids if fid in boolean_failed)
        undercut_id_set.update(fid for fid in all_candidate_ids if fid in boolean_skipped)
        undercut_id_set.update(boolean_not_applicable)
        undercut_ids = sorted(undercut_id_set)
    else:
        undercut_ids = sorted(proxy_undercut_ids)

    # Phase 5A follow-up: honest evidence-outcome buckets, disjoint by
    # construction, now scoped to the FULL candidate population (draft
    # proxy union accessibility risk), not just the draft-based proxy set.
    # candidate_unconfirmed = nominated by either candidate source, with no
    # positive Boolean-confirmed evidence AND not excluded as
    # not-applicable (covers: never Boolean-checked at all -- e.g. ranking
    # truncation, genuinely cleared by the sweep, or failed/skipped as a
    # sliver). Replaces Phase 5A's `proxy_only_face_ids`, which becomes
    # semantically misleading once a face can be a Boolean candidate
    # without ever being a draft-proxy candidate (e.g. UC3 face 4).
    boolean_not_applicable_set = set(boolean_not_applicable)
    ray_verified_clear_set = set(ray_verified_clear)
    # D-061: ray-verified-clear faces are their own, explicit evidence
    # bucket (see UndercutDetectionResult.ray_verified_clear_face_ids) --
    # deliberately excluded here too, rather than left to fall into
    # candidate_unconfirmed_face_ids by default. That field's existing
    # meaning is "reached the Boolean pipeline, not confirmed, not
    # not-applicable" (Boolean-cleared, or never Boolean-tested at all due
    # to ranking truncation); ray-clearance is a DIFFERENT evidence source
    # (measured geometrically, no Boolean ever attempted) and must not be
    # silently folded into a field whose meaning it doesn't share.
    candidate_unconfirmed_face_ids = sorted(
        all_candidate_ids - set(boolean_confirmed) - boolean_not_applicable_set - ray_verified_clear_set
    )

    valid_ids = {face.face_id for face in part.valid_faces}
    accessible_ids = sorted(valid_ids - set(undercut_ids))
    undercut_area = sum((part.get_face(fid).area if part.get_face(fid) is not None else 0.0) for fid in undercut_ids)

    if mutate:
        undercut_set = set(undercut_ids)
        for face in part.valid_faces:
            if face.face_id in undercut_set:
                face.is_undercut = True
                face.undercut_depth_mm = 0.0
                face.undercut_type = "pending-feature-group"
            elif face.face_id not in parting_ids:
                face.is_undercut = False
                face.undercut_depth_mm = None
                face.undercut_type = None

    projections = [_project(face.centroid, pull_dir) for face in part.valid_faces]
    min_projection = min(projections) if projections else 0.0
    max_projection = max(projections) if projections else 0.0

    features: list[UndercutFeature] = []
    boolean_failed_set = set(boolean_failed)
    boolean_skipped_set = set(boolean_skipped)
    baseline_grouping = _group_undercut_faces_with_boolean_proximity(
        part=part,
        face_ids=undercut_ids,
        interference_by_face=interference_by_face,
    )
    concave_neighbor_closure = _concave_neighbor_closure(part, undercut_ids, baseline_grouping.groups)
    grouping_result = (
        _group_undercut_faces_with_boolean_proximity(
            part=part,
            face_ids=sorted(set(undercut_ids) | concave_neighbor_closure),
            interference_by_face=interference_by_face,
        )
        if concave_neighbor_closure
        else baseline_grouping
    )
    for feature_id, group in enumerate(grouping_result.groups):
        faces = [part.get_face(fid) for fid in group]
        valid_faces = [face for face in faces if face is not None]
        if not valid_faces:
            continue

        group_projections = [_project(face.centroid, pull_dir) for face in valid_faces]
        center = _average_point(valid_faces)
        area = sum(face.area for face in valid_faces)
        group_metrics = [
            interference_by_face[face.face_id]
            for face in valid_faces
            if face.face_id in interference_by_face
        ]
        group_intersection_face_ids = [
            face.face_id
            for face in valid_faces
            if (
                face.face_id in interference_by_face
                and interference_by_face[face.face_id].intersection_shape is not None
            )
        ]
        group_intersection_shapes = [
            interference_by_face[face_id].intersection_shape
            for face_id in group_intersection_face_ids
        ]
        group_shape_analyses = [
            interference_by_face[face_id].shape_analysis
            for face_id in group_intersection_face_ids
        ]
        boolean_region_geometry = _combine_boolean_region_geometry(
            source_face_ids=group_intersection_face_ids,
            analyses=group_shape_analyses,
        )
        interference_volume = sum(metric.volume_mm3 for metric in group_metrics)
        boolean_depth_proxy = max(
            [metric.depth_mm for metric in group_metrics] or [0.0]
        )
        dominant_depth_metric = _dominant_depth_metric(group_metrics)
        boolean_depth_method = (
            dominant_depth_metric.depth_method
            if dominant_depth_metric is not None
            else "none"
        )
        boolean_depth_evidence = (
            dominant_depth_metric.depth_evidence
            if dominant_depth_metric is not None
            else {}
        )
        boolean_depth_factors = (
            dominant_depth_metric.depth_factors
            if dominant_depth_metric is not None
            else []
        )
        if boolean_depth_proxy <= 0.0 and area > 0.0:
            boolean_depth_proxy = interference_volume / area
            if boolean_depth_proxy > 0.0:
                boolean_depth_method = "feature-volume-area"
                boolean_depth_evidence = {
                    "feature_interference_volume_mm3": round(interference_volume, 6),
                    "feature_area_mm2": round(area, 6),
                    "volume_area_depth_mm": round(boolean_depth_proxy, 6),
                }
                boolean_depth_factors = [
                    "selected feature-level volume/area fallback because face-level Boolean depth was zero"
                ]
        min_angle = min(
            float(draft.face_results[face.face_id]["draft_angle_deg"])
            for face in valid_faces
        )
        projection_depth = max(
            0.0,
            min(
                max_projection - min(group_projections),
                max(group_projections) - min_projection,
            ),
        )
        base_depth_proxy = max(projection_depth, boolean_depth_proxy)
        fallback_release_dir = _estimate_release_direction(valid_faces, pull_dir)
        release_depth_estimate = _estimate_release_and_depth_from_boolean_geometry(
            faces=valid_faces,
            pull_direction=pull_dir,
            part=part,
            geometry=boolean_region_geometry,
            fallback_release_direction=fallback_release_dir,
            fallback_depth_mm=base_depth_proxy,
        )
        depth_proxy = release_depth_estimate.depth_mm
        release_dir = release_depth_estimate.release_direction
        type_classification = _classify_undercut_type(valid_faces, pull_dir, part)
        utype = type_classification.undercut_type
        geometric_classification = _classify_boolean_geometric_feature(
            geometry=boolean_region_geometry,
            pull_direction=pull_dir,
            release_direction=release_dir,
            part=part,
            undercut_type=utype,
            face_count=len(valid_faces),
        )
        interaction_type, interaction_factors = _feature_interaction_summary(
            group=group,
            interference_by_face=interference_by_face,
        )
        geometric_feature_type = geometric_classification.feature_type
        geometric_feature_confidence = geometric_classification.confidence
        geometric_feature_confidence_label = geometric_classification.confidence_label
        geometric_feature_method = geometric_classification.method
        geometric_feature_factors = list(geometric_classification.factors)
        if interaction_type in {"nested", "overlapping"}:
            geometric_feature_type = "complex/interacting-candidate"
            geometric_feature_confidence = max(geometric_feature_confidence, 0.68)
            geometric_feature_confidence_label = _confidence_label(geometric_feature_confidence)
            geometric_feature_method = (
                f"{geometric_feature_method} + boolean-region-{interaction_type}-interaction"
            )
            geometric_feature_factors.extend(
                [f"upgraded to complex/interacting because interaction_type={interaction_type}"]
                + interaction_factors
            )
        evidence_source = _feature_evidence_source(
            group=group,
            boolean_was_run=boolean_was_run,
            boolean_confirmed=boolean_confirmed,
            boolean_failed=boolean_failed_set,
            boolean_skipped=boolean_skipped_set,
        )
        severity = _severity(depth_proxy, area)
        recommendation = _recommend_mold_action(
            undercut_type=utype,
            severity=severity,
            evidence_source=evidence_source,
            release_direction=release_dir,
            pull_direction=pull_dir,
            depth_proxy_mm=depth_proxy,
            interference_volume_mm3=interference_volume,
            boolean_depth_method=boolean_depth_method,
            type_classification_score=type_classification.score,
            type_classification_method=type_classification.method,
        )

        features.append(UndercutFeature(
            feature_id=feature_id,
            face_ids=group,
            undercut_type=utype,
            severity=severity,
            evidence_source=evidence_source,
            type_classification_method=type_classification.method,
            type_classification_score=type_classification.score,
            type_classification_factors=type_classification.factors,
            release_direction=release_dir,
            location=center,
            depth_proxy_mm=depth_proxy,
            release_direction_method=release_depth_estimate.release_direction_method,
            release_direction_factors=release_depth_estimate.factors,
            depth_estimation_method=release_depth_estimate.depth_method,
            grouping_method=grouping_result.method,
            grouping_factors=grouping_result.factors,
            geometric_feature_type=geometric_feature_type,
            geometric_feature_confidence=geometric_feature_confidence,
            geometric_feature_confidence_label=geometric_feature_confidence_label,
            geometric_feature_method=geometric_feature_method,
            geometric_feature_factors=geometric_feature_factors,
            boolean_depth_proxy_mm=boolean_depth_proxy,
            boolean_depth_method=boolean_depth_method,
            boolean_depth_evidence=boolean_depth_evidence,
            boolean_depth_factors=boolean_depth_factors,
            interference_volume_mm3=interference_volume,
            interaction_type=interaction_type,
            interaction_factors=interaction_factors,
            total_area_mm2=area,
            min_draft_angle_deg=min_angle,
            boolean_confirmed_face_ids=sorted(set(group) & boolean_confirmed),
            boolean_failed_face_ids=sorted(set(group) & boolean_failed_set),
            boolean_skipped_face_ids=sorted(set(group) & boolean_skipped_set),
            boolean_not_applicable_face_ids=sorted(set(group) & boolean_not_applicable_set),
            boolean_intersection_face_ids=group_intersection_face_ids,
            boolean_intersection_shapes=group_intersection_shapes,
            boolean_region_geometry=boolean_region_geometry,
            side_action_candidate=recommendation.side_action_candidate,
            recommended_mold_action=recommendation.action,
            action_reason=recommendation.reason,
            pull_alignment=recommendation.pull_alignment,
            action_confidence=recommendation.confidence,
            action_confidence_label=recommendation.confidence_label,
            action_confidence_factors=recommendation.confidence_factors,
            action_confidence_breakdown=recommendation.confidence_breakdown,
            action_explanation=recommendation.explanation,
        ))

        if mutate:
            for face in valid_faces:
                face.undercut_depth_mm = depth_proxy
                face.undercut_type = utype

    method = "normal/draft adjacency prefilter"
    if boolean_was_run:
        method += " + swept-face Boolean refinement"
    elif boolean_refine:
        method += "; Boolean refinement unavailable in this runtime"
    else:
        method += "; Boolean refinement disabled"

    boolean_performance = _build_boolean_performance_summary(
        checked_face_ids=boolean_checked,
        failed_face_ids=boolean_failed,
        skipped_face_ids=boolean_skipped,
        metrics_by_face=interference_by_face,
        failure_details=boolean_failure_details,
        cache_hits=boolean_cache_hits,
        cache_misses=boolean_cache_misses,
        elapsed_s=boolean_time_s,
    ) if boolean_was_run else None
    boolean_reliability = _build_boolean_reliability_summary(
        enabled=boolean_was_run,
        undercut_face_ids=sorted(undercut_ids),
        checked_face_ids=boolean_checked,
        confirmed_face_ids=sorted(boolean_confirmed),
        failed_face_ids=boolean_failed,
        skipped_face_ids=boolean_skipped,
        failure_details=boolean_failure_details,
        skip_reasons=boolean_skip_reasons,
    )

    return UndercutDetectionResult(
        pull_direction=pull_dir,
        method=method,
        undercut_face_ids=sorted(undercut_ids),
        accessible_face_ids=sorted(accessible_ids),
        parting_face_ids=sorted(parting_ids),
        skipped_face_ids=sorted(skipped_ids),
        convexity_suppressed_face_ids=sorted(convexity_suppressed_ids),
        features=features,
        undercut_area_mm2=undercut_area,
        total_analysed_area_mm2=total_area,
        boolean_refined=boolean_was_run,
        boolean_checked_face_ids=sorted(boolean_checked),
        boolean_confirmed_face_ids=sorted(boolean_confirmed),
        boolean_failed_face_ids=sorted(boolean_failed),
        boolean_failure_reasons=boolean_failure_reasons,
        boolean_failure_details={
            face_id: info.to_dict()
            for face_id, info in boolean_failure_details.items()
        },
        boolean_skipped_face_ids=sorted(boolean_skipped),
        boolean_skip_reasons=boolean_skip_reasons,
        interference_volume_mm3=sum(metric.volume_mm3 for metric in interference_by_face.values()),
        boolean_depth_proxy_mm=max(
            [metric.depth_mm for metric in interference_by_face.values()] or [0.0]
        ),
        boolean_depth_method=_dominant_depth_method(list(interference_by_face.values())),
        boolean_cache_hits=boolean_cache_hits,
        boolean_cache_misses=boolean_cache_misses,
        boolean_time_s=boolean_time_s,
        boolean_performance=boolean_performance,
        boolean_reliability=boolean_reliability,
        accessibility_risk_face_ids=sorted(risk_face_ids),
        accessibility_risk_area_mm2=risk_area_mm2,
        analysis_time_s=time.perf_counter() - t_start,
        candidate_unconfirmed_face_ids=candidate_unconfirmed_face_ids,
        candidate_sources=candidate_sources,
        boolean_not_applicable_face_ids=sorted(boolean_not_applicable_set),
        boolean_not_applicable_reasons=boolean_not_applicable_reasons,
        ray_verified_clear_face_ids=sorted(ray_verified_clear_set),
    )
