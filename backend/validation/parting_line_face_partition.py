"""
backend/validation/parting_line_face_partition.py
---------------------------------------------------
READ-ONLY DIAGNOSTIC MODULE (P3.15 / "Option 1", 2026-08-13). Not production
code, not imported by backend.geometry.parting_line_v2.

Determines the ACTUAL connected sub-regions a B-Rep face is cut into by an
arbitrary set of Track-B interior curves -- correctly handling any number of
disjoint curves, closed curves, curves intersecting each other, and curves
terminating on different boundary arcs. This replaces the binary
(face,+1)/(face,-1) model used by P3.13/P3.14 (D-039, "Option 2"), which was
proven topologically invalid for faces with more than one disjoint interior
curve (45% of Part3's split faces at the tested direction) -- forcing them
into a 2-node model produced attachment assignments matching no real
continuous curve, which is what caused P3.13's pervasive odd-degree
fragmentation and P3.14's H1 non-closures.

Method: planar arrangement via `shapely.ops.polygonize`. A face's own
boundary edges (sampled as UV polylines from their real pcurves) plus every
Track-B interior curve on the face (already real UV polylines) are noded
(intersections resolved, near-coincident endpoints snapped to a grid) and
polygonized -- a standard, well-tested computational-geometry operation for
exactly this problem ("cut this polygon by this line arrangement into its
connected faces"), not a bespoke arrangement algorithm written from scratch
for this one use. `shapely` (MIT-licensed, GEOS-backed) was installed into
the project's `dfm_agent` micromamba env for this diagnostic script; it is
not a production dependency.

No hardcoded topology, no hardcoded face IDs, no "N curves -> N+1 regions"
shortcut -- the region count and adjacency are always the actual output of
polygonize on the actual curve arrangement, verified against closed-form
expected answers only in the synthetic fixtures (`run_fixture_tests`),
never assumed.

Known, stated limitation (not silently ignored -- see Fixture H): no
periodic-seam unwrapping is performed. A face's own boundary edges and
Track-B's own UV points are sampled directly from OCC's own pcurves/grid
bounds for THIS specific face, which are already a valid, non-overlapping,
correctly-closed trim boundary in UV space even for a periodic surface
(BRep_Tool.CurveOnSurface returns each edge's own unambiguous parameter
range on this face). This works correctly for a curve that stays within the
UV domain OCC hands back. It is NOT expected to work correctly for a curve
that would need to "wrap" across a periodic seam it was never sampled on
either side of -- Fixture H tests exactly this and the result is reported
honestly, not assumed.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.ops import polygonize, unary_union
from shapely import set_precision

try:
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.BRepTools import breptools
    from OCC.Core.GeomLProp import GeomLProp_SLProps

    from backend.geometry.step_loader import _face_normal_at_uv
    from backend.models.geometry_models import dot3

    _OCC_AVAILABLE = True
except Exception:  # pragma: no cover
    _OCC_AVAILABLE = False


# ===========================================================================
# Phase 1-3: pure topology function + synthetic fixtures
# ===========================================================================

@dataclass(frozen=True)
class FaceRegion:
    region_id: int
    polygon: Polygon
    uv_area: float


def partition_face_uv(
    boundary_lines: list[LineString], interior_lines: list[LineString],
    *, snap_grid: float = 1e-9,
) -> list[FaceRegion]:
    """
    Cut a face's UV domain (given by its boundary as a set of edge polylines
    -- need not already be ordered into one closed ring) by an arbitrary set
    of interior curves, and return its ACTUAL connected sub-regions.

    Handles, by construction (this is what `polygonize` on a noded line
    arrangement does, not a special case coded per topology):
      * any number of disjoint open curves crossing the face
      * closed interior curves (islands)
      * curves intersecting each other
      * curves terminating on different boundary arcs
      * curves nested inside one another

    Does NOT assume "N curves -> N+1 regions" -- the region set is always
    read directly off `polygonize`'s output.
    """
    all_lines = list(boundary_lines) + list(interior_lines)
    if not all_lines:
        return []
    merged = unary_union(all_lines)  # nodes the arrangement: splits lines at every crossing
    if snap_grid > 0:
        merged = set_precision(merged, grid_size=snap_grid)
    polygons = [p for p in polygonize(merged) if p.area > 0]
    return [FaceRegion(region_id=i, polygon=p, uv_area=p.area) for i, p in enumerate(polygons)]


def region_adjacency(regions: list[FaceRegion], *, touch_tolerance: float = 1e-9) -> dict[int, set[int]]:
    """
    Two regions are adjacent iff their boundaries share a positive-LENGTH
    arc, not merely a point.

    Caught by Fixture G (two crossing curves, 4 quadrants): the first version
    of this function used `polygon.distance() <= tolerance`, which is 0 for
    diagonal quadrants that only touch at the single crossing point -- that
    flagged all 4 quadrants as mutually adjacent, when the two DIAGONAL pairs
    share no real boundary arc at all (a single point is not a shared edge in
    the same sense H3's `separate_surface` uses "shares at least one edge").
    Fixed to require the two polygon boundaries' intersection to be a
    LineString/MultiLineString with positive length, not just a non-empty
    intersection.
    """
    adjacency: dict[int, set[int]] = {r.region_id: set() for r in regions}
    for i, a in enumerate(regions):
        for b in regions[i + 1:]:
            shared = a.polygon.boundary.intersection(b.polygon.boundary)
            if shared.length > touch_tolerance:
                adjacency[a.region_id].add(b.region_id)
                adjacency[b.region_id].add(a.region_id)
    return adjacency


def _rect_boundary(x0=0.0, y0=0.0, x1=1.0, y1=1.0) -> list[LineString]:
    return [
        LineString([(x0, y0), (x1, y0)]),
        LineString([(x1, y0), (x1, y1)]),
        LineString([(x1, y1), (x0, y1)]),
        LineString([(x0, y1), (x0, y0)]),
    ]


def run_fixture_tests() -> list[dict]:
    """Phase 2/3: the 8 synthetic UV-topology fixtures, region count/adjacency verified algorithmically."""
    results = []

    def check(name, boundary, interior, expected_regions, notes=""):
        regions = partition_face_uv(boundary, interior)
        adjacency = region_adjacency(regions)
        total_area = sum(r.uv_area for r in regions)
        passed = len(regions) == expected_regions
        results.append({
            "fixture": name, "expected_regions": expected_regions,
            "actual_regions": len(regions), "passed": passed,
            "total_uv_area": round(total_area, 6),
            "adjacency": {k: sorted(v) for k, v in adjacency.items()},
            "notes": notes,
        })

    # A: one open curve crossing the face -> 2 regions
    check("A_one_open_curve", _rect_boundary(),
          [LineString([(0.5, 0.0), (0.5, 1.0)])], 2)

    # B: two disjoint open curves, neither touching the other -> 3 regions
    check("B_two_disjoint_open_curves", _rect_boundary(),
          [LineString([(0.3, 0.0), (0.3, 1.0)]), LineString([(0.7, 0.0), (0.7, 1.0)])], 3)

    # C: three disjoint open curves -> 4 regions
    check("C_three_disjoint_open_curves", _rect_boundary(),
          [LineString([(0.25, 0.0), (0.25, 1.0)]),
           LineString([(0.50, 0.0), (0.50, 1.0)]),
           LineString([(0.75, 0.0), (0.75, 1.0)])], 4)

    # D: one closed interior curve (island) -> 2 regions (inside the loop, outside it)
    check("D_one_closed_curve", _rect_boundary(),
          [LineString([(0.3, 0.3), (0.7, 0.3), (0.7, 0.7), (0.3, 0.7), (0.3, 0.3)])], 2)

    # E: two disjoint closed curves -> 3 regions
    check("E_two_disjoint_closed_curves", _rect_boundary(),
          [LineString([(0.15, 0.3), (0.35, 0.3), (0.35, 0.7), (0.15, 0.7), (0.15, 0.3)]),
           LineString([(0.65, 0.3), (0.85, 0.3), (0.85, 0.7), (0.65, 0.7), (0.65, 0.3)])], 3)

    # F: one open curve + one closed curve, disjoint -> 3 regions
    check("F_open_plus_closed", _rect_boundary(),
          [LineString([(0.5, 0.0), (0.5, 1.0)]),
           LineString([(0.15, 0.3), (0.35, 0.3), (0.35, 0.7), (0.15, 0.7), (0.15, 0.3)])], 3)

    # G: two curves that actually cross each other (an X through the middle)
    # -> a single crossing point splits the face into 4 regions (like a +).
    # The point of this fixture is that the topology must be DERIVED, not
    # assumed -- 2 curves does not always mean 3 regions (see fixture B vs G).
    check("G_intersecting_curves", _rect_boundary(),
          [LineString([(0.0, 0.5), (1.0, 0.5)]), LineString([(0.5, 0.0), (0.5, 1.0)])], 4,
          notes="Deliberately checks that region count is topology-derived, not a fixed N+1 rule.")

    # H: periodic seam case. Represent a cylinder's UV domain as a rectangle
    # (u wraps 0..2pi horizontally); place a curve that would, on the REAL
    # periodic surface, cross the seam and reconnect on the other side, but
    # is given here exactly as OCC would hand it -- a single pcurve sample
    # confined to this face's own UV bounds, not unwrapped or duplicated.
    # This tests whether the flat-rectangle assumption (no special seam
    # handling implemented) is adequate -- see module docstring; the result
    # is reported honestly, not assumed to pass.
    check("H_periodic_seam_flat_domain", _rect_boundary(x0=0.0, y0=0.0, x1=2 * math.pi, y1=1.0),
          [LineString([(0.1, 0.0), (0.1, 1.0)]), LineString([(2 * math.pi - 0.1, 0.0), (2 * math.pi - 0.1, 1.0)])],
          3,
          notes=(
              "Two curves near opposite ends of a periodic domain, sampled flat (no seam "
              "unwrapping). On a REAL periodic surface these two curves are physically close "
              "together (near the seam) and might need to be treated as related; this fixture "
              "checks what the flat, non-periodic-aware implementation actually does (3 regions, "
              "the same as if they were unrelated interior curves) -- documenting the limitation "
              "empirically rather than leaving it unverified."
          ))

    return results


# ===========================================================================
# Phase 5+: wiring into real B-Rep face geometry
# ===========================================================================

def _sample_edge_uv(face_occ, edge_data, n: int = 12) -> LineString | None:
    """Sample an edge's own pcurve on this face -- the face's own boundary, not a fresh curve."""
    try:
        pcurve, first, last = BRep_Tool.CurveOnSurface(edge_data.occ_edge, face_occ)
        if pcurve is None:
            return None
    except Exception:
        return None
    points = []
    for i in range(n):
        t = first + (last - first) * i / (n - 1)
        uv = pcurve.Value(t)
        points.append((uv.X(), uv.Y()))
    return LineString(points)


def _outer_wire_edge_ids(part, face) -> set[int]:
    """
    Edge ids belonging to the face's OUTER wire, via `breptools.OuterWire` --
    distinguishes the true material boundary from any INNER (hole) wires a
    trimmed face may have. `part.face_to_edges` lists every boundary edge of
    a face without distinguishing outer from inner wires; a real trimmed
    face with a hole (e.g. a flat plate with a bolt hole) has BOTH, and
    without this distinction a hole's empty interior gets polygonized into
    its own region and treated as if it were real material -- caught by
    inspecting Part1 +Z's regression run: 5 faces reported 2-4 regions with
    ZERO Track-B curves involved at all (region_hist={2: 4, 4: 1}), and all
    5 turned out to be flat faces with more boundary edges than a simple
    outer loop needs -- genuine holes, not silhouette splits.
    """
    from OCC.Core.TopAbs import TopAbs_EDGE
    from OCC.Core.TopExp import TopExp_Explorer

    try:
        outer_wire = breptools.OuterWire(face.occ_face)
    except Exception:
        return set(part.face_to_edges.get(face.face_id, []))

    outer_occ_edges = []
    explorer = TopExp_Explorer(outer_wire, TopAbs_EDGE)
    while explorer.More():
        outer_occ_edges.append(explorer.Current())
        explorer.Next()

    edges_by_id = {e.edge_id: e for e in part.edges}
    outer_ids: set[int] = set()
    for edge_id in part.face_to_edges.get(face.face_id, []):
        edge = edges_by_id.get(edge_id)
        if edge is None:
            continue
        if any(edge.occ_edge.IsSame(oe) for oe in outer_occ_edges):
            outer_ids.add(edge_id)
    return outer_ids


def build_face_regions(part, face, track_b_segments_for_face: list, *, snap_grid_rel: float = 1e-6):
    """
    Real-geometry counterpart of `partition_face_uv`: boundary edges sampled
    from the face's OWN pcurves (`part.face_to_edges`), interior curves taken
    directly from Track-B's already-computed `FaceBacking.uv` (never
    resampled or refit).

    A region entirely bounded by INNER (hole) wire edges, with no outer-wire
    edge and no Track-B curve on its boundary, is a hole's empty interior --
    not material -- and is dropped rather than returned as a region.
    """
    boundary_lines: list[LineString] = []
    outer_lines: list[LineString] = []
    outer_ids = _outer_wire_edge_ids(part, face)
    edges_by_id = {e.edge_id: e for e in part.edges}
    for edge_id in part.face_to_edges.get(face.face_id, []):
        edge = edges_by_id.get(edge_id)
        if edge is None:
            continue
        line = _sample_edge_uv(face.occ_face, edge)
        if line is not None and line.length > 0:
            boundary_lines.append(line)
            if edge_id in outer_ids:
                outer_lines.append(line)

    interior_lines: list[LineString] = []
    for seg in track_b_segments_for_face:
        uv = seg.backing.uv
        if len(uv) >= 2:
            interior_lines.append(LineString(uv))

    try:
        u_min, u_max, v_min, v_max = breptools.UVBounds(face.occ_face)
        span = max(u_max - u_min, v_max - v_min, 1e-9)
    except Exception:
        span = 1.0
    snap = snap_grid_rel * span

    regions = partition_face_uv(boundary_lines, interior_lines, snap_grid=snap)
    if len(regions) <= 1 or not outer_lines:
        return regions

    material_regions = []
    for region in regions:
        touches_outer = any(
            region.polygon.boundary.intersection(line).length > snap for line in outer_lines
        )
        touches_interior_curve = any(
            region.polygon.boundary.intersection(line).length > snap for line in interior_lines
        )
        if touches_outer or touches_interior_curve:
            material_regions.append(region)
        # else: bounded ONLY by inner (hole) wire edges -- a hole's empty
        # interior, not material; dropped.
    return [FaceRegion(region_id=i, polygon=r.polygon, uv_area=r.uv_area) for i, r in enumerate(material_regions)]


def region_stats(face, region: FaceRegion, direction, *, grid: int = 9):
    """
    Area-weighted (area_mm2, mean_g) for ONE region, restricted to UV points
    the region's own polygon actually contains -- same M x M Jacobian-weighted
    philosophy as `_face_split_stats`/`regions.mean_abs_g`, just filtered to
    this specific sub-region instead of a global sign split.
    """
    try:
        surface = BRep_Tool.Surface(face.occ_face)
        u_min, u_max, v_min, v_max = breptools.UVBounds(face.occ_face)
    except Exception:
        return 0.0, 0.0

    minx, miny, maxx, maxy = region.polygon.bounds
    weight = 0.0
    g_sum = 0.0
    for i in range(grid):
        for j in range(grid):
            u = minx + (maxx - minx) * (i + 0.5) / grid
            v = miny + (maxy - miny) * (j + 0.5) / grid
            if not region.polygon.contains(Point(u, v)):
                continue
            normal = _face_normal_at_uv(face.occ_face, u, v)
            if normal is None:
                continue
            g = dot3(normal, direction)
            try:
                props = GeomLProp_SLProps(surface, u, v, 1, 1e-9)
                du, dv = props.D1U(), props.D1V()
                jac = math.sqrt(
                    (du.Y() * dv.Z() - du.Z() * dv.Y()) ** 2
                    + (du.Z() * dv.X() - du.X() * dv.Z()) ** 2
                    + (du.X() * dv.Y() - du.Y() * dv.X()) ** 2
                )
            except Exception:
                jac = 1.0
            weight += jac
            g_sum += g * jac
    if weight <= 0.0:
        return 0.0, 0.0
    # face.area is the TRUE 3-D area of the whole face; approximate this
    # region's share of it by its share of the total Jacobian-weighted grid
    # coverage over the face's full UV bounds (consistent with
    # `_face_split_stats`'s existing convention).
    full_grid_weight = 0.0
    for i in range(grid):
        for j in range(grid):
            u = u_min + (u_max - u_min) * (i + 0.5) / grid
            v = v_min + (v_max - v_min) * (j + 0.5) / grid
            normal = _face_normal_at_uv(face.occ_face, u, v)
            if normal is None:
                continue
            try:
                props = GeomLProp_SLProps(surface, u, v, 1, 1e-9)
                du, dv = props.D1U(), props.D1V()
                jac = math.sqrt(
                    (du.Y() * dv.Z() - du.Z() * dv.Y()) ** 2
                    + (du.Z() * dv.X() - du.X() * dv.Z()) ** 2
                    + (du.X() * dv.Y() - du.Y() * dv.X()) ** 2
                )
            except Exception:
                jac = 1.0
            full_grid_weight += jac
    area_mm2 = face.area * (weight / full_grid_weight) if full_grid_weight > 0 else 0.0
    mean_g = g_sum / weight
    return area_mm2, mean_g


# ===========================================================================
# P3.16 ("sub-edge-aware cross-face attachment"): a shared B-Rep edge can
# border MORE than one region per side. `region_for_edge_midpoint`
# (single-sample-per-edge) is exact only when neither adjacent face's region
# structure changes along that edge -- mirrors D-014's own documented
# limitation ("exact when {g>0} and {g<0} are each connected on the face"),
# just recurring one level down, at the edge rather than the face. This
# generalises it: split the edge at every point where EITHER side's region
# boundary actually crosses it (found by exact shapely intersection, not
# coarse sampling -- consistent with how `partition_face_uv` itself avoids
# sampling-based topology), then attach each resulting sub-interval
# independently. Reuses `EdgeBacking`'s existing t_start/t_end sub-range
# support -- the same mechanism Track A's own segment splitting and H3's
# `_uncovered_parameter` (D-015) already rely on -- rather than inventing a
# new provenance concept.
# ===========================================================================

def region_for_point(regions: list[FaceRegion], point: Point) -> int:
    if not regions:
        return 0
    for region in regions:
        if region.polygon.covers(point):
            return region.region_id
    return min(regions, key=lambda r: r.polygon.distance(point)).region_id


def edge_region_breakpoints(edge_line: LineString, regions: list[FaceRegion]) -> list[float]:
    """
    Normalized-along-edge (0..1) parameters where this edge's region
    attachment changes, found via EXACT intersection with each region's own
    boundary -- not by sampling the edge at N points and looking for a
    change (which could miss a crossing between two samples, or place it
    imprecisely). A region boundary crossing the edge produces a Point;
    a region boundary running ALONG part of the edge (the edge coincides
    with a Track-B curve for a stretch) produces a LineString, whose two
    ENDPOINTS are the relevant breakpoints.
    """
    breakpoints = {0.0, 1.0}
    if not regions:
        return sorted(breakpoints)
    for region in regions:
        inter = region.polygon.boundary.intersection(edge_line)
        if inter.is_empty:
            continue
        positions: list[float] = []
        geom_type = inter.geom_type
        if geom_type == "Point":
            positions = [edge_line.project(inter, normalized=True)]
        elif geom_type == "MultiPoint":
            positions = [edge_line.project(p, normalized=True) for p in inter.geoms]
        elif geom_type in ("LineString", "MultiLineString", "GeometryCollection"):
            # The region boundary runs COLLINEAR with edge_line for a
            # stretch (e.g. a region's own edge coincides with this shared
            # B-Rep edge). Two independently-sampled/discretised collinear
            # lines can intersect as many tiny fragments rather than one
            # clean overlap (shapely precision, not a real topology
            # feature) -- collapse to the overall covered EXTENT (min/max
            # normalized position across every fragment's every vertex)
            # rather than trusting each fragment's own endpoints, which was
            # measured to produce ~24 spurious breakpoints from a single
            # true overlap (Fixture I originally).
            all_points: list[Point] = []
            geoms = inter.geoms if hasattr(inter, "geoms") else [inter]
            for g in geoms:
                if g.geom_type == "Point":
                    all_points.append(g)
                elif g.geom_type == "LineString":
                    all_points.extend(Point(c) for c in g.coords)
            if all_points:
                projected = [edge_line.project(p, normalized=True) for p in all_points]
                positions = [min(projected), max(projected)]
        for pos in positions:
            breakpoints.add(pos)
    return sorted(breakpoints)


@dataclass(frozen=True)
class EdgeSubinterval:
    t_start: float
    t_end: float
    region_a: int
    region_b: int


def edge_subinterval_attachment(
    face_a, face_b, edge, regions_a: list[FaceRegion] | None, regions_b: list[FaceRegion] | None,
) -> list[EdgeSubinterval]:
    """
    Split a shared B-Rep edge at every parameter where EITHER adjacent
    face's region attachment changes, and return each sub-interval's exact
    attachment on both sides.

    ``t_start``/``t_end`` are the edge's own real 3-D curve parameters
    (`BRep_Tool.Range`) -- the same convention `EdgeBacking` already uses
    elsewhere, so a piece built from one of these sub-intervals needs no new
    provenance machinery.
    """
    # MUST match `build_face_regions`' own sampling density (default n=12) --
    # a mismatched resampling of the SAME curve produces two piecewise-linear
    # approximations that only approximately coincide, which manifests as
    # spurious extra "crossings" between them instead of one clean overlap.
    # Measured directly: with n=24 here vs n=12 in `build_face_regions`, 58
    # of Part1's 744 manifold edges (every Circle-type edge tested) produced
    # 21 spurious sub-intervals each in the trivial zero-Track-B-curve case,
    # which must yield exactly 1. Matching n removes the mismatch as a noise
    # source entirely (identical sampling of the same deterministic pcurve
    # evaluation produces identical points, so the region polygon's own
    # boundary segment IS this line, not an independent approximation of it).
    line_a = _sample_edge_uv(face_a.occ_face, edge)
    line_b = _sample_edge_uv(face_b.occ_face, edge)
    if line_a is None or line_b is None or line_a.length == 0 or line_b.length == 0:
        return []

    bp_a = edge_region_breakpoints(line_a, regions_a or [])
    bp_b = edge_region_breakpoints(line_b, regions_b or [])
    raw_breakpoints = sorted(set(bp_a) | set(bp_b))

    # Merge near-duplicate breakpoints (tolerance, justified independently):
    # face A's and face B's boundary polygons are each built from their OWN
    # independent `_sample_edge_uv` sampling of this SAME edge (12 points,
    # `build_face_regions`), while this function samples it AGAIN at 24
    # points for the intersection test -- two different discretisations of
    # one real curve, so their computed crossing positions agree only to
    # floating-point/sampling noise, not exactly. Measured directly on a
    # genuine Part1 edge with ZERO real curves on either side (both faces
    # single-region): the trivial case, which must yield exactly ONE
    # interval, produced 4 spurious breakpoints spaced 1e-6 to 4e-6 apart
    # (normalized) purely from this discretisation noise. A tolerance of
    # 1e-4 gives a 25-100x margin over that measured noise floor while
    # staying far below any geometrically real sub-interval gap (real
    # Track-B curves are separated by physical distances that are orders of
    # magnitude larger once normalized against a typical part's edge count).
    _MERGE_TOL = 1e-4
    breakpoints: list[float] = []
    for bp in raw_breakpoints:
        if breakpoints and bp - breakpoints[-1] < _MERGE_TOL:
            continue
        breakpoints.append(bp)
    if breakpoints and breakpoints[-1] < 1.0 - _MERGE_TOL:
        breakpoints.append(1.0)
    elif breakpoints:
        breakpoints[-1] = 1.0

    first, last = BRep_Tool.Range(edge.occ_edge)
    intervals: list[EdgeSubinterval] = []
    for i in range(len(breakpoints) - 1):
        n0, n1 = breakpoints[i], breakpoints[i + 1]
        if n1 - n0 < _MERGE_TOL:
            continue
        mid = (n0 + n1) / 2.0
        ra = region_for_point(regions_a or [], line_a.interpolate(mid, normalized=True))
        rb = region_for_point(regions_b or [], line_b.interpolate(mid, normalized=True))
        intervals.append(EdgeSubinterval(
            t_start=first + n0 * (last - first), t_end=first + n1 * (last - first),
            region_a=ra, region_b=rb,
        ))
    return intervals


def _build_two_face_fixture():
    """
    Two REAL OCC planar faces sharing one real B-Rep edge -- not a mock.
    Face A: unit square [0,1]x[0,1] in the XY plane. Face B: the adjacent
    unit square [1,2]x[0,1], sharing the edge x=1, y in [0,1]. Because both
    faces are built directly on the plane z=0 with a trivial planar
    parameterisation, each face's own UV coordinates equal its (x, y), which
    makes the expected sub-interval structure easy to state and check by
    hand while still exercising the REAL `BRep_Tool.CurveOnSurface`,
    `BRep_Tool.Range`, and edge-sharing machinery the real Part3 code path
    uses.

    Returns (face_a_data, face_b_data, shared_edge_data) as the SAME
    FaceData/EdgeData wrapper types `PartGeometry` uses elsewhere, so this
    is a genuine exercise of the production data model, not a parallel one.
    """
    from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire
    from OCC.Core.gp import gp_Ax3, gp_Dir, gp_Pln, gp_Pnt

    from backend.models.geometry_models import EdgeData, FaceData

    # An EXPLICIT, SHARED plane (origin (0,0,0), normal +Z, x-axis +X) --
    # OCC's default `BRepBuilderAPI_MakeFace(wire)` derives its own UV basis
    # per-face from the wire alone, which does NOT generally align with
    # global (x, y) (verified empirically: it put both faces' shared edge at
    # u=0.5 with v centred on 0, not the assumed x=1, y in [0,1]). Building
    # both faces on the SAME explicit `gp_Pln` guarantees u=global_x,
    # v=global_y exactly, so the hand-computed expected sub-intervals below
    # are checking the real geometry, not an assumption about it.
    plane = gp_Pln(gp_Ax3(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1), gp_Dir(1, 0, 0)))

    def edge(p0, p1):
        return BRepBuilderAPI_MakeEdge(gp_Pnt(*p0, 0), gp_Pnt(*p1, 0)).Edge()

    shared_ab = edge((1, 0), (1, 1))  # shared by both faces, same orientation for both

    wire_a = BRepBuilderAPI_MakeWire(
        edge((0, 0), (1, 0)), shared_ab, edge((1, 1), (0, 1)), edge((0, 1), (0, 0)),
    ).Wire()
    face_a_occ = BRepBuilderAPI_MakeFace(plane, wire_a).Face()

    wire_b = BRepBuilderAPI_MakeWire(
        shared_ab, edge((1, 1), (2, 1)), edge((2, 1), (2, 0)), edge((2, 0), (1, 0)),
    ).Wire()
    face_b_occ = BRepBuilderAPI_MakeFace(plane, wire_b).Face()

    face_a = FaceData(
        face_id=0, occ_face=face_a_occ, surface_type="Plane",
        normal=(0.0, 0.0, 1.0), centroid=(0.5, 0.5, 0.0), area=1.0,
        u_range=(0.0, 1.0), v_range=(0.0, 1.0), is_reversed=False, normal_valid=True,
    )
    face_b = FaceData(
        face_id=1, occ_face=face_b_occ, surface_type="Plane",
        normal=(0.0, 0.0, 1.0), centroid=(1.5, 0.5, 0.0), area=1.0,
        u_range=(1.0, 2.0), v_range=(0.0, 1.0), is_reversed=False, normal_valid=True,
    )
    shared_edge = EdgeData(
        edge_id=100, occ_edge=shared_ab, edge_type="Line", length=1.0,
        adjacent_face_ids=[0, 1], start_vertex=(1.0, 0.0, 0.0), end_vertex=(1.0, 1.0, 0.0),
        is_seam=False,
    )
    return face_a, face_b, shared_edge


def run_multi_face_fixture_tests() -> list[dict]:
    """
    Task 2 (P3.16): cross-face attachment fixtures. The single-face fixtures
    (`run_fixture_tests`) never exercise attachment between two DIFFERENT
    faces at all -- this is the gap that let the midpoint-based attachment's
    insufficiency reach Part3 undetected. Both fixtures here share one real
    edge between two real faces, each face independently region-partitioned,
    with the two faces' region-crossing points on the shared edge
    DELIBERATELY placed at different locations, so a correct implementation
    must produce more than one sub-interval.
    """
    face_a, face_b, edge = _build_two_face_fixture()
    results = []

    # Fixture I: face A split at y=0.5 (region A0: y<0.5, A1: y>0.5), face B
    # split at y=0.3 (region B0: y<0.3, B1: y>0.3) -- shared edge x=1 should
    # split into exactly 3 sub-intervals: [0,0.3]->(A0,B0), [0.3,0.5]->(A0,B1),
    # [0.5,1]->(A1,B1). A single-midpoint sampler (t=0.5) would see only
    # (A1, B1) for the WHOLE edge and silently miss the [0,0.5) span
    # entirely -- exactly the defect this fixture is built to catch.
    regions_a = [
        FaceRegion(0, Polygon([(0, 0), (1, 0), (1, 0.5), (0, 0.5)]), 0.5),
        FaceRegion(1, Polygon([(0, 0.5), (1, 0.5), (1, 1), (0, 1)]), 0.5),
    ]
    regions_b = [
        FaceRegion(0, Polygon([(1, 0), (2, 0), (2, 0.3), (1, 0.3)]), 0.3),
        FaceRegion(1, Polygon([(1, 0.3), (2, 0.3), (2, 1), (1, 1)]), 0.7),
    ]
    intervals = edge_subinterval_attachment(face_a, face_b, edge, regions_a, regions_b)
    expected = [(0.0, 0.3, 0, 0), (0.3, 0.5, 0, 1), (0.5, 1.0, 1, 1)]
    actual = [(round(iv.t_start, 6), round(iv.t_end, 6), iv.region_a, iv.region_b) for iv in intervals]
    passed = len(actual) == 3 and all(
        abs(a[0] - e[0]) < 1e-6 and abs(a[1] - e[1]) < 1e-6 and a[2] == e[2] and a[3] == e[3]
        for a, e in zip(actual, expected)
    )
    results.append({
        "fixture": "I_two_faces_different_breakpoints", "passed": passed,
        "expected": expected, "actual": actual,
        "notes": "Face A splits the shared edge at y=0.5, face B at y=0.3 -- must yield 3 sub-intervals, not 1.",
    })

    # Fixture J: THREE breakpoints total -- face A splits at y=0.25 and
    # y=0.75 (3 regions), face B splits at y=0.5 (2 regions) -> the union of
    # breakpoints {0.25, 0.5, 0.75} must produce 4 sub-intervals.
    regions_a3 = [
        FaceRegion(0, Polygon([(0, 0), (1, 0), (1, 0.25), (0, 0.25)]), 0.25),
        FaceRegion(1, Polygon([(0, 0.25), (1, 0.25), (1, 0.75), (0, 0.75)]), 0.5),
        FaceRegion(2, Polygon([(0, 0.75), (1, 0.75), (1, 1), (0, 1)]), 0.25),
    ]
    regions_b2 = [
        FaceRegion(0, Polygon([(1, 0), (2, 0), (2, 0.5), (1, 0.5)]), 0.5),
        FaceRegion(1, Polygon([(1, 0.5), (2, 0.5), (2, 1), (1, 1)]), 0.5),
    ]
    intervals2 = edge_subinterval_attachment(face_a, face_b, edge, regions_a3, regions_b2)
    expected2 = [(0.0, 0.25, 0, 0), (0.25, 0.5, 1, 0), (0.5, 0.75, 1, 1), (0.75, 1.0, 2, 1)]
    actual2 = [(round(iv.t_start, 6), round(iv.t_end, 6), iv.region_a, iv.region_b) for iv in intervals2]
    passed2 = len(actual2) == 4 and all(
        abs(a[0] - e[0]) < 1e-6 and abs(a[1] - e[1]) < 1e-6 and a[2] == e[2] and a[3] == e[3]
        for a, e in zip(actual2, expected2)
    )
    results.append({
        "fixture": "J_multiple_breakpoints_both_sides", "passed": passed2,
        "expected": expected2, "actual": actual2,
        "notes": "3 breakpoints total from both sides combined -> 4 sub-intervals, each independently attached.",
    })

    # Fixture L (Task 5): a LEGITIMATE multi-curve junction -- face A's own
    # curve reaches the shared edge at y=0.5, and face B's own INDEPENDENT
    # curve ALSO reaches the shared edge at exactly y=0.5 (coincident, not
    # offset like I/J). This is the case Part3 plausibly has: two different
    # curves genuinely converging at the same physical point. The correct
    # result is exactly 2 sub-intervals (the coincident breakpoint merges
    # into ONE, not two near-duplicate ones) -- verifying the even-degree
    # invariant holds even when multiple curves legitimately meet: at the
    # junction point, the boundary between [0,0.5] and [0.5,1] contributes
    # degree 2 from the edge alone, and each face's own curve terminating
    # exactly there contributes its own even pair, never leaving a dangling
    # single connection.
    regions_a_l = [
        FaceRegion(0, Polygon([(0, 0), (1, 0), (1, 0.5), (0, 0.5)]), 0.5),
        FaceRegion(1, Polygon([(0, 0.5), (1, 0.5), (1, 1), (0, 1)]), 0.5),
    ]
    regions_b_l = [
        FaceRegion(0, Polygon([(1, 0), (2, 0), (2, 0.5), (1, 0.5)]), 0.5),
        FaceRegion(1, Polygon([(1, 0.5), (2, 0.5), (2, 1), (1, 1)]), 0.5),
    ]
    intervals_l = edge_subinterval_attachment(face_a, face_b, edge, regions_a_l, regions_b_l)
    expected_l = [(0.0, 0.5, 0, 0), (0.5, 1.0, 1, 1)]
    actual_l = [(round(iv.t_start, 6), round(iv.t_end, 6), iv.region_a, iv.region_b) for iv in intervals_l]
    passed_l = len(actual_l) == 2 and all(
        abs(a[0] - e[0]) < 1e-6 and abs(a[1] - e[1]) < 1e-6 and a[2] == e[2] and a[3] == e[3]
        for a, e in zip(actual_l, expected_l)
    )
    results.append({
        "fixture": "L_coincident_multi_curve_junction", "passed": passed_l,
        "expected": expected_l, "actual": actual_l,
        "notes": (
            "Face A and face B's own curves both reach the shared edge at EXACTLY y=0.5 "
            "(a legitimate coincident junction, not an offset pair like I/J) -- must merge "
            "into ONE breakpoint (2 sub-intervals), not two near-duplicate breakpoints."
        ),
    })

    return results


def _build_periodic_cylinder_fixture():
    """
    A REAL, standard OCC cylinder (`BRepPrimAPI_MakeCylinder`) -- not a
    hand-built wire, specifically to avoid introducing a construction bug
    into the reference geometry the periodic-seam test relies on. Returns
    (cylinder_face, bottom_cap_face, top_cap_face, rim_edges) as FaceData/
    EdgeData, exercising the SAME `PartGeometry` types production uses.

    The lateral face's own wire references its seam edge TWICE (once at
    each orientation) -- exactly the structure that could, if mishandled,
    create a spurious extra boundary piece or duplicate topology.
    """
    from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCC.Core.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCC.Core.TopAbs import TopAbs_FACE
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
    from OCC.Core.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
    from OCC.Core.BRepTools import breptools
    from OCC.Core.TopoDS import topods

    from backend.models.geometry_models import EdgeData, FaceData

    radius, height = 5.0, 10.0
    axis = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))
    solid = BRepPrimAPI_MakeCylinder(axis, radius, height).Shape()

    lateral_occ = None
    bottom_occ = None
    top_occ = None
    explorer = TopExp_Explorer(solid, TopAbs_FACE)
    while explorer.More():
        face = topods.Face(explorer.Current())
        adaptor = BRepAdaptor_Surface(face)
        if adaptor.GetType() == GeomAbs_Cylinder:
            lateral_occ = face
        elif adaptor.GetType() == GeomAbs_Plane:
            centre = adaptor.Plane().Location()
            if abs(centre.Z()) < 1e-6:
                bottom_occ = face
            else:
                top_occ = face
        explorer.Next()

    u_min, u_max, v_min, v_max = breptools.UVBounds(lateral_occ)
    lateral_area = 2 * math.pi * radius * height
    cap_area = math.pi * radius * radius

    lateral = FaceData(
        face_id=0, occ_face=lateral_occ, surface_type="Cylinder",
        normal=(1.0, 0.0, 0.0), centroid=(radius, 0.0, height / 2), area=lateral_area,
        u_range=(u_min, u_max), v_range=(v_min, v_max), is_reversed=False, normal_valid=True,
    )
    bottom = FaceData(
        face_id=1, occ_face=bottom_occ, surface_type="Plane",
        normal=(0.0, 0.0, -1.0), centroid=(0.0, 0.0, 0.0), area=cap_area,
        u_range=(0.0, 1.0), v_range=(0.0, 1.0), is_reversed=False, normal_valid=True,
    )
    top = FaceData(
        face_id=2, occ_face=top_occ, surface_type="Plane",
        normal=(0.0, 0.0, 1.0), centroid=(0.0, 0.0, height), area=cap_area,
        u_range=(0.0, 1.0), v_range=(0.0, 1.0), is_reversed=False, normal_valid=True,
    )
    return lateral, bottom, top


def run_periodic_seam_fixture_tests() -> list[dict]:
    """
    Task 4 (P3.17): does the lateral cylinder face's own periodic seam --
    its wire references the seam edge TWICE -- create spurious topology?

    With ZERO interior (Track-B) curves, the lateral face is a single sheet
    of material with no dividing curve; the correct answer is exactly ONE
    region, regardless of how many times the seam edge appears in its own
    boundary wire. If the seam is mishandled (e.g. treated as two distinct
    boundary loops instead of one edge referenced twice), `polygonize`
    would either fail to close a valid region or spuriously report more
    than one.
    """
    lateral, bottom, top = _build_periodic_cylinder_fixture()
    results = []

    regions = build_face_regions_for_fixture(lateral)
    expected_regions = 1
    passed = len(regions) == expected_regions
    results.append({
        "fixture": "K_periodic_seam_zero_curves", "passed": passed,
        "expected_regions": expected_regions, "actual_regions": len(regions),
        "notes": "Lateral cylinder face, no interior curves -- seam must not fragment the single region.",
    })

    return results


def build_face_regions_for_fixture(face):
    """Thin wrapper: `build_face_regions` needs a `part`-like object only for `part.face_to_edges`/`part.edges`."""
    class _MiniPart:
        def __init__(self, face):
            edges_by_id = {}
            face_to_edges = {}
            from OCC.Core.TopAbs import TopAbs_EDGE
            from OCC.Core.TopExp import TopExp_Explorer
            from OCC.Core.TopoDS import topods
            from OCC.Core.BRep import BRep_Tool

            seen_edge_keys: dict = {}
            edge_ids: list[int] = []
            explorer = TopExp_Explorer(face.occ_face, TopAbs_EDGE)
            next_id = 0
            while explorer.More():
                occ_edge = topods.Edge(explorer.Current())
                key = occ_edge.TShape()
                if key not in seen_edge_keys:
                    first, last = BRep_Tool.Range(occ_edge)
                    edges_by_id[next_id] = type("E", (), {
                        "edge_id": next_id, "occ_edge": occ_edge,
                    })()
                    seen_edge_keys[key] = next_id
                    edge_ids.append(next_id)
                    next_id += 1
                else:
                    edge_ids.append(seen_edge_keys[key])
                explorer.Next()
            self.edges = list(edges_by_id.values())
            self.face_to_edges = {face.face_id: edge_ids}

    return build_face_regions(_MiniPart(face), face, [])


if __name__ == "__main__":
    results = run_fixture_tests()
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"[{status}] {r['fixture']}: expected={r['expected_regions']} actual={r['actual_regions']} "
              f"adjacency={r['adjacency']}")
        if r["notes"]:
            print(f"         note: {r['notes']}")

    print()
    multi_results = run_multi_face_fixture_tests()
    for r in multi_results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"[{status}] {r['fixture']}: expected={r['expected']} actual={r['actual']}")
        if r["notes"]:
            print(f"         note: {r['notes']}")

    print()
    periodic_results = run_periodic_seam_fixture_tests()
    for r in periodic_results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"[{status}] {r['fixture']}: expected={r['expected_regions']} actual={r['actual_regions']}")
        print(f"         note: {r['notes']}")

    all_passed = (
        all(r["passed"] for r in results)
        and all(r["passed"] for r in multi_results)
        and all(r["passed"] for r in periodic_results)
    )
    print(f"\n{'ALL FIXTURES PASSED' if all_passed else 'SOME FIXTURES FAILED'}")
