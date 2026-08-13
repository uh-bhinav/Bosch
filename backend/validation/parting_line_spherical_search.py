"""
backend/validation/parting_line_spherical_search.py
------------------------------------------------------------
P3.10 (2026-08-13): systematic spherical-grid feasibility search for
Part3, using the cheap zero-level-network diagnostic
(`parting_line_zero_level_network.py`) as a pre-filter before the
expensive full pipeline.

Grid resolution: elevation (polar angle from +Z) every 15 degrees,
azimuth every 15 degrees. Justification: (elevation steps 0-180 in 15deg
= 13 values, poles collapse azimuth) x (azimuth steps 0-345 in 15deg = 24
values) = 12*24 + 2 = 290 grid points. Measured per-direction cost for
the cheap diagnostic (Track A/B + graph, no H0-H7/candidate generation)
is ~1-2s on Part3 -- 290 points ~= 5-10 minutes, a reasonable runtime for
a background diagnostic sweep. A finer (10deg) grid would be ~4x the
points (~1150) for ~35-70 minutes; deferred unless the 15deg pass leaves
the question open.

Explicitly folds in, not replaces: (a) the 12 canonical directions already
recorded in D-026/D-029, (b) the 96 swept directions already recorded in
D-032. Both are re-scored with the SAME cheap diagnostic here for a
consistent ranking basis (their full-pipeline H0-H7 results are separate
and already on record; this script only adds the zero-level-network
metrics for them).

Ranking is CONTINUOUS (largest_component_fraction, then non_trivial_mu),
not a hard binary threshold -- calibration against Part1 (see companion
run) showed the raw CASE-0..3 binning does not cleanly separate Part1's
working direction from its failing ones (all 12 Part1 canonical
directions have substantial raw cyclic content; what actually
distinguishes +Z is that its candidates pass H3, not that cycles exist at
all -- a finer question reserved for the second-stage deep verification
on the shortlisted top candidates only, per the two-stage design).

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

PRINCIPAL_DIRECTIONS = {
    "+X": (1.0, 0.0, 0.0), "-X": (-1.0, 0.0, 0.0),
    "+Y": (0.0, 1.0, 0.0), "-Y": (0.0, -1.0, 0.0),
    "+Z": (0.0, 0.0, 1.0), "-Z": (0.0, 0.0, -1.0),
}
DIAGONAL_DIRECTIONS = {
    "(1,1,0)": (1.0, 1.0, 0.0), "(1,-1,0)": (1.0, -1.0, 0.0),
    "(1,0,1)": (1.0, 0.0, 1.0), "(1,0,-1)": (1.0, 0.0, -1.0),
    "(0,1,1)": (0.0, 1.0, 1.0), "(0,1,-1)": (0.0, 1.0, -1.0),
}

ELEVATION_STEP_DEG = 15
AZIMUTH_STEP_DEG = 15


def _grid_directions() -> dict[str, tuple]:
    points = {}
    for elev_deg in range(0, 181, ELEVATION_STEP_DEG):
        theta = math.radians(elev_deg)
        if elev_deg == 0 or elev_deg == 180:
            azimuths = [0]
        else:
            azimuths = list(range(0, 360, AZIMUTH_STEP_DEG))
        for az_deg in azimuths:
            phi = math.radians(az_deg)
            x = math.sin(theta) * math.cos(phi)
            y = math.sin(theta) * math.sin(phi)
            z = math.cos(theta)
            label = f"grid(elev{elev_deg},az{az_deg})"
            points[label] = (x, y, z)
    return points


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part", default="Part3.stp")
    parser.add_argument("--json", default="reports/parting_line_spherical_search.json")
    parser.add_argument("--include-existing", action="store_true", default=True)
    args = parser.parse_args(argv)

    from backend.config import settings
    from backend.geometry.parting_line_v2.engine import _bbox_diagonal
    from backend.geometry.step_loader import load_step
    from backend.validation.parting_line_zero_level_network import summarize_zero_level_network

    cfg = settings.dfm.parting_line_v2
    part = load_step(str(REPO_ROOT / "data" / "parts" / args.part))
    bbox_diagonal = _bbox_diagonal(part)

    directions: dict[str, tuple] = {}
    directions.update(_grid_directions())
    if args.include_existing:
        directions.update(PRINCIPAL_DIRECTIONS)
        directions.update(DIAGONAL_DIRECTIONS)
        sweep_path = REPO_ROOT / "reports" / "parting_line_angular_sweep_part3.json"
        if sweep_path.exists() and args.part == "Part3.stp":
            sweep = json.loads(sweep_path.read_text())
            for label, rec in sweep.items():
                directions[f"sweep({label})"] = tuple(rec["direction"])

    print(f"total directions to score: {len(directions)} "
          f"(grid: elevation step {ELEVATION_STEP_DEG} deg, azimuth step {AZIMUTH_STEP_DEG} deg)")

    results = {}
    t0 = time.time()
    for i, (label, direction) in enumerate(directions.items()):
        t1 = time.time()
        summary = summarize_zero_level_network(part, direction, cfg, bbox_diagonal)
        results[label] = summary.to_dict()
        if (i + 1) % 25 == 0 or i == len(directions) - 1:
            elapsed = time.time() - t0
            print(f"[{i+1}/{len(directions)}] elapsed={elapsed:.1f}s "
                  f"last={label} largest_frac={summary.largest_component_fraction:.3f} "
                  f"non_trivial_mu={summary.non_trivial_mu}")

    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\ntotal time: {time.time()-t0:.1f}s")
    print(f"report -> {args.json}")

    ranked = sorted(
        results.items(),
        key=lambda kv: (kv[1]["largest_component_fraction"], kv[1]["non_trivial_mu"]),
        reverse=True,
    )
    print("\n=== top 15 by largest_component_fraction, then non_trivial_mu ===")
    for label, r in ranked[:15]:
        print(f"  {label:>30}: frac={r['largest_component_fraction']:.3f} "
              f"non_trivial_mu={r['non_trivial_mu']:4d} mu_total={r['mu_total']:4d} "
              f"nodes={r['node_count']:4d} comps={r['component_count']:3d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
