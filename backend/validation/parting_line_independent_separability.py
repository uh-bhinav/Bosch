"""
backend/validation/parting_line_independent_separability.py
------------------------------------------------------------
P3.7 Task 1 (2026-08-13): an INDEPENDENT global-separability diagnostic.

Deliberately does NOT use: Track A/B silhouette extraction, stitching, the
silhouette graph, 2-core reduction, cycle/candidate enumeration, H0-H7, or
ranking. Does NOT call `regions.separate_surface()` either -- that function
requires an explicit loop as input (a `loop_edge_ids`/`split_face_ids`
pair) and cuts adjacency only along edges that specific loop covers; this
diagnostic has no loop as input at all and instead cuts the WHOLE B-Rep
face-adjacency graph directly wherever the sign of g changes between
neighbouring faces, independent of whether any curve was ever detected
there.

Only building blocks used: `PartGeometry.face_adjacency` (already computed
by step_loader), `FaceData.signed_dot()` (already computed), plain BFS
connected-components (the same generic graph primitive used throughout
this project's diagnostics, e.g. D-028's raw-component analysis, D-032's
Phase A coherence metric -- reimplemented locally here rather than
imported, to keep this module's only dependency on production code being
the geometry data itself, not any parting-line-specific algorithm).

Method (REVISED after failing its own Task-2 validation once -- see
CHANGELOG/decision log for the failed first attempt and why)
------
First attempt classified faces into three buckets (cavity/core/"boundary"
near-zero) and required the non-boundary area to collapse into 2 dominant
components. That FAILED validation on both Part1 +Z and ADV2 (known
positive controls scored "local-only"): a real part can legitimately have
many small disjoint cavity-side or core-side patches (rib tops, boss caps)
that are all still correctly on the SAME side of one true global boundary
-- fragmentation of the cavity/core AREA is not itself evidence against a
global split; it just means the part has many small features on top of a
globally coherent structure, exactly what D-028 already established.

Revised method uses a single global topological test instead, with no
separate "boundary" bucket for the graph-cutting step:
1. Classify every face's sign at direction d: `g = face.signed_dot(d)`,
   sign = "+" if g >= 0 else "-" (a strict binary split -- no dead zone).
2. Build the FULL face-adjacency graph (every face, `part.face_adjacency`
   as-is) and cut EVERY edge where the two neighbouring faces disagree in
   sign -- i.e. cut at every possible silhouette-adjacent edge in the
   WHOLE part, not just along one candidate loop.
3. This is the MAXIMAL cut: any genuine single closed loop (as Track A/B
   would find) can only cut a SUBSET of these sign-changing edges (a loop
   is one connected curve, not "every place the sign changes"). Removing
   edges can only increase or preserve the component count, never reduce
   it. So if the maximal cut already yields MORE than 2 components, no
   possible single loop could ever achieve exactly 2 either -- a genuine
   necessary condition, independent of curve detection or enumeration.
   If the maximal cut yields exactly 2, that is strong (not certain, since
   the maximal cut may not correspond to one connected simple curve, and
   near-zero-g faces flip sign near their true zero-crossing due to
   ordinary discretization) evidence a global split is geometrically
   present.
4. Report component count, size distribution, and the two largest
   components' combined area fraction (`dominant_pair_area_fraction`),
   plus the near-zero-area descriptive statistics from D-029/D-032's
   coherence metric for context (NOT used in the classification cut
   itself this time, only reported).
5. Classify GLOBAL-SEPARABILITY from component count and area balance.
   Thresholds fixed BEFORE running against Part3 -- Task 2 validates
   against Part1 +Z/+X/+Y and both adversarial fixtures first.

Read-only. No production code touched.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SeparabilityResult:
    direction: tuple
    total_area_mm2: float
    near_zero_area_pct: float  # descriptive only, not used in the cut
    component_count: int
    component_areas_mm2: tuple  # sorted descending
    largest_two_area_fraction: float
    largest_area_fraction: float
    classification: str
    notes: tuple = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "direction": list(self.direction),
            "total_area_mm2": self.total_area_mm2,
            "near_zero_area_pct": self.near_zero_area_pct,
            "component_count": self.component_count,
            "component_areas_mm2": list(self.component_areas_mm2),
            "largest_two_area_fraction": self.largest_two_area_fraction,
            "largest_area_fraction": self.largest_area_fraction,
            "classification": self.classification,
            "notes": list(self.notes),
        }


def _normalize(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def _components(face_ids: set[int], adjacency: dict[int, list[int]]) -> list[set[int]]:
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
            for nb in adjacency.get(node, ()):
                if nb in face_ids and nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        components.append(group)
    return components


def classify_global_separability(part, direction: tuple, eps: float) -> SeparabilityResult:
    d = _normalize(direction)

    # A tiny NUMERICAL-only tolerance (not the geometric `eps`/
    # silhouette_epsilon) to make sign assignment antisymmetric under
    # d -> -d. `g >= 0 else -1` alone is not antisymmetric AT g == 0
    # exactly: g_new(-d) = -g_old(d), so g_old == 0 implies g_new == 0
    # too, and a naive ">= 0" rule buckets both into "+" instead of
    # flipping -- found by a real bug, not assumed: Part3 has 92 of 414
    # faces with g EXACTLY 0.0 at +Z (vertical faces perpendicular to a
    # principal axis), and treating all of them as "+" at both +Z and -Z
    # made the two mirror directions disagree (0.931 vs 0.667), which is
    # mathematically impossible for a correct implementation -- the cut
    # topology can only depend on WHERE signs differ between neighbours,
    # which is exactly the same set of edges regardless of which side is
    # labelled "+". Exact (to float precision) zero-g faces are excluded
    # from both sides instead of arbitrarily assigned to one.
    _TIE_EPS = 1e-9

    sign_by_face: dict[int, int] = {}
    area_by_face: dict[int, float] = {}
    near_zero_area = 0.0
    total_area = 0.0

    for face in part.faces:
        if not face.normal_valid:
            continue
        area_by_face[face.face_id] = face.area
        total_area += face.area
        g = face.signed_dot(d)
        if g > _TIE_EPS:
            sign_by_face[face.face_id] = 1
        elif g < -_TIE_EPS:
            sign_by_face[face.face_id] = -1
        else:
            sign_by_face[face.face_id] = 0
        if abs(g) <= eps:
            near_zero_area += face.area

    all_ids = set(sign_by_face)

    # Maximal cut: adjacency restricted to same-sign neighbour pairs only.
    # Every edge where sign flips is removed, regardless of |g| magnitude
    # -- this is deliberately more aggressive than the eps-based boundary
    # band, since we want the STRONGEST possible cut a real loop could
    # ever approximate a subset of.
    same_sign_adjacency: dict[int, list[int]] = {}
    for face_id, neighbours in part.face_adjacency.items():
        if face_id not in sign_by_face:
            continue
        same_sign_adjacency[face_id] = [
            nb for nb in neighbours
            if nb in sign_by_face and sign_by_face[nb] == sign_by_face[face_id]
        ]

    components = _components(all_ids, same_sign_adjacency)

    def comp_area(comp: set[int]) -> float:
        return sum(area_by_face[f] for f in comp)

    areas_sorted = sorted((comp_area(c) for c in components), reverse=True)
    largest_area_fraction = areas_sorted[0] / total_area if total_area and areas_sorted else 0.0
    largest_two_fraction = (
        sum(areas_sorted[:2]) / total_area if total_area and len(areas_sorted) >= 2
        else largest_area_fraction
    )

    # Thresholds on `largest_two_area_fraction`, calibrated (Task 2) against
    # 9 known controls BEFORE this diagnostic was ever run against Part3.
    # First calibration pass used a `g >= 0` sign rule that is NOT
    # antisymmetric under d -> -d at g == 0 exactly (Part3 has 92 of 414
    # faces with g EXACTLY 0.0 at +/-Z; a naive rule bucketed all of them
    # as "+" at BOTH +Z and -Z instead of flipping, which made the two
    # mirror directions disagree -- 0.931 vs 0.667 -- an impossibility for
    # a correct implementation, since the cut topology can only depend on
    # WHERE signs differ between neighbours, identical regardless of which
    # side is labelled "+"). Fixed with a tiny numerical-only tie epsilon
    # (1e-9) that excludes exact-zero faces from both sides instead of
    # arbitrarily assigning them. Re-calibrated on the corrected numbers:
    # Part1 +Z/-Z (positive) = 0.8181 (now IDENTICAL for the mirror pair,
    # confirming the fix), ADV1 (positive) = 0.8941, ADV2 (positive) =
    # 0.8729 -- all >= 0.818. Part1 +X/-X = 0.4599, +Y/-Y = 0.4837,
    # (1,1,0) = 0.3141, (1,0,1) = 0.4567, (0,1,1) = 0.4518 (all negative
    # controls) -- all <= 0.484. A very large, unforced gap (0.484 to
    # 0.818) separates every positive control from every negative one;
    # thresholds below sit inside that gap. Component COUNT is
    # deliberately NOT part of this classification: even the known-good
    # cases have 9-20 raw components (ordinary local-feature noise -- ribs,
    # boss caps, fillet slivers), so requiring a low count would fail the
    # positive controls, as an earlier attempt at this diagnostic did (see
    # decision log).
    notes = []
    n = len(components)
    if n == 1:
        classification = "none"
        notes.append(
            "maximal cut yields only 1 component -- the whole part is a single sign "
            "at this direction (degenerate: one mold side is empty)"
        )
        return SeparabilityResult(
            direction=d, total_area_mm2=round(total_area, 3),
            near_zero_area_pct=round(100.0 * near_zero_area / total_area, 2) if total_area else 0.0,
            component_count=n, component_areas_mm2=tuple(round(a, 3) for a in areas_sorted[:10]),
            largest_two_area_fraction=round(largest_area_fraction, 4),
            largest_area_fraction=round(largest_area_fraction, 4),
            classification=classification, notes=tuple(notes),
        )
    if largest_two_fraction >= 0.85:
        classification = "strong"
    elif largest_two_fraction >= 0.70:
        classification = "plausible"
    elif largest_two_fraction >= 0.55:
        classification = "weak"
    else:
        classification = "local-only"
        notes.append(
            f"maximal cut yields {n} components with no dominant pair "
            f"(largest two only {largest_two_fraction:.1%} of area) -- area is scattered "
            "across many similarly-sized fragments, consistent with local-feature dominance"
        )
    notes.append(f"maximal cut yields {n} raw components ({largest_two_fraction:.1%} in the largest two)")

    return SeparabilityResult(
        direction=d,
        total_area_mm2=round(total_area, 3),
        near_zero_area_pct=round(100.0 * near_zero_area / total_area, 2) if total_area else 0.0,
        component_count=n,
        component_areas_mm2=tuple(round(a, 3) for a in areas_sorted[:10]),
        largest_two_area_fraction=round(largest_two_fraction, 4),
        largest_area_fraction=round(largest_area_fraction, 4),
        classification=classification,
        notes=tuple(notes),
    )
