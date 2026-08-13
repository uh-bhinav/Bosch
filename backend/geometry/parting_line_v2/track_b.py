"""
backend/geometry/parting_line_v2/track_b.py
-------------------------------------------
Track B — silhouette curves in **face interiors** (plan §4).

The mathematics
---------------
On a smooth face the normal is continuous, so the silhouette is the **zero set
of an implicit function** in parameter space::

        Σ_f = { (u,v) ∈ D_f : g(u,v) = 0 },      g = n̂(u,v) · d̂

This is a genuinely different problem from Track A's. At a sharp edge ``n̂`` is
set-valued and the test is the straddle ``0 ∈ [g_a, g_b]``; here ``n̂`` varies
smoothly and the answer is a **curve through the middle of a face**, touching
no B-Rep edge at all. No edge-based method can find it — which is exactly why
v1 cannot see a sphere's silhouette, or a cylinder's when it is pulled across
its axis (audit RC-1/RC-2, measured at P0: 0.0% coverage on both).

Method — marching squares with Newton refinement (§4.2)
------------------------------------------------------
1. **Cheap pre-pass.** Sample ``g`` on a coarse grid. If it does not change
   sign, the face carries no interior silhouette and is skipped. On real parts
   this rejects the large majority of faces for a few dozen evaluations each.
2. **Sag-derived resolution.** For a curve of curvature ``κ`` sampled with
   chord ``h``, the chordal deviation is ``sag ≈ h²κ/8``, so ``h ≤ √(8·τ_sag/κ)``.
   ``κ`` comes from ``GeomLProp_SLProps``' principal curvatures. This is the
   same principle OCC's own ``BRepMesh`` deflection uses.
3. **Marching squares.** Per cell, locate crossings on the four cell edges and
   connect them. The two ambiguous saddle configurations are resolved by the
   sign of ``g`` at the **cell centre** — deterministically, never arbitrarily
   (plan §8.3).
4. **Newton refinement** of every crossing, in parameter space::

        t ← t − g(t) / (∇g · Δ)

   with ``∇g`` by central differences. Bisection fallback if Newton leaves the
   bracket, so a crossing is never lost to a divergent step.
5. **Trim to the face.** A face's UV domain is a rectangle but the face is
   bounded by its wires, so every point is classified with
   ``BRepTopAdaptor_FClass2d`` and anything not ``TopAbs_IN`` is dropped. This
   is what stops marching squares from escaping onto the untrimmed surface —
   the specific way the "levitating curve" would return.
6. **Lift.** ``p = S(u,v)`` from OCC. Never interpolated in 3-D.

Periodic surfaces need no special handling here: a curve that wraps the seam
(a sphere's great circle) arrives as two UV runs whose 3-D endpoints coincide,
and the graph's 3-D welding joins them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from backend.geometry.parting_line_v2.types import CurveSegment, FaceBacking
from backend.models.geometry_models import PartGeometry, Vec3, dot3

try:
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.BRepTools import breptools
    from OCC.Core.BRepTopAdaptor import BRepTopAdaptor_FClass2d
    from OCC.Core.GeomLProp import GeomLProp_SLProps
    from OCC.Core.gp import gp_Pnt2d
    from OCC.Core.TopAbs import TopAbs_IN, TopAbs_ON, TopAbs_REVERSED

    _OCC_AVAILABLE = True
except Exception:  # pragma: no cover
    _OCC_AVAILABLE = False


__all__ = ["TrackBResult", "detect_face_silhouettes"]


@dataclass(frozen=True)
class TrackBResult:
    """Interior silhouette segments, plus why every other face was skipped."""

    segments: tuple[CurveSegment, ...]
    skipped: dict[int, str]
    #: Faces where ``|g| ≤ ε`` over the WHOLE face — a zero-draft band, not a
    #: curve. Emitting marching-squares output here would be noise (plan §4.3).
    degenerate_face_ids: tuple[int, ...] = ()
    sampled_face_count: int = 0
    total_sample_count: int = 0
    grid_sizes: dict[int, tuple[int, int]] = None  # type: ignore[assignment]
    #: How many segment endpoints were produced by boundary-intersection
    #: refinement (D-023 / mechanism 1) rather than being the last raw grid
    #: point classified inside the trimmed face. Purely a diagnostic count —
    #: nothing downstream depends on it.
    boundary_refinement_count: int = 0
    #: How many face-backed segments were classified ``kind="tangential"``
    #: instead of the default ``"silhouette"`` (D-025 / mechanism 2
    #: classification) because they run along a specific B-Rep edge that
    #: Track A's own test already calls tangential. Geometry/provenance is
    #: unchanged either way — this only reports how many segments got the
    #: label, for corpus-level before/after comparison.
    tangential_segment_count: int = 0

    def to_dict(self) -> dict:
        skip_reasons: dict[str, int] = {}
        for reason in self.skipped.values():
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
        segment_kinds: dict[str, int] = {}
        for segment in self.segments:
            segment_kinds[segment.kind] = segment_kinds.get(segment.kind, 0) + 1
        return {
            "segment_count": len(self.segments),
            "segment_kinds": segment_kinds,
            "degenerate_face_count": len(self.degenerate_face_ids),
            "degenerate_face_ids": list(self.degenerate_face_ids),
            "sampled_face_count": self.sampled_face_count,
            "total_sample_count": self.total_sample_count,
            "skipped_face_count": len(self.skipped),
            "skip_reasons": skip_reasons,
            "boundary_refinement_count": self.boundary_refinement_count,
            "tangential_segment_count": self.tangential_segment_count,
        }


class _FaceField:
    """``g(u,v)`` on one face, with a small evaluation cache."""

    __slots__ = ("surface", "reversed", "direction", "_cache")

    def __init__(self, face: object, direction: Vec3) -> None:
        self.surface = BRep_Tool.Surface(face)
        self.reversed = face.Orientation() == TopAbs_REVERSED
        self.direction = direction
        self._cache: dict[tuple[float, float], float | None] = {}

    def g(self, u: float, v: float) -> float | None:
        key = (u, v)
        if key in self._cache:
            return self._cache[key]
        value: float | None
        try:
            props = GeomLProp_SLProps(self.surface, u, v, 1, 1e-9)
            if not props.IsNormalDefined():
                value = None
            else:
                normal = props.Normal()
                nx, ny, nz = normal.X(), normal.Y(), normal.Z()
                if self.reversed:
                    nx, ny, nz = -nx, -ny, -nz
                value = dot3((nx, ny, nz), self.direction)
        except Exception:
            value = None
        self._cache[key] = value
        return value

    def point(self, u: float, v: float) -> Vec3 | None:
        try:
            props = GeomLProp_SLProps(self.surface, u, v, 0, 1e-9)
            p = props.Value()
            return (float(p.X()), float(p.Y()), float(p.Z()))
        except Exception:
            return None


def _grid_resolution(
    face: object, u_span: float, v_span: float, cfg: object, tau_sag: float
) -> tuple[int, int]:
    """
    Sag-derived ``(N_u, N_v)``.

    ``h ≤ √(8·τ_sag/κ)`` with ``κ`` the largest principal curvature found in a
    coarse pre-sample. A flat direction gets the minimum count; a tightly
    curved one gets more, bounded by ``uv_grid_max`` so a pathological face
    cannot blow up the budget silently.
    """
    minimum, maximum = cfg.uv_grid_min, cfg.uv_grid_max
    try:
        surface = BRep_Tool.Surface(face)
        u_min, u_max, v_min, v_max = breptools.UVBounds(face)
    except Exception:
        return minimum, minimum

    kappa = 0.0
    length_u = length_v = 0.0
    samples = 0
    for i in (0.25, 0.5, 0.75):
        for j in (0.25, 0.5, 0.75):
            u = u_min + (u_max - u_min) * i
            v = v_min + (v_max - v_min) * j
            try:
                props = GeomLProp_SLProps(surface, u, v, 2, 1e-9)
                if props.IsCurvatureDefined():
                    kappa = max(kappa, abs(props.MaxCurvature()), abs(props.MinCurvature()))
                d1u, d1v = props.D1U(), props.D1V()
                length_u += math.sqrt(d1u.X() ** 2 + d1u.Y() ** 2 + d1u.Z() ** 2)
                length_v += math.sqrt(d1v.X() ** 2 + d1v.Y() ** 2 + d1v.Z() ** 2)
                samples += 1
            except Exception:
                continue

    if samples == 0:
        return minimum, minimum
    arc_u = (length_u / samples) * u_span
    arc_v = (length_v / samples) * v_span
    chord = math.sqrt(8.0 * tau_sag / kappa) if kappa > 1e-12 else float("inf")
    if not math.isfinite(chord) or chord <= 0.0:
        return minimum, minimum

    n_u = max(minimum, min(maximum, int(math.ceil(arc_u / chord)) + 1))
    n_v = max(minimum, min(maximum, int(math.ceil(arc_v / chord)) + 1))
    return n_u, n_v


def _refine(
    field: _FaceField,
    p0: tuple[float, float],
    p1: tuple[float, float],
    g0: float,
    g1: float,
    cfg: object,
) -> tuple[float, float]:
    """
    Locate ``g = 0`` on the segment ``p0 → p1``.

    Newton in the segment parameter, with ``∇g·Δ`` by central difference, and
    a bisection fallback whenever a step leaves ``[0,1]`` or the derivative
    collapses. Newton alone can diverge on a nearly-tangent crossing; losing a
    crossing would silently break the curve, so the fallback is not optional.
    """
    def at(t: float) -> tuple[float, float]:
        return (p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t)

    lo, hi = 0.0, 1.0
    g_lo, g_hi = g0, g1
    t = g0 / (g0 - g1) if (g0 - g1) != 0.0 else 0.5

    for _ in range(cfg.newton_max_iterations):
        u, v = at(t)
        g_t = field.g(u, v)
        if g_t is None:
            break
        if abs(g_t) <= cfg.newton_tolerance:
            return u, v

        step = 1e-6
        t_plus = min(1.0, t + step)
        t_minus = max(0.0, t - step)
        g_plus = field.g(*at(t_plus))
        g_minus = field.g(*at(t_minus))
        derivative = (
            (g_plus - g_minus) / (t_plus - t_minus)
            if (g_plus is not None and g_minus is not None and t_plus > t_minus)
            else None
        )

        # Keep the bracket up to date so bisection can take over cleanly.
        if (g_t > 0) == (g_lo > 0):
            lo, g_lo = t, g_t
        else:
            hi, g_hi = t, g_t

        if derivative is None or abs(derivative) < 1e-15:
            t = 0.5 * (lo + hi)
            continue
        candidate = t - g_t / derivative
        t = candidate if lo <= candidate <= hi else 0.5 * (lo + hi)

    # Newton is fast but not guaranteed. If it has not reached the tolerance
    # within its budget, finish with pure BISECTION, which always converges
    # because the bracket is maintained above.
    #
    # This is not defensive padding: measured on Part3's spline faces at its
    # optimal direction, Newton alone left crossings with |g| above
    # tau_silhouette, and gate H0.3 correctly rejected the resulting curve as
    # "not provably on g = 0". A crossing point that is not actually on the
    # zero set is not a silhouette point, so silently keeping it would put an
    # off-silhouette curve into the candidate set.
    for _ in range(48):
        u, v = at(t)
        g_t = field.g(u, v)
        if g_t is None or abs(g_t) <= cfg.newton_tolerance:
            break
        if (g_t > 0) == (g_lo > 0):
            lo, g_lo = t, g_t
        else:
            hi, g_hi = t, g_t
        if abs(hi - lo) <= 1e-15:
            break
        t = 0.5 * (lo + hi)

    return at(t)


def _refine_trim_boundary(
    classifier: object,
    uv_inside: tuple[float, float],
    uv_outside: tuple[float, float],
    *,
    iterations: int = 40,
) -> tuple[float, float]:
    """
    Mechanism 1 fix (D-023, 2026-08-12).

    Bisect toward the true trim boundary between a point already classified
    inside/on the trimmed face and its immediate chain neighbour classified
    outside, using the SAME ``BRepTopAdaptor_FClass2d`` classifier that made
    both classifications as the oracle — the trimmed region's own wires are
    the authoritative B-Rep topology here, never a distance heuristic.

    Root cause this closes: the untouched contour previously just stopped at
    ``uv_inside`` — up to a full grid cell short of the real boundary
    (measured directly: 0.046-0.14 mm undershoot on Part3's face 274, traced
    end-to-end to an H0.3 rejection on a real candidate). Bisecting against
    the classifier converges to the boundary to floating-point precision in
    a bounded number of iterations, independent of grid resolution — this is
    the same technique already validated as a read-only diagnostic in
    ``backend/validation/parting_line_track_b_termination_trace.py``, now
    applied for real.

    Returns the last point on the ``lo`` (confirmed inside/on) side, so the
    result is guaranteed to satisfy the trim-containment check that gate
    H0.3 re-verifies independently — never a point on the outside.
    """
    lo, hi = uv_inside, uv_outside
    for _ in range(iterations):
        mid = (0.5 * (lo[0] + hi[0]), 0.5 * (lo[1] + hi[1]))
        state = classifier.Perform(gp_Pnt2d(mid[0], mid[1]))
        if state in (TopAbs_IN, TopAbs_ON):
            lo = mid
        else:
            hi = mid
    return lo


def _cell_segments(
    field: _FaceField,
    u0: float, u1: float, v0: float, v1: float,
    g00: float, g10: float, g11: float, g01: float,
    cfg: object,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """
    Marching-squares contour pieces for one cell.

    Crossings are located on whichever of the four cell edges change sign; two
    crossings give one piece, four give a **saddle**, resolved by the sign of
    ``g`` at the cell centre. Resolving a saddle arbitrarily would make the
    result depend on iteration order, breaking determinism (plan §8.3).
    """
    corners = {
        "B": ((u0, v0), (u1, v0), g00, g10),
        "R": ((u1, v0), (u1, v1), g10, g11),
        "T": ((u1, v1), (u0, v1), g11, g01),
        "L": ((u0, v1), (u0, v0), g01, g00),
    }
    crossings: dict[str, tuple[float, float]] = {}
    for name, (pa, pb, ga, gb) in corners.items():
        if (ga > 0) != (gb > 0):
            crossings[name] = _refine(field, pa, pb, ga, gb, cfg)

    if len(crossings) == 2:
        (_, a), (_, b) = sorted(crossings.items())
        return [(a, b)]

    if len(crossings) == 4:
        centre = field.g(0.5 * (u0 + u1), 0.5 * (v0 + v1))
        if centre is None:
            return []
        if (centre > 0) == (g00 > 0):
            return [(crossings["L"], crossings["B"]), (crossings["R"], crossings["T"])]
        return [(crossings["L"], crossings["T"]), (crossings["B"], crossings["R"])]

    return []


def _chain(
    pieces: list[tuple[tuple[float, float], tuple[float, float]]], tolerance: float
) -> list[list[tuple[float, float]]]:
    """Join cell pieces into maximal polylines by endpoint proximity in UV."""
    def key(p: tuple[float, float]) -> tuple[int, int]:
        return (round(p[0] / tolerance), round(p[1] / tolerance))

    adjacency: dict[tuple[int, int], list[int]] = {}
    for index, (a, b) in enumerate(pieces):
        adjacency.setdefault(key(a), []).append(index)
        adjacency.setdefault(key(b), []).append(index)

    used: set[int] = set()
    chains: list[list[tuple[float, float]]] = []

    for start in range(len(pieces)):
        if start in used:
            continue
        used.add(start)
        chain = [pieces[start][0], pieces[start][1]]

        for _ in range(2):                       # extend both ends
            while True:
                tail = chain[-1]
                nxt = None
                for index in adjacency.get(key(tail), []):
                    if index in used:
                        continue
                    a, b = pieces[index]
                    if key(a) == key(tail):
                        nxt, point = index, b
                        break
                    if key(b) == key(tail):
                        nxt, point = index, a
                        break
                if nxt is None:
                    break
                used.add(nxt)
                chain.append(point)
            chain.reverse()
        chains.append(chain)
    return chains


def detect_face_silhouettes(
    part: PartGeometry,
    pull_direction: Vec3,
    *,
    cfg: object,
    bbox_diagonal_mm: float,
    start_segment_id: int = 0,
) -> TrackBResult:
    """Find every face-interior silhouette curve for ``pull_direction``."""
    if not _OCC_AVAILABLE:
        return TrackBResult((), {}, (), 0, 0, {})

    epsilon = cfg.silhouette_epsilon
    tau_sag = max(cfg.sag_tolerance_rel * bbox_diagonal_mm, 1e-9)

    segments: list[CurveSegment] = []
    skipped: dict[int, str] = {}
    degenerate: list[int] = []
    grid_sizes: dict[int, tuple[int, int]] = {}
    sampled_faces = 0
    total_samples = 0
    segment_id = start_segment_id
    boundary_refinements = 0
    tangential_segments = 0

    for face_data in sorted(part.faces, key=lambda f: f.face_id):
        face = face_data.occ_face
        try:
            u_min, u_max, v_min, v_max = breptools.UVBounds(face)
        except Exception:
            skipped[face_data.face_id] = "UV bounds unavailable"
            continue
        if not all(math.isfinite(x) for x in (u_min, u_max, v_min, v_max)):
            skipped[face_data.face_id] = "non-finite UV bounds"
            continue
        if u_max - u_min <= 0.0 or v_max - v_min <= 0.0:
            skipped[face_data.face_id] = "degenerate UV domain"
            continue

        field = _FaceField(face, pull_direction)

        # --- cheap pre-pass: does g change sign at all? --------------------
        coarse = 5
        values: list[float] = []
        for i in range(coarse):
            for j in range(coarse):
                u = u_min + (u_max - u_min) * (i + 0.5) / coarse
                v = v_min + (v_max - v_min) * (j + 0.5) / coarse
                value = field.g(u, v)
                if value is not None:
                    values.append(value)
        total_samples += len(values)
        if not values:
            skipped[face_data.face_id] = "normal undefined across the face"
            continue
        if max(abs(x) for x in values) <= epsilon:
            degenerate.append(face_data.face_id)
            skipped[face_data.face_id] = (
                "zero-draft band: |g| <= eps over the whole face, so there is no "
                "curve to extract — the parting line's position here is a free "
                "parameter (plan 4.3/5.3)"
            )
            continue
        if min(values) > 0.0 or max(values) < 0.0:
            skipped[face_data.face_id] = "g does not change sign inside this face"
            continue

        # --- full grid ------------------------------------------------------
        n_u, n_v = _grid_resolution(face, u_max - u_min, v_max - v_min, cfg, tau_sag)
        grid_sizes[face_data.face_id] = (n_u, n_v)
        us = [u_min + (u_max - u_min) * i / (n_u - 1) for i in range(n_u)]
        vs = [v_min + (v_max - v_min) * j / (n_v - 1) for j in range(n_v)]
        grid: list[list[float | None]] = [[field.g(u, v) for v in vs] for u in us]
        total_samples += n_u * n_v
        sampled_faces += 1

        pieces: list[tuple[tuple[float, float], tuple[float, float]]] = []
        for i in range(n_u - 1):
            for j in range(n_v - 1):
                g00, g10 = grid[i][j], grid[i + 1][j]
                g11, g01 = grid[i + 1][j + 1], grid[i][j + 1]
                if None in (g00, g10, g11, g01):
                    continue
                pieces.extend(_cell_segments(
                    field, us[i], us[i + 1], vs[j], vs[j + 1],
                    g00, g10, g11, g01, cfg,  # type: ignore[arg-type]
                ))

        if not pieces:
            skipped[face_data.face_id] = "sign change found but no contour cell produced a crossing"
            continue

        chain_tolerance = min(
            (u_max - u_min) / max(n_u - 1, 1), (v_max - v_min) / max(n_v - 1, 1)
        ) * 1e-3
        classifier = BRepTopAdaptor_FClass2d(face, 1e-7)
        tau_silhouette = cfg.silhouette_epsilon * cfg.silhouette_error_factor

        for chain in _chain(pieces, max(chain_tolerance, 1e-12)):
            uv_kept: list[tuple[float, float]] = []
            points: list[Vec3] = []
            # Raw chain-point classifier state (IN/ON vs OUT only, never the
            # g-value/seam check below) for the PREVIOUS point, so a genuine
            # trim-boundary crossing can be detected and refined -- see
            # mechanism 1 (D-023) below. `None` means "no previous point yet".
            prev_uv: tuple[float, float] | None = None
            prev_trim_in: bool | None = None

            def _try_append_refined_boundary(uv_inside, uv_outside) -> None:
                """
                Mechanism 1 (D-023, 2026-08-12): a genuine trim-boundary
                crossing was just found between ``uv_inside`` (classified
                IN/ON) and ``uv_outside`` (classified OUT). Previously the
                contour simply stopped at ``uv_inside`` — up to a full grid
                cell short of the real boundary. Refine toward it instead,
                using the trim classifier itself as the oracle (never a
                distance heuristic), and only accept the refined point if it
                still satisfies the SAME g=0 tolerance every other kept point
                must satisfy (tau_silhouette) — H0 stays the honest arbiter;
                a refined point that fails that check is simply not added,
                falling back to the original behaviour for that crossing.
                """
                nonlocal segment_id, boundary_refinements
                boundary_uv = _refine_trim_boundary(classifier, uv_inside, uv_outside)
                g_boundary = field.g(*boundary_uv)
                if g_boundary is None or abs(g_boundary) > tau_silhouette:
                    return
                boundary_point = field.point(*boundary_uv)
                if boundary_point is None:
                    return
                uv_kept.append(boundary_uv)
                points.append(boundary_point)
                boundary_refinements += 1

            def _emit_classified(local_segment_id: int, local_points, local_uv) -> None:
                """
                D-025 (mechanism 2 classification, 2026-08-12): a finished
                segment is emitted as ``kind="tangential"`` instead of the
                default ``"silhouette"`` if it runs along a specific B-Rep
                edge that Track A's OWN test already calls tangential — see
                ``_boundary_tangential_edge``. Geometry, points, and
                provenance (still ``FaceBacking``) are unchanged either way;
                only the label changes. Never merges, drops, or moves the
                segment; H3/H4/enumeration/ranking are untouched by this
                label — they consume whatever the graph already contains.
                """
                nonlocal tangential_segments
                is_tangential = _boundary_tangential_edge(
                    part, face_data.face_id, local_points, pull_direction,
                    cfg=cfg, bbox_diagonal_mm=bbox_diagonal_mm,
                )
                if is_tangential:
                    tangential_segments += 1
                _emit(
                    segments, local_segment_id, local_points, local_uv, face_data.face_id, field,
                    kind="tangential" if is_tangential else "silhouette",
                )

            for u, v in chain:
                # Trim to the face's real (wire-bounded) region. Without this,
                # marching squares happily returns points on the untrimmed
                # surface — the exact way an off-part curve would reappear.
                state = classifier.Perform(gp_Pnt2d(u, v))
                trim_in = state in (TopAbs_IN, TopAbs_ON)

                if trim_in and prev_uv is not None and prev_trim_in is False:
                    # ENTERING the trimmed region: refine the true entry
                    # point and prepend it before continuing this run.
                    _try_append_refined_boundary((u, v), prev_uv)

                keep = True
                if not trim_in:
                    keep = False
                else:
                    # A point that is not actually ON the zero set is not a
                    # silhouette point. `g` can be DISCONTINUOUS at a
                    # parametrisation seam or a degenerate boundary, where it
                    # flips sign without ever passing through zero — marching
                    # squares sees a sign change and no refinement can resolve
                    # it. Measured on Part3 face 407 at its optimal direction:
                    # a whole run at u = 1.0 with g alternating -0.825/+0.825.
                    # Keeping such points injects a false curve, which gate
                    # H0.3 then correctly rejects; dropping them here is the
                    # honest fix, and it keeps Track B's output consistent with
                    # its own definition. This is a DIFFERENT failure mode from
                    # the trim-boundary crossing above (mechanism 2, D-023 —
                    # not addressed by this refinement, deliberately) and is
                    # left untouched.
                    g_value = field.g(u, v)
                    if g_value is None or abs(g_value) > tau_silhouette:
                        keep = False

                if not keep:
                    if not trim_in and prev_uv is not None and prev_trim_in is True:
                        # EXITING the trimmed region via a genuine trim
                        # crossing (not a g-value/seam rejection): refine the
                        # true exit point and append it before closing out
                        # this run. This is the case the H0 case study traced
                        # directly to a real H0.3 rejection (Part3 face 274).
                        _try_append_refined_boundary(prev_uv, (u, v))
                    if len(uv_kept) >= 2:
                        _emit_classified(segment_id, points, uv_kept)
                        segment_id += 1
                    uv_kept, points = [], []
                    prev_uv, prev_trim_in = (u, v), trim_in
                    continue

                point = field.point(u, v)
                if point is None:
                    prev_uv, prev_trim_in = (u, v), trim_in
                    continue
                uv_kept.append((u, v))
                points.append(point)
                prev_uv, prev_trim_in = (u, v), trim_in
            if len(uv_kept) >= 2:
                _emit_classified(segment_id, points, uv_kept)
                segment_id += 1

    return TrackBResult(
        segments=tuple(segments),
        skipped=skipped,
        degenerate_face_ids=tuple(degenerate),
        sampled_face_count=sampled_faces,
        total_sample_count=total_samples,
        grid_sizes=grid_sizes,
        boundary_refinement_count=boundary_refinements,
        tangential_segment_count=tangential_segments,
    )


def _emit(
    segments: list[CurveSegment],
    segment_id: int,
    points: list[Vec3],
    uv: list[tuple[float, float]],
    face_id: int,
    field: _FaceField,
    kind: str = "silhouette",
) -> None:
    """Build one face-backed segment, carrying its ``g`` values for H0.3."""
    g_values = tuple(field.g(u, v) or 0.0 for u, v in uv)
    segments.append(CurveSegment(
        segment_id=segment_id,
        points=tuple(points),
        backing=FaceBacking(face_id, tuple(uv)),
        kind=kind,  # type: ignore[arg-type]
        g_values=g_values,
    ))


def _boundary_tangential_edge(
    part: PartGeometry,
    face_id: int,
    points: list[Vec3],
    direction: Vec3,
    *,
    cfg: object,
    bbox_diagonal_mm: float,
) -> bool:
    """
    D-025 (mechanism 2 classification, 2026-08-12) — is this finished
    Track-B contour running along a specific B-Rep edge that TRACK A's OWN
    test already classifies tangential?

    Deliberately reuses Track A's exact semantics
    (``track_a._g_on_both_faces`` + ``track_a._classify``'s
    ``max(|g_a|, |g_b|) <= silhouette_epsilon`` test) rather than inventing
    a new Track-B-native rule. Two Track-B-native candidate signals were
    tried and MEASURED not to discriminate cleanly on the motivating case
    (Part3 face 317, +X): the marching-squares cell's max corner-``g``
    magnitude, and the fraction of chain points the trim classifier reports
    as ``TopAbs_ON`` rather than ``TopAbs_IN``. Both misfire on genuinely
    transversal chains on that same face (they also run mostly ``ON`` the
    trim boundary and/or have small-magnitude corners near it, for reasons
    unrelated to tangency). Reusing Track A's own edge-level test avoids
    guessing at a new geometric rule the plan does not specify.

    Samples only the segment's first/middle/last points against every edge
    genuinely bounding this face (``part.face_to_edges``, never an
    unrelated edge) — never a distance-tolerance merge, never forcing two
    tracks' points together. The projection tolerance reuses
    ``stitch_snap_tolerance_rel`` (mechanism 1's already-existing,
    already-measured tolerance for "is this point on this specific
    B-Rep edge") rather than inventing a new one. Requires ALL sampled
    points to agree on the SAME single edge and that edge to be tangential
    at its start, middle, and end parameter -- a segment that only grazes a
    tangential edge at one point, or that sits near more than one edge, is
    NOT reclassified.
    """
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
    from OCC.Core.GeomAPI import GeomAPI_ProjectPointOnCurve
    from OCC.Core.gp import gp_Pnt
    from OCC.Core.TopoDS import TopoDS_Edge

    from backend.geometry.parting_line_v2.track_a import _classify, _g_on_both_faces

    if len(points) < 2:
        return False
    tolerance_mm = max(cfg.stitch_snap_tolerance_rel * bbox_diagonal_mm, 1e-6)
    sample = [points[0], points[len(points) // 2], points[-1]]

    edges_by_id = {e.edge_id: e for e in part.edges}
    faces_by_id = {f.face_id: f for f in part.faces}
    candidate_edge_ids = part.face_to_edges.get(face_id, ())

    matched_edge_ids: set[int] = set()
    for point in sample:
        best = None
        for edge_id in candidate_edge_ids:
            edge = edges_by_id.get(edge_id)
            if edge is None or not isinstance(edge.occ_edge, TopoDS_Edge):
                continue
            try:
                curve, first, last = BRep_Tool.Curve(edge.occ_edge)
                if curve is None:
                    continue
                projector = GeomAPI_ProjectPointOnCurve(gp_Pnt(*point), curve, first, last)
                if projector.NbPoints() == 0:
                    continue
                distance = float(projector.LowerDistance())
            except Exception:
                continue
            if distance <= tolerance_mm and (best is None or distance < best[0]):
                best = (distance, edge_id)
        if best is None:
            return False
        matched_edge_ids.add(best[1])

    if len(matched_edge_ids) != 1:
        return False
    edge = edges_by_id[matched_edge_ids.pop()]
    adjacent = edge.adjacent_face_ids
    if len(adjacent) != 2:
        return False
    face_a_occ = faces_by_id[adjacent[0]].occ_face
    face_b_occ = faces_by_id[adjacent[1]].occ_face

    try:
        adaptor = BRepAdaptor_Curve(edge.occ_edge)
        t_first, t_last = adaptor.FirstParameter(), adaptor.LastParameter()
    except Exception:
        return False
    if not (math.isfinite(t_first) and math.isfinite(t_last)) or t_last <= t_first:
        return False

    epsilon = cfg.silhouette_epsilon  # Track A's own tangential threshold
    for t in (t_first, 0.5 * (t_first + t_last), t_last):
        pair = _g_on_both_faces(edge.occ_edge, face_a_occ, face_b_occ, t, direction)
        if pair is None or _classify(pair, epsilon) != "tangential":
            return False
    return True
