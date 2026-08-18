"""
backend/geometry/parting_line_v2/measures.py
--------------------------------------------
Pure geometric measures used by the gates (plan §7) and the ranking (§8).

**No OCC in this module.** Everything here is plain arithmetic on point lists,
so every formula is unit-testable without constructing B-Rep geometry — the
same factoring that made ``core_cavity._validate_split_volumes`` testable, and
the reason the audit singles that function out as correctly done.
"""

from __future__ import annotations

import math

from backend.models.geometry_models import Vec3, cross3, dot3, normalize3

__all__ = [
    "projection_basis", "project_points", "shoelace_area", "bbox_area_2d",
    "polyline_length_3d", "pull_axis_span", "total_turning", "excess_turning",
    "self_intersection", "self_intersection_multi", "cauchy_projected_area",
    "distinct_point_count", "largest_loop_projected_area",
]


def largest_loop_projected_area(
    loops: tuple[tuple[Vec3, ...], ...], pull_direction: Vec3
) -> float:
    """
    ``max_k |A_proj(Γ_k)|`` — the T1 coverage numerator for a multi-loop ``Γ``.

    Deliberately the **maximum**, not the sum and not the signed total. T1 asks
    "does this candidate wrap the part's outer silhouette", and it is the outer
    loop that answers that. Summing would reward a candidate for including an
    extra hole rim; subtracting (treating holes as negative area) would
    *penalise* the correct answer for a holed part, since the hole rim is a
    required component of a valid ``Γ``, not a defect.
    """
    if not loops:
        return 0.0
    u_axis, v_axis = projection_basis(pull_direction)
    return max(
        abs(shoelace_area(project_points(loop, u_axis, v_axis))) for loop in loops
    )


def projection_basis(pull_direction: Vec3) -> tuple[Vec3, Vec3]:
    """
    A deterministic orthonormal basis of the plane perpendicular to ``d̂``.

    The choice is arbitrary but must be *stable* — a basis that flips with
    floating-point noise would make projected areas, and therefore the
    ranking, non-reproducible (plan §8.3).
    """
    direction = normalize3(pull_direction)
    reference: Vec3 = (0.0, 0.0, 1.0)
    if abs(dot3(direction, reference)) > 0.9:
        reference = (1.0, 0.0, 0.0)
    u_axis = normalize3(cross3(reference, direction))
    v_axis = normalize3(cross3(direction, u_axis))
    return u_axis, v_axis


def project_points(points: tuple[Vec3, ...], u_axis: Vec3, v_axis: Vec3) -> list[tuple[float, float]]:
    return [(dot3(p, u_axis), dot3(p, v_axis)) for p in points]


def shoelace_area(points_2d: list[tuple[float, float]]) -> float:
    """
    Signed area of a closed polygon (the shoelace / surveyor's formula)::

            A = ½ · Σ (x_i·y_{i+1} − x_{i+1}·y_i)

    This is the T1 numerator. v1 uses a **bounding-box** area instead, which
    scores an L-shaped loop identically to a rectangle of the same extent
    (audit RC-5). Returns the signed value; callers take ``abs``.
    """
    if len(points_2d) < 3:
        return 0.0
    total = 0.0
    for i in range(len(points_2d)):
        x0, y0 = points_2d[i]
        x1, y1 = points_2d[(i + 1) % len(points_2d)]
        total += x0 * y1 - x1 * y0
    return 0.5 * total


def bbox_area_2d(points_2d: list[tuple[float, float]]) -> float:
    if not points_2d:
        return 0.0
    xs = [p[0] for p in points_2d]
    ys = [p[1] for p in points_2d]
    return max(0.0, max(xs) - min(xs)) * max(0.0, max(ys) - min(ys))


def polyline_length_3d(points: tuple[Vec3, ...], *, closed: bool = False) -> float:
    if len(points) < 2:
        return 0.0
    total = 0.0
    count = len(points) if closed else len(points) - 1
    for i in range(count):
        a, b = points[i], points[(i + 1) % len(points)]
        total += math.dist(a, b)
    return total


def pull_axis_span(points: tuple[Vec3, ...], pull_direction: Vec3) -> float:
    """
    ``max(P·d̂) − min(P·d̂)`` — how far the mold must step along the pull axis.

    This replaces PCA-based "planarity" (ranking tier T3). PCA finds the plane
    that best *fits* the loop, which is not the same as a valid *parting*
    plane: measured on Part3, PCA fits the loop to 0.74 mm while sitting ~60°
    off the pull axis, and using it would slice the mold diagonally
    (``config.yaml:132-136``). Fixing the plane normal to ``d̂`` and measuring
    the span removes that failure mode entirely, and the number that comes out
    is the physically meaningful one.

    It is also **exactly the error the planar split tool introduces** — so
    ``SplitTool.max_deviation_from_loop_mm`` is this quantity (plan §10.2).
    """
    if not points:
        return 0.0
    direction = normalize3(pull_direction)
    projections = [dot3(p, direction) for p in points]
    return max(projections) - min(projections)


def total_turning(points: tuple[Vec3, ...], *, closed: bool) -> float:
    """
    Discrete total turning ``K = Σ θ_i``, ``θ_i`` between consecutive tangents.

    Degenerate (zero-length) steps are skipped rather than contributing a
    spurious angle — a repeated point is a sampling artefact, not a corner.
    """
    if len(points) < 3:
        return 0.0
    tangents: list[Vec3] = []
    count = len(points) if closed else len(points) - 1
    for i in range(count):
        a, b = points[i], points[(i + 1) % len(points)]
        delta = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        if math.sqrt(sum(c * c for c in delta)) > 1e-12:
            tangents.append(normalize3(delta))

    if len(tangents) < 2:
        return 0.0
    total = 0.0
    pairs = len(tangents) if closed else len(tangents) - 1
    for i in range(pairs):
        t0, t1 = tangents[i], tangents[(i + 1) % len(tangents)]
        total += math.acos(max(-1.0, min(1.0, dot3(t0, t1))))
    return total


def excess_turning(points: tuple[Vec3, ...], *, closed: bool) -> float:
    """
    Ranking tier T5::

            E = max(0, (K − 2π) / 2π)

    **Why excess and not curvature.** "Low curvature = good parting line" is
    wrong, and the study notes flag it correctly: a turned part's parting line
    is a circle, and a rectangular housing's is a rectangle — both are ideal.
    Both also have ``K = 2π`` exactly, so both score ``E = 0`` and are **not
    penalised**. A zigzag accumulates turning well past ``2π`` and is.

    ``E`` is dimensionless, scale-invariant, and needs no tuned threshold —
    the cleanest of the soft criteria.
    """
    if not closed or len(points) < 3:
        return 0.0
    turning = total_turning(points, closed=True)
    return max(0.0, (turning - 2.0 * math.pi) / (2.0 * math.pi))


def _orientation(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_cross_2d(
    p0: tuple[float, float], p1: tuple[float, float],
    q0: tuple[float, float], q1: tuple[float, float],
    tolerance: float,
) -> bool:
    d1, d2 = _orientation(q0, q1, p0), _orientation(q0, q1, p1)
    d3, d4 = _orientation(p0, p1, q0), _orientation(p0, p1, q1)
    if ((d1 > tolerance and d2 < -tolerance) or (d1 < -tolerance and d2 > tolerance)) and \
       ((d3 > tolerance and d4 < -tolerance) or (d3 < -tolerance and d4 > tolerance)):
        return True
    return False


def _segment_bbox_2d(
    p0: tuple[float, float], p1: tuple[float, float],
) -> tuple[float, float, float, float]:
    """``(xmin, xmax, ymin, ymax)`` of one 2-D segment."""
    return (
        p0[0] if p0[0] <= p1[0] else p1[0],
        p1[0] if p1[0] >= p0[0] else p0[0],
        p0[1] if p0[1] <= p1[1] else p1[1],
        p1[1] if p1[1] >= p0[1] else p0[1],
    )


def _bboxes_disjoint_2d(
    b1: tuple[float, float, float, float], b2: tuple[float, float, float, float],
) -> bool:
    """
    O14/O15: a pure prefilter for ``_segments_cross_2d``, proven exact --
    not an approximation. Any point where two segments touch or cross must
    lie on both segments, hence within both segments' bounding boxes; if
    the boxes share no point, the segments cannot touch or cross under
    ANY definition, including the strict-crossing predicate
    ``_segments_cross_2d`` implements, regardless of that predicate's own
    ``1e-12`` orientation tolerance (which only matters for segments whose
    boxes DO overlap). Strict inequality (``<``, never ``<=``) is
    deliberate: boxes that merely touch at a boundary are NOT disjoint
    here, so that pair always still reaches the exact predicate.
    """
    return (
        b1[1] < b2[0] or b2[1] < b1[0]
        or b1[3] < b2[2] or b2[3] < b1[2]
    )


def _segment_distance_3d(
    p0: Vec3, p1: Vec3, q0: Vec3, q1: Vec3
) -> float:
    """Minimum distance between two 3-D segments (clamped closest approach)."""
    u = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
    v = (q1[0] - q0[0], q1[1] - q0[1], q1[2] - q0[2])
    w = (p0[0] - q0[0], p0[1] - q0[1], p0[2] - q0[2])
    a, b, c = dot3(u, u), dot3(u, v), dot3(v, v)
    d, e = dot3(u, w), dot3(v, w)
    denominator = a * c - b * b

    if denominator < 1e-14:          # near-parallel
        s, t = 0.0, (e / c if c > 1e-14 else 0.0)
    else:
        s = (b * e - c * d) / denominator
        t = (a * e - b * d) / denominator
    s, t = max(0.0, min(1.0, s)), max(0.0, min(1.0, t))

    closest_p = (p0[0] + s * u[0], p0[1] + s * u[1], p0[2] + s * u[2])
    closest_q = (q0[0] + t * v[0], q0[1] + t * v[1], q0[2] + t * v[2])
    return math.dist(closest_p, closest_q)


def self_intersection_multi(
    loops: tuple[tuple[Vec3, ...], ...],
    pull_direction: Vec3,
    *,
    tolerance: float,
) -> tuple[bool, int, int]:
    """
    Gate H2 for a ``Γ`` that is a **disjoint union** of closed curves.

    Checks each loop against itself AND every pair of loops against each
    other. Cross-loop checking is not optional: an outer rim and a hole rim
    that cross would be just as invalid as a single self-crossing loop, and
    the disjointness in "disjoint union of simple closed curves" (plan C1) is
    exactly what this enforces.
    """
    if not loops:
        return False, 0, 0

    total_checked = 0
    total_confirmed = 0
    for loop in loops:
        intersects, checked, confirmed = self_intersection(
            loop, pull_direction, closed=True, tolerance=tolerance
        )
        total_checked += checked
        total_confirmed += confirmed
        if intersects:
            return True, total_checked, total_confirmed

    u_axis, v_axis = projection_basis(pull_direction)
    for i in range(len(loops)):
        for j in range(i + 1, len(loops)):
            flat_i = project_points(loops[i], u_axis, v_axis)
            flat_j = project_points(loops[j], u_axis, v_axis)
            # O15: precomputed once per loop pair, reused for every (a, b)
            # comparison below -- see _bboxes_disjoint_2d's docstring for
            # the exactness proof; identical rationale as self_intersection.
            bboxes_i = [
                _segment_bbox_2d(flat_i[a], flat_i[(a + 1) % len(loops[i])])
                for a in range(len(loops[i]))
            ]
            bboxes_j = [
                _segment_bbox_2d(flat_j[b], flat_j[(b + 1) % len(loops[j])])
                for b in range(len(loops[j]))
            ]
            for a in range(len(loops[i])):
                a_next = (a + 1) % len(loops[i])
                bbox_a = bboxes_i[a]
                for b in range(len(loops[j])):
                    b_next = (b + 1) % len(loops[j])
                    total_checked += 1
                    if _bboxes_disjoint_2d(bbox_a, bboxes_j[b]):
                        continue
                    if not _segments_cross_2d(
                        flat_i[a], flat_i[a_next], flat_j[b], flat_j[b_next], 1e-12
                    ):
                        continue
                    distance = _segment_distance_3d(
                        loops[i][a], loops[i][a_next], loops[j][b], loops[j][b_next]
                    )
                    if distance < tolerance:
                        total_confirmed += 1
                        return True, total_checked, total_confirmed
    return False, total_checked, total_confirmed


def self_intersection(
    points: tuple[Vec3, ...],
    pull_direction: Vec3,
    *,
    closed: bool,
    tolerance: float,
) -> tuple[bool, int, int]:
    """
    Gate H2. Returns ``(intersects, checked_pairs_2d, confirmed_3d)``.

    Two phases, in the only order that is sound:

    1. **Project** into the pull-normal plane and test all non-adjacent
       segment pairs. Projection can only *create* apparent crossings, never
       destroy real ones — so **zero 2-D crossings is a PROOF of zero 3-D
       crossings**, and the loop passes immediately.
    2. Any 2-D crossing may be spurious (two curves can overlap in projection
       while passing at different heights). Decide those in **3-D**, by
       minimum segment-segment distance against ``tolerance``.

    This is O(n²) by design. Plan §12.5 rule 2 forbids optimizing a stage the
    corpus profile has not identified as a bottleneck; a Bentley-Ottmann sweep
    is the upgrade if it ever does. O15 (2026-08-17): the corpus profile DID
    identify this as the dominant bottleneck (see docs/DECISIONS_AND_ALGORITHMS.md
    O13/O14/O15) -- a bounding-box prefilter (``_bboxes_disjoint_2d``) now
    skips ``_segments_cross_2d`` for pairs proven incapable of crossing,
    exactly the "Bentley-Ottmann is the upgrade" note anticipated, but via
    the smaller, provably-exact bbox step rather than a full sweep-line
    rewrite. The O(n²) pair ENUMERATION is unchanged; only the cost of each
    pair examination drops for the (typically >99%) of pairs the bbox
    proves disjoint. ``checked`` still counts every non-adjacent pair the
    algorithm considers, exactly as before -- the prefilter changes what
    happens AFTER that count, never whether a pair is counted.
    """
    if len(points) < 4:
        return False, 0, 0

    u_axis, v_axis = projection_basis(pull_direction)
    flat = project_points(points, u_axis, v_axis)
    n = len(points)
    limit = n if closed else n - 1
    bboxes = [_segment_bbox_2d(flat[k], flat[(k + 1) % n]) for k in range(limit)]

    checked = 0
    confirmed = 0
    for i in range(limit):
        i_next = (i + 1) % n
        bbox_i = bboxes[i]
        for j in range(i + 2, limit):
            j_next = (j + 1) % n
            if i == j_next or j == i_next:
                continue          # adjacent segments legitimately share a point
            checked += 1
            if _bboxes_disjoint_2d(bbox_i, bboxes[j]):
                continue
            if not _segments_cross_2d(flat[i], flat[i_next], flat[j], flat[j_next], 1e-12):
                continue
            distance = _segment_distance_3d(points[i], points[i_next], points[j], points[j_next])
            if distance < tolerance:
                confirmed += 1
    return confirmed > 0, checked, confirmed


def cauchy_projected_area(
    face_areas: list[float], face_g_values: list[float]
) -> float:
    """
    Cheap denominator for T1 coverage::

            A_cauchy = ½ · Σ_f A_f · |n̂_f · d̂|

    ⚠ **This is an UPPER BOUND, not the true projected outline area**, for any
    non-convex solid: where the boundary's projection covers a point more than
    twice, the sum counts it more than twice. It is exact only for a convex
    body.

    Consequence, which must be stated wherever coverage is reported: the
    resulting ``coverage`` is a **conservative under-estimate**. That is safe
    for a gate (it under-rejects) but must never be quoted as "the" coverage
    without the caveat. The exact tessellation-union path is P3a's job, which
    also measures how large this overestimate actually is per part.
    """
    if len(face_areas) != len(face_g_values):
        raise ValueError("face_areas and face_g_values must be the same length.")
    return 0.5 * sum(a * abs(g) for a, g in zip(face_areas, face_g_values))


def distinct_point_count(points: tuple[Vec3, ...], tolerance: float) -> int:
    """Points that differ by more than ``tolerance`` from all earlier ones."""
    distinct: list[Vec3] = []
    for point in points:
        if all(math.dist(point, other) > tolerance for other in distinct):
            distinct.append(point)
    return len(distinct)
