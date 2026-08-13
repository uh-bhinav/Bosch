"""
backend/validation/parting_line_independent_separation_test.py
------------------------------------------------------------
P3.11 Step 1/2 (2026-08-13): a FRESH, independently-coded implementation
of "does this closed curve separate the B-Rep's face-adjacency graph into
two meaningful regions" -- deliberately NOT importing or calling
`backend.geometry.parting_line_v2.regions.separate_surface` or any of its
helpers (`_g_at_edge_on_face`, `_uncovered_parameter`, etc).

There is one correct mathematical formalization of "does a closed curve on
a B-Rep separate it into two regions": cut the face-adjacency graph along
the curve's covered locus and count connected components. There is no
alternative, equally-meaningful definition to substitute -- so
"independent" here means independently-IMPLEMENTED (own sign computation
via direct GeomLProp calls, own adjacency construction, own component
counting, own interval-arithmetic for partially-covered periodic edges),
not a different mathematical question. This lets a bug or discrepancy in
`regions.py`'s specific implementation surface by comparison, without
assuming the production code is correct a priori.

Classification (S0-S3), per the standing instruction:
    S0 = closed but does not separate (region_count == 1, or > 2)
    S1 = separates, but one region is a tiny/local sliver (< S1_AREA_FRACTION
         of total part area)
    S2 = separates the main body into two genuinely meaningful regions
    S3 = separates into two meaningful regions, but the DIRECTION-CONSISTENCY
         of the split is questionable (checked via signed mean-normal dot
         product per region -- a cheap independent proxy for H4, not H4
         itself)

Read-only. No production code touched.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

#: below this fraction of total part area, a "separated" region is
#: considered a local sliver, not a genuine mold half (S1, not S2)
S1_AREA_FRACTION = 0.05


@dataclass(frozen=True)
class IndependentSeparationResult:
    component_count: int
    component_face_counts: tuple
    component_areas_mm2: tuple
    smaller_region_area_fraction: float
    classification: str
    mean_normal_dot_region_a: float | None
    mean_normal_dot_region_b: float | None
    notes: tuple = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "component_count": self.component_count,
            "component_face_counts": list(self.component_face_counts),
            "component_areas_mm2": list(self.component_areas_mm2),
            "smaller_region_area_fraction": self.smaller_region_area_fraction,
            "classification": self.classification,
            "mean_normal_dot_region_a": self.mean_normal_dot_region_a,
            "mean_normal_dot_region_b": self.mean_normal_dot_region_b,
            "notes": list(self.notes),
        }


def _independent_g(occ_face, occ_edge_or_none, u, v, direction, is_reversed):
    """Fresh sign(g) computation: direct GeomLProp call, not `_g_at_edge_on_face`."""
    from OCC.Core.GeomLProp import GeomLProp_SLProps
    from OCC.Core.BRep import BRep_Tool

    surface = BRep_Tool.Surface(occ_face)
    try:
        props = GeomLProp_SLProps(surface, u, v, 1, 1e-9)
        if not props.IsNormalDefined():
            return None
        n = props.Normal()
        nx, ny, nz = n.X(), n.Y(), n.Z()
        if is_reversed:
            nx, ny, nz = -nx, -ny, -nz
        return nx * direction[0] + ny * direction[1] + nz * direction[2]
    except Exception:
        return None


def _independent_uncovered_intervals(full_range, covered_intervals):
    """Fresh interval-complement arithmetic (own implementation)."""
    if not covered_intervals:
        return [full_range]
    lo, hi = full_range
    merged = sorted(covered_intervals)
    result = []
    cursor = lo
    for a, b in merged:
        a = max(a, lo)
        b = min(b, hi)
        if a > cursor:
            result.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < hi:
        result.append((cursor, hi))
    return result


def independent_separation_test(
    part,
    direction: tuple,
    loop_edge_intervals: dict,   # edge_id -> list[(t_start, t_end)] COVERED by the candidate
    split_face_ids: set,          # faces with a Track-B interior curve on them
) -> IndependentSeparationResult:
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.TopAbs import TopAbs_REVERSED

    n = math.sqrt(sum(c * c for c in direction))
    d = tuple(c / n for c in direction)

    faces_by_id = {f.face_id: f for f in part.faces}
    edges_by_id = {e.edge_id: e for e in part.edges}
    usable = {fid for fid, f in faces_by_id.items() if f.normal_valid}
    split = set(split_face_ids) & usable

    def node_of(face_id, side):
        if face_id not in split:
            return (face_id, 0)
        return (face_id, 1 if (side is not None and side >= 0.0) else -1)

    # own face-adjacency-by-shared-edge construction (from raw B-Rep topology)
    shared: dict[tuple[int, int], set[int]] = {}
    for edge_id, face_ids in part.edge_to_faces.items():
        if len(face_ids) != 2:
            continue
        a, b = sorted(face_ids)
        if a not in usable or b not in usable:
            continue
        shared.setdefault((a, b), set()).add(edge_id)

    # Unconditionally create both (+1)/(-1) nodes for every split face, even
    # if one side ends up with zero adjacency edges -- matching production's
    # own `nodes.add((face_id, 1)); nodes.add((face_id, -1))` (regions.py
    # lines 271-272). A first version of this function only added nodes
    # that appeared via some edge relation, silently DROPPING isolated
    # split-face halves -- found by direct comparison against production
    # on Part3 +Y's largest candidate: this test reported 2 components,
    # production reported 3, and tracing showed the missing node was a
    # genuinely isolated (face, +1) half (zero edges reach it) that
    # production correctly counts as its own component and this test was
    # silently omitting. Fixed to match production's node-construction
    # discipline exactly, since that is the more complete and correct
    # behavior, not a bug to route around.
    adjacency: dict[tuple, set[tuple]] = {}
    for face_id in usable:
        if face_id in split:
            adjacency.setdefault((face_id, 1), set())
            adjacency.setdefault((face_id, -1), set())
        else:
            adjacency.setdefault((face_id, 0), set())
    for (a, b), edge_ids in shared.items():
        for edge_id in sorted(edge_ids):
            edge = edges_by_id.get(edge_id)
            if edge is None:
                continue
            occ_edge = edge.occ_edge
            first, last = BRep_Tool.Range(occ_edge)
            covered = loop_edge_intervals.get(edge_id, [])
            free_intervals = _independent_uncovered_intervals((first, last), covered)
            if not free_intervals:
                continue  # fully covered -- cut
            # sample the midpoint of the LARGEST free interval for sign evaluation
            free_intervals.sort(key=lambda iv: iv[1] - iv[0], reverse=True)
            t_mid = (free_intervals[0][0] + free_intervals[0][1]) / 2.0

            from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
            curve = BRepAdaptor_Curve(occ_edge)
            pnt = curve.Value(t_mid)

            side_a = side_b = None
            for face_id, target in ((a, "a"), (b, "b")):
                if face_id not in split:
                    continue
                face = faces_by_id[face_id]
                occ_face = face.occ_face
                from OCC.Core.BRepTools import breptools
                from OCC.Core.GeomAPI import GeomAPI_ProjectPointOnSurf
                surf = BRep_Tool.Surface(occ_face)
                proj = GeomAPI_ProjectPointOnSurf(pnt, surf)
                if proj.NbPoints() < 1:
                    continue
                u, v = proj.LowerDistanceParameters()
                is_reversed = occ_face.Orientation() == TopAbs_REVERSED
                g = _independent_g(occ_face, None, u, v, d, is_reversed)
                if target == "a":
                    side_a = g
                else:
                    side_b = g

            na, nb = node_of(a, side_a), node_of(b, side_b)
            adjacency.setdefault(na, set()).add(nb)
            adjacency.setdefault(nb, set()).add(na)

    # component search (own BFS)
    all_nodes = set(adjacency)
    seen = set()
    components = []
    for start in all_nodes:
        if start in seen:
            continue
        stack, group = [start], set()
        seen.add(start)
        while stack:
            node = stack.pop()
            group.add(node)
            for nb in adjacency.get(node, ()):
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        components.append(group)

    def area_of(comp):
        total = 0.0
        for face_id, _side in comp:
            total += faces_by_id[face_id].area
        return total

    def facecount_of(comp):
        return len({face_id for face_id, _side in comp})

    areas = sorted((area_of(c) for c in components), reverse=True)
    face_counts = sorted((facecount_of(c) for c in components), reverse=True)
    total_area = sum(f.area for f in part.faces if f.face_id in usable)
    n_components = len(components)

    smaller_frac = (areas[1] / total_area) if len(areas) >= 2 and total_area else 0.0

    notes = []
    if n_components != 2:
        classification = "S0"
        notes.append(f"component_count={n_components}, not 2")
    elif smaller_frac < S1_AREA_FRACTION:
        classification = "S1"
        notes.append(f"smaller region is only {smaller_frac:.1%} of total area -- local sliver")
    else:
        # cheap independent orientation proxy: mean g sign consistency per region
        comp_a, comp_b = sorted(components, key=area_of, reverse=True)[:2]

        def mean_dot(comp):
            vals = []
            for face_id, side in comp:
                face = faces_by_id[face_id]
                if face_id in split:
                    vals.append(1.0 if side >= 0 else -1.0)
                else:
                    vals.append(face.signed_dot(d))
            return sum(vals) / len(vals) if vals else 0.0

        dot_a = mean_dot(comp_a)
        dot_b = mean_dot(comp_b)
        if (dot_a > 0) != (dot_b > 0) or abs(dot_a) < 0.05 or abs(dot_b) < 0.05:
            classification = "S2"
        else:
            classification = "S3"
            notes.append(f"regions do not show clean opposite-sign orientation: dot_a={dot_a:.3f} dot_b={dot_b:.3f}")

        return IndependentSeparationResult(
            component_count=n_components,
            component_face_counts=tuple(face_counts),
            component_areas_mm2=tuple(round(a, 2) for a in areas),
            smaller_region_area_fraction=round(smaller_frac, 4),
            classification=classification,
            mean_normal_dot_region_a=round(dot_a, 4),
            mean_normal_dot_region_b=round(dot_b, 4),
            notes=tuple(notes),
        )

    return IndependentSeparationResult(
        component_count=n_components,
        component_face_counts=tuple(face_counts),
        component_areas_mm2=tuple(round(a, 2) for a in areas),
        smaller_region_area_fraction=round(smaller_frac, 4),
        classification=classification,
        mean_normal_dot_region_a=None,
        mean_normal_dot_region_b=None,
        notes=tuple(notes),
    )
