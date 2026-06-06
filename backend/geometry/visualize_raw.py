"""
backend/geometry/visualize_raw.py
----------------------------------
Module 1 companion: exact STEP B-Rep → display mesh for raw visualization.

Responsibility
--------------
Convert a loaded `PartGeometry` into a lightweight triangle mesh suitable for
PyVista/Streamlit display, while preserving the STEP face_id for every display
triangle.  This is a visualization adapter only.  Downstream DfM algorithms
continue to use exact OCC B-Rep geometry from `step_loader.py`.

Why a mesh here is acceptable
-----------------------------
The papers and DfM engine operate on native B-Rep faces, normals, and topology.
Interactive web visualization needs triangles because VTK/PyVista renders
polygonal data.  This module keeps that approximation at the UI boundary and
stores `face_ids` so visual highlights still map back to exact STEP faces.

Integration
-----------
    load_step("Part1.stp") → build_display_mesh(part) → to_pyvista()

The frontend can color by `mesh.cell_data["face_id"]`, `draft_class`, or any
future per-face result without re-reading the STEP file.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from backend.models.geometry_models import PartGeometry, Vec3

try:
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
    from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopoDS import topods, topods_Face

    _OCC_AVAILABLE = True
except ImportError:
    _OCC_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RawMeshData:
    """
    Triangle mesh for visualization, with exact STEP face mapping.

    points
        Unique display vertices in model coordinates.
    faces
        Triangle vertex indices into `points`.
    face_ids
        `face_ids[i]` is the source STEP face_id for `faces[i]`.
    face_centers
        Approximate center per STEP face, used for optional face ID labels.
    """

    points: list[Vec3]
    faces: list[tuple[int, int, int]]
    face_ids: list[int]
    face_centers: dict[int, Vec3] = field(default_factory=dict)

    @property
    def triangle_count(self) -> int:
        return len(self.faces)

    @property
    def point_count(self) -> int:
        return len(self.points)

    def to_dict(self) -> dict:
        return self.to_payload(include_geometry=False)

    def to_payload(self, include_geometry: bool = False) -> dict:
        """
        JSON-safe payload for API/frontend use.

        `include_geometry=False` is a compact summary.  `True` includes full
        point and triangle arrays for Streamlit/PyVista rendering.
        """
        payload = {
            "point_count": self.point_count,
            "triangle_count": self.triangle_count,
            "face_count": len(self.face_centers),
            "face_ids": self.face_ids,
            "face_centers": {
                str(fid): [round(v, 4) for v in center]
                for fid, center in self.face_centers.items()
            },
        }
        if include_geometry:
            payload["points"] = [[float(x), float(y), float(z)] for x, y, z in self.points]
            payload["faces"] = [[int(a), int(b), int(c)] for a, b, c in self.faces]
        return payload


def _require_occ() -> None:
    if not _OCC_AVAILABLE:
        raise ImportError(
            "pythonOCC is required to triangulate STEP B-Rep geometry for display. "
            "Use the locked conda/Docker environment from environment.yml."
        )


def _as_face(shape: object) -> object:
    """
    Cast a generic TopoDS shape to TopoDS_Face without OCC 7.7 warnings.

    pythonOCC 7.7.1 deprecated the module-level `topods_Face(...)` helper in
    favor of `topods.Face(...)`.  Older builds may not expose `topods.Face`, so
    keep a quiet fallback for compatibility.
    """
    if hasattr(topods, "Face"):
        return topods.Face(shape)
    return topods_Face(shape)


def _triangle_indices(triangle: object) -> tuple[int, int, int]:
    """
    Return OCC triangle node indices as a Python tuple.

    pythonOCC bindings vary slightly by OCC version: some expose `Get()` and
    some expose `Value(1..3)`.  This helper supports both.
    """
    if hasattr(triangle, "Get"):
        values = triangle.Get()
        return (int(values[0]), int(values[1]), int(values[2]))
    return (
        int(triangle.Value(1)),  # type: ignore[attr-defined]
        int(triangle.Value(2)),  # type: ignore[attr-defined]
        int(triangle.Value(3)),  # type: ignore[attr-defined]
    )


def _node_xyz(triangulation: object, node_index: int, transform: object) -> Vec3:
    pnt = triangulation.Node(node_index)
    pnt.Transform(transform)
    return (float(pnt.X()), float(pnt.Y()), float(pnt.Z()))


def _center_of_points(points: list[Vec3]) -> Vec3:
    if not points:
        return (0.0, 0.0, 0.0)
    n = float(len(points))
    return (
        sum(p[0] for p in points) / n,
        sum(p[1] for p in points) / n,
        sum(p[2] for p in points) / n,
    )


def _triangulate_occ_shape(
    shape: object,
    linear_deflection: float,
    angular_deflection: float,
    face_center_fallback: Optional[dict[int, Vec3]] = None,
) -> RawMeshData:
    """
    Triangulate any OCC shape into a JSON-safe display mesh.

    This helper is intentionally generic so the main part and smaller Boolean
    intersection regions use the same display-only conversion path.
    """
    _require_occ()

    if linear_deflection <= 0:
        raise ValueError("linear_deflection must be > 0")
    if angular_deflection <= 0:
        raise ValueError("angular_deflection must be > 0")

    mesher = BRepMesh_IncrementalMesh(
        shape,
        linear_deflection,
        False,
        angular_deflection,
        True,
    )
    mesher.Perform()
    if not mesher.IsDone():
        raise RuntimeError("OCC triangulation failed for visualization mesh.")

    points: list[Vec3] = []
    triangles: list[tuple[int, int, int]] = []
    triangle_face_ids: list[int] = []
    face_centers: dict[int, Vec3] = {}

    fallback_centers = face_center_fallback or {}
    face_index = 0
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        face = _as_face(exp.Current())
        location = face.Location()
        triangulation = BRep_Tool.Triangulation(face, location)

        if triangulation is None:
            logger.warning("Face %d has no triangulation; skipping in display view.", face_index)
            face_centers[face_index] = fallback_centers.get(face_index, (0.0, 0.0, 0.0))
            face_index += 1
            exp.Next()
            continue

        transform = location.Transformation()
        local_to_global: dict[int, int] = {}
        face_points: list[Vec3] = []

        for node_idx in range(1, triangulation.NbNodes() + 1):
            xyz = _node_xyz(triangulation, node_idx, transform)
            local_to_global[node_idx] = len(points)
            points.append(xyz)
            face_points.append(xyz)

        is_reversed = face.Orientation() == TopAbs_REVERSED
        for tri_idx in range(1, triangulation.NbTriangles() + 1):
            n1, n2, n3 = _triangle_indices(triangulation.Triangle(tri_idx))
            if is_reversed:
                n2, n3 = n3, n2
            triangles.append((
                local_to_global[n1],
                local_to_global[n2],
                local_to_global[n3],
            ))
            triangle_face_ids.append(face_index)

        face_centers[face_index] = _center_of_points(face_points)
        face_index += 1
        exp.Next()

    return RawMeshData(
        points=points,
        faces=triangles,
        face_ids=triangle_face_ids,
        face_centers=face_centers,
    )


def build_raw_mesh(
    part: PartGeometry,
    linear_deflection: float = 0.5,
    angular_deflection: float = 0.5,
) -> RawMeshData:
    """
    Triangulate a loaded STEP part for raw 3D visualization.

    Parameters
    ----------
    part
        Loaded `PartGeometry` from `step_loader.load_step`.
    linear_deflection
        OCC mesh linear tolerance in model units (normally mm). Smaller values
        look smoother but create more triangles.
    angular_deflection
        OCC mesh angular tolerance in radians.

    Returns
    -------
    RawMeshData
        Display mesh with triangle-to-STEP-face mapping.
    """
    return _triangulate_occ_shape(
        shape=part.occ_shape,
        linear_deflection=linear_deflection,
        angular_deflection=angular_deflection,
        face_center_fallback={face.face_id: face.centroid for face in part.faces},
    )


def build_shape_display_mesh(
    shape: object | None,
    linear_deflection: float = 0.5,
    angular_deflection: float = 0.5,
) -> RawMeshData:
    """
    Triangulate a non-part OCC shape for visualization.

    Boolean intersection regions are exact B-Rep shapes inside the analysis
    engine.  This function creates a display-only mesh for those regions so the
    API/frontend can show real undercut volumes without exposing OCC objects.
    """
    if shape is None:
        return RawMeshData(points=[], faces=[], face_ids=[], face_centers={})
    return _triangulate_occ_shape(
        shape=shape,
        linear_deflection=linear_deflection,
        angular_deflection=angular_deflection,
    )


def build_display_mesh(
    part: PartGeometry,
    linear_deflection: float = 0.5,
    angular_deflection: float = 0.5,
) -> RawMeshData:
    """
    Preferred public name for display triangulation.

    `build_raw_mesh` remains as a backwards-compatible alias from the first
    scaffold pass.  This name is clearer: the result is a display-only mesh,
    not a substitute for exact B-Rep analysis.
    """
    return build_raw_mesh(
        part=part,
        linear_deflection=linear_deflection,
        angular_deflection=angular_deflection,
    )


def to_pyvista(mesh: RawMeshData) -> object:
    """
    Convert `RawMeshData` to a `pyvista.PolyData`.

    Import is local so backend tests can run without PyVista installed.
    """
    try:
        import numpy as np
        import pyvista as pv
    except ImportError as exc:
        raise ImportError(
            "PyVista and NumPy are required for visualization conversion. "
            "Install the locked conda/Docker environment."
        ) from exc

    points = np.asarray(mesh.points, dtype=float)
    faces = np.asarray([[3, a, b, c] for a, b, c in mesh.faces], dtype=int).ravel()
    poly = pv.PolyData(points, faces)
    poly.cell_data["face_id"] = np.asarray(mesh.face_ids, dtype=int)
    return poly


def show_raw_view(
    part: PartGeometry,
    linear_deflection: float = 0.5,
    show_face_ids: bool = True,
) -> None:
    """
    Open an interactive PyVista window for local raw inspection.

    This is a developer utility.  The production frontend will use Streamlit.
    """
    mesh = build_raw_mesh(part, linear_deflection=linear_deflection)
    poly = to_pyvista(mesh)

    import pyvista as pv

    plotter = pv.Plotter()
    plotter.add_mesh(
        poly,
        color=(0.78, 0.82, 0.86),
        show_edges=True,
        edge_color=(0.18, 0.20, 0.22),
        line_width=1,
    )
    if show_face_ids:
        ids = sorted(mesh.face_centers)
        centers = [mesh.face_centers[fid] for fid in ids]
        labels = [str(fid) for fid in ids]
        plotter.add_point_labels(
            centers,
            labels,
            font_size=10,
            point_size=0,
            shape_opacity=0.35,
        )
    plotter.add_axes()
    plotter.show()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Visualize a STEP file as raw B-Rep mesh.")
    parser.add_argument("step_file", type=Path)
    parser.add_argument("--deflection", type=float, default=0.5)
    parser.add_argument("--no-labels", action="store_true")
    parser.add_argument("--summary-only", action="store_true")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    from backend.geometry.step_loader import load_step

    parser = _build_parser()
    args = parser.parse_args(argv)

    part = load_step(args.step_file)
    mesh = build_raw_mesh(part, linear_deflection=args.deflection)
    print(part.summary())
    print(
        f"\nRaw display mesh: {mesh.point_count} points, "
        f"{mesh.triangle_count} triangles, {len(mesh.face_centers)} face labels"
    )

    if not args.summary_only:
        show_raw_view(
            part,
            linear_deflection=args.deflection,
            show_face_ids=not args.no_labels,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
