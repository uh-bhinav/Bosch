"""
backend/geometry/step_loader.py
--------------------------------
Module 1 of the DfM Agent Geometry Engine.

Responsibility
--------------
Load a STEP B-Rep file, extract every face (with outward normal, surface type,
area, centroid, UV bounds), extract every unique edge (with type, length,
adjacent faces, vertex coords, seam flag), extract every unique vertex, build
the face-adjacency graph, and return a fully populated `PartGeometry`.

This module is the ONLY place that touches the raw OCC/STEP API.  Every
downstream module receives a `PartGeometry` and works through its structured
data — they never call OCC readers or explorers directly.

Pipeline position
-----------------
  [THIS] → draft_analyzer → direction_optimizer + undercut_detector
         → parting_line → core_cavity → AI Agent → Report

Why pythonOCC (not Trimesh / Open3D / cadquery direct import)?
--------------------------------------------------------------
The hackathon provides .stp (STEP ISO 10303) files from Siemens NX.
STEP stores exact analytic + NURBS surfaces (B-Rep), not triangle meshes.
Only OCC can parse them without approximation errors — unacceptable for
mold design where parting line placement requires millimetre accuracy.

Adjacency strategy — why `HashCode` (not IsSame() loop or TopTools_IndexedMap)
-------------------------------------------------------------------------------
We use `TopoDS_Shape.HashCode(HASH_MOD)` to deduplicate topological entities.

Why not a nested IsSame() loop?  O(n²) on faces × edges — too slow for a
500-face part with ~2000 edges.

Why not `TopTools_IndexedDataMapOfShapeListOfShape` + `topexp.MapShapesAndAncestors`?
That API is perfectly correct and we originally planned to use it, but the
module-level `topexp` singleton is not consistently available across pythonOCC
builds (conda-forge 7.7.x vs pip 7.6.x).  The hash approach is compatible
with all OCC versions ≥ 7.4 and is exactly what OCC itself uses internally
in its data structures.

Hash collision risk: with HASH_MOD = 2^31 − 1 and ≤ 5000 edges (typical
automotive cap), birthday-paradox probability ≈ 5000² / (2 × 2^31) ≈ 6×10⁻⁶.
Practically zero.  We also log a warning if any unexpected multi-face edge is
detected (would indicate a collision or genuine non-manifold geometry).

Seam edge detection
-------------------
A seam edge of a periodic surface (full cylinder, sphere, torus) appears TWICE
in the face's wire in OCC — once with FORWARD orientation and once REVERSED —
but both map to the same underlying TShape (same hash).  If we naively count
a seam edge as "shared between 2 faces" we corrupt the adjacency graph.

Detection: when processing a face's edges, if the same edge hash appears more
than once for the SAME face, it is a seam edge.  We then:
  1. Mark `EdgeData.is_seam = True`.
  2. Keep `adjacent_face_ids = [this_face_id]` (1 face, not 2).
  3. Do NOT add it to the adjacency graph (seam edges are NOT face boundaries).

References
----------
* Bassi et al. (2010) — uses face normals for accessibility scoring.
* Sangolli et al. (2021) — uses edge convexity (set later by undercut_detector).
* Nee et al. (1998) — uses silhouette edges (set later by parting_line).
* Hou et al. (2018) — uses edge graph with length/curvature weights.
"""

from __future__ import annotations

import logging
import math
import time
from pathlib import Path
from typing import Optional

# ── pythonOCC imports ─────────────────────────────────────────────────────────
try:
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
    from OCC.Core.BRepBndLib import brepbndlib
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.GeomAbs import (
        # Surface types
        GeomAbs_BSplineSurface,
        GeomAbs_BezierSurface,
        GeomAbs_Cone,
        GeomAbs_Cylinder,
        GeomAbs_OffsetSurface,
        GeomAbs_OtherSurface,
        GeomAbs_Plane,
        GeomAbs_Sphere,
        GeomAbs_SurfaceOfExtrusion,
        GeomAbs_SurfaceOfRevolution,
        GeomAbs_Torus,
        # Curve (edge) types
        GeomAbs_BSplineCurve,
        GeomAbs_BezierCurve,
        GeomAbs_Circle,
        GeomAbs_Ellipse,
        GeomAbs_Hyperbola,
        GeomAbs_Line,
        GeomAbs_OffsetCurve,
        GeomAbs_OtherCurve,
        GeomAbs_Parabola,
    )
    from OCC.Core.GeomLProp import GeomLProp_SLProps
    from OCC.Core.IFSelect import IFSelect_RetDone
    from OCC.Core.STEPControl import STEPControl_Reader
    from OCC.Core.TopAbs import (
        TopAbs_EDGE,
        TopAbs_FACE,
        TopAbs_REVERSED,
        TopAbs_SHELL,
        TopAbs_SOLID,
        TopAbs_VERTEX,
    )
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopoDS import (
        TopoDS_Shape,
        topods,
        topods_Edge,
        topods_Face,
        topods_Vertex,
    )

    _OCC_AVAILABLE = True
except ImportError:
    _OCC_AVAILABLE = False

try:
    import cadquery as cq

    _CADQUERY_AVAILABLE = True
except ImportError:
    cq = None  # type: ignore[assignment]
    _CADQUERY_AVAILABLE = False

from backend.models.geometry_models import (
    BoundingBox,
    EdgeData,
    FaceData,
    PartGeometry,
    Vec3,
    VertexData,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Module-level constants
# =============================================================================

#: Hash modulus.  Large prime; used for deduplicating TShape handles.
#: Probability of collision for ≤ 5000 shapes ≈ 6 × 10⁻⁶ (birthday paradox).
_HASH_MOD: int = 2**31 - 1

#: UV parameter values beyond this are treated as unbounded (clamp to ±1).
_PARAM_LIMIT: float = 1e6

#: Surface type enum → human-readable string.
_SURFACE_TYPE_MAP: dict = {}

#: Curve (edge) type enum → human-readable string.
_CURVE_TYPE_MAP: dict = {}

if _OCC_AVAILABLE:
    _SURFACE_TYPE_MAP = {
        GeomAbs_Plane: "Plane",
        GeomAbs_Cylinder: "Cylinder",
        GeomAbs_Cone: "Cone",
        GeomAbs_Sphere: "Sphere",
        GeomAbs_Torus: "Torus",
        GeomAbs_BezierSurface: "Bezier",
        GeomAbs_BSplineSurface: "BSpline/NURBS",
        GeomAbs_SurfaceOfRevolution: "Revolution",
        GeomAbs_SurfaceOfExtrusion: "Extrusion",
        GeomAbs_OffsetSurface: "Offset",
        GeomAbs_OtherSurface: "Other",
    }
    _CURVE_TYPE_MAP = {
        GeomAbs_Line: "Line",
        GeomAbs_Circle: "Circle",
        GeomAbs_Ellipse: "Ellipse",
        GeomAbs_Hyperbola: "Hyperbola",
        GeomAbs_Parabola: "Parabola",
        GeomAbs_BezierCurve: "Bezier",
        GeomAbs_BSplineCurve: "BSpline",
        GeomAbs_OffsetCurve: "Offset",
        GeomAbs_OtherCurve: "Other",
    }


# =============================================================================
# Custom exceptions
# =============================================================================

class STEPLoadError(Exception):
    """Raised when the STEP file cannot be parsed or yields no valid shapes."""


# =============================================================================
# Guard
# =============================================================================

def _require_occ() -> None:
    if not _OCC_AVAILABLE:
        raise ImportError(
            "pythonOCC (pythonocc-core) is required but not installed.\n"
            "Install via conda:  conda install -c conda-forge pythonocc-core\n"
            "Pip builds are unreliable — conda is strongly recommended."
        )


def _as_face(shape: object) -> object:
    """Cast to TopoDS_Face without pythonOCC 7.7+ deprecation warnings."""
    if hasattr(topods, "Face"):
        return topods.Face(shape)
    return topods_Face(shape)


def _as_edge(shape: object) -> object:
    """Cast to TopoDS_Edge without pythonOCC 7.7+ deprecation warnings."""
    if hasattr(topods, "Edge"):
        return topods.Edge(shape)
    return topods_Edge(shape)


def _as_vertex(shape: object) -> object:
    """Cast to TopoDS_Vertex without pythonOCC 7.7+ deprecation warnings."""
    if hasattr(topods, "Vertex"):
        return topods.Vertex(shape)
    return topods_Vertex(shape)


def _load_cadquery_part(filepath: Path, warnings: list[str]) -> Optional[object]:
    """
    Load the STEP file through CadQuery for future high-level CAD operations.

    pythonOCC remains the source of truth for exact STEP parsing and topology
    extraction.  CadQuery uses the separate OCP binding, so pythonOCC
    `TopoDS_Shape` objects cannot be safely cast into CadQuery shapes.  We load
    the STEP file independently here and store the CadQuery object only as an
    optional convenience handle for later feature work.
    """
    if not _CADQUERY_AVAILABLE or cq is None:
        warnings.append(
            "CadQuery is not installed in this runtime; cadquery_shape is None. "
            "Install the locked conda/Docker environment for full stack support."
        )
        return None

    try:
        return cq.importers.importStep(str(filepath))
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"CadQuery STEP import failed: {exc}")
        logger.warning("CadQuery STEP import failed: %s", exc)
        return None


# =============================================================================
# Bounding box
# =============================================================================

def _compute_bounding_box(shape: "TopoDS_Shape") -> BoundingBox:
    """
    Exact AABB using OCC's BRepBndLib.

    `brepbndlib.Add` uses the exact parametric surfaces — no meshing.
    This gives the true bounding box (not an approximation), which is
    critical for the Bassi sweep distance = diagonal × multiplier.
    """
    bbox = Bnd_Box()
    brepbndlib.Add(shape, bbox)
    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
    return BoundingBox(
        xmin=xmin, ymin=ymin, zmin=zmin,
        xmax=xmax, ymax=ymax, zmax=zmax,
    )


# =============================================================================
# Topology counts  (raw, before deduplication)
# =============================================================================

def _count_topology_raw(shape: "TopoDS_Shape") -> dict[str, int]:
    """
    Count topology entity occurrences using TopExp_Explorer.

    IMPORTANT: These are RAW counts, NOT unique counts.
    For edges and vertices, they include duplicates (seam edges appear twice,
    shared vertices appear once per face that contains them).

    The UNIQUE counts are computed by the hash-deduplication functions below
    and stored directly in PartGeometry.edge_count / .vertex_count.

    We keep raw counts here only for logging and diagnostic comparison.
    """
    counts: dict[str, int] = {}
    for topo_type, key in [
        (TopAbs_SOLID,  "solid_count"),
        (TopAbs_SHELL,  "shell_count"),
        (TopAbs_FACE,   "face_count"),
        (TopAbs_EDGE,   "edge_count_raw"),
        (TopAbs_VERTEX, "vertex_count_raw"),
    ]:
        exp = TopExp_Explorer(shape, topo_type)
        n = 0
        while exp.More():
            n += 1
            exp.Next()
        counts[key] = n
    return counts


# =============================================================================
# Face extraction (normals, surface types, areas, centroids)
# =============================================================================

def _clamp_uv(
    umin: float, umax: float, vmin: float, vmax: float
) -> tuple[float, float, float, float]:
    """
    Clamp unbounded UV ranges to ±1.

    Open cylinders, extrusions, and some NURBS can have UV ranges of ±1e100.
    Evaluating the surface at those extremes overflows or produces garbage.
    Clamping to ±1 puts the evaluation point near the surface origin, which
    is always a valid, well-conditioned point.
    """
    if abs(umin) > _PARAM_LIMIT or abs(umax) > _PARAM_LIMIT:
        umin, umax = -1.0, 1.0
    if abs(vmin) > _PARAM_LIMIT or abs(vmax) > _PARAM_LIMIT:
        vmin, vmax = -1.0, 1.0
    return umin, umax, vmin, vmax


def _compute_face_normal_and_centroid(
    face: "topods_Face",
    adaptor: "BRepAdaptor_Surface",
) -> tuple[Vec3, Vec3, bool]:
    """
    Evaluate the outward unit normal and 3-D centroid of a face.

    Algorithm
    ---------
    1. Compute UV centroid (midpoint of clamped parametric bounds).
    2. Evaluate surface at (u_mid, v_mid) via GeomLProp_SLProps (first
       derivatives → implicit normal via cross-product).
    3. Apply face orientation: REVERSED faces have their surface normal
       pointing inward — we flip it to get the outward direction.
    4. Re-normalise (defensive — should be unit already).

    The resulting normal is the OUTWARD normal: pointing away from the solid
    interior, towards the mold cavity.  This is the sign convention used by:
    • Bassi 2010:  n · d > 0 → cavity side; n · d < 0 → core side.
    • Nee 1998:    silhouette when n · d changes sign across an edge.
    • Core/cavity: classify face by sign of n · d.

    Returns (normal, centroid, is_valid).
    """
    umin = adaptor.FirstUParameter()
    umax = adaptor.LastUParameter()
    vmin = adaptor.FirstVParameter()
    vmax = adaptor.LastVParameter()
    umin, umax, vmin, vmax = _clamp_uv(umin, umax, vmin, vmax)
    umid = (umin + umax) / 2.0
    vmid = (vmin + vmax) / 2.0

    try:
        surface = BRep_Tool.Surface(face)
        slprops = GeomLProp_SLProps(surface, umid, vmid, 1, 1e-9)

        if not slprops.IsNormalDefined():
            logger.debug("Normal undefined at UV=(%.4f, %.4f) — degenerate.", umid, vmid)
            return (0.0, 0.0, 1.0), (0.0, 0.0, 0.0), False

        n = slprops.Normal()
        p = slprops.Value()
        nx, ny, nz = n.X(), n.Y(), n.Z()
        cx, cy, cz = p.X(), p.Y(), p.Z()

        if face.Orientation() == TopAbs_REVERSED:
            nx, ny, nz = -nx, -ny, -nz

        mag = math.sqrt(nx * nx + ny * ny + nz * nz)
        if mag < 1e-12:
            return (0.0, 0.0, 1.0), (cx, cy, cz), False

        return (nx / mag, ny / mag, nz / mag), (cx, cy, cz), True

    except Exception as exc:  # noqa: BLE001
        logger.debug("Normal computation exception: %s", exc)
        return (0.0, 0.0, 1.0), (0.0, 0.0, 0.0), False


def _compute_face_area(face: "topods_Face") -> float:
    """
    Exact surface area via OCC surface integration.

    `brepgprop.SurfaceProperties` integrates analytically over the exact
    parametric surface — no mesh approximation.
    """
    try:
        props = GProp_GProps()
        brepgprop.SurfaceProperties(face, props)
        return float(props.Mass())
    except Exception as exc:  # noqa: BLE001
        logger.debug("Area computation failed: %s", exc)
        return 0.0


def _extract_all_faces(
    shape: "TopoDS_Shape",
    warnings: list[str],
) -> list[FaceData]:
    """
    Traverse the shape and build a FaceData for every face.

    Face IDs are assigned sequentially in TopExp_Explorer order (0-based).
    The IDs are STABLE for a given .stp file — the same face always gets
    the same ID regardless of how many times you load the file.

    Error handling: if a face throws during extraction, we insert a
    placeholder with `normal_valid=False` so face IDs remain consistent
    with the topology count.  Downstream modules skip invalid faces via the
    `face.normal_valid` check.
    """
    faces: list[FaceData] = []
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    face_id = 0
    error_count = 0

    while exp.More():
        raw = exp.Current()
        face = _as_face(raw)

        try:
            adaptor = BRepAdaptor_Surface(face)
            stype = _SURFACE_TYPE_MAP.get(adaptor.GetType(), "Unknown")

            umin = adaptor.FirstUParameter()
            umax = adaptor.LastUParameter()
            vmin = adaptor.FirstVParameter()
            vmax = adaptor.LastVParameter()
            umin_c, umax_c, vmin_c, vmax_c = _clamp_uv(umin, umax, vmin, vmax)

            normal, centroid, valid = _compute_face_normal_and_centroid(face, adaptor)
            area = _compute_face_area(face)
            is_rev = (face.Orientation() == TopAbs_REVERSED)

            faces.append(FaceData(
                face_id=face_id,
                occ_face=face,
                surface_type=stype,
                normal=normal,
                centroid=centroid,
                area=area,
                u_range=(umin_c, umax_c),
                v_range=(vmin_c, vmax_c),
                is_reversed=is_rev,
                normal_valid=valid,
            ))

        except Exception as exc:  # noqa: BLE001
            logger.warning("Face %d extraction error: %s", face_id, exc)
            error_count += 1
            faces.append(FaceData(
                face_id=face_id,
                occ_face=face,
                surface_type="Error",
                normal=(0.0, 0.0, 1.0),
                centroid=(0.0, 0.0, 0.0),
                area=0.0,
                u_range=(0.0, 1.0),
                v_range=(0.0, 1.0),
                is_reversed=False,
                normal_valid=False,
            ))

        face_id += 1
        exp.Next()

    if error_count:
        warnings.append(
            f"{error_count} face(s) failed extraction; replaced with placeholder "
            "(normal_valid=False). See debug logs."
        )
    return faces


# =============================================================================
# Edge extraction + adjacency graph builder
# =============================================================================

def _get_edge_geometry(
    edge: "topods_Edge",
) -> tuple[str, float, Optional[Vec3], Optional[Vec3]]:
    """
    Extract edge type, arc-length, and endpoint coordinates.

    Returns
    -------
    edge_type   : human-readable curve type string
    length      : arc length in mm (exact via OCC linear integration)
    start_vtx   : (x, y, z) of first endpoint, or None for closed curves
    end_vtx     : (x, y, z) of last endpoint, or None for closed curves

    Endpoint ordering
    -----------------
    We use TopExp_Explorer(edge, TopAbs_VERTEX) to get the vertices.
    For an open edge (line, arc), this yields exactly 2 vertices.
    For a full closed curve (complete circle, closed spline), it yields 0 or 1.
    We store the first as start_vtx and last as end_vtx.
    """
    # ── Type ────────────────────────────────────────────────────────────
    try:
        adaptor = BRepAdaptor_Curve(edge)
        edge_type = _CURVE_TYPE_MAP.get(adaptor.GetType(), "Unknown")
    except Exception:  # noqa: BLE001
        edge_type = "Unknown"

    # ── Length ──────────────────────────────────────────────────────────
    try:
        props = GProp_GProps()
        brepgprop.LinearProperties(edge, props)
        length = float(props.Mass())
    except Exception:  # noqa: BLE001
        length = 0.0

    # ── Endpoint vertices ────────────────────────────────────────────────
    # We use TopExp_Explorer(edge, TopAbs_VERTEX) — works across all OCC versions.
    # Do NOT rely on TopExp.FirstVertex / LastVertex which have inconsistent
    # Python bindings across conda-forge builds.
    start_vtx: Optional[Vec3] = None
    end_vtx: Optional[Vec3] = None
    try:
        vexp = TopExp_Explorer(edge, TopAbs_VERTEX)
        vertex_coords: list[Vec3] = []
        seen_v_hashes: set[int] = set()
        while vexp.More():
            v = _as_vertex(vexp.Current())
            h = v.HashCode(_HASH_MOD)
            if h not in seen_v_hashes:
                seen_v_hashes.add(h)
                pnt = BRep_Tool.Pnt(v)
                vertex_coords.append((pnt.X(), pnt.Y(), pnt.Z()))
            vexp.Next()
        if len(vertex_coords) >= 1:
            start_vtx = vertex_coords[0]
        if len(vertex_coords) >= 2:
            end_vtx = vertex_coords[-1]
    except Exception:  # noqa: BLE001
        pass

    return edge_type, length, start_vtx, end_vtx


def _extract_edges_and_build_adjacency(
    shape: "TopoDS_Shape",
    faces: list[FaceData],
    warnings: list[str],
) -> tuple[
    list[EdgeData],
    dict[int, list[int]],   # face_adjacency
    dict[int, list[int]],   # face_to_edges
    dict[int, list[int]],   # edge_to_faces
]:
    """
    Build every unique EdgeData and all three adjacency maps.

    Algorithm (two-pass)
    --------------------
    Pass 1 — Iterate every face's edges.
        For each edge encountered:
        • Hash the TShape pointer → unique edge identifier.
        • If first encounter: allocate new edge_id, store OCC handle.
        • Accumulate face_ids for this edge (with deduplication).
        • Track if edge appears TWICE within the SAME face → seam edge.
        • Accumulate edge_ids for this face.

    Pass 2 — Build EdgeData objects.
        For each unique edge hash:
        • Call _get_edge_geometry() for type/length/vertices.
        • Determine is_seam from the seam hash set.
        • Build EdgeData.

    Pass 3 — Build face adjacency.
        For each non-seam manifold edge (2 adjacent faces):
        • Add bidirectional entries in face_adjacency.

    Seam edge handling
    ------------------
    A seam edge (e.g. the longitude line of a full cylinder) appears in
    a single face's wire in BOTH FORWARD and REVERSED orientation.
    Without special handling, its hash would appear twice in the face's
    edge list with the same face_id, making it look like it belongs to
    two different faces — corrupting the adjacency graph.

    We detect seam edges by checking if the same hash appears more than
    once for the same face_id in the raw (non-deduped) tracking list.
    Seam edges get adjacent_face_ids = [single_face_id] and are NOT added
    to the face adjacency graph.
    """
    # ── Pass 1: iterate faces' edges ─────────────────────────────────────
    # edge_hash → list of face_ids (WITH duplicates, for seam detection)
    _eh_to_fids_raw: dict[int, list[int]] = {}
    # edge_hash → list of face_ids (DEDUPED, for adjacency)
    _eh_to_fids: dict[int, list[int]] = {}
    # edge_hash → first-encountered OCC edge handle
    _eh_to_occ: dict[int, "topods_Edge"] = {}
    # edge_hash → assigned edge_id
    _eh_to_eid: dict[int, int] = {}
    # face_id → list of edge_ids (deduped)
    _fid_to_eids: dict[int, list[int]] = {fd.face_id: [] for fd in faces}

    edge_id_counter = 0

    for fd in faces:
        exp = TopExp_Explorer(fd.occ_face, TopAbs_EDGE)
        while exp.More():
            raw = exp.Current()
            edge = _as_edge(raw)
            h = edge.HashCode(_HASH_MOD)

            # Raw tracking (WITH duplicates per face — needed for seam detection)
            if h not in _eh_to_fids_raw:
                _eh_to_fids_raw[h] = []
            _eh_to_fids_raw[h].append(fd.face_id)

            # First time we see this edge?
            if h not in _eh_to_eid:
                _eh_to_eid[h] = edge_id_counter
                _eh_to_occ[h] = edge
                _eh_to_fids[h] = []
                edge_id_counter += 1

            eid = _eh_to_eid[h]

            # Deduplicated face tracking
            if fd.face_id not in _eh_to_fids[h]:
                _eh_to_fids[h].append(fd.face_id)

            # Deduplicated edge tracking per face
            if eid not in _fid_to_eids[fd.face_id]:
                _fid_to_eids[fd.face_id].append(eid)

            exp.Next()

    # ── Identify seam edges ──────────────────────────────────────────────
    # A hash is a seam if the same face_id appears >1× in the raw list.
    seam_hashes: set[int] = set()
    for h, raw_fids in _eh_to_fids_raw.items():
        if len(raw_fids) != len(set(raw_fids)):
            seam_hashes.add(h)

    # ── Pass 2: build EdgeData objects ───────────────────────────────────
    edges: list[EdgeData] = []
    edge_to_faces_map: dict[int, list[int]] = {}

    for h, eid in sorted(_eh_to_eid.items(), key=lambda kv: kv[1]):
        occ_edge = _eh_to_occ[h]
        adj_fids = _eh_to_fids[h]
        is_seam = (h in seam_hashes)

        etype, length, sv, ev = _get_edge_geometry(occ_edge)

        edges.append(EdgeData(
            edge_id=eid,
            occ_edge=occ_edge,
            edge_type=etype,
            length=length,
            adjacent_face_ids=adj_fids,
            start_vertex=sv,
            end_vertex=ev,
            is_seam=is_seam,
        ))
        edge_to_faces_map[eid] = adj_fids

    # ── Pass 3: build face adjacency (skip seams, skip boundary) ─────────
    face_adjacency: dict[int, list[int]] = {fd.face_id: [] for fd in faces}

    for ed in edges:
        if ed.is_seam:
            continue  # seam edges are NOT face-to-face boundaries
        if len(ed.adjacent_face_ids) != 2:
            continue  # boundary edge or non-manifold — not a face-boundary

        f1, f2 = ed.adjacent_face_ids[0], ed.adjacent_face_ids[1]
        if f2 not in face_adjacency[f1]:
            face_adjacency[f1].append(f2)
        if f1 not in face_adjacency[f2]:
            face_adjacency[f2].append(f1)

    # ── Sanity checks ─────────────────────────────────────────────────────
    non_manifold = [e for e in edges if len(e.adjacent_face_ids) > 2]
    if non_manifold:
        warnings.append(
            f"{len(non_manifold)} non-manifold edge(s) detected "
            f"(3+ adjacent faces). IDs: {[e.edge_id for e in non_manifold[:5]]}. "
            "This indicates a geometry error that may affect algorithm accuracy."
        )
        logger.warning("%d non-manifold edges found.", len(non_manifold))

    isolated = [fid for fid, nbrs in face_adjacency.items() if len(nbrs) == 0]
    if isolated:
        warnings.append(
            f"{len(isolated)} isolated face(s) with no adjacent neighbours. "
            f"Face IDs: {isolated[:10]}."
        )

    logger.info(
        "Edges: %d unique  |  boundary=%d  manifold=%d  seam=%d  non-manifold=%d",
        len(edges),
        sum(1 for e in edges if e.is_boundary),
        sum(1 for e in edges if e.is_manifold),
        sum(1 for e in edges if e.is_seam),
        len(non_manifold),
    )

    return edges, face_adjacency, _fid_to_eids, edge_to_faces_map


# =============================================================================
# Vertex extraction
# =============================================================================

def _extract_vertices(
    shape: "TopoDS_Shape",
    warnings: list[str],
) -> list[VertexData]:
    """
    Extract every UNIQUE vertex from the shape with its 3-D coordinates.

    Deduplication is by TShape hash.  The resulting list has exactly one
    entry per unique geometric point in the model.

    Note: TopExp_Explorer(shape, TopAbs_VERTEX) visits vertices multiple
    times (once for each edge/face that contains them).  Without the hash
    deduplication, vertex_count would be inflated ~4–6× for a typical part.
    """
    seen_hashes: set[int] = set()
    vertices: list[VertexData] = []
    vertex_id = 0
    error_count = 0

    exp = TopExp_Explorer(shape, TopAbs_VERTEX)
    while exp.More():
        raw = exp.Current()
        vertex = _as_vertex(raw)
        h = vertex.HashCode(_HASH_MOD)

        if h not in seen_hashes:
            seen_hashes.add(h)
            try:
                pnt = BRep_Tool.Pnt(vertex)
                coords: Vec3 = (pnt.X(), pnt.Y(), pnt.Z())
            except Exception:  # noqa: BLE001
                coords = (0.0, 0.0, 0.0)
                error_count += 1

            vertices.append(VertexData(
                vertex_id=vertex_id,
                occ_vertex=vertex,
                coordinates=coords,
            ))
            vertex_id += 1

        exp.Next()

    if error_count:
        warnings.append(f"{error_count} vertex coordinate extraction(s) failed.")

    return vertices


# =============================================================================
# Public API
# =============================================================================

def load_step(filepath: "str | Path") -> PartGeometry:
    """
    Load a STEP file and return a fully populated ``PartGeometry``.

    This is the SINGLE entry point for all downstream DfM analysis.
    Every other module takes a ``PartGeometry`` as input.

    What it builds
    --------------
    1. OCC shape (live handle for all downstream Boolean/sweep ops).
    2. Bounding box (exact, no mesh approximation).
    3. Face list with outward normals, surface types, areas, centroids.
    4. Edge list with types, lengths, endpoint coords, seam flags.
    5. Vertex list with unique 3-D coordinates.
    6. Adjacency maps: face↔face, face→edges, edge→faces.

    Parameters
    ----------
    filepath : str or Path
        Path to the ``.stp`` or ``.step`` file.

    Returns
    -------
    PartGeometry
        Fully populated.  Ready for draft_analyzer (Module 2).

    Raises
    ------
    FileNotFoundError  : File not found on disk.
    STEPLoadError      : OCC parse failure or no valid solid in file.
    ImportError        : pythonocc-core not installed.
    """
    _require_occ()

    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"STEP file not found: {path.resolve()}")

    if path.suffix.lower() not in {".stp", ".step"}:
        logger.warning("Extension '%s' is not .stp/.step — attempting anyway.", path.suffix)

    t_start = time.perf_counter()
    sep = "─" * 65
    logger.info(sep)
    logger.info("DfM Agent — Loading STEP: %s", path.name)
    warnings: list[str] = []

    # ── 1. Parse STEP ─────────────────────────────────────────────────────
    reader = STEPControl_Reader()
    status = reader.ReadFile(str(path))
    if status != IFSelect_RetDone:
        raise STEPLoadError(
            f"STEPControl_Reader.ReadFile() failed on '{path}' (status={status}). "
            "File may be corrupt, empty, or not valid STEP."
        )

    n_roots = reader.NbRootsForTransfer()
    logger.info("Roots for transfer: %d", n_roots)
    reader.TransferRoots()

    shape: TopoDS_Shape = reader.OneShape()
    if shape is None or shape.IsNull():
        raise STEPLoadError(
            f"No valid TopoDS shapes after transfer in '{path}'. "
            "File may contain only annotations or no solid bodies."
        )

    # ── 2. Bounding box ───────────────────────────────────────────────────
    bbox = _compute_bounding_box(shape)
    logger.info(
        "Bbox: X[%.2f→%.2f]  Y[%.2f→%.2f]  Z[%.2f→%.2f]  diag=%.2f mm",
        bbox.xmin, bbox.xmax, bbox.ymin, bbox.ymax, bbox.zmin, bbox.zmax, bbox.diagonal,
    )

    # ── 3. Raw topology counts ────────────────────────────────────────────
    raw = _count_topology_raw(shape)
    logger.info(
        "Raw topology — solids:%d shells:%d faces:%d edges(raw):%d vertices(raw):%d",
        raw["solid_count"], raw["shell_count"], raw["face_count"],
        raw["edge_count_raw"], raw["vertex_count_raw"],
    )

    if raw["face_count"] == 0:
        raise STEPLoadError(
            "Shape has 0 faces — may be a wireframe or annotation entity only."
        )
    if raw["solid_count"] > 1:
        warnings.append(
            f"Part has {raw['solid_count']} solids. DfM analysis treats the "
            "compound as one part. Consider analysing each solid separately."
        )

    # ── 4. Extract faces ──────────────────────────────────────────────────
    logger.info("Step 4/7 — Extracting face data …")
    t4 = time.perf_counter()
    faces = _extract_all_faces(shape, warnings)
    logger.info("  %d faces extracted in %.2f s.", len(faces), time.perf_counter() - t4)

    invalid_normals = sum(1 for f in faces if not f.normal_valid)
    if invalid_normals:
        warnings.append(
            f"{invalid_normals}/{len(faces)} faces have invalid normals "
            "(degenerate geometry). Excluded from draft/undercut analysis."
        )

    surface_type_counts: dict[str, int] = {}
    for fd in faces:
        surface_type_counts[fd.surface_type] = (
            surface_type_counts.get(fd.surface_type, 0) + 1
        )
    logger.info("  Surface types: %s", surface_type_counts)

    # ── 5. Extract edges + adjacency ──────────────────────────────────────
    logger.info("Step 5/7 — Building edge list and adjacency graph …")
    t5 = time.perf_counter()
    edges, face_adj, face_to_edges, edge_to_faces = _extract_edges_and_build_adjacency(
        shape, faces, warnings
    )
    logger.info(
        "  %d unique edges, adjacency built in %.2f s.",
        len(edges), time.perf_counter() - t5,
    )

    edge_type_counts: dict[str, int] = {}
    for ed in edges:
        edge_type_counts[ed.edge_type] = edge_type_counts.get(ed.edge_type, 0) + 1
    logger.info("  Edge types: %s", edge_type_counts)

    # ── 6. Extract vertices ───────────────────────────────────────────────
    logger.info("Step 6/7 — Extracting unique vertices …")
    t6 = time.perf_counter()
    vertices = _extract_vertices(shape, warnings)
    logger.info(
        "  %d unique vertices (raw was %d) in %.2f s.",
        len(vertices), raw["vertex_count_raw"], time.perf_counter() - t6,
    )

    # ── 7. Assemble PartGeometry ──────────────────────────────────────────
    cadquery_shape = _load_cadquery_part(path, warnings)
    load_time = time.perf_counter() - t_start
    logger.info("Step 7/7 — Assembly complete in %.3f s total.", load_time)
    logger.info(sep)

    return PartGeometry(
        source_file=str(path.resolve()),
        occ_shape=shape,
        faces=faces,
        bounding_box=bbox,
        cadquery_shape=cadquery_shape,
        # Use UNIQUE counts (after deduplication), not raw counts:
        face_count=len(faces),
        edge_count=len(edges),
        vertex_count=len(vertices),
        solid_count=raw["solid_count"],
        shell_count=raw["shell_count"],
        edges=edges,
        vertices=vertices,
        face_adjacency=face_adj,
        face_to_edges=face_to_edges,
        edge_to_faces=edge_to_faces,
        load_time_s=load_time,
        warnings=warnings,
        surface_type_counts=surface_type_counts,
        edge_type_counts=edge_type_counts,
    )


def load_step_with_fallback(
    filepath: "str | Path",
    strict: bool = False,
) -> Optional[PartGeometry]:
    """
    Like `load_step` but catches all errors and returns None on failure.

    Useful for batch processing or the AI Agent orchestration loop where a
    single bad file should not crash the whole session.

    Parameters
    ----------
    strict : bool
        If True, re-raises exceptions (same behaviour as `load_step`).
    """
    try:
        return load_step(filepath)
    except (FileNotFoundError, STEPLoadError, ImportError) as exc:
        if strict:
            raise
        logger.error("Could not load '%s': %s", filepath, exc)
        return None


# =============================================================================
# CLI entry point
# =============================================================================

if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )

    if len(sys.argv) < 2:
        print("Usage: python step_loader.py <path/to/file.stp> [--json] [--edges] [--vertices]")
        sys.exit(1)

    stp_path = sys.argv[1]
    part = load_step(stp_path)
    print(part.summary())

    if "--json" in sys.argv:
        out_path = Path(stp_path).with_suffix(".geometry.json")
        include_e = "--edges" in sys.argv
        include_v = "--vertices" in sys.argv
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(
                part.to_dict(
                    include_faces=True,
                    include_edges=include_e,
                    include_vertices=include_v,
                ),
                fh,
                indent=2,
            )
        print(f"\nJSON saved → {out_path}")
