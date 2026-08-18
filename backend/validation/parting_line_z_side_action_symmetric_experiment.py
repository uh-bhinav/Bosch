"""
backend/validation/parting_line_z_side_action_symmetric_experiment.py
-----------------------------------------------------------------
Extension of parting_line_z_side_action_experiment.py (2026-08-16):
tests whether representing BOTH symmetric radial rib stacks in
`side_core_face_ids` (not just the first, previously-justified one)
changes the H3=4 decomposition observed for C_balanced_mid.

Mirror face set is NOT inferred from face-ID proximity/offset. It was
established by direct geometric query (BRepAdaptor_Surface) confirming
an EXACT match (radius, area, z-position, adjacency topology) between
each face of the original 17-face justified set and its counterpart:

    cylinders: 0->18 (r=12.5,area=254.652), 2->20 (r=9.5,area=53.969),
               4->22 (r=12.5,area=72.758),  6->24 (r=9.5,area=53.969)
    shoulders: 1->19, 3->21, 5->23, 7->25 (same z, area, normal sign)
    fillets:   8->26, 9->27, 10->28, 11->29, 12->30, 13->31, 14->32,
               15->33, 16->34 (same major_r, minor_r=0.5, z, area, and
               isomorphic adjacency: each fillet touches the same two
               ring members as its counterpart does in the original
               stack)

READ-ONLY DIAGNOSTIC. Reuses build_graph_z_side_action (itself a
read-only wrapper around Mechanism B's build_graph_fixed) unmodified.
No production code touched. Does NOT add 329-338, its mirror cluster,
or any Type 1/Type 2 correction.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import backend.validation.parting_line_mechanism_b_fixture as mb
from backend.validation.parting_line_z_side_action_experiment import (
    JUSTIFIED_SIDE_ACTION_FACES,
    _make_builder,
)

MIRROR_CYLINDER_FACES = frozenset({18, 20, 22, 24})
MIRROR_SHOULDER_FACES = frozenset({19, 21, 23, 25})
MIRROR_FILLET_FACES = frozenset({26, 27, 28, 29, 30, 31, 32, 33, 34})

MIRROR_JUSTIFIED_SIDE_ACTION_FACES = (
    MIRROR_CYLINDER_FACES | MIRROR_SHOULDER_FACES | MIRROR_FILLET_FACES
)
assert len(MIRROR_JUSTIFIED_SIDE_ACTION_FACES) == 17

BOTH_STACKS_FACES = JUSTIFIED_SIDE_ACTION_FACES | MIRROR_JUSTIFIED_SIDE_ACTION_FACES
assert len(BOTH_STACKS_FACES) == 34


def run_symmetric_experiment():
    from backend.config import settings
    from backend.geometry.parting_line_v2.contracts import UndercutInput
    from backend.geometry.step_loader import load_step_cached

    cfg = settings.dfm.parting_line_v2
    undercuts = UndercutInput.empty()
    part3 = load_step_cached("data/parts/Part3.stp")

    def unit(v):
        n = math.sqrt(sum(c * c for c in v))
        return tuple(c / n for c in v)

    direction_z = unit((0, 0, 1))

    print(f"Mirror justified set ({len(MIRROR_JUSTIFIED_SIDE_ACTION_FACES)} faces): "
          f"{sorted(MIRROR_JUSTIFIED_SIDE_ACTION_FACES)}", flush=True)
    print(f"Combined (both stacks) set ({len(BOTH_STACKS_FACES)} faces): "
          f"{sorted(BOTH_STACKS_FACES)}", flush=True)

    results = mb._run_candidate(part3, direction_z, cfg, undercuts, _make_builder(BOTH_STACKS_FACES))
    for obj_name, r in results.items():
        if "degenerate" in r:
            print(f"  {obj_name}: degenerate cut", flush=True)
            continue
        if "error" in r:
            print(f"  {obj_name}: ERROR {r['error']}", flush=True)
            continue
        fr = r["feasibility"]
        areas = r.get("region_areas") or {}
        print(f"  {obj_name}: outcome={fr['outcome']} failed_gate={fr['failed_gate']} "
              f"loops={r['loop_count']} single_loop={r['is_single_continuous_loop']} "
              f"cavity={r['cavity_face_count']} core={r['core_face_count']} "
              f"cavity_mm2={areas.get('cavity_area_mm2')} core_mm2={areas.get('core_area_mm2')} "
              f"h1={fr['measurements'].get('h1_closure_error_mm')} "
              f"h3={fr['measurements'].get('h3_region_count')} "
              f"h4={fr['measurements'].get('h4_orientation_violation_fraction')} "
              f"h7={fr['measurements'].get('h7_coverage')}", flush=True)


if __name__ == "__main__":
    run_symmetric_experiment()
