# Decisions & Algorithms — Running Log

> **Purpose.** A single place recording every non-obvious decision and every
> algorithm implemented for the parting-line / core-cavity rebuild — **with the
> mathematics, and with the reason.**
>
> **Append-only.** Newest entry at the top of each section. Never rewrite an
> earlier entry; if a decision is reversed, add a new entry that supersedes it
> and link both ways.
>
> **Companions:** `docs/PARTING_LINE_CORE_CAVITY_AUDIT.md` (what was wrong),
> `docs/PARTING_LINE_ALGORITHM_PLAN.md` (what we intend to build).
> This file records **what we actually did, and why.**

---

## Entry format

```
### D-<n> — <title>            [<phase>] <YYYY-MM-DD>
**Decision.**  one sentence
**Mathematics.**  the formula / derivation, if any
**Why.**  the reason, with evidence
**Alternatives rejected.**  and why
**Where.**  file:line
```

---

# Phase P3.11 — Independent S2 separation test, self-corrected mid-investigation, confirms H3 correctness on all tested candidates

## D-037 — Fresh independent separation test (own sign computation, own adjacency, own components) validated on Part1, found and FIXED a bug in itself (not production) via a suspected discrepancy, then confirmed H3 agrees on all 5 requested Part3 directions; basis-cycle-pair search for an alternative single-loop S2 candidate came back negative ⭐⭐⭐⭐

**[P3.11] 2026-08-13.** No production code changed. New: `backend/
validation/parting_line_independent_separation_test.py`.

**Step 1/2 — independent test built and validated.** Deliberately does not
import `regions.py` at all: own sign(g) computation via direct
`GeomLProp_SLProps` calls (not `_g_at_edge_on_face`), own face-adjacency
construction from raw `part.edge_to_faces`/`face_to_edges`, own BFS
component search, own interval-complement arithmetic. Classification
S0 (doesn't separate) / S1 (separates but one side is a <5%-area local
sliver) / S2 (separates the main body meaningfully) / S3 (separates but
orientation signs don't cleanly oppose). **Mandatory Part1 +Z gate**:
correctly classifies Part1's known winning candidate as S2
(`component_count=2`, smaller region 13.4% of area, clean opposite-sign
orientation -0.53/+0.50) — matches production's own H3 exactly. Proceeded
to Part3 only after this passed.

**A self-caught bug, reported in full rather than presented as a clean
result.** Applying the test to the 5 requested directions
(`grid(az15)`, `grid(az165)`, `grid(az330)`, `+X`, `+Y`) initially found
what looked like a genuine discrepancy: `+Y`'s largest single-loop
candidate scored production `h3_region_count=3` but the independent test
said `component_count=2, S2` — a potential CASE-E smoking gun. Traced in
full before accepting it (per the standing "no manufactured conclusions"
discipline): the discrepancy traced to `_g_at_edge_on_face` appearing to
return `None` for face 37 on 3 edges -- BUT this was found to be an
artifact of the DIAGNOSTIC SCRIPT's own incorrect reconstruction of
production's `free_parameter` argument (a bug in the investigation, not
in `regions.py` -- confirmed by calling `_g_at_edge_on_face` exactly as
production does and getting clean, non-None results every time). The
REAL cause: production's `separate_surface` unconditionally creates BOTH
`(face_id, +1)` and `(face_id, -1)` graph nodes for every split face
(`regions.py` lines 271-272), even when one side ends up with zero
adjacency edges -- correctly reporting that side as its own isolated
component. The independent test's first version only added nodes that
appeared via some edge relation, silently dropping genuinely-isolated
split-face halves. **Fixed to match production's node-construction
discipline exactly** (matching, not routing around, since this is the
more complete and correct behavior). Re-validated: Part1 +Z gate still
passes (S2, unaffected by the fix). Re-ran all 5 Part3 directions:
**100% agreement with production on every one** (`grid(az15)`,
`grid(az165)`, `grid(az330)`: both say `region_count=1`/S0;
`+X`, `+Y`: both say `region_count=3`/S0).

**No CASE B or CASE E evidence found for these 5 directions' largest
candidates.** H3's rejections are independently confirmed correct by a
freshly, differently-implemented test.

**Step 4 — search for an alternative single-loop S2 candidate at
`grid(az15)`.** Computed the raw graph's fundamental cycle basis (62
cycles via `nx.cycle_basis`, a structured subset of the cycle space, not
blind enumeration -- justified given µ~98 makes exhaustive Johnson
enumeration intractable, consistent with D-036's same finding). Tested
candidate 1 (the S0-confirmed 120-segment/73%-bbox loop) XOR'd against
each of the 62 basis cycles via the independent test. **2 of 62
combinations scored S2** (`basis[57]`: 5.65% smaller region; `basis[60]`:
19.71% smaller region -- a substantial-looking split). **Both traced
further and found NOT to be genuine single continuous loops**: attempting
to chain `candidate1 XOR basis[60]`'s 128 segments end-to-end by matching
endpoints succeeded for only 120 of 128 -- because `basis[60]` is its own
independently closed 8-segment local loop with ZERO segment overlap with
candidate 1, so the "XOR" is really just a disjoint UNION of two separate
closed curves, not a modification of one curve. Same "loop_union"
structural pattern already established and rejected throughout
D-027 onward (e.g. candidate 43, and D-036's 126-segment/43.9mm-gap
candidate) -- would fail H1 (closure/single-curve) before ever reaching
H3. **No genuine single-loop S2 alternative found** via this search.

**Step 3 — bypass geometry, characterized.** The 9-hop bypass faces
(`329, 330, 15, 1, 372, 364, 370`, plus `0`) are `Cylinder`/`Torus`/
`BSpline`/`Plane` types with areas 0.81-63.10mm2 (against ~9000mm2 total
part area) -- the same small local boss/fillet feature scale already
characterized in D-028/D-030/D-034, not a large secondary structure. The
bypass is a real, small, physically local connectivity route.

**Step 6 classification: CASE A/C, not B or E, for every candidate
examined this entry.** No S2 single-loop candidate was found at any of
the 5 directly-tested directions or via the basis-pair search at
`grid(az15)`. H3's region-count results are independently confirmed
correct wherever tested.

**No production code changed.**

---

# Phase P3.10 — Systematic spherical search finds new territory (the equatorial band) with genuine large candidates; still CASE C, not CASE D

## D-036 — 374-direction spherical grid search (15deg resolution) finds the entire z=0 equatorial band scores far above any previously-tested Part3 direction; deep verification confirms CASE C (large genuine loops exist, production builds them, H3 correctly rejects them via short bypass paths) — no Part3 positive control found yet ⭐⭐⭐

**[P3.10] 2026-08-13.** No production code changed. New:
`backend/validation/parting_line_zero_level_network.py` (cheap
per-direction pre-filter), `backend/validation/
parting_line_spherical_search.py` (374-direction grid), `backend/
validation/parting_line_deep_verify.py` (exhaustive/cycle-basis
characterization + full production run on shortlisted directions).

**Cheap pre-filter, calibrated on Part1 first.** Metric: raw-graph
`largest_component_fraction` (D-035's "how concentrated is the
silhouette-relevant geometry" signal) + `non_trivial_mu` (cyclomatic
number minus trivial self-loops). On Part1's 12 canonical directions,
+Z/-Z rank #1 (0.899) distinctly above the runner-up (0.763) -- but the
metric does NOT cleanly binary-separate +Z from the failing directions
(all 12 have substantial raw cyclic content, 43-125 non-trivial mu,
because what actually distinguishes +Z is that ITS candidates pass H3,
not that cycles exist at all). Documented explicitly as a ranking signal,
not a binary classifier, before touching Part3 -- consistent with D-029's
prior finding that finer distinctions require H3-level testing.

**Search space: 374 directions** = 266-point grid (elevation every 15deg,
azimuth every 15deg, poles collapsed -- resolution justified by runtime:
~1-2s/direction cheap-diagnostic cost, ~180s total, a 10deg grid would be
~4x for marginal extra coverage) + the 12 canonical + 96 previously-swept
directions (re-scored with this same metric for a consistent basis, not
re-deriving their already-recorded H0-H7 results).

**Result: the entire z=0 equatorial band (all `elevation=90` grid points,
covering the full 360deg azimuth ring perpendicular to Z) scores far
above every other tested region** -- `largest_component_fraction`
0.87-0.90, `non_trivial_mu` 90-108, for EVERY azimuth in that ring, not
just the already-known +Y/-Y. Top result (`grid(elev90,az15)`,
frac=0.904) exceeds even Part1 +Z's own 0.899. This is genuinely new
territory: none of it coincides with the previously-tested 108 directions
(principal axes, canonical diagonals, or their +/-15deg neighbourhoods).
**Caveat, measured not assumed**: `+X` (already known from D-026 to
fail, 0 valid, 282 H3 failures) ALSO sits in this same equatorial band
and scores similarly (0.870, mu=107) -- confirming, again, that this
cheap metric is necessary-looking but not sufficient, exactly as the
Part1 calibration predicted.

**Deep verification, 10 diverse directions across the equatorial band**
(exhaustive Johnson cycle search where mu<=20 per component, `nx.
cycle_basis` where larger -- an explicit, honest downgrade matching
production's own `mu_max_for_johnson=12` gating, not silent
incompleteness) **plus the full unmodified production pipeline on each.**
All 10: independent search finds CASE 3 (multiple genuine global-looking
closed cycles, bbox ratio up to 0.73-0.92, up to 100+ faces touched).
Production DOES construct large candidates from this same geometry --
277-325 raw candidates per direction (an order of magnitude more than the
9-30 typically seen at the previously-tested bore/torus-dominated
directions) -- but **all 10 directions: 0 valid candidates**, H3
rejecting the large majority (247-287) and H4 a smaller remainder
(13-52), H0 negligible (0-3).

**Traced the two largest candidates found anywhere in this whole
investigation, at `grid(elev90,az15)`:**
- Candidate 120 (126 segments, 91.7% bbox): `discovered_by="loop_union"`,
  `loop_count=2`, a 43.9mm point-discontinuity at its stated "closure"
  point -- confirmed to be TWO separate sub-loops concatenated by
  `_subset_unions`, not one continuous curve, inheriting non-separation
  from its parts. Same structural pattern as D-027/D-028's candidate 43.
- **Candidate 1 (120 segments, 73.0% bbox, closure gap EXACTLY 0.0000mm --
  a genuine single closed loop, NOT a union)**: touches 60 distinct
  B-Rep edges and 35 Track-B split faces -- the largest true single loop
  found in the entire P3.x investigation. Still `H3, region_count=1`.
  BFS-traced the exact bypass (same method as D-027/D-034): a short
  **9-hop** path from `(face 0, +1)` to `(face 0, -1)` through faces
  `329, 330, 15, 1, 372, 364, 370` -- a real, short, alternate
  connectivity route the loop does not cross.

**What this establishes, precisely.** Part3's B-Rep has enough
cross-connectivity at these directions that even a genuine, properly
closed, 73%-bbox single loop leaves a short bypass. This is the SAME
"uncovered-edge/adjacency bypass" mechanism established in D-027, D-028,
and D-034 -- now confirmed at a scale (single loops covering ~3/4 of the
part) far beyond the small torus/bore cases previously examined. It is
not a new failure mode; it generalizes the existing one to much larger
candidates than any tested before.

**Classification: CASE C** ("production builds candidates, H3/H4 reject
them -- investigate gate correctness") **for all 10 deep-verified
directions.** H3's rejections traced above are mathematically justified
given the input (a real, short bypass exists) -- consistent with every
prior H3 audit in this investigation (D-028, D-030, D-031, D-034). Not
CASE D: zero valid candidates found. Not CASE B: production does
construct large candidates from the same geometry the independent search
identifies, so nothing is being lost between the independent network and
production's own representation.

**Still no Part3 positive control.** The equatorial band is a
substantially stronger diagnostic signal than anything found in the
prior 108-direction search, and materially expands the tested space, but
does not itself resolve to a valid parting line. 364 of 374 grid+existing
directions remain unexamined at the deep-verification level (only the
top 10 by the cheap pre-filter were deep-verified, per the task's "top
5-10" scope) -- open for further work, not concluded negative.

**No production code changed.**

---

# Phase P3.9 — Independent, candidate-generation-agnostic search for a global zero-level loop: CASE 1 confirmed

## D-035 — Exhaustive, method-independent cycle search (not cycle_basis, not Johnson, not H3/H4) finds NO global closed loop anywhere in Part3's CASE-A geometry — the face-sign partition is real, but no continuous separating curve realizes it ⭐⭐⭐

**[P3.9] 2026-08-13.** Direct answer to the question D-034 left open:
does a real global parting-line loop exist ANYWHERE in the geometry for
the 11 CASE-A directions, not just near the bore already traced? No
production code changed.

**Method.** Reused Track A/B segment detection and `build_graph` (graph
construction, not candidate generation, per the explicit instruction) to
get the RAW (pre-2-core) graph. Then, independently of `extract_loops`
(cycle_basis/Johnson) and H3/H4, searched for ALL cyclic structure via:
(1) direct self-loop enumeration, (2) direct parallel-edge (same node-pair,
2+ segments) enumeration -- both missed by a naive `networkx.simple_cycles`
call on a collapsed simple graph, a real methodological trap caught and
fixed mid-investigation -- and (3) `networkx.simple_cycles` on the
remaining simple-edge graph for any longer (3+ node) cycles.

**Result for the strongest CASE-A direction
(`(0,1,-1)+theta5+phi45`, frac=0.793).** Raw graph: 327 nodes, 266
segments, 64 connected components, largest only 21 nodes (6.4%). Total
cyclomatic number across the ENTIRE graph: **3** -- and all 3 are trivial
single-segment self-loops (segments 45, 46, 54). Zero parallel-edge
2-cycles. Zero longer simple cycles anywhere. **This exactly reconciles
with production's own reported `candidate_count=7`**: 3 individual
self-loops + `_subset_unions`'s combinatorial pairs/triple (C(3,2)+C(3,3)
= 3+1 = 4) = 7 -- independent confirmation that candidate generation is
NOT missing anything; it already found the complete cycle space this
independent search also found, by a different method.

**Repeated on 3 more CASE-A directions, same signature every time**:
`theta5+phi90` (75 components, largest 5.7%, mu=2, 1 self-loop, 1 longer
cycle), `theta10+phi225` (70 components, largest 7.7%, mu=3, 3
self-loops, 0 longer cycles), `theta15+phi225` (71 components, largest
6.0%, mu=4, 4 self-loops, 0 longer cycles). Consistently: dozens of
components, none dominant, minimal-to-trivial cyclic content.

**Part1 +Z golden control, for contrast (structural statistics only --
full `simple_cycles` enumeration on this graph is combinatorially
infeasible, mu=113, exactly why production gates Johnson behind
`mu_max_for_johnson=12`; killed after confirming it would not finish in
reasonable time).** Raw graph: 356 nodes, 460 segments, **9** components,
**largest holds 320 of 356 nodes -- 90%**. Total cyclomatic number in
that one dominant component: **113** (exactly matching D-026's
independently-recorded `candidate_count=113` for Part1 +Z -- a strong
cross-check the two measurements agree). 4 self-loops, 4 parallel-edge
pairs, elsewhere in the small remainder.

**The contrast is the finding.** Part1 +Z: one graph, 90% of the part's
silhouette-relevant geometry, rich cyclic structure (mu=113) to search
for the true loop within. Part3's CASE-A directions: the silhouette-
relevant geometry itself is fragmented into 60-75 disconnected pieces,
none dominant, essentially no cyclic content beyond degenerate self-loops.

**Answering Step 5/6's required distinction precisely.** D-033's
independent separability diagnostic found the face-SIGN distribution
resolves into two dominant AREA-weighted regions (a real, geometrically
meaningful partition). D-034 and this entry establish that finding does
NOT correspond to an actual continuous closed zero-level curve realizing
that partition -- exactly the distinction Step 6 required not to
conflate. The two dominant regions are real; the boundary between them is
not one connected curve, it is scattered disconnected fragments (partial
rim arcs, rulings, isolated self-loops) with genuine same-sign gaps
between them that carry no parting-relevant content at all (already
proven face-by-face in D-034: neighbouring cone faces are robustly,
unambiguously signed, not degenerate).

**Classification: CASE 1 — "No physically valid global zero-level loop
exists for this direction."** Not CASE 2 (production doesn't lose a real
loop -- there is no loop to lose, confirmed by an independent,
differently-implemented search that agrees exactly with production's own
candidate count). Not CASE 3 (nothing survives to H3/H4 for them to
mis-validate -- their rejections, already traced in D-034, are of trivial
self-loops and their unions, correctly rejected).

**What this does NOT prove.** Confirmed for 4 of the 11 CASE-A
directions (all in the same tight angular neighbourhood, all touching the
same bore feature) -- not independently re-verified for the remaining 7,
though the consistent signature across the 4 checked, combined with all
11 sharing the same structural cause (D-033), makes divergence unlikely.
Does not address whether OTHER, entirely untested regions of Part3's
practical direction space (beyond the 108 directions and their close
neighbourhoods already covered) might behave differently.

**No production code changed.**

---

# Phase P3.8 — Forensic trace of the CASE-A bore candidate: no code defect found; F3 control disproves the leading hypothesis

## D-034 — Full read-only forensic trace of Part3's bore CASE-A candidate: edge 112 is a correctly-skipped seam, the rim's partial coverage is geometrically correct (cone faces are robustly non-zero-draft, unlike F3's degenerate caps), and no single-stage defect is demonstrated ⭐⭐⭐

**[P3.8] 2026-08-13.** Direct continuation of D-033's CASE-A finding.
Read-only forensic trace per explicit instruction; no production code
changed.

**Edge topology of face 35 (the bore), established first.** 4 edges:
`111` (full 2π circle, faces `[35,320]` — bottom rim), `112` (v-range
`[-39,-1]`, span 38mm exactly matching the bore length, **only 1 adjacent
face `[35]`** — a genuine seam, not a physical boundary), `113`+`114`
(each π, faces `[35,319]` — top rim, split in two by the source CAD
topology). Answers question M directly: edge 112 "disappears" at Track
A's own edge classification, correctly and deliberately — confirmed via
`track_a.skipped[112] == "seam edge (parameterisation artefact, not a
physical boundary)"`. Not a bug: both "sides" of edge 112 are face 35
itself (the cylinder's own parametrization wraparound).

**Questions A-D, precisely answered.** Track A's raw output (not
stitching, not anything downstream) already shows PARTIAL coverage:
edge 111 → 2 segments, `t=[0,3.049]` and `[6.190,6.283]` (gap
`[3.049,6.190]`, ~π radians); edge 113 → 1 segment `[0,0.093]`; edge 114 →
1 segment `[3.235,6.283]`. Combined across 113+114 (which together
parametrize the full top-rim circle), the covered range is
`[0,0.093] ∪ [3.235,6.283]` — leaving `[0.093,3.235]` uncovered, the same
~π-radian gap pattern as the bottom rim. Track B independently confirmed:
exactly 2 straight "ruling" segments on face 35's cylindrical surface
(the same shape as fixture F3), connecting the covered portions of the
two rims.

**Question E/F/G/H (periodic seam, interval splitting, straddle-test
drops) — none apply.** The gap is not a seam-normalization artefact
(edge 112, the actual seam, is handled separately and correctly skipped);
it is not a dropped interval (verified: nothing in the stitched pool
touches this gap region on any of 111/113/114/320/319/321 — an
exhaustive search of every segment touching the bore's local neighbourhood
found nothing beyond what Track A/B already reported). It is not a
straddle-test failure: **the gap exists because face 35 (cylinder,
varying sign) and its neighbours 320/319 (cone, checked: g=+0.5725 and
-0.5725 respectively — robustly, unambiguously signed, NOT zero-draft)
genuinely agree in sign over roughly half the rim's circumference.**
Track A correctly emits nothing there because there is nothing to emit —
no sign change occurs.

**Question I/J/K — stitching and graph construction preserve everything
found.** Hand-chained the 6 relevant segments (top rim arc → tiny top
sliver → ruling down → bottom rim arc → tiny bottom sliver → ruling up)
by matching endpoints; they form a properly-ordered polyline with a
closure gap of 0.000993mm (a SEPARATE, genuinely real ~14x weld-tolerance
shortfall vs. the 6.8e-5mm `_weld_tolerance`, already flagged in D-033).
Nothing is lost in stitching or graph construction — verified directly,
not inferred.

**Question L — even force-closed, `separate_surface` still reports
`region_count=1`.** Root cause, precisely: the UNCOVERED portion of the
rim (the genuine same-sign arc) remains a live, uncut face-adjacency
connection between face 35 and faces 320/319 in `separate_surface`'s
model — exactly the same "uncovered-edge bypass" mechanism already
established in D-027/D-028 for the torus/boss features (there, edge 117's
uncovered half; here, edges 111/113/114's uncovered halves). **This is
not a new failure mode — it is the same mechanism, now confirmed on a
major structural feature (the 1432.57mm2 bore) instead of a small local
one**, which is itself informative (broadens D-028's finding) but is not
evidence of a new code defect.

**F3 control (question: does F3 reveal a structural difference implying a
fixable defect?) — NO, and this is the decisive negative result.**
F3's actual winning candidate (traced directly, not assumed) DOES achieve
full rim coverage — but via a mechanism Part3's bore does not share: F3's
two end caps are **exactly** zero-draft at the tested direction
(`track_b_summary.degenerate_face_ids=[1,2]`, g≡0 identically, by design
per F3's own fixture manifest — this is F3's deliberately engineered
target case for degenerate zero-draft-band handling). Because one side of
F3's straddle test is identically zero everywhere, the straddle condition
`0 ∈ [g_a, g_b]` is trivially satisfied along the ENTIRE rim, and Track A
emits either `silhouette` (true crossings) or `tangential` (D-025's
grazing classification) for every point — full coverage by construction
of the test geometry. Part3's cone faces 320/319 are confirmed NOT
degenerate (g=+0.5725/-0.5725, unambiguous), so this mechanism does not
apply, and partial coverage on Part3's bore rim is the geometrically
CORRECT output, not a defect F3 would have caught.

**Second control — invariance across all 11 CASE-A directions.** All 11
independently touch face 35 (confirmed directly, not assumed). Not
individually re-traced segment-by-segment (would require ~11x the tracing
above for marginal additional evidence given the mechanism is already
pinned down structurally, not numerically), but the structural argument
(cone faces 320/319's sign, and the seam status of edge 112) does not
depend on the small angular perturbations between the 11 directions, so
the same explanation is expected to hold for all of them.

**Success-criterion statement, precisely, as required:** *"The complete
physically expected bore boundary is NOT lost at any single processing
stage due to a demonstrated code defect. Track A/B correctly and
completely capture every genuine sign-crossing near the bore. H3 rejects
the resulting (properly closed, hand-verified) loop because the
UNCOVERED rim arcs are a real, correct absence of silhouette content —
face 35 and its cone neighbours genuinely share sign there — and this
uncovered arc remains a valid bypass connection in the separating graph,
identical in kind to D-027/D-028's already-established mechanism. F3 does
not contradict this: F3's full coverage stems from a specifically
engineered degenerate (zero-draft) condition Part3's cone faces do not
share."*

**Answering the 6 post-root-cause requirements:** No production change is
proposed. Per the explicit instruction ("Do not modify production code.
Do not declare victory merely because a tolerance increase makes H3
pass"), and because no single-stage code defect was demonstrated (the
weld-tolerance gap is real but insufficient alone, already shown in
D-033; the coverage gap is geometrically correct, not a bug), items 13-14
(minimum fix, regression test) are deliberately NOT produced this entry —
producing them would require inventing a fix for something not shown to
be broken.

**Confidence level: high** that no code-level defect exists in Track A/B,
stitching, or graph construction for this specific feature/direction
cluster. **Lower confidence** on whether SOME OTHER, not-yet-traced part
of Part3's geometry could still provide the missing "other half" of the
separating boundary via a longer path (the D-027/D-028 "true global loop
may extend beyond the local feature" open question) — this remains
untested for the bore specifically, as it was for the torus features.

**No production code changed.**

---

# Phase P3.7 — Independent global-separability diagnostic finds CASE A: a real candidate-completeness limitation, not direction infeasibility, on Part3's main bore

## D-033 — Independent (non-cycle, non-H3/H4) B-Rep separability diagnostic built, validated on 11 known controls, and finds 11 CASE-A directions on Part3, all traced to the same feature (the main bore, face 35): geometry exists, Track A/B detect it, but the assembled candidate has incomplete edge coverage ⭐⭐⭐

**[P3.7] 2026-08-13.** Direct response to the explicit instruction not to
use the PL engine to answer both "is this direction feasible" and "does
the algorithm recover it." No production code changed. New:
`backend/validation/parting_line_independent_separability.py`.

**Task 1 — the diagnostic.** Does NOT use Track A/B, stitching, the
silhouette graph, 2-core, cycle enumeration, H0-H7, or `separate_surface`.
Only uses `part.face_adjacency` and `FaceData.signed_dot()` (both already
computed by step_loader). Method: classify every face's sign at direction
d, cut the FULL face-adjacency graph at every edge where neighbouring
faces disagree in sign (the maximal possible cut — any real single loop
can only cut a subset of these edges, so if the maximal cut already
exceeds 2 components, no loop could ever achieve exactly 2 either), and
classify by `largest_two_area_fraction` (how much total area the two
biggest resulting components capture).

**A real bug found and fixed during Task 1, before any Part3 result was
looked at.** First version used `sign = 1 if g >= 0 else -1`, not
antisymmetric at g == 0 exactly. Part3 has 92 of 414 faces with g EXACTLY
0.0 at ±Z; the naive rule bucketed all of them as "+" at BOTH +Z and -Z,
making the two mirror directions disagree (0.931 vs 0.667 — mathematically
impossible for a correct implementation, since the cut topology can only
depend on WHERE signs differ, identical regardless of which side is
labelled "+"). Fixed with a 1e-9 numerical-only tie epsilon (NOT the
geometric `silhouette_epsilon` — reusing that would reopen a different,
already-failed approach, see below) that excludes exact-zero faces from
both sides instead of arbitrarily assigning them. Verified: +Z and -Z now
agree exactly (0.8181 == 0.8181) on Part1.

**A second, more substantial redesign, also before touching Part3.** The
very first attempt at this diagnostic (a 3-bucket cavity/core/boundary
model requiring the NON-boundary area to collapse into 2 dominant
components) FAILED its own Task-2 validation: Part1 +Z and ADV2 (both
known-positive controls) scored "local-only." Root cause: real parts
legitimately have many small disjoint cavity-side or core-side patches
(rib tops, boss caps) that are all correctly on the SAME side of one true
global boundary — fragmenting the cavity/core AREA is not itself evidence
against a global split. Redesigned to the maximal-cut method described
above, which does not require low fragmentation, only that the fragments
resolve into two dominant groups by area.

**Task 2 — validation, 11 known controls, all correct (0 mismatches).**
Positive controls: Part1 +Z/-Z = 0.8181/0.8181 (exact mirror match), ADV1
= 0.8941, ADV2 = 0.8729. Negative controls: Part1 +X/-X = 0.4599, +Y/-Y =
0.4837, (1,1,0) = 0.3141, (1,0,1) = 0.4567, (0,1,1) = 0.4518. A large,
UNFORCED gap (0.484 to 0.818) separates every positive from every
negative control. Thresholds fixed inside that gap (strong >= 0.85,
plausible >= 0.70, weak >= 0.55, local-only below) BEFORE any Part3
direction was evaluated.

**Task 3/4 — applied to all 108 previously-tested Part3 directions (12
canonical + 96 swept).** 12 canonical: all CASE B (local-only/weak,
frac 0.346-0.670) — diagnostic agrees with the PL engine that no global
split exists at any of them. 96 swept: 47 local-only, 38 weak, **11
"plausible" (frac 0.775-0.793)**, 0 "strong", 0 CASE C. **All 11
"plausible" directions are CASE A**: independent diagnostic says a global
split is geometrically plausible, PL engine finds zero valid candidates.
All 11 cluster in one neighbourhood: `(0,1,-1)/(0,1,1) + theta{5,10,15} +
phi{45,90,135,225,270,315}` (a rotation of the earlier (0,1,-1) anchor).

**Traced per Task 6, one representative in full
(`(0,1,-1)+theta5+phi45`, d ~ (-0.062, 0.661, -0.748)).** The independent
diagnostic's two dominant components are (a) a 307-face core region
(most of the part) and (b) a 4-face region {35, 36, 320, 321} totaling
2399.81mm2 — face 35 is the part's MAIN CENTRAL BORE (`Cylinder`,
1432.57mm2, r=6mm), face 36 its main flat BASE (`Plane`, 753.98mm2) —
genuinely global, structurally significant features, not small local
bosses. This is qualitatively different from every candidate examined in
D-027 through D-032, all of which were small torus/boss pinches.

Track A/B correctly detected the necessary raw content: two Track-B
"rulings" on the bore's cylindrical face (the classic two-straight-line
cylinder-silhouette pattern, same shape as fixture F3), plus Track-A arcs
on the bore's rim edges. Hand-chaining the 6 relevant segments
(5, 3, 90, 0, 2, 91) by matching endpoints produces a properly ordered,
nearly-closed polyline — closure gap **0.000993mm**, against an H1
tolerance of 0.000681mm (fails by 1.46x). The actual weld tolerance used
by `build_graph` (`_weld_tolerance`, driven by `weld_tolerance_rel`) is
**6.8e-5mm — roughly 14x smaller** than this genuine cross-track gap
between Track A's and Track B's independently-computed representations of
the same physical corner point. This is a different, much tighter
parameter than `stitch_snap_tolerance_rel` (already addressed in D-022).

**However — tightening weld tolerance would NOT be sufficient by
itself.** Manually force-closing the loop and re-running `separate_surface`
still gives `region_count=1` (does not separate). Root cause: the
assembled 6-segment loop covers only 3 of face 35's 4 B-Rep edges
(111, 113, 114 — not 112), and even those are only PARTIALLY covered —
edge 111's covered interval is `[0, 3.05] + [6.19, 6.28]` out of the full
`[0, 6.28]`, leaving roughly half the bottom rim circle uncovered. This is
the SAME partial-edge-coverage / candidate-incompleteness mechanism
already established in D-027/D-028 for small torus features — now shown,
for the first time, to also apply to a major structural feature (the main
bore), not just small local bosses. This broadens D-028's conclusion
rather than contradicting it.

**Classification of this finding (Task 6's decision rule).** Two distinct,
separately real issues, correctly NOT conflated:
1. A genuine, small, well-evidenced weld-tolerance gap (H1-relevant,
   ~14x) — real, fixable, LOW risk (raising `weld_tolerance_rel` by a
   documented, evidence-derived amount), but insufficient alone.
2. A genuine, larger, NOT-yet-understood candidate-completeness gap: why
   does the loop-assembly process produce a partial-coverage candidate
   instead of a fully-edge-covering one for this bore feature? This is
   NOT yet root-caused to a specific line of code -- it is evidence a
   deeper defect exists (leaning hypothesis B for this specific feature),
   but per the explicit instruction, no production change is proposed
   until this second, larger gap is itself understood.

**This is the strongest evidence yet for hypothesis B (a demonstrated
candidate-generation/completeness limitation) found in the whole P3.x
investigation** — but it is deliberately NOT reported as a full CASE A
resolution, since the exact mechanism producing partial edge coverage has
not itself been traced to a specific stage yet. Recommended next step
(not started): trace WHY the candidate assembly stops at partial coverage
of edges 111/113/114 and omits 112 entirely -- likely in stitching or
in how the marching-squares/straddle-test results for a periodic edge get
split into intervals -- using the same read-only diagnostic methodology as
D-027/D-028, before proposing any fix.

**No production code changed.**

---

# Phase P3.6 — Direction calibration + 96-direction angular sweep: no Part3 positive control found

## D-032 — Part1 calibration finds a geometrically-explainable metric (near-zero region connectivity, not area); 96-direction fine sweep around Part3's 4 diagonal anchors finds zero valid candidates ⭐

**[P3.6] 2026-08-13.** Phase A/B/C/D/E of the direction-investigation
protocol. No production code changed. New: `backend/validation/
parting_line_direction_calibration.py`, `backend/validation/
parting_line_angular_sweep.py`.

**Phase A — Part1 calibration.** D-029 found near-zero-AREA-percentage is
anti-correlated with Part1's ground truth (+Z has the most, 71.7%, yet is
the only working direction). Tested a geometrically motivated alternative:
whether the near-zero-draft faces form ONE connected envelope, using
`part.face_adjacency` (already computed, no new engine) restricted to the
near-zero subset, same `silhouette_epsilon` the parting-line engine itself
uses.

Result: **`largest_component_area_fraction` = 0.988 at Part1 +Z/-Z** —
98.8% of all near-zero area sits in a single connected patch (the part's
side walls forming one coherent ring) — sharply distinct from every
failing Part1 direction (0.788-0.885 at ±X/±Y/(1,±1,0); as low as
0.232-0.238 at (1,0,±1)/(0,1,±1)). +Z is the unique maximum, exactly
matching ground truth. Geometrically explainable: a coherent connected
envelope is what a real parting-adjacent wall looks like; fragmentation
into many small disconnected patches is what scattered local features
look like — the same distinction D-028 already established matters, now
expressed as a testable per-direction metric instead of a post-hoc
narrative.

Cross-applying to Part3's 12 canonical directions: the highest-coherence
direction is **+Y/-Y at 0.857** (not (1,0,±1), which the older, flawed
area-percentage metric had favored) — still below Part1's 0.988, and
already known from D-026 to fail (287 H3 failures). No Part3 canonical
direction matches Part1's signature.

**Phase B/C — 96-direction angular sweep.** Documented resolution: cone
half-angles theta in {5, 10, 15} degrees, 8 azimuths (45 degree steps)
around each of the 4 required anchors ((1,0,1), (1,0,-1), (0,1,1),
(0,1,-1)), giving 3x8=24 perturbed directions per anchor. Every direction
run independently through the unmodified `analyse_parting_line`,
`PullDirectionInput(..., "manual")` throughout -- no optimizer involvement.
Both layers recorded separately per direction (never collapsed): direction-
only metrics (draft-good %, undercut %, near-zero %, coherence fraction)
and the full pipeline (Track A/B, stitch, graph, 2-core, candidates,
H0-H7 counts, best candidate, core/cavity). Total runtime 172s (~1.8s/dir).

**Result: zero valid candidates across all 96 directions** (2,030 total
raw candidates generated, 0 passed every gate).

**Phase D — searched for a positive control.** None found. The closest
analog to Part1's distinguishing signature (`h3_failures=0`) appears at a
cluster of 3 directions near `(0,1,-1)/(0,1,1) + theta{5,10,15} + phi180`
(direction ~ `(0, 0.866, -0.5)`). Traced in full per Phase E's instruction
("any candidate that looks globally plausible, trace it all the way
through"): of 8 raw candidates, 2 fail H0 (near-tangential geometry, a
known mechanism), and the other 6 are **the same single-torus-face pinch
already characterized in D-030/D-031** -- 4 segments each,
`h4_violation≈33.6%` (nearly identical to the 34.2-34.3% found at every
other direction tested this whole investigation), one face isolated from
the other 413. **This is a critical distinction, stated precisely**: this
cluster's `h3_failures=0` does NOT mean a genuine global candidate
appeared -- it means the raw candidate POOL AT THIS DIRECTION happens to
be small (8 candidates) and every member of it is either an H0 failure or
a trivial pinch, none of which are non-separating "junk" loops. Structurally
identical to what every other tested direction produces; only the pool
composition differs.

**Phase E — failure classification for the best candidates found.**
Every quasi-plausible candidate across all 96 directions falls into the
same bucket: **(D) passes H3 (or fails H0), rejected by H4** for the
identical single-torus-face-pinch reason found at every direction tested
since D-028. No candidate anywhere in this sweep showed evidence of case
(B) (global geometry existing but candidate generation failing to
construct it) or case (C) (candidate exists, H3 wrongly rejects it) --
consistent with, not contradicting, D-028/D-030/D-031's prior findings.

**Phase F — recommendation.** Consistent with D-030/D-031: **do not
modify the parting-line algorithm**. This sweep adds 96 more directions
(2,030 more raw candidates) of evidence that the failure mode is uniform
-- local-feature (torus/boss) dominance of the candidate pool -- not
direction-specific noise that a finer search resolves. This shifts weight
further toward hypothesis A (no feasible direction in the practical space
searched so far) without proving it: the fine sweep covers only tight
(<=15 degree) neighborhoods of 4 specific diagonals, not the full
practical direction space Bosch described.

**No production code changed.**

---

# Phase P3.5 — Second adversarial fixture (Track-B global answer) + merged direction-validation table

## D-031 — ADV2 (sphere + misaligned bosses): CASE E again, this time for a Track-B-only global answer; merged direction-validation table built from existing data ⭐

**[P3.5] 2026-08-13.** Closes the one gap D-030 explicitly flagged: ADV1's
global answer was Track-A-only (like Part1's own working case), leaving
"does a Track-B-required global answer also survive local-feature noise"
untested. No production code changed; new fixture generator
(`backend/validation/generate_adversarial_fixture_2.py`), new fixture
(`data/fixtures/synthetic/ADV2_sphere_with_boss_array.stp`, diagnostic-only,
not in the frozen manifest).

**Fixture.** Sphere r=20mm at origin (fixture F4's own body). Closed-form
answer at d=(0,0,1): the great circle z=0, r=20 (Track-B only — a sphere
has no usable edges). 6 cylindrical bosses (r=3, h=6) welded on at scattered
latitudes (40°/140° from the pole, i.e. well clear of both the equator and
the poles), oriented along the local outward radial normal — misaligned
with the global pull direction by construction, same role as ADV1's bosses.

**A real construction bug found and fixed before the experiment could
run** (recorded for completeness, not swept under the rug): a flat-bottomed
cylinder pressed exactly tangent to the curved sphere surface only touches
it at one point; `union()` left a residual sliver face instead of cleanly
consuming it, and by the 2nd boss this corrupted the sphere face out of
existence entirely (`SPHERE` surface type vanished from the shape, verified
face-by-face after each union). Fixed by embedding each boss's start point
3mm inside the sphere before extruding outward (`BOSS_INSET`), the standard
robust case for CAD boolean unions. Verified: sphere face type count stays
exactly 1 after all 6 unions, final shape has exactly 13 faces (1 sphere +
6×[cylinder+cap]), sphere face area 4855.94mm² matches
4πr² − 6×(hole area) analytically.

**Ran the unmodified production pipeline at (0,0,1).** Track A: 20
segments (boss-adjacent edges). Track B: 13 segments (6 sampled curved
faces, 0 degenerate, 6 flat faces correctly skipped as single-sign). 2-core
prunes 37 of 42 post-stitch segments, leaving 5 components, µ=5 — **5
candidates generated**. 4 are boss top-rim self-loops (`EdgeBacking`,
1 segment each) that correctly fail H3 (`region_count=1`, local, don't
separate). The 5th is `FaceBacking face_id=1` (the sphere itself), a
**single self-loop segment** whose points have z range exactly
`[0.0000, 0.0000]` and radius range exactly `[20.0000, 20.0000]` — the
precise closed-form answer, zero measured deviation. Passes every gate,
`h3_region_count=2`, selected, `coverage=0.885`.

**Decision-tree outcome: CASE E, again**, now for the Track-B-required
global-answer case. Combined with D-030 (ADV1, Track-A-required global
answer), both tested combinations of "global answer topology" × "heavy
misaligned local-feature noise" recover the exact correct result through
the unmodified pipeline.

**One new, honestly-reported, SEPARATE finding — not conflated with the
CASE E conclusion.** `RegionClassification`'s area-summary fields show an
attribution asymmetry for the split sphere face: `FaceClassification(
face_id=1, label='split', cavity_area_mm2=0.0, core_area_mm2=4855.94)` —
the entire face's area lands under `core_area_mm2`, none under
`cavity_area_mm2`, despite the face being evenly split (`mean_g≈0`,
`min_g=-0.99`, `max_g=+0.99`). **This does not affect H3/H4** — those
gates use `SeparationResult.component_count` (the graph-based partition,
confirmed correct: exactly 2 regions) — this is isolated to the
downstream, reporting-only `cavity_area_mm2`/`core_area_mm2` summary
fields on `RegionClassification` for a Track-B **split** face specifically
(the 6 boss cylinder side faces, labeled `'ambiguous'` rather than
`'split'`, do NOT show this — their area correctly lands in
`ambiguous_area_mm2`). Recorded as an open item for future investigation;
**not fixed here** (diagnosis only, and out of scope for the direction-vs-
algorithm question this phase is answering).

**Merged direction-validation table.** Built by joining two already-
computed datasets — no new pipeline runs. `reports/baseline_matrix_
principal.json` + `_diagonal.json` (D-026, full per-stage PL pipeline
results, 12 directions × 2 parts) and `reports/parting_line_direction_
diagnostic.json` (D-029, direction-only draft/undercut/near-zero metrics,
same 24 combinations). Full table in the chat report delivered alongside
this entry; not duplicated here to avoid a third copy of the same numbers
already recorded in D-026 and D-029.

**No production code changed.** New: `backend/validation/
generate_adversarial_fixture_2.py`, `data/fixtures/synthetic/
ADV2_sphere_with_boss_array.stp`.

---

# Phase P3.4 — The decisive adversarial fixture: CASE E, algorithm cleared

## D-030 — Synthetic adversarial fixture (box + 6 misaligned bosses) proves the architecture correctly recovers a known global loop through heavy local-feature noise — CASE E, not F ⭐⭐⭐

**[P3.4] 2026-08-13.** The decisive experiment separating hypothesis A
("Part3's tested directions don't expose a feasible line") from hypothesis
B ("candidate-generation has a systematic weakness under local-feature
noise"). No production code changed — one new fixture generator
(`backend/validation/generate_adversarial_fixture.py`), one new fixture
(`data/fixtures/synthetic/ADV1_box_with_boss_array.stp`, NOT added to the
frozen F1-F17 manifest — kept separate as a diagnostic-only fixture).

**Fixture design (mathematically obvious, zero free parameters).** A
60×50×40mm box (asymmetric dimensions, no accidental extra ties) plus 6
cylindrical bosses (r=4mm, h=8mm, 1.5mm toroidal base fillet), one centered
on each box face, axis normal to that face. Tested at d=(1,1,1)/√3.

Closed-form expected answer: every box face normal is exactly one of
±X/±Y/±Z, so g=n·d is a nonzero CONSTANT over each whole face — no face is
ever split, the entire silhouette is Track-A-only. 3 faces are "+"
(+X,+Y,+Z, meeting at corner (30,25,20)), 3 are "-" (meeting at
(-30,-25,-20)). An edge is a silhouette edge iff its two faces have
opposite sign — exactly 6 of the box's 12 edges qualify, forming the
textbook hexagonal "3-plane mold" cube-diagonal silhouette, visiting the
other 6 corners. Every boss axis (±X/±Y/±Z) is misaligned with (1,1,1) by
the same 54.7°, exactly mirroring Part3's vertical bosses under an oblique
pull direction: each cylinder's lateral face gets 2 open Track-B rulings
(same shape as fixture F3), each torus fillet gets its own mixed-sign
Track-B content, and none of it should form a closed loop — deliberately
reproducing Part3's local-feature-dominated-graph structure around a
provably correct global answer.

**Ran the unmodified production pipeline, zero special-casing.** Results:

| Stage | Measurement |
|---|---|
| Track A | 12 segments, all `silhouette` (6 hexagon edges + 6 boss-fillet-adjacent edges) |
| Track B | 18 segments, all `silhouette`, 0 degenerate faces, 12 faces skipped ("g does not change sign") = exactly the 12 flat faces (6 box + 6 boss caps), all correctly single-signed as predicted |
| Stitch | 42 junctions, 36 segments (6 edge-splits) |
| Graph (pre-2-core) | 42 nodes / 36 edges, 1 component |
| 2-core | **30 of 36 segments pruned**, leaving exactly 6 nodes / 6 edges, 1 component, µ=1 |
| Candidate generation | **exactly 1 candidate** |
| Gates | **passes everything** — H0/H1/H2/H3/H4/H5-H7 all clean |
| H3 | `region_count=2` |
| Selected | the sole candidate, `coverage=0.938` |
| Core/Cavity | `cavity_area_mm2 == core_area_mm2 == 7467.56` **exactly** (independent numerical confirmation — a diagonal cube cut is point-symmetric through the center, so exact equality is the mathematically expected, not coincidental, result); each boss correctly inherits its own parent face's side (3 cavity, 3 core) |
| Winning segments | all 6 are `EdgeBacking`, endpoints trace precisely the 6 predicted hexagon corners: (-30,25,-20)→(-30,25,20)→(-30,-25,20)→(30,-25,20)→(30,-25,-20)→(30,25,-20) |

**Decision-tree outcome: CASE E.** "The known global Parting Line is
successfully generated and validated." Every stage handled the adversarial
local-feature noise correctly: Track A/B genuinely detected the local boss
fragments (12+18=30 raw segments beyond the 6-edge hexagon), none of them
spuriously closed into false cycles, 2-core correctly identified all 30 as
non-cyclic tree material (consistent with D-029's proof that 2-core is
mathematically exact) and pruned them, leaving exactly the one true cycle,
which candidate generation found, and every gate passed cleanly with zero
false rejections.

**Answering the 8 required questions directly:**
1. Existed in Track A/B? Yes — Track A alone already contains the full
   correct hexagon; Track B correctly found real but non-participating
   local content.
2. Survived graph construction? Yes.
3. Survived 2-core? Yes — as the ONLY thing that survives.
4. Correct global cycle generated? Yes — the only candidate generated.
5. Which gate rejected it? None — passes all of H0-H7.
6. What stage lost it? None — nothing was lost.
7. Does this reproduce Part3's structural signature? **No** — this is the
   key finding. The fixture has heavy local-feature noise (30 of 36
   segments are local) and STILL cleanly recovers the global answer;
   Part3, at every direction tested, has NO surviving global cycle at all
   for the pipeline to find.
8. Recommendation: **A** — keep the algorithm frozen, focus on direction
   feasibility. Per the decision tree: "Part3 becomes substantially more
   likely to be a direction/geometry-specific problem." Per the protocol's
   own explicit instruction, Part3 is NOT to be revisited/modified now,
   since this experiment found no evidence of an algorithmic weakness to
   chase.

**What this does NOT prove.** One fixture, one direction, one topology
(genus-0 convex-ish main body + local bumps). Does not prove the algorithm
is correct on every possible topology (e.g. a main body whose OWN global
silhouette requires Track B face-interior curves, mixed with local-feature
noise, is untested — Part1's own working case is Track-A-only too, so this
remains an open combination). Does not prove Part3's specific 24 tested
directions are the ONLY ones that matter — Bosch's practical direction
space (rare diagonals) is not fully enumerated.

**No production code changed.** New: `backend/validation/
generate_adversarial_fixture.py`, `data/fixtures/synthetic/
ADV1_box_with_boss_array.stp` (diagnostic-only, not in the frozen
F1-F17 manifest).

---

# Phase P3.3 — Direction-feasibility vs. algorithm-correctness separation

## D-029 — Direction-only diagnostic layer + multi-direction candidate audit: separates "is the direction moldable" from "does the algorithm work," finds a distinguishing signature for Part1, and generalizes D-028's local-feature finding to 3 directions on Part3 ⭐

**[P3.3] 2026-08-13.** Explicit protocol: treat pull-direction feasibility
(hypothesis A) and parting-line-algorithm correctness (hypothesis B) as
coupled unknowns, and design experiments that separate them instead of
inferring one from the pipeline's final pass/fail. No production code
changed; two additions only: a read-only direction-only diagnostic script
(`backend/validation/parting_line_direction_diagnostic.py`) and 3 new
regression tests locking Part1 @ +Z (previously untested by the v2 engine
at all — only Part3.stp appeared in `tests/test_parting_line_v2_level1.py`).

**Step 1/3 — direction-only moldability layer, ranked before any
parting-line result is consulted.** Reused existing machinery only
(`analyze_draft(mutate=False)`, `detect_undercuts(mutate=False,
boolean_refine=False)`, `FaceData.signed_dot()` against the same
`silhouette_epsilon` the engine itself uses) — no new score invented.
Computed for all 12 Part1 and 24 Part3 directions.

**Finding 1 (important negative result, reported honestly, not
discarded).** The naive "lower near-zero-area % = more promising" ranking
places Part1's Bosch-confirmed **+Z dead last (11th/12th of 12)** among
Part1's own directions (near-zero 71.7% vs. 42.9-43.6% at the failing
±X/±Y). This is anti-correlated with ground truth, not predictive — a
cube-like part's zero-draft side walls are exactly where its parting
region legitimately sits, not a red flag. **This ranking heuristic was NOT
retrofitted to fix this** (that would be circular/p-hacking) — it is
reported as evidence that a single area-percentage scalar cannot
distinguish "large near-zero band along a genuine parting-adjacent wall"
from "scattered near-zero area from many small unrelated features," which
is exactly the distinction D-028 already found matters for Part3.

**Finding 2 (the actionable one).** For Part3, this same layer ranks
**(1,0,1)** and **(1,0,-1)** far above every other tested direction —
near-zero 2.6-4.3% and undercut 1.5-3.2%, vs. 22-56% and 0.1-33% elsewhere,
and specifically far better than **(0,1,1)**, the direction D-027/D-028's
entire deep investigation focused on (near-zero 24.6%, undercut 23.4%) —
solely because it happened to produce the largest-looking raw candidate
under the old, parting-line-driven investigation. That is exactly the
circular reasoning ("the algorithm liked this direction, therefore the
direction must be good") Step 3 of this protocol was designed to catch,
and it did.

**Step 4 — full candidate audit at (1,0,1) and (1,0,-1), the two directions
now independently flagged as most promising.** Same methodology as D-028:
raw-graph inventory, every raw cycle-basis loop tested individually through
`separate_surface` AND the full `evaluate_gates`. Result: **structurally
identical to (0,1,1)** in every respect that matters. At both directions:
Track A collapses to ~70 segments (vs. 287-352 at ±X/±Y — confirms the
low undercut/near-zero reading: most edges simply aren't straddle-silhouette
edges here), the raw graph reduces to a handful of small torus-boss
components (µ=9 at both), and every closed loop found is one of the same
two failure shapes already characterized in D-028: a small single-torus
"pinch" (`region_sizes=[1, 413]` or `[1, 414]`) passing H3 but rejected by
H4 at **34.2-34.3% orientation violation — nearly identical across all
three directions tested**, or a larger local ring that fails H3 outright
(`region_count=1`). No candidate at either direction does better than what
D-028 already found at (0,1,1). This generalizes D-028's conclusion from
one direction to three independently-motivated ones (not picked because
the algorithm liked them).

**Cross-check against the full D-026 24-direction table (already
computed, reused not rerun).** A clean distinguishing signature for Part1
was found by comparing H3-failure counts alone: **Part1 @ +Z/-Z is the
only Part1 direction with `h3_failures = 0`** (all 113 raw candidates
successfully separate the part; 109 then fail H4, 4 pass everything).
Every other tested Part1 direction (±X/±Y, both diagonals) has `h3_failures`
in the hundreds. **No Part3 direction, among all 24 tested, ever reaches
`h3_failures = 0`** — Part3's raw candidate pool, everywhere tested, is
dominated by loops that fail to separate the part at all, not merely loops
that separate it asymmetrically. This is a structural difference between
Part1's working case and every tested Part3 case, not an artifact of one
direction's analysis.

**Step 5/6 — positive-control suite and Part1 regression, verified not
rebuilt.** `data/fixtures/synthetic/` already has 15 analytic fixtures
(F1-F14, F17) with closed-form documented expected answers
(`manifest.json`) exercising exactly the failure modes this project cares
about (degenerate zero-draft bands, face-interior-only silhouettes,
fillet blends, through-holes, mirror-symmetric ties, alternating draft).
**All 136 existing tests pass**, including every fixture. This already
satisfies Step 5's request for known-answer geometry; no new fixture was
needed. Step 6 (`Part1 +Z` as a mandatory regression) had a real gap: no
test exercised `Part1.stp` through the v2 engine at all before this entry
(`test_parting_line.py`/`test_agent_tools.py` only cover the v1 engine).
Added 3 tests to `tests/test_parting_line_v2_level1.py`: a full-pipeline
pass/region-split check, a +Z/-Z mirror-image check, and a determinism
check — all pass.

**Classification (of the 5 offered): closest to E, with a specific,
evidenced lean.** Not enough evidence yet to fully rule out hypothesis A
(a genuinely feasible direction outside the 24 tested — Bosch's own
practical-direction search space is not fully enumerated by this set) or
to fully confirm B (no synthetic fixture reproduces "many small local
features dominate the candidate pool at every tested direction," so this
specific failure mode hasn't been demonstrated on a known-answer geometry
yet — see open item below). What IS now demonstrated, across 3
independently-motivated directions and cross-checked against the full
24-direction table: **the algorithm's H0-H4 gates are behaving correctly
on every candidate that exists** (D-028), and **Part3's raw silhouette
structure is dominated by disjoint local-feature geometry (small
stepped-cylinder bosses with toroidal fillets) at every direction tested
so far**, unlike Part1 @ +Z where the candidate pool is uniformly
separating (h3=0) even before H4 filtering. This is evidence the current
24-direction set may not contain Part3's feasible direction (leans
hypothesis A), but is not proof — a synthetic "part with local bosses and
a real hidden global parting line" fixture would be the decisive next
experiment (open item).

**Open items, explicitly not resolved by this entry:**
- No synthetic fixture yet isolates "local-feature-dominated candidate
  pool at every tested direction" with a KNOWN correct answer, so
  hypothesis B (candidate-generation defect) cannot be fully ruled out —
  only shown to be unsupported by every direction tested so far.
- The 24-direction set (6 principal + 6 diagonal, tested at both ± signs)
  does not exhaust Bosch's stated practical search space claim ("rare
  diagonal cases") — finer-grained or off-axis-but-still-practical
  directions have not been tested.
- Part1 ±X/±Y were not re-audited with this exact loop-by-loop methodology
  in this entry (D-026/prior-session enumeration work stands; not
  contradicted, not independently re-verified here).

**No production code changed.** New: `backend/validation/
parting_line_direction_diagnostic.py`. New tests: `test_part1_plus_z_is_a_
mandatory_regression`, `test_part1_plus_z_and_minus_z_are_mirror_images`,
`test_part1_plus_z_is_deterministic_across_reanalysis` in
`tests/test_parting_line_v2_level1.py`.

---

# Phase P3.2 — Part3 root-cause tracing (rejecting "infeasible" as a conclusion)

## D-028 — CORRECTS D-027: 2-core pruning is mathematically inert here; the real picture is a mix of trivial local H4 rejections and tree fragments that were never cyclic ⭐

**[P3.2] 2026-08-13.** Supersedes D-027's causal claim; D-027's raw
inventory data (segment IDs, backings, endpoint distances) stands and is
reused below, but its "(C) graph construction loses topology at the 2-core
stage" conclusion was **premature** — it inferred causation from "these
segments are real AND they get pruned" without testing whether pruning
itself was the mechanism. This entry runs that test directly, per an
explicit 8-task protocol (raw-graph inventory, termination classification,
simple-cycle-validity question, Part1 control, self-loop isolation,
2-core-bypass experiment, "don't blindly blame 2-core," and options —
**not implemented**).

**Task 6 (bypass 2-core), the decisive test.** Built the raw (pre-reduction)
graph, computed its own branch/µ stats, and called `extract_loops` on it
directly, skipping `reduce_to_two_core` entirely. Result: **identical 11
candidates, identical strategy (`cycle_basis`), identical exact segment-ID
set** — zero segments recovered. This is not a coincidence: 2-core peeling
only ever removes degree-1 nodes, each removal deletes exactly one node and
one edge (E−V invariant) and can never disconnect the remainder (a leaf's
removal is never a cut), so **the cyclomatic number of every raw connected
component is provably identical before and after reduction** — confirmed
empirically too: 0 violations of this invariant across all 4 runs
(Part3 @ (0,1,1), Part1 @ +Z/+X/+Y). A segment 2-core prunes could never
have been part of ANY cycle in the raw graph either. D-027's framing
("graph construction loses topology at the 2-core stage") is **wrong** —
2-core is exact, not lossy, for the question candidate generation asks.

**So what actually explains Part3 @ (0,1,1)'s failure?** Two separate,
now fully evidenced phenomena, neither of which is a pipeline defect:

1. **242 of 298 raw segments (81%) are real, correctly-detected,
   mixed-sign-relevant silhouette fragments that were never cyclic to
   begin with** — confirmed via `part.face_to_edges`/`BRepAdaptor_Surface`
   inspection: they belong to dozens of small, spatially separate local
   features (mirror-symmetric stepped-cylinder bosses with toroidal
   fillets — faces 0-16 mirrored by 18-34, areas 21-255mm², plus smaller
   isolated torus/cylinder fillets like face 318/327, areas 1.9-10.3mm²).
   At an oblique direction like (0,1,1), a small rotationally-symmetric
   boss's own silhouette is generically an **open arc**, not a full closed
   rim — it only closes when the pull direction aligns with the boss's own
   axis. 203 of 242 pruned segments terminate >0.05mm from any real B-Rep
   vertex (ruling out "clean corner termination" as the default story) —
   consistent with an edge/face-interior silhouette naturally starting and
   stopping wherever sign(g) crosses zero along that local feature, with no
   reason to expect that crossing point to land on a vertex. This is
   genuinely case A/E in the Task-2 taxonomy (the boundary legitimately
   terminates because the local feature's own silhouette does not close at
   this direction), not a missing-segment defect — endpoint gaps to any
   other candidate structure measured 12-37mm, an order of magnitude past
   `stitch_snap_tolerance_rel`, ruling out a tolerance explanation too.

2. **Every closed cycle that DOES exist in the raw graph was individually
   tested** (11 raw loops via `separate_surface`, then the full
   `evaluate_gates`). Five (`loops 4-8`, one per small torus fillet,
   segments like `[33,34,35,36]`) DO pass H3 (`region_count=2`) — but
   `region_sizes=[1, 413]`: they trivially pinch off **one single face**
   from the other 413. Correctly caught by **H4**: "34.2% of one region's
   area faces the wrong way" — chopping off one torus face does not create
   two mold-separable halves, since "the rest of the part" contains faces
   at every orientation. Group 1 (the 4-segment equatorial ring around the
   larger torus, faces 37/317, `loop 3`) is genuinely closed and
   non-trivial but fails H3 outright (`region_count=1`) via the bypass
   path already traced in the superseded D-027 entry — it is itself a
   **local** feature loop that never reaches the main body. One 10-segment
   component (`loop 1`) over-partitions (`region_count=3`). The two
   self-loops (`loops 9/10`) are the already-recorded periodic-seam defect.

**Root cause, corrected: not (C).** The graph, 2-core reduction, H3, and
H4 are all behaving **correctly** given their inputs. What's missing is
genuinely global, main-body-spanning silhouette structure that closes into
a simple cycle at this direction — Part3's local-feature geometry (bosses)
dominates the cyclic part of the graph at (0,1,1), and none of it, alone or
combined, constitutes a real 2-piece mold split. This is evidence *for* a
narrower, more defensible claim than either extreme: not "Part3 is
infeasible" (untested: only one direction traced this deeply, and the
mechanism here — local-feature dominance — is directly actionable, see
below) and not "there's a pipeline bug to fix" (disproven for 2-core
specifically by the bypass test).

**Answering the Final Question directly.** *Why are physically
parting-relevant fragments tree-like in the graph?* Because many of them
belong to local features whose own silhouette genuinely does not close at
this oblique direction — a geometric fact, not a representation flaw.
*Is the graph wrong, the pruning wrong, or is simple-cycle the wrong
abstraction?* Neither of the first two (both proven exact). The third is
subtler than a yes/no: simple-cycle is the **correct** model of what a
valid parting line must be, but the **current candidate pool does not
distinguish local-feature loops from global-body loops** before handing
everything to the same H3/H4 gates — so a real, evidenced, but non-global
loop (Group 1) and trivial local pinches (loops 4-8) compete in the same
pool as whatever true main-body structure may or may not exist, with no
signal to tell them apart before scoring. That is a genuine architectural
gap (relates to Task 7 options C/E below), but it is a **feature-scoping**
gap, not a graph-correctness bug.

**Task 4 (Part1 control) — supports the same picture at smaller scale.**
Part1 @ +Z (Bosch-confirmed working direction): **0 segments pruned** — the
entire 460-edge raw graph is already within the 2-core, no tree material at
all. Part1 @ ±X/±Y (known-failing): 32/491 and 32/524 segments pruned
respectively (~6.5%/6.1%), of which 24/32 (75%) are mixed-sign-relevant —
the same mechanism is present, just far less severe than Part3's 85%. This
is consistent with fragmentation severity tracking distance from a
genuinely moldable direction, not a fixed defect independent of direction.

**Task 7 — which outcome is supported.** Not 1 (2-core invalid — disproven).
Not 2 as originally read (graph construction "missing connections" in the
tolerance sense — disproven, gaps are real 12-37mm distances). Closest to
a mix of **4** (some fragments are legitimately non-participants — the
local-feature open arcs) and a qualified **5**: the candidate pool would
benefit from distinguishing local-feature loops from global-body loops
before scoring, not from a richer cycle-space representation as such.

**Task 8 — options, evaluated, NOT implemented:**

| # | Option | Verdict |
|---|---|---|
| A | Fix graph connectivity before 2-core | Not supported — Task 6 proves nothing is lost there |
| B | Topology-aware pruning instead of hard 2-core | Not needed — 2-core is exact for cycle space |
| C | Preserve dangling fragments until candidate construction, assemble across them | Real gaps are 12-37mm; bridging across them risks manufacturing candidates with no physical meaning (false-positive risk high) |
| D | Richer graph/hypergraph representation | Not evidenced as the bottleneck; the bottleneck is feature-scope mixing, not representation |
| E | Construct candidates from connected geometric contour components, with local-feature vs main-body classification before H3/H4 scoring | **Best supported by this evidence** — would let the search separately evaluate "does the main body alone have a global loop" from "do local bosses have their own loops" (relevant to this project's existing `side_core.py`/Bosch-criterion-#5 machinery, which already exists to handle local-feature tooling separately) |
| F | Re-run this same protocol at other directions/parts before generalizing | Required regardless of which fix (if any) is chosen — this entry traced exactly one direction on one part |

**No production code changed by this entry.** Diagnostic scripts only:
`backend/validation/parting_line_2core_pruning_diagnosis.py`.

**Where.** `backend/geometry/parting_line_v2/graph.py` (`reduce_to_two_core`,
`extract_loops` — confirmed correct), `regions.py` (`separate_surface` —
confirmed correct), `gates.py` (H3/H4 — confirmed correct, H4 is doing
exactly its documented job rejecting the trivial pinches).

---

## D-027 — SUPERSEDED BY D-028 above. Original text retained for the record; do not cite its causal claim.

**[P3.2] 2026-08-13, corrected same day.** Original root-cause claim
("(C) graph construction loses topology at the 2-core pruning stage") is
**incorrect** — D-028's direct bypass experiment (Task 6) proves 2-core
reduction is mathematically exact and empirically inert with respect to
candidate generation. The raw inventory, endpoint-distance, and
mixed-sign-sampling evidence gathered below remains valid and is reused by
D-028; only the causal conclusion drawn from it is retracted.

**[P3.2] 2026-08-13**

**Decision.** Diagnosis only — no algorithm change. Traced candidate 43
(Part3, direction (0,1,1) normalized, the largest/highest-coverage candidate
across the full 24-direction D-026 sweep) end-to-end to find the first point
where its physically-plausible geometry stops being usable.

**Findings, in the order proven:**

1. The two zero-length self-loop segments (242/244, periodic-seam artifacts
   on face 317 at u=2π) do **not** cause the `region_count=1` failure —
   removing them and re-running `separate_surface()` gives an identical
   result. Recorded as a real, independent Track-B defect, not fixed here.
2. The candidate is `discovered_by="loop_union"` with `loop_count=4`: a
   4-segment closed equatorial ring around the torus (faces 37/317, segments
   9/243/120/121 — "Group 1"), a separate 10-segment local loop elsewhere
   ("Group 2"), and the two self-loops. Tested independently via
   `separate_surface()`, **both Group 1 and Group 2 individually return
   `region_count=1`** — neither is a global separator on its own, despite
   Group 1 spanning the part's full diameter.
3. BFS over `separate_surface()`'s own adjacency construction found the
   concrete bypass for Group 1: a 17-hop path through 13 other faces, whose
   last hop crosses edge 117 itself (the edge Group 1's segment 9 partially
   covers). Edge 117 is a full 2π periodic edge; the candidate covers only
   t=[π,2π]; the remaining half is correctly *not* silhouette (both adjacent
   faces share sign(g) there) — real geometry, not a bug — but it leaves a
   live uncut adjacency the graph walks straight through.
4. Independent point-sampling (production `_FaceField.g()`, not
   graph-inferred) along the bypass path found 5 faces — **327, 38, 39, 318,
   35** — that are themselves mixed-sign (contain a genuine sign(g) flip)
   and therefore should carry their own silhouette split. All five *do* have
   correctly-detected silhouette segments in the raw 298-segment stitched
   pool (327: 1 segment, 38: 3, 39: 23, 318: 3, 35: 6) — Track A/B did not
   miss them.
5. Tracing those segments through `build_graph` + `reduce_to_two_core`: the
   segments on 327/38/39/35 are **pruned entirely by 2-core reduction**
   (dangling/tree-like, never part of any raw-graph cycle) and never reach
   candidate generation. Segment 244 (face 318) survives 2-core but as its
   own isolated 1-node component, disconnected from Group 1.
6. Ruled out stitch-tolerance as the cause: endpoint distances from these
   segments to Group 1 are 12-37mm on a 68.1mm-diagonal part, roughly an
   order of magnitude past `stitch_snap_tolerance_rel`'s 1.36mm. Real
   geometric gaps, not a numeric-tolerance artifact.

**Root cause: (C) graph construction loses topology**, specifically at the
2-core pruning stage, compounded by genuine geometric fragmentation of the
true parting-relevant silhouette structure into disjoint local islands
(around the torus, and separately on 327/38/39/318/35) that never connect
end-to-end. Explicitly **not**: the self-loop bug, H3's Track-B split-face
handling (confirmed working correctly — `(317,+1)`/`(317,-1)` nodes were
constructed and queried as designed), a stitch-tolerance shortfall, or a
Track A/B detection gap (the segments Track A/B found are all individually
correct).

**Why this matters.** This is evidence *against* concluding "Part3 has no
feasible direction" — the necessary silhouette geometry substantially
exists in the raw segment pool; it is discarded by a graph-preprocessing
step (2-core reduction) that assumes parting-relevant structure is always
cyclic, which is not true when the true boundary is composed of open,
mutually-disconnected fragments that must be bridged rather than pruned.

**Alternatives rejected.** Concluding infeasibility from the D-026 matrix
alone (rejected per explicit instruction — untested until this trace).
Attributing the failure to the self-loop bug (rejected in step 1 above by
direct causal test, not assumption). Attributing it to H3 modeling curved
Track-B interiors incorrectly (rejected in step 3 — the mechanism is a raw
B-Rep adjacency bypass, not a Track-B-specific modeling failure).

**Where.** `backend/geometry/parting_line_v2/graph.py` (`reduce_to_two_core`
— the pruning step that discards the disconnected fragments before loop
search runs), `backend/geometry/parting_line_v2/engine.py` (`_subset_unions`
— never sees the pruned segments as candidates), `regions.py`
(`separate_surface` — confirmed correct given its input). No production code
changed by this entry. Proposing a fix (e.g., relaxing/parameterizing 2-core
pruning to preserve fragments that lie within stitch-tolerance-scaled range
of other pruned fragments, or generating candidates that stitch across
component boundaries before 2-core reduction) is **out of scope for this
entry** and requires separate review before implementation.

---

# Phase P3.1 — Direction-isolated connectivity diagnosis

## D-026 — 24-combo baseline matrix (6 principal + 6 diagonal directions × Part1/Part3): Level 0-2 frozen

**[P3.1] 2026-08-12**

**Decision.** Ran the unmodified production pipeline (`analyse_parting_line`,
zero algorithm changes) against Part1 and Part3 at the agreed finite
direction set — the six principal axes (±X/±Y/±Z) plus six normalized
diagonals ((1,1,0), (1,-1,0), (1,0,1), (1,0,-1), (0,1,1), (0,1,-1)) — 24
part×direction combinations total. `PullDirectionInput(..., "manual")`
throughout; the direction optimizer is never imported, called, or
approximated (`test_no_module_imports_the_direction_optimizer`). Based on
this and the prior diagnoses in this phase (D-022 through D-025),
**Level 0-2 (Track A/B, stitching, graph, H0-H7, ranking) is frozen** — no
further changes to these layers without new, specific diagnostic evidence.

**Results.**

```
Part1: 2 of 12 tested directions feasible -- +Z and -Z only (mirror images
       of the same physical mold axis; identical winning candidate,
       cavity/core areas swapped as expected). 0 of 6 diagonals feasible.
Part3: 0 of 24 tested directions (principal + diagonal) produce a fully
       valid candidate.
```

Full principal-direction table:

| Part | Dir | Track A/B | Graph (n/e/c/μ/branch) | Candidates | H0/H1/H2/H3/H4/H5-7 | Fully valid | Outcome |
|---|---|---|---|---|---|---|---|
| Part1 | +X | 404/58 | 358/459/12/113/184 | 313 | 0/0/0/213/100/0 | 0 | no_feasible |
| Part1 | -X | 404/58 | 358/459/12/113/184 | 313 | 0/0/0/213/100/0 | 0 | no_feasible |
| Part1 | +Y | 424/63 | 389/492/12/115/194 | 315 | 0/0/0/212/103/0 | 0 | no_feasible |
| Part1 | -Y | 424/63 | 389/492/12/115/194 | 315 | 0/0/0/212/103/0 | 0 | no_feasible |
| Part1 | +Z | 460/0 | 356/460/9/113/200 | 113 | 0/0/0/0/109/0 | **4** | **feasible** |
| Part1 | -Z | 460/0 | 356/460/9/113/200 | 113 | 0/0/0/0/109/0 | **4** | **feasible** |
| Part3 | +X | 332/175 | 440/566/3/129/191 | 329 | 0/0/0/282/47/0 | 0 | no_feasible |
| Part3 | -X | 332/174 | 439/564/3/128/190 | 328 | 0/0/0/281/47/0 | 0 | no_feasible |
| Part3 | +Y | 336/169 | 438/559/4/125/185 | 325 | 0/0/0/287/38/0 | 0 | no_feasible |
| Part3 | -Y | 336/171 | 440/562/3/125/187 | 325 | 0/0/**2**/286/37/0 | 0 | no_feasible |
| Part3 | +Z | 352/0 | 260/352/18/110/184 | 310 | 0/0/0/159/151/0 | 0 | no_feasible |
| Part3 | -Z | 352/0 | 260/352/18/110/184 | 310 | 0/0/0/159/151/0 | 0 | no_feasible |

Diagonal directions: same pattern, 0/12 feasible on either part. New,
minor, secondary observation: **H0 failures appear for the first time this
phase** at diagonal directions (1-6 candidates per direction, both parts) —
zero H0 failures were ever observed at any of the 12 principal-direction
runs across this entire investigation. Not investigated further this pass;
flagged for anyone continuing this work, not acted on (small counts, does
not change any outcome — every direction still resolves to
`no_feasible_candidate` on H3/H4 regardless of the few H0 rejections).

**Why frozen, not further modified.** This is the endpoint of a long
convergent chain of evidence in this phase, not a snap judgement:

- D-022/D-023: the two connectivity-improvement attempts (stitch tolerance,
  Track-B boundary refinement) both produced real, measured, positive
  effects and neither came close to flipping any outcome.
- The enumeration-comparison experiment (Part1 ±X/±Y, basis vs Johnson):
  broader search (up to 44x more candidates) found nothing better on
  either the H4-violation or area-balance metric.
- The envelope experiment (Part3 ±X/±Y): stripping every confirmed-genuine
  articulation-point facet left a fully-connected, full-extent, zero-cut-
  vertex subgraph -- and its own basis/Johnson enumeration still topped
  out at the same ~16% H4 violation the full graph found. The facets were
  never the blocker.
- The H4 backward-trace (Part1's best candidate): of 101 wrong-sign faces,
  46% border no Track-A geometry at all and the other 19% that do are
  6.9-15mm from the current loop's own path, on a ~19-30mm part -- not a
  local construction miss.
- This matrix: Part1 +Z/-Z reproduce byte-identical results to every
  earlier measurement in this phase -- the golden control has not moved
  under any of the above changes.

**What remains open, honestly.** Part3 has no positive control. D-022
through this entry rule out several specific mechanisms (articulation
points, enumeration breadth, connectivity gaps matching the pre-fix
symptom) as THE blocker, but "0 of 24 tested directions work" cannot, by
geometry alone, be distinguished from "the right direction for Part3 was
not among the 24 tested" -- exactly the distinction the plan's Question A
vs Question B split was designed to preserve. This is a missing piece of
input (Bosch's actual Part3 direction), not a demonstrated algorithmic gap.

**Alternatives rejected.** Continuing to widen the direction search
ourselves -- explicitly out of scope (Question B belongs to the direction-
optimizer team); inventing a heuristic to force a Part3 result -- forbidden
by explicit instruction and inconsistent with every principle this phase
has followed.

**Where.** `backend/validation/parting_line_baseline_matrix.py`,
`reports/baseline_matrix_principal.json`, `reports/baseline_matrix_diagonal.json`.

---

## D-025 — Track-B face-backed segments now distinguish `tangential` from `silhouette`, reusing Track A's own semantics

**[P3.1] 2026-08-12**

**Decision.** Mechanism 2's diagnosis (face 317, Part3 @ +X) established that
a Track-B contour can legitimately run *along* a B-Rep edge that Track A's
own straddle test already classifies `"tangential"` — a real zero-draft
condition, not a numerical stitching defect. Track B previously had no such
label at all: `_emit()` hardcoded `kind="silhouette"` for every face-backed
segment, unconditionally. Fixed: a finished Track-B segment is now labeled
`"tangential"` instead of `"silhouette"` when it runs along a single B-Rep
edge that TRACK A's own test (`_g_on_both_faces` + `_classify`,
`max(|g_a|,|g_b|) <= silhouette_epsilon`) calls tangential at that edge's
start, middle, and end parameter. Geometry, points, and provenance
(`FaceBacking`) are byte-for-byte unchanged — only the `kind` label differs.

**Why this rule, not another — two measured, rejected alternatives.** Before
implementing, two Track-B-native candidate signals were tried and measured
directly on face 317, per the explicit instruction not to invent a rule
without measuring it:

- *Cell-corner `|g|` magnitude* (`max(|corner g|) <= epsilon` on the
  marching-squares cell a crossing came from — the naive Track-B analogue of
  Track A's two-sided test): **rejected.** Measured 18/227 cells "tangential"
  by this test, and the cells bordering the actual boundary-following chain
  were NOT among them — their boundary-side corner is exactly 0 (on the
  tangential edge itself) but their interior-side corner is ~0.22 (a real,
  substantial value one grid cell away), so the max-corner test misses
  exactly the case it was meant to catch.
- *`TopAbs_ON` fraction* (is most of the chain classified "on the trim wire"
  rather than "in the interior" by `BRepTopAdaptor_FClass2d`): **rejected.**
  Measured 90-100% `ON` on ALL THREE of face 317's chains, including the two
  chains judged (by their full-domain v-span) to be genuine transversal
  crossings — this face's trim topology is apparently dense/complex enough
  that "near some edge" doesn't discriminate tangential from transversal at
  all.

Both failed because they try to infer tangency from Track B's own local
data. Reusing Track A's edge-level test instead — the actual authoritative
source for "is this specific B-Rep edge tangential" — succeeded immediately
and matches exactly what was asked: use existing Track-A semantics as the
reference, not a new geometric rule.

**Verified effect (measured, not merely asserted correct):**

```
Face 317 @ Part3 +X: segment 135 (the 110-point chain pinned to v=v_max,
  touching edge 52 at both ends, distance 0.0mm) -> "tangential".
  Segments 134/136 (the two full-v-span transversal chains) -> "silhouette",
  unchanged. Exactly the 3-way split the mechanism-2 diagnosis predicted.

Part3 @ +X: 175 total face-backed segments, 146 silhouette / 29 tangential
Part3 @ +Y: 169 total, 144 silhouette / 25 tangential
Part1 @ +X: 58 total, 55 silhouette / 3 tangential
Part1 @ +Y: 63 total, 59 silhouette / 4 tangential
Part1 @ +Z, Part3 @ +Z: 0 face-backed segments (Track B silent, unaffected)
F4 (sphere), F17 (barrel loft), F3 (cylinder rulings): ALL segments remain
  "silhouette" -- correctly NOT reclassified. These are genuine transversal
  crossings (a great circle, a widest-circle ridge, two straight rulings),
  none of them boundary-following.
```

**Zero effect on candidate generation, H0, H3, H4, or outcome — confirmed,
not assumed.** `kind` is propagated through `stitch.py` unchanged but is
never branched on by `graph.py`, `gates.py`, `regions.py`, or `ranking.py`
(checked directly — the only other `.kind` references in the whole package
are `stitch.py`'s pass-through copies). Candidate counts, H3/H4 rejection
counts, pruned-segment counts, component counts, and μ are bit-for-bit
identical before and after this change on every direction tested. This is
by design: the task was semantic correctness, not behavioral change, and the
measurement confirms the implementation didn't accidentally cross that line.

**Full regression suite: 477 passed / 4 skipped / 3 pre-existing-and-unrelated
failures, unchanged.**

**What this does NOT do.** Does not merge Track A and Track B points. Does
not choose a location on the tangential locus. Does not change H3/H4,
enumeration, ranking, tolerances, or pull-direction handling. Does not
resolve the underlying non-uniqueness (D-022's mechanism-2 finding stands:
the true parting-boundary position along a zero-draft band is not
determined by pull direction alone) — it only makes the *representation*
honest about which segments are which, which is a prerequisite for any
future work that might want to treat them differently (e.g., excluding
tangential segments from certain candidate-quality scoring, or surfacing
them distinctly in the UI) without guessing from geometry each time.

**Where.** `backend/geometry/parting_line_v2/track_b.py`
(`_boundary_tangential_edge`, `_emit_classified`),
`backend/validation/parting_line_mechanism2_diagnosis.py`,
`reports/mechanism2_diagnosis_face317.json`,
`reports/p3_1_part{1,3}_AFTER_D025.json`.

---

## D-024 — `GeomAPI_ProjectPointOnSurf`'s default construction silently restricts to the surface's OWN `Bounds()`, not the face's trim extent — root-caused AND fixed ⭐

**[P3.1] 2026-08-12**

**Decision.** H0.3's `max_surface_deviation_mm` check was never a bug in
Track B's point generation — it was a blind spot in how the check itself
called OCC. **Fixed**: `gates.py`'s H0.3 face-backed branch now constructs
`GeomAPI_ProjectPointOnSurf` with explicit bounds
(`breptools.UVBounds(face.occ_face)` — the SAME authoritative trim extent
`BRepTopAdaptor_FClass2d` is built from two lines above it, not an invented
or expanded domain) instead of the implicit-bounds constructor. Falls back
to the implicit form only if the trim bounds themselves can't be retrieved,
so this can never silently skip the check. `tau_surface`, H0's definition,
and every other gate are untouched — this corrects the verifier's search
domain, not what it verifies.

**Why — measured, with a control.** Traced Part3 face 274's exact H0-failing
endpoint (candidate 102/103, `uv = [0.3725, 1.0121]`) through four
representations: (A) `BRepAdaptor_Surface` (location-aware), (B) raw
`BRep_Tool.Surface`, (C) `GeomLProp_SLProps` (what `track_b.py`'s
`_FaceField.point()` actually does), (D) `GeomAPI_ProjectPointOnSurf`
re-projecting C's point onto the same surface B (what `gates.py`'s H0.3
check actually does):

```
distance(A, B) = distance(A, C) = 1.4e-14 mm   <- point generation is exact
distance(C, D) = 0.00384 mm                     <- ALL of the error is here
projected (u, v) = [0.3726, 1.0]  vs original [0.3725, 1.0121]
```

`u` barely moved; `v` was clamped from 1.0121 to exactly 1.0. Checked the
surface directly: `Geom_BSplineSurface.Bounds() = [0.0, 1.0, 0.0, 1.0]`, but
`breptools.UVBounds(face)` (the face's real trim-wire extent, the same
oracle `BRepTopAdaptor_FClass2d` uses to authoritatively classify IN/ON/OUT)
reaches `v = 1.0121` — **the trim wire legitimately extends ~1.2% past the
surface's own declared knot domain.** `GeomAPI_ProjectPointOnSurf`'s simple
2-argument constructor seeds its search from `surface->Bounds()`, so it
cannot find a true zero-distance match for any point in that 1.2% sliver —
it returns the nearest point it *can* find within `[0,1]×[0,1]`, off by
several microns on a curved patch.

**Control (proves this is not generic OCC/BSpline behaviour):** the
identical A/B/C/D trace on `F17_barrel_bulged_loft.stp` (also a
`Geom_BSplineSurface`, from a loft) and `F3_cylinder_axis_perpendicular_to_pull.stp`
gives `distance(C, D) ≈ 1e-15` — both already pass H0 with
`max_surface_deviation_mm < 1e-9`. Their trim extents evidently stay inside
`Bounds()`; Part3's face 274 does not.

**This predates mechanism 1 (D-023) and is independent of it.** The
pre-mechanism-1 endpoint (`v ≈ 1.011`) already exceeded `Bounds()` and
already failed H0.3 for the same reason, with `max_surface_deviation_mm =
0.00472 mm`. Mechanism 1 moved the point to the geometrically *more*
correct location (the true trim boundary, `v = 1.0121`) and modestly
reduced the deviation (0.00472 → 0.00388 mm) simply because it's now closer
to `v = 1.0`, but it cannot close this gap — the true point is, by
definition, outside where the projector is willing to look.

**Verified, with the exact before/after numbers.** All 4 of Part3's H0
failures at +X and all 4 at +Y are now gone (`h0_case_study_part3_AFTER_H03_FIX.json`:
0/329 and 0/325). The 4 previously-H0-rejected candidates per direction are
still correctly rejected — now at H3/H4, for unrelated reasons; total
candidate counts are unchanged (329/325), confirming this only changed
*which gate* evaluates them, not how many candidates exist. Controls
(F4/F17/F3) unchanged — `max_surface_deviation_mm` identical to the
pre-fix values, since their trim extents were already inside `Bounds()`.
Two new regression tests added
(`tests/test_parting_line_v2_level1.py::test_h0_3_projects_within_the_faces_real_trim_extent_not_just_surface_bounds`
and `::test_h0_3_explicit_bounds_give_near_zero_residual_where_implicit_bounds_did_not`).
Full suite: 477 passed (+2 new) / 4 skipped / 3 pre-existing-and-unrelated
failures, unchanged from before this fix.

**Does not, and was never expected to, make Part3 `feasible`.** H0 passing
is necessary but not sufficient — H3 (topological separation) and H4
(orientation) still correctly reject the vast majority of candidates for
reasons this fix doesn't touch.

**Alternatives rejected.** Loosening `tau_surface` — rejected outright by
explicit instruction; it would hide a real (if narrow) API-usage gap rather
than fix it, and would weaken the check for every other candidate too.

**Where.** `backend/geometry/parting_line_v2/gates.py` (H0.3 face-backed
branch), `backend/validation/parting_line_h0_surface_deviation_trace.py`,
`reports/h0_surface_deviation_trace.json`,
`reports/h0_case_study_part3_AFTER_H03_FIX.json`,
`reports/p3_1_part{1,3}_AFTER_H03_FIX.json`.

---

## D-023 — Track-B boundary termination: refine to the true trim boundary, not the last grid point (mechanism 1)

**[P3.1] 2026-08-12**

**Decision.** `track_b.detect_face_silhouettes` now refines a segment
endpoint to the true trim-boundary crossing (bisecting against
`BRepTopAdaptor_FClass2d`, the same classifier that already decides IN/ON/OUT)
instead of stopping at the last marching-squares grid point classified
inside. Isolated to `track_b.py`; independently revertable.

**Mathematics.** Standard bisection in UV, using the trim classifier as the
oracle (never a distance heuristic): for adjacent chain points `p_in`
(IN/ON) and `p_out` (OUT), converge `mid = 0.5(p_in + p_out)` toward the
classifier's own IN/ON ↔ OUT transition, 40 iterations, floating-point
convergence. The refined point is only accepted if it still satisfies the
existing `tau_silhouette` check — H0 stays the arbiter of correctness, not
this refinement.

**Why — measured, and traced to a real H0 failure.** Tracing face 274's
marching-squares path end to end (`parting_line_track_b_termination_trace.py`):
every logged point is already an accurate root of `g=0` (Newton/bisection
converge correctly); the algorithm simply *stopped* at the last IN/ON grid
point rather than computing an intersection with the true boundary,
undershooting it by 0.046–0.14 mm on that face. The H0 case study
(`parting_line_h0_case_study.py`) independently found candidate 102's worst
offender is bit-for-bit the same point this trace identified — a directly
confirmed causal chain from termination to rejection.

**Validated effect (before → after, controlled directions only):**

```
Part3 @ +X:  pruned 66 -> 60   2-core components 4 -> 3   (real improvement)
Part3 @ +Y:  pruned 69 -> 61   2-core components 5 -> 4   (real improvement)
Part1 @ +X/+Y, Part3 @ +Z:  no material change (expected — Track B silent
                              at Part3 +Z; Part1's mismatches are mostly
                              mechanism-2/local-feature cases, untouched)
```

**Does NOT satisfy the H0 pass criterion.** All 4 of Part3's H0 failures at
+X and +Y still fail after this change — traced directly to a *different*,
pre-existing issue (D-024). Do not cite this entry as "the H0 fix." Full
regression suite: 475 passed / 4 skipped / 3 pre-existing-and-unrelated
failures, both before and after. Runtime cost: whole-suite time roughly
doubled (379s → 849s) from the added bisection.

**Alternatives rejected.** Increasing snap/weld tolerance (tried first,
see D-022 — real but did not move the pruned-segment count at all, and
risked distance-based over-connection); forcing Track A and Track B onto
the same point via nearest-neighbour merging (explicitly forbidden — would
fabricate a connection not backed by B-Rep topology).

**Mechanism 2, deliberately not touched.** Face 317 (24.75 mm mismatch): a
Track-B contour legitimately follows a near-zero-draft boundary over a
substantial distance; Track A and Track B can validly disagree on where
along that ambiguous edge the "crossing" is. Not established as a bug. Left
for a separate tangential/zero-draft boundary investigation.

**Where.** `backend/geometry/parting_line_v2/track_b.py`
(`_refine_trim_boundary`, the chain-processing loop in
`detect_face_silhouettes`), `tests/test_parting_line_v2_level1.py`.

---

## D-022 — Direction-contamination audit, and a stitch-tolerance change that measurably didn't work

**[P3.1] 2026-08-12**

**Decision.** Re-audited P2/P3's real-part evidence: 7 of 22 corpus rows
(Part1, Part3, 5 external parts) silently used the unvalidated upstream
direction optimizer before `parting_line_profile.py`'s SKIP-by-default
protocol existed. Re-measured Part1/Part3 at explicit controlled directions
only (`PullDirectionInput(..., "manual")`, never `"optimizer"`) going
forward. Confirmed **Part1 is already `feasible` at +Z** (0 pruned segments)
— a fact the optimizer-direction-only evidence never surfaced, since it
tested a different, harder direction.

**stitch_snap_tolerance_rel added, then found insufficient.**
`stitch.py`'s snap search and cut-detection loop were widened
(0.0068 mm → up to ~1.4 mm on Part3) and the cut-detection loop was
additionally scoped to `edge.adjacent_face_ids` (previously an unscoped,
whole-part proximity search — a real bug independent of the tolerance
question). Regression-clean, but **measured to change the pruned-segment
count by exactly zero**, on both real parts, at every controlled direction
tested, across four different variants of the attempt. Superseded in
practice by D-023's mechanism, which does move the number.

**Where.** `backend/validation/parting_line_connectivity_diagnostic.py`,
`backend/geometry/parting_line_v2/stitch.py`,
`reports/connectivity_diagnostic_part1*.json`,
`reports/connectivity_diagnostic_part3*.json`.

---

# Phase P3 — Level 2: measure-then-build enumeration

## D-021 — No optimization, because the profile says we are not the bottleneck

**[P3] 2026-08-09**

**Decision.** Nothing was optimized, despite P2's runtime regression.

**Why — measured.** Across the 22-part corpus:

```
        total 29,604 ms
          v2 pipeline   3,492 ms   (11.8%)
          upstream     26,112 ms   (88.2%)   <- load_step + direction optimiser
```

On Part1, v2's stages are **1,382 ms of a 14,941 ms** run — 9.3%. The
dominant cost is the **direction optimiser**, which belongs to teammates and
is explicitly outside this sub-team's scope.

Plan §12.5 rule 2 forbids optimizing a stage the corpus profile did not
identify as a bottleneck. It did not identify ours. Within v2, `filter` is
the largest stage (p50 128 ms, max 1,652 ms) and would be the target **if**
v2 ever became the bottleneck.

**Where.** `reports/p3a_profile.json`, `reports/p3b_profile.json`

---

## D-020 — `κ_min` cannot be calibrated from this data, and H7 is currently inert

**[P3] 2026-08-09**

**Decision.** `κ_min` stays at the provisional **0.50**. It was **not**
"calibrated" to a new value, because the data does not support one.

**Measured.** Of 196 candidates that reached H7, the **minimum coverage was
0.950**; among selected loops the minimum was **0.991**. Nothing came near
0.50 — H7 **rejected nothing, on any part in the corpus**.

Two honest readings, both worth stating:

1. **H7 is currently redundant.** H3 (separation), H4 (orientation) and H6
   (non-degeneracy) already remove every low-coverage candidate before H7
   sees it. That is the gate hierarchy working as designed (§7.0: H3 is
   primary, H7 is a sanity check).
2. **Its denominator is unreliable exactly where it would matter.** D-011's
   `A_cauchy` overestimates the projected outline by **+58.75% on Part3** and
   **+35.17% on Part1** (measured against a rasterised tessellation union).
   Coverage on those parts is therefore *understated* by ~37% and ~26%, so a
   genuinely good loop could read 0.57 against a 0.50 gate. Raising `κ_min`
   on the strength of a distribution that never approached it would risk
   false rejections on precisely the non-convex parts the gate is for.

The plan anticipated this: *"If the data does not support any clean threshold,
say so and keep it a reported diagnostic rather than inventing one."*

**Where.** `config.min_coverage_ratio` (unchanged), `reports/p3a_profile.json`

---

## D-019 — Γ subsets, not just pairs — and order them ascending

**[P3] 2026-08-09**

**Decision.** Multi-curve `Γ` candidates are **subsets** of up to
`max_loop_union_size = 4` disjoint curves, enumerated **smallest-first**.

**Why subsets.** P1 bounded this to pairs as the smallest step that fixed a
through-hole. P3 measurement showed pairs are not enough: Part3's reduced
graph is 3 disjoint cycles with **zero branch nodes**, so every single and
every pair was rejected at H3 and only the triple remained untried. A
genus-`g` part generally needs `g + 1` curves. Enumerating subsets is cheap
precisely because reduction works — `2ⁿ − 1` with `n` in the low single digits
across the whole corpus.

**Why ascending order — a bug I introduced and caught.** Sorted
**descending**, the first draft spent all 200 candidate slots on 4-subsets
(`C(16,4) = 1820`) before generating a single pair, so F9's correct answer —
outer rim ⊔ hole rim, a **pair** — was never built, turning a fixture that
passed at P1 into a failure. Ascending is also right on principle: fewer
curves is a simpler `Γ` and should be preferred.

**Where.** `engine._subset_unions`, `config.max_loop_union_size`

---

## D-018 — Johnson's self-loops, again

**[P3] 2026-08-09**

**Decision.** `_johnson_cycles` emits self-loop segments as one-segment cycles
before running `nx.simple_cycles`.

**Why.** `networkx.simple_cycles` operates on a graph built by skipping
self-loops (`if node_a != node_b`), so a closed circular edge — a hole rim, a
cylinder rim — cannot appear in its output. Omitting them silently dropped
F9's hole rim from the candidate set, so the only `Γ` that separates a holed
part could never be formed.

**This is D-006's failure mode arriving by a second route.** The lesson worth
keeping: every new code path that consumes the graph has to be asked
independently whether it handles self-loops, because the convention that a
self-loop has degree 2 is load-bearing and easy to lose.

**Where.** `graph._johnson_cycles`

---

## D-017 — Johnson was built as the gate required, then made opt-in ⭐

**[P3] 2026-08-09**

**Decision.** Bounded Johnson enumeration is implemented and **disabled by
default** (`enumeration_strategy: "basis"`). Beam search was **never written**.

**The gate ran as specified.** §6.1 forbids writing a search strategy before
the corpus `μ` distribution justifies it. P3a measured it over 22 parts:

| bucket | count | share |
|---|---|---|
| `μ == 1` | 4 | 18.2% |
| **`2 ≤ μ ≤ 12`** | **17** | **77.3%** |
| `μ > 12` | 1 | 4.5% |

median 4, p95 9, max 25. The gate's table maps a dominant `2 ≤ μ ≤ 12` band
to *"add bounded Johnson, still skip beam"*, and one part at `μ = 25` is not
the "real mass above 12" that would justify beam. So Johnson was built and
beam was not.

**Then P3b measured what it bought: nothing.**

```
        outcomes across all 22 parts:  14 feasible / 8 not   — IDENTICAL
        candidates:  up to 22x more   (F10:  9 -> 200, hitting the cap)
        runtime:     up to 10x        (F10: 168 -> 1756 ms)
```

**The reason is structural, and it is certain rather than suspected.** Six of
the eight failing parts have **`branch_node_count == 0`**: every node has
degree 2, so the connected components **are** the only simple cycles, and
Johnson and the basis produce *identical* candidate sets there by
construction. Enumeration is provably **not** the binding constraint.

Note also that Johnson **hit the 200 cap** on F10, so in practice it is a
*truncated* enumeration — not straightforwardly "more complete" than a basis.

**Kept, not deleted**, because the code is correct and complete where a basis
is not; flipping the flag is a one-line change if evidence ever changes. But
per plan §11 — *"Did complexity actually buy us something?"* — here,
measurably, it did not.

**Where.** `graph._johnson_cycles`, `config.enumeration_strategy`

---

# Phase P2 — Level 1: face-interior silhouette curves

## D-016 — A point not on the zero set is not a silhouette point ⭐

**[P2] 2026-08-09**

**Decision.** Track B discards any crossing whose ``|g| > τ_silhouette``,
rather than emitting it and letting H0 reject the whole curve.

**Mathematics.** The silhouette is *defined* as ``Σ_f = {(u,v) : g(u,v) = 0}``.
Marching squares finds cells where ``g`` changes **sign**, which is the same
thing **only if ``g`` is continuous**. At a parametrisation seam or a
degenerate boundary ``g`` can jump sign without ever passing through zero, so
the sign change is real and the root is not.

**Why — measured.** Part3 face 407 at its optimal direction produced a run
entirely at ``u = 1.0`` (the domain boundary) with ``g`` alternating
``−0.825, +0.825, −0.825, +0.825``. No refinement can resolve that: there is
no root to find. Gate H0.3 correctly rejected the resulting candidate, which
is the system working — but the honest fix is not to manufacture the point in
the first place.

Newton's budget was increased with a **guaranteed bisection tail** at the same
time (bisection always converges on a maintained bracket), so genuine
slow-converging crossings are not confused with impossible ones.

**Where.** `track_b.detect_face_silhouettes`, `track_b._refine`

---

## D-015 — H3 must be **sub-edge** aware, not just sub-face

**[P2] 2026-08-09**

**Decision.** An edge counts as cut only over the **parameter intervals** ``Γ``
actually covers, and a split face attaches to a neighbour via a point in the
edge's *uncovered* portion.

**Why — measured on F3.** The correct ``Γ`` for a cylinder pulled across its
axis is *two rulings + two rim arcs*, where each arc covers only the **upper
semicircle** of a cap rim. Treating coverage as per-edge severs the cap from
the lower lateral half entirely, and H3 reports 1 region — rejecting the right
answer. The lower semicircle is still doing real connecting work.

Choosing the evaluation point matters as much: asking "which side of the split
face does this edge belong to" at the edge's *midpoint* can land inside the
covered part. It must be asked where the edge is still connecting.

**Where.** `regions.separate_surface`, `regions._uncovered_parameter`

---

## D-014 — H3's face-splitting form, by the sign of `g`

**[P2] 2026-08-09**

**Decision.** A face that ``Γ`` passes **through** becomes **two** nodes in the
region graph, split by ``sign(g)``.

**Mathematics.** The cutting curve *is* the level set ``g = 0``, so its two
sides are exactly ``{g > 0}`` and ``{g < 0}``. No 2-D UV partition is needed —
the sign is the partition.

**Why.** With Track B, ``Γ`` no longer runs only along B-Rep edges, and the
cheap edge-only H3 stops being exact: a sphere's great circle divides its
single face in two, but that face is one graph node with no link to remove, so
the edge-only test reports 1 region and rejects the correct answer.

The plan scheduled this for P3b, on the assumption Track B would land after
it. The dependency runs the other way, and P2 could not be finished without it.

**Documented limitation.** Exact when ``{g>0}`` and ``{g<0}`` are each
*connected* on the face — true for a single monotone crossing, which covers
every corpus case. A face crossed several times could have a disconnected
side. Building the full UV partition is only worth it if a real part is
measured to need it.

**Where.** `regions.separate_surface`, `regions.classify_regions`

---

## D-013 — Adjacent runs must abut exactly; single-sample runs are real

**[P2] 2026-08-09**

**Decision.** Track A keeps single-sample runs, and gives every run a
parameter span reaching the **midpoint** between it and its neighbour, so
consecutive runs share a boundary parameter.

**Why — measured on F3.** The cap-rim classification goes
silhouette → tangential → silhouette, and the one-sample tangential run sits
at exactly ``θ ≈ 0`` and ``π`` — precisely where the face-interior rulings
meet the rim. Discarding it as a "numerical touch" left each arc ending
**~1.4 mm short** of the junction, so nothing welded, 2-core deleted
everything, and the engine reported no candidate for a part whose answer is
obvious.

The discard rule was arbitrary; the fragmentation it caused was not.

**Where.** `track_a._runs`, `track_a._run_bounds`

---

## D-012 — The two tracks must be **stitched**, not merely concatenated

**[P2] 2026-08-09**

**Decision.** Edge-backed segments are split at the parameters where
face-backed curves terminate on them.

**Why.** The tracks produce curves that **meet but share no endpoint**. A
face-interior curve runs to the edge of its face and stops at a *general
point* along a B-Rep edge; Track A's segment spans the whole edge. Welding by
proximity never joins them — the curves touch in space while the graph has no
node where they touch.

Split points come from projecting the face curve's endpoint onto the **edge's
own OCC curve**, so both sides land on identical geometry and H0 is preserved
by construction.

**Where.** `stitch.stitch_tracks`

---

## D-011 — The Cauchy denominator must be **area-weighted**

**[P2] 2026-08-09**

**Decision.** ``⟨|g|⟩ = Σ|g_i|·J_i / ΣJ_i`` with ``J = ‖S_u × S_v‖``, on an
``11 × 11`` grid.

**Mathematics.** Uniform ``(u,v)`` sampling is correct only where the Jacobian
is constant. On a sphere it oversamples the poles, returning
``⟨|sin v|⟩_uniform = 2/π ≈ 0.637`` against the true area-weighted ``0.5``.

**Why — measured.** That 27% overestimate of the denominator made the sphere's
great circle — the exactly correct answer — score **80.7%** coverage.

**Grid chosen from measurement**, not preference. Error against the sphere's
exact ``πr²``:

| grid | 5×5 | 7×7 | 9×9 | **11×11** | 15×15 | 21×21 |
|---|---|---|---|---|---|---|
| error | −4.89% | −2.51% | −1.52% | **−1.02%** | −0.55% | −0.28% |

Note the denominator is **common to every candidate of a part**, so its error
cannot affect *ranking* — only the reported coverage and the H7 comparison.

**Where.** `regions.mean_abs_g`, `config.face_sample_grid`

---

# Phase P1 — Level 0 baseline

## D-010 — Coverage numerator is the **largest** loop, not the sum

**[P1] 2026-08-09**

**Decision.** For a multi-curve `Γ`, T1's numerator is `max_k |A_proj(Γ_k)|`.

**Mathematics.** Each component curve encloses a projected area by the
shoelace formula; we take the maximum rather than the sum or the signed total.

**Why.** T1 asks *"does this candidate wrap the part's outer silhouette"*, and
it is the outer curve that answers it.

- **Summing** would reward a candidate merely for including an extra hole rim.
- **Signed summing** (outer positive, holes negative) would *penalise* the
  correct answer for a holed part — the hole rim is a **required component** of
  a valid `Γ`, not a defect — and it needs a containment test and consistent
  orientation, neither of which is free.

**Consequence, accepted knowingly:** coverage can exceed 1.0. Measured on F9:
the outer rim encloses 40×40 = 1600 mm² while the part projects
1600 − π·6² ≈ 1487 mm², giving **107.6%**. That is correct, not a bug — the
rim encloses the hole, the denominator counts only material. H7 is a *floor*,
so a value above 1 never causes a rejection. It is reported rather than
clamped, because clamping would hide the fact that the two quantities measure
different things.

**Where.** `measures.largest_loop_projected_area`

---

## D-009 — Degree-2 chain contraction deferred, with a proof it costs nothing

**[P1] 2026-08-09**

**Decision.** §5.4's second reduction pass is **not** implemented at Level 0.

**Mathematics.** Contraction is safe to defer because the quantities that
depend on it are **invariant** under it. Collapsing a chain of `k` edges into
one super-edge removes `k−1` nodes and `k−1` edges, so the cyclomatic number

```
        μ = E − V + P
```

is unchanged, and no node's degree changes except the removed ones (which were
degree 2 and therefore never branch nodes). Both `μ` and `branch_node_count` —
the two numbers P3a's build-order gate consumes — are identical with or
without it.

**Why.** No Level-0 search benefits from the smaller graph, and building it now
would be machinery with no measured need, which is exactly what plan §6.1's
build-order gate forbids. Deferring is only defensible *because* of the
invariance argument above; without it this would be a silent approximation.

**Where.** `graph.py` module docstring

---

## D-008 — Cauchy projected area needs the **integral** of `|g|`, not a sample

**[P1] 2026-08-09**

**Decision.** The T1 denominator integrates `|g|` over each face by `M × M` UV
sampling, rather than using `A_f · |n̂_centroid · d̂|`.

**Mathematics.** The Cauchy-type bound for a closed solid is

```
        A_proj(∂S) ≤ A_cauchy = ½ · Σ_f ∫_f |n̂ · d̂| dA
```

with equality for a convex body. The **integral** is what makes it a bound.
Replacing `∫_f |n̂·d̂| dA` with `A_f · |n̂(centroid)·d̂|` is a different
quantity with no bounding property at all whenever `n̂` varies over the face.

**Why — measured.** The single-sample version produced **coverage = 104.4%**
on F7 (a lofted spline lid): a loop apparently covering *more than the whole
part*, which is impossible for a true upper bound and immediately falsified
the documentation claim that coverage is a conservative under-estimate. With
the integral, F7 reports exactly 100.0%.

**Caveat kept honest.** Sampling is uniform in `(u,v)`, not area-weighted, so
it is exact for constant-Jacobian surfaces (planes, cylinders) and an
approximation elsewhere. The exact tessellation-union path in P3a is what will
quantify the residual.

**Where.** `regions.mean_abs_g`, `engine.analyse_parting_line`

---

## D-007 — `Γ` is a **disjoint union** of closed curves ⭐

**[P1] 2026-08-09] — supersedes the original C1**

**Decision.** A parting line is `Γ = Γ₁ ⊔ … ⊔ Γₖ`, not a single closed curve.

**Mathematics.** The original C1 required `Γ ≅ S¹`. The binding condition is
actually **C4** — `∂S \ Γ` has exactly two components — and how many curves
that takes is a property of the part's topology, not something to assume. A
part of genus `g` generally needs `g + 1` curves.

**Why — measured on F9.** Box with a through-hole, pull `+Z`. Cutting the
outer top rim alone leaves the top face still connected to the bottom face
**through the hole's cylindrical wall**, so `separate_surface` returns **1**
region and H3 correctly rejects it. The `Γ` that separates is
**outer rim ⊔ hole rim** → exactly 2 regions, `{top face}` and the rest.

This was a flaw in the formal statement, not in the implementation — and it
was **caught by H3**, which is the strongest possible argument for having made
the topological separation test primary (§7.0) rather than the coverage
heuristic. The test caught an error in the definition above it.

Holes are ubiquitous in real automotive plastic parts, so the single-curve
model would have made a large fraction of real geometry unanalysable.

**Implementation, deliberately bounded.** Unions are formed **only** from
candidates that are geometrically sound but failed H3 with exactly one region,
and **only** when round 1 produced nothing feasible. Pairs only. A single
curve that separates is simpler and always preferred; higher-order unions wait
for evidence that a real part needs them.

**Where.** `types.PartingLoopCandidate.loops`, `engine._pair_unions`,
plan §1 C1

---

## D-006 — A closed circular edge is a graph **self-loop** of degree 2

**[P1] 2026-08-09**

**Decision.** A segment whose two endpoints weld to the same node is recorded
**twice** in the adjacency list.

**Mathematics.** Standard graph convention: a self-loop contributes **2** to
its node's degree, because both of its ends are incident there. Recording it
once gives degree 1.

**Why — measured.** Degree 1 makes `reduce_to_two_core` delete it as a
dangling end. A full circular B-Rep edge — a hole rim, a cylinder rim, a
cone's base circle — welds to a single node, so it was being **silently
discarded**. Consequences, all measured:

- **F2** (cylinder ∥ pull) and **F5** (cone) reported `no_feasible_candidate`
  when their rim circles *are* their correct parting lines.
- **F9**'s hole rim vanished, leaving the top face permanently connected to
  the bottom through the hole wall — so no candidate could ever separate the
  part, and the C1 bug above could not even be reached.

After the fix all three are feasible (F2 99.4%, F5 99.4%, F9 via a two-curve
`Γ`). A convention that reads as pedantic was load-bearing.

**Where.** `graph.build_graph`, `graph.extract_loops`

---

## D-005 — The sharp-edge silhouette test is **inclusive**, not a strict product ⭐

**[P1] 2026-08-09**

**Decision.** An edge is a silhouette edge when

```
        0 ∈ [min(g_a, g_b), max(g_a, g_b)]        (± ε)
```

not when `g_a · g_b < 0`.

**Mathematics.** Across a sharp edge the normal is **set-valued**: it sweeps
the geodesic arc from `n̂_a` to `n̂_b`. By continuity `g = n̂·d̂` attains
**every** value between `g_a` and `g_b` along that arc. So if either endpoint
is zero, the arc still touches `g = 0` and the edge lies on the silhouette.
The strict product test excludes exactly that case.

**Why — measured on F1.** A cube pulled `+Z` has `g = 1` on the top face and
`g = 0` on each side face. The strict test gives `1 × 0 = 0`, not negative, so
it finds **no silhouette on the cube's top rim** — manifestly the outline you
see looking down the pull axis. The first implementation had this bug and
returned 4 tangential segments and nothing else. With the inclusive test it
returns **8 silhouette segments (top rim + bottom rim) + 4 tangential**, the
analytic answer.

**Ordering matters too:** `tangential` is tested first and wins. When *both*
sides are within `ε` of zero the edge sits inside a zero-draft band, where the
parting line's position is a free parameter (§5.3) rather than a determined
crossing. v1 conflates the two into one `near_parting` kind.

**Where.** `track_a._classify`

---

# Phase P0 — Contracts, fixtures, harness

## D-004 — Per-stage timing is a first-class result field, not logging

**[P0] 2026-08-09**

**Decision.** Every v2 stage records `elapsed_ms` into a `StageTimings` object
carried **on the result**, not emitted to a logger.

**Why.** Plan §12.5 requires publishing p50/p95 per stage across the corpus.
That is only possible if timings are *data*. Log lines cannot be aggregated
across a corpus run without parsing, and parsing log text is a fragile
dependency for a gate that P3a's optimization decisions depend on.

The secondary reason is honesty: an unmeasured runtime regression is
indistinguishable from no regression. Making timing a field means every
result carries its own evidence.

**Alternatives rejected.**
- *Python `logging` at DEBUG* — not aggregatable; disappears in production.
- *`cProfile` on demand* — measures the wrong thing (function-level, not
  stage-level) and cannot run on every corpus part cheaply.
- *Decorator-based timing* — cleaner to write, but stage boundaries do not
  align with function boundaries (Track A and Track B both span several
  helpers), so the numbers would not match the plan's stage names.

**Where.** `backend/geometry/parting_line_v2/timing.py`

---

## D-003 — Inputs are validated on entry and refuse to default

**[P0] 2026-08-09**

**Decision.** `PullDirectionInput` and `UndercutInput` validate on construction
and **raise** on invalid input. No silent fallback to `+Z`, no silently
dropped face ids.

**Mathematics.** The pull direction must satisfy

```
        ‖d‖ = 1 ± 1e-9
```

and is stored normalized. A zero-length or non-finite vector is rejected
outright rather than normalized-with-a-warning, because there is no defensible
"nearest unit vector" to a zero vector.

**Why.** v1's `classify_core_cavity` silently falls back to `+Z` when no
direction is supplied (`core_cavity.py:137-139`) and merely appends a warning.
A warning that nobody blocks on is how a whole analysis gets computed against
the wrong axis while every reported metric looks healthy — the same failure
class the audit found repeatedly (RC-4).

The pull direction is **foundational**: per `CLAUDE.md`, everything downstream
is computed relative to it. Defaulting it is not a convenience, it is a
correctness hazard.

**Alternatives rejected.**
- *Warn and default to +Z* — v1's behaviour; rejected above.
- *Return a typed error instead of raising* — the rest of the pipeline returns
  structured results rather than raising, but that convention exists for
  **geometry** failures, which are expected and recoverable. A malformed input
  contract is a **programming** error, and should be loud.

**Where.** `backend/geometry/parting_line_v2/contracts.py`

---

## D-002 — v2 is a package, and its module boundaries are enforced by test

**[P0] 2026-08-09**

**Decision.** `backend/geometry/parting_line_v2/` is a package. Two import
rules are enforced by an automated test, not by convention:

1. **No module in the package may import `side_core`.** (Plan §12.8 —
   referrals are emitted, never routed, during P0–P6.)
2. **Candidate-generation and ranking modules may not import the surface
   provider.** (Plan §10.2 rule 1 — the parting line is a real geometric
   result, independent of how we currently split the mold.)

**Why.** Both rules exist to stop a specific, *tempting* shortcut. Rule 1's
temptation is "while we're here, just call Stage 4". Rule 2's is "the split
plane is right there, use its centroid". A convention documented in Markdown
does not survive contact with either; an import test does.

This mirrors the plan's own reasoning about warnings-vs-gates: a rule with no
mechanism behind it is decoration.

**Alternatives rejected.**
- *A single `parting_line_v2.py` module* — would make the import rules
  unenforceable (you cannot forbid an import within one file), and v1 is
  already a 4,746-line cautionary tale about single-module growth.
- *Lint rule / `flake8-tidy-imports`* — no linter is configured in this repo
  (audit: "no mypy, pyright, or ruff config"), so adding one is a bigger
  change than a test.

**Where.** `backend/geometry/parting_line_v2/`, `tests/test_parting_line_v2_contracts.py`

---

## D-001 — Provenance is a required field, not an optional annotation

**[P0] 2026-08-09**

**Decision.** `CurveSegment` cannot be constructed without a `backing` that is
either `EdgeBacking(edge_id, t_start, t_end)` or
`FaceBacking(face_id, uv_points)`. There is no `None` backing and no
"unknown" provenance.

**Mathematics.** This is the type-level encoding of hard gate **H0.1**. The
on-surface invariant requires that every point `p ∈ Γ` be recoverable from OCC
geometry:

```
        p = C(t)        for an edge-backed point, C = the OCC edge curve
        p = S(u,v)      for a face-backed point,  S = the OCC face surface
```

A segment with no backing has no `C` and no `S`, so `dist(p, ∂S)` is not
computable, so H0 cannot be evaluated — the candidate is unverifiable rather
than merely unverified.

**Why.** Making it a required constructor argument means a segment that
violates H0.1 **cannot be built**, rather than being built and then caught by
a filter that someone might later reorder, skip, or gate behind a flag.

This is the direct structural answer to RC-7 / the levitating parting line:
v1's final curve is Chaikin output that has no backing at all — there is no
edge or face it can be checked against, which is exactly why its drift was
never measured in the entire life of the feature.

**Alternatives rejected.**
- *`backing: Backing | None = None`* — allows the defect to exist and defers
  detection to runtime. The whole point is to make it unrepresentable.
- *A string tag (`provenance="edge"`)* — carries the label without the data.
  You cannot project a point onto a string.

**Where.** `backend/geometry/parting_line_v2/types.py`

---

# Measurements

## M-P3 — Corpus profile, 2026-08-09

`reports/p3a_profile.json` (measure) and `reports/p3b_profile.json` (after
build). **22 parts**: 15 synthetic + Part1/Part3 + **5 external models**
(GrabCAD-style: cones, cylinders, tori, BSplines). Real and external parts
profiled at their **optimal** direction, never `+Z` — P2 measured why.

**Outcomes: 14 feasible, 8 not, 0 CRASHES.** Rejections by gate:
`H4: 302, H3: 61, H6: 2`.

### B-18 — The corpus is short of the exit gate's target

The gate asks for **≥ 20 GrabCAD/ABC parts**. Only **5** external models were
available on this machine. The zero-crash result therefore covers 22 parts
total, not 20 *external* ones. Stated rather than glossed: generalisation
evidence is thinner than planned, and more external models are the single
cheapest way to strengthen it.

### B-19 — `A_cauchy` overestimates by up to 59% on real parts ⭐

Measured against a rasterised tessellation union (1024², error ≈ 0.1%):

| part | `A_cauchy` | exact | overestimate |
|---|---|---|---|
| **Part3** | 1889.4 | 1190.2 | **+58.75%** |
| **Part1** | 612.5 | 453.2 | **+35.17%** |
| F11 pockets | 2184.0 | 1800.0 | +21.33% |
| corpus median | | | **+0.24%** |

Near-exact on convex shapes (median +0.24%, min −0.62%), badly off on the
non-convex real parts — exactly as the Cauchy bound predicts. Coverage on
Part1/Part3 is understated by ~26% and ~37%, which is why `κ_min` was not
raised (D-020).

### B-20 — Enumeration is provably not the blocker; connectivity is ⭐⭐

Johnson changed **zero** outcomes (D-017). The real signal is in the
reduction:

| part | segments in | edges after 2-core | components | pruned as dangling |
|---|---|---|---|---|
| Part1 | 243 | 30 | 5 | **213 (88%)** |
| Part3 | 252 | 8 | 3 | **244 (97%)** |

The silhouette segments **exist** — Track A finds 136 on Part1, Track B 84 —
but they do not connect. What survives is a handful of small **local** cycles
(boss rims and similar), which is why Part1's candidates all fail **H4**: a
boss rim separates cleanly into 2 regions, but the larger region contains both
up- and down-facing faces. They are correctly rejected local features.

Measured endpoint gaps between non-welded segments: **7e-05 to 2.4e-04 mm**
against a weld tolerance of **3.08e-05 mm** — 2× to 8× too tight. Sub-micron
on a 30 mm part, i.e. **numerical, not geometric**.

Snapping face-curve endpoints onto their bounding edges (D-012's second half)
was implemented and did **not** change Part1's reduction, so those particular
gaps are not Track-B-to-edge. **The next diagnosis is where they are** — and
it is a connectivity question, not an enumeration one. Named precisely rather
than guessed at, and deliberately not attacked with more machinery.

### B-21 — Runtime: v2 is 11.8% of the total

```
        corpus total 29,604 ms
          v2 pipeline   3,492 ms  (11.8%)
          upstream     26,112 ms  (88.2%)  load_step + direction optimiser
```

Per-stage p50/p95 (ms): `filter` 128.5 / 488.4 (largest), `track_b`
2.1 / 106.2, `track_a` 3.0 / 56.7, `weld` 0.1 / 19.1, `enumerate` 0.2 / 4.0,
`reduce` and `rank` ≈ 0.

**No optimization performed** (D-021).

---

## M-P2 — Level 1 measured, 2026-08-09

`reports/p2_level1.json`. **16 of 17 fixtures feasible** (P1: 12 of 17).

### B-12 — The three Track B fixtures are solved *exactly* ⭐

| fixture | expected | measured |
|---|---|---|
| **F4** sphere | great circle, `z = 0`, `r = 20` | `\|z\| < 1e-6`, `r = 20.000000` |
| **F17** barrel | circle at mid-height, `r ≈ 16` | `z = 20.0000`, `r = 16.0000` |
| **F3** cylinder ⟂ pull | two rulings | `\|z\| < 1e-6`, `\|y\| = 15.000000` |

F3's answer needs **both tracks**: `mix = {edge: 6, face: 2}` — Track B's two
rulings stitched to Track A's rim arcs. Coverage 100.7%.

**A correction to the fixture, not the code:** F3's rulings are at
**`y = ±15, z = 0`**, not `z = ±15`. At `z = ±15` the normal is `(0,0,±1)` so
`g = ±1` — the *extreme*, not the zero. The fixture's expected-answer text said
`z = ±15` and was wrong.

### B-13 — The P2 exit gate: honoured, and it reversed my first conclusion ⭐⭐

The gate was written in advance: *"Part3's component count must drop sharply
from 22. If it does not, the RC-1 hypothesis is wrong and we stop and
re-diagnose rather than layering on more machinery."*

**First measurement, at `+Z`: it did not drop.** 18 → 18, μ 110 → 110, and
Track B found **zero** segments — 317 of Part3's faces have no interior sign
change and 97 are zero-draft bands.

Before declaring the hypothesis dead, one fair-test check: `+Z` is **not**
Part3's optimal direction, and B-5 already measured a 23× direction
sensitivity. At its **optimal** direction:

| | at `+Z` | at optimal |
|---|---|---|
| Track B segments | **0** | **203** |
| Components | 18 | **3** |
| μ | 110 | **3** |

Against v1's **22 components**, that is 22 → 3. **The hypothesis is
confirmed** — Track B collapses the fragmentation, and dramatically. Part1
likewise: μ 82 → 5.

**The lesson is about the test, not the code.** Measuring at `+Z` was
measuring a direction where Part3 is largely zero-draft, so the "silhouette"
is a wide degenerate band rather than a curve. A parting-line result quoted
without its direction is close to meaningless — B-5, biting a second time, on
me.

### B-14 — μ collapse makes full enumeration tractable ⭐

This is the most consequential number for P3. After Track B, at optimal
directions:

| part | μ before (P1) | μ after (P2) |
|---|---|---|
| Part1 | 82 | **5** |
| Part3 | 110 | **3** |

§6.1's build-order gate asks whether `μ` is small enough that Johnson
enumeration is affordable. At `μ = 3` and `μ = 5` it is trivially so. Track B
did not only find curves — **it collapsed the combinatorics**, which no amount
of better search on the old candidate set could have done.

### B-15 — Both real parts still have no feasible candidate, and why

Part1 at optimal: 5 candidates, **all rejected at H4**. Part3 at optimal: 6
candidates, **all rejected at H3**.

This is the documented Level-1 limitation, now isolated: a fundamental cycle
**basis** spans the cycle space, but its members are not necessarily the
physically meaningful loops — the real loop can be a *sum* of basis cycles.
With μ now 3–5, enumerating every simple cycle is cheap. That is P3's job and
it is now clearly the right next step, chosen on evidence rather than
assumption.

F11 (`μ = 25`, all 25 rejected at H4) is the same limitation on a synthetic
fixture.

### B-16 — H0 still holds with face-backed curves

Worst `|g|` on any candidate curve after the seam fix: **3.6e-12** (Part1),
**1.3e-10** (Part3), against `τ_silhouette = 0.002`. `off_face_point_count`
is 0 everywhere — the `FClass2d` trimming does stop marching squares escaping
onto the untrimmed surface.

### B-17 — Runtime regressed substantially, and is not yet optimized

p50 31.9 ms → **67.1 ms**; Part1 4.7 s → **24.6 s**; Part3 11.9 s → **44.4 s**.

Track B evaluates `GeomLProp_SLProps` per grid node per face. **No
optimization attempted**, per §12.5 rule 2 — the corpus profile has not been
taken yet, and the coarse pre-pass already rejects most faces. Recorded as the
number P3 must not worsen.

---

## M-P1 — Level 0 measured, 2026-08-09

`reports/p1_level0.json`. Synthetic fixtures at their declared direction;
`Part1`/`Part3` at `+Z`.

| id | fixture | outcome | μ | branch | cand | coverage | H0 dev (mm) | tier |
|---|---|---|---|---|---|---|---|---|
| F1 | cube | feasible | 5 | 8 | 5 | 100.0% | 0.0 | **T7** |
| F2 | cylinder ∥ pull | feasible | 2 | 0 | 2 | 99.4% | 3.7e-15 | T7 |
| F3 | cylinder ⟂ pull | **no_feasible_candidate** | 0 | 0 | 0 | — | — | — |
| F4 | sphere | **no_feasible_candidate** | 0 | 0 | 0 | — | — | — |
| F5 | cone | feasible | 1 | 0 | 1 | 99.4% | 4.9e-15 | sole |
| F6 | filleted box | feasible | 5 | 8 | 5 | 99.1% | 0.0 | T7 |
| F7 | spline lid | feasible | 1 | 0 | 1 | 100.0% | 0.0 | sole |
| F8 | box + boss | feasible | 7 | 8 | 7 | 100.0% | 0.0 | T7 |
| F9 | box + hole | feasible | 7 | 8 | 7 | **107.6%** | 1.5e-15 | T7 |
| F10 | T-junction rib | feasible | 9 | 16 | 9 | 100.0% | 0.0 | T3 |
| F11 | alternating pockets | **no_feasible_candidate** | 25 | 40 | 25 | — | — | — |
| F12 | draft-free rib | feasible | 10 | 16 | 10 | 100.0% | 0.0 | T7 |
| F13 | peanut | feasible | 5 | 8 | 5 | 99.5% | 1.3e-14 | T3 |
| F14 | mirror-symmetric | feasible | 9 | 8 | 9 | 100.0% | 0.0 | T7 |
| F17 | barrel (Track B) | **no_feasible_candidate** | 0 | 0 | 0 | — | — | — |
| F15 | Part1 @ +Z | feasible | 82 | 136 | 82 | 99.8% | 2.5e-15 | sole |
| F16 | Part3 @ +Z | **no_feasible_candidate** | 110 | 184 | 110 | — | — | — |

Runtime **p50 31.9 ms, p95 4734 ms, max 11898 ms**.

### B-7 — H0 holds to floating-point noise ⭐

Maximum deviation from the B-Rep across the entire corpus: **1.3 × 10⁻¹⁴ mm**.
Points come from `BRepAdaptor_Curve.Value(t)`, so the curve is on the part by
construction rather than by hope. v1 cannot make this claim at all — its
displayed curve is unconstrained Chaikin output with no backing to measure
against (audit RC-7).

### B-8 — The fail-loudly criterion is met, and it is the headline

**F3, F4, F17 report `no_feasible_candidate` with a stated reason.** At P0 the
equivalent v1 runs returned **`status = ok`** with 0.0% coverage on the same
shapes. That difference — between "I cannot see this" and a confident wrong
answer — is the whole justification for separating feasibility from scoring.

### B-9 — Three fixture expectations were wrong, and why

F5, F6 and F7 were predicted to need Track B. **They do not**, and the reason
matters more than the correction: the a-priori error was assuming *"has curved
faces"* ⇒ *"needs Track B"*. The real criterion is whether **`g` changes sign
inside a face**.

- **F6**: the top fillets span `g ∈ [0, 1]` — from the vertical wall to the
  horizontal top. They *touch* zero at the fillet/wall edge and never cross
  it internally, so Track A finds that edge.
- **F7**: all five lofted faces have `g_centroid ∈ [0.33, 0.44]`, strictly
  positive — a monotone inward slope with no sign change anywhere.

Consequence: **no fixture in the original corpus actually exercised Track B's
marching-squares path.** F17 (a lofted barrel, `min_g = −0.47`,
`max_g = +0.47` on one BSpline face) was added to close that gap. Without it,
P2 would have had no real test to pass.

### B-10 — P3a's `μ` data is arriving early, and it already says something

`μ = 25` on F11 and **`μ = 110` on Part3** — substantial mass well above
`mu_max_for_johnson = 12`. Both fail overwhelmingly at **H4** (F11: 25/25;
Part3: 151 H4 + 14 H3), which is the documented Level-0 limitation: a
fundamental cycle **basis** spans the cycle space but its members are not
necessarily the physically meaningful loops — the real loop can be a *sum* of
basis cycles.

This is precisely the case P3's enumeration would address, and the numbers
already suggest Johnson would be exponential at `μ = 110`, so beam search is
the likelier answer. **Not built yet** — §6.1's gate requires the full corpus
distribution first.

### B-11 — Runtime, stated carefully

p50 **31.9 ms** vs v1's **3772 ms**. This is **not** a like-for-like
comparison and must not be quoted as one: v2 does not build a parting surface,
which is where v1 spends 96.6% of its time (B-4). The honest statement is that
v2's candidate generation, filtering and ranking together cost ~30 ms on
typical fixtures, and that no optimization has been attempted.

---

## M-P0 — The Level-0 baseline, measured 2026-08-09

Command:

```
.micromamba/root/envs/dfm_agent/bin/python -m backend.validation.parting_line_ab \
    --engine v1 --json reports/baseline_p0.json
```

Corpus: 14 synthetic fixtures at their declared pull direction + `Part1.stp` /
`Part3.stp` at `+Z`, then the two real parts again with `--optimize`.
Raw data: `reports/baseline_p0.json`, `reports/baseline_p0_optimized.json`.

| id | fixture | closed | comps | bbox cov | parting surface | ms |
|---|---|---|---|---|---|---|
| F1 | cube | True | 1 | 100.0% | **failed** | 5705 |
| F2 | cylinder ∥ pull | **False** | 1 | **0.0%** | failed | 77 |
| F3 | cylinder ⟂ pull | **False** | 1 | **0.0%** | failed | 62 |
| F4 | sphere | **False** | 1 | **0.0%** | failed | 60 |
| F5 | cone | **False** | 1 | **0.0%** | failed | 5 |
| F6 | filleted box | True | 1 | 100.0% | generated_filling | 7849 |
| F7 | spline lid | True | 1 | 100.0% | generated_planar | 9742 |
| F8 | box + boss | True | 2 | 100.0% | generated_filling | 3527 |
| F9 | box + hole | True | 2 | 100.0% | generated_filling | 3498 |
| F10 | T-junction rib | True | 1 | 100.0% | generated_filling | 9394 |
| F11 | alternating pockets | True | 5 | 100.0% | failed | 692 |
| F12 | draft-free rib | True | 2 | 100.0% | generated_filling | 7078 |
| F13 | peanut | True | 1 | **2.1%** | generated_filling | 6205 |
| F15 | Part1 @ +Z | True | 7 | **4.1%** | generated_planar | 11061 |
| F15 | **Part1 @ optimal** | True | 12 | **94.8%** | generated_filling | 17899 |
| F16 | Part3 @ +Z | True | 15 | **0.2%** | generated_filling | 3651 |
| F16 | **Part3 @ optimal** | True | 22 | **18.1%** | generated_filling | 18818 |

Runtime across the 16 fixed-direction runs: **p50 3772 ms, p95 9742 ms, max
11061 ms.**

### B-1 — The harness is trustworthy

Part1 at its optimal direction reproduces **94.8% coverage / 12 components**
and Part3 reproduces **18.1% / 22 components** — matching `STATUS.md`'s
published figures exactly. The baseline table can be trusted as a reference.

### B-2 — Track A's blindness is confirmed empirically ⭐

**F2, F3, F4, F5 all produce `closed=False`, coverage `0.0%`, surface
`failed`.** These are exactly the four fixtures whose silhouette lives in a
face interior. Audit RC-1/RC-2 predicted this from reading the code; it is now
*measured* on geometry with known analytic answers.

F3 is the cleanest proof: the correct answer is **two straight rulings at
`u = φ ± π/2`** on the lateral cylinder plus two end-cap arcs. v1 finds
nothing usable, because those rulings are interior isoparametric curves rather
than B-Rep edges.

### B-3 — v1 does not fail loudly; it returns confident garbage ⭐

Every one of F2–F5 returned **`status = ok`**. Not an error, not a rejection —
a result. This is audit RC-4 (feasibility fused into scoring, nothing ever
rejected) reproduced on demand in four independent cases.

**This is the single strongest justification for the H0–H7 hard filter.** A
pipeline that cannot say "no valid parting line exists here" will say
something else instead, and what it says will look like an answer.

### B-4 — 96.6% of runtime is spent on a surface that then fails ⭐

Profiled on F1 (a **six-face cube**, total 5.66 s):

```
  5.457 s  (96.6%)   BRepFill_Filling_Build          ← and it FAILS
  0.164 s   (2.9%)   _refine_selected_wire
  ...
  raw wire points:        9
  resampled:             96
  after Chaikin x8:  24,321        ← 2,702x inflation of a 4-corner square
```

A cube's parting loop is four segments. v1 smooths it to 24,321 points,
decimates back to 120 constraint edges, spends 5.4 s in `BRepFill_Filling`,
and the surface **fails anyway**. RC-6 and RC-7 in one measurement.

Note this is not merely slow — the smoothing is what makes the loop non-planar
enough to miss the fast planar path. The raw four-corner loop is exactly
planar and perpendicular to `d̂`.

**Nothing is optimized on the strength of this yet** (plan §12.5 rule 2:
never optimize a stage the corpus profile did not identify). It is recorded so
P2 has a number to beat.

### B-5 — Enormous sensitivity to pull direction ⭐

| part | at `+Z` | at optimal |
|---|---|---|
| Part1 | **4.1%** coverage, 7 components | **94.8%**, 12 components |
| Part3 | **0.2%** coverage, 15 components | **18.1%**, 22 components |

A 23× swing on Part1 from changing only the input direction. This is the first
hard evidence for plan §12.6's sensitivity analysis, and it reframes it: a
parting-line result quoted **without** its direction is close to meaningless.

It also means every fixture's declared direction is part of its ground truth,
not a convenience — which is why the harness refuses to override a synthetic
fixture's declared direction even under `--optimize`.

### B-6 — Component count is the metric to watch in P2

Baseline fragmentation: F11 = 5, Part1 = 12, Part3 = 22 components.
Plan P2's exit gate makes Part3's number the falsifiable test: if Track B does
**not** collapse it sharply, the RC-1 hypothesis is wrong and we stop and
re-diagnose rather than adding machinery.

---

# Algorithms implemented

*(none yet — P0 is contracts, fixtures, and harness only; the first algorithm
lands in P1)*

---

# Superseded decisions

*(none yet)*
