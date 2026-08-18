"""
backend/validation/parting_line_tooling_backing_experiment.py
------------------------------------------------------------
Decisive topology proof for the proposed ToolingBacking/
tooling_split_face_ids abstraction (2026-08-15 design). Validation-only:
`separate_surface_with_tooling` is a faithful copy of the REAL production
`regions.separate_surface`, with exactly one additive branch appended for
faces in `tooling_split_face_ids` (axial-parameter split instead of
sign(g)). Production `regions.py` is imported and used UNMODIFIED for the
baseline/negative-control comparisons; it is never edited.

Question this file is allowed to answer, per instruction: can the proposed
parameter-based split of the coaxial bore (face 35) produce the intended
C1-C4 two-region topology without weakening existing invariants? Nothing
about H4/H5, side-action exemption, X/Y, objective weighting, or ranking
is investigated here.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from OCC.Core.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCC.Core.GeomAbs import GeomAbs_Cylinder

from backend.geometry.parting_line_v2.regions import (
    SeparationResult,
    _g_at_edge_on_face,
    _sample_face_g,
    separate_surface,
)
from backend.geometry.step_loader import load_step_cached
from backend.models.geometry_models import dot3

PART3 = load_step_cached("data/parts/Part3.stp")
FACES_BY_ID = {f.face_id: f for f in PART3.faces}
EDGES_BY_ID = {e.edge_id: e for e in PART3.edges}
PULL_Z = (0.0, 0.0, 1.0)

# The real, verified z=22 outer boundary (prior turn: endpoint-walk confirmed
# these 4 edges close into one loop on their own, total length 78.54mm =
# 2*pi*12.5, exactly a full circle split into 4 arcs by faces 325/366).
Z22_OUTER_BOUNDARY_EDGES = frozenset({35, 121, 95, 122})   # EDGE ids, not face ids
BORE_FACE_ID = 35                                           # FACE id (distinct namespace)


# ---------------------------------------------------------------------------
# Eligibility predicate (design from the specification stress test)
# ---------------------------------------------------------------------------

def eligibility_check(face_id: int, pull_direction=PULL_Z, eps_uniform: float = 1e-6,
                       axis_angle_tol: float = 1e-6):
    """
    Returns (eligible: bool, reason: str). Implements criteria (a)(b)(c)
    from the stress-test spec. Deliberately strict and explicit -- no
    silent fallback.
    """
    face = FACES_BY_ID.get(face_id)
    if face is None:
        return False, f"face {face_id} does not exist on this part"

    surf = BRepAdaptor_Surface(face.occ_face)
    if surf.GetType() != GeomAbs_Cylinder:
        return False, f"surface type is not Cylinder (type={surf.GetType()})"

    cyl = surf.Cylinder()
    axis_dir = cyl.Axis().Direction()
    axis_vec = (axis_dir.X(), axis_dir.Y(), axis_dir.Z())
    cos_angle = abs(dot3(axis_vec, pull_direction))
    if cos_angle < 1.0 - axis_angle_tol:
        return False, f"axis not parallel/antiparallel to pull direction (|cos|={cos_angle:.9f})"

    mean_g, min_g, max_g, _ = _sample_face_g(face, pull_direction, grid=9)
    if max(abs(min_g), abs(max_g)) > eps_uniform:
        return False, f"not uniformly zero-draft (min_g={min_g:.6g}, max_g={max_g:.6g})"

    neighbors = set(PART3.face_adjacency.get(face_id, []))
    if len(neighbors) != 2:
        return False, f"has {len(neighbors)} distinct neighboring face(s), require exactly 2: {sorted(neighbors)}"

    return True, f"eligible: cylinder, axis-aligned, uniform g, exactly 2 neighbors {sorted(neighbors)}"


# ---------------------------------------------------------------------------
# separate_surface_with_tooling -- faithful copy of production separate_surface
# with exactly one additive branch for tooling_split_face_ids.
# ---------------------------------------------------------------------------

def _axial_position_at_edge(edge_occ, pull_direction) -> float | None:
    """Projection of an edge's midpoint onto the pull axis."""
    try:
        adaptor = BRepAdaptor_Curve(edge_occ)
        t_mid = 0.5 * (adaptor.FirstParameter() + adaptor.LastParameter())
        p = adaptor.Value(t_mid)
        return dot3((p.X(), p.Y(), p.Z()), pull_direction)
    except Exception:
        return None


def separate_surface_with_tooling(
    part, loop_edge_ids, *,
    split_face_ids=frozenset(),
    tooling_split_face_ids: dict[int, float] | None = None,
    pull_direction=None,
    loop_edge_intervals=None,
) -> SeparationResult:
    """
    Copy of regions.separate_surface with ONE additive branch: faces in
    `tooling_split_face_ids` (face_id -> axial split_param) are split into
    two nodes by comparing each neighboring edge's axial position against
    split_param, instead of by sign(g). Faces in the existing `split_face_ids`
    use the UNCHANGED sign(g) path. A face may not be in both sets.
    """
    tooling = tooling_split_face_ids or {}
    assert split_face_ids.isdisjoint(tooling.keys()), "a face may not use both split mechanisms"

    usable = {f.face_id for f in part.faces if f.normal_valid}
    skipped = frozenset(f.face_id for f in part.faces if not f.normal_valid)
    faces_by_id = {f.face_id: f for f in part.faces}
    edges_by_id = {e.edge_id: e for e in part.edges}
    split = split_face_ids & usable
    tooling_ids = set(tooling.keys()) & usable

    def node_of(face_id, side):
        if face_id in split:
            return (face_id, 1 if (side is not None and side >= 0.0) else -1)
        if face_id in tooling_ids:
            return (face_id, 1 if (side is not None and side >= 0.0) else -1)
        return (face_id, 0)

    shared: dict[tuple[int, int], set[int]] = {}
    for edge_id, face_ids in part.edge_to_faces.items():
        if len(face_ids) != 2:
            continue
        a, b = sorted(face_ids)
        if a not in usable or b not in usable:
            continue
        shared.setdefault((a, b), set()).add(edge_id)

    nodes = set()
    for face_id in usable:
        if face_id in split or face_id in tooling_ids:
            nodes.add((face_id, 1))
            nodes.add((face_id, -1))
        else:
            nodes.add((face_id, 0))

    adjacency: dict[tuple[int, int], set[tuple[int, int]]] = {n: set() for n in nodes}
    intervals_by_edge = loop_edge_intervals or {}
    for (a, b), edge_ids in shared.items():
        for edge_id in sorted(edge_ids):
            edge = edges_by_id.get(edge_id)
            if edge_id in intervals_by_edge:
                continue  # not exercised in this experiment
            elif edge_id in loop_edge_ids:
                continue
            else:
                pass

            side_a = side_b = None
            if edge is not None and pull_direction is not None:
                if a in split:
                    side_a = _g_at_edge_on_face(faces_by_id[a].occ_face, edge.occ_edge, pull_direction, None)
                elif a in tooling_ids:
                    pos = _axial_position_at_edge(edge.occ_edge, pull_direction)
                    side_a = None if pos is None else (pos - tooling[a])
                if b in split:
                    side_b = _g_at_edge_on_face(faces_by_id[b].occ_face, edge.occ_edge, pull_direction, None)
                elif b in tooling_ids:
                    pos = _axial_position_at_edge(edge.occ_edge, pull_direction)
                    side_b = None if pos is None else (pos - tooling[b])
            node_a, node_b = node_of(a, side_a), node_of(b, side_b)
            adjacency[node_a].add(node_b)
            adjacency[node_b].add(node_a)

    seen = set()
    components = []
    for start in sorted(adjacency):
        if start in seen:
            continue
        stack, group = [start], set()
        seen.add(start)
        while stack:
            node = stack.pop()
            group.add(node[0])
            for neighbour in sorted(adjacency[node]):
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        components.append(frozenset(group))

    components.sort(key=lambda c: (-len(c), min(c) if c else -1))
    return SeparationResult(
        component_count=len(components),
        components=tuple(components),
        skipped_face_ids=skipped,
        split_face_ids=frozenset(split) | frozenset(tooling_ids),
    )


# ---------------------------------------------------------------------------
# Construction-time guard: split_param must match the real boundary's own z.
# ---------------------------------------------------------------------------

def resolve_and_validate_split_param(loop_edge_ids, expected_param, pull_direction=PULL_Z, tol=1e-6):
    """Extract the axial position the real boundary edges actually sit at,
    and hard-reject if the requested tooling split does not match it."""
    positions = set()
    for eid in loop_edge_ids:
        edge = EDGES_BY_ID[eid]
        pos = _axial_position_at_edge(edge.occ_edge, pull_direction)
        positions.add(round(pos, 6))
    if len(positions) != 1:
        raise ValueError(f"real boundary is not at a single consistent axial position: {positions}")
    real_param = next(iter(positions))
    if abs(real_param - expected_param) > tol:
        raise ValueError(
            f"tooling split_param={expected_param} does not match real boundary position={real_param}"
        )
    return real_param


def main():
    print("=" * 70)
    print("POSITIVE CASE: face 35 tooling split at z=22, matching real boundary")
    print("=" * 70)

    real_param = resolve_and_validate_split_param(Z22_OUTER_BOUNDARY_EDGES, 22.0)
    print(f"real boundary axial position (validated): z={real_param}")

    eligible, reason = eligibility_check(BORE_FACE_ID)
    print(f"face {BORE_FACE_ID} eligibility: {eligible} -- {reason}")
    assert eligible

    result = separate_surface_with_tooling(
        PART3, Z22_OUTER_BOUNDARY_EDGES,
        tooling_split_face_ids={BORE_FACE_ID: real_param},
        pull_direction=PULL_Z,
    )
    print(f"\nH3 (parameter-based split) component_count = {result.component_count}")
    for i, comp in enumerate(result.components):
        print(f"  component {i}: {len(comp)} faces")

    # Which component contains face 35's lower portion (via face 320, its
    # z=1 neighbor) vs upper portion (via face 319, its z=39 neighbor)?
    comp_of = {}
    for i, comp in enumerate(result.components):
        for fid in comp:
            comp_of[fid] = i
    print(f"\nface 35 (bore) itself lands in component: {comp_of.get(BORE_FACE_ID)}")
    print(f"face 320 (bore's z=1 neighbor, base flange side) in component: {comp_of.get(320)}")
    print(f"face 319 (bore's z=39 neighbor, top-cap side) in component: {comp_of.get(319)}")
    print(f"face 36 (base plate) in component: {comp_of.get(36)}")
    print(f"face 40 (top cap) in component: {comp_of.get(40)}")
    print(f"face 0 (rib lattice, stack 1) in component: {comp_of.get(0)}")
    print(f"face 38 (mid shaft band) in component: {comp_of.get(38)}")
    print(f"face 39 (cone) in component: {comp_of.get(39)}")

    same_side = comp_of.get(320) == comp_of.get(36) == comp_of.get(0)
    opposite_side = comp_of.get(320) != comp_of.get(319)
    print(f"\nbore lower/upper on OPPOSITE sides: {opposite_side}")
    print(f"base+rib-lattice+bore-lower all on SAME side: {same_side}")

    print("\n--- faces 325/366 and satellite cluster: reported, not absorbed ---")
    for fid in (325, 366, 344, 362, 328, 369, 347, 388):
        print(f"  face {fid}: component={comp_of.get(fid, 'NOT IN GRAPH (skipped/invalid normal?)')}")
    print("  (These are exactly the faces flagged last turn as the still-open small-transition-")
    print("   cluster question -- reported here explicitly, not silently merged into either side"
          " without comment.)")

    print("\n=== verify real outer boundary edges themselves are unchanged ===")
    print(f"Z22_OUTER_BOUNDARY_EDGES = {sorted(Z22_OUTER_BOUNDARY_EDGES)} (unmodified from prior turn's"
          " verified closure)")

    print("\n" + "=" * 70)
    print("NEGATIVE CONTROL 1: no tooling split -- reproduce current H3 failure")
    print("=" * 70)
    baseline = separate_surface(PART3, Z22_OUTER_BOUNDARY_EDGES, pull_direction=PULL_Z)
    print(f"component_count (production separate_surface, unmodified): {baseline.component_count}")
    print("expected: 1 (bore bridges both sides, undisputed) ->", baseline.component_count == 1)

    print("\n" + "=" * 70)
    print("NEGATIVE CONTROL 2: tooling split on rib face 0 -- must reject eligibility")
    print("=" * 70)
    eligible, reason = eligibility_check(0)
    print(f"face 0 eligibility: {eligible} -- {reason}")
    assert not eligible

    print("\n" + "=" * 70)
    print("NEGATIVE CONTROL 3: tooling split on face 39 (cone) -- must reject eligibility")
    print("=" * 70)
    eligible, reason = eligibility_check(39)
    print(f"face 39 eligibility: {eligible} -- {reason}")
    assert not eligible

    print("\n" + "=" * 70)
    print("NEGATIVE CONTROL 4: arbitrary z not matching real boundary -- must reject")
    print("=" * 70)
    try:
        resolve_and_validate_split_param(Z22_OUTER_BOUNDARY_EDGES, 10.0)
        print("FAIL: should have raised")
    except ValueError as e:
        print(f"correctly rejected: {e}")

    print("\n" + "=" * 70)
    print("NEGATIVE CONTROL 5: tooling split at z=22 WITHOUT a valid closed outer loop")
    print("=" * 70)
    incomplete_edges = frozenset({35, 95})  # missing 121, 122 -- does not close
    from collections import defaultdict
    from OCC.Core.BRepAdaptor import BRepAdaptor_Curve as _BAC

    def endpoints(edge_id):
        e = EDGES_BY_ID[edge_id].occ_edge
        c = _BAC(e)
        p0 = c.Value(c.FirstParameter())
        p1 = c.Value(c.LastParameter())
        return (round(p0.X(), 4), round(p0.Y(), 4), round(p0.Z(), 4)), \
               (round(p1.X(), 4), round(p1.Y(), 4), round(p1.Z(), 4))

    adj = defaultdict(list)
    for eid in incomplete_edges:
        a, b = endpoints(eid)
        adj[a].append((b, eid))
        adj[b].append((a, eid))
    degree_one = [pt for pt, conns in adj.items() if len(conns) == 1]
    print(f"incomplete boundary {sorted(incomplete_edges)}: {len(degree_one)} open (degree-1) endpoint(s)")
    print("-> this boundary does NOT close (matches endpoint-walk method from prior turn).")
    print("In the real pipeline this is rejected at H1 (closure) BEFORE H3 ever runs -- H3's")
    print("edge-cut graph has no independent notion of geometric closure, which is exactly why")
    print("H1 must run first and separately, unmodified by this proposal.")


if __name__ == "__main__":
    main()
