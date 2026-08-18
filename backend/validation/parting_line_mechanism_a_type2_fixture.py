"""
backend/validation/parting_line_mechanism_a_type2_fixture.py
------------------------------------------------------
Mechanism A / Type 2 (2026-08-15): minimal REAL-OCC fixture reproducing
"a face-interior Track-B curve has g approx 0 along its ENTIRE length
(a zero-draft-band locus) but is classified kind='silhouette' because
SegmentKind.zero_draft_band is never assigned anywhere in track_b.py".

Derivation (not injected): for a torus centered on the Z axis with pull
direction d=(dx,dy,0) (dz=0), the outward normal is
n(u,v) = (cos(v)cos(u), cos(v)sin(u), sin(v)), so
g(u,v) = n.d = cos(v)*(dx*cos(u) + dy*sin(u)). At u = pi/2 (mod pi), the
term (dx*cos(u)+dy*sin(u)) is identically 0 for EVERY v -- i.e. the
entire meridian circle u=pi/2 is a g=0 locus, not an isolated point. This
was derived from the real torus surface equation, then verified
empirically on this fixture (not assumed).

READ-ONLY DIAGNOSTIC. No file under `backend/geometry/parting_line_v2/`
is modified. No SegmentKind or g-value is injected -- everything below is
produced by calling the REAL `detect_edge_silhouettes` /
`detect_face_silhouettes` / `build_face_regions` machinery on real OCC
geometry.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from OCC.Core.BRep import BRep_Tool
from OCC.Core.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeTorus
from OCC.Core.BRepTools import breptools
from OCC.Core.GCPnts import GCPnts_AbscissaPoint
from OCC.Core.GeomAbs import GeomAbs_Plane, GeomAbs_Torus
from OCC.Core.gp import gp_Ax2, gp_Dir, gp_Pnt
from OCC.Core.GProp import GProp_GProps
from OCC.Core.TopAbs import TopAbs_EDGE, TopAbs_FACE
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopoDS import topods

import backend.validation.parting_line_face_partition as fp
import backend.validation.parting_line_region_partition_prototype as proto
from backend.models.geometry_models import EdgeData, FaceData


def _curve_length(occ_edge, first, last):
    curve = BRepAdaptor_Curve(occ_edge)
    return GCPnts_AbscissaPoint.Length(curve, first, last)


def _face_normal_at_uv_mid(face_occ, u, v):
    surf = BRep_Tool.Surface(face_occ)
    from OCC.Core.GeomLProp import GeomLProp_SLProps
    props = GeomLProp_SLProps(surf, u, v, 1, 1e-9)
    if not props.IsNormalDefined():
        return None
    n = props.Normal()
    if face_occ.Orientation() == 1:  # TopAbs_REVERSED
        n.Reverse()
    return (n.X(), n.Y(), n.Z())


def build_fixture():
    """
    A REAL half-torus solid (`BRepPrimAPI_MakeTorus(axis, R, r, angle)`):
    major radius R=10mm, minor radius r=3mm, swept u in [0, pi] around the
    Z axis -- a genuine OCC primitive, not a hand-built wire. 3 faces:
    face 0 = torus lateral surface (periodic in v, trimmed in u);
    face 1, face 2 = the two planar end caps closing the u=0 and u=pi ends.
    Each cap face meets the torus face along a real shared edge, and the
    two caps' own edges meet the torus's own two boundary circles (v=0..2pi
    at u=0 and u=pi) at real B-Rep vertices -- genuine multi-face corners,
    not synthetic topology.
    """
    R, r = 10.0, 3.0
    axis = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
    solid = BRepPrimAPI_MakeTorus(axis, R, r, math.pi).Shape()

    occ_faces = []
    explorer = TopExp_Explorer(solid, TopAbs_FACE)
    while explorer.More():
        occ_faces.append(topods.Face(explorer.Current()))
        explorer.Next()

    faces = []
    for fid, occ_face in enumerate(occ_faces):
        adaptor = BRepAdaptor_Surface(occ_face)
        u0, u1, v0, v1 = breptools.UVBounds(occ_face)
        um, vm = (u0 + u1) / 2.0, (v0 + v1) / 2.0
        normal = _face_normal_at_uv_mid(occ_face, um, vm)
        props = GProp_GProps()
        brepgprop.SurfaceProperties(occ_face, props)
        area = props.Mass()
        centroid_pnt = props.CentreOfMass()
        centroid = (centroid_pnt.X(), centroid_pnt.Y(), centroid_pnt.Z())
        surface_type = "Torus" if adaptor.GetType() == GeomAbs_Torus else (
            "Plane" if adaptor.GetType() == GeomAbs_Plane else "Other")
        faces.append(FaceData(
            face_id=fid, occ_face=occ_face, surface_type=surface_type,
            normal=normal, centroid=centroid, area=area,
            u_range=(u0, u1), v_range=(v0, v1), is_reversed=False, normal_valid=normal is not None,
        ))

    _HASH_MOD = 2**31 - 1
    seen_edge_keys: dict = {}
    edges_by_id: dict[int, object] = {}
    face_to_edges: dict[int, list[int]] = {}
    edge_to_faces: dict[int, set[int]] = {}
    next_id = 0
    for face_id, occ_face in enumerate(occ_faces):
        explorer = TopExp_Explorer(occ_face, TopAbs_EDGE)
        ids_here: list[int] = []
        while explorer.More():
            occ_edge = topods.Edge(explorer.Current())
            key = occ_edge.HashCode(_HASH_MOD)
            if key not in seen_edge_keys:
                first, last = BRep_Tool.Range(occ_edge)
                length = _curve_length(occ_edge, first, last)
                edges_by_id[next_id] = EdgeData(
                    edge_id=next_id, occ_edge=occ_edge, edge_type="Circle",
                    length=length, adjacent_face_ids=[],
                    start_vertex=None, end_vertex=None, is_seam=False,
                )
                seen_edge_keys[key] = next_id
                next_id += 1
            eid = seen_edge_keys[key]
            ids_here.append(eid)
            edge_to_faces.setdefault(eid, set()).add(face_id)
            explorer.Next()
        face_to_edges[face_id] = ids_here

    for eid, edge in edges_by_id.items():
        edge.adjacent_face_ids[:] = sorted(edge_to_faces[eid])

    class MiniPart:
        def __init__(self):
            self.faces = faces
            self.edges = list(edges_by_id.values())
            self.face_to_edges = face_to_edges
            self.edge_to_faces = {k: sorted(v) for k, v in edge_to_faces.items()}
            self.bounding_box = proto._bbox_diagonal

    part = MiniPart()
    return part, faces


def unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def run_baseline():
    print("=== Task 7 baseline: run REAL Track-A/B on the half-torus fixture ===", flush=True)
    part, faces = build_fixture()

    from backend.config import settings
    from backend.geometry.parting_line_v2.contracts import PullDirectionInput
    from backend.geometry.parting_line_v2.track_a import detect_edge_silhouettes
    from backend.geometry.parting_line_v2.track_b import detect_face_silhouettes

    cfg = settings.dfm.parting_line_v2
    pull = unit((1.0, 0.0, 0.0))  # dz=0 -- the derived degenerate condition
    direction = PullDirectionInput(pull, "manual").direction
    bbox_diag = 26.0  # torus overall extent ~ 2*(R+r) = 26mm

    track_a = detect_edge_silhouettes(part, direction, cfg=cfg, bbox_diagonal_mm=bbox_diag)
    print(f"Track A: {len(track_a.segments)} segments", flush=True)
    for s in track_a.segments:
        print(f"  {s.segment_id}: kind={s.kind} edge_id={s.backing.edge_id}", flush=True)

    track_b = detect_face_silhouettes(part, direction, cfg=cfg, bbox_diagonal_mm=bbox_diag,
                                       start_segment_id=len(track_a.segments))
    print(f"\nTrack B: {len(track_b.segments)} segments", flush=True)
    for s in track_b.segments:
        g = s.g_values
        g_range = (min(g), max(g)) if g else None
        print(f"  seg {s.segment_id}: face_id={s.backing.face_id} kind={s.kind} n_points={len(s.points)} "
              f"g_range={g_range} start={tuple(round(c,3) for c in s.points[0])} "
              f"end={tuple(round(c,3) for c in s.points[-1])}", flush=True)

    return part, faces, track_a, track_b, direction, bbox_diag, cfg


# ============================================================
# Task 7 (correction) -- classify zero_draft_band vs silhouette
# ============================================================

def classify_segment_kind(seg, face, direction, cfg, *, ratio_threshold: float = 1e-6):
    """
    Diagnostic-only reclassification, applied AFTER track_b.py's own
    (unmodified) segment construction -- never injects a kind, never
    touches g_values, never touches an already-"tangential" segment
    (D-025's own edge-proximity classification is untouched).

    Criterion (derived from EXISTING Track-B scaling, not a new absolute
    number): compare the segment's own max|g| against `mean_abs_g` for the
    WHOLE face -- the same area-weighted g-scale production already
    computes for Cauchy projected area (D-011) and region_stats. A
    genuine sign-crossing silhouette's kept points, even though each
    individually satisfies |g| <= tau_silhouette by construction, still
    show g varying on the order of the face's own natural g-scale nearby
    (discrete sample points essentially never land exactly on an analytic
    zero purely by chance). A zero-draft-band curve's g stays at floating-
    point noise (~1e-15) regardless of the face's own g-scale. The RATIO
    is what's compared -- not an absolute tolerance -- so it is scale-
    invariant the same way A1's chord/path ratio was (D-041).
    """
    if seg.kind != "silhouette" or not seg.g_values:
        return seg.kind
    curve_max_abs_g = max(abs(g) for g in seg.g_values)
    face_scale = proto.mean_abs_g(face, direction, cfg.face_sample_grid)
    if face_scale <= 0:
        return seg.kind
    ratio = curve_max_abs_g / face_scale
    return "zero_draft_band" if ratio < ratio_threshold else seg.kind


def run_classification_correction():
    print("\n=== Task 7 correction: classify zero_draft_band vs silhouette ===", flush=True)
    part, faces, track_a, track_b, direction, bbox_diag, cfg = run_baseline()
    faces_by_id = {f.face_id: f for f in faces}

    print("\n--- reclassification on the fixture (should all become zero_draft_band) ---", flush=True)
    for thr in (1e-3, 1e-6, 1e-9):
        results = []
        for seg in track_b.segments:
            face = faces_by_id[seg.backing.face_id]
            new_kind = classify_segment_kind(seg, face, direction, cfg, ratio_threshold=thr)
            results.append((seg.segment_id, seg.kind, new_kind))
        print(f"  threshold={thr}: {results}", flush=True)

    print("\n--- control: Part1's own real silhouette curves must NOT be reclassified ---", flush=True)
    from backend.config import settings
    from backend.geometry.parting_line_v2.contracts import PullDirectionInput
    from backend.geometry.parting_line_v2.track_a import detect_edge_silhouettes
    from backend.geometry.parting_line_v2.track_b import detect_face_silhouettes
    from backend.geometry.step_loader import load_step_cached

    part1 = load_step_cached("data/parts/Part1.stp")
    faces1_by_id = {f.face_id: f for f in part1.faces}
    direction1 = PullDirectionInput(unit((0, 0, 1)), "manual").direction
    bbox_diag1 = proto._bbox_diagonal(part1)
    ta1 = detect_edge_silhouettes(part1, direction1, cfg=cfg, bbox_diagonal_mm=bbox_diag1)
    tb1 = detect_face_silhouettes(part1, direction1, cfg=cfg, bbox_diagonal_mm=bbox_diag1,
                                   start_segment_id=len(ta1.segments))
    silhouette_segs = [s for s in tb1.segments if s.kind == "silhouette"]
    print(f"  Part1 +Z: {len(silhouette_segs)} real silhouette segments", flush=True)
    reclassified = 0
    for seg in silhouette_segs:
        face = faces1_by_id[seg.backing.face_id]
        new_kind = classify_segment_kind(seg, face, direction1, cfg, ratio_threshold=1e-6)
        if new_kind != "silhouette":
            reclassified += 1
            print(f"    UNEXPECTED reclassification: seg {seg.segment_id} face {face.face_id} -> {new_kind}",
                  flush=True)
    print(f"  {reclassified}/{len(silhouette_segs)} real Part1 silhouette segments reclassified "
          f"(expected 0 -- confirms the fix does not disable genuine silhouettes)", flush=True)
    return reclassified == 0


# ============================================================
# Task 7 -- wire the reclassification into the (Mechanism-B-frozen) graph
# construction: a zero_draft_band segment no longer acts as an ordinary
# sign-crossing divider for split-face cut-piece purposes. Region-finding
# itself (`build_face_regions`, the geometric polygon shapes) is NOT
# touched -- only which segments are eligible to become graph edges.
# ============================================================

def build_graph_type2_fixed(part, direction, track_b_segments, silhouette_edge_ids,
                             *, unary_weight, smoothness_weight, silhouette_discount,
                             ratio_threshold: float = 1e-6, face_regions_override=None):
    import backend.validation.parting_line_mechanism_b_fixture as mb
    from shapely.geometry import LineString as _LS

    faces_by_id = {f.face_id: f for f in part.faces if f.normal_valid}

    # Reclassify BEFORE handing segments to the (frozen) Mechanism-B graph
    # builder -- region-finding still sees every segment (untouched);
    # only each segment's OWN `.kind` is replaced where warranted.
    from dataclasses import replace as _replace
    from backend.config import settings as _settings
    cfg = _settings.dfm.parting_line_v2
    reclassified_segments = []
    reclass_log = []
    for seg in track_b_segments:
        from backend.geometry.parting_line_v2.types import FaceBacking
        if isinstance(seg.backing, FaceBacking) and seg.backing.face_id in faces_by_id:
            face = faces_by_id[seg.backing.face_id]
            new_kind = classify_segment_kind(seg, face, direction, cfg, ratio_threshold=ratio_threshold)
            if new_kind != seg.kind:
                reclass_log.append((seg.segment_id, seg.backing.face_id, seg.kind, new_kind))
                seg = _replace(seg, kind=new_kind)
        reclassified_segments.append(seg)

    result = mb.build_graph_fixed(
        part, direction, reclassified_segments, silhouette_edge_ids,
        unary_weight=unary_weight, smoothness_weight=smoothness_weight,
        silhouette_discount=silhouette_discount, face_regions_override=face_regions_override,
    )

    # The split-face cut-piece loop inside build_graph_fixed already only
    # emits a piece if `touches_a and touches_b` for a given segment's own
    # LineString -- we cannot un-emit after the fact without re-deriving,
    # so re-run just that loop here restricted to kind=="silhouette"
    # segments (zero_draft_band excluded), replacing cut_pieces'
    # "face"-kind entries with the corrected set. Edge-kind cut_pieces
    # (Mechanism B's own fix) are untouched.
    face_regions = result["face_regions"]
    cavity_nodes, core_nodes = result["cavity_nodes"], result["core_nodes"]
    track_b_by_face: dict[int, list] = {}
    for seg in reclassified_segments:
        from backend.geometry.parting_line_v2.types import FaceBacking
        if isinstance(seg.backing, FaceBacking):
            track_b_by_face.setdefault(seg.backing.face_id, []).append(seg)

    edge_cut_pieces = [p for p in result["cut_pieces"] if p.get("kind") == "edge"]
    face_cut_pieces = []
    for face_id, regions in face_regions.items():
        if not regions or len(regions) < 2:
            continue
        # build_graph_fixed (Mechanism B, frozen) computes its own
        # face_region_adjacency internally but does not return it --
        # recomputed here (read-only, same `fp.region_adjacency` call it
        # already makes) rather than touching the frozen function.
        adjacency = fp.region_adjacency(regions)
        segs = [s for s in track_b_by_face.get(face_id, []) if s.kind == "silhouette"]
        checked_pairs: set[tuple] = set()
        for ra in adjacency:
            for rb in adjacency[ra]:
                pair_key = tuple(sorted((ra, rb)))
                if pair_key in checked_pairs:
                    continue
                checked_pairs.add(pair_key)
                node_a, node_b = (face_id, ra), (face_id, rb)
                if (node_a in cavity_nodes) == (node_b in cavity_nodes):
                    continue
                region_a = next(r for r in regions if r.region_id == ra)
                region_b = next(r for r in regions if r.region_id == rb)
                for seg in segs:
                    if len(seg.backing.uv) < 2:
                        continue
                    line = _LS(seg.backing.uv)
                    touches_a = region_a.polygon.boundary.intersection(line).length > 0
                    touches_b = region_b.polygon.boundary.intersection(line).length > 0
                    if touches_a and touches_b:
                        face_cut_pieces.append({"kind": "face", "face_id": face_id, "segment": seg})

    result["cut_pieces"] = edge_cut_pieces + face_cut_pieces
    result["split_face_cut_count"] = len(face_cut_pieces)
    result["reclassification_log"] = reclass_log
    return result


if __name__ == "__main__":
    ok = run_classification_correction()
    print(f"\nControl check: {'PASS' if ok else 'FAIL'}")
