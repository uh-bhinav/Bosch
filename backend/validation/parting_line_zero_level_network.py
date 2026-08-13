"""
backend/validation/parting_line_zero_level_network.py
------------------------------------------------------------
P3.10 (2026-08-13): a cheap, direction-scannable diagnostic for "does a
non-trivial closed zero-level loop exist near here at all" -- independent
of `extract_loops` (cycle_basis/Johnson), H0-H7, and ranking (same
independence discipline as D-035, generalized into a reusable, fast
per-direction metric so it can be swept over many directions instead of
computed once by hand).

Reuses Track A/B detection and `build_graph` (graph CONSTRUCTION, not
candidate generation -- legitimate per the standing instruction). Stops
short of exhaustive `networkx.simple_cycles` enumeration in the bulk
sweep (that is what made D-035's Part1 run combinatorially infeasible at
mu=113) and instead reports fast structural proxies:

  - `component_count`, `largest_component_fraction` (D-035's "how
    concentrated is the silhouette-relevant geometry" signal -- Part1 +Z
    scored 90%, Part3's CASE-A directions scored 6-8%)
  - `mu_total` (total cyclomatic number across the whole raw graph)
  - `self_loop_count` (trivial 1-segment cycles, always countable in
    O(E), no enumeration needed)
  - `non_trivial_mu` = `mu_total - self_loop_count`, a cheap proxy for
    "how much REAL multi-segment cyclic content exists, beyond trivial
    self-loops" -- D-035 found Part3's CASE-A directions have
    `non_trivial_mu` at or near 0 (all-self-loop cyclomatic content);
    Part1 +Z has `non_trivial_mu` ~109-113.

Exhaustive `networkx.simple_cycles` enumeration (expensive, and
infeasible for large mu) is reserved for a SEPARATE, second-stage script
that only runs it on the shortlisted top candidates this cheap pass
identifies.

Read-only. No production code touched.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ZeroLevelNetworkSummary:
    direction: tuple
    track_a_segments: int
    track_b_segments: int
    stitched_segments: int
    node_count: int
    edge_count: int
    component_count: int
    largest_component_size: int
    largest_component_fraction: float
    mu_total: int
    self_loop_count: int
    non_trivial_mu: int
    #: coarse classification, NOT a production gate -- CASE 0-3 per the
    #: standing protocol, based on cheap proxies only (upgraded to a
    #: precise classification only after exhaustive verification in stage 2)
    coarse_case: str

    def to_dict(self) -> dict:
        return {
            "direction": list(self.direction),
            "track_a_segments": self.track_a_segments,
            "track_b_segments": self.track_b_segments,
            "stitched_segments": self.stitched_segments,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "component_count": self.component_count,
            "largest_component_size": self.largest_component_size,
            "largest_component_fraction": self.largest_component_fraction,
            "mu_total": self.mu_total,
            "self_loop_count": self.self_loop_count,
            "non_trivial_mu": self.non_trivial_mu,
            "coarse_case": self.coarse_case,
        }


def _normalize(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def summarize_zero_level_network(part, direction: tuple, cfg, bbox_diagonal_mm: float) -> ZeroLevelNetworkSummary:
    from backend.geometry.parting_line_v2.track_a import detect_edge_silhouettes
    from backend.geometry.parting_line_v2.track_b import detect_face_silhouettes
    from backend.geometry.parting_line_v2.stitch import stitch_tracks
    from backend.geometry.parting_line_v2.graph import build_graph

    d = _normalize(direction)
    track_a = detect_edge_silhouettes(part, d, cfg=cfg, bbox_diagonal_mm=bbox_diagonal_mm)
    track_b = detect_face_silhouettes(
        part, d, cfg=cfg, bbox_diagonal_mm=bbox_diagonal_mm, start_segment_id=len(track_a.segments)
    )
    stitched = stitch_tracks(
        part, track_a.segments, track_b.segments,
        tolerance_mm=max(cfg.stitch_snap_tolerance_rel * bbox_diagonal_mm, 1e-6),
    )
    graph = build_graph(stitched.segments, bbox_diagonal_mm=bbox_diagonal_mm, cfg=cfg)

    node_count = len(graph.node_points)
    edge_count = len(graph.segment_nodes)

    # connected components + self-loop count, both O(V+E), no enumeration
    seen: set[int] = set()
    components: list[int] = []
    self_loop_count = 0
    for seg_id, (a, b) in graph.segment_nodes.items():
        if a == b:
            self_loop_count += 1
    for start in graph.adjacency:
        if start in seen:
            continue
        stack, size = [start], 0
        seen.add(start)
        while stack:
            node = stack.pop()
            size += 1
            for nb, _sid in graph.adjacency.get(node, ()):
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        components.append(size)

    component_count = len(components)
    largest_component_size = max(components, default=0)
    largest_component_fraction = (
        largest_component_size / node_count if node_count else 0.0
    )
    mu_total = edge_count - node_count + component_count if node_count else 0
    non_trivial_mu = max(0, mu_total - self_loop_count)

    if mu_total == 0:
        coarse_case = "CASE 0: no closed zero-level cycle"
    elif non_trivial_mu == 0:
        coarse_case = "CASE 1: only trivial self-loop cycles"
    elif largest_component_fraction >= 0.5:
        coarse_case = "CASE 2/3: substantial cyclic content in a dominant component"
    else:
        coarse_case = "CASE 1: non-trivial cycles exist but not in a dominant/large component"

    return ZeroLevelNetworkSummary(
        direction=d,
        track_a_segments=len(track_a.segments),
        track_b_segments=len(track_b.segments),
        stitched_segments=len(stitched.segments),
        node_count=node_count,
        edge_count=edge_count,
        component_count=component_count,
        largest_component_size=largest_component_size,
        largest_component_fraction=round(largest_component_fraction, 4),
        mu_total=mu_total,
        self_loop_count=self_loop_count,
        non_trivial_mu=non_trivial_mu,
        coarse_case=coarse_case,
    )
