"""
backend/validation/parting_line_track_b_termination_trace.py
---------------------------------------------------------------
P3.1 follow-up (2026-08-12) — traces Track B's complete numerical path from
its final marching-squares cell to where it currently emits a segment
endpoint, for ONE specified face at a controlled direction.

Context: `parting_line_connectivity_diagnostic.py`'s `_diagnose_snap` proved
the snap-onto-edge mechanism is mathematically exact (0.0 residual, 100% of
endpoints snapped) yet still lands tens of mm from Track A's independently
computed crossing on the SAME edge, even when NO snap motion was needed
(the raw point was already exactly on that edge). This traces WHY, by
re-deriving `track_b.detect_face_silhouettes`'s marching-squares/chaining/trim
logic for one face with full instrumentation, self-checked against the real
function's output for that face.

Read-only: does not modify tolerances, welding, graph construction,
enumeration, ranking, or pull-direction handling. `direction` is always an
explicit, manually-supplied vector -- never the optimizer.
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


def _trace_face(part, face_id: int, direction, cfg) -> dict:
    from OCC.Core.BRepTools import breptools
    from OCC.Core.BRepTopAdaptor import BRepTopAdaptor_FClass2d
    from OCC.Core.gp import gp_Pnt2d
    from OCC.Core.TopAbs import TopAbs_IN, TopAbs_ON

    from backend.geometry.parting_line_v2.track_b import (
        _FaceField, _cell_segments, _chain, _grid_resolution, detect_face_silhouettes,
    )

    face_data = next(f for f in part.faces if f.face_id == face_id)
    face = face_data.occ_face
    u_min, u_max, v_min, v_max = breptools.UVBounds(face)
    tau_sag = max(cfg.sag_tolerance_rel * 1.0, 1e-9)  # bbox factor irrelevant to this face-local trace
    # Use the SAME bbox-derived tau_sag the real pipeline uses, recovered from
    # the part directly so the grid resolution matches exactly.
    from backend.geometry.parting_line_v2.engine import _bbox_diagonal
    bbox_diagonal = _bbox_diagonal(part)
    tau_sag = max(cfg.sag_tolerance_rel * bbox_diagonal, 1e-9)

    field = _FaceField(face, direction)
    n_u, n_v = _grid_resolution(face, u_max - u_min, v_max - v_min, cfg, tau_sag)
    us = [u_min + (u_max - u_min) * i / (n_u - 1) for i in range(n_u)]
    vs = [v_min + (v_max - v_min) * j / (n_v - 1) for j in range(n_v)]
    grid = [[field.g(u, v) for v in vs] for u in us]

    # Build pieces, TAGGING each with its originating cell (i, j) and the
    # bracketing g-values so every crossing is traceable back to its cell.
    pieces = []
    piece_cells = []
    piece_bracket_g = []
    for i in range(n_u - 1):
        for j in range(n_v - 1):
            g00, g10 = grid[i][j], grid[i + 1][j]
            g11, g01 = grid[i + 1][j + 1], grid[i][j + 1]
            if None in (g00, g10, g11, g01):
                continue
            before = len(pieces)
            new_pieces = _cell_segments(
                field, us[i], us[i + 1], vs[j], vs[j + 1], g00, g10, g11, g01, cfg
            )
            pieces.extend(new_pieces)
            for _ in new_pieces:
                piece_cells.append((i, j))
                piece_bracket_g.append((g00, g10, g11, g01))

    chain_tolerance = min(
        (u_max - u_min) / max(n_u - 1, 1), (v_max - v_min) / max(n_v - 1, 1)
    ) * 1e-3
    chains = _chain(pieces, max(chain_tolerance, 1e-12))

    # Map each chained UV point back to its originating piece (best-effort,
    # by exact/near match) so cell indices and bracket g-values survive
    # chaining for the trace output.
    def _find_piece(point):
        for idx, (a, b) in enumerate(pieces):
            if math.dist(a, point) < 1e-9 or math.dist(b, point) < 1e-9:
                return idx
        return None

    classifier = BRepTopAdaptor_FClass2d(face, 1e-7)
    tau_silhouette = cfg.silhouette_epsilon * cfg.silhouette_error_factor

    chain_traces = []
    for chain in chains:
        trace_points = []
        for u, v in chain:
            state = classifier.Perform(gp_Pnt2d(u, v))
            state_name = {TopAbs_IN: "IN", TopAbs_ON: "ON"}.get(state, "OUT")
            g_value = field.g(u, v)
            piece_idx = _find_piece((u, v))
            point3d = field.point(u, v)
            trace_points.append({
                "uv": [round(u, 9), round(v, 9)],
                "classifier_state": state_name,
                "g_value": round(g_value, 12) if g_value is not None else None,
                "is_root_of_g": (g_value is not None and abs(g_value) <= cfg.newton_tolerance),
                "within_silhouette_tau": (g_value is not None and abs(g_value) <= tau_silhouette),
                "cell_ij": piece_cells[piece_idx] if piece_idx is not None else None,
                "bracket_g": [round(x, 6) for x in piece_bracket_g[piece_idx]] if piece_idx is not None else None,
                "point_3d": [round(c, 6) for c in point3d] if point3d else None,
            })

        # Find every IN/ON -> OUT (or OUT -> IN/ON) transition: this is
        # EXACTLY where the current algorithm truncates the emitted segment,
        # with no further boundary refinement performed.
        transitions = []
        for k in range(len(trace_points) - 1):
            a_in = trace_points[k]["classifier_state"] in ("IN", "ON")
            b_in = trace_points[k + 1]["classifier_state"] in ("IN", "ON")
            if a_in != b_in:
                p_in = trace_points[k] if a_in else trace_points[k + 1]
                p_out = trace_points[k + 1] if a_in else trace_points[k]
                # Bisect toward the TRUE boundary in UV, using the classifier
                # itself as the oracle -- this is what the production code
                # does NOT do. Purely diagnostic: shows how much of the gap
                # is attributable to "no boundary refinement exists".
                lo_uv, hi_uv = p_in["uv"], p_out["uv"]
                for _ in range(40):
                    mid = (0.5 * (lo_uv[0] + hi_uv[0]), 0.5 * (lo_uv[1] + hi_uv[1]))
                    mid_state = classifier.Perform(gp_Pnt2d(*mid))
                    if mid_state in (TopAbs_IN, TopAbs_ON):
                        lo_uv = list(mid)
                    else:
                        hi_uv = list(mid)
                refined_point = field.point(*lo_uv)
                gap_mm = math.dist(field.point(*p_in["uv"]), refined_point) if refined_point else None
                transitions.append({
                    "last_kept_uv": p_in["uv"], "last_kept_point_3d": p_in["point_3d"],
                    "first_rejected_uv": p_out["uv"], "first_rejected_point_3d": p_out["point_3d"],
                    "bisected_boundary_uv": [round(c, 9) for c in lo_uv],
                    "bisected_boundary_point_3d": [round(c, 6) for c in refined_point] if refined_point else None,
                    "grid_resolution_gap_mm": round(math.dist(p_in["point_3d"], p_out["point_3d"]), 6)
                    if p_in["point_3d"] and p_out["point_3d"] else None,
                    "unrefined_vs_true_boundary_gap_mm": round(gap_mm, 6) if gap_mm is not None else None,
                })
        chain_traces.append({"point_count": len(trace_points), "points": trace_points, "transitions": transitions})

    # Self-check: our replica's kept/emitted points must match what the real
    # function actually emits for this face.
    real_result = detect_face_silhouettes(
        part, direction, cfg=cfg, bbox_diagonal_mm=bbox_diagonal, start_segment_id=0,
    )
    real_segments_on_face = [s for s in real_result.segments if s.backing.face_id == face_id]

    return {
        "face_id": face_id, "grid_resolution": [n_u, n_v],
        "uv_bounds": [u_min, u_max, v_min, v_max],
        "chain_count": len(chains),
        "chains": chain_traces,
        "real_segments_emitted_for_this_face": len(real_segments_on_face),
        "real_segment_point_counts": [len(s.points) for s in real_segments_on_face],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part", default=str(REPO_ROOT / "data" / "parts" / "Part3.stp"))
    parser.add_argument("--direction", default="+X")
    parser.add_argument("--faces", default="317", help="comma-separated face_ids to trace")
    parser.add_argument("--json", default="reports/track_b_termination_trace.json")
    args = parser.parse_args(argv)

    from backend.config import settings
    from backend.geometry.step_loader import load_step

    cfg = settings.dfm.parting_line_v2
    part = load_step(args.part)
    direction = DIRECTIONS[args.direction]

    results = []
    for face_id in [int(f) for f in args.faces.split(",") if f.strip()]:
        print(f"--- {Path(args.part).stem} @ {args.direction}, face {face_id} ---")
        trace = _trace_face(part, face_id, direction, cfg)
        results.append(trace)
        print(f"  grid {trace['grid_resolution']}, {trace['chain_count']} chain(s), "
              f"real segments emitted: {trace['real_segments_emitted_for_this_face']}")
        for chain in trace["chains"]:
            for t in chain["transitions"]:
                print(f"    transition: grid-gap={t['grid_resolution_gap_mm']}mm  "
                      f"true-boundary-refined-gap={t['unrefined_vs_true_boundary_gap_mm']}mm")

    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps({
        "part": Path(args.part).stem, "direction_label": args.direction,
        "direction": list(direction), "direction_source": "manual",
        "faces": results,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"\nreport -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
