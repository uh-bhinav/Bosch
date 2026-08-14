"""
backend/geometry/draft_analyzer.py
------------------------------------
Module 2 of the DfM Agent Geometry Engine: Draft Analysis.

Responsibility
--------------
Given a `PartGeometry` and a pull direction (unit Vec3), compute:
  - The draft angle for every face with a valid normal.
  - A three-level classification: "good" | "marginal" | "bad".
  - Signed mold-side classification: "positive" (cavity) | "negative" (core) | "parting".
  - Area-weighted severity assessment for the whole part.
  - Structured, actionable suggestions ready for the AI Agent layer.

By default this module MUTATES `FaceData.draft_angle_deg` and
`FaceData.draft_classification` in place on the `PartGeometry` object, AND
returns a standalone `DraftAnalysisResult` that contains everything needed for
visualisation, the AI Agent, and the PDF report.

For before-vs-after UI flows, call `analyze_draft(..., mutate=False)`.  The
returned result remains fully populated, including per-face angle/classification
data, while the part's current draft overlay is left untouched.

Pipeline position
-----------------
  step_loader → [THIS] → direction_optimizer → undercut_detector
             → parting_line → core_cavity → AI Agent → Report

Why draft analysis before direction optimisation?
-------------------------------------------------
This matches the real mold engineer workflow:
  1. Open the part in CATIA/SolidWorks.
  2. Immediately run draft analysis on the default Z direction →
     get a color-coded first impression of problem areas.
  3. Then search for a better pull direction (Bassi algorithm).
  4. Re-run draft analysis on the optimal direction → final result.

Our pipeline runs this module TWICE:
  • Once on the default direction (+Z) for immediate visual feedback.
  • Once after direction_optimizer.py selects the optimal direction.

Draft angle definition
----------------------
Draft angle = the taper (in degrees) of a wall face relative to the
pull direction. In the SolidWorks DraftAnalysis convention:

    draft_angle_deg = asin(|n · d|)

where:
    n  = outward unit normal of the face
    d  = unit pull direction vector

Physical meaning:
    0°   → face normal ⊥ pull  → perfectly vertical wall, zero taper → mold sticks
    1.5° → minimum acceptable taper for most automotive plastics
    90°  → face normal ∥ pull  → horizontal face (top/bottom cap) → no issue

Signed mold side:
    n · d > 0  → face points in pull direction → CAVITY side (upper mold half)
    n · d < 0  → face points against pull       → CORE side  (lower mold half)
    n · d ≈ 0  → silhouette / parting plane candidate

References
----------
* Bassi et al. (2010) — uses the same n·d computation for accessibility scoring.
  Our `draft_angle_deg` is the primary pre-filter before the expensive Boolean ops.
* Hou et al. (2018) — draft angle used as one weight in the parting curve cost fn.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Optional, Union

from backend.config import settings
from backend.models.geometry_models import FaceData, PartGeometry, Vec3, dot3, normalize3

logger = logging.getLogger(__name__)

FaceDraftValue = Union[float, str]
FaceDraftResult = dict[str, FaceDraftValue]


# =============================================================================
# Pre-computation dataclass (shared with undercut_detector, direction_optimizer)
# =============================================================================

@dataclass(frozen=True)
class FaceDirectionalMetrics:
    """
    Pre-computed per-face directional data for a single pull direction.

    Computed once by ``precompute_directional_metrics()`` and consumed by
    both ``analyze_draft()`` and ``detect_undercuts()`` to avoid redundant
    n·d calculations during the direction-optimizer candidate loop.

    Three signals derive from a single ``signed_dot = n · d`` computation.
    They represent strictly different physical properties — callers MUST NOT
    conflate them:

    - ``draft_angle_deg`` — surface-orientation quality (how far the face
      tilts relative to the pull axis).  NOT an undercut indicator.
    - ``mold_side`` — which mold half the face points into.  NOT an undercut
      indicator; a core-side face is normal.  Combined with concave-edge
      evidence it becomes a heuristic accessibility *risk* signal, but only
      Boolean swept-volume validation can confirm an actual undercut.
    - ``draft_classification`` — three-level quality class derived from the
      draft angle and global thresholds (no per-face overrides applied).
    """
    signed_dot: float           # n · d (clamped to [-1, 1], with sign)
    draft_angle_deg: float      # asin(|signed_dot|) in degrees
    mold_side: str              # "positive" | "negative" | "parting"
    draft_classification: str   # "good" | "marginal" | "bad"


# =============================================================================
# Result dataclasses
# =============================================================================

@dataclass
class DraftSuggestion:
    """
    A single actionable correction suggestion for a group of problematic faces.

    Grouping rationale: mold engineers prefer consolidated instructions —
    "Add 1.5° to these 12 Plane faces using the parting line as neutral
    plane" — rather than one suggestion per face.  We group by surface type
    and mold side because the fix (and which mold half to cut) differs.

    Fields
    ------
    face_ids         : Face IDs that need correction (sorted).
    classification   : "bad" or "marginal".
    surface_type     : Dominant surface type in this group.
    mold_side        : "positive" (cavity) | "negative" (core) | "mixed".
    avg_angle_deg    : Mean draft angle across faces in this group.
    min_angle_deg    : Worst (minimum) draft angle in this group.
    total_area_mm2   : Combined surface area of affected faces.
    required_angle_deg : Minimum acceptable draft (from config).
    suggested_delta_deg: How many degrees to add = required - avg (clamped ≥ 0).
    action_text      : Human-readable, Bosch-style correction instruction.
    """
    face_ids: list[int]
    classification: str          # "bad" | "marginal"
    surface_type: str
    mold_side: str               # "positive" | "negative" | "mixed"
    avg_angle_deg: float
    min_angle_deg: float
    total_area_mm2: float
    required_angle_deg: float
    suggested_delta_deg: float
    action_text: str

    def to_dict(self) -> dict:
        return {
            "face_ids": self.face_ids,
            "classification": self.classification,
            "surface_type": self.surface_type,
            "mold_side": self.mold_side,
            "avg_angle_deg": round(self.avg_angle_deg, 3),
            "min_angle_deg": round(self.min_angle_deg, 3),
            "total_area_mm2": round(self.total_area_mm2, 3),
            "required_angle_deg": round(self.required_angle_deg, 3),
            "suggested_delta_deg": round(self.suggested_delta_deg, 3),
            "action_text": self.action_text,
        }


@dataclass
class DraftAnalysisResult:
    """
    Complete result of a single draft analysis pass.

    This object contains everything needed by:
    - The 3D visualiser (face_ids by classification + colors).
    - The AI Agent layer (severity, suggestions, summary_text).
    - The PDF report (all numeric stats, suggestions, pull direction).

    Severity levels (area-weighted, based on bad_area fraction):
        "none"     : 0% bad area          → All faces meet minimum draft.
        "minor"    : 0–5% bad area        → A few problematic faces, easy to fix.
        "moderate" : 5–20% bad area       → Notable rework required.
        "critical" : >20% bad area        → Major redesign likely needed.
    """

    # ── Input ─────────────────────────────────────────────────────────────
    pull_direction: Vec3
    pull_direction_label: str       # e.g. "+Z (default)", "optimal", "user-override"
    analysis_pass: str              # "initial" | "optimal" | "override"

    # ── Face classifications ───────────────────────────────────────────────
    good_face_ids: list[int]        # draft ≥ good_threshold_deg
    marginal_face_ids: list[int]    # marginal_threshold_deg ≤ draft < good_threshold_deg
    bad_face_ids: list[int]         # draft < marginal_threshold_deg
    skipped_face_ids: list[int]     # invalid normals — excluded from analysis

    # ── Area statistics ────────────────────────────────────────────────────
    good_area_mm2: float
    marginal_area_mm2: float
    bad_area_mm2: float
    skipped_area_mm2: float
    total_analysed_area_mm2: float  # good + marginal + bad (not skipped)

    # ── Thresholds used ────────────────────────────────────────────────────
    good_threshold_deg: float
    marginal_threshold_deg: float

    # ── Derived assessments ────────────────────────────────────────────────
    severity: str                   # "none" | "minor" | "moderate" | "critical"

    # Per-face result snapshot.  This makes each pass self-contained, so the UI
    # can compare "initial +Z" vs "optimal" even when only the final pass mutates
    # FaceData for the active color overlay.
    face_results: dict[int, FaceDraftResult] = field(default_factory=dict)
    suggestions: list[DraftSuggestion] = field(default_factory=list)

    # ── Metadata ───────────────────────────────────────────────────────────
    analysis_time_s: float = 0.0

    # ── Computed properties ───────────────────────────────────────────────
    @property
    def face_count_analysed(self) -> int:
        return len(self.good_face_ids) + len(self.marginal_face_ids) + len(self.bad_face_ids)

    @property
    def good_pct(self) -> float:
        if self.total_analysed_area_mm2 == 0:
            return 0.0
        return 100.0 * self.good_area_mm2 / self.total_analysed_area_mm2

    @property
    def marginal_pct(self) -> float:
        if self.total_analysed_area_mm2 == 0:
            return 0.0
        return 100.0 * self.marginal_area_mm2 / self.total_analysed_area_mm2

    @property
    def bad_pct(self) -> float:
        if self.total_analysed_area_mm2 == 0:
            return 0.0
        return 100.0 * self.bad_area_mm2 / self.total_analysed_area_mm2

    @property
    def is_manufacturable(self) -> bool:
        """True when no bad faces exist — part meets minimum draft everywhere."""
        return len(self.bad_face_ids) == 0

    def summary_text(self) -> str:
        """
        Multi-line human-readable summary.  Used by the AI Agent as context and
        printed to the console during development.
        """
        d = self.pull_direction
        lines = [
            "=" * 65,
            "  Draft Analysis Result",
            "=" * 65,
            f"  Pull direction  : ({d[0]:+.3f}, {d[1]:+.3f}, {d[2]:+.3f})"
            f"  [{self.pull_direction_label}]",
            f"  Analysis pass   : {self.analysis_pass}",
            f"  Thresholds      : good ≥ {self.good_threshold_deg}°  |  "
            f"marginal ≥ {self.marginal_threshold_deg}°  |  bad < {self.marginal_threshold_deg}°",
            "",
            f"  Faces analysed  : {self.face_count_analysed}"
            f"  (skipped: {len(self.skipped_face_ids)})",
            "",
            f"  {'Category':<12}  {'Faces':>6}  {'Area mm²':>12}  {'%':>7}",
            f"  {'─' * 42}",
            f"  {'✅ Good':<12}  {len(self.good_face_ids):>6}"
            f"  {self.good_area_mm2:>12.1f}  {self.good_pct:>6.1f}%",
            f"  {'⚠ Marginal':<12}  {len(self.marginal_face_ids):>6}"
            f"  {self.marginal_area_mm2:>12.1f}  {self.marginal_pct:>6.1f}%",
            f"  {'❌ Bad':<12}  {len(self.bad_face_ids):>6}"
            f"  {self.bad_area_mm2:>12.1f}  {self.bad_pct:>6.1f}%",
            "",
            f"  Severity        : {self.severity.upper()}",
            f"  Manufacturable  : {'YES' if self.is_manufacturable else 'NO — corrections needed'}",
        ]
        if self.suggestions:
            lines.append(f"\n  Suggestions ({len(self.suggestions)}):")
            for i, s in enumerate(self.suggestions, 1):
                lines.append(f"    [{i}] {s.action_text}")
        lines.append(f"\n  Analysis time   : {self.analysis_time_s:.3f} s")
        lines.append("=" * 65)
        return "\n".join(lines)

    def agent_context(self) -> str:
        """
        Compact context string injected into the LLM prompt.

        Designed to be short enough to fit in the AI Agent's context window
        without wasting tokens on formatting.  The Agent uses this to generate
        its natural-language DfM report section.
        """
        d = self.pull_direction
        lines = [
            f"DRAFT ANALYSIS [{self.pull_direction_label}]:",
            f"  direction=({d[0]:+.3f},{d[1]:+.3f},{d[2]:+.3f})",
            f"  good={len(self.good_face_ids)}faces({self.good_pct:.1f}%area)"
            f"  marginal={len(self.marginal_face_ids)}faces({self.marginal_pct:.1f}%area)"
            f"  bad={len(self.bad_face_ids)}faces({self.bad_pct:.1f}%area)",
            f"  severity={self.severity}  manufacturable={self.is_manufacturable}",
        ]
        for s in self.suggestions:
            lines.append(f"  SUGGESTION: {s.action_text}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """JSON-serialisable dict for API response and report."""
        d = self.pull_direction
        return {
            "pull_direction": list(d),
            "pull_direction_label": self.pull_direction_label,
            "analysis_pass": self.analysis_pass,
            "thresholds": {
                "good_deg": self.good_threshold_deg,
                "marginal_deg": self.marginal_threshold_deg,
            },
            "face_counts": {
                "good": len(self.good_face_ids),
                "marginal": len(self.marginal_face_ids),
                "bad": len(self.bad_face_ids),
                "skipped": len(self.skipped_face_ids),
                "total_analysed": self.face_count_analysed,
            },
            "face_ids": {
                "good": self.good_face_ids,
                "marginal": self.marginal_face_ids,
                "bad": self.bad_face_ids,
                "skipped": self.skipped_face_ids,
            },
            "face_results": {
                str(face_id): {
                    "draft_angle_deg": round(float(values["draft_angle_deg"]), 3),
                    "draft_classification": str(values["draft_classification"]),
                    "mold_side": str(values["mold_side"]),
                }
                for face_id, values in self.face_results.items()
            },
            "area_mm2": {
                "good": round(self.good_area_mm2, 3),
                "marginal": round(self.marginal_area_mm2, 3),
                "bad": round(self.bad_area_mm2, 3),
                "skipped": round(self.skipped_area_mm2, 3),
                "total_analysed": round(self.total_analysed_area_mm2, 3),
            },
            "percentages": {
                "good_pct": round(self.good_pct, 2),
                "marginal_pct": round(self.marginal_pct, 2),
                "bad_pct": round(self.bad_pct, 2),
            },
            "severity": self.severity,
            "is_manufacturable": self.is_manufacturable,
            "suggestions": [s.to_dict() for s in self.suggestions],
            "analysis_time_s": round(self.analysis_time_s, 4),
        }


# =============================================================================
# Internal pure functions
# =============================================================================

# Mold-side classification dot-product thresholds.
# A face with |n·d| < this is in the "parting region" — essentially vertical.
_PARTING_THRESHOLD: float = 0.01   # ≈ 0.57° from perpendicular


def _classify_draft(angle_deg: float, good_thresh: float, marginal_thresh: float) -> str:
    """
    Map a draft angle to a three-level classification string.

    Parameters
    ----------
    angle_deg       : Draft angle in degrees (always ≥ 0 from asin(|n·d|)).
    good_thresh     : Minimum angle for "good" (default 1.5°).
    marginal_thresh : Minimum angle for "marginal" (default 0.5°).

    Returns
    -------
    "good"     : angle_deg ≥ good_thresh
    "marginal" : marginal_thresh ≤ angle_deg < good_thresh
    "bad"      : angle_deg < marginal_thresh
    """
    if angle_deg >= good_thresh:
        return "good"
    if angle_deg >= marginal_thresh:
        return "marginal"
    return "bad"


def _mold_side(signed_dot: float) -> str:
    """
    Classify which mold half a face belongs to based on n·d.

    "positive" : n·d >  threshold  → cavity side (upper half)
    "negative" : n·d < -threshold  → core side (lower half)
    "parting"  : |n·d| ≤ threshold → near-perpendicular, parting candidate
    """
    if signed_dot > _PARTING_THRESHOLD:
        return "positive"
    if signed_dot < -_PARTING_THRESHOLD:
        return "negative"
    return "parting"


def _assess_severity(bad_area_frac: float) -> str:
    """
    Map the fraction of bad area to a severity label.

    Thresholds align with Protolabs DFM report conventions and Bosch
    internal DfM practice for injection-molded automotive plastics.

    0%           → "none"     (all clear)
    0–5%         → "minor"    (a few faces, easy to address)
    5–20%        → "moderate" (notable rework)
    >20%         → "critical" (major redesign needed)
    """
    if bad_area_frac <= 0.0:
        return "none"
    if bad_area_frac < 0.05:
        return "minor"
    if bad_area_frac < 0.20:
        return "moderate"
    return "critical"


def _build_suggestions(
    part: PartGeometry,
    pull_direction: Vec3,
    good_threshold_deg: float,
    face_results: Optional[dict[int, FaceDraftResult]] = None,
) -> list[DraftSuggestion]:
    """
    Build a prioritised list of draft correction suggestions.

    Grouping strategy
    -----------------
    Each suggestion covers a group of faces that share:
      1. The same classification level ("bad" before "marginal").
      2. The same dominant surface type (Plane, Cylinder, BSpline/NURBS, ...).
      3. The same mold side ("positive" / "negative" — different correction tool).
      4. The same resolved draft condition ("smooth", "light_texture", ... —
         Roadmap Phase 1e). A mixed smooth+textured group would otherwise
         report one wrong `required_angle_deg` for faces that actually need
         different amounts of draft.

    This mirrors how a mold engineer writes their DfM report:
      "Add 1.5° draft to the 8 Plane faces on the cavity side using the
       parting line as neutral plane."

    Correction text format
    ----------------------
    We produce Bosch-style action items matching the format seen in
    Protolabs / SolidWorks DfM reports, e.g.:
      "Add +1.3° draft to 5 Cylinder faces (core side, ~142 mm²) using
       the parting line as neutral plane."

    Sort order: bad before marginal, then by total area descending
    (largest affected area first = highest priority).
    """

    # ── Collect problematic faces ─────────────────────────────────────────
    # Group key: (classification, surface_type, mold_side, condition_applied)
    from collections import defaultdict

    groups: dict[tuple[str, str, str, str], list[FaceData]] = defaultdict(list)
    group_required_good_deg: dict[tuple[str, str, str, str], float] = {}

    for face in part.faces:
        if not face.normal_valid:
            continue

        snapshot = face_results.get(face.face_id) if face_results else None
        classification = (
            str(snapshot["draft_classification"])
            if snapshot is not None
            else face.draft_classification
        )
        if classification not in ("bad", "marginal"):
            continue
        s_dot = dot3(face.normal, pull_direction)
        side = _mold_side(s_dot)
        condition_applied = str(snapshot.get("condition_applied", "smooth")) if snapshot else "smooth"
        key = (classification, face.surface_type, side, condition_applied)
        groups[key].append(face)
        group_required_good_deg[key] = (
            float(snapshot["required_good_deg"])
            if snapshot and "required_good_deg" in snapshot
            else good_threshold_deg
        )

    if not groups:
        return []

    suggestions: list[DraftSuggestion] = []

    for (classification, surface_type, side, condition_applied), faces_in_group in groups.items():
        if not faces_in_group:
            continue

        angles: list[float] = []
        for f in faces_in_group:
            if face_results and f.face_id in face_results:
                angles.append(float(face_results[f.face_id]["draft_angle_deg"]))
            elif f.draft_angle_deg is not None:
                angles.append(f.draft_angle_deg)
        if not angles:
            continue

        required_good_deg = group_required_good_deg[
            (classification, surface_type, side, condition_applied)
        ]
        avg_angle = sum(angles) / len(angles)
        min_angle = min(angles)
        total_area = sum(f.area for f in faces_in_group)
        delta = max(0.0, required_good_deg - avg_angle)

        # ── Compose action text ────────────────────────────────────────────
        n = len(faces_in_group)
        side_label = (
            "cavity side" if side == "positive"
            else "core side" if side == "negative"
            else "parting region"
        )
        priority_label = "CRITICAL" if classification == "bad" else "WARNING"
        condition_label = f" [{condition_applied}]" if condition_applied != "smooth" else ""

        action = (
            f"[{priority_label}] Add +{delta:.1f}° draft to {n} "
            f"{surface_type} face{'s' if n > 1 else ''}{condition_label} "
            f"({side_label}, {total_area:.0f} mm²). "
            f"Min angle: {min_angle:.2f}°. Required: {required_good_deg:.1f}°. "
            f"Neutral plane: parting line."
        )

        suggestions.append(DraftSuggestion(
            face_ids=sorted(f.face_id for f in faces_in_group),
            classification=classification,
            surface_type=surface_type,
            mold_side=side,
            avg_angle_deg=round(avg_angle, 3),
            min_angle_deg=round(min_angle, 3),
            total_area_mm2=round(total_area, 3),
            required_angle_deg=required_good_deg,
            suggested_delta_deg=round(delta, 3),
            action_text=action,
        ))

    # Sort: bad > marginal, then largest area first
    def _sort_key(s: DraftSuggestion) -> tuple[int, float]:
        priority = 0 if s.classification == "bad" else 1
        return (priority, -s.total_area_mm2)

    suggestions.sort(key=_sort_key)
    return suggestions


# =============================================================================
# Public API
# =============================================================================

#: Draft conditions known to `_condition_thresholds`. Not auto-detected from
#: geometry (STEP carries no surface-finish/texture data) — set explicitly
#: per face via `analyze_draft`'s `face_conditions` parameter.
_KNOWN_DRAFT_CONDITIONS = frozenset(
    {"smooth", "light_texture", "heavy_texture", "deep_rib"}
)


def _condition_thresholds(condition: str, cfg: "DraftSettings") -> tuple[float, float]:
    conditions = cfg.conditions
    mapping = {
        "smooth": (conditions.smooth_good_deg, conditions.smooth_marginal_deg),
        "light_texture": (
            conditions.light_texture_good_deg,
            conditions.light_texture_marginal_deg,
        ),
        "heavy_texture": (
            conditions.heavy_texture_good_deg,
            conditions.heavy_texture_marginal_deg,
        ),
        "deep_rib": (conditions.deep_rib_good_deg, conditions.deep_rib_marginal_deg),
    }
    return mapping[condition]


def _resolve_face_thresholds(
    face_id: int,
    face_conditions: Optional[dict[int, str]],
    default_good: float,
    default_marginal: float,
    cfg: "DraftSettings",
) -> tuple[float, float, str, str]:
    """
    Resolve which draft thresholds apply to one face (Roadmap Phase 1e).

    Resolution order implemented: explicit per-face override -> global
    default. Surface-type defaults and automatic deep-rib geometric
    detection are NOT implemented — every surface type honestly defaults to
    "smooth" today (STEP AP203/AP214 carries no texture/surface-finish
    data, so there is nothing to auto-detect), and a deep-rib face can
    still be flagged manually via `face_conditions` even without automatic
    detection.
    """
    if face_conditions and face_id in face_conditions:
        condition = face_conditions[face_id]
        if condition in _KNOWN_DRAFT_CONDITIONS:
            good, marginal = _condition_thresholds(condition, cfg)
            return good, marginal, "explicit_override", condition
        logger.warning(
            "Unknown draft condition %r for face %d; falling back to global default.",
            condition, face_id,
        )
    return default_good, default_marginal, "global_default", "smooth"


def precompute_directional_metrics(
    part: PartGeometry,
    pull_direction: Vec3,
) -> dict[int, FaceDirectionalMetrics]:
    """
    Compute n·d and derived draft metrics for every valid face in one pass.

    Intended for the direction-optimizer candidate loop where the same pull
    direction is consumed by both ``analyze_draft()`` and
    ``detect_undercuts()``.  Passing the returned dict to both as
    ``precomputed_metrics`` eliminates the redundant n·d computations those
    functions would otherwise each perform independently.

    Notes
    -----
    - Global draft thresholds are used.  Per-face ``face_conditions``
      overrides are NOT applied — callers that need per-face threshold
      overrides should call ``analyze_draft()`` directly without precomputed
      metrics.
    - Faces with ``normal_valid=False`` are omitted from the returned dict.
    - The returned dict is keyed by ``face_id`` (0-based integer).
    - For 311 faces × 54 candidates this eliminates ~33 k redundant dot-
      product computations per optimize_mold_direction() call.
    """
    pull_dir = normalize3(pull_direction)
    cfg = settings.dfm.draft
    good_thresh = cfg.good_threshold_deg
    marginal_thresh = cfg.marginal_threshold_deg
    result: dict[int, FaceDirectionalMetrics] = {}
    for face in part.faces:
        if not face.normal_valid:
            continue
        raw = dot3(face.normal, pull_dir)
        clamped = max(-1.0, min(1.0, raw))
        angle_deg = math.degrees(math.asin(abs(clamped)))
        result[face.face_id] = FaceDirectionalMetrics(
            signed_dot=clamped,
            draft_angle_deg=angle_deg,
            mold_side=_mold_side(clamped),
            draft_classification=_classify_draft(angle_deg, good_thresh, marginal_thresh),
        )
    return result


def analyze_draft(
    part: PartGeometry,
    pull_direction: Vec3,
    pull_direction_label: str = "user-specified",
    analysis_pass: str = "initial",
    mutate: bool = True,
    face_conditions: Optional[dict[int, str]] = None,
    precomputed_metrics: Optional[dict[int, FaceDirectionalMetrics]] = None,
) -> DraftAnalysisResult:
    """
    Compute draft angles for all valid faces and return a `DraftAnalysisResult`.

    Side effects
    ------------
    When ``mutate=True`` (default), mutates `FaceData.draft_angle_deg` and
    `FaceData.draft_classification` on every valid face in `part.faces`.
    Faces with `normal_valid=False` are skipped and set to `None`.

    When ``mutate=False``, `FaceData` is not changed.  Use this for the initial
    +Z pass when the UI wants a before-vs-after comparison while preserving the
    current active overlay on the part.

    Parameters
    ----------
    part              : Loaded PartGeometry (from step_loader.load_step).
    pull_direction    : Unit vector for the mold opening direction.
                        Need not be unit — we normalise defensively.
    pull_direction_label : Human-readable label for reports ("initial +Z",
                        "optimal", "user-override").
    analysis_pass     : "initial" | "optimal" | "override".
                        Stored in result for traceability.
    mutate            : If True, enrich `FaceData` in place. If False, only
                        return a standalone result snapshot.
    face_conditions   : Optional face_id -> condition name map ("smooth" |
                        "light_texture" | "heavy_texture" | "deep_rib").
                        Overrides the global good/marginal thresholds for
                        those specific faces (Roadmap Phase 1e) — e.g. the
                        frontend lets a user mark faces as textured, which
                        need more draft than a smooth wall. Unknown
                        condition names log a warning and fall back to the
                        global default rather than raising. Every face's
                        resolved threshold and its source
                        ("explicit_override" | "global_default") are
                        reported in `face_results[face_id]`.

    Returns
    -------
    DraftAnalysisResult
        Complete analysis with face IDs, areas, severity, and suggestions.
    """
    t_start = time.perf_counter()

    # ── Normalise pull direction defensively ──────────────────────────────
    try:
        pull_dir = normalize3(pull_direction)
    except ValueError as exc:
        raise ValueError(
            f"pull_direction {pull_direction} cannot be normalised: {exc}"
        ) from exc

    cfg = settings.dfm.draft
    good_thresh = cfg.good_threshold_deg
    marginal_thresh = cfg.marginal_threshold_deg

    logger.info(
        "Draft analysis | dir=(%+.3f,%+.3f,%+.3f) [%s] | good≥%.1f° marginal≥%.1f°",
        *pull_dir, pull_direction_label, good_thresh, marginal_thresh,
    )

    # ── Per-face analysis ─────────────────────────────────────────────────
    good_ids: list[int] = []
    marginal_ids: list[int] = []
    bad_ids: list[int] = []
    skipped_ids: list[int] = []

    good_area = 0.0
    marginal_area = 0.0
    bad_area = 0.0
    skipped_area = 0.0
    face_results: dict[int, FaceDraftResult] = {}

    for face in part.faces:
        if not face.normal_valid:
            if mutate:
                face.draft_angle_deg = None
                face.draft_classification = None
            skipped_ids.append(face.face_id)
            skipped_area += face.area
            continue

        pm = (
            precomputed_metrics.get(face.face_id)
            if precomputed_metrics is not None and face_conditions is None
            else None
        )
        if pm is not None:
            angle = pm.draft_angle_deg
            classification = pm.draft_classification
            side = pm.mold_side
            face_good_thresh = good_thresh
            face_marginal_thresh = marginal_thresh
            threshold_source = "global_default"
            condition_applied = "smooth"
        else:
            angle = face.draft_angle_for_direction(pull_dir)
            (
                face_good_thresh,
                face_marginal_thresh,
                threshold_source,
                condition_applied,
            ) = _resolve_face_thresholds(
                face.face_id, face_conditions, good_thresh, marginal_thresh, cfg
            )
            classification = _classify_draft(angle, face_good_thresh, face_marginal_thresh)
            side = _mold_side(dot3(face.normal, pull_dir))

        face_results[face.face_id] = {
            "draft_angle_deg": angle,
            "draft_classification": classification,
            "mold_side": side,
            "required_good_deg": face_good_thresh,
            "required_marginal_deg": face_marginal_thresh,
            "threshold_source": threshold_source,
            "condition_applied": condition_applied,
        }

        # ── Mutate FaceData ───────────────────────────────────────────────
        if mutate:
            face.draft_angle_deg = angle
            face.draft_classification = classification

        if classification == "good":
            good_ids.append(face.face_id)
            good_area += face.area
        elif classification == "marginal":
            marginal_ids.append(face.face_id)
            marginal_area += face.area
        else:
            bad_ids.append(face.face_id)
            bad_area += face.area

    total_area = good_area + marginal_area + bad_area
    bad_frac = bad_area / total_area if total_area > 0 else 0.0
    severity = _assess_severity(bad_frac)

    # ── Build suggestions ─────────────────────────────────────────────────
    suggestions = _build_suggestions(part, pull_dir, good_thresh, face_results)

    elapsed = time.perf_counter() - t_start

    logger.info(
        "Draft result: good=%d(%.1f%%) marginal=%d(%.1f%%) bad=%d(%.1f%%) "
        "skipped=%d  severity=%s  time=%.3fs",
        len(good_ids), 100 * good_area / total_area if total_area else 0,
        len(marginal_ids), 100 * marginal_area / total_area if total_area else 0,
        len(bad_ids), 100 * bad_area / total_area if total_area else 0,
        len(skipped_ids), severity, elapsed,
    )

    return DraftAnalysisResult(
        pull_direction=pull_dir,
        pull_direction_label=pull_direction_label,
        analysis_pass=analysis_pass,
        good_face_ids=good_ids,
        marginal_face_ids=marginal_ids,
        bad_face_ids=bad_ids,
        skipped_face_ids=skipped_ids,
        good_area_mm2=good_area,
        marginal_area_mm2=marginal_area,
        bad_area_mm2=bad_area,
        skipped_area_mm2=skipped_area,
        total_analysed_area_mm2=total_area,
        face_results=face_results,
        good_threshold_deg=good_thresh,
        marginal_threshold_deg=marginal_thresh,
        severity=severity,
        suggestions=suggestions,
        analysis_time_s=elapsed,
    )


def analyze_draft_default(
    part: PartGeometry,
    mutate: bool = True,
    face_conditions: Optional[dict[int, str]] = None,
) -> DraftAnalysisResult:
    """
    Run draft analysis using the default pull direction (+Z axis).

    This is the first thing the mold engineer does on receiving a new .stp
    file: check draft in the default orientation to get an initial picture
    before the optimal direction is computed.

    Called automatically at the start of the DfM pipeline; the result is
    shown immediately in the UI while the more expensive Bassi direction
    optimisation runs in the background.
    """
    return analyze_draft(
        part=part,
        pull_direction=(0.0, 0.0, 1.0),
        pull_direction_label="initial +Z (default)",
        analysis_pass="initial",
        mutate=mutate,
        face_conditions=face_conditions,
    )


def analyze_draft_optimal(
    part: PartGeometry,
    optimal_direction: Vec3,
    mutate: bool = True,
    face_conditions: Optional[dict[int, str]] = None,
) -> DraftAnalysisResult:
    """
    Re-run draft analysis on the optimal pull direction from Bassi's algorithm.

    This replaces the initial +Z result with the final, correct draft map.
    Calling this MUTATES all FaceData.draft_angle_deg values — the initial
    +Z values are overwritten.

    Called by `direction_optimizer.py` after it selects the best direction.
    """
    return analyze_draft(
        part=part,
        pull_direction=optimal_direction,
        pull_direction_label="optimal (Bassi 2010)",
        analysis_pass="optimal",
        mutate=mutate,
        face_conditions=face_conditions,
    )


def get_draft_color(face: FaceData) -> tuple[float, float, float]:
    """
    Return the RGB visualisation color (0–1 each) for a face based on its
    draft classification.

    Used by the PyVista/Streamlit frontend to build the color overlay.

    "good"     → green   (0.0,  0.85, 0.3)
    "marginal" → yellow  (1.0,  0.85, 0.0)
    "bad"      → red     (0.95, 0.15, 0.1)
    None       → grey    (0.55, 0.55, 0.55)  — invalid normal / not yet analysed
    """
    cls = face.draft_classification
    if cls == "good":
        return (0.0, 0.85, 0.3)
    if cls == "marginal":
        return (1.0, 0.85, 0.0)
    if cls == "bad":
        return (0.95, 0.15, 0.1)
    return (0.55, 0.55, 0.55)


def draft_colors_for_part(part: PartGeometry) -> list[tuple[float, float, float]]:
    """
    Return a list of RGB colors, one per face, in face_id order.

    Used by the PyVista frontend as the scalar color array:
        plotter.add_mesh(mesh, scalars=colors, rgb=True)

    Prerequisite: `analyze_draft` must have been called on `part` first.
    If called before analysis, all faces return grey.
    """
    return [get_draft_color(f) for f in part.faces]


# =============================================================================
# CLI entry point
# =============================================================================

if __name__ == "__main__":
    import sys
    import json
    import logging
    from pathlib import Path

    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(name)s: %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python draft_analyzer.py <Part.stp> [dx dy dz]")
        print("  dx dy dz  — optional pull direction (default: 0 0 1)")
        sys.exit(1)

    from backend.geometry.step_loader import load_step

    stp = sys.argv[1]
    dx = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    dy = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
    dz = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0

    part = load_step(stp)
    result = analyze_draft(part, (dx, dy, dz), pull_direction_label="CLI input")

    print(result.summary_text())

    out = Path(stp).with_suffix(".draft.json")
    with open(out, "w") as fh:
        json.dump(result.to_dict(), fh, indent=2)
    print(f"\nJSON saved → {out}")
