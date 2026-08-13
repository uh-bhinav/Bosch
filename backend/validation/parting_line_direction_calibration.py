"""
backend/validation/parting_line_direction_calibration.py
------------------------------------------------------------
P3.6 Phase A (2026-08-13): calibrate direction-only analysis against Part1's
known positive control (+Z/-Z valid; +/-X, +/-Y, both diagonals invalid).

D-029 found the naive near-zero-AREA-percentage metric is anti-correlated
with ground truth on Part1: +Z has the MOST near-zero area (71.7%) of any
Part1 direction, yet is the only one that works. This script tests a
geometrically-motivated alternative that does not reduce to a new scalar
threshold: whether the near-zero-draft faces form ONE CONNECTED envelope
(a coherent band, like a box's four walls forming a single ring around its
sides) versus many disconnected local patches (scattered small features).

Method: reuses `part.face_adjacency` (already computed by step_loader --
no new geometry engine) restricted to the subset of faces classified
near-zero at a given direction (same `silhouette_epsilon` threshold the
parting-line engine itself uses). Connected components of that restricted
subgraph are counted via a plain BFS/union-find -- no new algorithm, the
same graph-connectivity idea already used throughout this project's
diagnostics (D-028's raw-component analysis, D-029's cross-checks).

Read-only. No production code touched.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
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
ALL_DIRECTIONS = {**PRINCIPAL_DIRECTIONS, **DIAGONAL_DIRECTIONS}


def _normalize(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def _connected_components(face_ids: set[int], adjacency: dict[int, list[int]]) -> list[set[int]]:
    seen: set[int] = set()
    components: list[set[int]] = []
    for start in sorted(face_ids):
        if start in seen:
            continue
        stack, group = [start], set()
        seen.add(start)
        while stack:
            node = stack.pop()
            group.add(node)
            for neighbour in adjacency.get(node, ()):
                if neighbour in face_ids and neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        components.append(group)
    return components


def _calibration_metrics(part_path: str, direction: tuple) -> dict:
    from backend.config import settings

    from backend.geometry.step_loader import load_step

    part = load_step(part_path)
    d = _normalize(direction)
    eps = settings.dfm.parting_line_v2.silhouette_epsilon

    near_zero_face_ids: set[int] = set()
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

    components = _connected_components(near_zero_face_ids, part.face_adjacency)
    components_by_area = sorted(
        (sum(part.faces[fid].area for fid in comp) for comp in components), reverse=True
    )
    largest_component_area = components_by_area[0] if components_by_area else 0.0
    largest_component_face_count = max((len(c) for c in components), default=0)

    return {
        "direction": d,
        "near_zero_face_count": len(near_zero_face_ids),
        "near_zero_area_mm2": round(near_zero_area, 3),
        "near_zero_area_pct": round(100.0 * near_zero_area / total_area, 2) if total_area else 0.0,
        "near_zero_component_count": len(components),
        "largest_component_face_count": largest_component_face_count,
        "largest_component_area_mm2": round(largest_component_area, 3),
        # The key calibration signal: what fraction of the near-zero area
        # is concentrated in its single largest connected patch. Close to
        # 1.0 = one coherent envelope (a wall, a belt). Low = fragmented
        # into many small disconnected patches (local features).
        "largest_component_area_fraction_of_near_zero": (
            round(largest_component_area / near_zero_area, 4) if near_zero_area > 0 else 0.0
        ),
        "component_face_counts_sorted": sorted(
            (len(c) for c in components), reverse=True
        )[:10],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default="reports/parting_line_direction_calibration.json")
    args = parser.parse_args(argv)

    targets = [
        ("Part1", str(REPO_ROOT / "data" / "parts" / "Part1.stp")),
        ("Part3", str(REPO_ROOT / "data" / "parts" / "Part3.stp")),
    ]

    results: dict[str, dict] = {}
    for part_name, path in targets:
        print(f"=== {part_name} ===")
        part_results = {}
        for label, direction in ALL_DIRECTIONS.items():
            metrics = _calibration_metrics(path, direction)
            part_results[label] = metrics
            print(
                f"  {label:>9}: near_zero={metrics['near_zero_area_pct']:5.1f}%  "
                f"components={metrics['near_zero_component_count']:3d}  "
                f"largest_component_frac={metrics['largest_component_area_fraction_of_near_zero']:.3f}  "
                f"largest_component_faces={metrics['largest_component_face_count']}"
            )
        results[part_name] = part_results

    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nreport -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
