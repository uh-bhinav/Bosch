"""
backend/validation/parting_line_h0_surface_deviation_trace.py
-----------------------------------------------------------------
Follow-up to the mechanism-1 investigation (2026-08-12) — traces WHY H0.3's
``max_surface_deviation_mm`` check disagrees with Track B's own point
generation by several microns on Part3's face 274, even though mechanism 1's
boundary refinement is independently confirmed correct.

For one exact UV coordinate, evaluates the SAME point through every
representation involved:

    A: face's surface evaluator, WITH the face's own location applied
       (BRepAdaptor_Surface — the "correct", location-aware way to evaluate
       a point on a TopoDS_Face)
    B: the underlying Geom_Surface, raw, no location (BRep_Tool.Surface)
    C: Track B's own representation (GeomLProp_SLProps on B — this is
       EXACTLY what track_b.py's _FaceField.point() does)
    D: H0's representation (GeomAPI_ProjectPointOnSurf, projecting C's
       stored point back onto B — EXACTLY what gates.py's H0.3 check does)

Then reports pairwise distances, the projected UV vs the original UV, and
runs the identical experiment against a CONTROL (a fixture where H0 is known
to pass with <1e-9 mm deviation) to establish whether this is generic OCC
behaviour or specific to Part3's real, imported geometry.

Read-only. Does not modify H0, tau_surface, tolerances, pull-direction
handling, welding, enumeration, ranking, Track A, or mechanism 2.
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


def _trace_point(face, u: float, v: float) -> dict:
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
    from OCC.Core.GeomAPI import GeomAPI_ProjectPointOnSurf
    from OCC.Core.GeomLProp import GeomLProp_SLProps
    from OCC.Core.gp import gp_Pnt
    from OCC.Core.TopLoc import TopLoc_Location

    def d(p, q):
        return math.dist((p.X(), p.Y(), p.Z()), (q.X(), q.Y(), q.Z()))

    # --- A: location-aware face evaluator -----------------------------
    adaptor = BRepAdaptor_Surface(face, True)
    point_a = adaptor.Value(u, v)

    # --- B: underlying Geom_Surface, raw, no location ------------------
    location = TopLoc_Location()
    surface_b = BRep_Tool.Surface(face, location)
    point_b_local = surface_b.Value(u, v)
    # Apply the face's location manually, the way BRepAdaptor_Surface does
    # internally, so B and A are compared on equal footing.
    point_b_global = point_b_local.Transformed(location.Transformation())

    # --- C: Track B's own representation (_FaceField.point, verbatim) --
    props = GeomLProp_SLProps(surface_b, u, v, 0, 1e-9)
    point_c = props.Value()

    # --- D: H0's representation (gates.py's H0.3 check, verbatim) ------
    projector = GeomAPI_ProjectPointOnSurf(point_c, surface_b)
    has_result = projector.NbPoints() > 0
    point_d = projector.NearestPoint() if has_result else None
    distance_c_to_d = float(projector.LowerDistance()) if has_result else None
    u_d = v_d = None
    if has_result:
        u_d, v_d = projector.LowerDistanceParameters()

    return {
        "location_identity": location.IsIdentity(),
        "surface_type": surface_b.DynamicType().Name(),
        "uv": [u, v],
        "point_A_location_aware": [point_a.X(), point_a.Y(), point_a.Z()],
        "point_B_raw_geom_surface": [point_b_local.X(), point_b_local.Y(), point_b_local.Z()],
        "point_B_global": [point_b_global.X(), point_b_global.Y(), point_b_global.Z()],
        "point_C_track_b_repr": [point_c.X(), point_c.Y(), point_c.Z()],
        "point_D_projected": [point_d.X(), point_d.Y(), point_d.Z()] if point_d else None,
        "projected_uv": [u_d, v_d] if u_d is not None else None,
        "uv_delta": [u_d - u, v_d - v] if u_d is not None else None,
        "distance_A_B": d(point_a, point_b_global),
        "distance_A_C": d(point_a, point_c),
        "distance_B_C": d(point_b_global, point_c),
        "distance_C_D_reported_by_projector": distance_c_to_d,
        "distance_C_D_recomputed": d(point_c, point_d) if point_d else None,
    }


def _control_case(fixture_filename: str) -> dict:
    """Run the same 4-representation trace on a fixture known to pass H0."""
    from backend.config import settings
    from backend.geometry.parting_line_v2 import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line
    from backend.geometry.parting_line_v2.types import FaceBacking
    from backend.geometry.step_loader import load_step

    path = REPO_ROOT / "data" / "fixtures" / "synthetic" / fixture_filename
    part = load_step(str(path))
    cfg = settings.dfm.parting_line_v2
    pull = PullDirectionInput((0.0, 0.0, 1.0), "fixture")
    result = analyse_parting_line(part, pull, undercuts=UndercutInput.empty(), cfg=cfg)

    if result.selected is None:
        return {"fixture": fixture_filename, "error": "no selected candidate"}

    face_segment = next(
        (s for s in result.selected.segments if isinstance(s.backing, FaceBacking)), None
    )
    if face_segment is None:
        return {"fixture": fixture_filename, "error": "no face-backed segment in selected candidate"}

    faces_by_id = {f.face_id: f for f in part.faces}
    face = faces_by_id[face_segment.backing.face_id].occ_face
    mid_index = len(face_segment.backing.uv) // 2
    u, v = face_segment.backing.uv[mid_index]

    trace = _trace_point(face, u, v)
    trace["fixture"] = fixture_filename
    trace["on_surface_report"] = result.selected.feasibility.on_surface.to_dict()
    return trace


def _failing_case(part_path: str, direction_label: str, face_id: int) -> dict:
    from backend.config import settings
    from backend.geometry.parting_line_v2 import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line
    from backend.geometry.parting_line_v2.types import FaceBacking
    from backend.geometry.step_loader import load_step

    part = load_step(part_path)
    cfg = settings.dfm.parting_line_v2
    pull = PullDirectionInput(DIRECTIONS[direction_label], "manual")
    result = analyse_parting_line(part, pull, undercuts=UndercutInput.empty(), cfg=cfg)

    # Find an H0-failing candidate whose worst offender is on `face_id`.
    target = None
    for candidate in result.candidates:
        report = candidate.feasibility
        if report is None or report.failed_gate != "H0" or report.on_surface is None:
            continue
        worst = report.on_surface.worst_offender
        if worst is None:
            continue
        segment = next((s for s in candidate.segments if s.segment_id == worst[0]), None)
        if segment is not None and isinstance(segment.backing, FaceBacking) and segment.backing.face_id == face_id:
            target = (candidate, segment, worst)
            break

    if target is None:
        return {"error": f"no H0-failing candidate found with worst offender on face {face_id}"}

    candidate, segment, worst = target
    worst_point = worst[1]
    # Find the UV paired with the worst 3-D point.
    uv = None
    for p, this_uv in zip(segment.points, segment.backing.uv):
        if math.dist(p, worst_point) < 1e-9:
            uv = this_uv
            break
    if uv is None:
        # fall back: nearest point in the segment
        uv = min(
            zip(segment.points, segment.backing.uv),
            key=lambda pu: math.dist(pu[0], worst_point),
        )[1]

    faces_by_id = {f.face_id: f for f in part.faces}
    face = faces_by_id[face_id].occ_face
    trace = _trace_point(face, uv[0], uv[1])
    trace["candidate_id"] = candidate.candidate_id
    trace["segment_id"] = segment.segment_id
    trace["on_surface_report"] = candidate.feasibility.on_surface.to_dict()
    return trace


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default="reports/h0_surface_deviation_trace.json")
    args = parser.parse_args(argv)

    print("=== FAILING CASE: Part3 @ +X, face 274 ===")
    failing = _failing_case(str(REPO_ROOT / "data" / "parts" / "Part3.stp"), "+X", 274)
    print(json.dumps(failing, indent=2, default=str))

    controls = {}
    for fixture in [
        "F4_sphere.stp", "F17_barrel_bulged_loft.stp", "F3_cylinder_axis_perpendicular_to_pull.stp",
    ]:
        print(f"\n=== CONTROL: {fixture} ===")
        try:
            control = _control_case(fixture)
        except Exception as exc:  # noqa: BLE001
            control = {"fixture": fixture, "error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(control, indent=2, default=str))
        controls[fixture] = control

    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps({
        "failing_case": failing, "controls": controls,
    }, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nreport -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
