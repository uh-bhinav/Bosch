"""
backend/validation/parting_line_angular_sweep.py
------------------------------------------------------------
P3.6 Phase B/C/D (2026-08-13): controlled angular sweep around Part3's four
diagonal anchor directions -- (1,0,1), (1,0,-1), (0,1,1), (0,1,-1) -- each
sampled direction run independently through the FROZEN, unmodified v2
pipeline. No optimizer involvement; every direction is `PullDirectionInput
(..., "manual")`.

Documented resolution: for each anchor direction d0, perturb by a cone half-
angle theta in {5, 10, 15} degrees, at 8 azimuthal positions (phi = 0, 45,
..., 315 degrees) around d0, using two arbitrary orthonormal basis vectors
(u, v) perpendicular to d0:

    perturbed = normalize( d0*cos(theta) + (u*cos(phi) + v*sin(phi))*sin(theta) )

This gives 3 radii x 8 azimuths = 24 perturbed directions per anchor, plus
the anchor itself (already covered by the D-026/D-029 baseline matrix, not
re-run here) = 96 new directions total across the 4 anchors.

For every direction, records BOTH layers independently (never collapsed
into one score, per instruction):
  - direction-only metrics (draft-good %, undercut %, near-zero %, near-
    zero connected-component coherence fraction -- the metric calibrated
    against Part1 in Phase A)
  - the full frozen parting-line pipeline (Track A/B, stitch, graph,
    2-core, candidates, H0-H7 failure counts, best candidate, core/cavity
    split)

Read-only. No production code touched.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

ANCHOR_DIRECTIONS = {
    "(1,0,1)": (1.0, 0.0, 1.0),
    "(1,0,-1)": (1.0, 0.0, -1.0),
    "(0,1,1)": (0.0, 1.0, 1.0),
    "(0,1,-1)": (0.0, 1.0, -1.0),
}
RADII_DEG = (5.0, 10.0, 15.0)
AZIMUTHS_DEG = tuple(range(0, 360, 45))  # 8 positions


def _normalize(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def _perpendicular_basis(d):
    # Any vector not parallel to d, cross it to get a perpendicular one.
    helper = (1.0, 0.0, 0.0) if abs(d[0]) < 0.9 else (0.0, 1.0, 0.0)
    u = _cross(d, helper)
    u = _normalize(u)
    v = _cross(d, u)
    v = _normalize(v)
    return u, v


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _perturb(d0, u, v, theta_deg, phi_deg):
    theta, phi = math.radians(theta_deg), math.radians(phi_deg)
    result = tuple(
        d0[k] * math.cos(theta) + (u[k] * math.cos(phi) + v[k] * math.sin(phi)) * math.sin(theta)
        for k in range(3)
    )
    return _normalize(result)


def _sweep_points(anchor_label: str) -> dict[str, tuple]:
    d0 = _normalize(ANCHOR_DIRECTIONS[anchor_label])
    u, v = _perpendicular_basis(d0)
    points = {}
    for theta in RADII_DEG:
        for phi in AZIMUTHS_DEG:
            label = f"{anchor_label}+theta{theta:g}+phi{phi:g}"
            points[label] = _perturb(d0, u, v, theta, phi)
    return points


def _full_analysis(part, direction: tuple) -> dict:
    from backend.config import settings
    from backend.geometry.draft_analyzer import analyze_draft
    from backend.geometry.undercut_detector import detect_undercuts
    from backend.geometry.parting_line_v2.contracts import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line

    cfg = settings.dfm.parting_line_v2
    eps = cfg.silhouette_epsilon
    d = _normalize(direction)

    # -- direction-only layer --
    draft = analyze_draft(part, d, pull_direction_label="sweep", mutate=False)
    undercuts = detect_undercuts(part, d, mutate=False, boolean_refine=False)

    near_zero_face_ids = set()
    near_zero_area = 0.0
    total_area = 0.0
    for face in part.faces:
        if not face.normal_valid:
            continue
        total_area += face.area
        g = face.signed_dot(d)
        if abs(g) <= eps:
            near_zero_face_ids.add(face.face_id)
            near_zero_area += face.area

    seen, components = set(), []
    for start in sorted(near_zero_face_ids):
        if start in seen:
            continue
        stack, group = [start], set()
        seen.add(start)
        while stack:
            node = stack.pop()
            group.add(node)
            for nb in part.face_adjacency.get(node, ()):
                if nb in near_zero_face_ids and nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        components.append(group)
    largest_area = max((sum(part.faces[f].area for f in c) for c in components), default=0.0)

    direction_only = {
        "draft_good_pct": round(draft.good_pct, 2),
        "undercut_area_pct": round(undercuts.undercut_area_pct, 2),
        "near_zero_area_pct": round(100.0 * near_zero_area / total_area, 2) if total_area else 0.0,
        "near_zero_component_count": len(components),
        "largest_component_area_fraction": (
            round(largest_area / near_zero_area, 4) if near_zero_area > 0 else 0.0
        ),
    }

    # -- frozen parting-line pipeline --
    pull = PullDirectionInput(d, "manual")
    result = analyse_parting_line(part, pull, undercuts=UndercutInput.empty(), cfg=cfg)
    h_counts = {"h0": 0, "h1": 0, "h2": 0, "h3": 0, "h4": 0, "h5_h7": 0}
    for c in result.candidates:
        if c.feasibility and not c.feasibility.passed:
            gate = (c.feasibility.failed_gate or "").lower()
            if gate in ("h0",):
                h_counts["h0"] += 1
            elif gate == "h1":
                h_counts["h1"] += 1
            elif gate == "h2":
                h_counts["h2"] += 1
            elif gate == "h3":
                h_counts["h3"] += 1
            elif gate == "h4":
                h_counts["h4"] += 1
            else:
                h_counts["h5_h7"] += 1
    valid = [c for c in result.candidates if c.feasibility and c.feasibility.passed]

    pipeline = {
        "track_a_segments": result.track_a_summary.get("segment_count"),
        "track_b_segments": result.track_b_summary.get("segment_count"),
        "stitched_segments": result.stitch_summary.get("segment_count"),
        "graph_nodes": result.reduction.get("nodes_after"),
        "graph_edges": result.reduction.get("edges_after"),
        "cyclomatic_number": result.reduction.get("cyclomatic_number"),
        "candidate_count": len(result.candidates),
        **h_counts,
        "fully_valid_candidate_count": len(valid),
        "outcome": "feasible" if valid else "no_feasible_candidate",
    }
    if result.selected is not None and result.selected.feasibility.passed:
        pipeline["best_candidate_coverage"] = round(result.selected.score.coverage, 4) if result.selected.score else None
        pipeline["best_candidate_segments"] = len(result.selected.segments)
        if result.regions is not None:
            pipeline["cavity_face_count"] = len(result.regions.cavity_face_ids)
            pipeline["core_face_count"] = len(result.regions.core_face_ids)

    return {"direction": d, "direction_only": direction_only, "pipeline": pipeline}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part", default="Part3.stp")
    parser.add_argument("--json", default="reports/parting_line_angular_sweep.json")
    parser.add_argument("--limit", type=int, default=None, help="cap total directions (debug)")
    args = parser.parse_args(argv)

    from backend.geometry.step_loader import load_step

    part_path = str(REPO_ROOT / "data" / "parts" / args.part)
    part = load_step(part_path)

    all_points: dict[str, tuple] = {}
    for anchor_label in ANCHOR_DIRECTIONS:
        all_points.update(_sweep_points(anchor_label))
    labels = list(all_points.items())
    if args.limit:
        labels = labels[: args.limit]

    print(f"total sweep directions: {len(labels)} (radii={RADII_DEG} deg, azimuths={AZIMUTHS_DEG} deg)")

    results = {}
    t0 = time.time()
    for i, (label, direction) in enumerate(labels):
        t_start = time.time()
        record = _full_analysis(part, direction)
        results[label] = record
        elapsed = time.time() - t_start
        p = record["pipeline"]
        do = record["direction_only"]
        print(
            f"[{i+1}/{len(labels)}] {label:>28} ({elapsed:5.1f}s): "
            f"near0={do['near_zero_area_pct']:5.1f}% coh={do['largest_component_area_fraction']:.3f} | "
            f"cand={p['candidate_count']:4d} h3={p['h3']:4d} h4={p['h4']:4d} valid={p['fully_valid_candidate_count']} "
            f"{p['outcome']}"
        )

    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\ntotal time: {time.time()-t0:.1f}s")
    print(f"report -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
