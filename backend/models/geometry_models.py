"""
backend/models/geometry_models.py
----------------------------------
Shared data models for the entire DfM Agent geometry pipeline.

Design decisions
----------------
* `FaceData` holds the live OCC `TopoDS_Face` handle (required for all OCC
  operations downstream) PLUS all scalar fields that are JSON-serialisable.
* `EdgeData` holds the live `TopoDS_Edge` handle plus geometry (type, length,
  adjacent face IDs, vertex coordinates, seam flag).  Critically, it stores
  the two adjacent face IDs needed by Nee (silhouette detection), Sangolli
  (convexity), and Hou (graph weights).
* `VertexData` holds unique vertex coordinates (deduplicated by TShape hash).
* `PartGeometry` is the single output of `step_loader.load_step()` and the
  single input to every downstream module.  It is the "shared state" that
  flows through the pipeline and gets progressively enriched.
* Three adjacency maps live on `PartGeometry`:
    face_adjacency  dict[face_id  → list[face_id]]   — face graph
    face_to_edges   dict[face_id  → list[edge_id]]   — face → its edges
    edge_to_faces   dict[edge_id  → list[face_id]]   — edge → its 1 or 2 faces
* `to_dict()` methods strip all OCC objects so every module can safely
  serialise results for the API / frontend / report.
* Dataclasses (not Pydantic) are used here because `TopoDS_*` are C-extension
  objects that Pydantic cannot validate.  Pydantic is used at the API boundary.

Module dependencies
-------------------
This file has ZERO imports from the rest of the backend — it is the foundation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from OCC.Core.TopoDS import TopoDS_Edge, TopoDS_Face, TopoDS_Shape, TopoDS_Vertex


# =============================================================================
# Type aliases
# =============================================================================

Vec3 = tuple[float, float, float]   # (x, y, z) — always in mm
UVRange = tuple[float, float]        # (min, max) parametric range


# =============================================================================
# Primitive geometry helpers
# =============================================================================

def dot3(a: Vec3, b: Vec3) -> float:
    """Dot product of two 3-D vectors."""
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def normalize3(v: Vec3) -> Vec3:
    """
    Return unit vector.  Raises ValueError if magnitude is below 1e-12.

    Used to clean up normals after orientation flip.
    """
    mag = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    if mag < 1e-12:
        raise ValueError(f"Cannot normalise zero vector: {v}")
    return (v[0] / mag, v[1] / mag, v[2] / mag)


def cross3(a: Vec3, b: Vec3) -> Vec3:
    """Cross product of two 3-D vectors."""
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def mag3(v: Vec3) -> float:
    return math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)


# =============================================================================
# BoundingBox
# =============================================================================

@dataclass
class BoundingBox:
    """
    Axis-aligned bounding box (AABB) of the part or a single face.

    All values are in model units — automotive STEP files are always mm.
    The `diagonal` is the space diagonal used as the sweep distance in the
    Bassi 2010 accessibility algorithm (sweep_dist = diagonal × multiplier).
    """

    xmin: float
    ymin: float
    zmin: float
    xmax: float
    ymax: float
    zmax: float

    @property
    def diagonal(self) -> float:
        """Length of the space diagonal."""
        return math.sqrt(
            (self.xmax - self.xmin) ** 2
            + (self.ymax - self.ymin) ** 2
            + (self.zmax - self.zmin) ** 2
        )

    @property
    def center(self) -> Vec3:
        return (
            (self.xmin + self.xmax) / 2.0,
            (self.ymin + self.ymax) / 2.0,
            (self.zmin + self.zmax) / 2.0,
        )

    @property
    def dimensions(self) -> Vec3:
        """(ΔX, ΔY, ΔZ)."""
        return (
            self.xmax - self.xmin,
            self.ymax - self.ymin,
            self.zmax - self.zmin,
        )

    @property
    def max_dimension(self) -> float:
        return max(self.dimensions)

    def to_dict(self) -> dict:
        return {
            "xmin": round(self.xmin, 4),
            "ymin": round(self.ymin, 4),
            "zmin": round(self.zmin, 4),
            "xmax": round(self.xmax, 4),
            "ymax": round(self.ymax, 4),
            "zmax": round(self.zmax, 4),
            "diagonal_mm": round(self.diagonal, 4),
            "center_mm": [round(c, 4) for c in self.center],
            "dimensions_mm": [round(d, 4) for d in self.dimensions],
        }


# =============================================================================
# VertexData
# =============================================================================

@dataclass
class VertexData:
    """
    A unique 3-D vertex in the B-Rep topology.

    Vertices are deduplicated by TShape hash in the loader, so each unique
    physical point in the model appears exactly once.

    Fields
    ------
    vertex_id     : 0-based sequential index (order of first encounter).
    occ_vertex    : Live `TopoDS_Vertex` handle for downstream OCC ops.
    coordinates   : (x, y, z) in mm.
    """

    vertex_id: int
    occ_vertex: "TopoDS_Vertex"
    coordinates: Vec3

    def to_dict(self) -> dict:
        return {
            "vertex_id": self.vertex_id,
            "coordinates": [round(c, 4) for c in self.coordinates],
        }


# =============================================================================
# EdgeData
# =============================================================================

@dataclass
class EdgeData:
    """
    A unique topological edge in the B-Rep, with full geometry.

    Edges are deduplicated by TShape hash in the loader.  The `adjacent_face_ids`
    field is the critical output — it powers every downstream algorithm:

    * Nee 1998 (parting line):
        silhouette edge ↔ n1·d and n2·d have opposite signs.
        Requires adjacent_face_ids to know which two faces share this edge.

    * Sangolli 2021 (undercut recognition):
        `convexity` (convex/concave) classifies whether the edge is an
        "outside" corner or "inside" pocket — directly maps to undercut risk.

    * Hou 2018 (graph-based refinement):
        Edge becomes a graph node with weight based on length, curvature,
        flatness, and proximity to critical regions.

    Fields
    ------
    edge_id           : 0-based, stable within a loaded part.
    occ_edge          : Live `TopoDS_Edge` handle.
    edge_type         : "Line" | "Circle" | "Ellipse" | "BSpline" | "Bezier" |
                        "Parabola" | "Hyperbola" | "Offset" | "Other".
    length            : Arc length in mm (exact via OCC surface integration).
    adjacent_face_ids : 1 face → boundary edge.  2 faces → manifold interior.
                        3+ faces → non-manifold (unexpected for injection parts).
    start_vertex      : 3-D coords of first endpoint (or None for closed curves).
    end_vertex        : 3-D coords of second endpoint.
    is_seam           : True for the longitudinal seam of periodic surfaces
                        (e.g. full cylinders, spheres).  These edges have only
                        1 unique adjacent face but appear twice in its wire.
    convexity         : "convex" | "concave" | "tangent" | None.
                        None until undercut_detector.py populates it (Module 3).
                        Convex = outside corner (solid projects outward).
                        Concave = inside corner (pocket / undercut risk).
    is_silhouette     : None until parting_line.py populates it (Module 4).
                        True when adjacent face normals straddle the pull direction.
    is_parting_edge   : None until parting_line.py selects the parting loop.
    """

    edge_id: int
    occ_edge: "TopoDS_Edge"
    edge_type: str
    length: float
    adjacent_face_ids: list[int]
    start_vertex: Optional[Vec3]
    end_vertex: Optional[Vec3]
    is_seam: bool

    # Populated by downstream modules:
    convexity: Optional[str] = None       # Module 3: undercut_detector
    is_silhouette: Optional[bool] = None  # Module 4: parting_line
    is_parting_edge: Optional[bool] = None  # Module 4: parting_line

    # ── Convenience ───────────────────────────────────────────────────────
    @property
    def is_boundary(self) -> bool:
        """True for outer rim edges (only one adjacent face)."""
        return len(self.adjacent_face_ids) == 1

    @property
    def is_manifold(self) -> bool:
        """True for normal interior edges (exactly two adjacent faces)."""
        return len(self.adjacent_face_ids) == 2

    @property
    def is_closed(self) -> bool:
        """True for circles and full closed curves (no distinct endpoints)."""
        return self.start_vertex is None and self.end_vertex is None

    def to_dict(self) -> dict:
        d: dict = {
            "edge_id": self.edge_id,
            "edge_type": self.edge_type,
            "length_mm": round(self.length, 4),
            "adjacent_face_ids": self.adjacent_face_ids,
            "is_seam": self.is_seam,
            "is_boundary": self.is_boundary,
            "is_manifold": self.is_manifold,
        }
        if self.start_vertex is not None:
            d["start_vertex"] = [round(c, 4) for c in self.start_vertex]
        if self.end_vertex is not None:
            d["end_vertex"] = [round(c, 4) for c in self.end_vertex]
        if self.convexity is not None:
            d["convexity"] = self.convexity
        if self.is_silhouette is not None:
            d["is_silhouette"] = self.is_silhouette
        if self.is_parting_edge is not None:
            d["is_parting_edge"] = self.is_parting_edge
        return d


# =============================================================================
# FaceData
# =============================================================================

@dataclass
class FaceData:
    """
    All geometry data for one face in the STEP solid.

    The `occ_face` field is the live pythonOCC handle required for all
    downstream OCC operations (sweeping, Boolean, normal re-evaluation at
    non-centroid UV points).  Never include it in JSON — call `to_dict()`.

    Fields (set by step_loader)
    ---------------------------
    face_id        : 0-based sequential integer (TopExp_Explorer traversal).
    occ_face       : Live `TopoDS_Face` handle.
    surface_type   : "Plane" | "Cylinder" | "Cone" | "Sphere" | "Torus" |
                     "BSpline/NURBS" | "Bezier" | "Revolution" | "Extrusion" |
                     "Offset" | "Other".
    normal         : Outward unit normal at UV centroid, orientation-corrected.
                     "Outward" means pointing away from the solid interior,
                     towards the mold cavity — consistent with what a mold
                     engineer expects.
    centroid       : 3-D point at UV centroid (mm).
    area           : Exact surface area in mm² (OCC surface integration).
    u_range        : (umin, umax) clamped parametric bounds.
    v_range        : (vmin, vmax) clamped parametric bounds.
    is_reversed    : True if face orientation in shell is REVERSED (normal
                     already flipped; stored for debugging only).
    normal_valid   : False if normal computation failed (degenerate geometry
                     or singular UV point).  All downstream modules must check
                     this flag before using `normal`.

    Fields (populated progressively by downstream modules)
    -------------------------------------------------------
    draft_angle_deg       : Module 2 — draft_analyzer.py
    draft_classification  : Module 2 — "good" | "marginal" | "bad"
    is_undercut           : Module 3 — undercut_detector.py
    undercut_depth_mm     : Module 3
    undercut_type         : Module 3 — "internal" | "external" | None
    cavity_or_core        : Module 5 — core_cavity.py — "cavity" | "core" | "parting"
    """

    # ── Set by step_loader ────────────────────────────────────────────────
    face_id: int
    occ_face: "TopoDS_Face"
    surface_type: str
    normal: Vec3
    centroid: Vec3
    area: float
    u_range: UVRange
    v_range: UVRange
    is_reversed: bool
    normal_valid: bool

    # ── Module 2: Draft Analysis ──────────────────────────────────────────
    draft_angle_deg: Optional[float] = None
    draft_classification: Optional[str] = None  # "good" | "marginal" | "bad"

    # ── Module 3: Undercut Detection ──────────────────────────────────────
    is_undercut: Optional[bool] = None
    undercut_depth_mm: Optional[float] = None
    undercut_type: Optional[str] = None  # "internal" | "external"

    # ── Module 5: Core/Cavity ─────────────────────────────────────────────
    cavity_or_core: Optional[str] = None  # "cavity" | "core" | "parting"

    # ── Geometry helpers ──────────────────────────────────────────────────
    def draft_angle_for_direction(self, pull_dir: Vec3) -> float:
        """
        Compute draft angle (°) between this face normal and a pull direction.

        Industry definition (SolidWorks DraftAnalysis):
            draft_angle = asin(|n · d|)

        Where:
            n  = outward face normal (unit vector)
            d  = pull direction (unit vector)

        Intuition:
            • Vertical wall (n ⊥ d):  |n·d| = 0  → draft = 0°  (worst case)
            • Horizontal face (n ∥ d): |n·d| = 1  → draft = 90° (best case)
            • 1.5° draft: |n·d| ≈ sin(1.5°) ≈ 0.0262

        Returns 0.0 for faces with invalid normals (safe for all callers).
        """
        if not self.normal_valid:
            return 0.0
        raw = dot3(self.normal, pull_dir)
        clamped = max(-1.0, min(1.0, raw))
        return math.degrees(math.asin(abs(clamped)))

    def signed_dot(self, pull_dir: Vec3) -> float:
        """
        Signed dot product n · d.

        Positive  → face normal broadly aligned with pull (cavity-side).
        Negative  → face normal opposed to pull (core-side).
        Near zero → silhouette / parting region.

        Used by:
          - Bassi 2010: face accessibility classification
          - Core/cavity extraction: classify cavity vs core
        """
        if not self.normal_valid:
            return 0.0
        return dot3(self.normal, pull_dir)

    def to_dict(self) -> dict:
        """JSON-serialisable dict.  No OCC objects."""
        d: dict = {
            "face_id": self.face_id,
            "surface_type": self.surface_type,
            "normal": [round(x, 6) for x in self.normal],
            "centroid": [round(x, 4) for x in self.centroid],
            "area_mm2": round(self.area, 4),
            "u_range": [round(x, 6) for x in self.u_range],
            "v_range": [round(x, 6) for x in self.v_range],
            "is_reversed": self.is_reversed,
            "normal_valid": self.normal_valid,
        }
        if self.draft_angle_deg is not None:
            d["draft_angle_deg"] = round(self.draft_angle_deg, 3)
            d["draft_classification"] = self.draft_classification
        if self.is_undercut is not None:
            d["is_undercut"] = self.is_undercut
            d["undercut_depth_mm"] = (
                round(self.undercut_depth_mm, 4)
                if self.undercut_depth_mm is not None else None
            )
            d["undercut_type"] = self.undercut_type
        if self.cavity_or_core is not None:
            d["cavity_or_core"] = self.cavity_or_core
        return d


# =============================================================================
# PartGeometry  —  the primary pipeline object
# =============================================================================

@dataclass
class PartGeometry:
    """
    Complete geometric description of a loaded STEP part.

    This is THE single object that flows through the entire DfM pipeline.
    Every module takes a `PartGeometry` as input and enriches it in place.

    The `occ_shape` field holds the live OCC solid required by Bassi, Sangolli,
    Nee, and Hou algorithms.  Never serialise it directly.

    Adjacency maps (set by step_loader after face extraction)
    ----------------------------------------------------------
    face_adjacency  dict[int, list[int]]
        face_id → list of face_ids that share at least one edge with it.
        The core graph for Nee's edge-loop traversal and Hou's path optimiser.

    face_to_edges   dict[int, list[int]]
        face_id → list of edge_ids belonging to that face.
        Used by: Sangolli (iterate edges of a face), Nee (silhouette search).

    edge_to_faces   dict[int, list[int]]
        edge_id → list of face_ids (1 for boundary, 2 for interior).
        Used by: Nee (check silhouette), Hou (graph weights).
    """

    # ── Required at construction (from step_loader) ───────────────────────
    source_file: str
    occ_shape: "TopoDS_Shape"
    faces: list[FaceData]
    bounding_box: BoundingBox
    cadquery_shape: Optional[object] = None

    # ── Topology (unique counts, after hash deduplication) ───────────────
    face_count: int = 0
    edge_count: int = 0         # unique edges (seam edges NOT double-counted)
    vertex_count: int = 0       # unique vertices
    solid_count: int = 0
    shell_count: int = 0

    # ── Full geometry data ────────────────────────────────────────────────
    edges: list[EdgeData] = field(default_factory=list)
    vertices: list[VertexData] = field(default_factory=list)

    # ── Adjacency maps (populated by step_loader) ─────────────────────────
    face_adjacency: dict[int, list[int]] = field(default_factory=dict)
    face_to_edges: dict[int, list[int]] = field(default_factory=dict)
    edge_to_faces: dict[int, list[int]] = field(default_factory=dict)

    # ── Load metadata ─────────────────────────────────────────────────────
    load_time_s: float = 0.0
    warnings: list[str] = field(default_factory=list)
    surface_type_counts: dict[str, int] = field(default_factory=dict)
    edge_type_counts: dict[str, int] = field(default_factory=dict)

    # ── Analysis results (populated by downstream modules) ────────────────
    # Module 3: direction_optimizer + undercut_detector
    optimal_pull_direction: Optional[Vec3] = None
    direction_score: Optional[float] = None
    inaccessible_face_ids: list[int] = field(default_factory=list)

    # Module 4: parting_line
    parting_edge_ids: list[int] = field(default_factory=list)
    parting_wire_points: list[Vec3] = field(default_factory=list)

    # =========================================================================
    # Face accessors
    # =========================================================================

    @property
    def valid_faces(self) -> list[FaceData]:
        """Faces whose normals are valid (degenerate faces excluded)."""
        return [f for f in self.faces if f.normal_valid]

    @property
    def undercut_faces(self) -> list[FaceData]:
        return [f for f in self.faces if f.is_undercut is True]

    @property
    def cavity_faces(self) -> list[FaceData]:
        return [f for f in self.faces if f.cavity_or_core == "cavity"]

    @property
    def core_faces(self) -> list[FaceData]:
        return [f for f in self.faces if f.cavity_or_core == "core"]

    def get_face(self, face_id: int) -> Optional[FaceData]:
        """
        Look up FaceData by face_id.

        O(1) if IDs are dense and sequential (the normal case).
        Falls back to O(n) linear scan for sparse ID spaces.
        """
        if 0 <= face_id < len(self.faces) and self.faces[face_id].face_id == face_id:
            return self.faces[face_id]
        for f in self.faces:
            if f.face_id == face_id:
                return f
        return None

    def get_adjacent_faces(self, face_id: int) -> list[FaceData]:
        """
        Return all FaceData objects topologically adjacent to `face_id`.

        Two faces are adjacent if they share at least one edge.
        Returns empty list if face_id is unknown or adjacency not yet built.

        Used by: Nee 1998 (loop traversal), Sangolli (feature propagation).
        """
        adj_ids = self.face_adjacency.get(face_id, [])
        result = []
        for fid in adj_ids:
            fd = self.get_face(fid)
            if fd is not None:
                result.append(fd)
        return result

    # =========================================================================
    # Edge accessors
    # =========================================================================

    def get_edge(self, edge_id: int) -> Optional[EdgeData]:
        """Look up EdgeData by edge_id.  O(1) for dense IDs, O(n) fallback."""
        if 0 <= edge_id < len(self.edges) and self.edges[edge_id].edge_id == edge_id:
            return self.edges[edge_id]
        for e in self.edges:
            if e.edge_id == edge_id:
                return e
        return None

    def get_face_edges(self, face_id: int) -> list[EdgeData]:
        """
        Return all EdgeData objects belonging to `face_id`.

        Used by: Sangolli (iterate edges for convexity), Nee (silhouette check).
        """
        edge_ids = self.face_to_edges.get(face_id, [])
        result = []
        for eid in edge_ids:
            ed = self.get_edge(eid)
            if ed is not None:
                result.append(ed)
        return result

    def get_boundary_edges(self) -> list[EdgeData]:
        """
        Edges with exactly 1 adjacent face — the outer rim of the part.

        For a closed solid (injection-molded cap), boundary edges form the
        physical opening/rim.  They are candidates for the parting line.
        """
        return [e for e in self.edges if e.is_boundary]

    def get_manifold_edges(self) -> list[EdgeData]:
        """Edges shared between exactly 2 faces — the standard interior edges."""
        return [e for e in self.edges if e.is_manifold]

    def get_non_manifold_edges(self) -> list[EdgeData]:
        """
        Edges shared by 3 or more faces — non-manifold geometry.

        Should NOT appear in a well-formed injection-molded part.
        If present, they indicate a CAD error that will cause problems for
        all downstream algorithms.
        """
        return [e for e in self.edges if len(e.adjacent_face_ids) > 2]

    def get_seam_edges(self) -> list[EdgeData]:
        """Seam edges of periodic surfaces (full cylinders, spheres, tori)."""
        return [e for e in self.edges if e.is_seam]

    def get_silhouette_edges(self) -> list[EdgeData]:
        """
        Edges flagged as silhouette edges (set by parting_line.py).

        A silhouette edge for pull direction d: one adjacent face has n·d > 0
        and the other has n·d < 0.  These edges form the parting line candidates.
        """
        return [e for e in self.edges if e.is_silhouette is True]

    # =========================================================================
    # Vertex accessors
    # =========================================================================

    def get_vertex(self, vertex_id: int) -> Optional[VertexData]:
        if 0 <= vertex_id < len(self.vertices) and self.vertices[vertex_id].vertex_id == vertex_id:
            return self.vertices[vertex_id]
        for v in self.vertices:
            if v.vertex_id == vertex_id:
                return v
        return None

    # =========================================================================
    # Diagnostic / summary helpers
    # =========================================================================

    def adjacency_stats(self) -> dict:
        """
        Compute statistics about the face adjacency graph.

        Useful for:
        - Verifying the adjacency was built correctly (Euler characteristic check).
        - Detecting non-manifold geometry that will break downstream algorithms.
        - Giving the AI Agent context for its natural-language explanation.
        """
        if not self.face_adjacency:
            return {"status": "not_built"}

        neighbor_counts = [len(v) for v in self.face_adjacency.values()]
        boundary_edges = len(self.get_boundary_edges())
        manifold_edges = len(self.get_manifold_edges())
        non_manifold = len(self.get_non_manifold_edges())
        seam_edges = len(self.get_seam_edges())

        return {
            "faces": self.face_count,
            "unique_edges": self.edge_count,
            "unique_vertices": self.vertex_count,
            "boundary_edges": boundary_edges,
            "manifold_edges": manifold_edges,
            "non_manifold_edges": non_manifold,
            "seam_edges": seam_edges,
            "avg_face_neighbors": (
                round(sum(neighbor_counts) / len(neighbor_counts), 2)
                if neighbor_counts else 0.0
            ),
            "max_face_neighbors": max(neighbor_counts) if neighbor_counts else 0,
            "isolated_faces": sum(1 for c in neighbor_counts if c == 0),
            "is_manifold": non_manifold == 0,
        }

    def summary(self) -> str:
        """Human-readable summary printed to console or logged."""
        lines = [
            "=" * 65,
            "  DfM Agent — Part Geometry Summary",
            "=" * 65,
            f"  File          : {self.source_file}",
            f"  Load time     : {self.load_time_s:.3f} s",
            "",
            "  Bounding box  :",
            f"    X  [{self.bounding_box.xmin:>10.3f}  →  {self.bounding_box.xmax:>10.3f}] mm",
            f"    Y  [{self.bounding_box.ymin:>10.3f}  →  {self.bounding_box.ymax:>10.3f}] mm",
            f"    Z  [{self.bounding_box.zmin:>10.3f}  →  {self.bounding_box.zmax:>10.3f}] mm",
            f"    Diagonal     : {self.bounding_box.diagonal:.3f} mm",
            "",
            "  Topology (unique):",
            f"    Solids       : {self.solid_count}",
            f"    Shells       : {self.shell_count}",
            f"    Faces        : {self.face_count}",
            f"    Edges        : {self.edge_count}",
            f"    Vertices     : {self.vertex_count}",
            "",
            "  Surface types :",
        ]
        for stype, count in sorted(self.surface_type_counts.items(), key=lambda x: -x[1]):
            lines.append(f"    {stype:<24}: {count:>4}")

        if self.edge_type_counts:
            lines.append("")
            lines.append("  Edge types    :")
            for etype, count in sorted(self.edge_type_counts.items(), key=lambda x: -x[1]):
                lines.append(f"    {etype:<24}: {count:>4}")

        stats = self.adjacency_stats()
        if stats.get("status") != "not_built":
            lines += [
                "",
                "  Adjacency graph:",
                f"    Boundary edges   : {stats['boundary_edges']}",
                f"    Manifold edges   : {stats['manifold_edges']}",
                f"    Non-manifold     : {stats['non_manifold_edges']}",
                f"    Seam edges       : {stats['seam_edges']}",
                f"    Avg face nbrs    : {stats['avg_face_neighbors']}",
                f"    Max face nbrs    : {stats['max_face_neighbors']}",
                f"    Isolated faces   : {stats['isolated_faces']}",
                f"    Manifold solid   : {'YES' if stats['is_manifold'] else 'NO — check geometry'}",
            ]

        invalid_normals = sum(1 for f in self.faces if not f.normal_valid)
        if invalid_normals:
            lines.append(f"\n  ⚠  Invalid normals: {invalid_normals}/{self.face_count} faces")

        if self.optimal_pull_direction:
            d = self.optimal_pull_direction
            lines.append(
                f"\n  Optimal pull dir : ({d[0]:+.3f}, {d[1]:+.3f}, {d[2]:+.3f})"
                f"  score={self.direction_score:.4f}"
                f"  inaccessible={len(self.inaccessible_face_ids)}"
            )

        if self.warnings:
            lines.append("")
            lines.append("  Warnings:")
            for w in self.warnings:
                lines.append(f"    ⚠  {w}")

        lines.append("=" * 65)
        return "\n".join(lines)

    def to_dict(
        self,
        include_faces: bool = True,
        include_edges: bool = False,
        include_vertices: bool = False,
    ) -> dict:
        """
        JSON-serialisable dict.

        Parameters
        ----------
        include_faces    : Include per-face data (can be large for 500+ face parts).
        include_edges    : Include per-edge data.
        include_vertices : Include vertex coordinates.
        """
        d: dict = {
            "source_file": self.source_file,
            "face_count": self.face_count,
            "edge_count": self.edge_count,
            "vertex_count": self.vertex_count,
            "solid_count": self.solid_count,
            "shell_count": self.shell_count,
            "bounding_box": self.bounding_box.to_dict(),
            "has_cadquery_shape": self.cadquery_shape is not None,
            "surface_type_counts": self.surface_type_counts,
            "edge_type_counts": self.edge_type_counts,
            "load_time_s": round(self.load_time_s, 4),
            "warnings": self.warnings,
            "adjacency_stats": self.adjacency_stats(),
        }
        if self.optimal_pull_direction:
            d["optimal_pull_direction"] = list(self.optimal_pull_direction)
            d["direction_score"] = self.direction_score
            d["inaccessible_face_count"] = len(self.inaccessible_face_ids)
        if include_faces:
            d["faces"] = [f.to_dict() for f in self.faces]
        if include_edges:
            d["edges"] = [e.to_dict() for e in self.edges]
        if include_vertices:
            d["vertices"] = [v.to_dict() for v in self.vertices]
        return d
    
