"""
backend/validation/parting_line_mechanism2_diagnosis.py
-----------------------------------------------------------
READ-ONLY diagnosis of mechanism 2 (D-023's "face-317-style" case, still
open) — Track A and Track B independently find "crossings" on/near the same
shared B-Rep edge, tens of mm apart, with the snap mechanism proven
mathematically exact (D-022/D-023 investigation). This script does NOT
propose or apply a fix. It answers, with direct evidence:

    When g ~= 0 along a trimmed boundary, what is the mathematically
    correct interpretation of that contour?

For one face (default: Part3 face 317, direction +X):

1. Reconstructs the COMPLETE Track-B contour (every chain, every point,
   full g(u,v) profile -- not just the boundary transitions this
   investigation traced earlier).
2. Reports where |g| ~= 0 along each chain, and whether that holds
   consistently along a long run (tangential-boundary signature) or only at
   isolated points (transversal-crossing signature).
3. Independently recomputes Track A's own g_a/g_b straddle test on the
   shared edge, at its actual segment boundary.
4. Converts BOTH Track A's and Track B's relevant points to the SAME edge's
   own parametrisation (projection, not distance-tolerance merging) and
   reports edge-parameter separation alongside 3-D separation.
5. Reports the face's coarse pre-pass g range (the same numbers
   `detect_face_silhouettes` itself uses to decide degenerate vs not), so
   whether face 317 is globally tangential, locally tangential along one
   boundary strip only, or genuinely transversal is a measured fact, not an
   assumption.

Never merges, snaps, or chooses between the two tracks' points. Never widens
a tolerance. Read-only: does not modify H0, mechanism 1, tolerances,
welding, enumeration, ranking, or pull-direction handling.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DIRECTIONS = {
    "+X": (1.0, 0.0, 0.0), "-X": (-1.0, 0.0, 0.0),
    "+Y": (0.0, 1.0, 0.0), "-Y": (0.0, -1.0, 0.0),
    "+Z": (0.0, 0.0, 1.0), "-Z": (0.0, 0.0, -1.0),
}


def _diagnose(part_path: str, direction_label: str, face_id: int, edge_id: int) -> dict:
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
    from OCC.Core.BRepTools import breptools
    from OCC.Core.BRepTopAdaptor import BRepTopAdaptor_FClass2d
    from OCC.Core.GeomAbs import GeomAbs_BezierSurface, GeomAbs_BSplineSurface, GeomAbs_Circle, GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Line, GeomAbs_Plane, GeomAbs_Sphere
    from OCC.Core.GeomAPI import GeomAPI_ProjectPointOnCurve
    from OCC.Core.gp import gp_Pnt, gp_Pnt2d
    from OCC.Core.TopAbs import TopAbs_IN, TopAbs_ON

    from backend.config import settings
    from backend.geometry.parting_line_v2.contracts import PullDirectionInput
    from backend.geometry.parting_line_v2.engine import _bbox_diagonal
    from backend.geometry.parting_line_v2.track_a import detect_edge_silhouettes, _g_on_both_faces
    from backend.geometry.parting_line_v2.track_b import (
        _FaceField, _cell_segments, _chain, _grid_resolution,
    )
    from backend.geometry.parting_line_v2.types import EdgeBacking
    from backend.geometry.step_loader import load_step

    cfg = settings.dfm.parting_line_v2
    part = load_step(part_path)
    direction = DIRECTIONS[direction_label]
    bbox_diagonal = _bbox_diagonal(part)

    face_data = next(f for f in part.faces if f.face_id == face_id)
    face = face_data.occ_face
    edge_data = next(e for e in part.edges if e.edge_id == edge_id)
    edge = edge_data.occ_edge

    # --- 5. Coarse pre-pass, EXACTLY as detect_face_silhouettes computes it -
    u_min, u_max, v_min, v_max = breptools.UVBounds(face)
    field = _FaceField(face, direction)
    coarse = 5
    coarse_values = []
    for i in range(coarse):
        for j in range(coarse):
            u = u_min + (u_max - u_min) * (i + 0.5) / coarse
            v = v_min + (v_max - v_min) * (j + 0.5) / coarse
            g = field.g(u, v)
            if g is not None:
                coarse_values.append(g)
    epsilon = cfg.silhouette_epsilon

    surf_type_names = {
        GeomAbs_Plane: "Plane", GeomAbs_Cylinder: "Cylinder", GeomAbs_Cone: "Cone",
        GeomAbs_Sphere: "Sphere", GeomAbs_BezierSurface: "Bezier", GeomAbs_BSplineSurface: "BSpline",
    }
    from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
    surf_adaptor = BRepAdaptor_Surface(face, True)
    surface_type = surf_type_names.get(surf_adaptor.GetType(), str(surf_adaptor.GetType()))

    # --- 1/2. Full Track-B contour on this face, every chain, every point --
    tau_sag = max(cfg.sag_tolerance_rel * bbox_diagonal, 1e-9)
    n_u, n_v = _grid_resolution(face, u_max - u_min, v_max - v_min, cfg, tau_sag)
    us = [u_min + (u_max - u_min) * i / (n_u - 1) for i in range(n_u)]
    vs = [v_min + (v_max - v_min) * j / (n_v - 1) for j in range(n_v)]
    grid = [[field.g(u, v) for v in vs] for u in us]

    pieces = []
    for i in range(n_u - 1):
        for j in range(n_v - 1):
            g00, g10 = grid[i][j], grid[i + 1][j]
            g11, g01 = grid[i + 1][j + 1], grid[i][j + 1]
            if None in (g00, g10, g11, g01):
                continue
            pieces.extend(_cell_segments(
                field, us[i], us[i + 1], vs[j], vs[j + 1], g00, g10, g11, g01, cfg
            ))
    chain_tolerance = min(
        (u_max - u_min) / max(n_u - 1, 1), (v_max - v_min) / max(n_v - 1, 1)
    ) * 1e-3
    classifier = BRepTopAdaptor_FClass2d(face, 1e-7)
    tau_silhouette = cfg.silhouette_epsilon * cfg.silhouette_error_factor

    chains_report = []
    for chain in _chain(pieces, max(chain_tolerance, 1e-12)):
        g_values = [field.g(u, v) for u, v in chain]
        g_values = [g for g in g_values if g is not None]
        v_values = [v for _, v in chain]
        u_values = [u for u, _ in chain]
        states = [
            {TopAbs_IN: "IN", TopAbs_ON: "ON"}.get(classifier.Perform(gp_Pnt2d(u, v)), "OUT")
            for u, v in chain
        ]
        # Is this chain "pinned" to a boundary (v or u nearly constant across
        # the whole run)? That's the geometric signature of "following the
        # trim boundary" rather than crossing through the interior.
        v_span = max(v_values) - min(v_values) if v_values else 0.0
        u_span = max(u_values) - min(u_values) if u_values else 0.0
        domain_v_span = v_max - v_min
        domain_u_span = u_max - u_min
        chains_report.append({
            "point_count": len(chain),
            "u_range": [min(u_values), max(u_values)] if u_values else None,
            "v_range": [min(v_values), max(v_values)] if v_values else None,
            "v_span_fraction_of_domain": (v_span / domain_v_span) if domain_v_span else None,
            "u_span_fraction_of_domain": (u_span / domain_u_span) if domain_u_span else None,
            "pinned_to_v_boundary": (
                min(v_values) <= v_min + 1e-6 and max(v_values) <= v_min + 1e-6
            ) or (
                min(v_values) >= v_max - 1e-6 and max(v_values) >= v_max - 1e-6
            ) if v_values else False,
            "g_min": min(g_values) if g_values else None,
            "g_max": max(g_values) if g_values else None,
            "g_mean_abs": (sum(abs(g) for g in g_values) / len(g_values)) if g_values else None,
            "g_all_within_epsilon": all(abs(g) <= epsilon for g in g_values) if g_values else None,
            "fraction_within_tau_silhouette": (
                sum(1 for g in g_values if abs(g) <= tau_silhouette) / len(g_values)
            ) if g_values else None,
            "start": {"uv": chain[0], "state": states[0], "g": g_values[0] if g_values else None},
            "end": {"uv": chain[-1], "state": states[-1], "g": g_values[-1] if g_values else None},
        })

    # --- 3. Track A's own g_a/g_b straddle test on this edge, independently
    # recomputed (not assumed from stored backing) -------------------------
    track_a = detect_edge_silhouettes(part, direction, cfg=cfg, bbox_diagonal_mm=bbox_diagonal)
    track_a_on_edge = [
        s for s in track_a.segments
        if isinstance(s.backing, EdgeBacking) and s.backing.edge_id == edge_id
    ]

    faces_by_id = {f.face_id: f for f in part.faces}
    adjacent = edge_data.adjacent_face_ids
    face_a_occ = faces_by_id[adjacent[0]].occ_face if len(adjacent) > 0 else None
    face_b_occ = faces_by_id[adjacent[1]].occ_face if len(adjacent) > 1 else None

    track_a_details = []
    for seg in track_a_on_edge:
        b = seg.backing
        g_at_start = _g_on_both_faces(edge, face_a_occ, face_b_occ, b.t_start, direction) if face_a_occ and face_b_occ else None
        g_at_end = _g_on_both_faces(edge, face_a_occ, face_b_occ, b.t_end, direction) if face_a_occ and face_b_occ else None
        track_a_details.append({
            "segment_id": seg.segment_id, "kind": seg.kind,
            "t_start": b.t_start, "t_end": b.t_end,
            "g_a_g_b_at_t_start": g_at_start, "g_a_g_b_at_t_end": g_at_end,
            "straddles_at_t_start": (min(g_at_start) <= 0 <= max(g_at_start)) if g_at_start else None,
            "straddles_at_t_end": (min(g_at_end) <= 0 <= max(g_at_end)) if g_at_end else None,
            "start_point": seg.start, "end_point": seg.end,
        })

    # --- Edge 52's own type / periodicity / parameter range ---------------
    adaptor = BRepAdaptor_Curve(edge)
    curve_type_names = {GeomAbs_Line: "Line", GeomAbs_Circle: "Circle"}
    edge_info = {
        "edge_id": edge_id, "adjacent_face_ids": list(adjacent),
        "curve_type": curve_type_names.get(adaptor.GetType(), str(adaptor.GetType())),
        "is_periodic": adaptor.IsPeriodic() if hasattr(adaptor, "IsPeriodic") else None,
        "is_closed": adaptor.IsClosed() if hasattr(adaptor, "IsClosed") else None,
        "t_first": adaptor.FirstParameter(), "t_last": adaptor.LastParameter(),
        "length_mm": edge_data.length,
    }

    # --- 4. Project the Track-B boundary-chain endpoints onto edge_id's own
    # curve, and get their edge-parameter + 3D separation from Track A's
    # segment endpoints -- projection, never distance-tolerance merging.
    curve, first, last = BRep_Tool.Curve(edge)
    track_b_on_edge = []
    for chain in chains_report:
        for label, endpoint in (("start", chain["start"]), ("end", chain["end"])):
            u, v = endpoint["uv"]
            point3d = field.point(u, v)
            if point3d is None:
                continue
            projector = GeomAPI_ProjectPointOnCurve(gp_Pnt(*point3d), curve, first, last)
            if projector.NbPoints() == 0:
                continue
            proj_distance = float(projector.LowerDistance())
            proj_t = float(projector.LowerDistanceParameter())
            track_b_on_edge.append({
                "chain_endpoint": label, "uv": [u, v], "g": endpoint["g"],
                "point_3d": list(point3d), "projected_edge_t": proj_t,
                "distance_to_edge_mm": proj_distance,
            })

    comparisons = []
    for tb in track_b_on_edge:
        if tb["distance_to_edge_mm"] > 1e-3:
            continue  # not actually on this edge
        for ta in track_a_details:
            for which, ta_t, ta_point in (
                ("t_start", ta["t_start"], ta["start_point"]),
                ("t_end", ta["t_end"], ta["end_point"]),
            ):
                comparisons.append({
                    "track_b_chain_endpoint": tb["chain_endpoint"],
                    "track_b_edge_t": tb["projected_edge_t"],
                    "track_a_segment_id": ta["segment_id"],
                    "track_a_edge_t_which": which, "track_a_edge_t": ta_t,
                    "edge_parameter_delta": tb["projected_edge_t"] - ta_t,
                    "point_3d_distance_mm": math.dist(tb["point_3d"], ta_point),
                })

    return {
        "direction_label": direction_label, "direction": list(direction),
        "face_id": face_id, "surface_type": surface_type,
        "face_uv_bounds": [u_min, u_max, v_min, v_max],
        "coarse_pre_pass": {
            "n": len(coarse_values),
            "min": min(coarse_values) if coarse_values else None,
            "max": max(coarse_values) if coarse_values else None,
            "max_abs": max((abs(x) for x in coarse_values), default=None),
            "silhouette_epsilon": epsilon,
            "classified_degenerate": (
                max((abs(x) for x in coarse_values), default=1.0) <= epsilon
            ) if coarse_values else None,
            "sign_changes": (min(coarse_values) < 0 < max(coarse_values)) if coarse_values else None,
        },
        "track_b_chains": chains_report,
        "track_a_on_shared_edge": track_a_details,
        "shared_edge": edge_info,
        "track_b_projected_onto_shared_edge": track_b_on_edge,
        "track_a_vs_track_b_on_shared_edge": comparisons,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part", default=str(REPO_ROOT / "data" / "parts" / "Part3.stp"))
    parser.add_argument("--direction", default="+X")
    parser.add_argument("--face", type=int, default=317)
    parser.add_argument("--edge", type=int, default=52)
    parser.add_argument("--json", default="reports/mechanism2_diagnosis_face317.json")
    args = parser.parse_args(argv)

    result = _diagnose(args.part, args.direction, args.face, args.edge)

    print(f"=== {Path(args.part).stem} @ {args.direction}, face {args.face}, edge {args.edge} ===")
    print(f"surface type: {result['surface_type']}")
    print(f"face UV bounds: {result['face_uv_bounds']}")
    print(f"coarse pre-pass: {result['coarse_pre_pass']}")
    print(f"\nshared edge: {result['shared_edge']}")
    print(f"\ntrack A segments on this edge: {len(result['track_a_on_shared_edge'])}")
    for ta in result["track_a_on_shared_edge"]:
        print(f"  {ta}")
    print(f"\ntrack B chains on face {args.face}: {len(result['track_b_chains'])}")
    for i, c in enumerate(result["track_b_chains"]):
        print(f"  chain {i}: n={c['point_count']} v_range={c['v_range']} "
              f"(span={c['v_span_fraction_of_domain']:.3f} of domain) "
              f"pinned_to_v_boundary={c['pinned_to_v_boundary']} "
              f"g=[{c['g_min']:.6f},{c['g_max']:.6f}] mean|g|={c['g_mean_abs']:.6f} "
              f"all_within_eps={c['g_all_within_epsilon']} "
              f"frac_within_tau_silhouette={c['fraction_within_tau_silhouette']:.3f}")
    print(f"\ntrack A vs track B on shared edge {args.edge}:")
    for cmp in result["track_a_vs_track_b_on_shared_edge"]:
        print(f"  {cmp}")

    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nreport -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
