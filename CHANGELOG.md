# Changelog — DfM Agent

> **Append-only.** Add new entries at the top. Format: `### YYYY-MM-DD — Summary`

### 2026-08-13 — D-037: fresh independent separation test confirms H3 correctness; self-corrected false discrepancy; alternative-loop search negative

**What changed:**
- New: `backend/validation/parting_line_independent_separation_test.py`
  -- a from-scratch "does this loop separate the B-Rep" test that does
  NOT import `regions.py`: own sign(g) via direct `GeomLProp_SLProps`
  calls, own face-adjacency construction, own BFS components, own
  interval-complement arithmetic. S0/S1/S2/S3 classification.
- Validated on Part1 +Z (mandatory gate before touching Part3): correctly
  scores S2, matches production's H3 exactly (2 components, 13.4%
  smaller region, clean opposite-sign orientation).
- Applied to Part3's 5 requested directions -- initially found an
  apparent discrepancy on +Y (production region_count=3, independent
  test said 2/S2). Traced fully rather than accepted: root cause was a
  bug in the diagnostic script itself (silently dropping isolated
  split-face half-nodes that production's `separate_surface` correctly
  creates unconditionally for every split face, lines 271-272 of
  regions.py). Fixed to match production's node-construction discipline;
  re-validated Part1 +Z unaffected; re-ran all 5 directions and got
  100% agreement with production on every one (all correctly S0).
- **No CASE B or CASE E evidence found** -- H3's rejections independently
  confirmed correct on every directly-tested candidate.
- Searched for an alternative single-loop S2 candidate at grid(az15) via
  fundamental cycle-basis (62 cycles, µ~98 makes exhaustive Johnson
  enumeration intractable) XOR'd against the largest S0-confirmed
  candidate. 2 of 62 combinations scored S2, but both traced (via
  endpoint-chaining) to be disjoint unions of two separate closed loops,
  not single continuous curves -- the same already-established
  "loop_union" pattern that fails H1 before reaching H3. No genuine
  alternative found.
- Bypass geometry characterized: small local boss/fillet faces
  (0.81-63mm2 vs ~9000mm2 total part area), consistent with the
  mechanism already established in D-028/D-030/D-034.
- `docs/DECISIONS_AND_ALGORITHMS.md` D-037 added. `STATUS.md` updated. No
  production algorithm code changed.

---

### 2026-08-13 — D-036: 374-direction spherical search finds new territory (equatorial band), largest genuine candidates in the investigation, still CASE C

**What changed:**
- New: `backend/validation/parting_line_zero_level_network.py` (cheap
  per-direction diagnostic: raw-graph largest-component-fraction +
  non-trivial cyclomatic number, no candidate generation/H0-H7),
  `backend/validation/parting_line_spherical_search.py` (374-direction
  systematic grid: 15deg elevation x 15deg azimuth = 266 new points +
  the 108 previously-tested directions, re-scored consistently),
  `backend/validation/parting_line_deep_verify.py` (exhaustive Johnson
  cycle search where tractable, `nx.cycle_basis` fallback above
  mu=20 per component -- matches production's own `mu_max_for_johnson`
  gating -- plus the full unmodified production pipeline).
- Calibrated the cheap pre-filter on Part1 first: +Z ranks #1 (0.899)
  among Part1's 12 canonical directions, but the metric is a ranking
  signal, not a clean binary classifier (all 12 have substantial raw
  cyclic content -- consistent with D-029's prior finding that finer
  distinctions need H3-level testing).
- Result: the entire z=0 equatorial band (all `elevation=90` grid points,
  full 360deg azimuth ring) scores 0.87-0.90 -- far above anything tested
  in the prior 108-direction search (0.23-0.76) and genuinely new
  territory, not overlapping previously-tested directions. (Also
  confirmed +X, already known to fail, sits in this same band and scores
  similarly -- the metric remains necessary-looking, not sufficient.)
- Deep-verified 10 diverse directions across the band: production builds
  277-325 candidates each (an order of magnitude more than the
  bore/torus-dominated directions tested before) -- but all 10: zero
  valid candidates, H3 rejecting the large majority.
- Traced the two largest candidates found anywhere in the whole
  investigation, at `grid(elev90,az15)`: a 126-segment/91.7%-bbox
  "candidate" is actually 2 disconnected sub-loops unioned by
  `_subset_unions` (43.9mm closure gap); a genuine single 120-segment,
  73.0%-bbox, EXACTLY closed (0.0000mm gap) loop -- the largest true
  single loop found anywhere in this investigation -- still fails H3.
  BFS-traced a real, short 9-hop bypass path elsewhere in the part.
- **Classification: CASE C** for all 10 deep-verified directions --
  production builds real candidates from genuine large-scale geometry,
  H3 correctly and justifiably rejects them via a demonstrated bypass,
  same mechanism as D-027/D-028/D-034 now confirmed at a much larger
  scale. Not CASE D (no valid candidate found) and not CASE B (nothing
  is lost between the independent search and production's own
  representation).
- **Still no Part3 positive control.** 364 of 374 directions remain
  undeep-verified (only the top 10 by the cheap pre-filter were checked,
  per the requested "top 5-10" scope) -- expanded, not concluded,
  search space.
- `docs/DECISIONS_AND_ALGORITHMS.md` D-036 added. `STATUS.md` updated. No
  production algorithm code changed.

---

### 2026-08-13 — D-035: independent cycle search confirms CASE 1 — no global zero-level loop exists in Part3's CASE-A geometry

**What changed:**
- No production code changed. Read-only, independent (not
  `extract_loops`/cycle_basis/Johnson/H3/H4) search for ALL closed cyclic
  structure in the raw Track A/B graph, per explicit 9-step protocol.
- Method: self-loop enumeration, parallel-edge (same node-pair) 2-cycle
  enumeration, and `networkx.simple_cycles` for longer cycles -- caught
  and fixed a methodological trap mid-investigation (a naive
  `simple_cycles` call on a graph collapsed from a MultiGraph silently
  loses parallel-edge cycles).
- Strongest CASE-A direction (`(0,1,-1)+theta5+phi45`): raw graph 327
  nodes/266 segments/64 components, largest only 21 nodes (6.4%). Total
  cyclomatic number across the WHOLE graph: 3, all trivial single-segment
  self-loops. Zero parallel-edge or longer cycles anywhere. Exactly
  reconciles with production's own `candidate_count=7` (3 self-loops + 4
  `_subset_unions` combinations) -- independent confirmation candidate
  generation is not missing anything.
- Repeated on 3 more CASE-A directions: identical signature (60-75
  components, largest 5.7-7.7% of nodes, minimal cyclic content).
- Part1 +Z golden control (structural statistics only; full
  `simple_cycles` enumeration is combinatorially infeasible at mu=113,
  exactly why production gates Johnson behind `mu_max_for_johnson=12` --
  confirmed by directly hitting the wall and killing the run): raw graph
  356 nodes/460 segments/9 components, largest holds 320 of 356 nodes
  (90%), cyclomatic number 113 in that one component -- exactly matching
  D-026's independently-recorded `candidate_count=113` for Part1 +Z.
- **Classification: CASE 1** -- "no physically valid global zero-level
  loop exists for this direction." Not CASE 2 (nothing is lost;
  independently confirmed via a differently-implemented search agreeing
  exactly with production). Not CASE 3 (nothing meaningful survives to
  H3/H4 to mis-validate). D-033's "plausible" face-sign partition is real
  (two dominant regions by area) but does NOT correspond to an actual
  continuous zero-level curve realizing it -- the boundary is scattered,
  disconnected fragments with genuine same-sign gaps between them.
- Confirmed for 4 of 11 CASE-A directions (all sharing D-033's structural
  cause); not individually re-verified for the remaining 7.
- `docs/DECISIONS_AND_ALGORITHMS.md` D-035 added. `STATUS.md` updated.

---

### 2026-08-13 — D-034: forensic trace of the bore CASE-A candidate — no code defect demonstrated, F3 control disproves the leading hypothesis

**What changed:**
- No production code changed. Full read-only forensic trace of D-033's
  CASE-A finding, per explicit 15-question protocol.
- Confirmed edge 112 (face 35's 4th edge) is a genuine seam (only 1
  adjacent face — both "sides" are face 35 itself); Track A's own skip
  log already correctly labels it "seam edge (parameterisation
  artefact, not a physical boundary)". Not a bug.
- Confirmed Track A's partial coverage on edges 111/113/114 (roughly half
  the rim circumference each) originates at Track A itself, not lost in
  stitching — an exhaustive search of every segment near the bore's local
  neighbourhood (faces 35/36/320/321/319 and their edges) found nothing
  beyond what Track A/B already reported.
- Confirmed the uncovered rim arcs are geometrically CORRECT, not missing
  data: face 35's cone neighbours (320, 319) have robust, unambiguous
  sign (g=+0.5725, -0.5725 respectively) -- nowhere near zero-draft -- so
  the uncovered portion is a genuine same-sign region with nothing to
  detect.
- Hand-chained the 6 relevant segments into a properly-ordered,
  nearly-closed loop (closure gap 0.000993mm, the same ~14x
  weld-tolerance shortfall flagged in D-033). Confirmed that even with
  this loop manually force-closed, `separate_surface` still reports
  `region_count=1` -- the uncovered rim arcs remain a live bypass
  connection in the separating graph, identical in kind to D-027/D-028's
  already-established "uncovered-edge bypass" mechanism, now confirmed on
  a major feature (the 1432.57mm2 bore) rather than a small torus.
- **F3 control, decisive**: F3's own winning candidate achieves full rim
  coverage, but via a mechanism Part3's bore does not share -- F3's two
  end caps are EXACTLY zero-draft at the test direction (by design, per
  F3's own fixture manifest), which trivially satisfies the straddle test
  everywhere. Part3's cone faces are confirmed NOT degenerate, so this
  does not apply, and Part3's partial rim coverage is the geometrically
  correct output, not a defect F3 would have caught.
- **Success-criterion statement** (verbatim from the decision log): the
  boundary is not lost at any single stage due to a demonstrated code
  defect; H3 rejects the loop because the uncovered rim arcs are a real,
  correct absence of silhouette content, not a processing gap.
- **No production change proposed.** Per explicit instruction not to
  declare victory or propose a fix without a demonstrated defect, no
  minimum-fix/regression-test pair was produced this entry -- doing so
  would mean inventing a fix for something not shown to be broken.
- Confidence: high that no code-level defect exists in Track A/B,
  stitching, or graph construction for this feature/direction cluster.
  Open question, same as for the earlier torus features: whether a longer
  path elsewhere in the part could still complete the true global
  boundary.
- `docs/DECISIONS_AND_ALGORITHMS.md` D-034 added. `STATUS.md` updated.

---

### 2026-08-13 — D-033: independent global-separability diagnostic finds CASE A on Part3's main bore — strongest hypothesis-B evidence yet, not a resolved fix

**What changed:**
- New: `backend/validation/parting_line_independent_separability.py` — a
  diagnostic using ONLY `part.face_adjacency` and `FaceData.signed_dot()`
  (no Track A/B, stitching, graph, 2-core, cycle enumeration, H0-H7, or
  `separate_surface`). Cuts the full face-adjacency graph at every
  sign-flip edge (the maximal possible cut) and classifies by how much
  area the two largest resulting components capture.
- Found and fixed a real bug during Task 1 (before any Part3 result was
  seen): naive `sign = 1 if g>=0 else -1` is not antisymmetric at g==0
  exactly; Part3 has 92 of 414 faces with g exactly 0.0 at +/-Z, breaking
  +Z/-Z mirror agreement (0.931 vs 0.667). Fixed with a 1e-9 numerical
  tie epsilon.
- A first attempt at the whole diagnostic (3-bucket cavity/core/boundary
  model) failed its own Task-2 validation (Part1 +Z and ADV2 both scored
  "local-only" despite being known-positive) and was redesigned to the
  maximal-cut method, which doesn't penalize ordinary local-feature
  fragmentation as long as it still resolves into 2 dominant groups.
- Validated on 11 known controls (Part1 +Z/-Z/+-X/+-Y/(1,1,0)/(1,0,1)/
  (0,1,1), ADV1, ADV2): 0 mismatches, large unforced gap between positive
  (0.818-0.894) and negative (0.314-0.484) controls.
- Applied to all 108 already-tested Part3 directions. 12 canonical: all
  CASE B. Of 96 swept: **11 CASE A** (diagnostic says plausible, PL finds
  zero valid candidates) — all 11 touch the SAME feature: face 35, Part3's
  main central bore (Cylinder, 1432.57mm2, r=6mm) — a major structural
  feature, not a small torus/boss like every candidate examined since
  D-027.
- Traced one representative in full: Track A/B correctly detect the
  bore's silhouette (2 classic cylinder rulings + rim arcs, same shape as
  fixture F3). Hand-chained the 6 relevant segments into a properly
  ordered polyline with a closure gap of 0.000993mm against an H1
  tolerance of 0.000681mm (fails by 1.46x) -- the actual weld tolerance
  used by `build_graph` is 6.8e-5mm, ~14x smaller than this genuine
  cross-track (Track A vs Track B) gap. But manually force-closing the
  loop and re-running `separate_surface` STILL gives region_count=1 --
  the assembled candidate covers only 3 of the bore's 4 B-Rep edges, and
  even those only partially (edge 111's covered interval is roughly half
  the full circle). Same partial-edge-coverage mechanism as D-027/D-028,
  now shown on a major feature for the first time, broadening rather than
  contradicting that earlier finding.
- **Two distinct, correctly-not-conflated issues**: (1) a small, real,
  fixable weld-tolerance gap, insufficient alone; (2) a larger,
  not-yet-root-caused candidate-completeness gap (the actual blocker).
  **No fix proposed** -- the completeness gap itself needs tracing to a
  specific stage first, per the explicit instruction. This is the
  strongest evidence for hypothesis B found in the whole P3.x
  investigation, but deliberately not reported as resolved.
- `docs/DECISIONS_AND_ALGORITHMS.md` D-033 added. `STATUS.md` updated. No
  production algorithm code changed.

---

### 2026-08-13 — D-032: direction calibration (Part1) + 96-direction fine sweep (Part3) — no positive control found, algorithm stays frozen

**What changed:**
- New: `backend/validation/parting_line_direction_calibration.py` (Phase
  A) — computes, for every canonical direction, the fraction of near-zero
  -draft area concentrated in its single largest connected component
  (via existing `part.face_adjacency`, same `silhouette_epsilon` the
  engine uses). Calibrated against Part1: +Z/-Z score 0.988 (unique
  maximum, near-total coherence), vs. 0.79-0.89 at failing directions and
  0.23 at (1,0,±1)/(0,1,±1) — a geometrically explainable signal (coherent
  wall vs. scattered local features), unlike raw near-zero-area percentage
  which D-029 already found anti-correlated with ground truth. Applied to
  Part3: best canonical direction is +Y/-Y (0.857, still below Part1's
  0.988, already known from D-026 to fail with 287 H3 failures).
- New: `backend/validation/parting_line_angular_sweep.py` (Phase B/C) —
  documented 96-direction fine sweep (3 cone half-angles: 5/10/15 degrees,
  8 azimuths each) around all 4 required diagonal anchors
  ((1,0,1),(1,0,-1),(0,1,1),(0,1,-1)), every direction run independently
  through the unmodified `analyse_parting_line` (manual direction source
  throughout, zero optimizer involvement). Both direction-only and full
  pipeline layers recorded separately per direction, never collapsed.
- **Result: zero valid candidates across all 96 directions** (2,030 total
  raw candidates generated, 172s total runtime).
- Phase D: closest analog to Part1's `h3_failures=0` signature found (a
  3-direction cluster near `(0,1,-1)+theta{5,10,15}+phi180`) and traced in
  full. Not a genuine global candidate — the raw pool is just small (8
  candidates), and every member is either an H0 failure or the same
  single-torus-face pinch (34% H4 violation) already characterized in
  D-030/D-031. Every quasi-plausible candidate across the whole sweep
  falls into the same bucket (Phase E) — no new failure mode found.
- Phase F recommendation: **algorithm stays frozen.** Evidence continues
  to weight toward "no feasible direction in the space searched so far,"
  without proving it — this sweep only covers tight neighborhoods of 4
  diagonals, not Bosch's full stated practical direction space.
- `docs/DECISIONS_AND_ALGORITHMS.md` D-032 added. `STATUS.md` updated. No
  production algorithm code changed.

---

### 2026-08-13 — D-031: second adversarial fixture (Track-B global answer) — CASE E again; merged direction-validation table

**What changed:**
- New fixture generator `backend/validation/generate_adversarial_fixture_2.py`
  and fixture `data/fixtures/synthetic/ADV2_sphere_with_boss_array.stp`
  (diagnostic-only, not in the frozen F1-F17 manifest): a sphere (r=20mm,
  known closed-form answer at d=(0,0,1) = great circle z=0, entirely
  Track-B) plus 6 misaligned cylindrical bosses at scattered latitudes.
- Found and fixed a real fixture-construction bug before the experiment
  could run: a flat-bottomed cylinder tangent to a curved sphere surface
  only touches at one point, so `union()` left residual faces and by the
  2nd boss corrupted the sphere face out of existence entirely (verified
  face-by-face). Fixed by embedding each boss 3mm inside the sphere before
  extruding outward — the standard robust boolean case. Verified: sphere
  face count stays exactly 1 through all 6 unions.
- Ran the unmodified pipeline at (0,0,1): 5 candidates generated (4 boss
  top-rim self-loops, correctly H3-rejected as local; 1 the sphere's own
  face, `FaceBacking face_id=1`, single self-loop segment with z range
  exactly [0.0000, 0.0000] and radius range exactly [20.0000, 20.0000] —
  the precise closed-form answer). Passes every gate, selected.
- **Decision-tree outcome: CASE E, again** — now for a Track-B-required
  global answer, closing D-030's one explicitly-flagged gap. Both tested
  global-answer topologies (Track-A-only via ADV1, Track-B-only via ADV2)
  survive heavy misaligned local-feature noise cleanly.
- One new, separate, honestly-reported finding (not conflated with the
  CASE E conclusion): `RegionClassification.cavity_area_mm2`/
  `core_area_mm2` show an attribution asymmetry for a Track-B **split**
  face — 100% of face 1's area lands under `core_area_mm2`, none under
  `cavity_area_mm2`, despite `mean_g≈0`. Does NOT affect H3/H4 (they use
  the correct graph-based `SeparationResult.component_count`, confirmed
  exactly 2). Isolated to the reporting-only area-summary layer. Recorded
  as an open item, not fixed here.
- Built the requested merged direction-validation table by joining two
  already-computed datasets (D-026's `baseline_matrix_{principal,diagonal}
  .json` + D-029's `parting_line_direction_diagnostic.json`) — no new
  pipeline runs needed; delivered in the chat report, not duplicated in
  this file.
- `docs/DECISIONS_AND_ALGORITHMS.md` D-031 added. `STATUS.md` updated.
  No production algorithm code changed.

---

### 2026-08-13 — D-030: decisive adversarial fixture — CASE E, algorithm cleared of local-feature-noise weakness

**What changed:**
- New fixture generator: `backend/validation/generate_adversarial_
  fixture.py` (cadquery). Builds a 60×50×40mm box with 6 cylindrical
  bosses (r=4, h=8, 1.5mm toroidal fillet), one per face, axis normal to
  that face. New fixture file: `data/fixtures/synthetic/
  ADV1_box_with_boss_array.stp` — deliberately NOT added to the frozen
  F1-F17 manifest (kept as a standalone diagnostic fixture).
- Design gives a mathematically obvious, closed-form global parting line
  at d=(1,1,1)/√3: every box face normal is exactly ±X/±Y/±Z so g is
  constant per face (never split), and exactly 6 of the box's 12 edges
  have opposite-sign neighbors — the textbook hexagonal cube-diagonal
  silhouette. All 6 boss axes are misaligned with (1,1,1) by the same
  54.7°, reproducing Part3's exact structural situation (vertical bosses
  under an oblique pull direction) — each boss contributes real,
  correctly-detected, but non-closing local Track-B content (open cylinder
  rulings + mixed-sign torus fillets), mirroring D-028/D-029's Part3
  findings.
- Ran the unmodified production pipeline with zero special-casing. Result:
  Track A finds 12 segments, Track B finds 18 (30 total local+global raw
  segments); 2-core correctly prunes 30 of 36 post-stitch segments as
  non-cyclic tree material, leaving exactly the 6-edge/µ=1 true cycle;
  candidate generation produces **exactly 1 candidate**; it **passes every
  gate cleanly** (H0-H7); `cavity_area_mm2 == core_area_mm2 == 7467.56`
  exactly (an independent numerical check — point-symmetric diagonal cube
  cuts must split area exactly evenly, so this is the mathematically
  expected result, not a coincidence); all 6 winning segments are
  `EdgeBacking`, endpoints trace precisely the 6 predicted hexagon
  corners; each boss correctly inherits its parent face's mold side.
- **Decision-tree outcome: CASE E** — "the known global Parting Line is
  successfully generated and validated." Direct evidence AGAINST the
  hypothesis that local-feature-heavy geometry inherently breaks this
  architecture. Per the protocol's own explicit instruction, Part3 is NOT
  revisited or modified in this entry, since no evidence of an algorithmic
  weakness was found to justify it.
- **Recommendation: A — keep the algorithm frozen, focus on direction
  feasibility for Part3.** Caveats recorded honestly: one fixture, one
  direction, one topology (Track-A-only global answer, like Part1's own
  working case) — does not prove correctness on a main body whose OWN
  global answer requires Track B mixed with local-feature noise, and
  doesn't prove Part3's 24 tested directions exhaust Bosch's stated
  practical search space.
- `docs/DECISIONS_AND_ALGORITHMS.md` D-030 added. `STATUS.md` updated.
  No production algorithm code changed.

---

### 2026-08-13 — D-029: direction-feasibility vs. algorithm-correctness separated; Part1 +Z regression test added

**What changed:**
- New read-only diagnostic: `backend/validation/parting_line_direction_
  diagnostic.py` — computes direction-dependent moldability metrics
  (draft-angle distribution, positive/negative/near-zero sign(g) area,
  undercut area) for all 12 Part1 and 24 Part3 directions, reusing
  `analyze_draft`/`detect_undercuts`/`FaceData.signed_dot` rather than
  inventing a new score, and ranks directions BEFORE any parting-line
  result is consulted (avoids circular "the algorithm liked this
  direction" reasoning).
- Honest negative result: the naive ranking places Part1's Bosch-confirmed
  +Z **last** among Part1's own 12 directions (71.7% near-zero area vs.
  42.9-43.6% at the failing ±X/±Y) — anti-correlated with ground truth,
  not retrofitted to fix this.
- Actionable result: for Part3, ranks **(1,0,1)/(1,0,-1)** far above
  **(0,1,1)** — the direction the entire prior D-027/D-028 investigation
  focused on purely because it produced the largest-looking candidate.
- Ran the same D-028 loop-by-loop candidate audit (raw-graph inventory,
  every cycle-basis loop through `separate_surface` + full
  `evaluate_gates`) at (1,0,1) and (1,0,-1). Result: structurally identical
  to (0,1,1) — torus-boss single-face "pinch" loops pass H3 but are
  rejected by H4 at 34.2-34.3% orientation violation (near-identical
  across all 3 directions), or local rings fail H3 outright. Generalizes
  D-028's finding from one direction to three independently-motivated
  ones.
- Cross-checked the already-computed full D-026 24-direction table:
  Part1 @ +Z/-Z is the ONLY Part1 direction with `h3_failures=0`; no Part3
  direction, of 24 tested, ever reaches that — a clean structural
  distinguishing signature between the working and non-working cases.
- Confirmed the existing 15-fixture analytic positive-control suite
  (F1-F14, F17, `data/fixtures/synthetic/`, closed-form expected answers
  in `manifest.json`) is real and passing: **136/136 tests pass**,
  satisfying the "known-answer geometry" requirement without building a
  new suite.
- Found and closed a real gap: no test exercised `Part1.stp` through the
  v2 engine at all (only `Part3.stp` appeared in
  `tests/test_parting_line_v2_level1.py`; `test_parting_line.py` /
  `test_agent_tools.py` only cover the v1 engine). Added 3 tests:
  `test_part1_plus_z_is_a_mandatory_regression`,
  `test_part1_plus_z_and_minus_z_are_mirror_images`,
  `test_part1_plus_z_is_deterministic_across_reanalysis` — all pass.
- **Classification: closest to E** (insufficient evidence to fully
  separate hypothesis A "direction not tested yet" from hypothesis B
  "candidate-generation defect"), with a specific evidenced lean toward A.
  No synthetic fixture yet isolates Part3's exact failure signature
  (local-feature-dominated candidate pool at every tested direction) with
  a known correct answer, so B is not ruled out — flagged as the decisive
  next experiment, not run yet. `docs/DECISIONS_AND_ALGORITHMS.md` D-029
  added. `STATUS.md` updated to match. No production algorithm code
  changed.

---

### 2026-08-13 — D-028: corrects D-027 same day — 2-core pruning is exact, not lossy; Part3 @ (0,1,1) failure is local-feature dominance, gates behaving correctly

**What changed:**
- No production code changed. Follow-up 8-task diagnostic protocol
  (raw-graph inventory, termination classification, simple-cycle-validity
  question, Part1 control, self-loop isolation, 2-core-bypass experiment,
  "don't blindly blame 2-core," options-not-implementation) run directly
  against D-027's claim, per explicit instruction not to accept internal
  consistency as proof.
- **Decisive test**: built the raw (pre-`reduce_to_two_core`) graph and
  called `extract_loops` on it directly. Result: identical 11 candidates,
  identical exact segment-ID set, zero segments recovered. Proven
  mathematically too (leaf removal is E−V-invariant and never disconnects
  the remainder, so cyclomatic number per raw component is provably
  unchanged by 2-core peeling) and empirically (0 invariant violations
  across Part3 @ (0,1,1) and Part1 @ +Z/+X/+Y). **D-027's "graph
  construction loses topology at the 2-core stage" claim is retracted.**
- Reused D-027's raw inventory (242 mixed-sign-relevant pruned segments) to
  identify what they actually are: dozens of small, spatially separate
  local features (mirror-symmetric stepped-cylinder bosses with toroidal
  fillets, confirmed via face area/surface-type/adjacency inspection) whose
  own silhouette is a genuinely open, non-closing arc at this oblique
  direction — not a missing-segment defect (endpoint gaps 12-37mm, ruling
  out stitch tolerance).
- Tested every one of the 11 raw cycle-basis loops individually through
  `separate_surface` and the full `evaluate_gates`. Five (`loops 4-8`)
  pass H3 (region_count=2) but are trivial: `region_sizes=[1, 413]`, one
  single torus face pinched off from the rest of the 414-face part.
  Correctly rejected by **H4** ("34.2% of one region's area faces the
  wrong way"). Group 1 (the torus equatorial ring, already traced in
  D-027) fails H3 outright — a genuine local-feature loop that never
  reaches the main body. **H3, H4, and 2-core are all behaving correctly
  on every candidate that exists.**
- Confirmed Part1 @ +Z (Bosch-confirmed working direction) has **0**
  segments pruned by 2-core at all — a striking structural contrast to
  Part3's 85%. Part1 @ ±X/±Y (known-failing) shows the same
  local-fragment pattern at ~6% severity, not 0% — consistent with
  fragmentation severity tracking distance from a moldable direction.
- 8 remediation options evaluated (fix-connectivity-before-2-core,
  topology-aware pruning, preserve-and-bridge dangling fragments, richer
  hypergraph representation, contour-component candidate construction with
  local/global classification, re-run protocol elsewhere first) — **none
  implemented**. Best-supported: classify local-feature vs main-body
  geometry before H3/H4 scoring (ties to existing `side_core.py`
  local-tooling machinery), not any 2-core/graph-construction change.
- `docs/DECISIONS_AND_ALGORITHMS.md` D-028 added (supersedes D-027, which
  is retained for the record with its causal claim marked retracted).
  `STATUS.md` updated to match. New diagnostic script:
  `backend/validation/parting_line_2core_pruning_diagnosis.py`.

---

### 2026-08-13 — D-027: Part3 H3 failure root-caused — 2-core pruning discards real disconnected silhouette fragments [SUPERSEDED SAME DAY BY D-028 ABOVE]

**What changed:**
- No production code changed. Diagnostic-only, read-only tracing of
  candidate 43 (Part3 @ direction (0,1,1) normalized, the largest candidate
  found across D-026's full 24-direction sweep), per an explicit protocol
  rejecting "Part3 has no feasible direction" as a premature conclusion.
- Confirmed (by direct removal + re-run, not assumption) that the two
  zero-length self-loop segments (242/244) do not cause the observed
  `region_count=1` failure.
- Found the candidate is a `loop_union` decomposing into a genuinely closed
  4-segment equatorial ring around the torus (faces 37/317) and a separate
  10-segment local loop — neither separates the part when tested alone via
  `separate_surface()`.
- Traced the ring's bypass via BFS on `separate_surface()`'s own adjacency
  construction: a 17-hop path through 13 other faces, closing back through
  the loop's own edge (117) via its uncovered parameter half — correctly
  not silhouette there (real geometry), but still a live, uncut adjacency.
- Independent point-sampling (production `_FaceField.g()`, not
  graph-inferred) found 5 faces on that bypass path (327, 38, 39, 318, 35)
  that are themselves mixed-sign and should carry their own silhouette
  splits. Confirmed Track A/B *did* correctly detect silhouette segments on
  all 5 (1/3/23/3/6 segments respectively) in the raw 298-segment stitched
  pool — not a detection gap.
- Traced those segments through `build_graph` + `reduce_to_two_core`: they
  are pruned as dangling/tree-like before candidate generation (`_subset_
  unions`) ever runs. Endpoint gaps to the rest of the structure measured
  12-37mm on a 68.1mm-diagonal part, ruling out `stitch_snap_tolerance_rel`
  as the cause (an order of magnitude past its 1.36mm value here).
- **Root cause: (C) graph construction loses topology, specifically at the
  2-core pruning stage** — not the self-loop bug, not H3's Track-B
  split-face handling (confirmed working correctly), not a stitch-tolerance
  shortfall, not a Track A/B detection gap. See D-027 in
  `docs/DECISIONS_AND_ALGORITHMS.md` for the full evidence chain.
- This corrects D-026's framing for Part3 specifically: "no specific
  fixable defect found" no longer holds — D-026's whole-candidate
  pass/fail methodology could not have surfaced a fragment-level pruning
  defect. Part1's ±X/±Y failures were not re-examined for this same
  mechanism and remain under D-026's prior diagnosis.
- **No fix implemented or proposed for adoption yet** — per explicit
  instruction, this entry is diagnosis only. `STATUS.md`, `TODO.md`
  (new P3.2 section) updated to match.

---

### 2026-08-12 — D-026: 24-combo baseline matrix — Level 0-2 parting-line algorithm FROZEN

**What changed:**
- No production code changed. Ran the unmodified pipeline
  (`backend/validation/parting_line_baseline_matrix.py`, new) against
  Part1 and Part3 at the agreed finite direction set: 6 principal axes
  (±X/±Y/±Z) + 6 normalized diagonals ((1,1,0), (1,-1,0), (1,0,1),
  (1,0,-1), (0,1,1), (0,1,-1)) — 24 combinations, `PullDirectionInput(...,
  "manual")` throughout.
- **Result: Part1 feasible only at +Z/-Z (2/12 tested); Part3 feasible at
  none of 24 tested directions.** Full table in
  `docs/DECISIONS_AND_ALGORITHMS.md` D-026.
- Combined with this phase's prior diagnoses (D-022 stitch tolerance,
  D-023 Track-B boundary refinement, D-024 H0.3 fix, D-025 tangential
  classification, plus the enumeration comparison and envelope experiment
  from the two sessions before this one), **Level 0-2 (Track A/B,
  stitching, graph, H0-H7, ranking) is now declared FROZEN** — no further
  changes without new, specific diagnostic evidence.
- Minor secondary finding, not investigated: H0 failures appear for the
  first time this phase at diagonal directions only (1-6 candidates per
  direction) — never observed at any of the 12 principal-direction runs.
  Small counts; doesn't change any outcome.

**Why:**
Convergent evidence across the whole phase — not this single matrix in
isolation — supports freezing: broader enumeration (Johnson, 44x more
candidates) found nothing better on Part1; stripping Part3's confirmed-
genuine articulation-point facets didn't move the outcome; a direct
backward-trace of Part1's best candidate's H4 violations found the needed
geometry mostly absent or far from the loop, not a local construction
miss. Part1 +Z/-Z reproduce byte-identical results to every earlier
measurement, unmoved by any change made this phase. The remaining open
item — Part3 has no known-good direction to serve as a positive control —
is a missing input (Bosch's actual Part3 direction), not a demonstrated
algorithmic gap, and is explicitly out of this module's scope to search
for (Question B belongs to the direction-optimizer team).

---

### 2026-08-12 — D-025: Track-B now distinguishes tangential from silhouette segments (mechanism 2 diagnosis + minimal fix)

**What changed:**
- Read-only diagnosis first (`backend/validation/parting_line_mechanism2_diagnosis.py`,
  `reports/mechanism2_diagnosis_face317.json`): reconstructed Part3 face
  317's full Track-B contour and found the ~24.75mm "mismatch" against
  Track A previously reported is not a stitching defect — edge 52 (the
  shared boundary) is a full closed circle Track A's own straddle test
  already classifies `"tangential"` across its *entire* length. One of
  Track B's 3 chains on that face runs pinned along that same tangential
  edge; the other two are genuine transversal crossings elsewhere on the
  face. The true parting-boundary location along a tangential locus is not
  determined by pull direction alone — this is intrinsic non-uniqueness,
  not a bug, and was not "fixed" by forcing anything together.
- **Minimal classification fix**: `backend/geometry/parting_line_v2/track_b.py`
  now labels a finished face-backed segment `kind="tangential"` (instead of
  always `"silhouette"`) when it runs along a single B-Rep edge that
  Track A's own test (`_g_on_both_faces`/`_classify`,
  `max(|g_a|,|g_b|) <= silhouette_epsilon`) already calls tangential.
  Geometry/points/provenance unchanged — label only.
- Two Track-B-native candidate rules were tried FIRST and measured not to
  work (cell-corner `|g|` magnitude; `TopAbs_ON` fraction — both misfire on
  face 317's genuinely transversal chains too), before falling back to
  reusing Track A's own edge-level test, per explicit instruction not to
  invent an unmeasured geometric rule.

**Verification:** face 317's boundary-following segment reclassified
`tangential` exactly as predicted; its two transversal siblings stay
`silhouette`. Corpus-wide: Part3 @ +X 146 silhouette/29 tangential (of 175),
@ +Y 144/25 (of 169); Part1 @ +X 55/3 (of 58), @ +Y 59/4 (of 63); Part1/Part3
@ +Z unaffected (Track B silent there). F3/F4/F17 controls: all segments
remain `silhouette`, correctly unreclassified. **Zero effect on candidate
counts, H0, H3, H4, or outcome anywhere** — confirmed by direct comparison,
not assumed (`kind` is propagated by `stitch.py` but never branched on by
`graph.py`/`gates.py`/`regions.py`/`ranking.py`). Full regression suite: 477
passed / 4 skipped / 3 pre-existing-and-unrelated failures, unchanged.

**Why:**
Diagnosis-first again: reconstructed the geometry, classified it against
the plan's own zero-draft-band theory, and only implemented a fix once the
diagnosis showed exactly what was needed — a labeling correction, not a
merge/choice/tolerance change forbidden by the investigation's own
constraints. Sets up (but does not perform) any future work that might
want to treat tangential segments differently from genuine transversal
silhouette segments.

---

### 2026-08-12 — D-024: H0.3 fixed — `GeomAPI_ProjectPointOnSurf` now searches the face's real trim extent, not just the surface's own `Bounds()`

**What changed:**
- `backend/geometry/parting_line_v2/gates.py`: H0.3's face-backed branch now
  constructs `GeomAPI_ProjectPointOnSurf` with explicit bounds from
  `breptools.UVBounds(face.occ_face)` — the same authoritative trim extent
  `BRepTopAdaptor_FClass2d` already classifies against two lines above —
  instead of the implicit-bounds constructor, which silently restricted its
  search to the underlying `Geom_Surface`'s own declared `Bounds()`. Falls
  back to the old implicit form only if the trim bounds can't be retrieved.
  `tau_surface` and H0's definition are unchanged — this fixes the
  *verifier's* search domain, not what it verifies.
- Root cause (D-024, full mathematics and evidence in
  `docs/DECISIONS_AND_ALGORITHMS.md`): Part3 face 274's
  `Geom_BSplineSurface.Bounds() == [0,1]×[0,1]`, but its trim wire genuinely
  reaches `v≈1.0121`, ~1.2% beyond it. Points there are real, on-B-Rep
  points (confirmed to 1.4e-14mm across 3 independent evaluation paths) that
  the old projector could never find a zero-distance match for, since it
  only searched inside `Bounds()`.
- 2 new regression tests in `tests/test_parting_line_v2_level1.py`.

**Verification:** all 4 H0 failures on Part3 @ +X and all 4 @ +Y are gone
(0/329, 0/325 candidates) — the same candidates now correctly fail H3/H4
instead (candidate counts unchanged), confirming H0 passing is necessary but
not sufficient, not a route to `feasible` on its own. Controls (F4 sphere,
F17 barrel loft, F3 cylinder) unchanged — their trim extents were already
inside `Bounds()`. Full regression suite: 477 passed (+2) / 4 skipped / 3
failed, same 3 pre-existing-and-unrelated failures as every prior run in
this investigation (2× missing `OPENAI_API_KEY`, 1× the already-documented
Part1 6-piece side-core fragmentation).

**Why:**
Closes the diagnosis opened the same day (mechanism 1, D-023) once it became
clear the 4 H0 failures it was traced to were actually caused by a separate,
independent issue in H0's own OCC usage. Diagnosed first (4 independent point
representations traced and compared, with a control group proving this
isn't generic OCC/BSpline behavior) and only then fixed, per explicit
instruction not to touch H0 until the discrepancy was understood.

---

### 2026-08-12 — P3.1: direction-contamination audit, Track-B boundary refinement (mechanism 1), H0.3 projection discrepancy root-caused

**What changed:**
- **Direction-contamination audit.** Found 7 of 22 P2/P3 corpus rows (Part1,
  Part3, 5 external parts) silently used the unvalidated upstream direction
  optimizer before `parting_line_profile.py`'s SKIP-by-default protocol
  existed. Re-measured Part1/Part3 at explicit controlled directions only
  from here forward (`PullDirectionInput(..., "manual")`). New fact: **Part1
  is already `feasible` at +Z** — invisible in the optimizer-only evidence.
- New instrumented, read-only diagnostics (self-checked against the real
  production functions on every run): `parting_line_connectivity_diagnostic.py`,
  `parting_line_h0_case_study.py`, `parting_line_track_b_termination_trace.py`,
  `parting_line_h0_surface_deviation_trace.py`.
- **Stitch snap tolerance widened** (`stitch_snap_tolerance_rel`, new config
  key) and its cut-detection loop scoped to `edge.adjacent_face_ids` (fixing
  a real, independent unscoped-proximity-search bug). Regression-clean, but
  measured to change the pruned-segment count by **exactly zero** on both
  real parts, at every controlled direction — do not read this as a fix.
- **Mechanism 1 implemented** (`track_b.py`): Track-B contours now refine to
  the true trim boundary (bisecting against `BRepTopAdaptor_FClass2d`)
  instead of stopping at the last marching-squares grid point classified
  inside — closes a real, measured 0.046–0.14 mm undershoot, traced directly
  to an actual H0 rejection (Part3 face 274). Measured, positive connectivity
  effect on Part3 (+X: 66→60 pruned segments, 4→3 components after 2-core;
  +Y: 69→61 pruned, 5→4 components). Does **not** make either real part
  `feasible`, and does **not** fix the 4 H0 failures it was traced to.
  Whole-suite runtime roughly doubled (379s→849s).
- **H0.3 `max_surface_deviation_mm` discrepancy root-caused, not fixed.**
  Traced Part3 face 274's exact H0-failing endpoint through 4 independent
  representations: point generation (`BRepAdaptor_Surface`, raw
  `BRep_Tool.Surface`, `GeomLProp_SLProps`) agrees to 1.4e-14 mm; the
  discrepancy is entirely in `GeomAPI_ProjectPointOnSurf`, which silently
  restricts its search to the surface's own declared `Bounds()`
  (`[0,1]×[0,1]`) rather than the face's real trim extent (which reaches
  `v=1.0121` — ~1.2% beyond `Bounds()` — confirmed via `breptools.UVBounds`).
  Verified against a control (F17/F3 fixtures: same check, `<1e-9 mm`) — not
  generic OCC/BSpline behavior, specific to this face's trim-vs-surface-domain
  relationship. Minimal fix identified (pass explicit trim bounds to the
  projector in `gates.py`) but deliberately **not implemented** this session.
- Mechanism 2 (face 317, 24.75 mm Track-A/B mismatch on a near-zero-draft
  boundary) — deliberately not investigated further; not established as a
  bug.
- All 6 new/changed decisions logged in full, with mathematics and evidence,
  as D-022/D-023/D-024 in `docs/DECISIONS_AND_ALGORITHMS.md`.

**Verification:** full regression suite 475 passed / 4 skipped / 3 failed
(all 3 pre-existing and unrelated: 2× missing `OPENAI_API_KEY`, 1× the
already-documented Part1 6-piece side-core fragmentation), confirmed
unchanged before and after every change this session.

**Why:**
Diagnosis-first discipline throughout, per explicit instruction: measure
before changing, isolate controlled-direction evidence from the
upstream-optimizer-contaminated evidence, verify every change against the
real failing cases rather than claiming success from a plausible-looking
mechanism. Two real, isolated, independently-revertable production changes
landed (`stitch.py` tolerance/scoping, `track_b.py` boundary refinement);
neither is claimed as more than what was actually measured.

---

### 2026-08-09 — P3: measure-then-build enumeration — and a decisive negative result

**P3a measured; P3b built exactly what the measurement justified; the
measurement then showed it bought nothing.** Corpus grown to **22 parts** — 15
synthetic + Part1/Part3 + **5 external models** found on disk (cones,
cylinders, tori, BSplines). New profiler `backend/validation/parting_line_profile.py`.
Suite **459 passed / 3 failed** (same pre-existing). 118 v2 tests.

**§6.1's build-order gate ran as specified.** The μ distribution over 22 parts:
`μ=1` 18.2%, **`2 ≤ μ ≤ 12` 77.3%**, `μ>12` 4.5% (median 4, p95 9). The gate
maps that to *"add bounded Johnson, still skip beam"* — so bounded Johnson was
written and **beam search never was**.

**Then P3b measured what Johnson bought: zero outcome changes across the whole
corpus**, at up to 22× the candidates (F10: 9 → 200, hitting the cap) and 10×
the runtime. The reason is structural and certain: **6 of the 8 failing parts
have `branch_node_count == 0`**, where every node has degree 2 and the
components *are* the only simple cycles — so Johnson and the basis are
identical there by construction. **Enumeration is provably not the binding
constraint.** Johnson is kept but **opt-in** (`enumeration_strategy: "basis"`),
per plan §11's "did complexity actually buy us something?".

**What the blocker actually is (B-20):** the silhouette segments exist but do
not connect. Part1 reduces 243 segments → 30 edges / 5 components (**88%
pruned as dangling**); Part3 252 → 8 / 3 (**97% pruned**). What survives are
small *local* cycles — boss rims — which is why Part1's candidates all fail
H4: a boss rim separates cleanly, but the larger region holds both up- and
down-facing faces. Measured non-welded endpoint gaps: **7e-05 to 2.4e-04 mm**
against a **3.08e-05 mm** weld tolerance — sub-micron, i.e. numerical, not
geometric. Named as the next diagnosis rather than attacked with more
machinery.

**`A_cauchy` quantified against exact geometry (B-19).** New rasterised
tessellation-union measurement (1024², ~0.1% error): overestimate is
**+58.75% on Part3**, **+35.17% on Part1**, median **+0.24%** corpus-wide —
near-exact on convex shapes, badly off on non-convex ones, exactly as the
bound predicts.

**`κ_min` deliberately NOT calibrated (D-020).** Of 196 candidates reaching
H7 the minimum coverage was 0.950; H7 **rejected nothing on any part**. The
data supports no threshold, and the denominator is unreliable precisely where
one would matter. Left provisional at 0.50 and documented as currently inert —
the plan's own instruction for this case.

**No optimization performed (D-021).** v2 is **11.8%** of corpus runtime;
88.2% is upstream `load_step` + the direction optimiser (teammates' module).
§12.5 rule 2 forbids optimizing a stage the profile did not identify.

**Three defects found and fixed:** Johnson dropped **self-loops** (D-018 —
D-006's failure mode by a second route, which removed F9's hole rim); subset
unions were ordered **size-descending** so 4-subsets consumed the cap before
pairs were tried, breaking F9 (D-019); and multi-curve Γ was generalised from
pairs to **subsets** of up to 4, since Part3's 3 disjoint cycles left only the
triple untried.

### 2026-08-09 — P2: v2 Level 1 — Track B, face-interior silhouette curves

Track B (marching squares + Newton on `g(u,v) = 0`), Track A ↔ Track B
stitching, H3's face-splitting and sub-edge forms. **16 of 17 corpus fixtures
feasible** (P1: 12). Suite **459 passed / 3 failed** (same pre-existing
failures). 52 v2 Level-0/1 tests + 62 contract tests.

**The three Track B fixtures are solved exactly**: F4 sphere → great circle
(`|z| < 1e-6`, `r = 20.000000`); F17 barrel → circle at `z = 20.0000`,
`r = 16.0000`, strictly inside a BSpline face; F3 cylinder ⟂ pull → two
rulings at `|y| = 15.000000`, `|z| < 1e-6`. F3 needs **both tracks**
(`mix = {edge: 6, face: 2}`) — Track B's rulings stitched to Track A's rim
arcs.

**The P2 exit gate was honoured, and it reversed the first conclusion.** The
gate said: if Part3's component count does not drop sharply from 22, the RC-1
hypothesis is wrong and we stop. Measured at `+Z` it did **not** drop
(18 → 18, μ 110 → 110, Track B found zero segments — 317 faces have no
interior sign change, 97 are zero-draft bands). But `+Z` is not Part3's
optimal direction, and B-5 already measured a 23× direction sensitivity. At
its **optimal** direction: Track B finds **203** segments, components
**22 → 3**, μ **110 → 3**. Part1 likewise μ **82 → 5**. Hypothesis confirmed;
the earlier reading was measuring a direction where the part is largely
zero-draft.

**Consequence for P3 (§6.1's build-order gate):** with μ now 3–5 at optimal
directions, enumerating every simple cycle is trivially affordable. Track B
did not only find curves, **it collapsed the combinatorics**. Both real parts
still have no feasible candidate — Part1's 5 candidates all fail H4, Part3's 6
all fail H3 — which is exactly the documented Level-1 limitation: a cycle
*basis* spans the cycle space but its members need not be the physically
meaningful loops. That is now the clearly-indicated next step, chosen on
evidence.

**Six defects found by measurement**, all with mathematics in
`docs/DECISIONS_AND_ALGORITHMS.md` (D-011…D-016):
1. **`regions.py` never imported `BRep_Tool`** — `_g_at_edge_on_face` raised
   `NameError`, was swallowed, returned `None`, and both of F17's planes
   attached to the same side of the split face.
2. **The Cauchy denominator was not area-weighted** (D-011). Uniform `(u,v)`
   sampling oversamples a sphere's poles: `2/π ≈ 0.637` vs the true `0.5`, a
   27% error that made the exactly-correct great circle score 80.7% coverage.
   `face_sample_grid` raised 5 → **11**, chosen from a measured convergence
   table against `πr²` (−4.89% at 5×5, −1.02% at 11×11).
3. **Track A discarded single-sample runs** (D-013), which sat exactly where
   F3's rulings meet the rim — leaving each arc ~1.4 mm short of the junction,
   so nothing welded and 2-core deleted everything.
4. **The tracks were never stitched** (D-012) — they meet in space but share
   no endpoint, so the graph had no node where they touch.
5. **H3 needed its face-splitting form** (D-014) and, unpredicted, **sub-edge
   granularity** (D-015): Γ covers only the *upper semicircle* of F3's rim, and
   treating coverage as per-edge severed a connection that is still real.
6. **A seam artefact produced false crossings** (D-016): `g` is discontinuous
   at a parametrisation seam, flipping sign without passing through zero.
   Measured on Part3 face 407 — a run at `u = 1.0` with `g` alternating
   ±0.825. H0.3 correctly rejected it; Track B now refuses to emit it.

**Runtime regressed and is not optimized**: p50 31.9 → 67.1 ms, Part3
11.9 → 44.4 s. Per §12.5 rule 2 no optimization was attempted — the corpus
profile has not been taken. Recorded as the number P3 must not worsen.

### 2026-08-09 — P1: v2 Level 0 — Track A, hard filter H0–H7, lexicographic ranking

The first algorithm in `backend/geometry/parting_line_v2/`. v1 is untouched and
remains the default engine. **436 passed / 3 failed** (same 3 pre-existing
failures as P0, unrelated); 33 new Level-0 tests, 62 contract tests.

**New modules**: `track_a.py` (sharp-edge silhouette with **edge-local**
normals), `graph.py` (welding, 2-core reduction, cycle extraction),
`measures.py` (pure geometry, no OCC), `regions.py` (H3 + core/cavity),
`gates.py` (H0–H7), `ranking.py` (lexicographic T1–T7), `engine.py`.

**Three real bugs found by measuring against fixtures with known answers**,
all documented with their mathematics in `docs/DECISIONS_AND_ALGORITHMS.md`:

1. **The silhouette condition must be inclusive** (D-005). Across a sharp edge
   the normal is *set-valued* and sweeps the arc from `n̂_a` to `n̂_b`, so `g`
   attains every value between `g_a` and `g_b`: the test is
   `0 ∈ [g_a, g_b]`, not `g_a·g_b < 0`. On a cube (top `g=1`, side `g=0`) the
   strict product gives `1×0 = 0` — not negative — so the first implementation
   found **no silhouette on the cube's top rim**. Fixed: 8 silhouette + 4
   tangential segments, the analytic answer.
2. **A closed circular edge is a graph self-loop of degree 2** (D-006).
   Recorded once it has degree 1, and the 2-core prune deletes it as a
   dangling end — silently discarding F2's and F5's rim circles (which *are*
   those parts' correct parting lines) and F9's hole rim.
3. **The Cauchy projected area needs the integral of `|g|`, not a centroid
   sample** (D-008). The single-sample form has no bounding property and
   produced **coverage = 104.4%** on F7 — a loop covering more than the whole
   part. With the integral, F7 reports exactly 100.0%.

**A flaw in the plan's own formal statement, caught by H3** (D-007): C1
required `Γ ≅ S¹`, a single closed curve. On F9 (box + through-hole) cutting
the outer rim alone leaves the top face connected to the bottom **through the
hole wall** → H3 reports 1 region. The `Γ` that separates is
**outer rim ⊔ hole rim**. C1 corrected to *a disjoint union of simple closed
curves*; a genus-`g` part generally needs `g+1`. Holes are ubiquitous in real
plastic parts, so the single-curve model would have made much real geometry
unanalysable. Implementation is bounded: pairs only, formed only from
candidates that failed H3 with exactly one region, only when round 1 found
nothing.

**Measured (`reports/p1_level0.json`)**:
- **H0 holds to 1.3e-14 mm** across the corpus — points come from
  `BRepAdaptor_Curve.Value(t)`, so the curve is on the part by construction.
- **F3 (cylinder ⟂ pull), F4 (sphere), F17 (barrel) report
  `no_feasible_candidate`** with a stated reason. At P0 the equivalent v1 runs
  returned **`status = ok`** with 0.0% coverage on the same shapes.
- F1 cube: `μ = E−V+P = 12−8+1 = 5`, 5 basis cycles, 3 rejected at H4, the two
  survivors (top and bottom rim) tie on every tier and are decided by **T7** —
  exactly the equal-optima case. Length 160.0 mm = 4×40.
- F11 `μ=25` and Part3 `μ=110` — real mass above `mu_max_for_johnson=12`, both
  failing at H4. Early P3a evidence; **no enumeration built**, per §6.1's gate.

**A corpus gap found and closed**: F5/F6/F7 were predicted to need Track B and
**do not** — F6's fillets span `g ∈ [0,1]` and F7's loft faces are all `g > 0`,
so both only *touch* zero at a face boundary. The real criterion is whether
`g` **changes sign inside** a face. That meant **no fixture actually exercised
Track B**. Added **F17** (lofted barrel, one BSpline face with
`min_g = −0.47`, `max_g = +0.47`, no B-Rep edge near the answer) so P2 has
something real to prove itself against. Plan and manifest expectations
corrected to match measurement.

Also fixed while building: a module-level mutable dict used as per-call
scratch in `engine.py` (would have leaked regions between requests in the
stateless backend), and the deprecated `breptools_UVBounds` call.

---

### 2026-08-09 — P0: v2 parting-line engine — contracts, fixture corpus, A/B baseline

First phase of the parting-line / core-cavity rebuild scoped in
`docs/PARTING_LINE_ALGORITHM_PLAN.md`. **No algorithm code** — P0 is
contracts, fixtures, and the harness that makes every later phase measurable.
v1 is untouched and remains the default engine.

**Preceded by two analysis documents.** `docs/PARTING_LINE_CORE_CAVITY_AUDIT.md`
reads the existing `parting_line.py` (4,746 lines) and `core_cavity.py` and
records 11 root causes; `docs/PARTING_LINE_ALGORITHM_PLAN.md` specifies the
replacement through Levels 0–2 (Level 3/4 explicitly deferred).
`docs/DECISIONS_AND_ALGORITHMS.md` is a new running log of every decision and
algorithm **with its mathematics and its reason**, maintained from here on.

**New package** `backend/geometry/parting_line_v2/` (`types.py`,
`contracts.py`, `timing.py`). Two invariants are encoded *structurally* rather
than checked later:
- `CurveSegment` **cannot be constructed without an OCC backing** —
  `EdgeBacking(edge_id, t_start, t_end)` or `FaceBacking(face_id, uv)`, with
  one UV pair per point. A curve that is not recoverable as `C(t)` or `S(u,v)`
  is unrepresentable, which is the structural fix for the levitating-curve
  defect (audit RC-7).
- **No `confidence`/`readiness` field exists anywhere in v2** and a test
  forbids adding one. No labelled outcomes exist, so no calibrated
  probabilities can.

**Module boundaries enforced by AST test, not convention**
(`tests/test_parting_line_v2_contracts.py`, 48 tests, all passing): no module
may import `side_core` (H5 emits a `SideActionReferral`, never routes), and no
generation/ranking module may import a surface provider (the parting line is a
geometric result independent of the planar split approximation).

**Config**: new `dfm.parting_line_v2` block (26 keys, every threshold that v2
will use) plus `dfm.parting_line.engine: "v1" | "v2"`, defaulting to **v1**.
`κ_min` is **0.50 and labelled provisional** — a configuration decision, not a
manufacturing law; calibrated from corpus data in P3a. Added a
`_replace_scalars` config helper so a 26-key block does not need 26
near-identical coercion lines.

**Fixture corpus**: `scripts/generate_fixtures.py` builds 14 synthetic STEP
fixtures into `data/fixtures/synthetic/` (**`data/parts/` untouched** —
invariant #2), each targeting a named algorithmic failure mode with a
checkable answer, plus a `manifest.json` carrying the expected result and the
P1 expectation. All 14 load cleanly through `step_loader` with 100% valid
normals.

**A/B harness**: `backend/validation/parting_line_ab.py`.

**Measured baseline** (`reports/baseline_p0.json`, `..._optimized.json`; full
analysis in `DECISIONS_AND_ALGORITHMS.md` §M-P0):
- **The harness is trustworthy** — Part1 at its optimal direction reproduces
  94.8% coverage / 12 components and Part3 18.1% / 22, matching `STATUS.md`
  exactly.
- **Track A's blindness is now measured, not just argued.** F2/F3/F4/F5
  (cylinder ∥ pull, cylinder ⟂ pull, sphere, cone) all return `closed=False`,
  **0.0% coverage**, surface `failed` — the four fixtures whose silhouette
  lives in a face interior. F3's correct answer is analytically known (two
  straight rulings at `u = φ ± π/2`).
- **v1 does not fail loudly.** All four returned `status = ok`. Audit RC-4
  reproduced on demand in four independent cases — the strongest justification
  for the H0–H7 hard filter.
- **96.6% of runtime is spent on a surface that then fails.** On a *six-face
  cube*: 5.457 s of 5.66 s inside `BRepFill_Filling_Build`, fed a loop that
  Chaikin inflated from **9 raw points to 24,321** (2,702×) before decimating
  back to 120 constraint edges — and the surface fails anyway. Not optimized
  yet, per plan §12.5 rule 2 (never optimize a stage the corpus profile did
  not identify); recorded so P2 has a number to beat.
- **23× sensitivity to pull direction** — Part1 scores 4.1% at `+Z` vs 94.8%
  at its optimal direction. First hard evidence for the §12.6 sensitivity
  work, and it reframes it: a parting-line result quoted without its direction
  is close to meaningless.

**Verification**: 48/48 new tests pass; full suite **389 passed, 3 failed, 4
skipped**. All 3 failures confirmed **pre-existing and unrelated** by
re-running them with `backend/config.py`/`config.yaml` stashed — identical
failures (`test_agent_providers` ×2: `httpx`/`openai` `proxies` kwarg
incompatibility; `test_side_core` real-export: reloads 6 solids vs an expected
3, the already-documented S4.3 disconnected-compound behaviour).

---

### 2026-07-29 — S4.3: generalize side-core generation to multiple/grouped features

`backend/geometry/side_core.py` gains `MultiSideCoreResult`,
`select_side_core_features()`, `generate_side_cores_for_features()`, and
`combine_side_cores_per_half()` — the roadmap §4.3 Q1 generalization from
Stage 4's single highest-confidence feature to every qualifying feature
(default: every "critical" feature; callers can widen to
`("critical", "minor")` etc. and cap the count). Every feature is measured
independently against the SAME pristine `cavity_solid`/`core_solid` (§4.3
Q5), never a half already reduced by an earlier feature's cut, so results
never depend on generation order. `generate_primary_side_core` (Stage 4's
original single-feature entry point) is unchanged and still available —
this is additive, not a replacement.

**A real sizing bug found and fixed first** (surfaced by a face grouping
neither original Stage 4 test exercised — see the previous entry's
robustness finding): `_feature_footprint_half_size()` now sizes its
Boolean sweep-tool plane from the `footprint_percentile`-th (default 0.75)
ranked Bnd_Box corner radius, not the max. Part1's 11-face critical
feature at `detect_undercuts()`'s default settings has one face (225)
sitting ~5.5mm from an otherwise tightly-clustered 10-face group
(~0.6-2.3mm spread); a max-based plane dragged out by that single outlier
measured a real 36.59% volume-conservation error, vs. 0.00% at the 75th
percentile. No regression on either previously-verified case (percentile
and max coincide when there's no lone outlier). New config key:
`dfm.side_core.footprint_percentile` (0.75).

**Two more real findings, surfaced while building the STEP export gate for
the multi-feature case** (both are geometric facts about Boolean results
on real, spatially-complex feature groupings — not defects, and both now
documented in `side_core.py`'s module docstring so no future session
mistakes them for bugs):
1. A single feature's `side_core_solid` can itself be a multi-piece
   (disconnected) compound. Part1 feature 0 (the same 11-face grouping
   above): its side core is a 5-piece compound (251.0/75.4/82.4/3.6/4.5
   mm3) — `BRepAlgoAPI_Common` between a swept plane and a non-convex
   11-face region legitimately fragments. Volume conservation is
   unaffected (0.0028% error); only the solid count changes.
2. Two or more features' individual `side_core_volume_mm3` values can
   overlap in physical space when they're near each other. Measured on
   Part1: 4 adjacent feature pairs overlap by ~21.4mm3 each, ~128mm3
   total. **First diagnostic attempt** exported each of Part1's 8
   generated side cores as a SEPARATE STEP body alongside one combined-
   reduced core half: the export reported `solid_count: 10` (bodies
   passed to the writer) but reloading found **14** actual `TopAbs_SOLID`
   shapes with total volume 34639.0mm3 vs. the original 34508.5mm3
   tooling volume (≈0.38% inflation) — fully explained by finding #2's
   double-counted overlap, not a Boolean-tolerance defect (verified via
   direct pairwise `BRepAlgoAPI_Common` between every side-core pair).

**Fix: `combine_side_cores_per_half()` now returns a real
`CombinedHalfSideCoreResult` per half** (fused-side-core volume,
reduced-half volume, `overlap_volume_mm3` = `sum(individual volumes) -
fused volume`, and its own conservation error) instead of a bare shape
dict, and the STEP export path (both `/parts/{filename}/core-cavity` and
`/parts/{filename}/export/mold-halves`) exports AT MOST ONE combined body
per half — never one raw body per feature. Re-verified end-to-end on
Part1 @ (0,0,1) with all 8 critical+minor features: exported
`solid_count: 3` (cavity, reduced core, one combined side-core body),
reloaded solid count 8 (cavity=1, reduced core=1, combined side-core
body=6 — the 6 is finding #1 again: 5 fragments inherited from feature
0's own compound, fused with 1 blob from features 1-7, which mutually
overlap in a connected chain and so fuse into a single region), reloaded
total volume 34509.99mm3 vs. original 34508.54mm3 — **0.0042% error**,
down from the first attempt's 0.38%.

**API**: `/parts/{filename}/core-cavity` and
`/parts/{filename}/export/mold-halves` both gain
`multi_feature_side_cores` (bool), `side_core_severities` (comma-separated,
default `"critical"`), `side_core_max_features` (optional cap) query
params, additive alongside the existing single-feature
`generate_side_core` flag. Responses include both per-feature diagnostics
(`side_cores`) and the per-half combined/conserving result
(`side_core_combined`) — callers must never sum `side_cores[*].
side_core_volume_mm3` across features sharing a half (see finding #2).
Verified live against the running Docker backend, not just pytest.

**Tests**: new `test_real_multi_feature_side_core_combines_and_exports_on_part1`
in `tests/test_side_core.py` — the multi-feature analogue of Stage 4's
single-feature export gate. Deliberately asserts a *floor* on reloaded
solid count (`>= 2 + combined bodies`), not an exact count, since a
combined body's internal solid count is data-dependent (finding #1); does
assert the two things that must always hold: cavity and each reduced main
half stay exactly 1 solid, and total reloaded volume conserves within
tolerance. All 12 tests in the file pass (3 new/modified,
9 pre-existing); full project suite re-run with no regressions.

**Honesty**: the side-core generator can now be described as "generates
one side core per qualifying undercut feature (not just the single
highest-confidence one), each independently Boolean-verified, then
combined into at most one exported body per mold half — verified
volume-conserving to <0.01% on Part1's real 8-feature case." Still never
claim it merges spatially-close features into a single SHARED side-core
*shape* before generation (§4.3 Q1 — each feature's sweep geometry is
still generated independently; only the post-hoc combination for export
is shared), and still never claim it decides lifter vs. slide vs.
collapsible-core (§4.3 Q4 — unchanged from Stage 4).

---

### 2026-07-29 — Stage 6: PDF report export (roadmap §5) — the last major roadmap gap

New `backend/report/` package: `pdf_export.py` (reportlab Platypus document
builder) + `templates.py` (styles/layout helpers). `reportlab` had been
pinned in `requirements.txt` since the initial scaffold and imported
nowhere — this is what finally uses it.

**Pure presentation layer, per roadmap §5.5's honesty constraint.**
`build_dfm_report_pdf()` takes the same `.to_dict()` payloads every
analysis endpoint already returns as JSON (part summary, draft, undercuts,
parting line, core/cavity, optionally direction/solid-split/side-core/AI
agent narrative/a frontend-supplied screenshot) and lays them out — it
recomputes nothing. Every warning or degraded-confidence flag from any
source (`parting_line.warnings`, `core_cavity.warnings`, undercut Boolean
reliability, `split_tool_kind="planar_approximation"`, a failed side-core
generation, the AI agent's own `analysis_warnings`) is aggregated into a
"Warnings" section at the top of the report — nothing gets dropped for a
cleaner-looking page.

**Two real bugs found and fixed while verifying against real Part1.stp
data** — both were **known bug patterns from earlier stages that this new
module had silently reintroduced**, not new defects in the underlying
engine:
1. **`best_label` duplication** (the exact bug fixed in `frontend/app.py`
   during S3.5): `direction_optimizer.py`'s `_direction_label()` falls back
   to the raw vector string for non-axis-aligned directions, so printing
   `best_label` and `best_direction` as separate rows produced
   `"(+0.232, +0.357, +0.905)"` twice. Fixed with a `pdf_export.py`-local
   `_direction_label_display()` mirroring the frontend's own guard
   (`len(label) == 2 and label[0] in "+-" and label[1] in "XYZ"`).
2. **Misleading 100% "conservation error" for `side_core.status ==
   "no_feature"`**: `SideCoreResult.conservation_error` defaults to `1.0`
   (an unset placeholder, not a measurement) when no side core was
   generated at all. Rendering it unconditionally read as "100% error" for
   a state that isn't an error — it means "no undercuts at this pull
   direction," exactly as designed. Fixed by branching on `status` before
   rendering volumes, matching the frontend's own existing three-way
   `generated`/`no_feature`/other conditional for this exact field.

**A genuine, previously-undocumented robustness finding while re-verifying
`side_core.py` for this section**: re-running Stage 4's side-core
generation on Part1 at a manual `(0,0,1)` pull direction — the same
direction, but with `detect_undercuts()` called at its (unspecified,
therefore default `max_boolean_faces=120`) settings rather than the
diagnostic script's earlier `max_boolean_faces=20` — grouped a different,
larger face set into the "highest-confidence critical feature" and hit a
genuine **36.59% volume-conservation error**. `side_core.py` correctly
reported `status="failed"` with the real numbers rather than silently
returning bad data — the module's own honesty check did exactly its job.
This is a real robustness gap in the current single-feature/single-sweep
approach on more complex face groupings, not a regression in this PDF
work; it directly informs the upcoming S4.3 generalization (grouped/
multi-feature side cores) and is tracked there rather than "fixed" here.

**API**: `POST /parts/{filename}/export/report` — `use_optimal_direction`/
`dx`/`dy`/`dz` (S3.6 pattern), `include_solid_split`/`include_side_core`/
`include_agent_narrative` (all opt-in, each degrades gracefully — a failed
or unavailable AI agent call never blocks the rest of the report), an
optional JSON body (`ReportScreenshotPayload.screenshot_png_base64`) for a
frontend-supplied screenshot. Returns `application/pdf` with a
`Content-Disposition: attachment` header. Verified live via FastAPI's
`TestClient`: a full report end-to-end, the missing-part 404 path, an
invalid-base64 400 path, and a real embedded-screenshot round trip.

Screenshots are explicitly frontend-supplied, never backend-rendered —
CLAUDE.md invariant #3 keeps OCC/rendering out of anything client-facing,
and the reverse holds too: the backend has no renderer and must not gain
one to rasterize a viewport itself.

**Frontend**: new "PDF Report" section (checkboxes for solid split/side
core/AI agent narrative, "Generate PDF Report" button, `st.download_button`
once bytes are available). Honors an active direction override (S3.6) —
if one is active, the report uses that exact direction rather than
silently falling back to the optimizer's recommendation. Verified via
Streamlit `AppTest`: a real click through the actual UI produces real PDF
bytes with no exception.

**Tests**: 18 new tests in `tests/test_pdf_export.py` — pure-function
coverage for `_collect_warnings` (every warning source, including the
"no_feature is not a warning" negative case) and `_direction_label_display`
(the exact duplication regression), structural PDF validity checks
(`%PDF` header, `%%EOF` trailer, non-trivial size) against both hand-built
minimal/all-sections-populated inputs and real Part1.stp/Part3.stp
geometry through the full pipeline. All 18 pass; full project suite
re-verified with the new package in place.

**Honesty**: PDF report export can now be described as "implemented — a
presentation-only PDF builder over the same result dicts every analysis
endpoint already returns, verified end-to-end against real Part1.stp/
Part3.stp data" — not as "the report includes agent narrative or a
screenshot by default" (both are opt-in and the report must generate
without either) and not as "side-core generation is fully robust across
all feature groupings" (see the conservation-error finding above, now
tracked under S4.3).

---

### 2026-07-28 — Stage 5: AI agent orchestration layer (roadmap §4)

New `backend/agent/` package — the first code this layer has ever had.
Before this, `backend/agent/dfm_agent.py` and `backend/agent/tools.py` were
both genuinely 0 bytes; per `.claude/rules/honesty-and-scope.md` neither
could be described as implemented, partial, or scaffolded. Implements the
roadmap's full Stage 5 design: `providers.py` (provider-agnostic
`LLMProvider` abstraction), `tools.py` (6 tools wrapping the geometry
engine), `schemas.py` (pydantic `DfMReport`/`DfMFinding`), `prompts.py`
(system prompt enforcing this project's honesty rules), `dfm_agent.py`
(the tool-calling orchestration loop).

**Provider choice, resolved against real conflicting evidence.** The
roadmap's original 2026-07-26 decision names Gemini as default with
Anthropic/OpenAI as adapters — but the *actual* `docker-compose.yml` only
ever wired through `OPENAI_API_KEY`/`GROK_API_KEY`, and `requirements.txt`
already pinned `langchain-openai`/`openai`, never `google-generativeai` or
`anthropic`. Per the honesty rules' authority table (actual source/config
outranks a planning doc), this was flagged to the user rather than silently
resolved either way. User chose "provider-agnostic, all three adapters" —
Gemini, Anthropic, and OpenAI all built, with Grok added as a fourth,
low-cost option reusing the OpenAI adapter class via its OpenAI-compatible
endpoint (exactly matching the scaffold that was already there).

**Real Gemini API key provided and verified live, matching this project's
established practice of testing against real behavior rather than mocks.**
Two real findings during that verification, before any code was written
against a wrong assumption:
1. The user's key authenticates and lists models successfully, but
   `gemini-2.0-flash` (the roadmap's original pick) returns **zero free-tier
   quota** — confirmed via a live `generateContent` call returning HTTP 429
   `RESOURCE_EXHAUSTED` with `limit: 0`. `gemini-2.5-flash` and
   `gemini-flash-lite-latest` both work with real successful responses on
   the same key. User chose `gemini-2.5-flash` as the default model.
2. `google-generativeai` (the roadmap's named package) is the **legacy**
   SDK — the actually-installable, currently-maintained package is
   `google-genai` (verified: `pip install google-genai` → real client,
   real live tool-calling round trip against the actual API). Used
   `google-genai==2.14.0` instead of guessing at the legacy package's API
   surface, which would likely have been stale or wrong.

**Real, live, end-to-end verification of the full orchestration loop** —
not just unit tests — against `Part1.stp` via `run_dfm_analysis()` and
through the actual `/parts/{filename}/agent/analyze` API endpoint: the
agent called `optimize_pull_direction` (and, on a separate run, chained
`analyze_draft` + `detect_undercuts` after it), received real geometry
results (`best_direction=(0.232, 0.357, 0.905)` — matching the exact value
independently established in earlier sessions), and returned a real,
schema-valid `DfMReport` citing a genuine measured finding: face 232 at
1.075° draft against a 1.5° minimum, `evidence_source="boolean_confirmed"`,
a concrete recommendation. "No undercuts detected" correctly matches what
this project already knows about Part1's optimal direction (the direction
optimizer specifically searches for undercut-free directions).

**One real bug found and fixed during that live verification**: once
`optimize_pull_direction` establishes the pull direction as `"optimal"`,
the system prompt (correctly) instructs the model to pass that exact
vector into every subsequent tool call so all analyses stay mutually
consistent — but the original `_track_direction()` logic naively
re-classified "a `pull_direction` argument was supplied" as
`"user_specified"`, silently downgrading a real optimizer result to a
fabricated user-override label on every propagating call after the first.
Fixed: once `"optimal"` is set, it wins for the rest of the run regardless
of what direction values get echoed into later tool calls. Locked in with
`tests/test_dfm_agent.py::test_track_direction_optimal_source_is_not_overwritten_by_propagated_calls`.

**A second real bug, found while wiring the tests, not the live call**:
after installing `google-genai`/`anthropic` alongside the already-pinned
`openai==1.25.0`, pip resolved a modern `httpx` (0.28.1) as a shared
dependency — but `openai==1.25.0` still passes `Client(proxies=...)`
internally, a kwarg httpx 0.28 removed (replaced by `mounts`/`proxy`).
Confirmed live: `openai.OpenAI()` raised `TypeError: unexpected keyword
argument 'proxies'` the moment any tool called the OpenAI or Grok adapter —
a real production bug, not just a test artifact. Fixed by bumping to
`openai==1.109.1` (verified compatible with httpx 0.28.1 in the same
container).

**Design decisions, each resolving one of the roadmap's stated open
questions**:
- Tool result matching: Gemini matches by function **name** (no per-call ID
  in its wire format); Anthropic/OpenAI match by a unique call **id**.
  `ToolCall` carries both fields so every adapter uses whichever it needs.
- `temperature` is never sent to the Anthropic adapter — Claude Opus 5 (the
  configured default Anthropic model) rejects sampling parameters entirely
  (400), per current Claude API behavior; steering happens via the system
  prompt instead.
- The four "hard rules" from the roadmap (never return OCC handles, always
  `mutate=False`, truncate aggressively, surface failures as data not
  exceptions) are enforced structurally: every tool's payload is a
  dataclass's own `.to_dict()` (never touches `occ_*` fields), every
  geometry call passes `mutate=False` explicitly (belt-and-suspenders — the
  S3.8 `load_step_cached()` clone-per-call guarantee already makes this
  concurrency-safe regardless), face-ID lists are capped at
  `agent.max_face_ids_per_tool` (default 25) with a `truncated: true`
  marker, and a `_tool_safe` decorator catches every exception and returns
  `{"status": "error", "code", "message", "recovery_hint"}` — the same
  structured shape `backend/api/main.py` already uses.
- `tools_called`, `pull_direction`, and `pull_direction_source` on the
  final `DfMReport` are tracked **mechanically** from what actually
  executed, never reported by the model in its own JSON output — an agent
  narrating its own audit trail is exactly the class of claim this
  project's honesty rules exist to prevent.
- The final-turn output contract is plain JSON via a documented prompt
  instruction (not a provider-specific structured-output API), matching
  the "author once, keep every adapter trivial" philosophy already applied
  to tool schemas — `_parse_report()` tolerates a stray markdown code fence
  and falls back to a structured "did not complete" report (never raises)
  on invalid JSON or a pydantic schema mismatch.

**Config**: `config.yaml`'s `agent:` block replaced (`model`/`temperature`
→ `provider`/`temperature`/`max_tool_iterations`/`max_face_ids_per_tool`/
`models.{gemini,anthropic,openai,grok}`); `backend/config.py` gained
`AgentModelsSettings` + updated `AgentSettings`. `.env` (gitignored) holds
the real `GOOGLE_API_KEY`; `docker-compose.yml`'s backend service gained
`GOOGLE_API_KEY`/`ANTHROPIC_API_KEY` pass-through alongside the
already-existing `OPENAI_API_KEY`/`GROK_API_KEY`. `requirements.txt` gained
`google-genai==2.14.0` and `anthropic==0.120.1`, and bumped
`openai` 1.25.0 → 1.109.1 (see the httpx conflict above).

**API**: `POST /parts/{filename}/agent/analyze` (optional `query`/`provider`
query params, runs the full tool-calling sweep and returns a `DfMReport`)
and `GET /agent/providers` (which providers are importable in this
environment vs. configured) — both verified live end-to-end via FastAPI's
`TestClient` against the real backend, including both structured-error
paths (missing part → 404 `part_not_found`; unknown provider name → 400
`agent_configuration_error`).

**Frontend**: new "AI Agent" tab — provider selector (seeded from
`/agent/providers`), optional focus-query text input, "Run AI DfM Review"
button, and a findings display (severity icon, category, evidence source,
confidence, affected faces, measured values, recommendation, tooling
impact) plus a tools-called audit-trail expander and full report JSON.
Verified via Streamlit `AppTest`: the tab renders with no exception, and a
real click through the actual UI (not just the API) completes the full
round trip against the live backend.

**Tests**: 52 new tests across `tests/test_agent_schemas.py`,
`tests/test_agent_providers.py`, `tests/test_agent_tools.py`,
`tests/test_dfm_agent.py` — pydantic schema validation, the JSON-Schema →
Gemini `types.Schema` converter, provider dispatch (including the Grok/
OpenAI-adapter-class-sharing case), all four hard rules against real
Part1.stp geometry (including a direct verification that tool calls never
mutate the shared `load_step_cached()` template), the orchestration loop's
batching/bounding/direction-tracking logic via a scripted fake provider,
and `_parse_report`'s tolerance for malformed model output. All 52 pass;
full project suite re-verified with the new package in place.

**Honesty**: the agent layer can now be described as "implemented — a
provider-agnostic tool-calling agent that drives the same deterministic
geometry engine as the rest of the app, verified live end-to-end against
real Part1.stp geometry through Gemini" — not as "fully productionized"
(no streaming `/agent/chat` endpoint yet, no persisted conversation state,
Anthropic/OpenAI/Grok adapters are structurally verified and unit-tested
but not live-tested against real accounts) and not as validating the
engine's own analysis quality (the agent narrates and prioritizes what the
tools already compute; it does not add new geometric capability).

---

### 2026-07-28 — Stage 4: side-core / lifter solid generation (Bosch criterion #5, first increment)

New `backend/geometry/side_core.py` — the first geometry Bosch criterion #5
has ever had. Before this, `grep` for lifter/side-core work found only
*recommendation strings* in `undercut_detector.py`
(`"lifter-or-collapsible-core-review"`); no side-core solid, no side-core
pull direction, nothing geometric. This implements the roadmap's explicit
"suggested first increment" (§4.4): one side-core solid for the single
highest-confidence critical undercut feature, subtracted from whichever
mold half contains it, exported as a third solid.

**Scope decisions** (roadmap §4.3 posed six open design questions before
estimation was possible — each is answered explicitly in `side_core.py`'s
module docstring, not left implicit):
1. Per-feature only, not grouped — `select_primary_side_core_feature` picks
   the single highest-interference critical feature.
2. `release_direction` used verbatim from `UndercutFeature`, never snapped
   to a machine axis — the undercut engine already computed it from real
   Boolean-confirmed geometry.
3. NOT built on `BRepFill_Filling` (the roadmap's own speculated "most
   likely" approach) — that machinery is confirmed topologically invalid on
   both real parts for the *main* parting surface (Stage 2, S2.3), and there
   is no reason to expect it more reliable on a smaller, still-curved side
   feature. Reuses Stage 2b's proven fix instead: a flat planar
   Boolean-split tool (`core_cavity.build_planar_split_tool`), sized to the
   feature's own local footprint and swept along `release_direction`.
4. Lifter vs. slide vs. collapsible-core classification is explicitly NOT
   decided — this module answers "what volume of steel must retract, and
   along which direction," not "what kind of moving part does it." Never
   claim this module selects a tooling mechanism.
5. Containing-half selection: `BRepAlgoAPI_Common` against BOTH
   `cavity_solid` and `core_solid` directly; whichever has the larger
   overlap volume is subtracted from.
6. Exported as a third solid in the SAME AP214 STEP file as cavity/core —
   `core_cavity.export_mold_halves` gained `solid_overrides`/`extra_solids`
   parameters rather than `core_cavity.py` importing from `side_core.py`
   (which already imports from `core_cavity.py` — would have been circular).

**Two real bugs found and fixed while prototyping against real Part1/Part3
geometry, both load-bearing enough to be regression-tested, not just fixed
and forgotten:**

- **Footprint sizing must use each feature face's `Bnd_Box` corners, not
  face centroids or vertex-only sampling.** Face-centroid scatter is zero
  for a single-face feature (Part3 feature 0 is exactly one face), flooring
  the sweep plane to a useless 2mm minimum regardless of the face's true
  size (measured: `side_core_volume=297.0mm³` against a feature with
  `total_area_mm2=339.3` — clearly wrong). Vertex-only sampling then under-
  measured curved-edge faces: a circular arc's widest point relative to the
  feature centroid is generally NOT at either endpoint vertex. Measured on
  Part3 face 37: vertex sampling gave a 1.50mm perpendicular radius while
  the face's real `Bnd_Box` spans 36mm — a ~24x undersizing. Switching to
  `Bnd_Box` corners (built from the actual underlying curve/surface
  geometry, so it gets curved extrema right) corrected the side-core volume
  to a geometrically sensible 46,967.3 mm³.
- **The fuzzy tolerance used to measure the side-core overlap
  (`BRepAlgoAPI_Common`) must be reused, unchanged, for the `BRepAlgoAPI_Cut`
  that removes it.** A mismatched pair (0.01 for the Common, a different
  hardcoded 0.1 for the Cut) measured a **37.72% volume-conservation error**
  on Part1 even though both Boolean operations individually reported
  success (`IsDone()` true, no errors) — this is a same-value invariant, not
  a "pick a safe default" tolerance. Root cause, confirmed by direct
  measurement: at fuzzy values above the one that succeeded for the
  `Common`, `BRepAlgoAPI_Common` can silently return a *different, smaller
  or empty* result while still reporting success — so reusing a different,
  larger "safe-sounding" fuzzy value for the following Cut operates against
  geometry that doesn't match what was actually measured. A consistent 0.01
  measured 0.00-0.02% error at every plane size tested, 1.0x-2.0x the
  feature's footprint.

**Validated end-to-end on both real demo parts** (single sample per part —
see `.claude/memory/known-gaps.md`). Both parts' *optimal* pull direction
specifically eliminates undercuts by design (that's what the direction
optimizer searches for), so there is nothing for a side core to act on
there — validation instead uses a fixed non-optimal direction known to
produce a real critical feature (matching the roadmap's own §4.2 worked
example, which does the same for Part1):

```
Part1 @ pull=(0,0,1): feature 0, 6 faces, depth 26.97mm
  side_core_volume=9219.8 mm³, containing_half=core, conservation_error=0.00%
Part3 @ pull=(0,0,-1): feature 0, 1 face, depth 40.01mm, release≈+X
  side_core_volume=46967.3 mm³, containing_half=cavity, conservation_error=0.00%
```

Roadmap Stage 4 §4.4's exact gate — **"the three solids (cavity, core,
side core) reload from STEP, and their volumes are consistent with the
blank minus the part"** — verified directly: exported both parts as
3-solid AP214 STEP files, reloaded with `STEPControl_Reader`, confirmed
`TopAbs_SOLID` count is exactly 3, and confirmed
`reduced_half + untouched_half + side_core` matches the original
`cavity + core` total to within 0.001% on both parts.

**Config**: new `dfm.side_core` block in `config.yaml`/`backend/config.py`
(`SideCoreSettings`) — `footprint_margin_factor: 1.5`,
`min_half_size_mm: 2.0`, `fuzzy_tolerance: 0.01`,
`volume_conservation_tolerance: 0.05` — all measured/justified inline in
both files, no unexplained magic numbers.

**API**: `/parts/{filename}/core-cavity` gained `generate_side_core: bool`
(gated behind `solid_split=true`); `/parts/{filename}/export/mold-halves`
gained `use_optimal_direction`/`dx`/`dy`/`dz` (previously always used the
optimal direction only, with no override support — now matches
`/core-cavity`'s S3.6 pattern) plus `generate_side_core`, which writes the
side core as a third STEP body via `export_mold_halves`'s new
`solid_overrides`/`extra_solids` parameters.

**Frontend**: new "Side core / lifter (Stage 4)" sidebar checkbox
(disabled unless "Boolean solid split" is also checked), a result panel in
the Core/Cavity tab (status chip, containing half, volumes, conservation
error, explicit non-goal caption about lifter/slide/collapsible-core
classification), and `_collect_issues()` now surfaces side-core
`"generated"`/failure states in the Findings panel — including through the
S3.6 direction-override path, since demonstrating a real side core requires
a manual non-optimal direction.

**Tests**: new `tests/test_side_core.py` — pure selection-logic tests
(`select_primary_side_core_feature`'s critical-severity preference and
interference-volume tiebreak), guard-clause tests (blocked without
`split_ok`, blocked with `None` solids, `to_dict()` never leaks raw OCC
shapes), and the real end-to-end regression guard for both bugs above:
full pipeline → side core → 3-solid AP214 export → STEP reload, asserting
exactly 3 solids and volume conservation, on both Part1 and Part3. Full
suite: **277 passed** (266 previous + 11 new), 0 failed.

**Honesty**: Bosch criterion #5 can now be described as "a real side-core
solid exists for the single highest-confidence critical feature, Boolean-
subtracted from the containing mold half, exported alongside cavity/core in
the same AP214 file" — NOT as "side-core generation is complete" (grouped/
multi-feature generation, §4.3 Q1, is explicitly out of scope) and NOT as
"lifter/slide/collapsible-core selection is implemented" (§4.3 Q4 is
explicitly not decided by this module).

---

### 2026-07-28 — S3.8: backend `PartGeometry` LRU cache + mesh/analysis payload split — Stage 3 is now fully complete

Two items carried over from the cancelled React migration plan (§0.2), both
backend changes that needed no frontend framework change to deliver.

**1. `PartGeometry` LRU cache — the single biggest latency source, per the
roadmap's own framing.** CLAUDE.md documents the backend as deliberately
stateless: every endpoint re-parses the STEP file from scratch, with no
shared in-memory geometry between requests. That statelessness is the right
contract to keep (no request should ever see another's leftover state) —
but "re-parse the file" and "re-run the whole analysis pipeline" are not
the same requirement, and the file parse alone was being paid for on every
single call.

New `load_step_cached()` in `backend/geometry/step_loader.py`, keyed on
`(path, mtime_ns)` — editing a STEP file on disk changes its mtime and
invalidates the cache entry automatically, so a cache hit is never stale.
All 7 `load_step(path)` call sites in `backend/api/main.py` switched to it
(the `load_step` import itself removed as now-unused there). Measured
directly against the running server: **0.79s cold load → ~0.003s on a warm
hit** (≈250x). Also removed a `test_api_error_handling.py`-adjacent
oversight: `load_step` stayed the correct choice (unwrapped) in
`part_validation.py`/`performance_profile.py`, which are one-shot CLI tools
where "does this succeed from a genuinely clean load" is the actual
question being asked — caching there would undermine the tool's purpose,
not just be unnecessary.

**Why this is safe despite the mutate-flag contract** (the roadmap calls
the regression test "mandatory alongside the cache," and for good reason):
`FaceData`/`EdgeData`/`PartGeometry` are plain, non-frozen dataclasses that
downstream analysis mutates in place when called with `mutate=True`
(`draft_angle_deg`, `is_undercut`, `cavity_or_core` on faces;
`optimal_pull_direction`, `parting_edge_ids`, ... on the part itself,
confirmed by grepping every direct-assignment call site across
`direction_optimizer.py`/`parting_line.py`/`main.py`). Caching and handing
out the SAME object across requests would let one request's analysis
mutate state another request — running concurrently, since FastAPI can
interleave requests — would then read. New `_clone_pristine_part()` never
lets that happen: only the pristine object `load_step()` returns (BEFORE
any analysis touches it) is ever cached, and every call to
`load_step_cached()` returns a freshly-constructed clone
(`dataclasses.replace()` on the outer object and on every `FaceData`/
`EdgeData`/`VertexData`, plus fresh copies of every adjacency dict and
mutable list) — mutating a clone's fields can never be visible from a
different clone or from the cached template itself. OCC handles
(`occ_shape`, `occ_face`, `occ_edge`, `occ_vertex`) ARE shared by reference
across clones — that's the actual point of the cache — which is safe
because no code path in this project mutates loaded B-Rep geometry in
place; Boolean and derived operations always construct new OCC objects.

5 new tests in `tests/test_step_loader.py::TestLoadStepCached`, including
the exact mandatory scenario: mutate one clone's `draft_classification`,
`is_undercut`, `cavity_or_core`, `optimal_pull_direction`,
`inaccessible_face_ids`, `parting_edge_ids`, and `warnings`, then assert a
second clone drawn from the same cache entry shows none of it. Also: a
cached clone's topology matches a genuinely fresh `load_step()` call
exactly; the OCC shape handle is confirmed shared by reference across
clones; and the cache genuinely invalidates when the underlying file's
mtime changes.

**2. Mesh/analysis payload split — stop re-downloading identical
geometry on every overlay switch.** Found that the backend already had
exactly the right mechanism for this: `DisplayMesh.to_payload(
include_geometry: bool = False)` in `visualize_raw.py` already supported
returning a compact summary (counts, `face_ids`, `face_centers`) without
the large `points`/`faces` arrays — but every one of the 5 relevant
endpoints (`/draft`, `/undercuts`, `/direction`, `/parting-line`,
`/core-cavity`) hardcoded `include_geometry=True` regardless. Added
`include_mesh_geometry: bool = Query(default=True)` to each and threaded it
through. The frontend already had a client-side half of this problem solved
(`_cache_and_strip_mesh`/`_hydrate_mesh`, from an earlier session's Bug F6
fix) — it primes a `cached_display_mesh` in session state on the first
mesh-bearing result and strips duplicate geometry arrays from every
subsequent one — but that only ever reduced *client memory*, since the full
payload had already been transferred over the network before being
discarded. New `_mesh_geometry_already_cached()` checks whether that
client-side cache is already primed for the current part and, if so, every
`_fetch_*` function now requests `include_mesh_geometry=false` — actually
avoiding the redundant transfer this time, not just the redundant storage.
`_hydrate_mesh`'s existing merge logic (`{**cached, **display_mesh}`)
needed zero changes: it already reconstructs the full mesh from cached
geometry plus whatever the fresh response carries, regardless of whether
the large arrays are present in that response or not.

Measured directly: the same `/draft` call for Part1, with the base geometry
already cached, drops from **682,742 to 224,780 bytes (≈67% smaller)**.
Verified there is zero rendering regression by inspecting the actual
rendered output, not just checking for exceptions: ran the full guided flow
via Streamlit's `AppTest` harness, then read every `plotly_chart` element's
underlying figure spec and confirmed every `mesh3d` trace across all 5
analysis tabs has full, correct vertex/face data (6,649 points / 7,270
faces, matching the cached base mesh exactly) — despite most of those
responses never having carried a single point or face over the wire.

**Stage 3 is now fully complete (S3.1 through S3.8).** Full suite: **266
passed, 0 failed** (261 previous + 5 new).

---

### 2026-07-28 — S3.7: diverse candidate directions — stop claiming *the* answer, start showing defensible options

**The problem, as measured on the live Part1 run**: the direction
optimizer's "top candidates" table was six near-identical entries — the
best direction at score 0.313, then five more within 9° of it, all
essentially the same physical answer restated with tiny perturbations. An
artefact of Milestone 1.4's fine-search cone (it densely samples right
around whatever looked best in the coarse pass). Useless to an engineer
asking "what are my real options, and why does this one win?"

**Fix**: `_cluster_diverse_candidates()` in `frontend/app.py` — a greedy
diverse-subset selection (the same idea as non-max suppression):
candidates are already sorted best-first by score; walk the list and keep
a candidate only if it's at least 15° from every candidate already kept.
New `_angular_separation_deg()` helper computes the angle between two
direction vectors.

**A real gap this exposed**: the frontend's `_fetch_direction()` never
requested more than the API's default top-10 candidates
(`include_all_candidates` defaults to `false` server-side) — exactly where
the near-duplicate problem was hiding, since real diversity often only
shows up much further down the ranked list. Added
`"include_all_candidates": True` to the fetch. Verified on real Part1: 114
total scored candidates → **17 genuinely distinct families** after
clustering (best 0.313, then real alternatives at 0.969 / 2.521 / 4.024 /
... mm — each one a materially different direction, not a restatement of
the winner).

**UI**: new "Diverse Candidate Directions" section in the Direction tab —
direction (axis + tilt), score, angular distance from the best, bad-draft
area %, undercut feature count, and whether it was Boolean-refined, one row
per distinct family. Caption states the defensible claims plainly: validity
(genuinely undercut-free?), ranking transparency (why this beat the
others), stability (do nearby directions score similarly?) — not that this
is uniquely *the* answer. The raw all-candidates dump (now potentially 100+
rows since the fetch requests everything) moved into a collapsed "Top
Candidates (raw, all scored)" expander — Layer 3, matches the S3.1
progressive-disclosure structure rather than dumping everything by default.

**Verification**: Streamlit `AppTest` against the real backend for both
Part1 and Part3 — zero exceptions, "Diverse Candidate Directions" section
and its caption both confirmed present. No backend changes this round (the
`include_all_candidates` query param already existed and worked correctly
— the gap was purely that the frontend never asked for it), so the
existing 261-test suite is unaffected.

---

### 2026-07-28 — S3.6: direction override (Bosch criterion #2) — the optimizer recommends, the engineer decides

**Philosophy**: the optimizer computes the geometrically optimal pull
direction; that is a recommendation, not a mandate. Real mold engineers
override it for reasons outside pure geometry — flash, gate location,
ejector layout, existing tooling, cost. The UI needed a way to let an
engineer replace the recommendation with their own direction and see every
downstream analysis recompute for it, **without discarding the
recommendation** — both must stay comparable.

**Implementation.** New "Override Mold Direction" section in the Direction
tab: ±X/±Y/±Z preset buttons plus a custom-vector input (auto-normalized to
a unit vector). Applying one calls the existing per-endpoint `dx/dy/dz`
support already built into `/draft`, `/undercuts`, `/parting-line`, and
(after the fix below) `/core-cavity` — no new backend analysis logic
needed, only a fix to one endpoint that had never actually supported this.
Results are stored in a new `override_result` session-state key, entirely
separate from the recommended pipeline's `draft_result`/`undercut_result`/
`parting_line_result`/`core_cavity_result` — nothing is overwritten. A
"Recommended vs Override" comparison table shows direction, draft severity,
undercut counts, parting readiness/coverage, and cavity/core/parting face
split side by side. An always-visible warning banner
(`_render_active_direction_banner`) shows whenever an override is active,
independent of which tab is open, so the engineer always knows whether
they're looking at optimized or overridden results. The "Findings" panel
(S3.1/S3.4) switches to the override's results while one is active — "the
engineering report reflects the chosen direction" — with every location
suffixed "(override)"; the recommendation itself stays fully intact and
inspectable via the comparison table. Changing the selected part or the
base pull direction (which already resets all analysis state) also clears
any active override, so a stale override from a previous part can never
leak forward.

**Real backend gap found and fixed**: `/parts/{filename}/core-cavity`
accepted a `use_optimal_direction=false` flag but had **no `dx`/`dy`/`dz`
parameters at all** — passing `use_optimal_direction=false` silently fell
back to a hardcoded `(0.0, 0.0, 1.0)` regardless of what direction the
caller actually wanted, with no way to classify against a genuinely custom
direction. `/parting-line` already had the correct pattern (`pull_direction
= (dx, dy, dz)` when not using the optimal direction); `/core-cavity` now
matches it. Verified directly: `curl ".../core-cavity?use_optimal_direction=false&dx=0&dy=0&dz=1"`
now reports `pull_direction_source: "manual_query_direction"` and returns
face counts that genuinely differ from the optimal-direction classification
(24/209/78 cavity/core/parting on Part1 for +Z, vs the optimizer's own
split for its recommended direction) — previously this call silently
ignored the direction and always returned the same (0,0,1)-based
classification no matter what `use_optimal_direction=false` callers passed.

**Verification.** Streamlit's `AppTest` harness (no browser tool available
in this environment) drove the real app against the real backend: ran the
full Level 1 flow on Part1, clicked the "+Z" override preset, and confirmed
— banner appears (`⚠️ Viewing results for a manual direction override:
+Z...`), the Findings panel correctly surfaces *worse* results for +Z than
the recommended direction (critical draft correction required, a critical
undercut remaining, parting-line coverage dropping to 4%) — a genuine,
correct demonstration of exactly the tradeoff this feature exists to show —
comparison table renders, then clicking "Clear override" removes the
banner and reverts Findings to the recommendation. Zero exceptions
throughout.

**One real Streamlit bug found and fixed during that verification, not
before it.** The banner and Findings panel are rendered near the top of the
script, before the button-handling code (further down, inside the Direction
tab) that actually sets the override state. Since Streamlit executes the
whole script top-to-bottom on every rerun, the first `AppTest` pass after
clicking an override button showed the *comparison table* correctly (it's
rendered after the state-setting code, in the same pass) but the banner and
Findings still showed the *old* state — a one-rerun lag that would have
been a confusing flicker for a real user. Fixed with the standard Streamlit
idiom: call `st.rerun()` immediately after every override-state mutation,
forcing a clean fresh pass where every render call — regardless of its
position in the script — sees consistent, current state.

**Correction to the 2026-07-28 "Stage 3 core" entry below**: that entry
claimed `direction.optimal_undercuts` (from the `/direction` endpoint) has
no per-feature `features` list, unlike the standalone `/undercuts`
endpoint. Re-checked properly while building S3.6 (the earlier check had
truncated a keys list at 10 entries and cut the 11th, `features`, off): the
field is present in both, using the same `UndercutDetectionResult.to_dict()`
method. It was simply empty (`[]`) for Part1's optimal direction, because
that direction genuinely has zero undercut features — not because of a
schema difference. The *code* written for that entry is unaffected and
still correct (it degrades safely either way), but the stated reason was
wrong; recorded here rather than silently edited, per this file's
append-only convention.

**Regression test added**: `test_core_cavity_endpoint_honours_a_manually_supplied_direction`
in `tests/test_api_error_handling.py` calls the real route function against
real Part1 geometry with `use_optimal_direction=False` at two different
supplied directions and asserts the resulting face counts genuinely differ
— if `/core-cavity` ever regresses to ignoring `dx/dy/dz` again, this fails.
Full suite: **261 passed, 0 failed** (260 previous + 1 new).

---

### 2026-07-28 — Stage 3 core (S3.1-S3.5): issue-first UI, metric glossary, direction axis+tilt formatting — plus Level 2 wired into Streamlit for the first time

**The metrics-interpretability problem the whole Stage 3 plan was built
around**: metrics were visible, not interpretable — a flat dump of
quality-indicator chips, tables, and JSON expanders with no ranking, no
explanation of what any number meant, and `graph_cleanup.strategy` (the
single field that would have caught Bug B immediately) buried inside a
conditionally-collapsed "Graph Cleanup Evidence" expander that only opened
when there happened to be a conflict edge.

**S3.1 + S3.4 — issue-first, three-layer progressive disclosure.** Added
`_collect_issues()` and `_render_issue_summary()` to `frontend/app.py`: scan
every pipeline stage's real result (draft, undercuts, direction, parting
line, core/cavity) and build ranked `{severity, location, title, detail,
evidence}` records — deliberately the same shape the roadmap says Stage 5's
agent will eventually consume. Rendered as a "Findings" panel right after
the journey header, before the existing tabs: ≤5 issues by default (Layer 1
verdict), a "Show N more" toggle for the rest, and a "Show evidence"
expander per issue (Layer 2). The existing per-step tabs and their raw-JSON
expanders are now Layer 3 (provenance/debug) — unchanged, just correctly
positioned in the hierarchy instead of being the only view.

**S3.2 — metric glossary.** `METRIC_GLOSSARY` (10 entries covering the
roadmap's list: `readiness`, `closure_error_mm`, `graph_cleanup_strategy`,
`silhouette_coverage_ratio`, `undercut_area_pct`, `direction_score`,
`depth_proxy_mm`, `pull_alignment`, `bridging_status`, `split_tool_kind`),
each answering what it means / what good looks like / what to do if bad.
Surfaced two ways: a hover tooltip (`title=` HTML attribute — no new
dependency) on the relevant indicator chip, and a "📖 Metric Glossary"
reference expander near the top of the page.

**S3.3 — `graph_cleanup.strategy` now always visible.** Added a "Search
strategy" chip to the parting-line quality-indicator row (red when
`greedy-fallback`), plus a "Silhouette coverage" chip (previously only a
`st.write` line further down the page). Verified against real, live data —
not placeholders: Part1 shows `contracted-graph-search` (green) and 95%
coverage; Part3 correctly shows 18% coverage (amber), reproducing Bug H's
original finding exactly through the new gate.

**S3.5 — direction as vector + closest axis + tilt.** New
`_direction_axis_tilt_text()` replaces `_vector_text()` at all 10 call sites
that display a pull direction. On real Part1: `(+0.232, +0.357, +0.905) ≈
+Z, tilted 25°` — matches the roadmap's own worked example exactly. Fixed a
latent duplication bug while touching this code: `direction_optimizer.py`'s
`_direction_label()` falls back to raw vector text for any non-axis-aligned
direction, so two places that showed `best_label` next to the vector used to
print the vector twice ("(+0.232, +0.357, +0.905) (+0.232, +0.357, +0.905)
≈ +Z, tilted 25°"). New `_direction_label_display()` only prepends the
label when it's a genuine 2-character axis label.

**Bonus, not originally scoped this session: Level 2 wired into the UI.**
New "Boolean solid split (Level 2)" sidebar checkbox → `solid_split=true` on
`/core-cavity` → a new display block in the Core/Cavity tab (split status,
solid count, cavity/core/blank volumes) with an explicit info banner
whenever `split_tool_kind="planar_approximation"` — so a viewer can never
mistake the exported solids for an exact rendering of the 3-D parting curve
shown in the Parting Line tab. Verified `split_ok`, 2 solids, on real Part1.

**Two real bugs found and fixed while verifying against live data, not
mocks** (same pattern as every other bug this project has found — build the
check, then prove it against the real thing before trusting it):
1. `direction.optimal_undercuts` (from the `/direction` endpoint) is a
   **summary only** — `feature_count`, `major_undercut_features_count`,
   `has_critical_undercut`, percentages — with **no per-feature `features`
   list**, unlike the standalone `/undercuts` endpoint's response. The
   initial issue-builder assumed the same shape everywhere and silently
   produced zero undercut findings for the optimal direction on real data.
   Fixed: the issue-builder now branches on which shape is actually
   available, using the summary fields directly when that's all there is.
2. Draft severity's real vocabulary (`draft_analyzer.py`) is `none | minor |
   moderate | critical` — not the guessed `good | marginal | bad`. Real
   Part1 data returned `severity: "none"`, which matched none of the
   original checks, so the draft "OK" finding silently never appeared.
   Fixed to match `_tone_for_draft_severity`'s existing, correct mapping.

**Verification method**: no browser tool is available in this environment,
so Streamlit's own `streamlit.testing.v1.AppTest` harness was used instead —
it actually runs the full app server-side (widget interactions, session
state, reruns) against the real running backend, which is a materially
stronger check than just confirming the page returns HTTP 200. Ran the full
"Run Full Level 1 Flow" button-click flow for both Part1 and Part3, with the
new solid-split checkbox enabled: zero exceptions (`at.exception` empty)
before and after every fix, and the rendered markdown was inspected
directly to confirm real values (not placeholders) for every new UI
element.

**Not done this session** (see TODO.md S3.6/S3.7/S3.8): direction override
(Bosch criterion #2), candidate diversity clustering, backend
`PartGeometry` LRU cache.

---

### 2026-07-28 — Stage 2b: core/cavity solid split genuinely works end-to-end on both real parts (Milestones 1.10/1.11 verified, not just "tests pass")

**The shoulder-extension attempt: real progress, then a deeper root cause found.**
Built `_build_shoulder_collar()` in `parting_line.py` — a ruled `BRepOffsetAPI_
ThruSections` loft extending the parting loop radially outward (perpendicular
to the pull direction) to `extension_factor * bbox_diagonal_mm`, fused with the
`BRepFill_Filling` patch. This genuinely worked as *area extension*, measured
on real geometry: **2,351.91 → 20,225.52 mm² on Part1, 602.92 → 71,308.22 mm²
on Part3** (~8.6x and ~118x respectively). But `BRepCheck_Analyzer` confirmed
the underlying `BRepFill_Filling` patch is **topologically invalid
independent of any extension** — true even with `shoulder_extension_enabled=
False`, on both real parts. Three separate healing strategies were tried
directly against it and none produced a valid shape: `ShapeFix_Shape` (raw
patch: still invalid, area drifted from 2351.91→2340.31 mm²), `ShapeFix_Face`
per-face (still invalid), and `BRepBuilderAPI_Sewing` at 1e-3 tolerance
followed by `ShapeFix_Shape` again (still invalid, even on the sewn
compound). `BRepAlgoAPI_Splitter` cannot reliably consume an invalid tool
shape regardless of how far it extends — extending an unfixably invalid
patch does not fix it. Confirmed via `split_core_cavity_solids` against the
shoulder-extended shape on both parts: `BRepAlgoAPI_Splitter reported
errors`, 0 solids — a *different* failure mode than the previously-documented
"one near-full-blank solid + a degenerate sliver," but still not a working
split.

**The real fix: stop trying to use the real 3-D parting surface as the
Boolean tool at all.** Added `core_cavity.build_planar_split_tool(centroid,
pull_direction, half_size_mm)` — a single, trivially-valid flat plane
perpendicular to the pull direction, centred on the parting loop's own
centroid (mean of `wire_points`), sized to `split_plane_half_size_factor *
bbox_diagonal_mm` (new config, default 2.0). This sidesteps the invalid-patch
problem entirely instead of trying to heal it. `split_core_cavity_solids()`
now builds this tool internally from a new `loop_points` parameter and uses
it as the sole `BRepAlgoAPI_Splitter` tool; the same centroid is reused for
cavity/core classification (replacing the old logic, which computed a
"parting centroid" via `brepgprop_VolumeProperties` on `parting_sheet` — a
face/shell has no volume, so that call was silently degenerate and fell back
to the blank's geometric midpoint, a semantically wrong point for a 2-D
surface with no dedicated test ever catching it).

**Verified end-to-end on real OCC, both real demo parts, for the first time
in this project's history:**
- `split_core_cavity_solids`: `solid_split_status="split_ok"`,
  `split_solid_count=2`, `split_tool_kind="planar_approximation"` on both
  parts. Part1: cavity=17,587.27 mm³ / core=16,909.73 mm³ (tooling
  35,950.05 mm³, 4.04% conservation error). Part3: cavity=221,298.12 mm³ /
  core=158,807.40 mm³ (tooling 395,169.87 mm³, 3.81% conservation error).
- `export_mold_halves()`: `status="exported"`, AP214, `solid_count=2` on
  both parts — the first time this function has ever run against a genuine
  `split_ok` result (previously only exercised against fake/guard-check
  inputs, since no real split had ever succeeded).
- Re-loaded the exported STEP file with a fresh `STEPControl_Reader` on both
  parts: **exactly 2 solids**, volumes matching the split result — the exact
  gate TODO.md S2.4 specified.

This is a genuine, honest **geometric approximation**, not the exact 3-D
parting surface — real for non-planar parting lines (measured pull-axis
span: Part1 16.16/30.78 mm, Part3 7.14/68.12 mm — not a negligible amount of
3-D-ness). Labeled via the new `CoreCavitySolidResult.split_tool_kind` field
(`"planar_approximation"` on success) so no downstream consumer can
accidentally claim the exported solids follow the exact candidate parting
line. The *reported/displayed* parting-line curve and surface
(`PartingSurfaceResult`) are completely unaffected — unchanged from before
Stage 2b, still the real 3-D `BRepFill_Filling`-based candidate.

**Config**: `volume_conservation_tolerance` raised from 0.02 to 0.06 to match
the measured 4.04%/3.81% error with margin — documented as an accepted
consequence of the planar approximation, not silently loosened. New
`split_plane_half_size_factor` (default 2.0, × bbox diagonal). Tracked as
`TODO.md` S2.5 (low priority) whether this gap can be tightened further by
tuning the Splitter's own fuzzy tolerance separately from the Cut step's.

**Removed** (real code, but provably insufficient and no longer used):
`_build_shoulder_collar()`, `_make_polyline_wire()`, `PartingSurfaceSettings.
shoulder_extension_enabled`, `PartingSurfaceResult.shoulder_extended` /
`.shoulder_failure_reason`. `_build_parting_surface()`'s filling-strategy
return reverted to its pre-Stage-2b form (`extension_factor=1.0` — the
surface is never extended; it doesn't need to be anymore, since it is no
longer the Boolean tool).

**BUG I re-verified against the exact original repro command** —
`python -m backend.validation.part_validation --expect Part1.stp
--assert-core-cavity-solids 2` (default Z pull direction, no `--direction`) —
which previously got OOM-killed. Now completes cleanly on both parts:
`core_cavity_split` in 0.47s (Part1) / 0.98s (Part3), exit 0, no OOM. Root
cause was almost certainly the old splitter retrying `BRepAlgoAPI_Splitter`
against the invalid, possibly self-intersecting shoulder-extended shape;
the new planar tool succeeds on the first attempt with no expensive retries.

**Tests**: 5 new in `tests/test_core_cavity.py` —
`test_split_blocked_without_loop_points`,
`test_build_planar_split_tool_produces_a_valid_face`,
`test_build_planar_split_tool_normal_is_perpendicular_to_pull_direction`,
and — the tests that actually prove Milestones 1.10/1.11 work —
`test_real_split_and_export_round_trips_on_part1` /
`_on_part3`, which run the full real pipeline (direction search → parting
line → Boolean split → AP214 export → STEP reload) against the real
`data/parts/Part1.stp` / `Part3.stp` fixtures and assert exactly 2 reloaded
solids. Full suite: **260 passed, 0 failed** (255 previous + 5 new), real
OCC, Docker.

**Call sites updated** to pass `loop_points=parting_result.wire_points`:
both `/core-cavity` and `/export/mold-halves` endpoints in
`backend/api/main.py`, and the `core_cavity_split` step in
`backend/validation/part_validation.py` (X.1).

---

### 2026-07-28 — Cross-cutting X.1: real-geometry assertion flags, plus a real Docker infra bug (F7) and a new OOM finding (BUG I)

**X.1 done.** Added `check_assertions()` and five `--assert-*` flags to
`backend/validation/part_validation.py`:
`--assert-parting-line-closed [TOLERANCE_MM]`, `--assert-exact-optimiser`,
`--assert-parting-surface-generated`, `--assert-silhouette-coverage
[MIN_RATIO]`, `--assert-core-cavity-solids N` (the last implies a new
`--core-cavity` step that runs the real `split_core_cavity_solids()` Boolean
split). Every flag reads a **measured** value — `closure_error_mm`,
`graph_cleanup_strategy`, `parting_surface_status`, `silhouette_coverage_ratio`,
`split_solid_count` — never a self-reported status/boolean alone, and a
missing or absent step is a hard assertion failure, never a silent pass. This
is the harness-level defense the 2026-07-27 audit called for: Bug A
(`closure_guaranteed=True` with a real 17mm gap), Bug B (silent
`graph_cleanup.strategy == "greedy-fallback"`), Bug E (`parting_surface`
failing silently), and Bug H (a local-feature loop selected instead of the
main silhouette) would all have been caught immediately by these flags had
they existed at the time.

Verified two ways:
1. **9 new unit tests** in `tests/test_part_validation.py`, each built from a
   deliberately bad hand-crafted JSON payload reproducing one of the above
   bugs' exact failure shape — confirmed each flag fails for the *right*
   reason (not just "fails"), including the case where the step never ran at
   all (must fail, not skip).
2. **Live run against real Part1/Part3 output** in Docker:
   `--assert-silhouette-coverage` correctly caught Part3's genuinely measured
   18.1% coverage against the 0.35 threshold (exit code 3) — the exact number
   already on record in `STATUS.md` from Bug H, now independently reproduced
   through the new gate rather than trusted from memory.
   `--assert-parting-line-closed`/`--assert-exact-optimiser`/
   `--assert-parting-surface-generated` all correctly passed for both parts
   (closure, exact-search, and surface generation are genuinely healthy right
   now). Exit code 3 is reserved for assertion failures, distinct from 1
   (step failure) and 2 (missing expected file).

**F7 — found and fixed while trying to prove X.1 against real geometry:**
`docker-compose.yml` never bind-mounted `tests/` — only `backend/`,
`frontend/`, `data/`, `reports/`, and `config.yaml` were live-mounted. Every
`docker compose exec backend pytest tests/...` (the exact command CLAUDE.md
documents) was silently running whatever `tests/` tree got baked into the
image at its last build, not the current repo. Confirmed materially stale:
6 of the repo's 12 test files were missing from the running container
entirely — including `test_core_cavity.py` (written for Stage 2a, believed
verified "246/246 passing in Docker") and `test_parting_line.py` — and the
container's copy of `tests/pytest.ini` predated F5's `pythonpath = ..` fix,
meaning **F5 was fixed in source on 2026-07-27 but the fix itself was never
actually verified in Docker**, because Docker was reading a stale
pre-F5 copy the whole time. Fixed with one line: `./tests:/app/tests` added
to the backend service's volumes, mirroring `./backend`. Recreated the
container and reverified from scratch: bare `pytest tests/test_core_cavity.py`
now passes 9/9 with no workaround, and the full suite is genuinely
**255/255** (237 from BUG G + 9 from Stage 2a + 9 from X.1) — the first time
this exact number has been confirmed against a container that actually has
every current test file. This is the same category of defect as everything
else in `docs/ENGINE_AUDIT_2026-07-27.md`: a documented verification command
that looks authoritative but was never confirmed to read current source.

**BUG I — new, found by actually running X.1's `--core-cavity` step against
real Part1 geometry, not yet fixed.**
`python -m backend.validation.part_validation --expect Part1.stp
--assert-core-cavity-solids 2` did not return a structured `failed` result —
it got OOM-killed (`Killed`, exit 137). `docker inspect bosch-backend-1`
confirmed `OOMKilled: true` for the process; the backend container's own
`uvicorn` process survived and `/health` stayed green throughout, so this
did not take the API down, but the fuzzy-tolerance retry loop inside
`split_core_cavity_solids()` (Stage 2a's S2.1b fix) has no memory or
iteration ceiling, and with the parting surface not yet reaching the mold
blank's bounds (S2.2's diagnosed shoulder-extension gap), each retry may be
constructing large or degenerate intermediate shapes. Logged as a new open
item alongside S2.3 rather than investigated further this session — running
`--core-cavity` against Part1 without a timeout/memory wrapper is not safe
until either S2.3 lands or the retry loop gets an explicit bound.

Full suite: **255 passed, 0 failed** (real OCC, Docker, container recreated
with the F7 fix live).

---

### 2026-07-28 — Stage 2: core/cavity solid split was NEVER actually running — two real bugs found; the real blocker for Part1 AND Part3 precisely diagnosed

**`_OCC_SPLIT_AVAILABLE` was `False` this entire time, for every request, in
every environment where this was supposedly tested.** Ran the real
`/parts/{filename}/export/mold-halves` endpoint against the running Docker
backend — the very first thing Stage 2 asked for — and it returned
`"pythonOCC Boolean APIs not available in this environment"` immediately.
Root cause: `from OCC.Core.Interface_Static import Interface_Static` — that
module path **does not exist** (the real one is `OCC.Core.Interface`). A
bare `except (ImportError, Exception): _OCC_SPLIT_AVAILABLE = False`
swallowed the `ModuleNotFoundError` with **no logging at all**, so the
failure read as an environment limitation rather than a one-line bug. This
means Milestones 1.10/1.11's "28 tests pass (2026-07-27)" claim was never
backed by a real run of the actual Boolean/export code — the exact same
process failure the 2026-07-27 audit found in the parting line, now found in
core/cavity too. Fixed the import path and added loud error logging so this
class of defect can never hide silently again.

**A second, structurally identical bug was underneath the first.**
`BRepAlgoAPI_Cut().SetArguments([blank])` — this pythonOCC binding's
`SetArguments`/`SetTools` require a real `TopTools_ListOfShape`, not a plain
Python list; passing a list raises `TypeError`, caught by the retry loop's
`except Exception` and reported as the generic "failed after all
fuzzy-tolerance retries." Fixed with a `_shape_list()` helper wrapping every
argument list before use (both `BRepAlgoAPI_Cut` and `BRepAlgoAPI_Splitter`).

**With both fixed, the Boolean split genuinely runs — and immediately
exposed a third, real defect: it could report `split_ok` on a broken
split.** Measured on Part1 before a check existed: the split returned "2
solids" with volumes **35950.05 mm³ and −0.164 mm³** against a tooling
volume of 34509.89 mm³ — one solid kept almost the entire tooling volume,
the other was a degenerate negative-volume sliver. The existing code only
checked that the two solids landed on *different* sides of the parting
centroid, never that either volume was *plausible*. This is the exact same
failure pattern as Bug A (report success, hand downstream broken geometry).
Added `_validate_split_volumes()` — a pure function, unit-tested directly —
enforcing both a minimum-volume floor (each solid ≥ 1% of tooling volume,
`core_cavity.min_solid_volume_fraction`) and volume conservation (cavity +
core ≈ tooling within 2%, `core_cavity.volume_conservation_tolerance`).
Neither part currently passes this check — see below for why.

**The real remaining blocker, precisely diagnosed (not the one predicted).**
STATUS.md previously flagged Part3's 18.1% silhouette coverage as the likely
Stage 2 risk. With the bugs above fixed, the actual cause turned out to be
different and affects **both** parts: `_build_parting_surface`'s
`BRepFill_Filling` strategy — the one both real parts actually use — builds
a face bounded *exactly* by the parting loop, with `extension_factor=1.0`
hardcoded ("Filling doesn't extrude"). It never extends into the mold
blank's margin (`blank_margin_factor=0.25` × bbox diagonal beyond the part),
so `BRepAlgoAPI_Splitter` cannot cleanly bisect the larger tooling volume —
Part1 returns one near-full-blank solid plus a degenerate sliver; Part3
returns 4 solids instead of 2.

Tested the obvious quick fix — extrapolating the filling surface's `Geom_Surface`
beyond its original UV bounds — and it is **not viable**: sampled 2× beyond
the original parametric domain on both parts and got points on the order of
10²⁰ mm, numerically catastrophic garbage from a B-spline patch evaluated far
outside its fit region. The real fix needs a proper "shoulder extension"
algorithm — extruding/lofting the loop's *boundary wire* outward to the
blank's bounds, not extrapolating the fitted surface — genuinely new
geometric work, not a quick patch. Scoped as a new task rather than attempted
under time pressure.

**Added `tests/test_core_cavity.py` — the first dedicated tests this module
has ever had** (9 tests): a regression guard for the exact
`_OCC_SPLIT_AVAILABLE` import bug, five unit tests for
`_validate_split_volumes` covering the measured Part1 failure directly, and
two tests for `export_mold_halves` including the `data/parts/` write guard
(CLAUDE.md invariant #2) — a safety-critical check that also had zero prior
coverage.

Verified on real OCC in Docker: 246 passed (237 previous + 9 new), 0 failed.
Both `/export/mold-halves` calls against the live backend now fail for the
correct, precisely-stated reason instead of a generic environment message.

---

### 2026-07-28 — Planning docs brought current: STATUS.md rewritten, roadmap re-planned around the audit, Phase 2 formally cancelled

Documentation-only pass. No engine code changed.

**`STATUS.md` rewritten.** It was dated 2026-07-27 and materially wrong:
F6 sat under "Open Blockers" with its own text saying "Fix applied";
`test_parting_line_paths_payload_is_json_safe` was listed as failing (it
passes); test status read "Passes with mocks" with no real numbers; module
line counts were stale by up to 1,500 lines (`parting_line.py` listed as
~3,200, actually 4,720); none of the nine bugs fixed this session appeared.
Now carries a headline table (both parts `ready`, with Part3's 18.1% coverage
flagged rather than buried), accurate per-module line counts, the real
237/237 test result, and an explicit "known test-suite weakness" section
naming the process defect.

**`docs/ARCHITECTURE_ROADMAP.md` re-planned** around
`ENGINE_AUDIT_2026-07-27.md` + `RECOVERY_PLAN.md`:

- Added a **▶️ START HERE** block — next action is Stage 2 plus cross-cutting
  X.1, with the reasoning and a doc-routing table.
- §0.1 now records what *actually happened* to each original phase, rather
  than restating the original intent.
- §0.2 formally cancels the React migration; §0.3 lays out Stages 2–6 with a
  sequencing chart.
- **§0.4 (new) — the process defect.** Every audit bug survived a green
  suite. Includes a table mapping each required real-geometry assertion to
  the specific bug it would have caught.
- **New Stage 2** (unblock Level 2) with measured gates, and an explicit note
  that Part3 may legitimately fail — to be reported, not worked around.
- **New Stage 3** (engineering-review UI) — see below.
- **New Stage 4** (side core / lifter, Bosch criterion #5) — six design
  questions to resolve before estimation, plus a minimal first increment.
- Phase 2/3 sections marked **[HISTORICAL]** rather than deleted; their
  transport, caching and test-matrix designs are still sound.
- Risk register rewritten: three risks are marked **MATERIALISED** with what
  actually happened, instead of listed as hypothetical.
- Invariants now lead with the lesson: **"A gate must measure geometry, not
  read a reported flag. If a no-op change could satisfy a gate, the gate is
  wrong."**

**Stage 3's metrics problem restated correctly.** The earlier framing
("metrics not readable") was imprecise. The metrics *are* visible — the
problem is volume and lack of meaning, failing two different audiences: a
developer who can't tell what `depth_proxy_mm` signifies or which numbers
matter, and a mold engineer who can't reach a conclusion without scrolling
tables.

Inspected the real exports in `metrics/*.csv` to ground this. **The engine
already computes excellent explanation data** — `action_confidence_breakdown`
carries per-term `code`/`impact`/`explanation` entries *including negative
terms* ("silhouette category is inherently ambiguous", −0.03) plus a written
summary. Meanwhile a single export has ~45 columns, with `grouping_factors`
holding 25 repeated `linked 30-31: bbox_gap_mm=0.0000 …` entries and
`boolean_intersection` containing ten identical repeated geometry analyses.

**So this is an information-architecture problem, not a missing-data one** —
recorded as three-layer progressive disclosure (verdict / evidence /
provenance), a metric glossary answering *meaning · good value · what to do*,
and surfacing `graph_cleanup.strategy` in the default view (that one metric
alone would have exposed Bug B immediately).

**Fixed a genuine contradiction between docs.** The roadmap's Decisions Log
claimed "no mix-up … no data restoration needed — F1 is closed without any
change to `data/parts/`", directly contradicting `TODO.md` and `STATUS.md`,
which record a genuine mix-up and a restoration. Verified against the
filesystem: `Part1.stp` is exactly 522,419 B (the size `TODO.md` attributes
to `rename.stp`), `rename.stp` no longer exists, and `data/parts/` has a
2026-07-27 mtime — a change did happen. The Decisions Log was the stale one;
corrected, with the correction marked rather than silently rewritten.

`TODO.md` restructured to match (Stage 2/3/4 + cross-cutting sections,
Phase 2 struck through with items either moved or explicitly dropped), and
`RECOVERY_PLAN.md` / `ENGINE_AUDIT_2026-07-27.md` both marked as absorbed
diagnosis records so neither is mistaken for the live plan.

---

### 2026-07-28 — FIX C (Docker/local viewer parity) + roadmap/tracker reconciliation + a real `Part2.stp` code bug found and fixed

**FIX C — Docker frontend now matches local dev's interactive Plotly
viewer.** `_USE_PLOTLY_VIEWER` gated on `sys.platform == "darwin"` or
`DFM_FORCE_PLOTLY=1`; Docker (Linux) never set the env var, so it silently
used the PyVista/`stpyvista`/Xvfb renderer while macOS got Plotly — same
backend, different viewer depending on where you ran it. Fixed with one line
in `docker-compose.yml`. Verified live: brought the stack up, confirmed the
env var reaches the container, and ran `_show_mesh_plotly`'s real
trace-building code inside the running frontend container against a mesh
payload fetched from the real running backend for `Part1.stp` (6,649 points,
7,270 faces) — produced a valid `go.Mesh3d` figure end to end.

**Roadmap/tracker reconciliation.** TODO.md's Phase 1 roadmap still had
`1.6` (real graph search replacing bounded DFS) unchecked, even though this
session's Bug B fix fully resolved it — a duplicate-tracking issue between
the roadmap line and an earlier "F4" entry that only covered adjacency, not
the actual search. Marked done with the correct cross-reference. Also found
that Milestones 1.7–1.11 were already `[x]` in TODO.md but the session's own
task tracker still showed them all as pending — never synced after the work
(much of it) landed. Reconciled both directions.

**Verified the "done" claims were actually true before trusting them** (per
this repo's honesty policy — code is truth, not old doc text):
`backend/geometry/core_cavity.py` has genuinely grown from 139 lines
(face-classification only) to 505 lines with a real Boolean solid split
(`split_core_cavity_solids()`) and AP214 mold-half STEP export
(`export_mold_halves()`) — confirmed by reading the implementation directly,
not by trusting the checkmark.

**Found and fixed a real, separate code bug while checking this:**
`DEFAULT_EXPECTED_FILES = ("Part1.stp", "Part2.stp")` was still hardcoded in
both `backend/validation/part_validation.py` and
`backend/validation/performance_profile.py` — `Part2.stp` was resolved to
`Part3.stp` back in Phase 0 (F1) and will never exist, so both validation
harnesses were permanently reporting a false "missing file" and
`--fail-on-missing-expected` would have failed CI for a file that was never
coming. Fixed to `("Part1.stp", "Part3.stp")`; verified live against the
running backend — `missing_expected_files` now correctly reports `[]`. The
tests in `tests/test_part_validation.py`/`test_performance_profile.py` all
pass `expected_files` explicitly (using `"Part2.stp"` generically as a
stand-in for "a missing file" in their own fixtures), so none of them
depended on the stale default — 17/17 still pass.

**Documentation accuracy pass**, since `docs/IMPLEMENTATION_STATUS.md` is
explicitly this repo's "self-declared truth source" for what's
implemented and was materially wrong: updated the `core_cavity.py` module
row, the "Known Limitations" section (was still claiming "Core/cavity
extraction is not available yet"), added a "Current Level 2 Build" section,
fixed remaining `Part2.stp` → `Part3.stp` references, and updated "Next
Implementation Phases" to drop items already done. Also updated
`.claude/rules/honesty-and-scope.md`'s claims-to-avoid/correct-phrasing
sections and its "check the actual state of core_cavity.py" note (was
pinned to a stale line count).

Not touched in this pass (lower-visibility docs, flagged rather than
silently left inconsistent): `docs/DFM_REPORT_OUTLINE.md`,
`docs/DEMO_SCRIPT.md`, `docs/EVIDENCE_CHECKLIST.md` still have a couple of
`Part2.stp` mentions.

---

### 2026-07-28 — Bug G fully fixed: `tests/test_parting_line.py` runs 32/32 with zero exclusions for the first time

**Root cause, finally isolated.** `_sample_closed_edge_points` constructs
`BRepAdaptor_Curve(edge.occ_edge)` — a SWIG-wrapped C++ call. When
`edge.occ_edge` is a `MagicMock` (as in every unit test that doesn't load
real STEP data), that constructor can hang indefinitely at the native layer.
No Python `try/except` can catch or interrupt a hang inside SWIG-wrapped C++
— the existing `except Exception: return []` around the whole block was
powerless against it. Fixed with an `isinstance(edge.occ_edge, TopoDS_Edge)`
guard before the call: a normal, fast, pure-Python check that fails cleanly
on any mock or invalid object, never reaching the native layer at all.
Exactly the fix this item's own note called for
("guard `_sample_closed_edge_points` on OCC-object type").

**Both previously-hanging tests now pass in under a second each:**
- `test_selected_wire_reports_unorderable_edges_without_endpoints` — passes
  as originally written, no changes needed.
- `test_single_closed_edge_without_endpoints_can_use_sampled_curve_points` —
  passes, but its `diagnostics.status == "ok"` assertion was updated to
  `"warning"`. This test could never actually run to completion on real OCC
  before (confirmed via `git stash` A/B baseline hang), so its assertions
  were never verified against real behavior. The synthetic sampled circle
  (radius 1) sits inside the mock part's 10x10x10 bounding box at ~3.9%
  projected coverage — the Bug H silhouette-coverage guard (added later in
  this same investigation thread) correctly flags that as a likely local
  feature. The warning is correct; the old assertion was simply stale.

**Full suite result: `tests/test_parting_line.py` — 32 passed, 0 excluded**
(previously the working set was 26-29 depending on the day, always with 2-3
tests permanently excluded via `-k "not ... and not ..."`). Whole-project
suite: **237 passed, 0 failed, 0 hung, 0 excluded** — the CHANGELOG's
earlier "28 tests pass" claims for Milestones 1.9-1.11 were never actually
backed by a complete real-OCC run; this is the first time the full suite has
run clean end to end.

---

### 2026-07-27 — Bug H-3 fixed: wire quality now reflects the selected loop, not the source component — Part3 readiness improves to `ready`

**Root cause.** `_wire_quality`'s label decision and `_assess_wire_quality`'s
scoring both read `branch_point_count`/`skipped_edge_ids` computed once, at
the top of `_build_ordered_wire`, from the ENTIRE input component — before
either the greedy walk or the (Bug B) second-pass exact search had decided
which edges to actually use. For a normal small component this is invisible
(the selected wire is usually most of the component anyway). For Part3's
269-edge ring-bridged super-component, it meant a demonstrably closed,
clean 15-edge loop was labeled `"partial"` (base score 0.25, not 0.86) and
penalized for `branch_point_count=36` and `skipped_edge_ids` — properties of
the messy 269-edge haystack, not the clean loop found inside it. Final
score: 0.00, regardless of how good the actual find was.

**Fix, in two parts:**
1. `_wire_quality` no longer lets `skipped_edge_ids` (edges elsewhere in the
   component that could not even be parsed — a data-quality signal, not a
   property of the specific wire) override an otherwise-earned
   `"closed_loop"`/`"open_chain"` label. It still degrades the numeric score
   via the existing `missing_endpoints` penalty — it just no longer caps the
   category. `gap_count` still forces `"partial"`, since a gap describes
   this wire's own walk, not the source data.
2. When Bug B's second-pass search substitutes a verified closed loop for
   the greedy walk's result, `branch_point_count` is now recomputed from
   *that specific edge subset's* own point-degree structure, not the whole
   component's. A search-verified simple closed loop is branch-free by
   construction (unless it genuinely self-intersects at a shared vertex,
   which is still correctly flagged).

**Found and fixed a second, more serious bug while writing the regression
test.** A test edge with `start=None, end=None` (standing in for a
genuinely unparseable edge) hung the test suite for 15+ minutes. Root cause:
`_build_ordered_wire` called `_sample_closed_edge_points` (real OCC calls)
for *any* edge with unparseable endpoints, not just the single-edge-component
case it was written for — on a mocked/invalid OCC object this can hang
indefinitely (the same mechanism already tracked as BUG G, now confirmed
broader than previously scoped: it affects multi-edge components too, not
only single-edge ones). Fixed: `_sample_closed_edge_points` is now only ever
called when the edge is genuinely the sole edge in its component; an
unparseable edge in a multi-edge component is skipped directly, no OCC call.

**Measured impact on Part3:** the bridged wire's score went from the broken
0.00 to a legitimate **0.70** (vs the original selection's 0.77) — still
correctly discarded (genuinely close, but the original is a bit better on
quality with coverage tied at 18.6%), but now for an *honest* reason instead
of a nonsensical one. Part3's overall readiness improved from `review`
(0.635) to **`ready` (0.806)**, since the same quality-scoring fix also
raises the score of the retained original selection. Part1 unaffected.

Verified on real OCC in Docker: 29 parting-line tests (1 new, locking both
the label-override fix and the recompute-on-substitution fix together) +
205 others pass.

---

### 2026-07-27 — Bug H-2: ring bridging implemented; loops now genuinely close; new bottleneck found and precisely diagnosed

Followed through on Bug B's finding: bridging built a spanning tree (proven
structurally acyclic), so no wire tracer could ever close it. Implemented
the suggested fix and iterated through three real bugs it surfaced along the
way — each confirmed with direct measurement, not assumption.

**1. Ring bridging (`_bridge_via_angular_ring`), replacing the tree
strategy.** Orders components by angle around their collective centroid (in
the pull-normal plane) and bridges each to its next angular neighbor,
wrapping around — N links for N components, a cycle by construction, not
N-1 (a tree). Tried first; falls back to the old tree strategy only when
inapplicable or when nothing is reachable at all.

**2. First filter calibration was wrong — fixed with real data, not a
guess.** The initial per-component filter (drop components below 10% of the
largest one's coverage) excluded 17 of Part3's 22 components. Measured the
actual distribution before re-tuning: coverage ranged from 18.6% down to a
long tail of sub-1% fragments that are still genuine silhouette pieces, with
only 2 of 22 truly degenerate (~0%). Threshold dropped to 0.1% of the part's
extent (absolute), targeting only real degenerates.

**3. Fixed links left permanent gaps — replaced with an adaptive walk.** A
naive fixed ring (bridge index i to i+1) left the cycle broken wherever one
link was unreachable (e.g. blocked by undercut-face exclusion) — Part3 hit 2
such gaps, leaving 2 disconnected open arcs instead of one loop. Rewrote as
an adaptive walk: skip an unreachable neighbor, try the next one in angular
order, continue around, then explicitly close back to the start. Verified:
Part3 now produces one genuinely closed 18-component cycle (up from 2 broken
arcs), confirmed via `nx.number_connected_components` and a completed
`nx.find_cycle`.

**4. Found and fixed a real bug in Bug B's own contraction step.** Even with
a genuine cycle in the graph, the exact search still reported no closure.
Cross-checked with `nx.find_cycle` (independent of my own code) — it found a
15-edge cycle my search had missed entirely. Root cause:
`_contract_degree2_chains` dropped "self-loop" hyper-edges (a chain that
leaves and returns to the same junction) as presumed dead-end spurs — but a
genuine closed loop can attach to the rest of a graph at only one junction,
in which case it *is* a self-loop by construction. The heuristic was
filtering out the answer before the search could see it. Fixed: keep every
hyper-edge; let the search (not a pre-filter) decide what to use.

**5. Added a guaranteed-correct fallback for when the exact search's budget
runs out.** Finding the *optimal* weighted closed trail is near-NP-hard;
finding *some* cycle is polynomial. Measured on Part3's real 269-edge
ring-bridged graph: even with a 55-hyper-edge contracted space and a
3,000,000-state budget, the exhaustive search hit its limit without
resolving closure — `nx.cycle_basis` found and scored real candidate cycles
in under a second. `_find_any_cycle_via_networkx` is now a last-resort tier:
score every cycle in `nx.cycle_basis` by the same edge-weight function the
exact search uses, and take the best; fall back further to plain
`nx.find_cycle` only if that's empty. Whether it's actually used is still
gated by the existing accept/reject comparison, so this can only ever
improve outcomes.

**6. Fixed a real honesty bug in the discard message.** With all of the
above, Part3's bridged wire now genuinely closes (`is_closed=True`,
confirmed) — and is still correctly discarded, because it doesn't improve
on the original selection (coverage 18.6% vs 18.6%, quality score 0.00 vs
0.16 — essentially a wash on coverage, worse on quality). But the discard
message unconditionally said "did not close the loop" regardless of the
real reason. Fixed to report the true reason (closed-but-not-better vs
genuinely didn't close) and the actual coverage numbers on both sides.

**New, more precise bottleneck found — not yet fixed.** The bridged wire's
quality score is measured from `branch_point_count`/`skipped_edge_ids`
computed over the *entire input component* (269 edges, 36 branch points),
not the *specific closed loop actually selected* (18 links, far cleaner).
Even a genuinely good extracted loop is scored as if the whole messy haystack
it was found in is the answer. This conflation — input messiness vs. output
quality — is architecturally distinct from Bug B (search correctness) and
Bug H-2 (bridging topology), both of which are now genuinely fixed and
verified. Tracked as a new, separately scoped item; not attempted in this
pass given the amount of ground already covered.

Verified on real OCC in Docker: 28 parting-line tests (2 new: ring bridging
excludes local features and connects the rest into a genuine cycle; ring
bridging closes a 4-corner square loop a tree structurally could not) + 205
others pass. Part1 unaffected (94.8%, `ready` 0.792 — the 0.1% area drift
from `1487→1360mm²` is real self-loop inclusion changing the refined curve
slightly, not a regression). Part3 pipeline timing: ~17s (was ~8-11s before
ring bridging; the added cost is the 3M-state contracted search plus
`cycle_basis` scoring, both bounded and safe — no hang risk, confirmed by
direct timing).

---

### 2026-07-27 — Bug B fixed (exact search replaces greedy fallback); Bug H-2's real root cause proven

**Bug B — genuinely fixed, in both places it existed.** Two separate
functions ordered candidate edges into a wire, and both fell back to a
non-backtracking greedy walk once the graph got large:
- `_trace_best_weighted_path` (refinement of the already-selected wire) —
  bounded exhaustive DFS up to 22 edges, greedy above that.
- `_build_ordered_wire` (initial per-component ordering, used everywhere
  including the bridging accept/reject decision) — **always** a pure greedy
  walk, with no exact search at all, regardless of size. This is why the
  earlier BUG B fix (which only touched `_trace_best_weighted_path`) didn't
  change Part3's outcome: the function that actually decides whether a
  bridged super-component closes was never touched.

Fixed with one shared exact-search dispatcher,
`_best_path_with_contraction_fallback`, used by both:
1. **Contraction (new).** `_contract_degree2_chains` collapses maximal
   chains of degree-2 nodes into single "hyper-edges" before searching — a
   candidate-edge graph traced from real geometry is mostly a simple curve
   with occasional branches. Measured on Part3's 254-edge bridged graph:
   only 36 of 236 nodes were real junctions; the exhaustive search now
   reasons about 50 hyper-edges instead of 254 raw edges. Self-loop
   hyper-edges (a chain that leaves and returns to the same junction — a
   dead-end spur, e.g. a small hole rim) are dropped from the search unless
   the whole graph reduces to one such loop, in which case it's kept (it IS
   the answer).
2. **`_build_ordered_wire` gets the search as an additive second pass** —
   its original greedy walk runs unchanged first; the search only replaces
   the result when it finds a genuine closed loop the greedy walk missed,
   never when the greedy walk already succeeded. Zero behavior change for
   every case the existing 27 tests already covered; only engages for the
   specific case that was previously silently broken.
3. **Search budget split.** The contracted graph is far smaller, so it gets
   a much larger state budget (3,000,000 vs. 75,000) — cheap per-state
   since the graph itself is small. Measured on Part3's real 50-hyper-edge
   graph: the search now runs to full completion (177,032 states, well
   under budget) instead of exhausting the old 75,000-state budget mid-search
   with an inconclusive partial result.

Verified on real OCC in Docker: 27 parting-line tests + 205 others pass.
Part1/Part3 pipeline timing unaffected (~8–9s each) — the larger budget
never risks a hang because it only engages on the much smaller contracted
graph.

**Bug H-2's real root cause — now proven, not just suspected.** With Bug B's
search running to full, exhaustive completion, it definitively shows Part3's
bridged 259-edge super-component has **no closed loop through any subset of
it** — not a search limitation, a structural fact about the graph. Reading
`_bridge_disconnected_components` confirms why: its merge loop guards with
`if _find(ci) == _find(cj): continue` before every merge — textbook
union-find/MST construction, which strictly reduces component count by
exactly 1 per successful round. By definition this produces a **spanning
tree** over the original components, containing zero cycles among the
bridge connections. No wire tracer, however exhaustive, can find a closed
loop through a graph whose connecting structure is provably acyclic.

Fixing this needs a different bridging strategy — one that produces a ring
over components instead of a tree (e.g. order components by projected angle
around the part's silhouette centroid and bridge each to its next angular
neighbor, explicitly closing the ring) rather than greedy-cheapest-pair-first,
which inevitably builds a tree. This is new scope beyond Bug B, not yet
attempted; the `silhouette_coverage_ratio` warning (Bug H) means the gap
stays visible rather than silently passing in the meantime.

---

### 2026-07-27 — Bug D fixed, Bug H-2 narrowed to the real blocker (Bug B's tracer)

**Bug D (performance) — genuinely fixed.** `_bridge_disconnected_components`
called `nx.shortest_path(source, target)` fresh for every `(ep_i, ep_j)`
endpoint pair on every merge round — O(rounds × pairs × |ep_i| × |ep_j|) full
Dijkstra runs, recomputed from scratch each round even though the underlying
graph never changes. On Part3 (22 components, ~209 endpoints) this measured
at 373,000+ Dijkstra calls and **did not finish in 10+ minutes**. Fixed by
running one `nx.single_source_dijkstra` per unique endpoint up front and
reusing the resulting distance/path maps as O(1) lookups for every round.
Part3 bridging now completes in **under 1 second** as part of an ~11s total
pipeline run. Verified: identical merge decisions to the old algorithm
(same cheapest-bridge-first greedy strategy), just no longer recomputing
the same shortest paths thousands of times.

**Bug F's "skip bridging when closed" guard made coverage-aware.** The
guard assumed a closed loop is automatically the right one. On Part3 the
pre-bridge selection was already closed (47 edges) but covered only 18.2% of
the part's projected extent — a real closed loop, just the wrong one. The
fast path now requires `is_closed AND coverage >= min_silhouette_coverage_ratio`
before skipping bridging; otherwise bridging is attempted and the result is
compared against the original using both quality *and* coverage.

**Bridging now stops once a tree's coverage crosses the target, instead of
indiscriminately fusing every disconnected component.** Previously, once
triggered, bridging merged literally everything reachable into one
super-component regardless of whether the added pieces were genuine
silhouette fragments or unrelated local features (hole rims, bosses) —
on Part3 that produced a single 22-way merge including a 162 mm bridge
jump. Bridging now tracks the projected coverage of the tree it is growing
after each merge, stops as soon as it crosses `min_silhouette_coverage_ratio`
(leaving the rest unmerged as probable local features), and otherwise keeps
whichever intermediate tree had the best coverage of any seen — never the
blind full merge. New unit test
`test_bridging_stops_once_coverage_target_is_reached_leaving_local_features_unmerged`
locks this with a synthetic 3-component scene (two opposite corners + one
central "hole" component) and asserts the central component is left out.

**Bug H-2 is narrowed, not solved — and the real blocker is now precisely
identified.** With both fixes above, bridging on Part3 completes fast and
merges 20 of 22 components (up from being unable to finish at all) — but the
resulting wire still scores 0.00 quality and fails to close, so it is
correctly discarded and the original 18.2%-coverage selection is retained.
Measured the theoretical ceiling: combining every candidate edge point
(ignoring connectivity entirely) reaches **49.9%** projected coverage — above
the 35% target — proving Part3's true silhouette data length *is* present in
the candidate set. The blocker is downstream: `_trace_best_weighted_path`
(the function that orders a component's edges into a wire) exhaustively
searches only up to `search_edge_limit=22` edges; above that it falls back to
a single-pass greedy walk with **no backtracking** (`strategy="greedy-fallback"`),
which fails to find a closed traversal through Part3's ~278-edge merged
graph. This is the same gap TODO.md's "Milestone 1.6" entry only partially
closed: networkx is used for adjacency queries, but the actual best-loop
search algorithm was never replaced. BUG H-2 cannot be fully fixed until
BUG B's tracer is. See updated BUG B/BUG H-2 entries below.

Verified on real OCC in Docker: 27 parting-line tests pass (one new, for the
early-stop behavior), 205 in the rest of the suite. No regression on Part1
(94.9% coverage, `ready` 0.792, unchanged — bridging correctly still not
needed there).

---

### 2026-07-27 — Bug H: parting line now selects the MAIN silhouette (Nee maximum-contour rule)

**Bosch criterion #3 was functionally wrong while every metric read healthy.**
The engine reported readiness 1.000 and wire quality 0.96 while having
selected a *hole rim* as the parting line. Measured projected area of the
selected loop against the part's own projected extent:

| Part | Before | After |
|---|---|---|
| Part1 | 27.6 % | **94.9 %** |
| Part3 | 1.0 % | 18.2 % (flagged — see below) |

**Root cause.** `_wire_selection_key` ranked `projection.abs_area_mm2`
**fifth**, behind `projection_rank` and `quality_assessment.score`. Nee et al.
1998 specifies *"largest projected area (maximum contour rule)"* as the
**primary** criterion — so the engine was systematically preferring a small
tidy loop over the large slightly-messy one that is the actual parting line.
Ranking is now, in order: validity gate → undercut-conflict avoidance →
**projected area** → quality → previous tiebreakers.

Conflict avoidance deliberately stays *above* area: a parting line through a
critical undercut region is not made acceptable by being large, and
`test_undercut_conflict_penalty_prefers_clean_parting_loop` locks that order.

**Readiness scores dropped, and that is the correct outcome.** Part1 went
1.000 → 0.792 and Part3 → `review` (0.670). The engine now selects a branched,
genuinely messier component — because that is what the real main silhouette
looks like — instead of scoring a hole rim as perfect. An honest 0.792 on the
right curve beats a dishonest 1.000 on the wrong one.

**New guard — `silhouette_coverage_ratio`.** The failure mode above was
invisible: nothing compared the selected loop against the part. The result now
carries the loop's projected bounding-box area divided by the part's, in the
pull-normal plane, and warns below
`parting_line.min_silhouette_coverage_ratio` (0.35). Part1 passes silently at
94.9 %; **Part3 correctly fires the warning at 18.2 %**.

**Part3 is improved but not solved.** Its silhouette is fragmented across 22
components and no single component covers it, so ranking alone cannot fix it —
it needs targeted bridging, which now interacts with the Bug F fix that skips
bridging when a closed loop already exists. This is tracked as an open item;
the coverage warning means it can no longer pass silently in the meantime.

Verified on real OCC in Docker: `tests/test_parting_line.py` 26 passed
(3 deselected — the two BUG G hangs plus one), rest of suite 205 passed.

---

### 2026-07-27 — Stage 1.4: parting surface generation fixed (Bug E)

`_build_parting_surface` produced **no surface at all** for either part,
blocking Milestone 1.10's solid split and 1.11's export. Three distinct
causes, all fixed.

**1. `BRepFill_Filling` was constructed with illegal arguments.**
The real signature is
`(Degree, NbPtsOnCur=15, NbIter=2, Anisotropie, Tol2d=1e-5, Tol3d=1e-4, …)`.
The call passed `(degree, 0, 0, False, tol)` — i.e. `NbPtsOnCur=0` and
`NbIter=0` — so OCC rejected it outright with
`Standard_ConstructionErrorGeomPlate : Number of iteration must be >= 1`.
The filling path could therefore *never* run. Now uses OCC's own defaults
for the solver knobs, and puts the caller's tolerance on `Tol3d` (a 3-D
distance) rather than `Tol2d` (a parametric tolerance).

**2. The loop was ~24,000 points — unusable as a constraint set.**
`refined_points` is a *display* polyline (Chaikin smoothing + resampling).
Filling takes one edge constraint per segment, so it was being handed
~24,000 constraints. New `_decimate_closed_loop()` uniformly samples the
loop down to `filling_max_constraint_edges` (120) while preserving closure.

**3. The planar strategy had no pull-direction check.**
A mold opens along the pull axis, so a parting plane's normal must be
roughly parallel to it — but PCA finds the plane that best *fits* the
points, which is a different thing. Measured on Part3: PCA fits the loop to
0.74 mm while sitting ~60° off the pull axis (`|dot(n, pull)| = 0.503`);
accepting it would have sliced the mold diagonally instead of separating
cavity from core. The planar path now additionally requires
`|dot(plane_normal, pull)| >= planar_pull_alignment_min` (0.90).

**Measured planarity — both parts have genuinely 3-D parting lines**, so the
filling path is the *normal* path, not an exotic fallback (Nee et al. 1998 is
titled "Automatic Determination of **3-D** Parting Lines and Surfaces" for
exactly this reason):

| Part | pull-axis span of loop | bbox diagonal | ratio |
|---|---|---|---|
| Part1 | 16.16 mm | 30.78 mm | 52% |
| Part3 | 7.14 mm | 68.12 mm | 10% |

**Stage 1.4 gate — PASSED on both parts:**

| | Part1 | Part3 |
|---|---|---|
| surface status | `generated_filling` | `generated_filling` |
| area | 5344.29 mm² | 172.36 mm² |
| `occ_shape` present | ✅ | ✅ |
| readiness | ready (1.000) | ready (1.000) |
| blocks core/cavity | False | False |

New config: `dfm.parting_surface.planar_pull_alignment_min` (0.90),
`filling_max_constraint_edges` (120).

**Verification**: 24 passed, 0 regressions (3 deselected — BUG G).

**⚠️ BUG H found while sanity-checking the green gate** — see `TODO.md`.
The surface is now generated, but it is being generated around the *wrong
loop*. Projected area of the selected parting loop vs the part's projected
extent: **Part1 27.6%, Part3 1.0%** (10 selected edges out of 202
candidates). Part3 is selecting a small feature/hole rim rather than the
outer silhouette. Root cause: `_wire_selection_key` ranks projected area
only **5th**, behind `projection_rank` and `quality_assessment.score`,
whereas Engine.md/Nee 1998 specifies *"largest projected area (maximum
contour rule)"* as the **primary** criterion. A tidy small closed loop
therefore outranks the true main silhouette. Every metric reads healthy
(readiness 1.000, quality 0.96) while Bosch criterion #3 is functionally
wrong — a good example of why the geometry, not the score, has to be
checked.

---

### 2026-07-27 — Stage 1.1: parting-line correctness restored (Bugs A + F)

Independent audit of Milestones 1.6–1.11 (see `docs/ENGINE_AUDIT_2026-07-27.md`
and `docs/RECOVERY_PLAN.md`) found the parting-line stage was **reporting
success while emitting a broken result**, blocking every downstream stage.
Two defects fixed.

**Bug A — closure was claimed, never performed (`_attempt_loop_closure`).**
- The function computed a closing path through the B-Rep edge graph and then
  **discarded it**, unconditionally returning `(True, 0.0)`. Its return type
  had no channel for geometry and it never touched the point list. On real
  Part1 it reported `closure_guaranteed=True, closure_error_mm=0.0` while
  handing downstream a curve with a **17.35 mm gap** — and a parting
  *surface* was then built from that open curve.
- Now returns `(guaranteed, error, closed_points, bridge_edge_count, warnings)`:
  it maps the path's quantized node keys back to real 3-D vertices via a new
  `key_to_point` map, splices them into the curve, closes it exactly, then
  **re-measures the result and refuses to report success if the residual gap
  still exceeds tolerance.**
- The caller now uses the spliced curve and rebuilds `refinement` so
  `refined_points` (what `main.py` serialises for the viewer) matches what
  the surface was actually built from.
- New `PartingLineResult.closure_bridge_edge_count`.

**Bug F — bridging destroyed an already-good closed loop (Milestone 1.7).**
- Root cause of the readiness regression. Bridging ran unconditionally
  (the API never passes `bridge_components`, so it defaulted to `True`) and
  merged **all** components into one branchy super-component, even when
  `_select_projected_wire` had already found a clean closed loop.
- Measured on Part1 at its optimal direction, bridging the only variable:

  | | bridging OFF | bridging ON |
  |---|---|---|
  | readiness | ready (1.000) | weak (0.080) |
  | selection quality | high (0.96) | empty (0.0) |
  | `is_closed` | True | False |
  | branch pts / gaps | 0 / 0 | 11 / 15 |
  | blocks core/cavity | False | **True** |
  | elapsed | 0.2 s | 49.8 s |

- Bridging is now a **fallback**: skipped entirely when a closed loop is
  already selected, and when it does run its result is kept only if it
  closes the loop or does not reduce quality. New
  `PartingLineResult.bridging_status` makes the decision inspectable
  (`not_needed` / `applied` / `discarded_not_an_improvement` /
  `unavailable` / `disabled`). The skip is deliberately **not** a warning,
  so it no longer costs readiness score.

**Stage 1.1 gate — PASSED on both parts**, run exactly as the API runs it
(optimal direction, `bridge_components` at its default):

| | before | after |
|---|---|---|
| readiness | weak (0.08) | **ready (0.999)** |
| blocks core/cavity | True | **False** |
| report-ready | False | **True** |
| parting-line elapsed | 49.8 s | **0.23 s** |
| MEASURED first→last gap | 17.35 mm | **0.000000 mm** |

Reported closure now agrees with measured geometry on Part1 **and** Part3.

**Regression guards added** (`tests/test_parting_line.py`, 4 new): reported
closure must match measured geometry; a non-zero bridge count must mean
points were really added; an unclosable loop must report failure honestly;
bridging must not run when a closed loop already exists. These measure
geometry rather than structure — the entire bug class was invisible to the
existing mock-based tests.

**Verification**: 24 passed, 0 failures. Three tests deselected — see BUG G.

**BUG G found (pre-existing, not from this change)**: two
`test_parting_line.py` tests hang forever against real pythonocc-core
(`EdgeData(start=None, end=None, occ_edge=MagicMock())` → real OCC calls on
a mock). **Confirmed pre-existing via a `git stash` A/B** — baseline code
hangs identically, which means the earlier "28 tests pass" claim for
Milestones 1.9–1.11 was not a completed real-OCC run. Logged in `TODO.md`.

---

### 2026-07-27 — Phase 2c/2d/2e: Depth design decision, overclaim check, Part3 audit

**Phase 2c — Undercut depth: precision vs. conservative max (team decision documented):**
- Added a comprehensive class docstring to `UndercutFeature` in
  `backend/geometry/undercut_detector.py` explaining the intentional design:
  `depth_proxy_mm` takes the *largest* plausible estimate (conservative safety margin)
  while `BooleanInterferenceMetrics.depth_mm` prefers the most precise. This
  difference is documented as intentional (better to over-estimate than under-estimate
  undercut depth for mold engineering). An attempted "prefer precision" fix was reverted
  after breaking 3 tests (Milestone 1.3). The docstring references the relevant ARCHITECTURE_ROADMAP
  section and TODO decision record.
- Decision: keep feature-level as conservative upper bound. No code change.

**Phase 2d — SUBMISSION_REPORT.md overclaim check:**
- Verified `docs/SUBMISSION_REPORT.md` is already correctly qualified:
  - Parting line: "Candidate/foundation" (accurate)
  - Core/cavity: "Complete for face classification only" (accurate; now also has solid split)
  - Honest limitations section (lines 46-50) correctly qualified
- Checked off in `TODO.md`. No further action needed.

**Phase 2e — Part3.stp undercut count 0 domain analysis:**
- Updated STATUS.md with explicit domain reasoning: if ALL 16 originally flagged faces sit
  on external convex features (bosses, ribs with all-convex edge transitions), suppression
  to 0 is geometrically correct — those faces have no concave edges, so they cannot form
  genuine pockets. The suppression logic is verified correct on synthetic test cases.
- A 100% swing on a real part still needs Docker verification (compare `face_ids` +
  `surface_type` + edge convexity classifications with suppression on/off) and mold
  engineer sign-off before using the 0-undercut result in demo claims.
- Documented in STATUS.md as a known pending domain review.

---

### 2026-07-27 — Milestone 1.11: Multi-solid STEP export via STEPControl_Writer

- New `export_mold_halves()` function in `backend/geometry/core_cavity.py`:
  - `STEPControl_Writer` with `Interface_Static.SetCVal("write.step.schema", "AP214")` —
    matching the source file schema (locked decision from 2026-07-27).
  - Transfers cavity and core solids via `writer.Transfer(solid, STEPControl_AsIs)`.
  - Writes to `output/mold_halves/` (never `data/parts/` — invariant #2 explicitly enforced
    with a path guard: if the resolved export path is a subdirectory of `data/parts/`, the
    function returns `status="failed"` with a clear reason).
  - Returns JSON-safe dict: `status`, `output_path`, `file_size_bytes`, `schema`, `solid_count`.
  - Gracefully handles missing OCC writer, failed solid result, and write errors.
- New API endpoint `POST /parts/{filename}/export/mold-halves` in `backend/api/main.py`:
  - Runs the full pipeline (load → direction → parting line → solid split → export).
  - Returns: `filename`, `pull_direction`, `parting_surface_status`, `solid_split`, `export`.
  - Accepts optional `output_dir` query param to override the default export directory.
- `.gitignore` updated: added `output/mold_halves/` to exclude generated STEP artifacts.
- OCC imports extended in `core_cavity.py`: `Interface_Static`, `IFSelect_RetDone`,
  `STEPControl_Writer`, `STEPControl_AsIs`.
- **Verification**: 28 tests pass. STEP export with real OCC requires Docker.
  Round-trip verification (reload exported file, count 2 solids) is the Docker gate.

---

### 2026-07-27 — Milestone 1.10: Core/cavity Boolean solid split

- New `CoreCavitySolidResult` dataclass and `split_core_cavity_solids()` function in
  `backend/geometry/core_cavity.py`:
  - Step 1: `BRepPrimAPI_MakeBox` mold blank (bbox + `blank_margin_factor × diagonal` on each side).
  - Step 2: `BRepAlgoAPI_Cut(blank, part.occ_shape)` → tooling volume, with fuzzy-tolerance
    retry ladder `[1.0, 5.0, 25.0] × split_fuzzy_factor`.
  - Step 3: `BRepAlgoAPI_Splitter(tooling, parting_sheet)` → two mold halves.
  - Step 4: `GProp_GProps` centre-of-mass for each solid; classify by
    `sign(dot(CoM − parting_centroid, pull_direction))` → cavity / core.
  - Graceful degradation: `solid_split_status` = "blocked_by_parting_line" (no sheet),
    "failed" (OCC error, with `failure_reason`), or "split_ok" (2 solids returned).
  - `split_solid_count` is always reported even on failure (actual count, not assumed 2).
  - `cavity_solid` / `core_solid` are raw `TopoDS_Shape` objects for Milestone 1.11 export;
    not serialized in `to_dict()`.
- OCC imports added with guard: `BRepAlgoAPI_Cut`, `BRepAlgoAPI_Splitter`,
  `BRepBndLib`, `BRepGProp`, `BRepPrimAPI_MakeBox`, `TopExp_Explorer`,
  `GProp_GProps`, `gp_Pnt`.
- `backend/api/main.py`: `/core-cavity` endpoint now accepts `solid_split: bool = False`.
  When `True`, runs `detect_parting_line_candidates` to get the parting surface, then
  `split_core_cavity_solids`; result in `payload["solid_split"]`.
- New config keys: `dfm.core_cavity.blank_margin_factor: 0.25`, `solid_split_enabled: true`,
  `export_dir: "output/mold_halves"`, `split_fuzzy_factor: 0.1` — all in `config.yaml` and
  `CoreCavitySettings`.
- `IMPLEMENTATION_STATUS.md` note: `core_cavity.py` no longer face classification only.
- **Verification**: 28 tests pass (`test_parting_line.py` + `test_api_error_handling.py`).
  Solid split requires real OCC (Docker); mock-based tests are unaffected.

---

### 2026-07-27 — Milestone 1.9: Parting surface generation

- New `PartingSurfaceResult` dataclass in `backend/geometry/parting_line.py` with fields:
  `status`, `strategy`, `planar_deviation_mm`, `extension_factor`, `area_mm2`,
  `failure_reason`, `occ_shape` (not serialized). Exposes `to_dict()` for API.
- New `_build_parting_surface()` function:
  - **Strategy 1 (PCA planar, preferred)**: NumPy SVD on loop points → best-fit plane.
    If max deviation ≤ `planar_tolerance_mm` (0.25 mm): builds OCC wire from loop points via
    `BRepBuilderAPI_MakeEdge/MakeWire`, trims a bounded face with `BRepBuilderAPI_MakeFace`,
    extrudes past bbox via `BRepPrimAPI_MakePrism` (factor = `extension_factor` × bbox diagonal).
  - **Strategy 2 (BRepFill_Filling, fallback)**: N-sided patch from loop edges as boundary
    constraints. Returns a `TopoDS_Face` without extrusion.
  - Both strategies compute area via `brepgprop_SurfaceProperties` for verification.
  - Graceful failure path on any OCC error (`status="failed"`, `failure_reason=...`).
  - Protected by `_OCC_SURFACE_AVAILABLE` guard — degrades cleanly when pythonOCC is absent.
- `detect_parting_line_candidates()` calls `_build_parting_surface()` when `closure_guaranteed`
  is True; otherwise sets `status="not_attempted"`.
- `PartingLineResult` gets new `parting_surface: PartingSurfaceResult` field.
- New config section `dfm.parting_surface` in `config.yaml` and `PartingSurfaceSettings`
  in `backend/config.py`: `planar_tolerance_mm: 0.25`, `extension_factor: 1.5`,
  `filling_max_degree: 3`, `filling_tolerance_mm: 0.01`.
- New OCC imports added with try/except guard: `BRepBuilderAPI_MakeEdge/MakeFace/MakeWire`,
  `BRepFill_Filling`, `BRepPrimAPI_MakePrism`, `GProp_GProps`, `brepgprop_SurfaceProperties`,
  `gp_Dir/Pln/Pnt/Vec`. Also imports numpy as `_np` (already in the conda environment).
- **Verification**: all 23 `tests/test_parting_line.py` tests pass unchanged (1.84s).
  Note: OCC surface generation is not exercised in mock-based tests (requires real geometry).
  Verification with real OCC requires Docker.

---

### 2026-07-27 — Milestone 1.8: Loop closure guarantee + gating

- New function `_attempt_loop_closure()` in `backend/geometry/parting_line.py`:
  - If wire is already closed: returns `(True, 0.0, [])`.
  - If closure error ≤ `max_closure_error_mm` (0.05 mm): treats wire as closed.
  - Otherwise: rebuilds `G_all` from all part edges (same bridge-cost scheme as 1.7) and
    attempts `nx.shortest_path` from the wire's last endpoint back to its first.
  - If closing path found: returns `(True, 0.0, [message])`.
  - If closing path not found: returns `(False, error_mm, [review-warning messages])`.
    The warning message tells downstream consumers and the UI that readiness must be
    "review" — closure failed and the loop is genuinely open.
- `detect_parting_line_candidates()` now accepts `max_closure_error_mm: float = 0.05`.
- `PartingLineResult` gets two new fields: `closure_error_mm: float` (default 0.0) and
  `closure_guaranteed: bool` (default False); both appear in `to_dict()`.
- The method string in `PartingLineResult` updated to mention Milestones 1.7 and 1.8.
- New config keys `max_closure_error_mm: 0.05` and `max_components_exact_cycle: 8` already
  added to `config.yaml` and `PartingLineSettings` in Milestone 1.7 prep.
- **Verification**: all 23 `tests/test_parting_line.py` tests pass unchanged (1.83s).

---

### 2026-07-27 — Milestone 1.7: Bridge disconnected silhouette components via real B-Rep edges

- New function `_bridge_disconnected_components()` in `backend/geometry/parting_line.py`:
  - Builds `G_all` as a `nx.Graph` over ALL part edges (not just candidates).
  - Bridge cost per edge: `1.0 × length` (candidate, free to reuse), `boundary_bridge_factor ×
    length` (boundary — cheaper, since open rims are often where the PL should run),
    `bridge_penalty_factor × length` (non-candidate manifold), `+inf` if any adjacent face
    is a known undercut face (never route through undercut geometry).
  - Routes between disconnected component endpoint-pairs via `nx.shortest_path(weight="cost")`.
  - Greedily connects all reachable components (union-find), building a single merged
    `PartingLineComponent` containing candidate + bridge edges.
  - Bridge edges get `kind="bridge"` in `candidate_kinds` so they are distinguishable
    from silhouette/near-parting edges in diagnostics.
- `detect_parting_line_candidates()` now accepts `bridge_components: bool = True`,
  `bridge_penalty_factor: float = 4.0`, `boundary_bridge_factor: float = 0.6` params.
  Bridging is called between `_candidate_components()` and `_build_ordered_wire()` when
  there are 2+ components and networkx is available.
- Bridge status messages are prepended to the result's `warnings` list.
- New config keys in `config.yaml` and `PartingLineSettings`:
  `bridge_penalty_factor: 4.0`, `boundary_bridge_factor: 0.6`.
- Also added Milestone 1.8 config keys: `max_closure_error_mm: 0.05`,
  `max_components_exact_cycle: 8` (used by upcoming closure-guarantee step).
- **Verification**: all 23 `tests/test_parting_line.py` tests pass unchanged (1.87s).
  Bridging is a no-op for single-component parts (skipped when `len(components) < 2`).

---

### 2026-07-27 — Milestone 1.6: Replace bounded DFS with networkx graph in parting_line.py (F4 resolved)

- Added `import networkx as nx` (with `_NX_AVAILABLE` guard for robustness) to
  `backend/geometry/parting_line.py`.
- In `_trace_best_weighted_path`, replaced the hand-rolled `point_to_edges: dict[tuple,
  set[int]]` adjacency structure with an explicit `nx.MultiGraph`:
  - Each quantized vertex key becomes a graph node.
  - Each candidate edge becomes a MultiGraph edge carrying `edge_id` as data.
  - Adjacency queries (`point_to_edges.get(key)`) → `point_to_edges_of(key)` backed by
    `G.edges(key, data=True)`.
  - Branch-point counting (`len(edge_ids) > 2`) → `_branch_point_count()` via
    `G.degree(node) > 2`.
- A plain-dict fallback is kept for environments where networkx is not installed
  (though `requirements.txt` pins `networkx==3.3`).
- The existing bounded DFS and greedy traversal paths are unchanged — only the
  adjacency representation changed.
- **Verification**: all 23 `tests/test_parting_line.py` tests pass unchanged (1.91s).
  `_NX_AVAILABLE = True` confirmed at import time with networkx 3.4.2.
- F4 marked resolved in `STATUS.md` and `TODO.md`.

---

### 2026-07-27 — Phase 2a/2b/2f: test fix, mock hygiene, CLAUDE.md hard invariant #6

**Phase 2a — Fix `test_parting_line_paths_payload_is_json_safe`:**
- Root cause: two stale test assertions in `tests/test_api_error_handling.py` lines 87/90.
  - Line 87: `assert payload["raw"]["visible_by_default"] is False` — code sets `True` (both
    overlays shown by default, matching the sidebar checkboxes at app.py:2901-2902).
  - Line 90: `assert payload["legend"]["refined"]["label"] == "Refined parting curve candidate"` —
    code has `"Parting Line (Refined)"` (PARTING_LINE_STYLES["refined"]["label"] at main.py:56).
- Fix: updated both assertions to match current code behavior. Verified: `pytest
  tests/test_api_error_handling.py::test_parting_line_paths_payload_is_json_safe` passes.

**Phase 2b — Mock test hygiene: explicit `boolean_refine=False` on mock-OCC tests:**
- Added `boolean_refine=False` to three `detect_undercuts()` calls in
  `tests/test_undercut_detector.py` (lines 68, 180, 355) — these use `occ_face=MagicMock()`
  and previously had no guard against real Boolean ops in a Docker environment with
  pythonocc-core installed.
- Added `monkeypatch.setattr(undercut_module, "_OCC_BOOLEAN_AVAILABLE", False)` to
  `test_optimize_mold_direction_mutates_part_to_best_direction` in
  `tests/test_direction_optimizer.py` (line 103) — same issue via the optimizer's internal
  `detect_undercuts` calls.
- All Boolean-enabled tests already used `monkeypatch.setattr(detector,
  "_swept_face_interference_volume", ...)` — those are safe and unchanged.
- Verified: all 4 modified tests pass immediately (< 0.25s combined). Previously they would
  stall for minutes in Docker.

**Phase 2f — CLAUDE.md hard invariant #6:**
- Added invariant #6: "After every milestone or fix, append a dated CHANGELOG.md entry,
  update STATUS.md, and check off TODO.md items. Do not batch — do it per milestone."
- This codifies the standard already applied to Milestones 1.1–1.5 as an enforced standing
  rule for every future session.

---

### 2026-07-27 — F6 fix (frontend crash: mesh caching + triangle ceiling)

**Root cause (confirmed by code reading):** Running "Full Level 1 Flow" on macOS
accumulated 6 full copies of the same mesh geometry (`points` + `faces` arrays,
~500 KB each) in `st.session_state` — one per analysis step (summary, draft,
undercuts, direction, parting-line, core-cavity). The backend is stateless and
re-triangulates from scratch for every request; each response included the full
mesh payload; `_store_step_result()` stored the entire response dict. Six copies
of ~500 KB = ~3 MB minimum, plus Plotly rendering overhead and Streamlit's full-
script rerun model → RAM grew monotonically → system memory pressure → Tornado
WebSocket buffer allocation failures → `WebSocketClosedError` / `StreamClosedError`
flood → laptop crash. Plotly (not PyVista) was already being used on macOS, so
the VTK Cocoa thread crash was not the issue.

**Fix — `frontend/app.py`:**
- New `_cache_and_strip_mesh(result)`: on first call, copies `points`, `faces`,
  `face_ids`, `face_centers`, and counts to `st.session_state["cached_display_mesh"]`.
  On subsequent calls, strips those same keys from the stored result's `display_mesh`,
  reducing each copy to only the overlay-specific arrays (`draft_rgb`, etc.).
- New `_hydrate_mesh(display_mesh)`: merges the cached geometry back with any
  step-specific overlay dict at render time (cached base + step overlays merged via
  `{**cached, **step_display_mesh}`).
- `_store_step_result()` now calls `_cache_and_strip_mesh(result)` before storing.
- `_reset_analysis_state()` now also pops `"cached_display_mesh"`.
- All 6 rendering sites (summary, draft, undercuts, direction × 2, parting-line,
  core-cavity) updated to call `_hydrate_mesh(result.get("display_mesh"))` instead
  of accessing `result["display_mesh"]` directly.

**Fix — `backend/geometry/visualize_raw.py`:**
- `build_display_mesh()` now accepts `max_triangle_count: int | None`.
- When the initial triangulation exceeds the limit, scales up `linear_deflection`
  proportionally (`deflection *= sqrt(actual / limit)`) and re-triangulates once,
  logging a warning. Default limit from `settings.dfm.display.max_triangle_count`.

**Fix — `backend/config.py` + `config.yaml`:**
- New `DisplaySettings` dataclass with `max_triangle_count: int = 100_000`.
- Added to `DFMSettings`; wired into `load_settings()` from `dfm.display` block.
- `config.yaml`: added `dfm.display.max_triangle_count: 100000`.

**Tracked as F6** in `STATUS.md` (open → resolved same session) and `TODO.md` (added + checked off).

**Verification required (manual):** Load Part3.stp on macOS, run "Full Level 1 Flow",
confirm no `WebSocketClosedError` in terminal, RSS stays under ~500 MB.

---

### 2026-07-27 — Phase 0 fixes + Phase 1.1 (edge convexity) + Phase 1.2 (convexity-gated suppression) + Phase 1.3 (reassessed, no change) + Phase 1.4 (flash risk + coarse-to-fine search) + Phase 1.5 (draft conditional thresholds, scoped)

**Phase 1.5 — Draft conditional thresholds (`backend/geometry/draft_analyzer.py`),
scoped to explicit override + global default:**
- `analyze_draft(..., face_conditions: Optional[dict[int, str]] = None)` —
  per-face override to one of four named conditions
  (`smooth`/`light_texture`/`heavy_texture`/`deep_rib`), each with its own
  config-overridable good/marginal thresholds
  (`dfm.draft.conditions.<name>.{good,marginal}`). Unknown condition names
  log a warning and fall back to the global default rather than raising.
  Every face's resolved threshold, source (`explicit_override` |
  `global_default`), and applied condition are reported in `face_results`.
- `_build_suggestions` now also groups by resolved condition, so a mixed
  smooth+textured group produces separate suggestions with the correct
  `required_angle_deg` each, instead of one group averaged across
  incompatible requirements.
- **Deliberately did not implement** the roadmap's tiers 2 (surface-type
  defaults) and 3 (automatic deep-rib geometric detection) — tier 2 is a
  no-op today since the roadmap's own honesty ruling defaults every surface
  type to "smooth" (STEP carries no texture data to justify anything else),
  and tier 3 needs a per-face 3-D bounding box plus a fuzzy
  "forms a narrow channel" adjacency check that wasn't verified in the time
  available. The `deep_rib` *condition* exists and is usable via
  `face_conditions` even without automatic detection. Full reasoning in
  `docs/ARCHITECTURE_ROADMAP.md` Milestone 1.5 note.
- Verified on real Part1.stp: marking a bad-draft face `light_texture`
  correctly raised its required threshold to 3.0°, correctly tagged
  `threshold_source=explicit_override`, left all other faces at
  `global_default`, and split it into its own suggestion group with the
  right required angle in the action text.
- New tests: `tests/test_draft_analyzer.py::TestFaceConditionThresholds` (6
  new, mock-based). Full suite re-run: 57 passed, 0 regressions.
- API wiring (accepting `face_conditions` on `/draft`) deferred to Phase 2
  — no value exposing it before the frontend has a texture-marking UI to
  call it from.

**Phase 1.4 — Flash risk term + coarse-to-fine direction search
(`backend/geometry/direction_optimizer.py`):**
- `_score_candidate` now includes a flash-risk term: faces nearly parallel
  to the pull direction (`|n·d| < sin(flash_angle_threshold_deg)`) AND thin
  (area below `flash_thin_area_factor × bbox_diagonal²`, a coarse
  wall-thinness proxy — true thickness needs ray casting/medial-axis
  analysis, out of scope) contribute to a weighted penalty term, placed
  between marginal-draft and bad-draft in the scoring hierarchy.
- New two-stage search: after the existing 54-candidate coarse grid is
  scored and sorted, a local cone (`generate_fine_candidate_directions`,
  ±15° at 5° steps by default) is sampled around each of the top-3 coarse
  winners, scored with the identical prefilter-only path
  (`mutate=False`, `boolean_refine=False`), merged in, and re-sorted before
  Boolean refinement selection. Capped at 60 additional candidates. The
  per-candidate scoring block (draft + undercuts + score + result
  construction) was factored into a shared `_score_direction_candidate`
  helper to avoid duplicating it for both stages.
- `mutate=True` still happens exactly once, for the single final winner —
  unchanged contract.
- Verified on real geometry (fine search on vs. off): Part1 best_score
  0.692→0.313 (−54.8%), Part3 6.415→1.384 (−78.4%) — the fine stage found a
  genuinely better direction on both real parts, not a marginal tweak.
  Candidate count increased by exactly 60 as designed; no timing regression.
- New config: `flash_risk_weight` (200.0), `flash_angle_threshold_deg` (5.0),
  `flash_thin_area_factor` (0.02), `fine_search_enabled` (true),
  `fine_search_top_k` (3), `fine_angular_step_deg` (5.0),
  `fine_search_cone_half_angle_deg` (15.0), `fine_search_max_candidates` (60).
- New tests: `tests/test_direction_optimizer.py` (8 new, mock-based, no OCC
  needed). The end-to-end test explicitly forces
  `_OCC_BOOLEAN_AVAILABLE=False` to avoid the mock+real-Boolean stall found
  during Phase 1.2 verification.

**Phase 1.3 — reassessed, no code change.** The roadmap's stated gap
("bounding-box span over-reports undercut depth") was based on a shallower
reading of `undercut_detector.py` than a detailed pass revealed. The
per-face depth function (`_select_boolean_depth_details`) already extracts
exact B-Rep vertices of the Boolean intersection shape and prioritizes them
over bounding-box/volume fallbacks — exactly what this milestone asked for,
already covered by 4 passing tests. Attempted the same "prefer precision"
fix at the feature-level aggregation layer
(`_estimate_release_and_depth_from_boolean_geometry`,
`base_depth_proxy = max(...)`), then **reverted it** after discovering it
broke 3 existing tests with exact numeric assertions
(e.g. `assert feature.depth_proxy_mm == 4.0` against a precise input of
`1.0`) — the feature-level "take the largest plausible estimate" behavior is
very likely an intentional conservative-safety-margin choice (overestimating
undercut depth is a cheap tooling inefficiency; underestimating it is a real
mold defect), not a bug. Flagged as a team decision in `TODO.md` rather than
silently overridden. Full reasoning in `docs/ARCHITECTURE_ROADMAP.md`
Milestone 1.3 note.

**Phase 0 (all verified against real OCC in Docker, not mocks):**
- **F1 resolved**: confirmed `Part1.stp` (522,419 B) and `Part3.stp` (863,881 B)
  are genuinely distinct Level 1 / Level 2 inputs, both AP214. Verified via a
  real Docker validation run: Part1 = 311 faces / 30.78mm bbox diagonal,
  Part3 = 414 faces / 68.12mm bbox diagonal — geometrically distinct, and
  Part3's much longer `direction_search` (628s vs Part1's 85s) is consistent
  with it being the more complex Level 2 part.
- **F2 fixed**: `dfm.core_cavity.threshold` added end-to-end (`config.yaml` →
  `CoreCavitySettings` → `classify_core_cavity()` → `/core-cavity` endpoint).
- **F3 fixed**: `.claude/rules/api-layer.md` endpoint table corrected.
- Corrected the "Complete" overclaims for parting line and core/cavity in
  `docs/SUBMISSION_REPORT.md`'s evaluation matrix.
- **New finding (F5, fixed)**: the documented test command
  (`docker compose exec backend pytest tests/ -v --tb=short`) never actually
  worked — no root `conftest.py` or root `pytest.ini` put `/app` on
  `sys.path`, so every test failed collection with `ModuleNotFoundError: No
  module named 'backend'`. A root-level `conftest.py` doesn't fix it either:
  `tests/pytest.ini` being the discovered config file pins pytest's
  `confcutdir` to `tests/`, so it never looks above that directory for a
  parent conftest. Fixed with one line — `pythonpath = ..` in
  `tests/pytest.ini` — pytest's native mechanism for exactly this layout.
  Verified with the exact documented command.
- Ran real OCC validation (`part_validation.py --direction --boolean-refine`)
  and the performance profiler in Docker; committed real (non-`skipped`)
  evidence to `reports/level1_validation/`. Both parts pass every stage:
  load, topology, draft, undercut detection, direction search, parting line
  (both report `readiness: ready` with an already-closed wire under the
  *existing* heuristics — a useful baseline ahead of Phase 1.8's closure
  guarantee).
- Also surfaced (not yet fixed): `test_api_error_handling.py::
  test_parting_line_paths_payload_is_json_safe` is a genuine test failure,
  unrelated to the import bug — needs investigation.

**Phase 1.1 — Edge convexity (`backend/geometry/step_loader.py`):**
- `EdgeData.convexity` (declared since the initial scaffold, never populated)
  is now computed at load time for every manifold, non-seam edge —
  pull-direction-independent, so it's cached once rather than recomputed per
  direction downstream.
- New config: `dfm.undercut.convexity_tangent_tolerance` (default 0.01).
- Discovered and worked around a genuine pythonOCC gotcha:
  `BRepAdaptor_Curve.D1` ignores `TopoDS_Edge.Orientation()`, so both the
  tangent sign and the adjacent-face order must be tied to the *same*
  reference face to get a consistent convexity classification — verified
  empirically (a cube's 12 edges came back 6/6 split before the fix, 12/0
  after). See `docs/ARCHITECTURE_ROADMAP.md` Milestone 1.1 note for detail.
- Verified against: a synthetic 10×10×10 cube (12/12 convex), a cube with a
  rectangular pocket (pocket floor's 4 edges concave, matching the roadmap's
  stated gate; pocket's 4 internal vertical corners also correctly concave;
  rim and original box edges correctly convex), and real `Part1.stp` (>90%
  of manifold edges classified). New tests:
  `tests/test_step_loader.py::TestEdgeConvexitySynthetic`.

**Phase 1.2 — Convexity-gated undercut false-positive suppression
(`backend/geometry/undercut_detector.py`):**
- A proxy-undercut face (draft angle below the marginal threshold) whose
  bounding edges are ALL convex/tangent — no concave edge, so no genuine
  pocket — is now cleared before Boolean refinement ever sees it. An
  unclassified (`None`) edge does NOT trigger suppression: this requires
  positive evidence, not merely the absence of a concave edge.
- New: `UndercutDetectionResult.convexity_suppressed_face_ids` (full
  traceability — suppressed faces are never silently dropped), config
  `dfm.undercut.convexity_suppression_enabled` (default `true`, kill switch).
- Fixed a real bug found during verification: a suppressed face that also
  falls inside the parting-region dot-product band (which, given the shipped
  defaults, is essentially every suppressed face — `sin(0.5°) ≈ 0.0087` is
  smaller than `parting_dot_threshold=0.01`) was left with `is_undercut=None`
  instead of an explicit `False`, because the pre-existing final mutate block
  only clears faces outside the parting band. Now mutated explicitly at the
  point of suppression.
- Verified on real geometry (suppression on vs. off, calm Docker environment):
  Part1 undercut count 44→18, Boolean-checked 78→27, 45.2s→13.4s;
  Part3 undercut count 16→0, Boolean-checked 97→3, 73.6s→1.9s. **Both
  directions of the gate hold** ("count unchanged or lower", "Boolean calls
  measurably down"). Part3's 100%-suppression swing is flagged for a mold
  engineer's visual sanity check, not just accepted on the strength of unit
  tests — see `docs/ARCHITECTURE_ROADMAP.md` Milestone 1.2 note.
- New tests: `tests/test_undercut_detector.py` (4 new, mock-based, no OCC
  needed — suppression logic is deterministic given `EdgeData.convexity`).
- **Found, not fixed (pre-existing, orthogonal to this milestone)**: any
  mock-based test building `FaceData(occ_face=MagicMock())` and calling
  `detect_undercuts()`/`optimize_mold_direction()` without explicit
  `boolean_refine=False` stalls for minutes against a container with real
  pythonocc-core, because the mock is fed straight into real
  `BRepAlgoAPI_Common`/`BRepPrimAPI_MakePrism` calls. Invisible before F5 was
  fixed (Docker test runs never worked at all until today). Tracked in
  `TODO.md`.

**Environment note**: mid-session, this machine's Docker VM was shared with
several unrelated heavy tenants (`redline_*`, `k3d-*`, 9+ days uptime,
individually using 70-80% CPU) that caused severe slowdown and at least one
OOM-kill (exit 137) of a `performance_profile.py` run. Those containers were
not touched (not this project's). They exited independently partway through
the session (unrelated teardown), after which the shared VM had far more
headroom and subsequent runs completed quickly and reliably. Worth remembering
if a future session sees inexplicably slow or OOM-killed Docker runs on this
machine: check `docker stats` across ALL containers, not just this project's.

**Why:**
Executing the roadmap phase-by-phase as agreed: Phase 0 unblocks everything
downstream; Phase 1 proceeds one milestone at a time, each with a Docker-verified
gate before moving to the next, per the user's explicit instruction not to
batch or rush ahead.

---

### 2026-07-26 — Architecture Roadmap & Master Specification

**What changed:**
- Created `docs/ARCHITECTURE_ROADMAP.md` — full 4-phase master specification:
  - **Phase 1 — Geometry engine hardening**: closed-loop parting line via `networkx`
    with B-Rep edge bridging (`EdgeData.is_boundary`); parting surface via PCA planar
    extrusion with `BRepFill_Filling` fallback; real core/cavity solid split
    (`BRepAlgoAPI_Cut` → `BRepAlgoAPI_Splitter`) and multi-solid `STEPControl_Writer`
    export; edge convexity to kill undercut false positives; extremal vertex depth;
    flash-risk scoring term and coarse-to-fine (±5°) direction search; surface-type
    conditional draft thresholds.
  - **Phase 2 — Frontend migration**: Streamlit → React + Vite + react-three-fiber.
    Core design decision is splitting `/geometry/mesh` (fetched once) from
    `/analysis/*` (per-face results only), with client-side overlay switching driven
    by the existing `faceId` triangle attribute. Requires a `PartGeometry` LRU cache,
    which deliberately amends the stateless-backend decision.
  - **Phase 3 — Real-world testing**: synthetic known-answer fixtures, real-OCC
    Docker suite, assertion flags in the validation harness, production Docker build, CI.
  - **Phase 4 — AI agent**: provider-agnostic layer, tool definitions, senior mold
    engineer prompt, structured `DfMReport` schema with `evidence_source`.
- Rewrote `TODO.md` around the roadmap's phase/milestone structure.
- Added an "Open Blockers" table and a corrected data inventory to `STATUS.md`.

**Findings recorded (all verified against the repo, not speculative):**
- **F1 (blocker)**: `Part1.stp` and `Part3.stp` are byte-identical — same MD5
  `a373ffdf57ebb1036ec43b9e77025afa`, same 863,881 bytes, both carrying the internal
  header `FILE_NAME('Part3.stp', …)`. `rename.stp` is 522,419 bytes with internal name
  `Element_Packaging_Cap.stp`, matching the 522 KB that STATUS.md records for Part1.
  The original Part1 appears to have been overwritten by a copy of Part3.
- **F2**: `core_cavity.py:14` documents a config key
  `dfm.parting_line.silhouette_dot_tolerance` that does not exist; `threshold=0.05`
  is hardcoded in the module and again in `main.py`.
- **F3**: `.claude/rules/api-layer.md` documents `/display-mesh` and
  `/boolean-regions` endpoints that do not exist in `main.py`.
- **F4**: `networkx==3.3` is pinned for "Hou 2018 parting line" but never imported.
- `EdgeData.convexity` exists as a field and is never populated by any module.

**Decisions:**
- Phase 4 (AI agent) is sequenced **last**, deliberately. An LLM narrating incorrect
  geometry launders a bug into an authoritative-sounding engineering recommendation.
- Agent layer is **provider-agnostic with Gemini as the default** (cost and testing
  ease), Anthropic and OpenAI as swappable adapters. Supersedes
  `agent.model: "gpt-4o-mini"` in `config.yaml`. Tool schemas are authored to
  Gemini's JSON Schema subset — the most restrictive of the three.
- Frontend migration follows a strangler-fig pattern: Streamlit stays runnable
  through milestone 2.6 so the demo always has a working fallback.

**Why:**
Establishing one execution-ordered plan across geometry, frontend, testing, and the
agent layer, with explicit validation gates so no capability gets claimed before it
is demonstrated.

---

### 2026-07-26 — Claude Code Setup

**What changed:**
- Created root `CLAUDE.md` (~110 lines) with project identity, architecture, run commands, invariants, and honesty rules.
- Created `.claude/settings.json` with safe permissions (allow test/git/docker commands, deny STEP file edits and pip pythonocc).
- Created `.claude/settings.local.json` for per-developer overrides (gitignored).
- Created 6 path-scoped rules in `.claude/rules/`:
  - `geometry-engine.md` — PartGeometry patterns, mutate flag, Boolean pruning
  - `api-layer.md` — endpoint list, stateless design, structured errors
  - `frontend.md` — no OCC imports, session state, PyVista rendering
  - `testing.md` — layered test order, OCC mocking, threshold sources
  - `config-and-infra.md` — Docker, conda, config.yaml structure
  - `honesty-and-scope.md` — authority table, claims to avoid (always loaded)
- Created 6 on-demand skills in `.claude/skills/`:
  - `dfm-domain-knowledge` — injection molding domain concepts
  - `occ-pythonocc-reference` — OCC class glossary and patterns
  - `research-paper-fidelity` — exact gap mapping vs. 4 papers
  - `pipeline-data-flow` — field-level data flow across modules
  - `evidence-and-validation` — validation harness usage
  - `run-dfm-stack` — Docker/conda recipes
- Created 4 commands in `.claude/commands/`: test, debug, audit, status-check.
- Created 2 memory files: `decisions.md` (architecture log), `known-gaps.md` (what's missing).
- Created 3 project tracking files: `STATUS.md`, `CHANGELOG.md`, `TODO.md`.
- Updated `.gitignore` to include `.claude/settings.local.json`.

**Why:**
Setting up Claude Code for optimal context management. Rules are path-scoped so they only load when relevant. Skills are on-demand so CLAUDE.md stays under 200 lines. Tracking files keep the team aligned across sessions.

---

### Pre-2026-07-26 — Existing Codebase

Full Level 1 geometry pipeline built:
- STEP loader, draft analyzer, undercut detector, direction optimizer (all fully implemented)
- Parting line (foundation), core/cavity (face classification only)
- FastAPI backend, Streamlit frontend, validation harnesses
- Docker setup, conda environment, config system
- ~20,800 lines of Python across the project
- AI agent layer and PDF export remain unstarted
