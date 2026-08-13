"""
backend/validation/parting_line_deep_verify.py
------------------------------------------------------------
P3.10 stage 2 (2026-08-13): deep, exhaustive verification for a small
shortlist of directions flagged promising by the cheap zero-level-network
pre-filter (`parting_line_spherical_search.py`).

For each direction, in order:
  1. Independent exhaustive cycle search (D-035 method: self-loops,
     parallel-edge 2-cycles, `networkx.simple_cycles` for longer cycles)
     on the RAW (pre-2-core) graph -- NOT `extract_loops`, NOT H3/H4.
  2. For every non-trivial closed loop found, geometric characterization:
     length, bbox, bbox/part-bbox ratio, face count, Track-A vs Track-B
     segment fraction, tangential fraction.
  3. Classification: CASE 0 (no cycle) / CASE 1 (local-feature cycles
     only) / CASE 2 (one global-looking cycle) / CASE 3 (multiple).
  4. The UNMODIFIED full production pipeline (`analyse_parting_line`) on
     the same direction, for direct comparison -- Track A/B, stitch,
     graph, candidates, H0-H7, valid count, core/cavity.
  5. The final A/B/C/D classification per the standing protocol:
       A: independent search finds no global loop -> direction not useful
       B: independent search finds a global loop, production can't build it
       C: production builds it, H3/H4 reject it -> investigate gates
       D: production builds it and it's valid -> Part3 positive control

Read-only. No production code touched.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _normalize(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def _exhaustive_cycles(part, direction, cfg, bbox_diagonal_mm):
    import networkx as nx
    from collections import defaultdict
    from backend.geometry.parting_line_v2.track_a import detect_edge_silhouettes
    from backend.geometry.parting_line_v2.track_b import detect_face_silhouettes
    from backend.geometry.parting_line_v2.stitch import stitch_tracks
    from backend.geometry.parting_line_v2.graph import build_graph
    from backend.geometry.parting_line_v2.types import EdgeBacking, FaceBacking

    d = _normalize(direction)
    track_a = detect_edge_silhouettes(part, d, cfg=cfg, bbox_diagonal_mm=bbox_diagonal_mm)
    track_b = detect_face_silhouettes(
        part, d, cfg=cfg, bbox_diagonal_mm=bbox_diagonal_mm, start_segment_id=len(track_a.segments)
    )
    stitched = stitch_tracks(
        part, track_a.segments, track_b.segments,
        tolerance_mm=max(cfg.stitch_snap_tolerance_rel * bbox_diagonal_mm, 1e-6),
    )
    segs_by_id = {s.segment_id: s for s in stitched.segments}
    graph = build_graph(stitched.segments, bbox_diagonal_mm=bbox_diagonal_mm, cfg=cfg)

    G = nx.MultiGraph()
    for node in graph.node_points:
        G.add_node(node)
    for seg_id, (a, b) in graph.segment_nodes.items():
        G.add_edge(a, b, segment_id=seg_id)

    found_loops = []  # list of list-of-segment-ids

    by_pair = defaultdict(list)
    for seg_id, (a, b) in graph.segment_nodes.items():
        if a == b:
            found_loops.append([seg_id])
        else:
            by_pair[tuple(sorted((a, b)))].append(seg_id)

    for pair, segids in by_pair.items():
        if len(segids) >= 2:
            # every combination of 2 parallel segments is its own 2-cycle
            for i in range(len(segids)):
                for j in range(i + 1, len(segids)):
                    found_loops.append([segids[i], segids[j]])

    simple = nx.Graph()
    node_pair_to_seg = {}
    for (a, b), segids in by_pair.items():
        simple.add_edge(a, b)
        node_pair_to_seg[(a, b)] = segids[0]
        node_pair_to_seg[(b, a)] = segids[0]

    # mu of the (parallel-edges-collapsed) simple graph -- exhaustive
    # `simple_cycles` (Johnson) is exponential in the number of simple
    # cycles, which explodes combinatorially well before mu=20 on graphs
    # this size (measured directly: still running after 2+ minutes on the
    # first mu~98 direction here, so killed and abandoned). Production
    # itself gates Johnson behind `mu_max_for_johnson` (default 12) for
    # exactly this reason. Match that discipline: exhaustive enumeration
    # below the threshold, `nx.cycle_basis` (polynomial, one cycle per
    # independent basis element, NOT every simple cycle) above it -- an
    # explicit, honest downgrade, not silently pretending completeness.
    exhaustive_threshold = 20
    per_component_mu = []
    node_cycle_source = "exhaustive (Johnson, networkx.simple_cycles)"
    all_node_cycles = []
    for comp_nodes in nx.connected_components(simple):
        comp = simple.subgraph(comp_nodes)
        comp_mu = comp.number_of_edges() - comp.number_of_nodes() + 1
        per_component_mu.append(comp_mu)
        if comp_mu <= 0:
            continue
        if comp_mu <= exhaustive_threshold:
            all_node_cycles.extend(nx.simple_cycles(comp, length_bound=None))
        else:
            node_cycle_source = "cycle_basis (mu too large for exhaustive Johnson enumeration)"
            all_node_cycles.extend(nx.cycle_basis(comp))

    for node_cycle in all_node_cycles:
        seg_cycle = []
        for i in range(len(node_cycle)):
            a, b = node_cycle[i], node_cycle[(i + 1) % len(node_cycle)]
            seg_cycle.append(node_pair_to_seg[(a, b)])
        found_loops.append(seg_cycle)

    # characterize each loop
    part_bbox = part.occ_shape if hasattr(part, "occ_shape") else None
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRepBndLib import brepbndlib
    box = Bnd_Box()
    brepbndlib.Add(part.occ_shape, box)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    part_bbox_diag = math.dist((xmin, ymin, zmin), (xmax, ymax, zmax))

    characterized = []
    for seg_ids in found_loops:
        segs = [segs_by_id[i] for i in seg_ids]
        all_points = [p for s in segs for p in s.points]
        xs = [p[0] for p in all_points]; ys = [p[1] for p in all_points]; zs = [p[2] for p in all_points]
        loop_bbox_diag = math.dist((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))
        length = sum(
            math.dist(s.points[i], s.points[i + 1])
            for s in segs for i in range(len(s.points) - 1)
        )
        faces_touched = set()
        edge_backed = 0
        face_backed = 0
        tangential = 0
        for s in segs:
            if isinstance(s.backing, EdgeBacking):
                edge_backed += 1
                faces_touched.update(part.edge_to_faces.get(s.backing.edge_id, []))
            else:
                face_backed += 1
                faces_touched.add(s.backing.face_id)
            if s.kind == "tangential":
                tangential += 1
        n = len(segs)
        bbox_ratio = loop_bbox_diag / part_bbox_diag if part_bbox_diag else 0.0
        if n <= 2:
            case = "local (trivial self-loop / 2-segment)"
        elif bbox_ratio >= 0.5 and len(faces_touched) >= 5:
            case = "GLOBAL-LOOKING"
        else:
            case = "local-feature"
        characterized.append({
            "segment_ids": seg_ids,
            "segment_count": n,
            "length_mm": round(length, 3),
            "bbox_ratio_of_part": round(bbox_ratio, 4),
            "faces_touched": len(faces_touched),
            "edge_backed_count": edge_backed,
            "face_backed_count": face_backed,
            "tangential_count": tangential,
            "classification": case,
        })

    global_loops = [c for c in characterized if c["classification"] == "GLOBAL-LOOKING"]
    if not characterized:
        overall_case = "CASE 0: no closed zero-level cycle"
    elif not global_loops:
        overall_case = "CASE 1: only local-feature cycles"
    elif len(global_loops) == 1:
        overall_case = "CASE 2: one global-looking closed cycle"
    else:
        overall_case = "CASE 3: multiple global-looking closed cycles"

    return {
        "direction": d,
        "total_loops_found": len(characterized),
        "loops": characterized,
        "overall_case": overall_case,
        "cycle_search_method": node_cycle_source,
    }


def _production_pipeline(part, direction, cfg):
    from backend.geometry.parting_line_v2.contracts import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import analyse_parting_line

    d = _normalize(direction)
    pull = PullDirectionInput(d, "manual")
    result = analyse_parting_line(part, pull, undercuts=UndercutInput.empty(), cfg=cfg)
    h_counts = {"h0": 0, "h1": 0, "h2": 0, "h3": 0, "h4": 0, "h5_h7": 0}
    for c in result.candidates:
        if c.feasibility and not c.feasibility.passed:
            gate = (c.feasibility.failed_gate or "").lower()
            h_counts[gate if gate in h_counts else "h5_h7"] += 1
    valid = [c for c in result.candidates if c.feasibility and c.feasibility.passed]
    out = {
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
        out["best_candidate_coverage"] = round(result.selected.score.coverage, 4) if result.selected.score else None
        if result.regions is not None:
            out["cavity_face_count"] = len(result.regions.cavity_face_ids)
            out["core_face_count"] = len(result.regions.core_face_ids)
    return out


def classify_a_b_c_d(independent_case: str, pl_result: dict) -> str:
    has_global = "GLOBAL-LOOKING" in independent_case or independent_case.startswith("CASE 2") or independent_case.startswith("CASE 3")
    valid = pl_result["fully_valid_candidate_count"] > 0
    produced_candidates = pl_result["candidate_count"] > 0
    if not has_global:
        return "A: independent diagnostic finds no global loop -> direction not useful"
    if has_global and valid:
        return "D: valid Part3 parting line found"
    if has_global and not produced_candidates:
        return "B: independent global loop exists but production builds nothing -> ALGORITHM DEFECT"
    if has_global and produced_candidates and not valid:
        return "C: production builds candidates but H3/H4 reject them -> investigate gates"
    return "UNCLASSIFIED"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part", default="Part3.stp")
    parser.add_argument("--directions-json", required=True, help="JSON file: {label: [dx,dy,dz]}")
    parser.add_argument("--out", default="reports/parting_line_deep_verify.json")
    args = parser.parse_args(argv)

    from backend.config import settings
    from backend.geometry.parting_line_v2.engine import _bbox_diagonal
    from backend.geometry.step_loader import load_step

    cfg = settings.dfm.parting_line_v2
    part = load_step(str(REPO_ROOT / "data" / "parts" / args.part))
    bbox_diagonal = _bbox_diagonal(part)

    directions = json.loads(Path(args.directions_json).read_text())

    results = {}
    for label, direction in directions.items():
        print(f"=== {label} ({direction}) ===")
        indep = _exhaustive_cycles(part, tuple(direction), cfg, bbox_diagonal)
        print(f"  independent: {indep['overall_case']}, {indep['total_loops_found']} total loops")
        for loop in indep["loops"]:
            if loop["classification"] == "GLOBAL-LOOKING":
                print(f"    GLOBAL LOOP: {loop}")
        pl = _production_pipeline(part, tuple(direction), cfg)
        print(f"  production: candidates={pl['candidate_count']} h3={pl['h3']} h4={pl['h4']} valid={pl['fully_valid_candidate_count']}")
        classification = classify_a_b_c_d(indep["overall_case"], pl)
        print(f"  CLASSIFICATION: {classification}")
        results[label] = {"independent": indep, "production": pl, "classification": classification}

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nreport -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
