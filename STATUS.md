# Project Status — DfM Agent

> **Last updated**: 2026-08-15
> **Update this file after every change session.**
>
> **Master plan**: `docs/ARCHITECTURE_ROADMAP.md` — phased specification with
> algorithms, config keys, and per-milestone validation gates.
> Execution checklist: `TODO.md`. Change history: `CHANGELOG.md`.
> Engine correctness review: `docs/ENGINE_AUDIT_2026-07-27.md` +
> `docs/RECOVERY_PLAN.md`.

## Headline

**D-044 — Secondary-action delegation implemented (2026-08-15).** H4 tests
whether the geometry expected to move with the primary mould direction is
orientation-consistent — not whether the whole part has zero undercuts. An
explicitly authorized `DelegatedSecondaryAction` (face ids + movement
direction + evidence) is independently re-validated per candidate and per
pull direction (`regions.validate_delegation`): provenance present, valid
non-parallel movement direction, disjoint from the candidate's real
parting line, and — the one structural sanity check — a connected face
set. Passing proves only structural self-consistency; `evidence.
geometric_verification` stays `"unverified"`, the only legal value, since
no geometric release/sweep verification exists in this codebase (D-042
already showed the one candidate mechanism is unreliable for this class of
geometry). A genuine discovery surfaced *while writing the tests*, not
hypothesized in advance: authoring ONE delegation record spanning Part3's
entire rib lattice (both mirror stacks) was correctly REJECTED by the
connectedness check, because the two stacks are not adjacent to each
other — splitting into two per-stack records, each independently
connected, both validate. End-to-end on the real, unforced production
pipeline: `analyse_parting_line(Part3, +Z, core_pin_face_refs=(bore,),
delegations=(stack1, stack2))` — the real Round-1-discovered `z=4.0`
candidate drops from `h4=7.56%` to `h4=0.499%` (34 faces delegated) and
**passes**, while the other two real core-pin candidates (`z=1.0`,
`z=31.43`) receive the identical delegation and remain correctly rejected
at H4 — nothing tuned or additionally masked. H5, `detect_undercuts`, and
ranking all independently re-verified unaffected. Full existing suite (152
tests) re-verified byte-identical; 16 new tests cover the complete frozen
case matrix. Full detail: D-044.

**D-043 — Core-pin / tooling-split mechanism implemented (2026-08-15).** A
face exactly coaxial with the pull direction (e.g. Part3's central bore,
`g ≡ 0` across its entire length) has no B-Rep boundary or Track-B crossing
anywhere between its two ends, so no candidate loop could previously be
closed by cutting through it — every Z-primary candidate was structurally
forced to the part's extremities (base flange or top cap). Implemented as
non-geometric H3 partition metadata (`PartingLoopCandidate.
tooling_split_face_ids`), deliberately NOT a new curve on the real parting
line — a `ToolingBacking` segment design was built, stress-tested, and
rejected after tracing `ranking.py`'s coverage/length measures and plan
§9.5's "real parting line" invariant. Bridge localization (deterministic
articulation-point analysis) is kept strictly separate from the independent
geometric eligibility gate (cylindrical, axis-aligned, uniformly zero-draft
over the WHOLE face via a dedicated config key never shared with H4,
exactly 2 neighbours) — verified this excludes the alternating-radius rib
lattice on the neighbour-count criterion specifically, not on g-uniformity,
which those faces also individually satisfy. Full existing test suite (139
tests) re-verified byte-identical with the new mechanism unused (default);
13 new tests cover the positive/negative/causality matrix. End-to-end on
the real production pipeline: closes 3 independently-discovered Part3 +Z
candidates via the tooling split, all still separately and correctly
rejected at H4 (the pre-existing orientation-consistency gap, deliberately
untouched by this milestone). Full detail: D-043.

**P3.11 — Fresh independent separation test confirms H3 correctness on
every candidate examined; self-corrected a false discrepancy mid-
investigation; alternative-loop search came back negative
(2026-08-13, D-037).** Built a from-scratch separation test (own sign
computation via direct GeomLProp calls, own adjacency, own components --
does not import `regions.py` at all), validated on Part1 +Z (mandatory
gate: correctly scores S2, matches production exactly). Applying it to
the 5 requested Part3 directions initially found what looked like a
smoking-gun discrepancy on `+Y` (production said region_count=3, the
independent test said 2/S2) — traced in full and found to be **a bug in
the diagnostic script itself**, not production: the test's first version
silently dropped isolated split-face half-nodes that production
correctly creates and counts. Fixed to match production's own
node-construction discipline; re-validated Part1 +Z still passes; re-ran
all 5 directions and got **100% agreement with production on every one**
(all S0/non-separating, matching H3 exactly). Searched for an
alternative single-loop S2 candidate at `grid(az15)` via fundamental
cycle-basis XOR combinations (62 basis cycles, µ~98 makes exhaustive
enumeration intractable) — 2 of 62 combinations scored S2, but both
traced to be disjoint unions of two separate closed loops (failing
single-curve continuity), not genuine single continuous curves — same
already-established "loop_union" pattern, would fail H1 before reaching
H3. Bypass geometry characterized: small local boss/fillet faces
(0.81-63mm2 vs ~9000mm2 total), consistent with the already-established
mechanism. **No CASE B or CASE E evidence found anywhere this entry.**
Full detail: D-037.

**P3.10 — 374-direction spherical search finds new territory (the
z=0 equatorial band) with the largest genuine candidates in the whole
investigation, but still CASE C, not CASE D (2026-08-13, D-036).**
Systematic 15°×15° grid (374 total directions incl. the prior 108) using
a cheap pre-filter (raw-graph `largest_component_fraction` +
`non_trivial_mu`), calibrated on Part1 first (+Z ranks #1 at 0.899, but
the metric is a ranking signal not a binary classifier — all 12 Part1
directions have substantial raw cyclic content). **Result: the entire
z=0 equatorial band scores far above anything tested before** (0.87–0.90,
vs. 0.23–0.76 elsewhere) — genuinely new territory, not overlapping the
prior 108 directions. Deep-verified 10 diverse points across this band:
production builds 277–325 candidates each (an order of magnitude more
than before), but **all 10: zero valid candidates**. Traced the two
largest candidates found in the whole investigation: a 126-segment,
91.7%-bbox "candidate" turned out to be 2 disconnected sub-loops
artificially unioned (43.9mm closure gap); a genuine single 120-segment,
**73.0%-bbox, exactly-closed** loop (the largest true single loop found
anywhere in P3.x) still fails H3 — BFS-traced a real, short **9-hop**
bypass path elsewhere in the part. Same "uncovered-edge bypass"
mechanism as D-027/D-028/D-034, now confirmed at a scale far beyond
anything previously tested. **Classification: CASE C** (production
builds real candidates, H3 correctly, justifiably rejects them) for all
10 directions deep-verified. **Still no Part3 positive control** — but
364 of 374 directions remain undeep-verified; this is expanded, not
concluded, territory. Full detail: D-036.

**P3.9 — CASE 1 CONFIRMED: independent, candidate-generation-agnostic
search finds NO global zero-level loop anywhere in Part3's CASE-A
geometry (2026-08-13, D-035).** Direct follow-up to D-034. Built the raw
(pre-2-core) graph via Track A/B + `build_graph` (legitimate reuse — not
candidate generation), then searched for ALL cyclic structure
independently of `extract_loops`/cycle_basis/Johnson/H3/H4: self-loops,
parallel-edge 2-cycles, and longer simple cycles via `networkx.
simple_cycles`. For the strongest CASE-A direction: 64 components,
largest only 6.4% of nodes, total cyclomatic number **3** — all 3 trivial
self-loops, zero longer cycles anywhere. **Exactly reconciles with
production's own `candidate_count=7`** (3 self-loops + 4
`_subset_unions` combinations) — independent confirmation candidate
generation isn't missing anything. Repeated on 3 more CASE-A directions:
identical signature (60-75 components, largest 5.7-7.7%, minimal cyclic
content). Part1 +Z golden control, for contrast: **one dominant
component holding 90% of all nodes**, rich cyclic structure (µ=113,
exactly matching D-026's independently-recorded 113 candidates — a strong
cross-check). **Classification: CASE 1** — "no physically valid global
zero-level loop exists for this direction." Not a candidate-generation
defect (confirmed by an independently-implemented search agreeing exactly
with production) and not an H3/H4 defect (nothing meaningful survives to
be mis-validated). D-033's "plausible" face-sign partition is real, but
does NOT correspond to an actual continuous separating curve — the two
dominant regions exist, but the boundary between them is scattered,
disconnected fragments with genuine same-sign gaps, not one loop. Full
detail: D-035.

**P3.8 — Forensic trace of the bore CASE-A candidate closes with NO
demonstrated code defect; F3 control disproves the leading hypothesis
(2026-08-13, D-034).** Full read-only trace of D-033's finding. Edge 112
("missing") is confirmed a correctly-skipped seam artifact (both sides are
face 35 itself). Track A's partial rim coverage on edges 111/113/114 is
confirmed geometrically CORRECT, not a bug: the neighboring cone faces
320/319 have robust, unambiguous sign (g=+0.57/-0.57 — nowhere near
zero-draft), so the uncovered rim arcs are genuine same-sign regions with
nothing to detect. Hand-chained the 6 relevant segments into a properly
ordered, nearly-closed loop (0.000993mm gap, the same ~14x weld-tolerance
shortfall already flagged in D-033) and confirmed even force-closing it
still gives `region_count=1` — the uncovered rim arcs remain a live
bypass in the separating graph, the SAME mechanism already established
in D-027/D-028, now confirmed on a major feature (the bore) instead of a
small torus. **F3 control is decisive**: F3's own full rim coverage comes
from its end caps being EXACTLY zero-draft at the test direction (a
deliberately engineered degenerate case) — Part3's cone faces are
confirmed NOT degenerate, so F3's success mechanism doesn't apply and
doesn't imply a fixable gap here. **No production change proposed** — per
explicit instruction, no fix is produced for something not demonstrated
to be broken. High confidence no code-level defect exists in Track A/B,
stitching, or graph construction for this feature; open question (as for
the earlier torus features) is whether a longer path elsewhere in the
part could still complete the true global boundary. Full detail: D-034.

**P3.7 — Independent (non-cycle, non-H3/H4) separability diagnostic
built and validated on 11 controls; finds 11 CASE-A directions on Part3,
all the SAME feature (the main bore) — strongest hypothesis-B evidence
yet, but not a resolved fix (2026-08-13, D-033).** Built a diagnostic
using ONLY `face_adjacency`+`signed_dot` (no Track A/B, no cycles, no
H3/H4): cuts the whole B-Rep everywhere sign(g) flips (the maximal
possible cut) and checks if it collapses to ~2 dominant regions. Found
and fixed a real antisymmetry bug (92 of 414 Part3 faces have g exactly
0.0 at ±Z; a naive `>=0` rule broke +Z/-Z mirror symmetry) and redesigned
after a first attempt failed its own validation (fragmented cavity/core
area isn't itself bad — D-028 already established many small same-side
patches are normal). Validated on 11 known controls (Part1 +Z/-Z/±X/±Y/
diagonals, ADV1, ADV2) with zero mismatches and a large unforced gap
(0.484 negative-max vs 0.818 positive-min). Applied to all 108
already-tested Part3 directions: 12 canonical are all CASE B (diagnostic
agrees no split exists); of 96 swept, **11 are CASE A** (diagnostic says
plausible, PL engine finds zero valid candidates) — all 11 touch the SAME
feature: face 35, Part3's main central bore (not a small torus this
time). Traced in full: Track A/B correctly detect the bore's silhouette
(two classic cylinder rulings + rim arcs); hand-chaining shows a real,
tiny (~14x) weld-tolerance gap causing an H1 near-miss — but even with
the loop manually force-closed, H3 still fails, because the assembled
candidate covers only PART of the bore's rim edges (same partial-coverage
mechanism as D-027/D-028, now shown on a major feature, not just small
bosses). Two distinct, separately-real issues correctly not conflated: a
small fixable weld-tolerance gap (insufficient alone), and a larger,
not-yet-root-caused candidate-completeness gap (the actual blocker).
**No fix proposed yet** — the completeness gap itself needs tracing first,
per the explicit "identify the exact stage" requirement. This is the
strongest evidence for hypothesis B found in the whole investigation, but
deliberately not reported as resolved. Full detail: D-033.

**P3.6 — Direction calibration + 96-direction fine sweep: no Part3
positive control found; algorithm stays frozen (2026-08-13, D-032).**
Phase A: calibrated a geometrically-explainable direction metric against
Part1's ground truth — **near-zero-draft region CONNECTIVITY (fraction of
area in the single largest connected patch via `part.face_adjacency`), not
raw area**. Part1 +Z/-Z score 0.988 (near-total coherence), the unique
maximum among Part1's 12 directions and sharply above every failing one
(0.79-0.89, down to 0.23). Part3's best canonical direction by this
corrected metric is +Y/-Y (0.857, still below Part1's 0.988, already known
to fail). Phase B/C: documented 96-direction fine sweep (±5°/10°/15°, 8
azimuths) around all 4 required diagonal anchors, every direction run
independently through the frozen pipeline — **zero valid candidates across
2,030 total raw candidates generated.** Phase D: closest analog to Part1's
distinguishing `h3_failures=0` signature found and traced in full — it is
NOT a genuine global candidate, just a small raw pool where every member is
either an H0 failure or the same single-torus-face pinch (34% H4
violation) found at every other direction since D-028. Phase E: every
quasi-plausible candidate in the sweep falls into the same bucket (H3
pass/H4 reject on a trivial local pinch) — no new failure mode. Phase F:
**algorithm stays frozen**; evidence continues to weight toward "no
feasible direction in the space searched so far" without proving it — the
sweep covers only tight neighborhoods of 4 diagonals, not Bosch's full
stated practical space. Full detail: D-032.

**P3.5 — Second adversarial fixture (Track-B-required global answer)
also CASE E; direction-validation table merged from existing data
(2026-08-13, D-031).** Closes D-030's one open gap: a sphere (known
closed-form answer = the great circle z=0, entirely Track-B, no usable
edges) plus 6 misaligned bosses reproduces D-030's result exactly —
correct answer found (`FaceBacking face_id=1`, z/radius exactly [0,0]/
[20,20], zero deviation), passes every gate, selected. A real fixture-
construction bug (curved-surface tangent union corrupting the sphere face)
was found and fixed along the way — recorded honestly, not swept under
the rug. One new, separate, honestly-reported finding: `RegionClassification`'s
`cavity_area_mm2`/`core_area_mm2` fields show an attribution asymmetry for
a Track-B **split** face (100% lands on one side) — does NOT affect H3/H4
(which use the correct graph-based `component_count`), isolated to the
reporting layer, not fixed here. Both adversarial combinations tested
(Track-A-only global answer, Track-B-only global answer) survive heavy
local-feature noise cleanly. Full detail: D-031.

**P3.4 — DECISIVE: synthetic adversarial fixture proves the algorithm
correctly recovers a known global loop through heavy local-feature noise —
CASE E, algorithm cleared (2026-08-13, D-030).** Built a fixture designed
to fail: a 60×50×40mm box (known-correct hexagonal global parting line at
d=(1,1,1), provable in closed form, zero free parameters) plus 6 bosses
misaligned with the pull direction, deliberately reproducing Part3's
local-feature-dominated-graph structure (D-028/D-029). Ran the exact
unmodified production pipeline. Result: Track A/B correctly detect 30
local-feature segments beyond the true 6-edge hexagon; NONE spuriously
close into false cycles; 2-core correctly prunes all 30 as non-cyclic tree
material; **exactly 1 candidate is generated — the correct hexagon — and
it passes every gate (H0-H7) cleanly**; `cavity_area_mm2 == core_area_mm2
== 7467.56` exactly (independently confirms correctness — a diagonal cube
cut is point-symmetric, so exact equality is the mathematically expected
result, not luck); each boss correctly inherits its parent face's mold
side. **Recommendation: A — keep the algorithm frozen, Part3's failure is
substantially more likely a direction/geometry-specific issue than an
architectural defect.** Per the protocol's own explicit gating, Part3 is
NOT revisited/modified this entry, since no evidence of algorithmic
weakness was found to chase. Full detail: D-030.

**P3.3 — Direction-feasibility vs. algorithm-correctness separated
(2026-08-13, D-029).** Built a direction-only diagnostic layer (reuses
`analyze_draft`/`detect_undercuts`, no new score) and ranked all 12 Part1 +
24 Part3 directions BEFORE consulting parting-line outcome, to avoid
"the algorithm liked this direction, therefore it's good" circularity.
Found the naive near-zero-area ranking is anti-correlated with ground
truth on Part1 (+Z ranks last, 71.7% near-zero, yet is the ONLY working
direction) — reported honestly, not retrofitted. For Part3, it flags
**(1,0,1)/(1,0,-1)** as far more promising than **(0,1,1)** (the direction
D-027/D-028's whole investigation focused on purely because it produced
the largest-looking candidate — exactly the circularity this step exists
to catch). Full candidate audit at both new directions found **the
identical structural pattern D-028 found at (0,1,1)**: torus-boss "pinch"
loops passing H3 but rejected by H4 at 34.2-34.3% orientation violation
(near-identical across all 3 directions), or local rings failing H3
outright. Cross-checked against the full D-026 24-direction table: Part1
@ +Z/-Z is the ONLY Part1 direction with `h3_failures=0`; no Part3
direction, of 24 tested, ever reaches that. Added the previously-missing
Part1 +Z regression test for the v2 engine (3 new tests, all pass) and
confirmed the existing 15-fixture analytic positive-control suite (F1-F17)
still passes 136/136. Classification: **closest to E (insufficient
evidence to fully separate hypotheses A/B)**, with a specific evidenced
lean toward A — Part3's candidate pool is local-feature-dominated at every
one of 24 tested directions, unlike Part1's uniformly-separating pool at
+Z — but no synthetic fixture yet proves this isn't also an algorithm
limitation, so B is not ruled out. Full detail: D-029.

**P3.2 — Part3 @ (0,1,1) fully explained; D-027's "2-core pruning" causal
claim retracted and corrected by D-028 same day (2026-08-13).** A direct
bypass experiment (run `extract_loops` on the raw graph, skip
`reduce_to_two_core` entirely) produced the **exact same 11 candidates,
same segment IDs** — proving 2-core reduction is mathematically exact and
loses nothing (a degree-1 node's removal is never part of any cycle by
construction; verified with 0 invariant violations across Part3 @ (0,1,1)
and Part1 @ +Z/+X/+Y). The real picture, evidenced end-to-end: Part3's 242
"lost" segments belong to dozens of small local features (mirror-symmetric
stepped-cylinder bosses with toroidal fillets) whose own silhouette
genuinely does not close into a loop at this oblique direction — not a
defect. Of the loops that DO close, 5 (`loops 4-8`) trivially pinch off
**one single face** from the other 413 (`region_sizes=[1, 413]`) — H3
correctly passes them (region_count=2), **H4 correctly rejects them**
(34% orientation violation: "the rest of the part" isn't a real mold half).
Group 1 (the torus equatorial ring) is genuine and non-trivial but is
itself a local-feature loop that never reaches the main body. **The graph,
2-core reduction, H3, and H4 are all behaving correctly.** What's missing
is genuinely global, main-body-spanning structure — not a bug to fix, but
evidence the candidate pool should distinguish local-feature loops from
global-body loops before scoring (ties to this project's own
`side_core.py`/Bosch-criterion-#5 machinery, which already exists to
handle local-feature tooling separately). Part1 @ +Z (known-good): 0
segments pruned at all. Part1 @ ±X/±Y (known-bad): same mechanism present,
~6% severity vs Part3's 85% — consistent with severity tracking distance
from a moldable direction, not a fixed defect. No production code changed;
8 fix options evaluated and NOT implemented (see D-028's table) — best
supported: classify local-feature vs main-body geometry before H3/H4
scoring, not a 2-core/graph change. Full detail:
`docs/DECISIONS_AND_ALGORITHMS.md` D-028 (supersedes D-027, which is
retained in the log for the record but its causal claim is retracted).

**P3.1 — Level 0-2 parting-line algorithm FROZEN (2026-08-12, D-026).** Full
24-combo baseline matrix (6 principal ±X/±Y/±Z + 6 diagonal directions ×
Part1/Part3, unmodified pipeline, manual directions only): **Part1 feasible
only at +Z/-Z (2/12); Part3 feasible at none of 24 tested directions.**
Convergent evidence this phase (enumeration comparison, envelope experiment,
H4 backward trace, this matrix) shows no specific fixable defect in Track
A/B, graph construction, H3, or H4 — see D-026. **Superseded for Part3 by
D-027 above**, which found a specific, evidenced defect (2-core pruning) that
this matrix's methodology could not have surfaced (it only tested
whole-candidate pass/fail, not fragment-level graph survival). Full detail
below and in `docs/DECISIONS_AND_ALGORITHMS.md` D-022 through D-026.

**P3.1 earlier work (direction-isolated connectivity diagnosis):**
Full detail: `docs/DECISIONS_AND_ALGORITHMS.md` D-022 through D-025. Honest
current status, so nothing below is mistaken for "done":

- **Mechanism 2 (D-025): diagnosed AND semantically fixed.** Face 317's
  boundary-following contour is a genuine tangential/zero-draft condition
  (edge 52, a full circle, is tangential across its entire length per
  Track A's own test) — not a stitching defect, not unique/mergeable.
  Track B now labels such segments `"tangential"` instead of `"silhouette"`,
  reusing Track A's exact classification test (two Track-B-native rules were
  tried and measured NOT to work first — see D-025). Zero effect on
  candidate counts/H0/H3/H4/outcome, confirmed by direct measurement — this
  was a labeling fix, not a behavioral one. F3/F4/F17 controls unaffected.

- **Direction contamination audit (D-022)**: P2/P3's real-part evidence was
  partly measured at the (unvalidated) upstream optimizer's direction.
  Re-measured at explicit controlled directions only from here forward.
  New fact this surfaced: **Part1 is already `feasible` at +Z** (0 pruned
  segments) — the optimizer-direction evidence alone never showed this.
- **Mechanism 1 — Track-B boundary refinement (D-023): implemented, real
  but incomplete.** Fixes a genuine defect (contour stopped short of the
  true trim boundary by 0.046–0.14 mm). Measured, positive connectivity
  effect on Part3 (+X: 66→60 pruned segments, 4→3 components after 2-core;
  +Y: 69→61 pruned, 5→4 components). **Does NOT make Part1 or Part3
  `feasible`, and does NOT fix the 4 H0 failures it was traced to** — do
  not cite this as "the H0 fix." Whole-suite runtime roughly doubled
  (379s→849s); not yet optimized.
- **H0.3 projection discrepancy (D-024): root-caused AND FIXED.**
  `GeomAPI_ProjectPointOnSurf`'s default construction searched only the
  surface's own declared `Bounds()` ([0,1]×[0,1]), not the face's real trim
  extent — Part3 face 274's trim wire genuinely reaches `v=1.0121`, ~1.2%
  past `Bounds()`. Confirmed with a control (F17, F3 fixtures: same check,
  `<1e-9 mm` deviation) — not generic OCC behavior. **Fixed**: `gates.py`'s
  H0.3 check now passes the face's real `breptools.UVBounds()` explicitly.
  Verified: all 4 H0 failures at Part3 +X and all 4 at +Y are gone (0/329,
  0/325); the same candidates are now correctly rejected at H3/H4 instead
  (candidate counts unchanged) — H0 passing is necessary, not sufficient.
  Controls (F4/F17/F3) unchanged. Does **not** make Part3 `feasible` — never
  expected to.
- **Mechanism 2 (face-317-style, 24.75 mm Track-A/B mismatch on a
  near-zero-draft boundary): still open, not investigated further.** Not
  established as a bug — may be a genuine case where both tracks are
  individually valid on an ambiguous boundary.
- **The direction optimizer remains an external dependency of this
  subsystem, not part of it.** `parting_line_v2` only ever consumes an
  explicitly-supplied `PullDirectionInput`; nothing in this investigation
  changed that boundary (enforced by
  `test_no_module_imports_the_direction_optimizer`).

Regression suite is clean throughout this work: 477 passed (+2 new tests
for D-024) / 4 skipped / 3 failed, and all 3 failures are pre-existing and
unrelated (2× missing `OPENAI_API_KEY`, 1× the already-documented Part1
6-piece side-core fragmentation) — confirmed unchanged before and after
every change made in this investigation.

---

**Parting-line / core-cavity rebuild started (P0 done, 2026-08-09).** An audit
of the two modules this sub-team owns — `docs/PARTING_LINE_CORE_CAVITY_AUDIT.md`
— found 11 root causes, the deepest being that **silhouette candidates are
restricted to B-Rep edges and classified by a single normal sample per face**
(`FaceData.normal` is the normal at the UV centroid). On any part whose parting
line crosses a curved face, the true answer is therefore never generated.
`docs/PARTING_LINE_ALGORITHM_PLAN.md` specifies the replacement through Levels
0–2; `docs/DECISIONS_AND_ALGORITHMS.md` logs every decision and algorithm with
its mathematics and its reason.

**P3 done (2026-08-09): measure-then-build — and a decisive negative result.**
Corpus grown to **22 parts** (15 synthetic + Part1/Part3 + **5 external
models**), all profiled at their **optimal** direction. **Zero crashes.**

§6.1's build-order gate ran exactly as written: P3a measured the μ
distribution (`2 ≤ μ ≤ 12` on **77.3%** of parts), which justified building
bounded Johnson and **not** beam search. P3b then measured what Johnson
bought: **zero outcome changes across the entire corpus**, at up to 22× the
candidates and 10× the runtime. The reason is structural and certain — **6 of
the 8 failing parts have `branch_node_count == 0`**, where the components
*are* the only simple cycles, so Johnson and the basis are identical there by
construction. **Enumeration is provably not the blocker.** Johnson is kept but
opt-in (`enumeration_strategy: "basis"`).

| P3 finding | measured |
|---|---|
| **The real blocker** | Segments exist but don't connect. Part1: 243 → 30 edges (**88% pruned as dangling**); Part3: 252 → 8 (**97%**). Survivors are small *local* cycles (boss rims), which is why Part1 fails H4 |
| **Gap size** | Non-welded endpoints **7e-05 – 2.4e-04 mm** vs a **3.08e-05 mm** weld tolerance — sub-micron, **numerical not geometric** |
| **`A_cauchy` error** | **+58.75%** (Part3), **+35.17%** (Part1), median **+0.24%** — measured against a rasterised tessellation union |
| **`κ_min`** | **Not calibrated.** H7 rejected nothing on any part (min coverage 0.950 of 196 candidates). Left provisional at 0.50 and documented as inert |
| **Runtime** | v2 is **11.8%** of corpus time; 88.2% is upstream `load_step` + direction optimiser. **No optimization performed** |

**Known shortfall:** the exit gate asks for ≥ 20 *external* parts; only 5 were
available. Generalisation evidence is thinner than planned.

**Next diagnosis is named, not guessed:** why sub-micron gaps remain between
silhouette segments that should meet. It is a **connectivity** problem, not an
enumeration one — and deliberately not attacked with more machinery until
diagnosed.

---

**P2 done (2026-08-09): Track B — face-interior silhouette curves.** The
silhouette is now found where it actually lives: `g(u,v) = 0` traced by
marching squares with Newton refinement, trimmed to each face's real region,
and stitched to Track A's edge curves. **16 of 17 corpus fixtures feasible**
(P1: 12). Suite **459 passed / 3 failed** (pre-existing).

| P2 result | measured |
|---|---|
| **Sphere** | great circle — `\|z\| < 1e-6`, `r = 20.000000` |
| **Barrel (BSpline)** | circle at `z = 20.0000`, `r = 16.0000`, strictly inside the face |
| **Cylinder ⟂ pull** | two rulings at `\|y\| = 15.000000`; answer needs **both tracks** (`edge: 6, face: 2`) |
| **H0 on-surface** | worst `\|g\|` **1.3e-10** vs `τ = 0.002`; `off_face = 0` everywhere |
| **Runtime** | regressed p50 31.9 → 67.1 ms, Part3 11.9 → 44.4 s. **Not optimized** — no corpus profile taken yet |

**The P2 exit gate was honoured, and it reversed the first conclusion.** The
gate said: if Part3's components do not drop sharply from 22, RC-1 is wrong and
we stop. At `+Z` they did **not** (18 → 18, μ 110 → 110, Track B found *zero*
segments). But `+Z` is not Part3's optimal direction. At its **optimal**
direction Track B finds **203** segments and components go **22 → 3**, μ
**110 → 3**; Part1's μ goes **82 → 5**. **RC-1 confirmed** — the earlier
reading was measuring a direction where Part3 is largely zero-draft.

**Consequence for P3:** with μ now 3–5, enumerating every simple cycle is
finally cheap — §6.1's build-order question is answered by data rather than
assumption. Both real parts still have no feasible candidate (Part1 5/5 fail
H4, Part3 6/6 fail H3), which is exactly the documented Level-1 limitation: a
cycle *basis* spans the cycle space but its members need not be the
physically meaningful loops.

Six defects found by measurement (D-011…D-016), including a **27% error in the
Cauchy denominator** from unweighted `(u,v)` sampling, an unimported
`BRep_Tool` whose `NameError` was silently swallowed, and a **seam
discontinuity** producing crossings with `|g| = 0.825` that H0.3 correctly
caught.

---

**P1 done (2026-08-09): Level 0 runs end-to-end.** Track A with **edge-local**
normals, scale-aware welding, 2-core reduction, cycle-basis extraction, the
full **H0–H7** hard filter, lexicographic T1–T7 ranking, and core/cavity
derived from H3's regions. v1 is untouched and remains the default
(`dfm.parting_line.engine: "v1"`). Suite: **436 passed / 3 failed**
(pre-existing, unrelated).

| P1 result | measured |
|---|---|
| **Fails loudly** | F3 (cylinder ⟂ pull), F4 (sphere), F17 (barrel) → `no_feasible_candidate` **with a stated reason**. v1 returned `status = ok` at 0.0% coverage on the same shapes |
| **H0 on-surface** | max deviation **1.3 × 10⁻¹⁴ mm** across the corpus — the curve is on the B-Rep by construction |
| **Cube analytic** | `μ = 12−8+1 = 5`, 3 rejected at H4, top and bottom rim tie on every tier → decided by **T7**. Length 160.0 mm = 4×40 |
| **Part1 @ +Z** | feasible, 99.8% coverage (v1 scores 4.1% at the same direction) |
| **Still open** | F11 (`μ=25`) and Part3 (`μ=110`) fail at H4 — a cycle *basis* does not contain every meaningful loop. Early P3a evidence; no enumeration built yet |

**Four real defects were found by measuring against fixtures with known
answers** — three implementation bugs and, notably, **one flaw in the plan's
own formal statement**: C1 required `Γ` to be a single closed curve, but a part
with a through-hole needs **outer rim ⊔ hole rim** (cutting the outer rim alone
leaves the top face connected to the bottom through the hole wall). H3 caught
it — the strongest argument for having made topological separation the primary
validity test rather than the coverage heuristic. Full mathematics for each in
`docs/DECISIONS_AND_ALGORITHMS.md` (D-005 … D-010).

**A corpus gap was found and closed**: F5/F6/F7 were predicted to need Track B
and do not, so **no fixture actually exercised it**. F17 (lofted barrel, one
BSpline face with `min_g = −0.47`, `max_g = +0.47`) was added so P2 has a real
test to pass.

---

**P0 delivered contracts, a 15-fixture synthetic corpus, and a measured
baseline — no algorithm code.** The baseline is now evidence rather than
argument:

| | measured |
|---|---|
| Harness fidelity | Reproduces `STATUS.md`'s published Part1 **94.8% / 12 components** and Part3 **18.1% / 22** exactly |
| Track A blindness | **F2/F3/F4/F5** (cylinder ∥ pull, cylinder ⟂ pull, sphere, cone) → `closed=False`, **0.0% coverage**, surface `failed` |
| v1 never rejects | All four returned **`status = ok`** — confident garbage, not an error (audit RC-4, reproduced 4×) |
| Runtime | **96.6% of a six-face cube's 5.66 s** is `BRepFill_Filling_Build`, fed a loop Chaikin inflated **9 → 24,321 points** — and the surface fails anyway |
| Direction sensitivity | Part1 scores **4.1% at +Z vs 94.8% at optimal** — a 23× swing from the input alone |

Full analysis: `docs/DECISIONS_AND_ALGORITHMS.md` §M-P0. Raw data:
`reports/baseline_p0.json`, `reports/baseline_p0_optimized.json`.

**Next: P1** — Level 0 baseline (Track A with **edge-local** normals, reusing
the existing but currently-unused `step_loader._face_normal_at_uv`), graph
reduction, and the full H0–H7 hard filter. Its acceptance criterion is that
F3/F4/F6/F7 **fail loudly** rather than returning a plausible wrong answer.

---

**The parting-line stage is fixed and honest.** The 2026-07-27 audit found it
reporting success while emitting a curve with a 17.35 mm gap, which silently
invalidated core/cavity and export. That entire chain of defects (Bugs A, B,
D, E, F, G, H, H-2, H-3) is now closed and verified against real geometry in
Docker, not just against mocks.

**Full test suite: 348 passed, 0 failed, 0 excluded** (237 + 9
`test_core_cavity.py` (Stage 2a) + 9 `check_assertions` (X.1) + 5 more
`test_core_cavity.py` (Stage 2b) + 1 `/core-cavity` direction regression
guard (S3.6) + 5 `load_step_cached` mutate-safety tests (S3.8) + 12
`test_side_core.py` (Stage 4 + S4.3) + 52 agent-layer tests (Stage 5) + 18
`test_pdf_export.py` (Stage 6), 2026-07-29) — real OCC, Docker, container
holding current source (F7 fixed the stale-image-tree problem that
previously made this number unverifiable).

**S4.3 — side-core generalized to multiple/grouped features — done.**
`backend/geometry/side_core.py` gains `generate_side_cores_for_features()`
(one side core per qualifying feature, default every "critical" one, not
just the single highest-confidence one) and `combine_side_cores_per_half()`
(fuses every feature landing in the same mold half and cuts it in ONE
combined operation, never sequential per-feature cuts). A real sizing bug
was found and fixed first: footprint sizing now uses the 75th-percentile
(not max) Bnd_Box corner radius, fixing a genuine 36.59% conservation
error on Part1's 11-face critical feature down to 0.00% (new config key
`dfm.side_core.footprint_percentile`). Two more real findings surfaced
building the STEP export gate — both are documented geometric facts, not
bugs: (1) a single feature's side core can be a multi-piece disconnected
compound (Part1 feature 0: 5 pieces); (2) nearby features' local sweep
footprints can physically overlap (Part1: ~128mm3 across 4 pairs), so
summing individual `side_core_volume_mm3` values — or exporting each as a
separate STEP body — double-counts that overlap (a first diagnostic
export measured 34639.0mm3 reloaded vs. 34508.5mm3 original, ≈0.38%
inflation, fully explained by this). Fixed by exporting AT MOST ONE
combined body per half. Re-verified end-to-end on Part1 @ (0,0,1), all 8
critical+minor features: exported `solid_count: 3`, reloaded volume
34509.99mm3 vs. original 34508.54mm3 (0.0042% error). New API query
params on `/core-cavity` and `/export/mold-halves`:
`multi_feature_side_cores`, `side_core_severities`, `side_core_max_features`
— verified live against the running Docker backend. See CHANGELOG.md
2026-07-29 for full detail.

**Stage 6 — PDF report export — done.** New `backend/report/` package
(`pdf_export.py` + `templates.py`) finally uses `reportlab`, pinned since
the initial scaffold and imported nowhere until now. Pure presentation
layer over the same `.to_dict()` payloads every analysis endpoint already
returns — recomputes nothing, and aggregates every warning/degraded-
confidence flag from every source into a top-of-report "Warnings" section
rather than dropping any for a cleaner page. Verified end-to-end via
`POST /parts/{filename}/export/report` (FastAPI TestClient) and the new
"PDF Report" frontend section (Streamlit AppTest, real click, real bytes).
Two real bugs found and fixed during verification — both were *known bug
patterns from earlier stages* the new module had silently reintroduced:
`best_label` duplicating the raw vector (the exact S3.5 bug, now guarded
the same way in `pdf_export.py`), and a misleading "100% conservation
error" shown for `side_core.status == "no_feature"` (an unset default, not
a real measurement). A genuine — and separate — robustness finding also
surfaced while re-verifying `side_core.py`: a different undercut-detection
parameterization on Part1 grouped a larger face set into "the critical
feature" and hit a real 36.59% conservation error, correctly caught and
reported as `status="failed"` rather than silently returned as good data.
Tracked under S4.3 (grouped/multi-feature generalization), not treated as
a Stage 6 defect. See CHANGELOG.md 2026-07-29 for full detail.

**Stage 5 — AI agent orchestration layer — done.** New `backend/agent/`
package: provider-agnostic tool-calling agent (Gemini/Anthropic/OpenAI/Grok)
driving the same 6 deterministic geometry functions the API already
exposes. Verified live, end-to-end, against real `Part1.stp` through Gemini
(`gemini-2.5-flash`) — real tool calls, real measured findings (face 232 at
1.075° draft vs. 1.5° minimum), a schema-valid `DfMReport`, and the full
`/parts/{filename}/agent/analyze` API + Streamlit "AI Agent" tab round
trip. Two real bugs found and fixed during that live verification: (1) once
the pull direction is established as `"optimal"`, later tool calls that
correctly echo it back were being mis-tracked as `"user_specified"`; (2) a
modern `httpx` pulled in by the new SDKs broke the pinned `openai==1.25.0`
client construction (`TypeError: unexpected keyword argument 'proxies'`),
fixed by bumping to `openai==1.109.1`. See CHANGELOG.md for full detail.
`backend/agent/dfm_agent.py`/`tools.py` were genuinely 0 bytes before this —
this is the first code the agent layer has ever had.

**Stage 4 — side-core / lifter generation (Bosch criterion #5, first
increment) — done.** New `backend/geometry/side_core.py`: one side-core
solid for the single highest-confidence critical undercut feature,
Boolean-subtracted from whichever mold half contains it, exported as a
third AP214 solid. Verified on both real parts: exported STEP reloads with
exactly 3 solids, volumes conserve to within 0.001% of the original
cavity+core total. Grouped/multi-feature generation and lifter-vs-slide-vs-
collapsible-core classification are explicitly out of scope for this
increment — see Resolved and `docs/ARCHITECTURE_ROADMAP.md` §4.3.

**Cross-cutting X.1 done**: `part_validation.py` gained 5 `--assert-*` flags
that check *measured* geometry (`closure_error_mm`, `graph_cleanup_strategy`,
`parting_surface_status`, `silhouette_coverage_ratio`, `split_solid_count`),
never a self-reported flag alone. See Resolved.

| Part | Readiness | Silhouette coverage | Parting surface (display) | Core/cavity split |
|---|---|---|---|---|
| `Part1.stp` | `ready` (0.792) | 94.8% | `generated_filling` | ✅ `split_ok`, 2 solids |
| `Part3.stp` | `ready` (0.806) | **18.1%** ⚠ | `generated_filling` | ✅ `split_ok`, 2 solids |

Part3's low coverage is **correctly flagged**, not hidden — its silhouette is
genuinely fragmented across 22 B-Rep components. See Open Items.

**Stage 3 is done through S3.6 (2026-07-28).** `frontend/app.py` gained an
issue-first "Findings" panel (Layer 1 verdict, ≤5 ranked items with "Show
evidence" expanders), a 10-entry metric glossary with hover tooltips,
`graph_cleanup.strategy` and `silhouette_coverage_ratio` as always-visible
chips (previously buried in a collapsed expander — exactly the Bug B blind
spot the roadmap called out), direction vectors shown with axis+tilt
("≈ +Z, tilted 25°") everywhere, and the Boolean solid split wired into the
UI for the first time (opt-in checkbox, with an explicit `split_tool_kind`
honesty callout).

**S3.6 — direction override (Bosch criterion #2) — done.** ±X/±Y/±Z presets
plus a custom-vector input in the Direction tab; applying one recomputes
draft/undercuts/parting-line/core-cavity for that direction and stores the
result separately (`override_result`) — the recommendation is never
overwritten. A "Recommended vs Override" comparison table and an
always-visible "using an override" banner (independent of which tab is
open) make the tradeoff visible; the Findings panel switches to the
override's results while one is active, every location suffixed
"(override)". Found and fixed a real backend gap while implementing this:
`/core-cavity` accepted `use_optimal_direction=false` but silently ignored
any supplied `dx/dy/dz`, always falling back to a hardcoded `+Z` — there was
no way to classify against a genuinely custom direction at all. Fixed to
match `/parting-line`'s existing correct pattern.

Verified with Streamlit's `AppTest` harness against the real backend for
both parts — no exceptions, real data throughout (no browser tool available
in this environment, so this was the closest rigorous substitute). One real
Streamlit state-ordering bug caught during that verification: the banner
and Findings panel render earlier in the script than the button-handling
code that sets override state, so they showed stale state for one rerun
after clicking — fixed with `st.rerun()` immediately after every state
mutation.

**S3.7 — candidate diversity clustering — done.** `_cluster_diverse_candidates()`
greedily selects candidates ≥15° apart (candidates pre-sorted best-first),
replacing the previous "top 6, all within 9°" near-duplicate list. Now
fetches the full candidate set (`include_all_candidates=true`) instead of
the default top-10, where the near-duplicate problem was hiding. Verified
on real Part1: 114 scored candidates → 17 genuinely distinct families.

**S3.8 — Stage 3 is now fully DONE.** Two items, both measured:
1. **`PartGeometry` LRU cache** (`load_step_cached()`, keyed on `(path,
   mtime_ns)`) — cold load 0.79s → warm hit ~0.003s (≈250x). The mandatory
   mutate-safety test the roadmap called for: only a pristine, never-mutated
   template is ever cached; every caller gets a fresh, independently-mutable
   clone (`_clone_pristine_part()`) — mutating one clone's face/direction
   fields never affects another's, verified directly.
2. **Mesh/analysis payload split** — the backend already had the right hook
   (`to_payload(include_geometry=...)`) but every endpoint hardcoded `True`;
   now the frontend requests `include_mesh_geometry=false` once the base
   geometry is already cached client-side. Measured: the same `/draft` call
   drops from 682,742 to 224,780 bytes (≈67% smaller) on a cache hit, with
   zero rendering regression — verified by inspecting the actual rendered
   Plotly `mesh3d` traces across all 5 analysis tabs (real vertex/face
   counts every time, matching the cached base exactly).

Full suite 266/266 (261 + 5 new mutate-safety tests).

**Level 2 (core/cavity solid split) now genuinely works end-to-end on both
real parts — Milestones 1.10 and 1.11 are verifiably implemented, not just
"tests pass" on a mocked path.** The real 3-D parting surface
(`BRepFill_Filling`) is confirmed topologically invalid on both parts
independent of any extension attempt (`BRepCheck_Analyzer`, unfixable by
`ShapeFix`/`Sewing` — see Resolved, "Stage 2b"). The Boolean split now uses a
separate, always-valid flat-plane approximation tool instead
(`core_cavity.build_planar_split_tool`) — verified with a real `split_ok`,
2 solids, a reloadable AP214 STEP export, on both Part1 and Part3. This is a
genuine geometric approximation for non-planar parting lines, honestly
labeled via `CoreCavitySolidResult.split_tool_kind="planar_approximation"`;
the *reported/displayed* parting line is completely unaffected. See Resolved
and `TODO.md` S2.3/S2.4.

## ⚠️ Open Items

| ID | Issue | Impact / Next step |
|---|---|---|
| **Part3 silhouette coverage** | Selected parting loop spans only 18.1% of Part3's projected extent. Ring bridging now produces a genuinely closed 18-component cycle, but it scores 0.70 vs the retained original's 0.77, so the original is kept. | Not a correctness bug — the engine warns honestly via `silhouette_coverage_ratio`. Needs either better loop selection on fragmented silhouettes or acceptance that Part3 needs manual parting-line input. **Should be reviewed by a mold engineer.** |
| **Volume conservation is ~4%, not the original 2% target** | The planar-approximation Boolean split conserves tooling volume to within 4.04% (Part1) / 3.81% (Part3), not the originally-intended 2%. `volume_conservation_tolerance` raised to 0.06 to match, documented not silently loosened. | Low priority, not a correctness bug (`_validate_split_volumes` still rejects anything outside tolerance). `TODO.md` S2.5 — investigate whether tuning the Splitter's own fuzzy tolerance (separately from the Cut step's) tightens this. |
| **Side-core lifter-vs-slide-vs-collapsible-core mechanism selection** | `side_core.py` (both single- and multi-feature paths) answers only "what volume must retract, along which direction" — it never decides the tooling mechanism (roadmap §4.3 Q4, unchanged since Stage 4). | Explicitly out of scope; not tracked as a bug. |
| **Combined side-core bodies can be multi-piece compounds** | A combined per-half side-core body's internal solid count is data-dependent (Part1's real 8-feature case: 6 disconnected pieces). Volume still conserves (<0.01% on Part1) — only the solid count varies. | Documented in `side_core.py`'s module docstring and `combine_side_cores_per_half`'s docstring; not a defect, no fix planned. |
| **Mock-test hygiene** | Mock-based tests (`occ_face=MagicMock()`) calling `detect_undercuts()`/`optimize_mold_direction()` without explicit `boolean_refine=False` stall for minutes against real pythonocc-core. | Partially mitigated by Bug G's `isinstance` guard and explicit `boolean_refine=False` at known call sites in `test_undercut_detector.py` / `test_direction_optimizer.py`. Still needs an audit pass for any remaining mock-based tests. |
| **Part3 convexity swing** | Part3's undercut count drops 16 → 0 with convexity suppression enabled. Logic is verified (synthetic box/pocket + 4 unit tests), but a 100% swing on a real part needs visual sanity check. | Needs mold engineer sign-off before being used in demo claims. Kill switch: `dfm.undercut.convexity_suppression_enabled`. |
| **Gemini free-tier daily quota is very tight** | The team's Gemini key hit `RESOURCE_EXHAUSTED` mid-session with `limit: 20` requests/day for `gemini-2.5-flash` (confirmed live, 2026-07-28) — not a code bug, an account-tier limit. Verification runs after that point (frontend UI click) hit this and correctly showed a graceful error, not a crash. | For continued demo/dev use: enable billing on the Gemini key, or switch `agent.provider` to `anthropic`/`openai`/`grok` (structurally verified, not yet live-tested — see next item) once a key is available. |
| **Anthropic/OpenAI/Grok adapters are structurally verified, not live-tested** | Built from verified real SDK signatures (`anthropic` 0.120.1, `openai` 1.109.1) and covered by mocked-provider unit tests, but no Anthropic/OpenAI/Grok API key was available this session to run a live end-to-end call the way Gemini was. | Not a known defect — just an honest gap in what's been *proven*, vs. Gemini's full live verification. Provide a key for any of the three to close this. |


## ✅ Resolved

| ID | Issue | Resolution |
|---|---|---|
| **BUG A** | `_attempt_loop_closure` computed the closing path, discarded it, and returned `(True, 0.0)` regardless — a 17.35 mm gap reported as closed. | Fixed 2026-07-27. Returns closing points, splices real B-Rep vertices, closes exactly, and **re-measures** before reporting. Measured gap now 0.000000 mm on both parts. 4 permanent honesty-guard tests added. |
| **BUG B** / **F4** | Milestone 1.6 was only cosmetically done — `networkx` replaced an adjacency dict, but the search stayed a 22-edge bounded DFS falling back to non-backtracking greedy. Every real part (~206 edges) took the fallback. | Fixed 2026-07-27/28. Shared `_best_path_with_contraction_fallback` used by **both** wire-ordering paths; degree-2 chains contracted into hyper-edges (Part3: 254 edges → 50 hyper-edges) so search scales with branch points, not edge count. |
| **BUG D** | Bridging was O(rounds × pairs × \|ep_i\| × \|ep_j\|) full Dijkstra calls — 373,000+ calls on Part3, did not finish in 10+ min (budget 45 s). | Fixed 2026-07-27. One `nx.single_source_dijkstra` per endpoint, computed once, reused as O(1) lookups. Part3 bridging now **under 1 second**. |
| **BUG E** | No parting surface produced on either part. Three causes: illegal `BRepFill_Filling` args (`NbIter=0`), ~24,000-point display polyline fed as constraints, no pull-direction check on the planar path. | Fixed 2026-07-27. Both parts now yield `generated_filling` with a live `occ_shape`. |
| **BUG F** | Bridging ran unconditionally and **destroyed an already-good closed loop** (Part1: `ready(1.000)` → `weak(0.080)`, 0.2 s → 49.8 s). | Fixed 2026-07-27. Bridging is now a fallback, gated on `is_closed AND coverage >= threshold`, result kept only if genuinely better. `bridging_status` makes the decision inspectable. |
| **BUG G** | Two `test_parting_line.py` tests hung forever on real OCC. Root cause: `BRepAdaptor_Curve(MagicMock)` — a SWIG-wrapped C++ call that hangs at the native layer, uncatchable by Python `try/except`. | Fixed 2026-07-28 with an `isinstance(edge.occ_edge, TopoDS_Edge)` guard. **Suite now 237/237, zero exclusions.** |
| **`_OCC_SPLIT_AVAILABLE` false import** | `_OCC_SPLIT_AVAILABLE` was `False` for every request, in every environment — core/cavity solid split and STEP export had **never once actually run** with real OCC. Root cause: `from OCC.Core.Interface_Static import Interface_Static` — that module path doesn't exist (real path: `OCC.Core.Interface`), silently swallowed by a bare `except`. | Fixed 2026-07-28. Corrected the import path and added error-level logging so the failure can never hide silently again. |
| **`SetArguments([shape])` TypeError** | `BRepAlgoAPI_Cut`/`BRepAlgoAPI_Splitter`'s `SetArguments`/`SetTools` require a real `TopTools_ListOfShape`, not a plain Python list — raised `TypeError`, silently caught by the retry loop's `except Exception`. | Fixed 2026-07-28 with a `_shape_list()` wrapper. Uncovered a third bug once fixed: the split could report `split_ok` on a degenerate result; `_validate_split_volumes()` now guards against it. |
| **Stage 2b — solid split now genuinely works end-to-end** | The real `BRepFill_Filling` parting surface is confirmed topologically invalid on both real parts (`BRepCheck_Analyzer`), independent of any extension attempt — a lofted "shoulder" collar extension genuinely worked as area extension (2,352→20,226 mm² Part1, 603→71,308 mm² Part3) but `ShapeFix_Shape`/`ShapeFix_Face`/`BRepBuilderAPI_Sewing` all failed to make the underlying patch valid, so `BRepAlgoAPI_Splitter` still couldn't use it. | Fixed 2026-07-28 with `core_cavity.build_planar_split_tool()` — a separate, always-valid flat plane through the loop centroid, used as the Boolean tool instead of the real parting surface. Verified `split_ok` + 2 solids + a STEP export that reloads with 2 solids, on **both** Part1 and Part3. Labeled `split_tool_kind="planar_approximation"` — a genuine, honest geometric approximation, not the exact 3-D parting line. Shoulder-collar code removed (provably insufficient). |
| **BUG I — solid split OOM** | Running the real split via `--core-cavity`/`--assert-core-cavity-solids` on Part1 with the default Z pull direction got OOM-killed (exit 137) instead of failing cleanly. | Re-verified 2026-07-28 against the exact original repro command after the Stage 2b fix: completes cleanly, no OOM, on both parts (0.47s/0.98s). Root cause was almost certainly the old splitter retrying against the invalid shoulder-extended shape; the new planar tool needs no expensive retries. |
| **Metrics not interpretable (S3.1-S3.5)** | Metrics were *visible* but presented as a flat dump; `graph_cleanup.strategy` (the single highest-value field — exposing it alone would have caught Bug B) was buried in a conditionally-collapsed expander. | Fixed 2026-07-28: issue-first "Findings" panel (Layer 1 verdict, ≤5 ranked items), metric glossary with tooltips, `graph_cleanup.strategy`/`silhouette_coverage_ratio` always-visible chips, direction axis+tilt formatting. One real bug found and fixed while building this against live data: draft severity's real vocabulary is `none|minor|moderate|critical`, not the guessed `good|marginal|bad`, so the "OK" draft finding silently never appeared. Verified via Streamlit `AppTest` against the real backend, both parts, no exceptions. |
| **Bosch criterion #2 (direction override, S3.6)** | Flash *scoring* existed (Milestone 1.4) but there was no user override path. | Fixed 2026-07-28: ±X/±Y/±Z/custom override in the Direction tab, recomputes draft/undercuts/parting-line/core-cavity, stores the result separately from the recommendation, "Recommended vs Override" comparison, always-visible active-direction banner. Found and fixed a real backend gap: `/core-cavity` silently ignored any supplied direction when not using the optimal one, always falling back to hardcoded `+Z`. Verified via `AppTest`, no exceptions. |
| **Candidate list not diverse (S3.7)** | Top 6 direction candidates were all within 9° of each other — an artefact of the Milestone 1.4 fine-search cone, not genuinely distinct options. | Fixed 2026-07-28: `_cluster_diverse_candidates()` greedily keeps candidates ≥15° apart from every already-kept one; now fetches the full candidate set instead of the default top-10. Verified on real Part1: 114 scored candidates → 17 genuinely distinct families. |
| **No `PartGeometry` cache; every endpoint re-parses the STEP file (S3.8)** | Stateless-by-design backend meant every one of `/draft`/`/undercuts`/`/direction`/`/parting-line`/`/core-cavity` reloaded and reparsed the STEP file from scratch, even for repeat calls on the same part within one guided-flow session. | Fixed 2026-07-28: `load_step_cached()` keyed on `(path, mtime_ns)`, returning a fresh mutate-safe clone every call (mandatory safety test included). Measured 0.79s → ~0.003s on a warm hit. Also split mesh geometry from analysis payloads (`include_mesh_geometry` flag) — same `/draft` call now 682,742 → 224,780 bytes once geometry is cached, verified with zero rendering regression. |
| **BUG H** | Parting line selected the *tidiest* loop, not the *main silhouette* — `_wire_selection_key` ranked projected area 5th, inverting Nee 1998's maximum-contour rule. | Fixed 2026-07-27. Reordered to: validity → conflict avoidance → **projected area** → quality. Part1 coverage 27.6% → 94.8%. Added `silhouette_coverage_ratio` + warning so this can never pass silently again. |
| **BUG H-2** | Bridging built a **spanning tree** (union-find), which by definition contains zero cycles — so no wire tracer could *ever* close it. Proven by exhaustive 177,032-state search finding nothing. | Fixed 2026-07-27. `_bridge_via_angular_ring` orders components by angle around their centroid and bridges into a genuine **cycle**. Part3: 2 broken arcs → one closed 18-component cycle. |
| **BUG H-3** | Wire quality was scored from the **whole input component** (269 edges, 36 branch points) rather than the loop actually selected out of it — a clean 15-edge loop scored 0.00. | Fixed 2026-07-27. `skipped_edge_ids` no longer caps the quality label; `branch_point_count` recomputed from the selected subset. Part3 readiness `review (0.635)` → **`ready (0.806)`**. |
| **FIX C** | Docker used PyVista/Xvfb (static render) while local macOS used interactive Plotly — same data, different UX. | Fixed 2026-07-28: `DFM_FORCE_PLOTLY=1` in `docker-compose.yml`. Verified live against the running stack with a real Part1 mesh payload (6,649 points / 7,270 faces). |
| **F1** | `Part1.stp`/`Part3.stp` shared an MD5 — a genuine file mix-up. | Fixed 2026-07-27. Part1 = 522,419 B / `d0c89a7c…` (311 faces, 30.78 mm bbox); Part3 = 863,881 B / `a373ffdf…` (414 faces, 68.12 mm bbox). Genuinely different geometry. |
| **F2** | `core_cavity.py` cited a nonexistent config key; `threshold=0.05` hardcoded. | Fixed 2026-07-27: `dfm.core_cavity.threshold` added to `config.yaml` + `CoreCavitySettings`. |
| **F3** | `.claude/rules/api-layer.md` listed two endpoints that don't exist. | Fixed 2026-07-27: corrected to document `include_mesh` / `include_boolean_regions` query flags. |
| **F5** | The documented test command never worked — no `conftest.py`/`pytest.ini` put `/app` on `sys.path`. | Fixed 2026-07-27 with `pythonpath = ..` in `tests/pytest.ini`. |
| **F6** | Streamlit flooded `WebSocketClosedError` on macOS; 6 full mesh copies (~500 KB each) in `st.session_state` exhausted RAM. | Fixed 2026-07-27: `_cache_and_strip_mesh` + `_hydrate_mesh` + `dfm.display.max_triangle_count: 100000`. |
| Validation harness `Part2.stp` | Both harnesses hardcoded `DEFAULT_EXPECTED_FILES = ("Part1.stp", "Part2.stp")` — a file resolved away in Phase 0 that will never exist, so they permanently reported a false "missing file" and `--fail-on-missing-expected` would fail CI forever. | Fixed 2026-07-28 → `("Part1.stp", "Part3.stp")`. Verified live: `missing_expected_files` now `[]`. |
| `test_parting_line_paths_payload_is_json_safe` | Failed for real when first surfaced (2026-07-27). | Re-verified 2026-07-28: **passes**. Was catching a genuine pre-Bug-B pipeline defect, now fixed. |
| Real OCC validation | Every saved validation report showed `status: "skipped"` (no OCC in test env). | Fixed 2026-07-27: real runs in Docker; both parts pass every stage. Evidence in `reports/level1_validation/`. |
| **F7** | `docker-compose.yml` never bind-mounted `tests/` — `docker compose exec backend pytest tests/...` (CLAUDE.md's documented command) silently ran a stale, image-baked test tree missing 6 of 12 current files, including `test_core_cavity.py`. F5's `pythonpath = ..` fix (2026-07-27, source) was itself never actually verified in Docker for the same reason. | Fixed 2026-07-28: `./tests:/app/tests` added to backend's volumes, mirroring `./backend`. Container recreated and reverified: full suite genuinely 255/255. |
| **Cross-cutting X.1** | Every 2026-07-27 audit bug survived a fully green mock suite because nothing asserted measured geometry independently of self-reported flags. | Fixed 2026-07-28: 5 `--assert-*` flags added to `part_validation.py` (closure, exact-optimiser, parting-surface, silhouette-coverage, core-cavity-solids), each gated by 9 new tests built from deliberately bad payloads, plus a live run against real Part1/Part3 confirming `--assert-silhouette-coverage` genuinely catches Part3's 18.1%. |
| **Bosch criterion #5 (Stage 4, first increment)** | No geometry existed for side-core/lifter generation — only recommendation strings in `undercut_detector.py`. | Fixed 2026-07-28: new `backend/geometry/side_core.py` generates one side-core solid for the single highest-confidence critical feature (planar-approximation sweep tool, reusing `core_cavity.build_planar_split_tool`), Boolean-subtracted from whichever mold half contains it, exported as a third AP214 solid. Two real bugs found and fixed while prototyping: footprint sizing must use face `Bnd_Box` corners (not centroids — zero scatter for single-face features; not vertices — misses curved-edge extrema, measured 24x undersizing on Part3); the Common/Cut fuzzy tolerance must be identical (a mismatch measured 37.72% conservation error on Part1 despite both ops reporting success). Verified end-to-end on both real parts: 3-solid STEP export reloads with exactly 3 solids, volumes conserve to <0.001%. |
| **Phase 2b (mock-test hygiene, partial)** | Mock-based tests calling `detect_undercuts()`/`optimize_mold_direction()` without `boolean_refine=False` stall for minutes in Docker against real OCC. | Fixed 2026-07-27 at known call sites: explicit `boolean_refine=False` added to 3 call sites in `test_undercut_detector.py` (lines 68, 180, 355) and `_OCC_BOOLEAN_AVAILABLE=False` patched in `test_direction_optimizer.py`. All 74 tests in these modules pass in <1s. Broader audit still tracked as an open item above. |

## Module Status

| Module | File | Lines | Status | Notes |
|---|---|---|---|---|
| STEP Loader | `backend/geometry/step_loader.py` | ~1,236 | ✅ Done | Full topology + edge convexity (1.1) + `load_step_cached()` LRU cache with mutate-safe cloning (S3.8, 2026-07-28) |
| Draft Analyzer | `backend/geometry/draft_analyzer.py` | 872 | ✅ Done | Face-level draft + conditional thresholds (1.5) |
| Undercut Detector | `backend/geometry/undercut_detector.py` | 3,517 | ✅ Done | Selective Boolean refinement, feature grouping, convexity suppression (1.2) |
| Direction Optimizer | `backend/geometry/direction_optimizer.py` | 1,058 | ✅ Done | Candidate search, Boolean pruning, flash risk + coarse-to-fine (1.4) |
| Parting Line | `backend/geometry/parting_line.py` | 4,720 | ✅ Substantial | Real graph search (1.6/Bug B), ring bridging (1.7/Bug H-2), verified closure (1.8/Bug A), parting surface (1.9/Bug E). Full Hou global optimization still not applied |
| Core/Cavity | `backend/geometry/core_cavity.py` | ~695 | ✅ Split verified end-to-end (Stage 2b) | Face classification + Boolean solid split (1.10) + AP214 export (1.11). `split_ok` + 2 solids + reloadable STEP export verified on both real parts via `build_planar_split_tool()` (a labeled planar approximation — see Resolved "Stage 2b"), not the (topologically invalid) real 3-D parting surface |
| Visualize Raw | `backend/geometry/visualize_raw.py` | 442 | ✅ Done | Display mesh with `face_id` mapping + triangle ceiling |
| Data Models | `backend/models/geometry_models.py` | 768 | ✅ Done | Shared dataclasses, zero internal imports |
| Config | `backend/config.py` | 714 | ✅ Done | Frozen settings |
| FastAPI Backend | `backend/api/main.py` | 1,077 | ✅ Done | All endpoints + `solid_split` + `POST /export/mold-halves` |
| Streamlit Frontend | `frontend/app.py` | ~4,980 | ✅ Stage 3 complete (S3.1-S3.8) | Guided 5-step UI + ranked-findings summary, metric glossary, Level 2 UI wiring, direction override with Recommended-vs-Override comparison, diverse candidate-direction clustering, mesh-payload split (2026-07-28). React migration **cancelled**. |
| Validation | `backend/validation/part_validation.py` | ~825 | ✅ Real-geometry assertions (X.1) | 5 `--assert-*` flags added 2026-07-28, each checking a measured value, not a self-reported flag |
| Performance | `backend/validation/performance_profile.py` | 448 | ✅ Done | Timing budgets |
| Side core / Lifter | `backend/geometry/side_core.py` | ~370 | ✅ First increment verified end-to-end | **Bosch criterion #5.** One side core for the single highest-confidence critical feature, Boolean-subtracted from the containing mold half, exported as a 3rd AP214 solid. Grouped/multi-feature generation and lifter-vs-slide-vs-collapsible-core classification are explicitly out of scope (roadmap §4.3) |
| AI Agent | `backend/agent/dfm_agent.py` | ~165 | ✅ Verified live end-to-end | Orchestration loop: bounded tool-calling iterations, batched execution, mechanically-tracked `tools_called`/`pull_direction`/`pull_direction_source`, tolerant JSON report parsing. Verified against real `Part1.stp` via Gemini. |
| Agent Providers | `backend/agent/providers.py` | ~330 | ✅ Gemini live-verified; Anthropic/OpenAI/Grok structurally verified | Provider-agnostic `LLMProvider` abstraction. Gemini adapter fully live-tested; Anthropic/OpenAI/Grok built from verified real SDK signatures and unit-tested with mocks, not yet live-tested (no Anthropic/OpenAI/Grok API key available) |
| Agent Tools | `backend/agent/tools.py` | ~260 | ✅ Verified end-to-end on real Part1.stp | 6 tools wrapping the geometry engine; all four roadmap "hard rules" (no OCC handles, mutate=False, truncation, structured errors) verified against real geometry |
| Agent Schemas/Prompts | `backend/agent/schemas.py`, `prompts.py` | ~40, ~65 | ✅ Done | Pydantic `DfMReport`/`DfMFinding`; system prompt enforcing this project's honesty rules |
| PDF Export | `backend/report/pdf_export.py`, `templates.py` | ~330, ~90 | ✅ Verified end-to-end | Pure presentation layer over already-computed `.to_dict()` payloads; `reportlab` finally imported after being pinned since the initial scaffold. Aggregates every source's warnings into a top-level "Warnings" section. Verified on real Part1.stp/Part3.stp and via the live `/export/report` API + frontend button. |

## Test Status

**Full suite: 347 passed / 0 failed / 0 excluded** (real pythonocc-core in
Docker, container recreated 2026-07-28 with the F7 mount fix live). No
`-k` exclusions needed.

| Test File | Lines | Status |
|---|---|---|
| `test_parting_line.py` | 1,190 | ✅ 32/32 — includes 8 honesty/regression guards added this session |
| `test_undercut_detector.py` | 1,683 | ✅ Passes (mock-based) |
| `test_draft_analyzer.py` | 695 | ✅ Passes (mock-based) |
| `test_direction_optimizer.py` | 522 | ✅ Passes (mock-based) |
| `test_step_loader.py` | ~600 | ✅ Passes — +5 tests 2026-07-28: `TestLoadStepCached`, the mandatory mutate-safety guard for the S3.8 LRU cache |
| `test_part_validation.py` | ~430 | ✅ Passes — +9 tests 2026-07-28 for `check_assertions()` (X.1), each built from a deliberately bad payload |
| `test_core_cavity.py` | (2026-07-28) | ✅ 14/14 — 9 from Stage 2a + 5 from Stage 2b. Includes `test_real_split_and_export_round_trips_on_part1`/`_on_part3`: the first tests to ever run the full real pipeline (direction → parting line → Boolean split → AP214 export → STEP reload) against `data/parts/Part1.stp`/`Part3.stp` and assert exactly 2 reloaded solids |
| `test_performance_profile.py` | 107 | ✅ Passes |
| `test_api_error_handling.py` | ~120 | ✅ Passes — +1 test 2026-07-28: real-OCC regression guard for the `/core-cavity` direction bug (S3.6) |
| `test_api_boolean_regions.py` | 69 | ✅ Passes |
| `test_visualize_raw.py` | 69 | ✅ Passes |
| `test_side_core.py` | (2026-07-28) | ✅ 11/11 — Stage 4 first increment. Includes `test_real_side_core_generation_and_export_round_trips_on_part1`/`_on_part3`: full pipeline → side core → 3-solid AP214 export → STEP reload, asserting exactly 3 reloaded solids and volume conservation |
| `test_agent_schemas.py`, `test_agent_providers.py`, `test_agent_tools.py`, `test_dfm_agent.py` | (2026-07-28) | ✅ 52/52 — Stage 5 agent layer. Real Part1.stp checks for all four "hard rules", scripted-provider orchestration tests, direction-tracking regression guard |
| `test_pdf_export.py` | (2026-07-29) | ✅ 18/18 — Stage 6 PDF export. `_collect_warnings`/`_direction_label_display` pure-function coverage (including the "no_feature is not a warning" negative case), structural PDF validity, real Part1.stp/Part3.stp end-to-end generation |

### Root process defect — now mitigated (X.1 done)

Every bug in the 2026-07-27 audit **survived a fully green suite**, because
the tests were mock-based and asserted *structure* (does the function return
the right shape?) rather than *geometry* (is the curve actually closed?).
Four milestones were marked complete on that basis.

The cross-cutting fix — real-geometry assertions in the validation harness
(X.1) — **is now implemented** (`--assert-parting-line-closed`,
`--assert-exact-optimiser`, `--assert-parting-surface-generated`,
`--assert-silhouette-coverage`, `--assert-core-cavity-solids`). Remaining
cross-cutting gaps: X.2 (synthetic known-answer fixtures — current tests are
still all OCC mocks, not real geometry with a known-correct answer), X.3
(real-OCC CI), X.4 (performance budgets enforced), X.5 (production Docker
build).

## Data Status

STEP schema: `AUTOMOTIVE_DESIGN` (AP214). Mold-half export targets AP214 to match.

| File | Size | MD5 | Role | Status |
|---|---|---|---|---|
| `data/parts/Part1.stp` | 522,419 B | `d0c89a7c…` | Level 1 input | ✅ 311 faces, 30.78 mm bbox |
| `data/parts/Part3.stp` | 863,881 B | `a373ffdf…` | Level 2 input | ✅ 414 faces, 68.12 mm bbox |

There is **no `Part2.stp`** — an earlier naming mix-up, resolved in Phase 0
(F1). Validation harness defaults corrected 2026-07-28.

## Infrastructure

| Component | Status |
|---|---|
| Docker (backend + frontend) | ✅ Configured; frontend now forces Plotly to match local (FIX C); `tests/` now bind-mounted like `backend/` (F7) |
| Conda environment | ✅ `environment.yml` defined |
| Config system | ✅ `config.yaml` + frozen dataclasses |
| Test command | ✅ Works as documented, and now actually verified against a container holding current source (F5 + F7) |
| `.claude/` setup | ✅ Complete |
