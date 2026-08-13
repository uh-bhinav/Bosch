"""
backend/geometry/parting_line_v2/track_a.py
-------------------------------------------
Track A — silhouette detection at **sharp edges** (plan §3).

The mathematics
---------------
The part boundary ``∂S`` is *piecewise* smooth, so the visibility function

        g(p) = n̂(p) · d̂

has two qualitatively different kinds of zero, needing two different
algorithms:

* **Face interior** — ``n̂`` is continuous, so ``g(u,v) = 0`` is an implicit
  curve. That is Track B (plan §4), which lands in P2.
* **Sharp edge** — ``n̂`` is *set-valued*: it jumps from ``n̂_a`` to ``n̂_b``
  across the edge. The silhouette condition is therefore

        0 ∈ [g_a, g_b]        i.e.   g_a · g_b < 0    (a strict straddle)

  which is what this module tests. **This is exact for sharp edges** — it is
  not an approximation of the face-interior case, it is the correct condition
  for the other half of the silhouette.

The two tracks are complementary, not redundant. Together they cover ``Σ``.

What is different from v1
-------------------------
v1's ``_classify_edge`` (``parting_line.py:627``) evaluates ``g`` from
``FaceData.normal`` — the normal at each face's **UV centroid**, a single
sample for the whole face. For a planar face that is exact; for anything
curved it is a lossy summary evaluated potentially far from the edge in
question.

This module evaluates both normals **at the edge**, via each face's pcurve,
reusing ``step_loader._face_normal_at_uv``. That primitive already exists and
is already used by ``_compute_edge_convexity`` — it was simply never used by
the parting-line code (audit RC-1).

It also samples along the edge rather than at one parameter, so an edge that
is a silhouette over only part of its length yields a **sub-segment**, with
the crossing parameter refined by bisection.

Output
------
``CurveSegment`` objects whose points come from ``BRepAdaptor_Curve.Value(t)``
— real OCC geometry, satisfying gate H0 by construction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from backend.geometry.parting_line_v2.types import CurveSegment, EdgeBacking, SegmentKind
from backend.models.geometry_models import EdgeData, PartGeometry, Vec3, dot3

try:
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
    from OCC.Core.GeomAbs import GeomAbs_Circle, GeomAbs_Line
    from OCC.Core.gp import gp_Pnt
    from OCC.Core.TopoDS import TopoDS_Edge

    from backend.geometry.step_loader import _face_normal_at_uv

    _OCC_AVAILABLE = True
except Exception:  # pragma: no cover - environment without pythonOCC
    _OCC_AVAILABLE = False


__all__ = ["TrackAResult", "detect_edge_silhouettes"]


@dataclass(frozen=True)
class TrackAResult:
    """Segments found by Track A, plus why every other edge was skipped."""

    segments: tuple[CurveSegment, ...]
    #: edge_id -> reason, for every edge that produced no segment. Kept so a
    #: "found nothing" result can be explained rather than merely reported —
    #: on a cylinder or sphere this map IS the finding.
    skipped: dict[int, str]
    sampled_edge_count: int
    total_sample_count: int

    @property
    def silhouette_segments(self) -> tuple[CurveSegment, ...]:
        return tuple(s for s in self.segments if s.kind == "silhouette")

    @property
    def tangential_segments(self) -> tuple[CurveSegment, ...]:
        return tuple(s for s in self.segments if s.kind == "tangential")

    def to_dict(self) -> dict:
        kinds: dict[str, int] = {}
        for segment in self.segments:
            kinds[segment.kind] = kinds.get(segment.kind, 0) + 1
        skip_reasons: dict[str, int] = {}
        for reason in self.skipped.values():
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
        return {
            "segment_count": len(self.segments),
            "segment_kinds": kinds,
            "sampled_edge_count": self.sampled_edge_count,
            "total_sample_count": self.total_sample_count,
            "skipped_edge_count": len(self.skipped),
            "skip_reasons": skip_reasons,
        }


def _sample_count(adaptor: object, length_mm: float, cfg: object, bbox_diagonal_mm: float) -> int:
    """
    How many parameters to evaluate along one edge.

    A straight line needs only its endpoints — ``g`` on each side varies only
    through the adjacent surfaces, and for a line bounding planar faces it is
    constant. Curved edges get a sag-derived count:

            sag ≈ h²·κ / 8   ⟹   h ≤ √(8·τ_sag/κ)

    For a circle, ``κ = 1/r`` so ``h ≤ √(8·r·τ_sag)``. For anything else the
    curve type is not analytic here, so we fall back to a length-proportional
    count — deliberately conservative, and honest: a *general* curvature-driven
    rule needs the second derivatives Track B already computes, so it arrives
    with Track B in P2 rather than being half-built here.
    """
    minimum, maximum = cfg.edge_samples_min, cfg.edge_samples_max
    tau_sag = max(cfg.sag_tolerance_rel * bbox_diagonal_mm, 1e-9)

    curve_type = None
    try:
        curve_type = adaptor.GetType()  # type: ignore[union-attr]
    except Exception:
        pass

    if curve_type == GeomAbs_Line:
        return minimum

    if curve_type == GeomAbs_Circle:
        try:
            radius = float(adaptor.Circle().Radius())  # type: ignore[union-attr]
            chord = math.sqrt(max(8.0 * radius * tau_sag, 1e-12))
            return max(minimum, min(maximum, int(math.ceil(length_mm / max(chord, 1e-9))) + 1))
        except Exception:
            pass

    chord = max(tau_sag * 50.0, bbox_diagonal_mm * 1e-2)
    return max(minimum, min(maximum, int(math.ceil(length_mm / max(chord, 1e-9))) + 1))


def _g_on_both_faces(
    edge_shape: object,
    face_a: object,
    face_b: object,
    t: float,
    pull_direction: Vec3,
) -> tuple[float, float] | None:
    """
    ``(g_a, g_b)`` at 3-D curve parameter ``t``.

    The edge's pcurve on each face shares the edge's own 3-D curve parameter
    (see ``step_loader._compute_edge_convexity``), so one ``t`` evaluates both
    sides consistently — which is the whole point: ``g_a`` and ``g_b`` must be
    compared *at the same physical location*, not at two face centroids.
    """
    values: list[float] = []
    for face in (face_a, face_b):
        try:
            pcurve, first, last = BRep_Tool.CurveOnSurface(edge_shape, face)
        except Exception:
            return None
        if pcurve is None:
            return None
        clamped = min(max(t, first), last)
        try:
            uv = pcurve.Value(clamped)
            normal = _face_normal_at_uv(face, uv.X(), uv.Y())
        except Exception:
            return None
        if normal is None:
            return None
        values.append(dot3(normal, pull_direction))
    return values[0], values[1]


def _bisect_crossing(
    edge_shape: object,
    face_a: object,
    face_b: object,
    t_lo: float,
    t_hi: float,
    pull_direction: Vec3,
    max_iterations: int,
    tolerance: float,
) -> float:
    """
    Refine the parameter where ``h(t) = g_a(t)·g_b(t)`` changes sign.

    Bisection rather than Newton: ``h`` is a product of two quantities whose
    derivatives require the surfaces' second fundamental forms, and bisection
    cannot diverge. The bracket is guaranteed by the caller (the samples
    straddle), so bisection always converges — which matters more here than
    speed, since this runs at most once per edge sign change.
    """
    lo, hi = t_lo, t_hi
    h_lo = _g_on_both_faces(edge_shape, face_a, face_b, lo, pull_direction)
    if h_lo is None:
        return 0.5 * (t_lo + t_hi)
    sign_lo = math.copysign(1.0, h_lo[0] * h_lo[1])

    for _ in range(max_iterations):
        if abs(hi - lo) <= tolerance:
            break
        mid = 0.5 * (lo + hi)
        h_mid = _g_on_both_faces(edge_shape, face_a, face_b, mid, pull_direction)
        if h_mid is None:
            break
        if math.copysign(1.0, h_mid[0] * h_mid[1]) == sign_lo:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def detect_edge_silhouettes(
    part: PartGeometry,
    pull_direction: Vec3,
    *,
    cfg: object,
    bbox_diagonal_mm: float,
    start_segment_id: int = 0,
) -> TrackAResult:
    """
    Find every sharp-edge silhouette segment for ``pull_direction``.

    Classification per sampled parameter:

    ==========================  =====================================
    ``g_a·g_b < 0``             silhouette (a strict straddle)
    ``max(|g_a|,|g_b|) ≤ ε``    tangential — a zero-draft edge
    otherwise                   not on the silhouette
    ==========================  =====================================

    ``tangential`` is kept **separate** from ``silhouette``. v1 conflates the
    two into ``near_parting``, but they are different situations: a straddle is
    a genuine sign change, while a tangential edge sits inside a zero-draft
    band whose parting-line position is a free parameter (plan §5.3).

    Maximal runs of consecutive samples sharing a classification become one
    segment, with run boundaries refined by bisection.
    """
    if not _OCC_AVAILABLE:
        return TrackAResult((), {}, 0, 0)

    epsilon = cfg.silhouette_epsilon
    faces_by_id = {face.face_id: face for face in part.faces}

    segments: list[CurveSegment] = []
    skipped: dict[int, str] = {}
    segment_id = start_segment_id
    sampled_edges = 0
    total_samples = 0

    for edge in sorted(part.edges, key=lambda e: e.edge_id):
        reason = _skip_reason(edge, faces_by_id)
        if reason is not None:
            skipped[edge.edge_id] = reason
            continue

        face_a = faces_by_id[edge.adjacent_face_ids[0]].occ_face
        face_b = faces_by_id[edge.adjacent_face_ids[1]].occ_face
        edge_shape = edge.occ_edge
        if not isinstance(edge_shape, TopoDS_Edge):
            skipped[edge.edge_id] = "edge has no usable TopoDS_Edge handle"
            continue

        try:
            adaptor = BRepAdaptor_Curve(edge_shape)
            t_first, t_last = adaptor.FirstParameter(), adaptor.LastParameter()
        except Exception as exc:  # noqa: BLE001
            skipped[edge.edge_id] = f"curve adaptor failed: {type(exc).__name__}"
            continue
        if not (math.isfinite(t_first) and math.isfinite(t_last)) or t_last <= t_first:
            skipped[edge.edge_id] = "degenerate parameter range"
            continue

        count = _sample_count(adaptor, edge.length, cfg, bbox_diagonal_mm)
        params = [
            t_first + (t_last - t_first) * i / (count - 1) for i in range(count)
        ]
        classes: list[str | None] = []
        g_pairs: list[tuple[float, float] | None] = []
        for t in params:
            pair = _g_on_both_faces(edge_shape, face_a, face_b, t, pull_direction)
            g_pairs.append(pair)
            classes.append(_classify(pair, epsilon))
        sampled_edges += 1
        total_samples += count

        if all(c is None for c in classes):
            skipped[edge.edge_id] = (
                "adjacent face normals do not straddle the pull direction"
                if all(p is not None for p in g_pairs)
                else "normal evaluation failed at every sample"
            )
            continue

        for kind, i_lo, i_hi in _runs(classes):
            t_lo, t_hi = _run_bounds(params, classes, i_lo, i_hi)
            # Where a run borders a NON-candidate sample the transition is a
            # real geometric crossing, so refine it rather than accepting an
            # arbitrary sample position.
            if kind == "silhouette":
                if i_lo > 0 and classes[i_lo - 1] is None:
                    t_lo = _bisect_crossing(
                        edge_shape, face_a, face_b, params[i_lo - 1], params[i_lo],
                        pull_direction, cfg.newton_max_iterations, cfg.newton_tolerance,
                    )
                if i_hi < len(params) - 1 and classes[i_hi + 1] is None:
                    t_hi = _bisect_crossing(
                        edge_shape, face_a, face_b, params[i_hi], params[i_hi + 1],
                        pull_direction, cfg.newton_max_iterations, cfg.newton_tolerance,
                    )
            if abs(t_hi - t_lo) <= 0.0:
                continue

            points = _curve_points(adaptor, t_lo, t_hi, max(2, i_hi - i_lo + 1))
            if points is None or len(points) < 2:
                continue
            segments.append(CurveSegment(
                segment_id=segment_id,
                points=points,
                backing=EdgeBacking(edge.edge_id, t_lo, t_hi),
                kind=kind,  # type: ignore[arg-type]
                # g_values is deliberately EMPTY for edge-backed segments:
                # at a sharp edge the normal is set-valued, so there is no
                # single g. The evidence is the straddle (g_a·g_b < 0),
                # re-checkable from the backing. Face-backed segments (P2)
                # DO carry g, and gate H0.3 checks |g| for those only.
                g_values=(),
            ))
            segment_id += 1

    return TrackAResult(tuple(segments), skipped, sampled_edges, total_samples)


def _skip_reason(edge: EdgeData, faces_by_id: dict[int, object]) -> str | None:
    """Why this edge cannot carry a sharp-edge silhouette test."""
    if edge.is_seam:
        return "seam edge (parameterisation artefact, not a physical boundary)"
    if len(edge.adjacent_face_ids) == 1:
        return "boundary edge (one adjacent face; no second normal to straddle)"
    if len(edge.adjacent_face_ids) != 2:
        return f"non-manifold edge ({len(edge.adjacent_face_ids)} adjacent faces)"
    for face_id in edge.adjacent_face_ids:
        if face_id not in faces_by_id:
            return f"adjacent face {face_id} missing from part"
    return None


def _classify(pair: tuple[float, float] | None, epsilon: float) -> str | None:
    """
    Classify one sampled parameter from the two one-sided values ``g_a, g_b``.

    The condition is **inclusive interval containment**, not a strict product
    test::

            silhouette  ⟺  0 ∈ [min(g_a, g_b), max(g_a, g_b)]     (± ε)

    Why inclusive matters — a real case that the strict form gets wrong.
    Across a sharp edge the normal sweeps the geodesic arc from ``n̂_a`` to
    ``n̂_b``, so by continuity ``g`` attains **every** value between ``g_a``
    and ``g_b``. If either endpoint is zero, the arc still touches ``g = 0``
    and the edge *is* on the silhouette.

    Measured on fixture F1: a cube pulled ``+Z`` has ``g = 1`` on the top face
    and ``g = 0`` on each side face. The strict test ``g_a·g_b < 0`` gives
    ``1 × 0 = 0``, not negative — so it finds **no silhouette at all** on the
    cube's top rim, which is manifestly the outline you see looking down the
    pull axis. The inclusive test finds it. (First implementation here used
    the strict form and returned 4 tangential segments and nothing else.)

    ``tangential`` is tested first and wins: when BOTH sides are within ``ε``
    of zero the edge sits inside a zero-draft band, where the parting line's
    position is a free parameter (plan §5.3) rather than a determined
    crossing. Conflating the two is what v1's single ``near_parting`` kind
    does.
    """
    if pair is None:
        return None
    g_a, g_b = pair
    if max(abs(g_a), abs(g_b)) <= epsilon:
        return "tangential"
    if min(g_a, g_b) <= epsilon and max(g_a, g_b) >= -epsilon:
        return "silhouette"
    return None


def _runs(classes: list[str | None]) -> list[tuple[SegmentKind, int, int]]:
    """
    Maximal runs of consecutive samples sharing a classification.

    **Single-sample runs are kept.** An earlier version dropped them as
    "numerical touches", and that silently broke connectivity: on F3's cap-rim
    circle the classification goes silhouette → tangential → silhouette, where
    the one-sample tangential run sits exactly at θ ≈ 0 and π — precisely
    where the face-interior rulings meet the rim. Dropping it left each arc
    ending ~1.4 mm short of the junction, so nothing welded, 2-core deleted
    everything, and the engine reported no candidate for a part whose answer
    is obvious. A run of one sample is still a real classification of a real
    piece of the edge; it is given a real parameter span by `_run_bounds`.
    """
    runs: list[tuple[SegmentKind, int, int]] = []
    start = 0
    for index in range(1, len(classes) + 1):
        if index == len(classes) or classes[index] != classes[start]:
            if classes[start] is not None:
                runs.append((classes[start], start, index - 1))  # type: ignore[arg-type]
            start = index
    return runs


def _run_bounds(
    params: list[float],
    classes: list[str | None],
    i_lo: int,
    i_hi: int,
) -> tuple[float, float]:
    """
    Parameter span for a run, chosen so **adjacent runs abut exactly**.

    Where a run borders another *candidate* run, both take the midpoint
    between the two straddling samples, so they share a boundary parameter and
    their endpoints weld into one graph node. Where it borders a non-candidate
    sample the boundary is refined separately by the caller (bisection on the
    actual crossing), because there the transition is a real geometric event
    rather than a sampling artefact.
    """
    lo = params[i_lo]
    hi = params[i_hi]
    if i_lo > 0 and classes[i_lo - 1] is not None:
        lo = 0.5 * (params[i_lo - 1] + params[i_lo])
    if i_hi < len(params) - 1 and classes[i_hi + 1] is not None:
        hi = 0.5 * (params[i_hi] + params[i_hi + 1])
    return lo, hi


def _curve_points(adaptor: object, t_lo: float, t_hi: float, count: int) -> tuple[Vec3, ...] | None:
    """
    Evaluate the real 3-D curve at ``count`` parameters in ``[t_lo, t_hi]``.

    Points come from OCC, never from interpolation between endpoints — that is
    gate H0.2's whole premise, and the reason the resulting curve provably
    lies on the part.
    """
    try:
        points: list[Vec3] = []
        for i in range(count):
            t = t_lo + (t_hi - t_lo) * i / (count - 1)
            pnt: gp_Pnt = adaptor.Value(t)  # type: ignore[union-attr]
            points.append((float(pnt.X()), float(pnt.Y()), float(pnt.Z())))
        return tuple(points)
    except Exception:
        return None
