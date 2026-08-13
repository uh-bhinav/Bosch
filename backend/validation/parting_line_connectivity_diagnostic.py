"""
backend/validation/parting_line_connectivity_diagnostic.py
------------------------------------------------------------
Connectivity diagnosis, at CONTROLLED directions only (never the upstream
optimizer — see ``parting_line_profile.py``'s direction protocol and the
2026-08-12 direction-contamination audit).

B-20 (``docs/DECISIONS_AND_ALGORITHMS.md``) found that Part1/Part3's
silhouette segments largely fail to weld into the graph (Part1: 88% pruned,
Part3: 97%), leaving only small local cycles that correctly fail H3/H4. That
finding was measured entirely at the (unvalidated) optimizer direction. This
script re-measures the same thing at explicit, manually-chosen directions, and
adds the instrumentation the plan's diagnostic checklist asked for:

* every Track A / Track B segment, with full provenance
* every graph-welding decision (raw endpoint -> assigned node, distance to
  the node it joined, whether it was a weld or a new node)
* every node's degree and incident segments, before and after 2-core
* every segment pruned by 2-core, with its backing
* every connected component, before and after 2-core, with a Track A/B mix
* a ranked "gap report": every node that got pruned, paired with its nearest
  OTHER node in the full (pre-reduction) graph, so near-misses (numerically
  close, geometrically real) are distinguishable from genuine disconnections

This is READ-ONLY instrumentation. It calls the exact same pipeline functions
``analyse_parting_line`` calls (``detect_edge_silhouettes``,
``detect_face_silhouettes``, ``stitch_tracks``, ``build_graph``,
``reduce_to_two_core``) — it does not reimplement the algorithm, except for
two faithful, self-checking replicas needed to log per-endpoint decisions the
production functions don't expose: ``build_graph``'s weld loop, and
``stitch._snap_face_endpoints_to_edges``'s snap search. Both are asserted
equal to the real functions' output on every run, so a silent divergence
between a replica and production fails loudly rather than misleads.

Per the user's explicit instruction: this script does NOT propose or apply a
connectivity fix. It only measures and classifies.

--- P3.1 (2026-08-12) — direction-isolated connectivity diagnosis ---

A first fix attempt (raising the stitch snap tolerance, scoping its cut-
detection loop to genuinely-bounding edges) was regression-clean but did NOT
change the number of segments pruned by 2-core reduction on EITHER real part,
on any controlled direction tested. See D-022 in
``docs/DECISIONS_AND_ALGORITHMS.md``.

P3.1 answers a narrower, prior question this raised: given that the snap
search finds a structurally-correct candidate edge and moves the endpoint
onto it, why does a real gap remain? ``_diagnose_snap`` traces, for every
Track-B endpoint: which edge was chosen, its OCC parameter, the residual
distance BEFORE the snap, the residual distance AFTER re-projecting the
snapped point onto that SAME edge curve (must be ~0 by construction — if not,
the snap math itself is suspect), and the distance from the snapped point to
Track A's OWN segment endpoint on that same edge (the direct test of "are
Track A and Track B evaluating the same geometric entity, just failing to
connect for numerical reasons, or are they actually different points").

Per the direction-contamination concern raised separately: this run is
deliberately restricted to a small, explicit direction matrix (Part1 +Z/+X/+Y,
Part3 +Z/+X/+Y) rather than searching for a "good" direction on either part.
+Z is included per part specifically because it is each part's known
DIFFERENT regime (Part1: already `feasible`, zero pruning; Part3: zero
pruning but a highly-branched, all-local-loop graph) — the matrix is designed
to separate "is Track A/B/stitch/graph construction correct given d" from
"is d itself favourable", never to hunt for the latter.
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


def _diagnose_snap(part, track_a_segments, track_b_segments, *, tolerance_mm: float) -> dict:
    """
    P3.1 (2026-08-12) — faithful, read-only replica of
    ``stitch._snap_face_endpoints_to_edges``, logging every field the
    connectivity investigation asked for:

    original point/uv, every candidate edge considered (not just the winner),
    the chosen edge + its OCC parameter, the snapped 3D point, the residual
    BEFORE snap (original point -> chosen edge), the residual AFTER snap
    (re-projecting the snapped point onto the SAME edge curve -- this must be
    ~0 by construction; if it is not, the snap math itself is suspect, not
    just its search radius), and a cross-check against Track A's OWN segment
    on that edge (if one exists) -- the direct test of "are Track A and
    Track B evaluating the same geometric entity, just failing to connect for
    numerical reasons, or are they actually different points".

    Self-checked: the snapped point/uv for every endpoint must match what
    ``_snap_face_endpoints_to_edges`` itself produces, or this function
    raises -- a silent divergence here would defeat the whole point of the
    instrumentation.
    """
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
    from OCC.Core.GeomAPI import GeomAPI_ProjectPointOnCurve
    from OCC.Core.gp import gp_Pnt
    from OCC.Core.TopoDS import TopoDS_Edge

    from backend.geometry.parting_line_v2.stitch import _snap_face_endpoints_to_edges
    from backend.geometry.parting_line_v2.types import FaceBacking

    edges_by_id = {e.edge_id: e for e in part.edges}
    # Track A's own edge-backed segments, grouped by edge, for the
    # same-geometric-entity cross-check.
    track_a_by_edge: dict[int, list] = {}
    for seg in track_a_segments:
        if hasattr(seg.backing, "edge_id"):
            track_a_by_edge.setdefault(seg.backing.edge_id, []).append(seg)

    reference_segments, reference_snapped = _snap_face_endpoints_to_edges(
        part, track_b_segments, tolerance_mm=tolerance_mm
    )
    reference_by_id = {s.segment_id: s for s in reference_segments}

    records = []
    for segment in track_b_segments:
        backing = segment.backing
        if not isinstance(backing, FaceBacking):
            continue
        candidate_edge_ids = list(part.face_to_edges.get(backing.face_id, ()))
        if not candidate_edge_ids:
            continue

        points = list(segment.points)
        uvs = list(backing.uv)
        for index in (0, len(points) - 1):
            which = "start" if index == 0 else "end"
            original_point = points[index]
            candidates = []
            for edge_id in candidate_edge_ids:
                edge = edges_by_id.get(edge_id)
                if edge is None or not isinstance(edge.occ_edge, TopoDS_Edge):
                    continue
                try:
                    curve, first, last = BRep_Tool.Curve(edge.occ_edge)
                    if curve is None:
                        continue
                    projector = GeomAPI_ProjectPointOnCurve(
                        gp_Pnt(*original_point), curve, first, last
                    )
                    if projector.NbPoints() == 0:
                        continue
                    distance = float(projector.LowerDistance())
                    parameter = float(projector.LowerDistanceParameter())
                except Exception:
                    continue
                candidates.append({
                    "edge_id": edge_id, "distance_mm": round(distance, 9),
                    "parameter": round(parameter, 9), "within_tolerance": distance <= tolerance_mm,
                })
            candidates.sort(key=lambda c: c["distance_mm"])
            if not candidates:
                continue
            best = next((c for c in candidates if c["within_tolerance"]), None)

            record = {
                "face_id": backing.face_id, "endpoint": which,
                "original_point": [round(c, 6) for c in original_point],
                "original_uv": [round(c, 6) for c in uvs[index]],
                "candidates_considered": candidates[:5],
                "snapped": best is not None,
            }
            if best is not None:
                edge = edges_by_id[best["edge_id"]]
                adaptor = BRepAdaptor_Curve(edge.occ_edge)
                snapped_pnt = adaptor.Value(best["parameter"])
                snapped_point = (float(snapped_pnt.X()), float(snapped_pnt.Y()), float(snapped_pnt.Z()))
                # Residual AFTER snap: re-project the NEW point onto the SAME
                # edge curve. Must be ~0 by construction (it came from
                # adaptor.Value(parameter) on this exact curve) -- a nonzero
                # value here would mean the snap math itself is broken.
                reproj = GeomAPI_ProjectPointOnCurve(
                    gp_Pnt(*snapped_point), *BRep_Tool.Curve(edge.occ_edge)
                )
                residual_after_snap = float(reproj.LowerDistance()) if reproj.NbPoints() else None

                # Cross-check vs Track A's OWN segment(s) on this same edge:
                # the direct "same geometric entity" test.
                track_a_here = track_a_by_edge.get(best["edge_id"], [])
                nearest_track_a_mm = None
                if track_a_here:
                    nearest_track_a_mm = min(
                        min(math.dist(snapped_point, ta.start), math.dist(snapped_point, ta.end))
                        for ta in track_a_here
                    )

                record.update({
                    "chosen_edge_id": best["edge_id"],
                    "chosen_edge_parameter": best["parameter"],
                    "residual_before_snap_mm": best["distance_mm"],
                    "snapped_point": [round(c, 6) for c in snapped_point],
                    "residual_after_snap_mm": (
                        round(residual_after_snap, 9) if residual_after_snap is not None else None
                    ),
                    "track_a_segments_on_chosen_edge": len(track_a_here),
                    "nearest_track_a_endpoint_mm": (
                        round(nearest_track_a_mm, 9) if nearest_track_a_mm is not None else None
                    ),
                })
            records.append(record)

    # Self-check: the real function must have snapped exactly as many
    # endpoints as this replica decided to snap. `reference_snapped` counts
    # BOTH endpoints of every segment it moved; `snapped_records` here is
    # already per-endpoint, so the totals must match exactly.
    snapped_records = [r for r in records if r["snapped"]]
    assert len(snapped_records) == reference_snapped, (
        f"snap replica diverged from _snap_face_endpoints_to_edges: "
        f"replica snapped {len(snapped_records)}, real function snapped {reference_snapped}"
    )

    residuals_after = [
        r["residual_after_snap_mm"] for r in snapped_records
        if r["residual_after_snap_mm"] is not None
    ]
    nearest_track_a = [
        r["nearest_track_a_endpoint_mm"] for r in snapped_records
        if r["nearest_track_a_endpoint_mm"] is not None
    ]
    return {
        "endpoint_count": len(records),
        "snapped_count": len(snapped_records),
        "residual_after_snap_mm_max": round(max(residuals_after), 9) if residuals_after else None,
        "nearest_track_a_endpoint_mm_stats": {
            "n": len(nearest_track_a),
            "min": round(min(nearest_track_a), 6) if nearest_track_a else None,
            "median": round(sorted(nearest_track_a)[len(nearest_track_a) // 2], 6) if nearest_track_a else None,
            "max": round(max(nearest_track_a), 6) if nearest_track_a else None,
        },
        "records_sample": sorted(
            records, key=lambda r: r.get("nearest_track_a_endpoint_mm") or 0, reverse=True
        )[:30],
    }


def _diagnose_one(part_path: str, direction_label: str, direction: tuple, *, top_n: int) -> dict:
    from backend.config import settings
    from backend.geometry.parting_line_v2.contracts import PullDirectionInput, UndercutInput
    from backend.geometry.parting_line_v2.engine import _bbox_diagonal
    from backend.geometry.parting_line_v2.graph import (
        _cell, _components, _weld_tolerance, build_graph, reduce_to_two_core,
    )
    from backend.geometry.parting_line_v2.stitch import stitch_tracks
    from backend.geometry.parting_line_v2.track_a import detect_edge_silhouettes
    from backend.geometry.parting_line_v2.track_b import detect_face_silhouettes
    from backend.geometry.parting_line_v2.types import EdgeBacking, FaceBacking
    from backend.geometry.step_loader import load_step
    from OCC.Core.BRepAdaptor import BRepAdaptor_Curve

    cfg = settings.dfm.parting_line_v2
    part = load_step(part_path)
    pull = PullDirectionInput(direction, "manual")
    assert pull.is_correctness_evidence, "controlled-direction diagnostic must use a manual direction"

    bbox_diagonal = _bbox_diagonal(part)

    track_a = detect_edge_silhouettes(part, pull.direction, cfg=cfg, bbox_diagonal_mm=bbox_diagonal)
    track_b = detect_face_silhouettes(
        part, pull.direction, cfg=cfg, bbox_diagonal_mm=bbox_diagonal,
        start_segment_id=len(track_a.segments),
    )
    snap_tolerance_mm = max(cfg.stitch_snap_tolerance_rel * bbox_diagonal, 1e-6)
    stitched = stitch_tracks(
        part, track_a.segments, track_b.segments, tolerance_mm=snap_tolerance_mm,
    )
    all_segments = stitched.segments

    snap_diagnosis = _diagnose_snap(
        part, track_a.segments, track_b.segments, tolerance_mm=snap_tolerance_mm
    )

    # Full-pipeline stats (candidate count, H0-H7 rejections) via the real
    # production entry point -- reuses already-tested code rather than
    # re-deriving candidate generation and gate evaluation here.
    from backend.geometry.parting_line_v2.engine import analyse_parting_line
    full_result = analyse_parting_line(part, pull, undercuts=UndercutInput.empty(), cfg=cfg)

    # --- reference graph (production code, untouched) ----------------------
    reference_graph = build_graph(all_segments, bbox_diagonal_mm=bbox_diagonal, cfg=cfg)
    reference_node_count = len(reference_graph.node_points)
    reference_edge_count = len(reference_graph.segment_nodes)

    # --- instrumented replica: same tolerance, same neighbourhood search,
    #     but logs every weld decision -----------------------------------
    tolerance = _weld_tolerance(bbox_diagonal, cfg, kernel_tolerance_mm=0.0)
    buckets: dict[tuple, list[int]] = {}
    node_points: dict[int, tuple] = {}
    weld_log: list[dict] = []
    next_node = 0

    def node_for(point, *, segment_id, which):
        nonlocal next_node
        base = _cell(point, tolerance)
        best = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for node in buckets.get((base[0] + dx, base[1] + dy, base[2] + dz), ()):
                        d = math.dist(node_points[node], point)
                        if d <= tolerance and (best is None or d < best[1]):
                            best = (node, d)
        if best is not None:
            weld_log.append({
                "segment_id": segment_id, "endpoint": which, "point": list(point),
                "decision": "welded", "node_id": best[0], "distance_mm": best[1],
            })
            return best[0]
        node = next_node
        next_node += 1
        node_points[node] = point
        buckets.setdefault(base, []).append(node)
        weld_log.append({
            "segment_id": segment_id, "endpoint": which, "point": list(point),
            "decision": "new_node", "node_id": node, "distance_mm": None,
        })
        return node

    adjacency: dict[int, list[tuple]] = {}
    segment_nodes: dict[int, tuple] = {}
    for segment in sorted(all_segments, key=lambda s: s.segment_id):
        node_a = node_for(segment.start, segment_id=segment.segment_id, which="start")
        node_b = node_for(segment.end, segment_id=segment.segment_id, which="end")
        if node_a == node_b:
            adjacency.setdefault(node_a, []).append((node_b, segment.segment_id))
            adjacency.setdefault(node_a, []).append((node_b, segment.segment_id))
        else:
            adjacency.setdefault(node_a, []).append((node_b, segment.segment_id))
            adjacency.setdefault(node_b, []).append((node_a, segment.segment_id))
        segment_nodes[segment.segment_id] = (node_a, node_b)

    assert len(node_points) == reference_node_count, (
        f"instrumented replica diverged from build_graph: "
        f"{len(node_points)} nodes vs reference {reference_node_count}"
    )
    assert len(segment_nodes) == reference_edge_count

    segments_by_id = {s.segment_id: s for s in all_segments}

    def _degree(adj, n):
        return len(adj.get(n, ()))

    def _describe_backing(segment) -> dict:
        b = segment.backing
        if isinstance(b, EdgeBacking):
            edge = next((e for e in part.edges if e.edge_id == b.edge_id), None)
            return {
                "provenance": "edge", "edge_id": b.edge_id,
                "adjacent_face_ids": list(edge.adjacent_face_ids) if edge else None,
                "t_start": round(b.t_start, 9), "t_end": round(b.t_end, 9),
            }
        return {
            "provenance": "face", "face_id": b.face_id,
            "uv_start": [round(c, 6) for c in b.uv[0]] if b.uv else None,
            "uv_end": [round(c, 6) for c in b.uv[-1]] if b.uv else None,
        }

    def _segment_summary(segment_id: int) -> dict:
        s = segments_by_id[segment_id]
        return {
            "segment_id": segment_id, "kind": s.kind,
            "start": [round(c, 6) for c in s.start], "end": [round(c, 6) for c in s.end],
            "backing": _describe_backing(s),
        }

    def _component_summaries(adj, node_pts) -> list[dict]:
        seen: set = set()
        comps = []
        for start in sorted(adj):
            if start in seen:
                continue
            stack, group = [start], []
            seen.add(start)
            while stack:
                n = stack.pop()
                group.append(n)
                for nb, _ in adj.get(n, ()):
                    if nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
            seg_ids = sorted({sid for n in group for _, sid in adj.get(n, ())})
            provenance = {"edge": 0, "face": 0}
            for sid in seg_ids:
                provenance[segments_by_id[sid].provenance] += 1
            pts = [node_pts[n] for n in group]
            xs, ys, zs = [p[0] for p in pts], [p[1] for p in pts], [p[2] for p in pts]
            length = sum(
                math.dist(a, b)
                for sid in seg_ids
                for a, b in zip(segments_by_id[sid].points, segments_by_id[sid].points[1:])
            )
            comps.append({
                "node_count": len(group), "segment_count": len(seg_ids),
                "branch_node_count": sum(1 for n in group if _degree(adj, n) > 2),
                "bbox_mm": {"x": [round(min(xs), 4), round(max(xs), 4)],
                            "y": [round(min(ys), 4), round(max(ys), 4)],
                            "z": [round(min(zs), 4), round(max(zs), 4)]},
                "total_length_mm": round(length, 4),
                "track_a_segments": provenance["edge"], "track_b_segments": provenance["face"],
                "segment_ids": seg_ids,
            })
        comps.sort(key=lambda c: -c["segment_count"])
        return comps

    components_before = _component_summaries(adjacency, node_points)

    # --- reduce (mutates a copy so we keep the pre-reduction state) --------
    graph_copy_adj = {n: list(v) for n, v in adjacency.items()}
    graph_copy_nodes = dict(node_points)
    graph_copy_segnodes = dict(segment_nodes)

    class _GraphShim:
        pass

    shim = _GraphShim()
    shim.adjacency = graph_copy_adj
    shim.node_points = graph_copy_nodes
    shim.segment_nodes = graph_copy_segnodes
    shim.degree = lambda n: len(shim.adjacency.get(n, ()))

    stats = reduce_to_two_core(shim)  # mutates shim in place, returns ReductionStats

    components_after = _component_summaries(shim.adjacency, shim.node_points)
    surviving_nodes = set(shim.node_points)
    pruned_node_ids = sorted(n for n in node_points if n not in surviving_nodes)

    # --- pruned segments, with full backing -------------------------------
    pruned_segments = [_segment_summary(sid) for sid in sorted(stats.pruned_edge_ids)]

    # --- gap report: every pruned node vs its nearest OTHER node in the
    #     FULL pre-reduction graph (not just surviving ones) ---------------
    all_points = list(node_points.items())
    gap_report = []
    for node_id in pruned_node_ids:
        p = node_points[node_id]
        incident_segment_ids = sorted({sid for _, sid in adjacency.get(node_id, ())})
        # A node's OWN other endpoint (reached via one of its own incident
        # segments) is always spatially close and is never a candidate
        # connection worth repairing -- exclude it, or the "nearest node" is
        # trivially the segment's own far end and the gap report is noise.
        own_far_nodes = {nb for nb, sid in adjacency.get(node_id, ()) if sid in incident_segment_ids}
        best = None
        for other_id, other_p in all_points:
            if other_id == node_id or other_id in own_far_nodes:
                continue
            d = math.dist(p, other_p)
            if best is None or d < best[1]:
                best = (other_id, d)
        nearest_incident = sorted({sid for _, sid in adjacency.get(best[0], ())}) if best else []

        this_backing = [segments_by_id[sid].backing for sid in incident_segment_ids]
        near_backing = [segments_by_id[sid].backing for sid in nearest_incident]
        same_edge = any(
            isinstance(a, EdgeBacking) and isinstance(b, EdgeBacking) and a.edge_id == b.edge_id
            for a in this_backing for b in near_backing
        )
        same_face = any(
            isinstance(a, FaceBacking) and isinstance(b, FaceBacking) and a.face_id == b.face_id
            for a in this_backing for b in near_backing
        )
        # STRUCTURAL cross-track junction: an edge-backed segment on edge E
        # and a face-backed segment on face F, where E genuinely bounds F
        # (E in part.face_to_edges[F]). This is a real candidate junction
        # point regardless of how far apart they currently land -- distance
        # is evidence of HOW BADLY it failed to stitch, not whether it is
        # a junction at all.
        edge_face_pairs = [
            (a.edge_id, b.face_id) if isinstance(a, EdgeBacking) else (b.edge_id, a.face_id)
            for a in this_backing for b in near_backing
            if {type(a).__name__, type(b).__name__} == {"EdgeBacking", "FaceBacking"}
        ]
        structural_junction = any(
            edge_id in part.face_to_edges.get(face_id, ()) for edge_id, face_id in edge_face_pairs
        )
        cross_track = bool(edge_face_pairs)
        ratio = (best[1] / tolerance) if best and tolerance > 0 else float("inf")
        if best and best[1] <= tolerance:
            hint = "ANOMALY: within weld tolerance but not welded (possible spatial-hash bug)"
        elif structural_junction:
            hint = "C: Track-A/Track-B boundary junction not stitched (edge genuinely bounds this face)"
        elif same_edge:
            hint = "A: numerical tolerance gap (same OCC edge, endpoints not merged)"
        elif same_face:
            hint = "D/E: same face, different face-curve endpoints not merged (UV/seam candidate)"
        elif cross_track and ratio <= 50:
            hint = "C?: close, cross-track, but edge does not bound this face (inspect)"
        elif ratio <= 50:
            hint = "B/I: close but different provenance — inspect (possible duplicate OCC topology)"
        elif ratio <= 2000:
            hint = "F/G: moderate gap — inspect segment generation/termination"
        else:
            hint = "H: likely genuine geometric disconnection (far from any other node)"

        gap_report.append({
            "pruned_node_id": node_id, "point": [round(c, 6) for c in p],
            "incident_segment_ids": incident_segment_ids,
            "incident_segments": [_segment_summary(s) for s in incident_segment_ids],
            "nearest_node_id": best[0] if best else None,
            "nearest_node_point": [round(c, 6) for c in best[0] and node_points[best[0]]] if best else None,
            "distance_mm": round(best[1], 9) if best else None,
            "weld_tolerance_mm": round(tolerance, 9),
            "distance_over_tolerance": round(ratio, 2) if best else None,
            "nearest_incident_segments": [_segment_summary(s) for s in nearest_incident],
            "root_cause_hint": hint,
        })

    gap_report.sort(key=lambda g: (g["distance_mm"] if g["distance_mm"] is not None else float("inf")))

    # Which faces recur across the gap report -- a face implicated in many
    # independent gaps is a much stronger lead than any single gap.
    face_tally: dict[int, int] = {}
    for g in gap_report:
        for seg in g["incident_segments"] + g["nearest_incident_segments"]:
            b = seg["backing"]
            for fid in (b.get("adjacent_face_ids") or [b.get("face_id")]):
                if fid is not None:
                    face_tally[fid] = face_tally.get(fid, 0) + 1
    top_faces = sorted(face_tally.items(), key=lambda kv: -kv[1])[:15]

    all_dists = sorted(g["distance_mm"] for g in gap_report if g["distance_mm"] is not None)
    def _pct(p):
        if not all_dists:
            return None
        return round(all_dists[min(len(all_dists) - 1, int(p * (len(all_dists) - 1)))], 6)
    distance_percentiles = {
        "n": len(all_dists), "min": _pct(0.0), "p10": _pct(0.10), "p25": _pct(0.25),
        "p50": _pct(0.50), "p75": _pct(0.75), "p90": _pct(0.90), "max": _pct(1.0),
    }

    return {
        "direction_label": direction_label, "direction": list(pull.direction),
        "direction_source": pull.source, "is_correctness_evidence": pull.is_correctness_evidence,
        "bbox_diagonal_mm": round(bbox_diagonal, 4),
        "weld_tolerance_mm": round(tolerance, 9),
        "track_a": track_a.to_dict(), "track_b": track_b.to_dict(), "stitch": stitched.to_dict(),
        "graph_before_reduction": {
            "node_count": len(node_points), "edge_count": len(segment_nodes),
            "component_count": len(components_before), "components": components_before,
        },
        "graph_after_reduction": {
            "node_count": stats.nodes_after, "edge_count": stats.edges_after,
            "branch_node_count": stats.branch_node_count,
            "cyclomatic_number": stats.cyclomatic_number,
            "component_count": len(components_after), "components": components_after,
        },
        "pruned_segment_count": len(pruned_segments),
        "pruned_segments": pruned_segments,
        "gap_report_top_n": gap_report[:top_n],
        "gap_report_hint_counts": _count_hints(gap_report),
        "gap_report_top_faces": top_faces,
        "gap_report_distance_percentiles_mm": distance_percentiles,
        "snap_diagnosis": snap_diagnosis,
        "full_pipeline": {
            "outcome": full_result.outcome,
            "candidate_count": len(full_result.candidates),
            "rejection_summary": full_result.rejection_summary,
            "mu": full_result.bounds.cyclomatic_number,
            "branch_node_count": full_result.bounds.branch_node_count,
            "strategy": full_result.bounds.strategy,
        },
    }


def _count_hints(gap_report: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for g in gap_report:
        key = g["root_cause_hint"].split(":")[0]
        counts[key] = counts.get(key, 0) + 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part", default=str(REPO_ROOT / "data" / "parts" / "Part3.stp"))
    parser.add_argument("--directions", default="+X,-X,+Y,-Y,+Z,-Z")
    parser.add_argument("--top-n", type=int, default=50)
    parser.add_argument("--json", default="reports/connectivity_diagnostic_part3.json")
    args = parser.parse_args(argv)

    labels = [d.strip() for d in args.directions.split(",") if d.strip()]
    results = []
    for label in labels:
        direction = DIRECTIONS[label]
        print(f"--- {Path(args.part).stem} @ {label} {direction} ---")
        record = _diagnose_one(args.part, label, direction, top_n=args.top_n)
        results.append(record)
        gr = record["graph_before_reduction"]
        ar = record["graph_after_reduction"]
        print(
            f"  before: {gr['node_count']} nodes / {gr['edge_count']} edges / "
            f"{gr['component_count']} components"
        )
        print(
            f"  after:  {ar['node_count']} nodes / {ar['edge_count']} edges / "
            f"{ar['component_count']} components / mu={ar['cyclomatic_number']} / "
            f"branch={ar['branch_node_count']}"
        )
        print(f"  pruned: {record['pruned_segment_count']} segments")
        print(f"  gap-report hint counts: {record['gap_report_hint_counts']}")
        sd = record["snap_diagnosis"]
        print(
            f"  snap: {sd['snapped_count']}/{sd['endpoint_count']} endpoints snapped, "
            f"residual-after-snap max={sd['residual_after_snap_mm_max']}, "
            f"nearest-Track-A-endpoint stats={sd['nearest_track_a_endpoint_mm_stats']}"
        )
        fp = record["full_pipeline"]
        print(
            f"  full pipeline: outcome={fp['outcome']} candidates={fp['candidate_count']} "
            f"rejections={fp['rejection_summary']}"
        )

    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps({
        "part": Path(args.part).stem,
        "note": "Controlled directions only (direction_source=manual). "
                "Read-only instrumentation; no fix applied.",
        "directions": results,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"\nreport -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
