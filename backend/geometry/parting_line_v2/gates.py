"""
backend/geometry/parting_line_v2/gates.py
-----------------------------------------
The hard feasibility filter H0-H7 (plan §7).

**Every candidate passes or is rejected with a named reason. Nothing is scored
until it has passed.** This is the structural fix for audit RC-4: v1 folds
validity signals (gaps, branches) into the same 0-1 number as preferences, so
nothing is ever rejected and the pipeline always returns *something*. Measured
at P0, v1 returns ``status = ok`` on four fixtures whose silhouette it cannot
see at all.

The gates are not equal (plan §7.0)
-----------------------------------
=================  ==========================  ==================================
class              gates                       status
=================  ==========================  ==================================
**definitional**   H0, H1, H2, H3, H6          consequences of §1's C1-C4;
                                               not tunable, not negotiable
**physical**       H4                          follows from C5; its tolerances
                                               are on a real physical condition
**routing/sanity** H5, H7                      heuristic, provisional
=================  ==========================  ==================================

**H3 is the primary validity criterion.** H7 (coverage) is a conservative
sanity gate and a strong ranking signal — there is no manufacturing law saying
a valid parting line covers ≥ X% of projected area, and §8.1's cheap
denominator is an upper bound anyway. **If H3 and H7 disagree, H3 is right.**
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from backend.geometry.parting_line_v2 import measures
from backend.geometry.parting_line_v2.contracts import DelegatedSecondaryAction, UndercutInput
from backend.geometry.parting_line_v2.regions import (
    RegionClassification,
    SeparationResult,
    classify_regions,
    separate_surface,
    validate_delegation,
)
from backend.geometry.parting_line_v2.types import (
    CurveSegment,
    EdgeBacking,
    FaceBacking,
    FeasibilityReport,
    OnSurfaceReport,
    PartingLoopCandidate,
    SideActionReferral,
)
from backend.models.geometry_models import PartGeometry, Vec3, dot3

try:
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.BRepTools import breptools
    from OCC.Core.BRepTopAdaptor import BRepTopAdaptor_FClass2d
    from OCC.Core.GeomAPI import GeomAPI_ProjectPointOnCurve, GeomAPI_ProjectPointOnSurf
    from OCC.Core.gp import gp_Pnt, gp_Pnt2d
    from OCC.Core.TopAbs import TopAbs_IN, TopAbs_ON

    _OCC_AVAILABLE = True
except Exception:  # pragma: no cover
    _OCC_AVAILABLE = False


__all__ = ["GateOutcome", "evaluate_gates", "evaluate_on_surface"]


@dataclass(frozen=True)
class GateOutcome:
    """Feasibility plus the artefacts H3 produced, so nothing is recomputed."""

    report: FeasibilityReport
    separation: SeparationResult | None = None
    regions: RegionClassification | None = None


# ---------------------------------------------------------------------------
# H0 — on-surface validity (runs before everything)
# ---------------------------------------------------------------------------

def evaluate_on_surface(
    part: PartGeometry,
    segments: tuple[CurveSegment, ...],
    *,
    cfg: object,
    bbox_diagonal_mm: float,
) -> OnSurfaceReport:
    """
    Gate H0 — every point of ``Γ`` provably lies on the B-Rep.

    Measured against the **actual OCC geometry**: edge points are projected
    onto the edge's own ``Geom_Curve``. Never against the display tessellation
    and never against the camera projection — a curve can look perfect from
    the camera and still sit 0.5 mm off the surface.

    Sub-tests (plan H0):

    * **H0.1** every segment carries a resolvable OCC backing. Enforced
      structurally by ``CurveSegment`` (it cannot be constructed otherwise),
      so this counts rather than discovers.
    * **H0.2** edge-derived: ``dist(p, edge_curve) ≤ τ_edge``.
    * **H0.3** face-derived: ``dist(p, surface) ≤ τ_surface``, ``(u,v)``
      inside the trimmed face, ``|g| ≤ τ_silhouette``. **No face-backed
      segments exist at Level 0** — Track B lands in P2 — so this reports 0.
    * **H0.4** no projection-only geometry. Structural: every point here came
      from ``BRepAdaptor_Curve.Value(t)``.

    Note on ``max_silhouette_error``: it is computed over **face-backed points
    only**, and that is not an omission. At a sharp edge the normal is
    *set-valued*, so there is no single ``g`` to bound; the correct condition
    there is the straddle ``0 ∈ [g_a, g_b]``, which Track A tests directly.
    """
    tau_edge = max(cfg.edge_tolerance_rel * bbox_diagonal_mm, 1e-7)
    tau_surface = max(cfg.surface_tolerance_rel * bbox_diagonal_mm, 1e-7)
    tau_silhouette = cfg.silhouette_epsilon * cfg.silhouette_error_factor

    max_edge_deviation = 0.0
    max_surface_deviation = 0.0
    max_silhouette_error = 0.0
    off_face = 0
    unbacked = 0
    worst: tuple[int, Vec3] | None = None
    failed: set[str] = set()
    notes: list[str] = []

    edges_by_id = {e.edge_id: e for e in part.edges}
    faces_by_id = {f.face_id: f for f in part.faces}

    for segment in segments:
        backing = segment.backing
        if backing is None:  # pragma: no cover - unconstructable
            unbacked += 1
            failed.add("H0.1")
            continue

        if isinstance(backing, EdgeBacking):
            edge = edges_by_id.get(backing.edge_id)
            if edge is None:
                unbacked += 1
                failed.add("H0.1")
                continue
            if not _OCC_AVAILABLE:
                notes.append("OCC unavailable; H0.2 could not be measured.")
                continue
            try:
                curve, first, last = BRep_Tool.Curve(edge.occ_edge)
            except Exception:
                curve = None
            if curve is None:
                unbacked += 1
                failed.add("H0.1")
                notes.append(f"edge {backing.edge_id} has no 3-D curve to check against")
                continue
            for point in segment.points:
                try:
                    projector = GeomAPI_ProjectPointOnCurve(gp_Pnt(*point), curve, first, last)
                    distance = float(projector.LowerDistance()) if projector.NbPoints() else float("inf")
                except Exception:
                    distance = float("inf")
                if distance > max_edge_deviation:
                    max_edge_deviation = distance
                    worst = (segment.segment_id, point)

        elif isinstance(backing, FaceBacking):
            face = faces_by_id.get(backing.face_id)
            if face is None or not _OCC_AVAILABLE:
                unbacked += 1
                failed.add("H0.1")
                continue
            try:
                surface = BRep_Tool.Surface(face.occ_face)
                classifier = BRepTopAdaptor_FClass2d(face.occ_face, 1e-7)
            except Exception:
                unbacked += 1
                failed.add("H0.1")
                continue

            # D-024: GeomAPI_ProjectPointOnSurf's implicit-bounds constructor
            # searches only the underlying Geom_Surface's OWN declared
            # Bounds() (e.g. a BSplineSurface's clean [0,1]x[0,1] knot
            # domain) -- NOT the face's real trimmed extent. A face's trim
            # wires can legitimately reach past that domain (measured on
            # Part3 face 274: Bounds() = [0,1]x[0,1], but the trim wire's own
            # UVBounds() reaches v=1.0121, ~1.2% beyond it), and a point that
            # is validly on the B-Rep there has no zero-distance match within
            # the restricted search -- so the projector snaps to the nearest
            # point it CAN find inside Bounds(), several microns off, and
            # H0.3 rejects a genuinely on-surface point. breptools.UVBounds
            # is the SAME authoritative trim extent BRepTopAdaptor_FClass2d
            # (used two lines above, and again below for containment) is
            # built from -- not an invented or expanded domain, the one this
            # module already trusts. Falls back to the implicit-bounds form
            # only if the trim extent itself cannot be determined, so this
            # cannot silently skip the check.
            try:
                u_min, u_max, v_min, v_max = breptools.UVBounds(face.occ_face)
                trim_bounds = (
                    u_min, u_max, v_min, v_max
                ) if all(math.isfinite(x) for x in (u_min, u_max, v_min, v_max)) else None
            except Exception:
                trim_bounds = None

            for point, (u, v) in zip(segment.points, backing.uv):
                # (a) the point must lie on the surface...
                try:
                    if trim_bounds is not None:
                        projector = GeomAPI_ProjectPointOnSurf(gp_Pnt(*point), surface, *trim_bounds)
                    else:
                        projector = GeomAPI_ProjectPointOnSurf(gp_Pnt(*point), surface)
                    distance = float(projector.LowerDistance()) if projector.NbPoints() else float("inf")
                except Exception:
                    distance = float("inf")
                if distance > max_surface_deviation:
                    max_surface_deviation = distance
                    worst = (segment.segment_id, point)
                # (b) ...AND inside the face's TRIMMED region. A point can sit
                # exactly on the underlying surface while being outside the
                # face's wires — that is how marching squares escapes onto the
                # untrimmed extension, and it is the specific mechanism by
                # which an off-part curve would reappear.
                try:
                    if classifier.Perform(gp_Pnt2d(u, v)) not in (TopAbs_IN, TopAbs_ON):
                        off_face += 1
                except Exception:
                    off_face += 1

            for g_value in segment.g_values:
                max_silhouette_error = max(max_silhouette_error, abs(g_value))

    if max_edge_deviation > tau_edge:
        failed.add("H0.2")
    if max_surface_deviation > tau_surface:
        failed.add("H0.3")
    if max_silhouette_error > tau_silhouette:
        failed.add("H0.3")
    if off_face:
        failed.add("H0.3")

    if not any(isinstance(s.backing, FaceBacking) for s in segments):
        notes.append(
            "No face-backed points at Level 0 (Track B lands in P2), so "
            "max_silhouette_error is reported as 0. The sharp-edge silhouette "
            "condition is the straddle 0 in [g_a, g_b], checked in Track A."
        )

    return OnSurfaceReport(
        passed=not failed,
        max_surface_deviation_mm=max_surface_deviation,
        max_edge_deviation_mm=max_edge_deviation,
        max_silhouette_error=max_silhouette_error,
        off_face_point_count=off_face,
        unbacked_segment_count=unbacked,
        worst_offender=worst,
        failed_subtests=tuple(sorted(failed)),
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------------
# H0-H7
# ---------------------------------------------------------------------------

def evaluate_gates(
    candidate: PartingLoopCandidate,
    part: PartGeometry,
    pull_direction: Vec3,
    *,
    undercuts: UndercutInput,
    cfg: object,
    bbox_diagonal_mm: float,
    part_projected_area_mm2: float,
    delegations: tuple[DelegatedSecondaryAction, ...] = (),
) -> GateOutcome:
    """
    Run H0-H7 in order, cheapest-first except H0. Returns on first failure.

    ``delegations`` (D-044, default empty -- inert unless explicitly
    supplied, matching every existing caller): candidate
    ``DelegatedSecondaryAction`` records, each independently re-validated
    against THIS candidate and THIS ``pull_direction`` via
    ``regions.validate_delegation`` before H4 runs. Only records that pass
    contribute face ids H4 excludes from its region area/violation-area
    sums -- H4 never reads a delegation's ``movement_type``, ``evidence``,
    or provenance, only the validated face-id set. Passing validation is
    NOT a geometric release proof; see ``DelegationEligibility``'s and
    ``DelegatedSecondaryAction.evidence.geometric_verification``'s
    docstrings.
    """
    measurements: dict[str, float] = {}
    points = candidate.points
    loop_edge_ids = frozenset(
        s.backing.edge_id for s in candidate.segments if isinstance(s.backing, EdgeBacking)
    )
    # Populated just before H4 runs; every FeasibilityReport constructed at
    # H4 or later carries whatever was validated by that point (empty before
    # H4, since delegation is meaningless without a passed H3 region split).
    validated_delegations: tuple[DelegatedSecondaryAction, ...] = ()

    def reject(gate, reason: str, referral: SideActionReferral | None = None) -> GateOutcome:
        return GateOutcome(FeasibilityReport(
            passed=False, failed_gate=gate, reason=reason,
            measurements=measurements, on_surface=on_surface, referral=referral,
            validated_delegations=validated_delegations,
        ))

    # --- H0 -----------------------------------------------------------------
    on_surface = evaluate_on_surface(
        part, candidate.segments, cfg=cfg, bbox_diagonal_mm=bbox_diagonal_mm
    )
    measurements["h0_max_edge_deviation_mm"] = on_surface.max_edge_deviation_mm
    measurements["h0_max_surface_deviation_mm"] = on_surface.max_surface_deviation_mm
    if not on_surface.passed:
        return reject("H0", (
            f"Curve is not provably on the B-Rep: failed "
            f"{', '.join(on_surface.failed_subtests)} "
            f"(max edge deviation {on_surface.max_edge_deviation_mm:.6g} mm)."
        ))

    # --- H1 closed (EVERY component curve of Γ) -----------------------------
    tau_close = max(cfg.closure_tolerance_rel * bbox_diagonal_mm, 1e-7)
    closure_error = max(
        (math.dist(loop[0], loop[-1]) for loop in candidate.loops if len(loop) >= 2),
        default=float("inf"),
    )
    measurements["h1_closure_error_mm"] = closure_error
    measurements["h1_loop_count"] = float(candidate.loop_count)
    if closure_error > tau_close:
        return reject("H1", (
            f"Loop is not closed: worst component's endpoints are {closure_error:.6g} mm "
            f"apart (tolerance {tau_close:.6g} mm)."
        ))

    # --- H2 simple (within each curve AND between curves) -------------------
    tau_weld = max(cfg.weld_tolerance_rel * bbox_diagonal_mm, 1e-7)
    intersects, checked_pairs, confirmed = measures.self_intersection_multi(
        candidate.loops, pull_direction, tolerance=tau_weld
    )
    measurements["h2_checked_pairs"] = float(checked_pairs)
    measurements["h2_confirmed_intersections"] = float(confirmed)
    if intersects:
        return reject("H2", (
            f"Γ is not simple: {confirmed} crossing(s) confirmed in 3-D out of "
            f"{checked_pairs} projected pair(s) checked (includes cross-loop pairs)."
        ))

    # --- H3 separates (THE primary validity test) ---------------------------
    # Faces the loop passes THROUGH must be split, or the edge-only adjacency
    # test cannot see the cut at all (a sphere's great circle divides its single
    # face, but that face is one node with no link to remove).
    split_face_ids = frozenset(
        s.backing.face_id for s in candidate.segments if isinstance(s.backing, FaceBacking)
    )
    loop_edge_intervals: dict[int, list[tuple[float, float]]] = {}
    for segment in candidate.segments:
        if isinstance(segment.backing, EdgeBacking):
            loop_edge_intervals.setdefault(segment.backing.edge_id, []).append(
                (segment.backing.t_start, segment.backing.t_end)
            )
    separation = separate_surface(
        part, loop_edge_ids,
        split_face_ids=split_face_ids, pull_direction=pull_direction,
        loop_edge_intervals=loop_edge_intervals,
        # Non-geometric H3 partition metadata (plan D-043) -- never a curve
        # in candidate.segments/.loops. See PartingLoopCandidate's field
        # docstring and regions.separate_surface's "Tooling splits" section.
        tooling_split_face_ids=dict(candidate.tooling_split_face_ids),
    )
    measurements["h3_region_count"] = float(separation.component_count)
    measurements["h3_split_face_count"] = float(len(split_face_ids))
    if not separation.separates:
        detail = (
            "does not separate the part (1 region)"
            if separation.component_count == 1
            else f"over-partitions the part ({separation.component_count} regions)"
        )
        return GateOutcome(
            FeasibilityReport(
                passed=False, failed_gate="H3",
                reason=f"Loop {detail}; a parting line must produce exactly 2.",
                measurements=measurements, on_surface=on_surface,
            ),
            separation=separation,
        )

    loop_face_ids = frozenset(
        face_id for edge_id in loop_edge_ids
        for face_id in part.edge_to_faces.get(edge_id, ())
    )
    regions = classify_regions(
        part, separation, pull_direction, loop_face_ids=loop_face_ids, cfg=cfg,
        tooling_split_face_ids=dict(candidate.tooling_split_face_ids),
    )

    # --- H4 orientation consistency -----------------------------------------
    # D-044: delegations are (re-)validated HERE, per candidate and per
    # pull_direction, never trusted from an earlier call. Only entries that
    # pass contribute face ids to exclude, and only H4's decision logic ever
    # reads that face-id set -- movement_type/evidence/source/verification
    # are reporting metadata, consumed nowhere in this block.
    validated_delegations = tuple(
        d for d in delegations if validate_delegation(part, candidate, d, pull_direction, cfg).eligible
    )
    delegated_face_ids = frozenset(fid for d in validated_delegations for fid in d.face_ids)

    faces_by_id = {f.face_id: f for f in part.faces}
    g_by_id = {c.face_id: c.mean_g for c in regions.faces}
    worst_violation = 0.0
    for label, component in (
        ("cavity", regions.cavity_face_ids), ("core", regions.core_face_ids)
    ):
        # Region-aware: only THIS region's own intersection with the
        # validated delegated set is removed -- a face delegated for one
        # candidate's cavity is never subtracted from an unrelated region.
        evaluated = frozenset(component) - delegated_face_ids
        area = sum(faces_by_id[f].area for f in evaluated if f in faces_by_id)
        if area <= 0:
            continue
        sign = 1.0 if label == "cavity" else -1.0
        violating = sum(
            faces_by_id[f].area for f in evaluated
            if f in g_by_id and sign * g_by_id[f] < -cfg.orientation_epsilon
        )
        worst_violation = max(worst_violation, violating / area)
    measurements["h4_orientation_violation_fraction"] = worst_violation
    measurements["h4_delegated_face_count"] = float(len(delegated_face_ids))
    if worst_violation > cfg.orientation_violation_max:
        return GateOutcome(
            FeasibilityReport(
                passed=False, failed_gate="H4",
                reason=(
                    f"{worst_violation * 100:.1f}% of one region's remaining "
                    "primary-moving area faces the wrong way (limit "
                    f"{cfg.orientation_violation_max * 100:.1f}%); the two sides are not "
                    "separately mold-accessible, even after excluding "
                    f"{len(delegated_face_ids)} validated delegated face(s)."
                ),
                measurements=measurements, on_surface=on_surface,
                validated_delegations=validated_delegations,
            ),
            separation=separation, regions=regions,
        )

    # --- H5 undercut: ROUTE, do not condemn ---------------------------------
    conflicting = undercuts.undercut_face_ids & loop_face_ids
    measurements["h5_conflicting_face_count"] = float(len(conflicting))
    if conflicting:
        features = undercuts.features_touching(conflicting)
        conflict_segments = tuple(
            s.segment_id for s in candidate.segments
            if isinstance(s.backing, EdgeBacking)
            and set(part.edge_to_faces.get(s.backing.edge_id, ())) & conflicting
        )
        conflict_length = sum(
            measures.polyline_length_3d(s.points)
            for s in candidate.segments if s.segment_id in conflict_segments
        )
        referral = SideActionReferral(
            feature_ids=tuple(f.feature_id for f in features),
            conflicting_segment_ids=conflict_segments,
            conflict_length_mm=conflict_length,
            release_direction_hint=next(
                (f.release_direction for f in features if f.release_direction), None
            ),
        )
        return GateOutcome(
            FeasibilityReport(
                passed=False, failed_gate="H5",
                reason="requires_side_action",
                measurements=measurements, on_surface=on_surface, referral=referral,
                validated_delegations=validated_delegations,
            ),
            separation=separation, regions=regions,
        )

    # --- H6 non-degenerate --------------------------------------------------
    length = sum(measures.polyline_length_3d(loop, closed=True) for loop in candidate.loops)
    projected_area = measures.largest_loop_projected_area(candidate.loops, pull_direction)
    distinct = measures.distinct_point_count(points, tau_weld)
    measurements["h6_length_mm"] = length
    measurements["h6_projected_area_mm2"] = projected_area
    measurements["h6_distinct_points"] = float(distinct)

    min_length = cfg.min_length_rel * bbox_diagonal_mm
    min_area = cfg.min_projected_area_rel * bbox_diagonal_mm ** 2
    if length < min_length or projected_area < min_area or distinct < 4:
        return GateOutcome(
            FeasibilityReport(
                passed=False, failed_gate="H6",
                reason=(
                    f"Loop is degenerate: length {length:.4g} mm (min {min_length:.4g}), "
                    f"projected area {projected_area:.4g} mm² (min {min_area:.4g}), "
                    f"{distinct} distinct point(s) (min 4)."
                ),
                measurements=measurements, on_surface=on_surface,
                validated_delegations=validated_delegations,
            ),
            separation=separation, regions=regions,
        )

    # --- H7 coverage: PROVISIONAL sanity gate, not a manufacturing law ------
    coverage = projected_area / part_projected_area_mm2 if part_projected_area_mm2 > 0 else 0.0
    measurements["h7_coverage"] = coverage
    if coverage < cfg.min_coverage_ratio:
        return GateOutcome(
            FeasibilityReport(
                passed=False, failed_gate="H7",
                reason=(
                    f"below_provisional_coverage_gate: loop spans {coverage * 100:.1f}% of "
                    f"the part's projected outline (provisional gate "
                    f"{cfg.min_coverage_ratio * 100:.0f}%). Probably a local feature loop — "
                    "this is a heuristic, not a geometric invalidity."
                ),
                measurements=measurements, on_surface=on_surface,
                validated_delegations=validated_delegations,
            ),
            separation=separation, regions=regions,
        )

    return GateOutcome(
        FeasibilityReport(
            passed=True, measurements=measurements, on_surface=on_surface,
            validated_delegations=validated_delegations,
        ),
        separation=separation, regions=regions,
    )
