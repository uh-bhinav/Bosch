"""
backend/geometry/parting_line_v2/graph.py
-----------------------------------------
Silhouette graph: welding, reduction, and loop extraction (plan §5, §6).

Node/edge choice (plan §5.1)
---------------------------
Nodes are **welded 3-D points**; edges are **curve segments**. This answers
"which segments form a loop", which is the parting-line question. The dual
choice — nodes = faces, edges = shared edges — answers "which side is this
face on", which is the core/cavity question, and lives in ``regions.py``.
Both are needed, for their respective stages.

Reduction (plan §5.4)
---------------------
Two ``O(V+E)`` passes run before any search:

1. **2-core** — iteratively delete every node of degree ≤ 1. A degree-1 node
   cannot lie on any cycle, so what survives is the only part of the graph
   that can contain a loop.
2. **Degree-2 chain contraction** — *not physically performed at Level 0*, and
   deliberately so. The quantities P3a needs are the cyclomatic number ``μ``
   and the branch-node count, and **both are invariant under contraction**:
   collapsing a chain of ``k`` edges removes ``k−1`` nodes and ``k−1`` edges,
   leaving ``μ = E − V + P`` unchanged. No Level-0 search benefits from the
   smaller graph either. Building it now would be machinery with no measured
   need — exactly what plan §6.1's build-order gate forbids.

Loop extraction (plan §6.1)
---------------------------
Strategy is chosen by the reduced graph's shape, and **reported**:

======================  ===================================================
reduced graph empty     ``none`` — no loop can exist. Report it and stop.
every node degree 2     ``single_cycle`` — each component IS a cycle. O(V+E)
branch nodes remain     ``cycle_basis`` — μ fundamental cycles from a
                        spanning forest, O(E·V) worst case
======================  ===================================================

Johnson enumeration and beam search are **not implemented**, per the plan's
build-order gate: P3a measures the ``μ`` distribution across the corpus first,
and only branches with real mass get written.
"""

from __future__ import annotations

import itertools
import math
import time
from collections import deque
from dataclasses import dataclass, field

from backend.geometry.parting_line_v2.types import CurveSegment
from backend.models.geometry_models import Vec3

try:
    import networkx as nx  # type: ignore[import-untyped]
    _NX_AVAILABLE = True
except ImportError:  # pragma: no cover
    _NX_AVAILABLE = False
    nx = None  # type: ignore[assignment]

__all__ = ["SilhouetteGraph", "ReductionStats", "build_graph", "extract_loops"]


@dataclass(frozen=True)
class ReductionStats:
    """What §5.4's reduction did, reported so a degraded run is never silent."""

    nodes_before: int
    edges_before: int
    nodes_after: int
    edges_after: int
    branch_node_count: int
    component_count: int
    cyclomatic_number: int
    pruned_edge_ids: tuple[int, ...] = ()

    def to_dict(self) -> dict:
        return {
            "nodes_before": self.nodes_before,
            "edges_before": self.edges_before,
            "nodes_after": self.nodes_after,
            "edges_after": self.edges_after,
            "branch_node_count": self.branch_node_count,
            "component_count": self.component_count,
            "cyclomatic_number": self.cyclomatic_number,
            "pruned_edge_count": len(self.pruned_edge_ids),
        }


@dataclass
class SilhouetteGraph:
    """A welded multigraph over curve-segment endpoints."""

    node_points: dict[int, Vec3] = field(default_factory=dict)
    #: segment_id -> (node_a, node_b)
    segment_nodes: dict[int, tuple[int, int]] = field(default_factory=dict)
    #: node -> list of (neighbour_node, segment_id). A MULTIgraph: two segments
    #: may join the same pair of nodes (a circle split into two runs does).
    adjacency: dict[int, list[tuple[int, int]]] = field(default_factory=dict)
    segments_by_id: dict[int, CurveSegment] = field(default_factory=dict)
    weld_tolerance_mm: float = 0.0

    def degree(self, node: int) -> int:
        return len(self.adjacency.get(node, ()))

    def live_segment_ids(self) -> list[int]:
        return sorted(self.segment_nodes)


def _weld_tolerance(bbox_diagonal_mm: float, cfg: object, kernel_tolerance_mm: float) -> float:
    """
    ``τ_weld = max(kernel tolerance, bbox_diag × rel, absolute floor)``.

    v1 uses a flat ``point_tolerance = 1e-4 mm`` (audit RC-9): scale-blind and
    kernel-blind. A STEP file carries its own tolerances, set by the
    originating CAD system, and ignoring them is the standard cause of "works
    in NX, fragments in our tool".

    Level 0 uses one **global** kernel tolerance (the part's maximum vertex
    tolerance) rather than a per-vertex value. That is the conservative
    direction — a larger weld radius merges more, never less — and it keeps
    the welding pass independent of OCC. Per-vertex refinement is only worth
    building if a part is ever measured to need it.
    """
    return max(kernel_tolerance_mm, cfg.weld_tolerance_rel * bbox_diagonal_mm, 1e-7)


def _cell(point: Vec3, size: float) -> tuple[int, int, int]:
    return (
        int(math.floor(point[0] / size)),
        int(math.floor(point[1] / size)),
        int(math.floor(point[2] / size)),
    )


def build_graph(
    segments: tuple[CurveSegment, ...],
    *,
    bbox_diagonal_mm: float,
    cfg: object,
    kernel_tolerance_mm: float = 0.0,
) -> SilhouetteGraph:
    """
    Weld segment endpoints into graph nodes.

    Uses a **spatial hash checked across all 27 neighbouring cells**, not
    integer quantisation. v1 quantises coordinates into integer keys
    (``parting_line._point_key``), which has a grid-boundary failure mode:
    two points ``0.6 × τ`` apart can land in different cells and never merge,
    fragmenting a silhouette that is actually connected. Checking the
    neighbourhood removes that failure entirely.
    """
    tolerance = _weld_tolerance(bbox_diagonal_mm, cfg, kernel_tolerance_mm)
    graph = SilhouetteGraph(weld_tolerance_mm=tolerance)
    buckets: dict[tuple[int, int, int], list[int]] = {}
    next_node = 0

    def node_for(point: Vec3) -> int:
        nonlocal next_node
        base = _cell(point, tolerance)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for node in buckets.get((base[0] + dx, base[1] + dy, base[2] + dz), ()):
                        if math.dist(graph.node_points[node], point) <= tolerance:
                            return node
        node = next_node
        next_node += 1
        graph.node_points[node] = point
        buckets.setdefault(base, []).append(node)
        return node

    for segment in sorted(segments, key=lambda s: s.segment_id):
        node_a = node_for(segment.start)
        node_b = node_for(segment.end)
        if node_a == node_b:
            # A segment whose endpoints weld together is a SELF-LOOP: a full
            # closed curve on its own — a hole rim, a cylinder rim, a cone's
            # base circle. It is already a valid one-segment cycle.
            #
            # It must be recorded TWICE so the node's degree is 2. Recording
            # it once gives degree 1, and `reduce_to_two_core` then deletes it
            # as a dangling end. Measured: that silently discarded F9's hole
            # rim (leaving the top face connected to the bottom through the
            # hole wall, so no candidate could ever separate the part), plus
            # F2's and F5's rim circles — which ARE those parts' correct
            # parting lines. A self-loop contributes 2 to the degree by the
            # standard graph convention, and here that convention is load-
            # bearing rather than pedantic.
            graph.adjacency.setdefault(node_a, []).append((node_b, segment.segment_id))
            graph.adjacency.setdefault(node_a, []).append((node_b, segment.segment_id))
        else:
            graph.adjacency.setdefault(node_a, []).append((node_b, segment.segment_id))
            graph.adjacency.setdefault(node_b, []).append((node_a, segment.segment_id))
        graph.segment_nodes[segment.segment_id] = (node_a, node_b)
        graph.segments_by_id[segment.segment_id] = segment

    return graph


def reduce_to_two_core(graph: SilhouetteGraph) -> ReductionStats:
    """
    Iteratively delete degree ≤ 1 nodes. Mutates ``graph`` in place.

    A degree-1 node cannot lie on any cycle, and deleting it can expose
    another — hence the fixpoint loop. Typically collapses a real silhouette
    graph to exactly its loops.
    """
    nodes_before = len(graph.node_points)
    edges_before = len(graph.segment_nodes)
    pruned: list[int] = []

    queue = deque(n for n in graph.adjacency if len(graph.adjacency[n]) <= 1)
    while queue:
        node = queue.popleft()
        incident = graph.adjacency.get(node)
        if incident is None or len(incident) > 1:
            continue
        for neighbour, segment_id in list(incident):
            graph.adjacency[neighbour] = [
                (n, s) for (n, s) in graph.adjacency.get(neighbour, []) if s != segment_id
            ]
            graph.segment_nodes.pop(segment_id, None)
            pruned.append(segment_id)
            if len(graph.adjacency.get(neighbour, [])) <= 1:
                queue.append(neighbour)
        graph.adjacency.pop(node, None)
        graph.node_points.pop(node, None)

    live_nodes = {n for n, inc in graph.adjacency.items() if inc}
    graph.adjacency = {n: inc for n, inc in graph.adjacency.items() if inc}
    graph.node_points = {n: p for n, p in graph.node_points.items() if n in live_nodes}

    components = _components(graph)
    branch_nodes = sum(1 for n in graph.adjacency if graph.degree(n) > 2)
    edges_after = len(graph.segment_nodes)
    nodes_after = len(graph.node_points)
    # mu = E - V + P (cyclomatic number / first Betti number)
    mu = edges_after - nodes_after + len(components) if nodes_after else 0

    return ReductionStats(
        nodes_before=nodes_before,
        edges_before=edges_before,
        nodes_after=nodes_after,
        edges_after=edges_after,
        branch_node_count=branch_nodes,
        component_count=len(components),
        cyclomatic_number=max(0, mu),
        pruned_edge_ids=tuple(sorted(set(pruned))),
    )


def _components(graph: SilhouetteGraph) -> list[list[int]]:
    seen: set[int] = set()
    components: list[list[int]] = []
    for start in sorted(graph.adjacency):
        if start in seen:
            continue
        stack, group = [start], []
        seen.add(start)
        while stack:
            node = stack.pop()
            group.append(node)
            for neighbour, _ in graph.adjacency.get(node, ()):
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        components.append(sorted(group))
    return components


def _walk_cycle(graph: SilhouetteGraph, component: list[int]) -> list[int] | None:
    """Ordered segment ids around an all-degree-2 component."""
    start = component[0]
    ordered: list[int] = []
    visited_segments: set[int] = set()
    current = start
    previous_segment = -1

    while True:
        options = [
            (n, s) for (n, s) in graph.adjacency.get(current, ())
            if s != previous_segment and s not in visited_segments
        ]
        if not options:
            break
        neighbour, segment_id = sorted(options, key=lambda x: x[1])[0]
        ordered.append(segment_id)
        visited_segments.add(segment_id)
        previous_segment = segment_id
        current = neighbour
        if current == start:
            break

    if current != start or not ordered:
        return None
    return ordered


def _spanning_forest(graph: SilhouetteGraph) -> tuple[dict[int, int], dict[int, int], set[int]]:
    """BFS forest. Returns (parent_node, parent_segment, tree_segment_ids)."""
    parent_node: dict[int, int] = {}
    parent_segment: dict[int, int] = {}
    tree_segments: set[int] = set()
    seen: set[int] = set()

    for root in sorted(graph.adjacency):
        if root in seen:
            continue
        seen.add(root)
        queue = deque([root])
        while queue:
            node = queue.popleft()
            for neighbour, segment_id in sorted(graph.adjacency.get(node, ()), key=lambda x: x[1]):
                if neighbour in seen:
                    continue
                seen.add(neighbour)
                parent_node[neighbour] = node
                parent_segment[neighbour] = segment_id
                tree_segments.add(segment_id)
                queue.append(neighbour)
    return parent_node, parent_segment, tree_segments


def _path_to_root(node: int, parent_node: dict[int, int]) -> list[int]:
    path = [node]
    while node in parent_node:
        node = parent_node[node]
        path.append(node)
    return path


def _fundamental_cycles(graph: SilhouetteGraph) -> list[list[int]]:
    """
    One cycle per non-tree edge — the fundamental cycle basis.

    A connected graph has exactly ``μ = E − V + 1`` independent cycles, and
    this produces all of them in ``O(E·V)``. It is a **basis**, not the full
    set of simple cycles: a basis cycle can be a small artefact loop, and some
    physically meaningful loops are sums of basis members. That is the
    documented Level-0 limitation — enumerating all simple cycles (Johnson) is
    exponential and gated behind P3a's measurement.
    """
    parent_node, parent_segment, tree_segments = _spanning_forest(graph)
    cycles: list[list[int]] = []

    for segment_id in sorted(graph.segment_nodes):
        if segment_id in tree_segments:
            continue
        node_a, node_b = graph.segment_nodes[segment_id]
        if node_a == node_b:
            cycles.append([segment_id])          # self-loop: already a cycle
            continue

        path_a = _path_to_root(node_a, parent_node)
        path_b = _path_to_root(node_b, parent_node)
        set_b = {n: i for i, n in enumerate(path_b)}
        meeting = next((n for n in path_a if n in set_b), None)
        if meeting is None:
            continue                              # different components

        branch_a = path_a[: path_a.index(meeting) + 1]
        branch_b = path_b[: set_b[meeting]]
        node_cycle = branch_a + list(reversed(branch_b))

        segment_cycle: list[int] = [segment_id]
        ok = True
        for i in range(len(node_cycle) - 1):
            child, parent = node_cycle[i], node_cycle[i + 1]
            link = parent_segment.get(child)
            if link is None or parent_node.get(child) != parent:
                link = parent_segment.get(parent)
                if link is None or parent_node.get(parent) != child:
                    ok = False
                    break
            segment_cycle.append(link)
        if ok and len(segment_cycle) >= 1:
            cycles.append(segment_cycle)

    return cycles


def _johnson_cycles(
    graph: SilhouetteGraph, *, max_candidates: int, time_budget_s: float
) -> tuple[list[list[int]], bool, bool]:
    """
    Enumerate **every** simple cycle, bounded (plan §6.1).

    Built at P3b, and only because P3a's corpus measurement justified it.
    The ``μ`` distribution over 22 parts came out:

        μ == 1            4  (18.2%)
        2 <= μ <= 12     17  (77.3%)   <- dominant
        μ  > 12           1  ( 4.5%)

    §6.1's gate maps a dominant ``2 ≤ μ ≤ 12`` band to "add bounded Johnson,
    still skip beam search", and a single part at ``μ = 25`` is not the "real
    mass above 12" that would justify beam. So Johnson is written and beam is
    not — a decision made by data, not preference.

    **Why this is needed at all.** A fundamental cycle *basis* spans the cycle
    space but its members need not be physically meaningful loops: the real
    parting line can be a *sum* of basis cycles. Measured at P2, every
    candidate on both real parts was rejected (Part1 5/5 at H4, Part3 6/6 at
    H3) while the basis was all that had been generated.

    ``networkx.simple_cycles`` returns **node** cycles. Parallel edges are
    distinct curve segments here (a circle split into two runs joins the same
    pair of nodes twice), so each node cycle is expanded over its parallel-edge
    choices. Returns ``(cycles, cap_hit, budget_hit)``.
    """
    if not _NX_AVAILABLE or not graph.segment_nodes:
        return [], False, False

    multigraph = nx.MultiGraph()  # type: ignore[union-attr]
    for segment_id, (node_a, node_b) in sorted(graph.segment_nodes.items()):
        if node_a != node_b:
            multigraph.add_edge(node_a, node_b, key=segment_id)

    parallel: dict[tuple[int, int], list[int]] = {}
    for segment_id, (node_a, node_b) in graph.segment_nodes.items():
        if node_a != node_b:
            parallel.setdefault((min(node_a, node_b), max(node_a, node_b)), []).append(segment_id)
    for key in parallel:
        parallel[key].sort()

    cycles: list[list[int]] = []
    seen: set[frozenset[int]] = set()
    started = time.perf_counter()
    cap_hit = budget_hit = False

    # Self-loops FIRST. A closed circular edge (a hole rim, a cylinder rim)
    # welds to a single node, and `nx.simple_cycles` on the multigraph built
    # above cannot return it because self-loops are excluded from that graph.
    # Each is already a complete one-segment cycle.
    #
    # This is D-006's failure mode returning by a different route: omitting it
    # silently dropped F9's hole rim from the candidate set, so the only Γ that
    # separates a holed part — outer rim ⊔ hole rim — could never be formed.
    for segment_id, (node_a, node_b) in sorted(graph.segment_nodes.items()):
        if node_a == node_b:
            signature = frozenset({segment_id})
            if signature not in seen:
                seen.add(signature)
                cycles.append([segment_id])

    try:
        for node_cycle in nx.simple_cycles(multigraph):  # type: ignore[union-attr]
            if time.perf_counter() - started > time_budget_s:
                budget_hit = True
                break
            if len(cycles) >= max_candidates:
                cap_hit = True
                break
            if len(node_cycle) < 2:
                continue

            if len(node_cycle) == 2:
                # A 2-cycle traverses two DISTINCT parallel edges.
                key = (min(node_cycle), max(node_cycle))
                options = parallel.get(key, [])
                for i in range(len(options)):
                    for j in range(i + 1, len(options)):
                        candidate = [options[i], options[j]]
                        signature = frozenset(candidate)
                        if signature not in seen:
                            seen.add(signature)
                            cycles.append(candidate)
                continue

            choices: list[list[int]] = []
            for index in range(len(node_cycle)):
                a = node_cycle[index]
                b = node_cycle[(index + 1) % len(node_cycle)]
                options = parallel.get((min(a, b), max(a, b)), [])
                if not options:
                    choices = []
                    break
                choices.append(options)
            if not choices:
                continue

            # Bound the parallel-edge expansion so one heavily-parallel cycle
            # cannot consume the whole candidate budget on its own.
            total = 1
            for option in choices:
                total *= len(option)
            if total > max_candidates:
                choices = [[option[0]] for option in choices]

            for combination in itertools.product(*choices):
                signature = frozenset(combination)
                if len(signature) != len(combination) or signature in seen:
                    continue
                seen.add(signature)
                cycles.append(list(combination))
                if len(cycles) >= max_candidates:
                    cap_hit = True
                    break
    except Exception:
        return cycles, cap_hit, budget_hit

    return cycles, cap_hit, budget_hit


def _ordered_points(graph: SilhouetteGraph, segment_ids: list[int]) -> tuple[Vec3, ...]:
    """
    Concatenate segment point lists head-to-tail, flipping where needed.

    Points come from the segments themselves — which came from OCC — so the
    resulting polyline is on the B-Rep by construction (gate H0).
    """
    if not segment_ids:
        return ()

    remaining = list(segment_ids)
    first = graph.segments_by_id[remaining.pop(0)]
    points: list[Vec3] = list(first.points)

    while remaining:
        tail = points[-1]
        best_index = None
        best_flip = False
        best_distance = float("inf")
        for index, segment_id in enumerate(remaining):
            segment = graph.segments_by_id[segment_id]
            head_distance = math.dist(tail, segment.start)
            tail_distance = math.dist(tail, segment.end)
            if head_distance < best_distance:
                best_index, best_flip, best_distance = index, False, head_distance
            if tail_distance < best_distance:
                best_index, best_flip, best_distance = index, True, tail_distance
        if best_index is None:
            break
        segment = graph.segments_by_id[remaining.pop(best_index)]
        ordered = tuple(reversed(segment.points)) if best_flip else segment.points
        points.extend(ordered[1:] if math.dist(points[-1], ordered[0]) < 1e-9 else ordered)

    return tuple(points)


def extract_loops(
    graph: SilhouetteGraph,
    stats: ReductionStats,
    *,
    max_candidates: int,
    mu_max_for_johnson: int = 12,
    time_budget_s: float = 5.0,
    strategy: str = "basis",
) -> tuple[list[tuple[list[int], tuple[Vec3, ...]]], str, bool]:
    """
    Candidate loops from the reduced graph.

    Returns ``(loops, strategy, cap_hit)`` where each loop is
    ``(ordered_segment_ids, ordered_points)``.
    """
    if not graph.segment_nodes:
        return [], "none", False

    components = _components(graph)
    if stats.branch_node_count == 0:
        loops: list[tuple[list[int], tuple[Vec3, ...]]] = []
        for component in components:
            # A lone self-loop node IS the cycle (a hole rim, a cylinder rim).
            if len(component) == 1:
                incident = {s for _, s in graph.adjacency.get(component[0], ())}
                for segment_id in sorted(incident):
                    loops.append(([segment_id], graph.segments_by_id[segment_id].points))
                continue
            ordered = _walk_cycle(graph, component)
            if ordered:
                loops.append((ordered, _ordered_points(graph, ordered)))
        if loops:
            return loops[:max_candidates], "single_cycle", len(loops) > max_candidates

    # Branch nodes remain. P3a's corpus measurement (77.3% of parts in
    # 2 <= mu <= 12) justified bounded Johnson; beam search stays unwritten
    # because only 4.5% exceed 12. See `_johnson_cycles`.
    if (
        strategy == "johnson"
        and _NX_AVAILABLE
        and stats.cyclomatic_number <= mu_max_for_johnson
    ):
        cycles, cap_hit, budget_hit = _johnson_cycles(
            graph, max_candidates=max_candidates, time_budget_s=time_budget_s
        )
        if cycles:
            loops = [(c, _ordered_points(graph, c)) for c in cycles if c]
            loops.sort(key=lambda item: (-len(item[0]), tuple(sorted(item[0]))))
            return loops[:max_candidates], "johnson", cap_hit or budget_hit

    cycles = _fundamental_cycles(graph)
    loops = [(c, _ordered_points(graph, c)) for c in cycles if c]
    # Deterministic order: longest first, then by segment ids (plan §8.3).
    loops.sort(key=lambda item: (-len(item[0]), tuple(sorted(item[0]))))
    return loops[:max_candidates], "cycle_basis", len(loops) > max_candidates
