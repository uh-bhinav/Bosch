"""
backend/validation/parting_line_forensic_trace.py
-----------------------------------------------------
READ-ONLY AUTOMATED FORENSIC TOOL (P3.18, 2026-08-13). Diagnostic only --
does not modify Track A/B, stitching, graph construction, H0-H7, weld
tolerances, or decomposition. No production code touched.

Built after a manual trace of cluster 49 caught a real mistake: comparing
an OCC edge curve parameter (t) directly against a face UV parameter (u)
because the numbers looked similar. They are DIFFERENT parameterizations
and are NEVER comparable as raw numbers. This tool enforces the correction
structurally: every correspondence claim is established by evaluating
actual OCC geometry (BRepAdaptor_Curve.Value(t), Geom_Surface evaluation,
GeomAPI_ProjectPointOnSurf/OnCurve) and comparing resulting 3-D points,
never by comparing parameter values across different curves/surfaces.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from OCC.Core.BRep import BRep_Tool
from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
from OCC.Core.GeomAPI import GeomAPI_ProjectPointOnCurve, GeomAPI_ProjectPointOnSurf
from OCC.Core.gp import gp_Pnt

import backend.validation.parting_line_face_partition as fp
import backend.validation.parting_line_region_partition_prototype as proto
from backend.geometry.parting_line_v2.types import EdgeBacking, FaceBacking
from backend.models.geometry_models import dot3


def _edge_nearest_point(edge_data, target_3d, n_samples: int = 50):
    """
    Nearest point on an edge's REAL 3-D curve to `target_3d`, via actual OCC
    projection -- never via comparing parameter numbers.
    """
    try:
        curve, first, last = BRep_Tool.Curve(edge_data.occ_edge)
    except Exception:
        return None
    if curve is None:
        return None
    try:
        projector = GeomAPI_ProjectPointOnCurve(gp_Pnt(*target_3d), curve, first, last)
        if projector.NbPoints() < 1:
            return None
        t = projector.LowerDistanceParameter()
        p = projector.NearestPoint()
        dist = projector.LowerDistance()
    except Exception:
        return None
    return {"t": t, "point": (p.X(), p.Y(), p.Z()), "distance_mm": dist, "range": (first, last)}


def _face_nearest_uv(face_data, target_3d):
    """Nearest (u,v) on a face's REAL surface to `target_3d`, via actual OCC projection."""
    try:
        surface = BRep_Tool.Surface(face_data.occ_face)
        projector = GeomAPI_ProjectPointOnSurf(gp_Pnt(*target_3d), surface)
        if projector.NbPoints() < 1:
            return None
        u, v = projector.LowerDistanceParameters()
        dist = projector.LowerDistance()
    except Exception:
        return None
    return {"u": u, "v": v, "distance_mm": dist}


def search_all_edges_near_point(part, target_3d, radius_mm: float):
    """
    Exhaustive search of EVERY B-Rep edge in the part (not just ones already
    in the current cut-piece graph) for proximity to `target_3d`, via real
    OCC curve projection.
    """
    hits = []
    for edge in part.edges:
        nearest = _edge_nearest_point(edge, target_3d)
        if nearest is None:
            continue
        vertex_dists = []
        if edge.start_vertex is not None:
            vertex_dists.append(("start_vertex", math.dist(edge.start_vertex, target_3d)))
        if edge.end_vertex is not None:
            vertex_dists.append(("end_vertex", math.dist(edge.end_vertex, target_3d)))
        best_vertex = min(vertex_dists, key=lambda x: x[1]) if vertex_dists else None
        min_dist = min([nearest["distance_mm"]] + [d for _, d in vertex_dists], default=nearest["distance_mm"])
        if min_dist <= radius_mm:
            hits.append({
                "edge_id": edge.edge_id, "edge_type": edge.edge_type,
                "adjacent_face_ids": list(edge.adjacent_face_ids),
                "length_mm": edge.length,
                "nearest_curve_point": nearest,
                "nearest_vertex": best_vertex,
                "min_distance_mm": round(min_dist, 6),
            })
    hits.sort(key=lambda h: h["min_distance_mm"])
    return hits


def face_geometry_report(part, face_id, target_3d, direction):
    faces_by_id = {f.face_id: f for f in part.faces}
    face = faces_by_id.get(face_id)
    if face is None:
        return None
    uv = _face_nearest_uv(face, target_3d)
    try:
        from backend.geometry.step_loader import _face_normal_at_uv
        normal = _face_normal_at_uv(face.occ_face, uv["u"], uv["v"]) if uv else None
        g = dot3(normal, direction) if normal is not None else None
    except Exception:
        g = None
    surf = BRep_Tool.Surface(face.occ_face)
    is_u_periodic = surf.IsUPeriodic() if hasattr(surf, "IsUPeriodic") else None
    is_v_periodic = surf.IsVPeriodic() if hasattr(surf, "IsVPeriodic") else None
    try:
        from OCC.Core.BRepTools import breptools
        u_min, u_max, v_min, v_max = breptools.UVBounds(face.occ_face)
    except Exception:
        u_min = u_max = v_min = v_max = None
    return {
        "face_id": face_id, "surface_type": face.surface_type,
        "nearest_uv": uv, "g_at_nearest_uv": g,
        "is_u_periodic": is_u_periodic, "is_v_periodic": is_v_periodic,
        "u_bounds": (u_min, u_max), "v_bounds": (v_min, v_max),
    }


def region_membership_report(part, face_id, target_3d, track_b_segments):
    faces_by_id = {f.face_id: f for f in part.faces}
    face = faces_by_id.get(face_id)
    if face is None:
        return None
    segs = [s for s in track_b_segments if isinstance(s.backing, FaceBacking) and s.backing.face_id == face_id]
    regions = fp.build_face_regions(part, face, segs)
    uv = _face_nearest_uv(face, target_3d)
    membership = None
    if uv and regions:
        from shapely.geometry import Point
        pt = Point(uv["u"], uv["v"])
        for region in regions:
            if region.polygon.covers(pt):
                membership = region.region_id
                break
        if membership is None:
            best = min(regions, key=lambda r: r.polygon.distance(pt))
            membership = f"nearest={best.region_id} (not strictly inside any region -- on/near a boundary)"

    curve_distances = []
    for seg in segs:
        dists = [math.dist(p, target_3d) for p in seg.points]
        curve_distances.append({"segment_id": seg.segment_id, "min_3d_distance_mm": round(min(dists), 6)})
    curve_distances.sort(key=lambda d: d["min_3d_distance_mm"])

    return {
        "face_id": face_id, "region_count": len(regions) if regions else (1 if regions is None else 0),
        "region_containing_point": membership,
        "track_b_curve_count": len(segs),
        "nearest_track_b_curves": curve_distances,
    }


def cross_face_attachment_report(part, face_a_id, face_b_id, edge_id, target_3d, direction, track_b_segments):
    faces_by_id = {f.face_id: f for f in part.faces}
    edges_by_id = {e.edge_id: e for e in part.edges}
    face_a, face_b, edge = faces_by_id[face_a_id], faces_by_id[face_b_id], edges_by_id[edge_id]

    segs_a = [s for s in track_b_segments if isinstance(s.backing, FaceBacking) and s.backing.face_id == face_a_id]
    segs_b = [s for s in track_b_segments if isinstance(s.backing, FaceBacking) and s.backing.face_id == face_b_id]
    regions_a = fp.build_face_regions(part, face_a, segs_a)
    regions_b = fp.build_face_regions(part, face_b, segs_b)

    intervals = fp.edge_subinterval_attachment(face_a, face_b, edge, regions_a, regions_b)
    curve = BRepAdaptor_Curve(edge.occ_edge)

    report = []
    for iv in intervals:
        p_start = curve.Value(iv.t_start)
        p_end = curve.Value(iv.t_end)
        p_start_3d = (p_start.X(), p_start.Y(), p_start.Z())
        p_end_3d = (p_end.X(), p_end.Y(), p_end.Z())
        near_target = min(math.dist(p_start_3d, target_3d), math.dist(p_end_3d, target_3d))
        report.append({
            "t_start": iv.t_start, "t_end": iv.t_end,
            "point_start_3d": p_start_3d, "point_end_3d": p_end_3d,
            "region_a": iv.region_a, "region_b": iv.region_b,
            "nearest_endpoint_distance_to_target_mm": round(near_target, 6),
        })
    return report


def forensic_trace(part, direction_tuple, target_3d, weld_tolerance_mm: float, label: str = ""):
    """The complete automated forensic trace for one 3-D location."""
    from backend.config import settings
    from backend.geometry.parting_line_v2.contracts import PullDirectionInput
    from backend.geometry.parting_line_v2.track_a import detect_edge_silhouettes
    from backend.geometry.parting_line_v2.track_b import detect_face_silhouettes

    cfg = settings.dfm.parting_line_v2
    direction = PullDirectionInput(direction_tuple, "manual").direction
    bbox_diag = proto._bbox_diagonal(part)
    track_a = detect_edge_silhouettes(part, direction, cfg=cfg, bbox_diagonal_mm=bbox_diag)
    silhouette_edge_ids = frozenset(
        s.backing.edge_id for s in track_a.segments
        if s.kind == "silhouette" and isinstance(s.backing, EdgeBacking)
    )
    track_b = detect_face_silhouettes(part, direction, cfg=cfg, bbox_diagonal_mm=bbox_diag, start_segment_id=len(track_a.segments))

    print(f"\n{'=' * 70}\nFORENSIC TRACE: {label}\ntarget_3d = {target_3d}\n{'=' * 70}", flush=True)

    print("\n--- B. Exhaustive B-Rep edge search (ALL edges, not just current cut-piece set) ---", flush=True)
    search_radius = max(weld_tolerance_mm * 3, 2.0)
    edge_hits = search_all_edges_near_point(part, target_3d, search_radius)
    print(f"radius={search_radius:.4f}mm  found {len(edge_hits)} edges", flush=True)
    for h in edge_hits:
        print(f"  edge {h['edge_id']:4d} ({h['edge_type']:10s}) faces={h['adjacent_face_ids']} "
              f"len={h['length_mm']:.4f}mm  min_dist={h['min_distance_mm']:.6f}mm  "
              f"nearest_curve_t={h['nearest_curve_point']['t']:.6f}  "
              f"nearest_vertex={h['nearest_vertex']}", flush=True)

    involved_faces = sorted({fid for h in edge_hits for fid in h["adjacent_face_ids"]})
    print(f"\n--- C/D. Face surface + region membership for faces {involved_faces} ---", flush=True)
    face_reports = {}
    region_reports = {}
    for fid in involved_faces:
        fr = face_geometry_report(part, fid, target_3d, direction)
        rr = region_membership_report(part, fid, target_3d, track_b.segments)
        face_reports[fid] = fr
        region_reports[fid] = rr
        print(f"  face {fid} ({fr['surface_type']}): nearest_uv={fr['nearest_uv']} "
              f"dist={fr['nearest_uv']['distance_mm']:.6f}mm g={fr['g_at_nearest_uv']} "
              f"u_periodic={fr['is_u_periodic']} v_periodic={fr['is_v_periodic']} "
              f"u_bounds={fr['u_bounds']}", flush=True)
        print(f"      regions={rr['region_count']} containing_region={rr['region_containing_point']} "
              f"track_b_curves={rr['track_b_curve_count']} nearest={rr['nearest_track_b_curves']}", flush=True)

    print(f"\n--- E. Cross-face attachment for every shared edge among {involved_faces} ---", flush=True)
    checked_pairs = set()
    attachment_reports = {}
    for h in edge_hits:
        fids = h["adjacent_face_ids"]
        if len(fids) != 2:
            continue
        pair = tuple(sorted(fids))
        if pair in checked_pairs:
            continue
        checked_pairs.add(pair)
        report = cross_face_attachment_report(part, pair[0], pair[1], h["edge_id"], target_3d, direction, track_b.segments)
        attachment_reports[(pair, h["edge_id"])] = report
        print(f"  edge {h['edge_id']} faces={pair}:", flush=True)
        for iv in report:
            marker = " <-- NEAR TARGET" if iv["nearest_endpoint_distance_to_target_mm"] <= weld_tolerance_mm else ""
            print(f"      [{iv['t_start']:.4f},{iv['t_end']:.4f}] region_a={iv['region_a']} region_b={iv['region_b']} "
                  f"end_pts={iv['point_start_3d']}/{iv['point_end_3d']} "
                  f"nearest_dist={iv['nearest_endpoint_distance_to_target_mm']:.6f}mm{marker}", flush=True)

    return {
        "label": label, "target_3d": target_3d, "edge_hits": edge_hits,
        "face_reports": face_reports, "region_reports": region_reports,
        "attachment_reports": attachment_reports,
    }
