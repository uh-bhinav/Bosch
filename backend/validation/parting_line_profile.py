"""
backend/validation/parting_line_profile.py
------------------------------------------
**P3a — measure first.** (plan §12 P3a, §6.1's build-order gate)

This script builds **no** enumeration strategy. Its whole job is to publish the
measurements that decide what P3b is allowed to build:

1. **The ``μ`` distribution** across the whole corpus. §6.1 forbids writing
   Johnson enumeration or beam search until the data shows real mass in their
   branches. If ``μ = 1`` dominates after reduction, neither gets written.
2. **``A_cauchy`` vs the exact projected outline**, so the T1 denominator's
   overestimate is a measured number rather than a caveat.
3. **The H7 coverage distribution** over candidates that passed H0-H4, so
   ``κ_min`` is calibrated from data instead of the provisional 0.50.
4. **Per-stage p50/p95 runtime**, so any later optimization targets a
   bottleneck that was actually identified (plan §12.5 rule 2).
5. **Crash count** on unlabelled external parts — a high rejection rate is an
   acceptable outcome, a crash is not.

**Direction protocol (revised 2026-08-09).** The upstream direction optimizer
is teammate-owned and under repair, so its output cannot serve as correctness
evidence for THIS module: a good result would not distinguish "our silhouette
is right" from "that direction suits us", and a bad one would not distinguish
"our algorithm is broken" from "that direction is wrong". Those are two
different questions with two different owners.

Therefore real/external parts are **SKIPPED** unless a controlled direction is
supplied with ``--direction``. ``--allow-optimizer`` re-enables optimizer
directions explicitly, and every record carries ``direction_source`` and
``is_correctness_evidence`` so contaminated rows can never be mistaken for
clean ones.

Note the earlier finding stands as an *observation* and not as a
justification: at ``+Z`` Part3 yields 0 Track-B segments and ``μ = 110``,
while at the (unvalidated) optimizer direction it yields 203 and ``μ = 3``.
That shows the problem is strongly direction-dependent — it does **not** show
which direction is right.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SYNTHETIC = REPO_ROOT / "data" / "fixtures" / "synthetic"
REAL_PARTS = REPO_ROOT / "data" / "parts"
DEFAULT_EXTERNAL = os.environ.get(
    "DFM_EXTERNAL_CORPUS", "/Users/abhinavgurkar/Downloads/Testing .STP files"
)


# ---------------------------------------------------------------------------
# Exact projected outline area, by tessellation + rasterised union
# ---------------------------------------------------------------------------

def exact_projected_area(part, direction, *, grid: int = 1024) -> tuple[float, str]:
    """
    Area of the part's true projected outline, for comparison with
    ``A_cauchy``.

    ``A_cauchy = ½·Σ_f ∫_f |n̂·d̂| dA`` is **exact for a convex body** and an
    **overestimate** otherwise, because a non-convex boundary's projection
    covers some points more than twice. This measures the real thing so that
    overestimate stops being a caveat and becomes a number.

    Method: tessellate, project every triangle into the pull-normal plane, and
    **rasterise their union** onto a ``grid × grid`` lattice. Union of many
    2-D triangles is what is wanted (overlaps must count once), and an exact
    polygon union needs a library this environment does not have. Rasterising
    has error bounded by the cell size along the outline's perimeter — around
    0.1% at 1024², which is far below the effect being measured.
    """
    try:
        import numpy as np
        from OCC.Core.BRep import BRep_Tool
        from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
        from OCC.Core.TopAbs import TopAbs_FACE
        from OCC.Core.TopExp import TopExp_Explorer
        from OCC.Core.TopLoc import TopLoc_Location
        from OCC.Core.TopoDS import topods

        from backend.geometry.parting_line_v2.measures import projection_basis
    except Exception as exc:  # pragma: no cover
        return 0.0, f"unavailable: {exc}"

    bbox = part.bounding_box
    diagonal = math.sqrt(
        (bbox.xmax - bbox.xmin) ** 2 + (bbox.ymax - bbox.ymin) ** 2
        + (bbox.zmax - bbox.zmin) ** 2
    )
    try:
        BRepMesh_IncrementalMesh(part.occ_shape, diagonal * 1e-3, False, 0.5, True)
    except Exception as exc:
        return 0.0, f"meshing failed: {exc}"

    u_axis, v_axis = projection_basis(direction)
    triangles: list[tuple[float, float, float, float, float, float]] = []

    explorer = TopExp_Explorer(part.occ_shape, TopAbs_FACE)
    while explorer.More():
        face = topods.Face(explorer.Current())
        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation(face, location)
        if triangulation is not None:
            transform = location.Transformation()
            nodes = []
            for i in range(1, triangulation.NbNodes() + 1):
                p = triangulation.Node(i).Transformed(transform)
                x, y, z = p.X(), p.Y(), p.Z()
                nodes.append((
                    x * u_axis[0] + y * u_axis[1] + z * u_axis[2],
                    x * v_axis[0] + y * v_axis[1] + z * v_axis[2],
                ))
            for i in range(1, triangulation.NbTriangles() + 1):
                a, b, c = triangulation.Triangle(i).Get()
                (x0, y0), (x1, y1), (x2, y2) = nodes[a - 1], nodes[b - 1], nodes[c - 1]
                triangles.append((x0, y0, x1, y1, x2, y2))
        explorer.Next()

    if not triangles:
        return 0.0, "no triangulation produced"

    array = np.asarray(triangles, dtype=float)
    min_x = float(min(array[:, 0].min(), array[:, 2].min(), array[:, 4].min()))
    max_x = float(max(array[:, 0].max(), array[:, 2].max(), array[:, 4].max()))
    min_y = float(min(array[:, 1].min(), array[:, 3].min(), array[:, 5].min()))
    max_y = float(max(array[:, 1].max(), array[:, 3].max(), array[:, 5].max()))
    width, height = max_x - min_x, max_y - min_y
    if width <= 0 or height <= 0:
        return 0.0, "degenerate projection"

    cell_x, cell_y = width / grid, height / grid
    covered = np.zeros((grid, grid), dtype=bool)
    centres_x = min_x + (np.arange(grid) + 0.5) * cell_x
    centres_y = min_y + (np.arange(grid) + 0.5) * cell_y

    for x0, y0, x1, y1, x2, y2 in triangles:
        i0 = max(0, int((min(x0, x1, x2) - min_x) / cell_x) - 1)
        i1 = min(grid, int((max(x0, x1, x2) - min_x) / cell_x) + 2)
        j0 = max(0, int((min(y0, y1, y2) - min_y) / cell_y) - 1)
        j1 = min(grid, int((max(y0, y1, y2) - min_y) / cell_y) + 2)
        if i0 >= i1 or j0 >= j1:
            continue
        gx, gy = np.meshgrid(centres_x[i0:i1], centres_y[j0:j1], indexing="ij")
        denominator = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(denominator) < 1e-15:
            continue
        lam0 = ((y1 - y2) * (gx - x2) + (x2 - x1) * (gy - y2)) / denominator
        lam1 = ((y2 - y0) * (gx - x2) + (x0 - x2) * (gy - y2)) / denominator
        inside = (lam0 >= 0) & (lam1 >= 0) & (lam0 + lam1 <= 1)
        covered[i0:i1, j0:j1] |= inside

    return float(covered.sum()) * cell_x * cell_y, f"rasterised {grid}x{grid}"


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------

def _corpus(external_dir: str) -> list[dict]:
    entries: list[dict] = []

    manifest = SYNTHETIC / "manifest.json"
    if manifest.exists():
        for fixture in json.loads(manifest.read_text())["fixtures"]:
            entries.append({
                "id": fixture["fixture_id"], "name": fixture["name"],
                "path": str(SYNTHETIC / fixture["filename"]),
                "kind": "synthetic", "direction": tuple(fixture["pull_direction"]),
            })

    for fixture_id, filename in (("F15", "Part1.stp"), ("F16", "Part3.stp")):
        path = REAL_PARTS / filename
        if path.exists():
            entries.append({
                "id": fixture_id, "name": path.stem, "path": str(path),
                "kind": "real", "direction": None,          # None => optimise
            })

    if external_dir and Path(external_dir).is_dir():
        for index, path in enumerate(sorted(glob.glob(str(Path(external_dir) / "*")))):
            if path.lower().endswith((".stp", ".step")):
                entries.append({
                    "id": f"X{index + 1}", "name": Path(path).stem,
                    "path": path, "kind": "external", "direction": None,
                })
    return entries


def _profile_one(
    entry: dict, *, exact_area: bool,
    manual_direction: tuple[float, float, float] | None = None,
    allow_optimizer: bool = False,
) -> dict:
    from backend.config import settings
    from backend.geometry.parting_line_v2 import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line
    from backend.geometry.step_loader import load_step

    record: dict = {"id": entry["id"], "name": entry["name"], "kind": entry["kind"]}
    started = time.perf_counter()
    try:
        part = load_step(entry["path"])
        direction = entry["direction"]
        source = "fixture"
        if direction is None:
            if manual_direction is not None:
                direction, source = manual_direction, "manual"
            elif allow_optimizer:
                from backend.geometry.direction_optimizer import optimize_mold_direction
                direction = tuple(
                    float(c) for c in optimize_mold_direction(part).best_direction
                )
                source = "optimizer"
            else:
                record.update({
                    "status": "skipped",
                    "reason": (
                        "no controlled direction supplied. Real/external parts are "
                        "SKIPPED rather than silently optimizer-directed — the "
                        "upstream optimizer is under repair, so its output cannot "
                        "serve as correctness evidence for this module. Pass "
                        "--direction, or --allow-optimizer for integration runs."
                    ),
                })
                record["total_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
                return record
        direction = tuple(float(c) for c in direction)

        pull = PullDirectionInput(direction, source)  # type: ignore[arg-type]
        record["direction_source"] = source
        record["is_correctness_evidence"] = pull.is_correctness_evidence
        result = analyse_parting_line(
            part, pull, undercuts=UndercutInput.empty(),
            cfg=settings.dfm.parting_line_v2,
        )

        record.update({
            "status": "ok",
            "direction": [round(c, 6) for c in direction],
            "face_count": len(part.faces),
            "outcome": result.outcome,
            "mu": result.bounds.cyclomatic_number,
            "branch_nodes": result.bounds.branch_node_count,
            "components": result.reduction.get("component_count", 0),
            "strategy": result.bounds.strategy,
            "candidates": result.bounds.candidates_found,
            "track_a_segments": result.track_a_summary.get("segment_count", 0),
            "track_b_segments": result.track_b_summary.get("segment_count", 0),
            "degenerate_faces": result.track_b_summary.get("degenerate_face_count", 0),
            "rejections": result.rejection_summary,
            "stage_ms": {
                s["stage"]: s["elapsed_ms"] for s in result.timings.to_dict()["stages"]
            },
            "a_cauchy": round(result.part_projected_area_mm2, 4),
            # Every H7 measurement from candidates that got that far — the raw
            # material for calibrating kappa_min.
            "coverages": [
                round(c.feasibility.measurements["h7_coverage"], 6)
                for c in result.candidates
                if c.feasibility and "h7_coverage" in c.feasibility.measurements
            ],
        })
        if result.selected:
            record["selected_coverage"] = round(result.selected.score.coverage, 6)

        if exact_area:
            area, note = exact_projected_area(part, direction)
            record["a_exact"] = round(area, 4)
            record["a_exact_note"] = note
            if area > 0:
                record["cauchy_overestimate_pct"] = round(
                    100.0 * (record["a_cauchy"] - area) / area, 3
                )
    except Exception as exc:  # noqa: BLE001
        record.update({"status": "crash", "error": f"{type(exc).__name__}: {exc}"})
    record["total_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external", default=DEFAULT_EXTERNAL)
    parser.add_argument(
        "--direction", default="",
        help="controlled direction for real/external parts, e.g. '0,0,1'. "
             "Without it, real parts are SKIPPED rather than silently "
             "optimizer-directed.",
    )
    parser.add_argument(
        "--allow-optimizer", action="store_true",
        help="permit optimizer-derived directions. Results are INTEGRATION "
             "evidence only, never correctness evidence for this module.",
    )
    parser.add_argument("--no-exact-area", action="store_true")
    parser.add_argument("--json", default="reports/p3a_profile.json")
    args = parser.parse_args(argv)

    entries = _corpus(args.external)
    print(f"P3a profile — {len(entries)} part(s)")
    print("Real and external parts use their OPTIMAL direction, never +Z "
          "(P2 measured why: at +Z Part3 reads mu=110, at optimal mu=3).\n")

    header = (f"{'id':<5}{'name':<28}{'kind':<10}{'outcome':<24}"
              f"{'mu':>5}{'brch':>5}{'cand':>5}{'A/B segs':>11}{'ms':>9}")
    print(header)
    print("-" * len(header))

    manual = None
    if args.direction:
        parts = [float(x) for x in args.direction.replace(" ", "").split(",")]
        manual = (parts[0], parts[1], parts[2])
        print(f"Controlled direction for real/external parts: {manual}  "
              f"(direction_source = 'manual')\n")
    elif args.allow_optimizer:
        print("!! --allow-optimizer: optimizer-derived directions in use. Results are "
              "INTEGRATION evidence ONLY, not correctness evidence.\n")
    else:
        print("No --direction given: real/external parts will be SKIPPED "
              "(never silently optimizer-directed).\n")

    records = []
    for entry in entries:
        record = _profile_one(
            entry, exact_area=not args.no_exact_area,
            manual_direction=manual, allow_optimizer=args.allow_optimizer,
        )
        records.append(record)
        if record["status"] == "skipped":
            print(f"{record['id']:<5}{record['name'][:27]:<28}{record['kind']:<10}"
                  f"SKIPPED (no controlled direction)")
        elif record["status"] == "crash":
            print(f"{record['id']:<5}{record['name'][:27]:<28}{record['kind']:<10}"
                  f"CRASH {record['error'][:50]}")
        else:
            print(f"{record['id']:<5}{record['name'][:27]:<28}{record['kind']:<10}"
                  f"{record['outcome']:<24}{record['mu']:>5}{record['branch_nodes']:>5}"
                  f"{record['candidates']:>5}"
                  f"{record['track_a_segments']:>5}/{record['track_b_segments']:<5}"
                  f"{record['total_ms']:>9.0f}")

    ok = [r for r in records if r["status"] == "ok"]
    crashes = [r for r in records if r["status"] == "crash"]

    # --- 1. the mu distribution: what §6.1's gate consumes -----------------
    print("\n" + "=" * 78)
    print("1. mu DISTRIBUTION  (decides whether Johnson / beam get written at all)")
    buckets = {"mu == 0": 0, "mu == 1": 0, "2 <= mu <= 12": 0, "mu > 12": 0}
    for record in ok:
        mu = record["mu"]
        key = ("mu == 0" if mu == 0 else "mu == 1" if mu == 1
               else "2 <= mu <= 12" if mu <= 12 else "mu > 12")
        buckets[key] += 1
    for key, count in buckets.items():
        share = 100.0 * count / len(ok) if ok else 0.0
        print(f"   {key:<16} {count:>3}  ({share:5.1f}%)  {'#' * count}")
    mus = sorted(r["mu"] for r in ok)
    if mus:
        print(f"   min {mus[0]}  median {statistics.median(mus):.0f}  "
              f"p95 {mus[int(0.95 * (len(mus) - 1))]}  max {mus[-1]}")

    # --- 2. Cauchy overestimate --------------------------------------------
    print("\n2. A_cauchy vs EXACT projected outline")
    over = [r["cauchy_overestimate_pct"] for r in ok if "cauchy_overestimate_pct" in r]
    if over:
        print(f"   n={len(over)}  min {min(over):+.2f}%  median "
              f"{statistics.median(over):+.2f}%  max {max(over):+.2f}%")
        worst = max(ok, key=lambda r: r.get("cauchy_overestimate_pct", -1e9))
        print(f"   worst: {worst['id']} {worst['name']} "
              f"{worst['cauchy_overestimate_pct']:+.2f}%")
    else:
        print("   not measured")

    # --- 3. H7 coverage distribution ---------------------------------------
    print("\n3. H7 COVERAGE distribution  (calibrates kappa_min, provisional 0.50)")
    all_coverages = sorted(c for r in ok for c in r.get("coverages", []))
    selected = sorted(r["selected_coverage"] for r in ok if "selected_coverage" in r)
    if all_coverages:
        print(f"   all candidates reaching H7: n={len(all_coverages)}  "
              f"min {min(all_coverages):.3f}  median {statistics.median(all_coverages):.3f}  "
              f"max {max(all_coverages):.3f}")
    if selected:
        print(f"   SELECTED loops:             n={len(selected)}  "
              f"min {min(selected):.3f}  median {statistics.median(selected):.3f}  "
              f"max {max(selected):.3f}")
        print(f"   -> lowest accepted coverage is {min(selected):.3f}")

    # --- 4. per-stage runtime ----------------------------------------------
    print("\n4. PER-STAGE RUNTIME  (p50 / p95 ms) — identifies bottlenecks BEFORE optimizing")
    stages: dict[str, list[float]] = {}
    for record in ok:
        for stage, ms in record.get("stage_ms", {}).items():
            stages.setdefault(stage, []).append(ms)
    order = ["load", "track_a", "track_b", "weld", "reduce",
             "enumerate", "filter", "rank", "core_cavity", "surface"]
    for stage in order:
        values = stages.get(stage)
        if not values:
            continue
        values.sort()
        p50 = statistics.median(values)
        p95 = values[int(0.95 * (len(values) - 1))]
        print(f"   {stage:<12} p50 {p50:9.1f}   p95 {p95:9.1f}   max {max(values):9.1f}")
    totals = sorted(r["total_ms"] for r in ok)
    if totals:
        print(f"   {'TOTAL':<12} p50 {statistics.median(totals):9.1f}   "
              f"p95 {totals[int(0.95 * (len(totals) - 1))]:9.1f}   max {max(totals):9.1f}")

    # --- 5. outcomes --------------------------------------------------------
    print("\n5. OUTCOMES")
    outcomes: dict[str, int] = {}
    for record in ok:
        outcomes[record["outcome"]] = outcomes.get(record["outcome"], 0) + 1
    for outcome, count in sorted(outcomes.items(), key=lambda x: -x[1]):
        print(f"   {outcome:<26} {count:>3}")
    gates: dict[str, int] = {}
    for record in ok:
        for gate, count in record.get("rejections", {}).items():
            gates[gate] = gates.get(gate, 0) + count
    print(f"   rejections by gate: {dict(sorted(gates.items()))}")
    print(f"   CRASHES: {len(crashes)}  (a crash is not an acceptable outcome; "
          "a rejection is)")

    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps({
        "phase": "P3a",
        "note": "measurement only — no enumeration strategy was built",
        "records": records,
        "mu_buckets": buckets,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"\nreport -> {args.json}")
    return 1 if crashes else 0


if __name__ == "__main__":
    sys.exit(main())
