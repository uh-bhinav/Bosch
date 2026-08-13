"""
backend/geometry/parting_line_v2/stitch.py
------------------------------------------
Track A ↔ Track B stitching (plan §4.2 step 5).

The problem
-----------
The two tracks produce curves that **meet but do not share endpoints**. A
face-interior silhouette curve runs to the edge of its face and stops there —
at a general point along a B-Rep edge, not at that edge's vertex. Track A's
segment for the same edge spans the whole edge. So welding by endpoint
proximity never joins them: the curves touch in space, but the graph has no
node where they touch.

Measured on F3 (cylinder pulled across its axis): Track B finds the two
rulings, Track A finds the two cap-rim circles, and **nothing connects**. The
rulings are open chains, 2-core reduction deletes them as dangling ends, and
the engine reports no candidate — while the correct answer is plainly
*ruling + cap arc + ruling + cap arc*.

The fix
-------
Split each edge-backed segment at the parameters where face-backed curves
terminate on it, so a real graph node exists at every junction. The split
points come from projecting the face curve's endpoint onto the **edge's own
OCC curve**, so both sides land on exactly the same geometry and gate H0 is
preserved by construction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from backend.geometry.parting_line_v2.types import CurveSegment, EdgeBacking, FaceBacking
from backend.models.geometry_models import PartGeometry, Vec3

try:
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
    from OCC.Core.GeomAPI import GeomAPI_ProjectPointOnCurve
    from OCC.Core.gp import gp_Pnt
    from OCC.Core.TopoDS import TopoDS_Edge

    _OCC_AVAILABLE = True
except Exception:  # pragma: no cover
    _OCC_AVAILABLE = False


__all__ = ["StitchResult", "stitch_tracks"]


@dataclass(frozen=True)
class StitchResult:
    segments: tuple[CurveSegment, ...]
    junction_count: int
    split_edge_segment_count: int

    def to_dict(self) -> dict:
        return {
            "junction_count": self.junction_count,
            "split_edge_segment_count": self.split_edge_segment_count,
            "segment_count": len(self.segments),
        }


def _curve_points(adaptor: object, t_lo: float, t_hi: float, count: int) -> tuple[Vec3, ...]:
    points: list[Vec3] = []
    for i in range(count):
        t = t_lo + (t_hi - t_lo) * i / (count - 1)
        p: gp_Pnt = adaptor.Value(t)  # type: ignore[union-attr]
        points.append((float(p.X()), float(p.Y()), float(p.Z())))
    return tuple(points)


def stitch_tracks(
    part: PartGeometry,
    edge_segments: tuple[CurveSegment, ...],
    face_segments: tuple[CurveSegment, ...],
    *,
    tolerance_mm: float,
) -> StitchResult:
    """
    Split edge-backed segments wherever a face-backed curve terminates on them.

    Returns every segment (split edge segments plus the untouched face
    segments) with contiguous ids. Face segments are never modified — they are
    already exactly where the mathematics puts them.
    """
    if not _OCC_AVAILABLE or not face_segments or not edge_segments:
        return StitchResult(edge_segments + face_segments, 0, 0)

    edges_by_id = {e.edge_id: e for e in part.edges}

    # Snap face-curve endpoints onto the boundary edge they reach, FIRST.
    #
    # A Track B curve that runs to the edge of its face terminates at a point
    # computed independently on that face: marching squares locates it on a
    # grid and Newton converges `g -> 0` in PARAMETER space, not to the shared
    # edge. Two curves meeting at the same edge from adjacent faces therefore
    # land slightly apart, and welding — correctly tuned to the kernel's
    # tolerance — refuses to join them.
    #
    # Measured on Part1 at its optimal direction: gaps of 7e-05 to 2.4e-04 mm
    # against a weld tolerance of 3.08e-05 mm, which left **213 of 243
    # segments pruned as dangling** and only 5 local cycles surviving. The
    # gaps are numerical, not geometric — sub-micron on a 30 mm part.
    #
    # Snapping moves the endpoint ONTO the edge curve and recomputes its (u,v)
    # from that edge's pcurve on the face, so the point stays exactly on both
    # the edge and the face and gate H0 is preserved rather than weakened. The
    # alternative — loosening the global weld tolerance — would blunt Track A
    # too and risk merging genuinely distinct vertices.
    face_segments, snapped = _snap_face_endpoints_to_edges(
        part, face_segments, tolerance_mm=tolerance_mm
    )

    # Each junction is tagged with the face it came from. A cut is only ever
    # attempted against an edge that GENUINELY BOUNDS that face
    # (edge.adjacent_face_ids), mirroring the same restriction
    # `_snap_face_endpoints_to_edges` already applies to its own search. This
    # is deliberate, not incidental: without it, this loop checks every
    # junction point in the WHOLE PART against every edge with no structural
    # relationship required at all — a global proximity search. Measured
    # directly (2026-08-12 connectivity-fix follow-up): widening
    # `tolerance_mm` without this restriction let unrelated faces' junction
    # points start cutting edges they have no B-Rep relationship to, growing
    # Part3's pre-reduction graph by ~25% (503->631 nodes at +X) without
    # actually reducing the number of segments 2-core pruned. Scoping to
    # `adjacent_face_ids` is exactly the "only connect via real B-Rep
    # topology, never mere proximity" rule the rest of this package already
    # follows (H3, the weld search, the snap search above).
    #
    # This scoping is a correctness improvement in its own right (unscoped
    # proximity search is a real bug independent of the tolerance question),
    # but it is NOT, by itself, a fix for the pruning problem: even with this
    # restriction in place, the pruned-segment count on both real parts is
    # unchanged from before ANY of this work (D-022, still open).
    junctions: list[tuple[Vec3, int]] = []
    for segment in face_segments:
        if isinstance(segment.backing, FaceBacking):
            junctions.append((segment.start, segment.backing.face_id))
            junctions.append((segment.end, segment.backing.face_id))

    result: list[CurveSegment] = []
    next_id = 0
    junction_hits = 0
    split_count = 0

    for segment in sorted(edge_segments, key=lambda s: s.segment_id):
        backing = segment.backing
        edge = edges_by_id.get(backing.edge_id) if isinstance(backing, EdgeBacking) else None
        if edge is None or not isinstance(edge.occ_edge, TopoDS_Edge):
            result.append(_renumber(segment, next_id))
            next_id += 1
            continue

        try:
            adaptor = BRepAdaptor_Curve(edge.occ_edge)
            curve, first, last = BRep_Tool.Curve(edge.occ_edge)
        except Exception:
            curve = None
        if curve is None:
            result.append(_renumber(segment, next_id))
            next_id += 1
            continue

        t_lo, t_hi = backing.t_start, backing.t_end
        cuts: list[float] = []
        candidate_points = [
            point for point, face_id in junctions if face_id in edge.adjacent_face_ids
        ]
        for point in candidate_points:
            try:
                projector = GeomAPI_ProjectPointOnCurve(gp_Pnt(*point), curve, first, last)
                if projector.NbPoints() == 0:
                    continue
                distance = float(projector.LowerDistance())
                parameter = float(projector.LowerDistanceParameter())
            except Exception:
                continue
            if distance > tolerance_mm:
                continue
            span = abs(t_hi - t_lo)
            if span <= 0.0:
                continue
            # Strictly interior only: a junction at an existing endpoint
            # already welds normally and needs no split.
            if min(t_lo, t_hi) + 1e-9 * span < parameter < max(t_lo, t_hi) - 1e-9 * span:
                cuts.append(parameter)
                junction_hits += 1

        if not cuts:
            result.append(_renumber(segment, next_id))
            next_id += 1
            continue

        boundaries = sorted({t_lo, t_hi, *cuts}, reverse=t_hi < t_lo)
        pieces = 0
        for a, b in zip(boundaries, boundaries[1:]):
            if abs(b - a) <= 0.0:
                continue
            count = max(2, math.ceil(len(segment.points) * abs(b - a) / max(abs(t_hi - t_lo), 1e-12)))
            result.append(CurveSegment(
                segment_id=next_id,
                points=_curve_points(adaptor, a, b, count),
                backing=EdgeBacking(backing.edge_id, a, b),
                kind=segment.kind,
                g_values=(),
            ))
            next_id += 1
            pieces += 1
        if pieces:
            split_count += 1

    for segment in sorted(face_segments, key=lambda s: s.segment_id):
        result.append(_renumber(segment, next_id))
        next_id += 1

    return StitchResult(tuple(result), junction_hits + snapped, split_count)


def _renumber(segment: CurveSegment, segment_id: int) -> CurveSegment:
    return CurveSegment(
        segment_id=segment_id,
        points=segment.points,
        backing=segment.backing,
        kind=segment.kind,
        g_values=segment.g_values,
    )


def _snap_face_endpoints_to_edges(
    part: PartGeometry,
    face_segments: tuple[CurveSegment, ...],
    *,
    tolerance_mm: float,
) -> tuple[tuple[CurveSegment, ...], int]:
    """
    Move each face-curve endpoint onto the nearest bounding edge of its own
    face, when one is within ``tolerance_mm``.

    The replacement point is taken from the **edge's OCC curve**, and its
    ``(u,v)`` from that edge's **pcurve on the face** — so the snapped point
    lies exactly on the edge AND exactly on the face, and H0.3's surface and
    containment checks both still hold. Only endpoints move; interior points
    are already where the mathematics puts them.
    """
    edges_by_id = {e.edge_id: e for e in part.edges}
    faces_by_id = {f.face_id: f for f in part.faces}
    snapped = 0
    adjusted: list[CurveSegment] = []

    for segment in face_segments:
        backing = segment.backing
        if not isinstance(backing, FaceBacking):
            adjusted.append(segment)
            continue
        face_data = faces_by_id.get(backing.face_id)
        if face_data is None:
            adjusted.append(segment)
            continue
        candidate_edges = [
            edges_by_id[e] for e in part.face_to_edges.get(backing.face_id, ())
            if e in edges_by_id
        ]
        if not candidate_edges:
            adjusted.append(segment)
            continue

        points = list(segment.points)
        uvs = list(backing.uv)
        for index in (0, len(points) - 1):
            best = None
            for edge in candidate_edges:
                if not isinstance(edge.occ_edge, TopoDS_Edge):
                    continue
                try:
                    curve, first, last = BRep_Tool.Curve(edge.occ_edge)
                    if curve is None:
                        continue
                    projector = GeomAPI_ProjectPointOnCurve(
                        gp_Pnt(*points[index]), curve, first, last
                    )
                    if projector.NbPoints() == 0:
                        continue
                    distance = float(projector.LowerDistance())
                except Exception:
                    continue
                if distance <= tolerance_mm and (best is None or distance < best[0]):
                    best = (distance, edge, float(projector.LowerDistanceParameter()))
            if best is None:
                continue
            _, edge, parameter = best
            try:
                pcurve, p_first, p_last = BRep_Tool.CurveOnSurface(
                    edge.occ_edge, face_data.occ_face
                )
                if pcurve is None:
                    continue
                clamped = min(max(parameter, p_first), p_last)
                uv = pcurve.Value(clamped)
                adaptor = BRepAdaptor_Curve(edge.occ_edge)
                snapped_point = adaptor.Value(parameter)
            except Exception:
                continue
            points[index] = (
                float(snapped_point.X()), float(snapped_point.Y()), float(snapped_point.Z())
            )
            uvs[index] = (float(uv.X()), float(uv.Y()))
            snapped += 1

        adjusted.append(CurveSegment(
            segment_id=segment.segment_id,
            points=tuple(points),
            backing=FaceBacking(backing.face_id, tuple(uvs)),
            kind=segment.kind,
            g_values=segment.g_values,
        ))
    return tuple(adjusted), snapped
