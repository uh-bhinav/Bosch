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

# Phase 5D-1 — Bilateral accessibility-risk candidate generation: cavity-side faces (`n·d > 0`) with a concave bounding edge now also enter the Boolean-refinement candidate pool, closing a proven asymmetry without touching Boolean confirmation, proxy-undercut, scoring, or `parting_line_v2` semantics

**Documentation debt, noted not hidden.** D-051 through D-055 (Phase
5C-1 through 5C-3 and Phase 4's `topological_side`) are implemented,
tested, and already referenced by name throughout
`direction_optimizer.py` and `parting_line_v2/{types,regions}.py`, but
their own decision-log entries were never appended to this file. Not
backfilled here (out of this phase's scope, and re-deriving five
entries' exact historical measurements from code alone risks getting
the numbers wrong) — tracked as a `TODO.md` documentation-debt item
instead of silently left unmentioned.

## D-056 — Accessibility-risk candidate generation is now bilateral (core-side AND cavity-side), reusing the identical concave-edge requirement and threshold on both sides ⭐⭐⭐⭐

**[2026-08-16] Implemented — `backend/geometry/undercut_detector.py`
only.** No change to Boolean confirmation semantics, proxy-undercut
semantics, severity/depth/interference calculations, evidence tiers,
the comparator, `parting_line_v2`, or any threshold value. No new
fixture-specific or Part-specific conditions added anywhere.

**Root cause (Phase 5 re-audit).** `_compute_accessibility_risk` only
ever tested faces with `n·d <= -threshold` (core-side). Mathematical
justification for the original restriction: for a face `F` with outward
normal `n` and pull direction `d`, if `n·d > 0`, sweeping `F` along `+d`
initially moves *away* from `F`'s own adjacent material (a basic
differential-geometry property of an outward normal on a manifold
boundary) — so `F`'s own local sweep cannot find LOCAL self-interference
this way, only interference with DISTANT material further along the
sweep path. This proves core-side-only candidate generation was not an
arbitrary shortcut. It does NOT prove cavity-side faces are risk-free:
a cavity-side face's sweep can still hit genuine, distant material
(e.g. a plate-top face swept upward into a small boss/cap sitting above
it) — a real, provable gap, motivating this fix.

**Fix.** `_compute_accessibility_risk(..., side: str = "core")`. New
keyword-only parameter, default `"core"` preserves byte-identical
behaviour for any caller that does not pass it.
```python
directional = signed if side == "cavity" else -signed
if directional <= threshold:
    continue
```
Algebraically equivalent to the original `if signed >= -threshold:
continue` when `side="core"`. Condition 2 (concave bounding-edge
requirement) is completely unchanged, reused identically for both
sides — a cavity-side face is flagged only under the exact same
evidence standard already applied on the core side, never a weaker one.
`detect_undercuts` now calls this twice (`side="core"`, `side="cavity"`)
and unions the two face-ID sets and area totals; the existing
`check_ids = sorted(set(proxy_undercut_ids) | set(risk_face_ids))`
union-with-Boolean-confirmation code path is untouched — cavity-side
candidates flow through the identical, pre-existing Boolean-refinement
mechanism as core-side candidates always have.

**Fixture — found, not built.** The required hand-verified cavity-side
ground truth already existed inside `UC3_spool_true_undercut.stp`
(16 faces, hand-verified in Phase 5A) as face 10 — the exact mirror of
face 4's already-proven 6400 mm³ core-side shelf. Face 10: area
800 mm² (900 − 100 mm² stem footprint), normal `(0,0,1)`, `g=+1.0`
(cavity-side), bounding edges 17/23/21/19 all `"concave"`. Hand
computation: the 800 mm² annulus swept `+Z` passes through the empty
gap beside the stem (z 8→22) then intersects the cap's full 30×30
footprint over its 8 mm thickness: `800 × 8 = 6400 mm³` — independently
re-measured this session via `_swept_face_interference_volume` and
matching to the hand value (`rel=1e-6`). This fixture was not
constructed for this fix — a pre-existing code comment in
`test_undercut_detector_accessibility_union.py` (Phase 5A follow-up,
predating this phase) had already identified this exact asymmetry as
"newly discovered, not fixed in this correction," which is independent
evidence this is a real, previously-known gap rather than a fixture
tuned to pass.

**Tests.**
`tests/test_undercut_detector.py::TestAccessibilityRisk` — 3 new tests
(cavity-side-with-concave-edge flagged, cavity-side-all-convex not
flagged, core+cavity risk faces both detected simultaneously with
correct area sum). 10/10 in the class, 73/73 combined with
`test_undercut_detector_semantics.py`.
`tests/test_undercut_detector_accessibility_union.py` — `test_C`'s
stale "not reachable via default path" assertion removed; new `test_C2`
proves face 10 is now reachable through the exact
`direction_optimizer.py`-matching default call
(`boolean_check_all_faces=False`), confirmed, with both faces'
6400 mm³ independently re-verified; new `test_C3` is the negative
control (UC3 face 2, cavity-side, all-convex edges, never flagged).
10/10 passed.
Full regression: `test_undercut_detector.py` + `_semantics.py` +
`_accessibility_union.py` = 83/83. `test_direction_optimizer.py` +
`test_direction_optimizer_feature_acceptability.py` = 51/51 (one test,
`test_uc4_real_fixture_no_longer_verified_acceptable`, needed its
sanity-check assertion updated — see "UC4 side effect" below; not a
regression). `test_direction_optimizer_evidence_tiers.py` (real Part1/
Part3/Dhukkan/UC3 geometry) run in full; see CHANGELOG.md for the
pass/fail count recorded at completion.

**Part1 — required to stay explained, not cosmetically forced.**
Fresh measurement, both principal directions along the part's own
symmetry axis: `boolean_confirmed_face_ids` is still `[]` at both `+Z`
and `-Z`, unchanged from the pre-fix baseline. The bilateral fix does
add new *candidates* that were never Boolean-tested before this fix
(e.g. faces 28/46 at `+Z`, `g=+1.0`, cavity-side, concave edge) — the
candidate pool measurably grew (`candidate_unconfirmed_face_ids` now
includes faces that were previously never checked) — but every one of
them, without exception, Boolean-tests to zero interference. This is
the expected, honest outcome for a part with no real cavity-side
undercuts along that axis: more geometry is now being checked, and the
answer is still "clean," for the correct reason (no material found),
not because nothing new was tested.

**UC4 side effect (not a bug, flagged not hidden).**
`UC4_small_deep_pocket_on_large_plate.stp` reuses UC3's exact
stem/cap geometry atop a much larger diluting plate. Its own plate-top
face (39,900 mm², `g=+1.0`, concave annulus around the stem gap) is the
same kind of genuine cavity-side mirror as UC3's face 10, and is now
also correctly Boolean-confirmed (`interference_volume_mm3` doubles
from 6400 to 12800, matching a second independently hand-verifiable
800 mm²×8 mm=6400 mm³ overlap with the cap). Because
`confirmed_undercut_pct` attributes a face's *entire* area to
"confirmed" once any interference is found on it — a pre-existing,
unchanged whole-face-granularity trait of that metric, explicitly out
of this phase's scope to alter (severity/depth/interference
calculations were required to stay untouched) — UC4's confirmed area
jumps from ~0.89% to ~45.46%, well past the 10% suitability threshold.
This means UC4 no longer demonstrates the original Phase 5C-3
"small-area-but-critical" failure mode on its own area metric; it still
correctly demonstrates that a confirmed critical feature blocks
`verified_acceptable`, now via both the area rule and
`feature_acceptability` independently. `test_uc4_real_fixture_no_longer_verified_acceptable`'s
docstring and stale `< 10%` sanity-check assertion were updated to
describe this; no fixture geometry, threshold, or production code was
changed to "fix" this number.

**False positives.** None found. Every cavity-side face flagged in this
session's regression genuinely satisfies the concave-edge evidence
requirement, and every Boolean-confirmed cavity-side face
(UC3 face 10, UC4's plate-top face) has an independently hand-computed,
matching swept-volume value. The negative controls
(`test_C3`/`test_cavity_side_all_convex_edges_not_accessibility_risk`,
UC3 face 2, Part1's clean-along-axis result) all held.

**Runtime impact.** `_compute_accessibility_risk` is now called twice
per direction instead of once (same per-face cost, same concave-edge
precomputation reused from `step_loader`); the candidate pool handed to
Boolean refinement grows on parts with concave cavity-side topology
(Part1: from ~26 core-side candidates to 68 total candidates at each of
`+Z`/`-Z`), proportionally increasing Boolean-refinement wall time on
those directions. Not separately profiled this session beyond the
regression suite's own run times (see CHANGELOG.md).

**Remaining detector gap.** The whole-face-area-counts-as-confirmed
granularity issue surfaced by the UC4 side effect above is real and
pre-existing (not introduced by D-056), and now more visible because
bilateral candidate generation makes it more likely that a large,
mostly-clear face with one small genuine pocket gets Boolean-confirmed.
Not fixed here — flagged for a future phase, since fixing it would mean
changing interference/area accounting, explicitly out of 5D-1's scope.

**Where.** `backend/geometry/undercut_detector.py:_compute_accessibility_risk`
(~line 3190-3260), call site in `detect_undercuts` (~line 3405-3425).

---

# Phase 5D-2 — Bosch Part1 reference-image forensic comparison (D-057) and `confirmed_undercut_pct` metric audit (D-058)

## D-057 — Direct 3-D rendering comparison shows the Bosch reference image does NOT depict Part1.stp; no face-level mapping is claimed ⭐⭐⭐⭐

**[2026-08-16] Read-only investigation, no code changed.** The user
provided the actual Bosch "Undercuts" reference image for the first
time this session (previously absent from the repo — D-042 explicitly
withheld any alignment claim pending this). Rendered `Part1.stp` via
`pyvista` off-screen rendering (`build_raw_mesh`/`to_pyvista`, reusing
`visualize_raw.py` unmodified) from 5 angles (isometric ×3, top-down
orthographic, bottom-up orthographic/perspective) for direct visual
comparison — the first time this investigation has had actual rendered
Part1 geometry to compare against the reference, rather than relying on
field-level inference alone.

**Finding.** Part1.stp is a radially 4-fold-symmetric snap-fit cap:
closed top face bearing a raised/engraved logo medallion, 4 identical
rim scallop-slots at the top edge midpoints (90° apart), and 4 identical
tall cantilever legs on the underside arranged around a central stepped
cylindrical boss, each leg separated from its neighbors by a straight
vertical slot. The Bosch reference image shows two objects, each a
single rectangular box, hollow-shell (cyan interior clearly visible
through one open face), with exactly ONE side-wall slot and ONE
flat cantilever blade/rib passing through ONE bottom slot — no rim
logo, no 4-fold symmetry, no closed top. These are two different part
designs: different symmetry order (4-fold vs. none), different feature
count (4 legs vs. 1 blade; 4 slots vs. 1-2), different topology (Part1
has a closed top; the Bosch parts are open-shell). **Direct visual
comparison, not inference, is the basis for this finding** — screenshots
retained in session scratch (`part1_view1/2.png`, `part1_bottom1.png`,
`part1_top_ortho.png`).

**Consequence.** No face-ID-level (or even feature-level) mapping from
the Bosch image's red dot/line markers to any `Part1.stp` face is
possible, honest, or attempted. Per explicit instruction, none was
invented. The Bosch image is almost certainly a generic illustrative
"what an undercut looks like" training graphic (consistent with its
plain "Undercuts" caption, no part number, no dimensions, no source
attribution), not a rendered analysis of this project's Part1 fixture.
This does not mean the image is useless — see the type-level discussion
in the full 5D-2 report (delivered in-session, not duplicated here) —
but it forecloses any claim of Bosch alignment, "false positive," or
"false negative" being validated against Part1 specifically, and this
finding supersedes any future attempt to tune detector behavior toward
reproducing this image's marker pattern on Part1.

**Where.** No code touched. Rendering script:
session scratch only (not committed — reproducible from
`backend/geometry/visualize_raw.py` + `pyvista`, both already in the
repo/environment).

## D-058 — `confirmed_undercut_pct` measures whole-face area attributed to any confirmed interference, not actual interfering footprint; not face-tessellation-invariant; recommendation is EXTEND, not fixed this phase ⭐⭐⭐

**[2026-08-16] Read-only investigation, no code changed.** Traced
`_confirmed_undercut_pct` (`direction_optimizer.py:1128-1146`) exactly:
`100 * sum(part.get_face(fid).area for fid in boolean_confirmed_face_ids)
/ max(total_analysed_area_mm2, 1.0)`, where `total_analysed_area_mm2` is
the sum of every face's full area on the whole part (`undercut_detector.py:3345-3351`,
`total_area += face.area` for every `normal_valid` face, unconditionally).

**What it actually measures.** Option A of the three posed alternatives:
"total face area containing any confirmed interference," as a fraction
of whole-part surface area — NOT "actual physically interfering area"
(would require the overlap footprint, not the whole confirmed face's
area) and NOT any volumetric measure.

**Structural defect, not just an edge case.** Because the unit of area
measurement is "whichever polygon the CAD author's face boundary happens
to be," the metric is **not invariant to how a surface was tessellated
into faces at authoring/export time.** Two STEP files representing the
physically identical undercut, differing only in whether a large planar
region was authored as one face or split into several, would report
different `confirmed_undercut_pct` values for identical real geometry.
D-056's own regression exposed a live instance: UC4's plate-top face
(39,900 mm², one B-Rep face) has a genuine, hand-verified 6400 mm³/
800 mm² overlap with the cap above it — identical in magnitude to UC3's
own already-accepted face 10 — yet counts its **entire** 39,900 mm² as
"confirmed," pushing `confirmed_undercut_pct` from ~0.89% to ~45.46%
for the same physical interference UC3 reports as ~13.6%.

**Where it currently matters.** `_is_direction_suitable_boolean`'s own
threshold check on this value is confirmed **inert** (D-053's own
comment: return value discarded by its only caller,
`_evidence_tier`/`_feature_acceptability` are the actual acceptance
gate since D-053/D-054) — so the binary accept/reject decision is
already safe from this defect. It is NOT inert in scoring:
`direction_optimizer.py:723-725`,
`cfg.scoring_confirmed_undercut * confirmed_undercut_pct` feeds the
continuous score, which is the second key in D-052's comparator
(`(tier_rank, score, accessibility_risk_area_pct, ...)`) — i.e. it can
still swing tie-breaking and relative ranking *within* a tier, purely as
a function of face-tessellation granularity rather than real
interference magnitude.

**Recommendation: EXTEND, not KEEP-as-is, not REDESIGN.** Do not remove
or replace `confirmed_undercut_pct` — it is cheap (no new geometry ops),
existing thresholds/tests are calibrated against it, and in the common
case observed so far (UC3, Part1's currently-empty confirmed set) it is
not pathological. The defect is real but narrow: it only misleads when
a single confirmed face's own area is large relative to its actual
overlap. Recommended future direction (NOT implemented this phase,
consistent with an additive pattern already used successfully in this
project — D-055's `topological_side` alongside `label`): add a second,
complementary metric representing genuine interfering footprint or
volume fraction, expose both, and let callers (scoring, evidence tier)
choose the meaningful one per their own semantics — never overload the
existing field's meaning.

**Where.** `backend/geometry/direction_optimizer.py:1128-1146` (`_confirmed_undercut_pct`),
`:723-725` (scoring use), `backend/geometry/undercut_detector.py:3345-3351`
(`total_area` accumulation). No code changed.

---

# Phase 6 — Original pull-direction-timeout/false-positive handoff reconciliation + Part1/Part3 convergence audit (D-059)

## D-059 — The pre-R1-R5 handoff's core diagnosis (candidate-pool bloat, T1) is stale and no longer reproduces; the CURRENT Part1 bottleneck is per-direction Boolean-retry cost variance across 18 mandatorily-refined directions, measured at 1775s; the evidence-driven winner is a diagonal, not +Z ⭐⭐⭐⭐⭐

**[2026-08-16] Read-only audit, no code changed.** Reconciled an older
handoff document (`docs/handoff/text-11E3934B4476-1.txt`, pre-dating
D-042/D-046 by its own field-name vocabulary — `parting_ids` as the
sole classification, `boolean_validation_complete`,
`boolean_check_all_core_side`, a green `no_interference` render style —
none of which exist in current code) against the actual current
codebase and live measurement.

**Reconciliation summary.** Of the handoff's 3 core fixes: Fix D
(exclude `|n·d|≤0.01` faces from the candidate pool) was **not
implemented as proposed** — superseded by D-046's narrower, earlier,
already-in-place `boolean_near_zero_g_threshold=1e-6` guard applied at
the point of the sweep (not at candidate-generation) plus the
independently-existing convexity-suppression pass, which together
already cut Part1 +Z's raw 78-face proxy set to 26 before Boolean
testing. Fix B+C/tertiary (remove the 150-face expanded final-pass
validation and `boolean_check_all_core_side`) is **already absent from
current code** — every `_cached_detect_boolean_undercuts` call site now
uses the same `cfg.boolean_refine_max_faces=80` uniformly (verified: 5
call sites, all identical), `final_direction_max_boolean_faces` does not
exist in `config.yaml`/`config.py`. Fix E (rename a green
`no_interference` render style) is **moot** — that style, and the whole
`boolean_no_interference_face_ids`/`boolean_failed_face_ids`-as-primary
data model it referenced, no longer exists; the current three-bucket
contract (D-046) and visual style table have no green category at all.
The proposed instrumentation (`logging.info` calls, `_dump_face_diagnostic()`,
`boolean_volume_by_face` field) and the `test_undercut_semantic_contract.py`
test file were **never implemented** under those names.

**Live measurement, current code, Part1 +Z (this session).**
`check_ids` (proxy ∪ bilateral risk, post-convexity-suppression) = 68
faces — NOT the handoff's claimed ~230. `boolean_refine_max_faces=80`
budget is never hit; **zero candidates are truncated**. 4 faces
(207/215/222/230, the same BSpline leg-transition faces identified in
D-057's Bosch comparison) genuinely **fail** Boolean refinement (an OCC
op failure, not a false confirmation) → routed to `manual-review`,
never `boolean_confirmed`. `boolean_confirmed_face_ids=[]`. **The
handoff's T1 (candidate-pool bloat) and U1 (perpendicular-dot false
positives) do not reproduce on current code and current Part1
geometry** — both were evidently already resolved by work done earlier
in this project (D-042/D-046/convexity-suppression), independent of
and prior to this specific handoff's own proposed fixes.

**Live measurement, `optimize_mold_direction(Part1.stp)`, full run,
this session.** `ELAPSED=1775.1s` (~29.6 min) — worse than both the
handoff's own ">240s" trigger and its "<30s" target, and worse than the
user-cited ~1196s. `search_stage_reached=2`, `direction_cache_misses=18`
(all 18 of Stage 1's 6 principals + Stage 2's 12 diagonals genuinely
Boolean-refined, per D-048's unconditional-refinement policy — matches
design, not a bug), `boolean_survivor_candidate_count=17` (barely any
Stage-3 pruning benefit since almost every Stage 1+2 candidate is
already Boolean-refined by design). Root cause of the 1775s is **not**
pool truncation (ruled out directly above) but per-direction OCC
Boolean-retry cost variance across those 18 mandatory refinements — the
same "144s-1122s run-to-run variance, consistent with but not
independently root-caused as OCC's own Boolean-retry brittleness"
already flagged, unresolved, in D-048's own entry. This session's 1775s
is a new, worse data point for that same still-open, still-unsolved
performance question — not a new phenomenon.

**The winner is NOT +Z.** `best_direction=(-0.707, 0.000, +0.707)`
(a 45° diagonal), `optimal_found=True`, `evidence_tier=verified_acceptable`,
`confirmed_undercut_pct=0.0`, `feature_acceptability=clean`. Direct
comparison: +Z itself has the 4 Boolean-FAILED BSpline faces above
(not clean), while the winning diagonal has zero. **This is the
evidence-driven system doing its job correctly, not malfunctioning** —
forcibly converging Part1 to +Z (as both the original handoff's AC1 and
a later request's stated target both assumed) would mean preferring a
direction the detector's own honest evidence rates lower, purely to
match an a priori assumption neither handoff independently re-verified
against current evidence. Flagged as the single most important finding
of this audit, not a task to silently execute.

**Full detail:** delivered in-session as the combined "Handoff
Reconciliation + Convergence Audit" report (2026-08-16). Not duplicated
here in full; this entry preserves the decisive measured facts.

---

# Phase 4 — Core/cavity gray-face reporting gap (D-049) and ambiguous-face classification forensic audit (D-050)

## D-050 — Ambiguous-face classification forensic audit: no cancellation defect demonstrated on either real part; `mean_g`-only semantics kept unchanged ⭐⭐⭐

**[2026-08-16] Read-only investigation, no code changed.**
`backend/geometry/parting_line_v2/regions.py`'s `classify_regions()` labels
a face `"ambiguous"` iff `abs(mean_g) <= silhouette_epsilon` and it does not
touch the parting loop. The theoretical concern audited: could a genuinely
curved/saddle face have `min_g` substantially negative and `max_g`
substantially positive (real draft in both directions) while `mean_g`
happens to average out near zero, causing a real cavity/core-determinate
face to be mislabeled ambiguous by an averaging artifact?

**Method.** Direct instrumentation of the already-computed
`FaceClassification.mean_g/min_g/max_g/sample_count` (11x11 UV sampling,
unmodified) for every `"ambiguous"`-labeled face on Part1 (+Z, no
authorization, selected candidate 49) and Part3 candidate 110
(authorized), cross-referenced with `part.faces[...].surface_type`,
`part.face_adjacency` (loop-adjacency), and H3 component membership.

**Finding.** Zero faces on either part show a real straddle: the maximum
`max_g - min_g` spread across the ENTIRE ambiguous population is
`4.56e-15` (Part1) and `1.41e-16` (Part3 candidate 110) — 13-14 orders of
magnitude below `silhouette_epsilon=0.02`, i.e. IEEE-754 floating-point
noise, not a geometric signal. `g` is zero to float precision at every one
of 121 sampled points on every ambiguous face on both parts — genuine
zero-draft geometry (planar ribs/walls parallel to the pull axis, bores/
bosses coaxial with it), not curvature cancellation. `RegionClassification.
inconsistent_face_ids` (the pipeline's own pre-existing straddle detector,
applied to ALL cavity/core-labeled faces, not just ambiguous ones) is
empty on both parts — the failure mode does not manifest anywhere in
either model, not only within the currently-ambiguous population.

**Decision.** Classification semantics (`abs(mean_g) <= silhouette_epsilon`)
are kept UNCHANGED. No min/max-based criterion, no new threshold, no
CASE-B/C special-casing implemented — there is no measured defect to fix,
and building one against fixtures that cannot confirm or falsify it would
be exactly the "tune to desired output" failure this audit was
commissioned to avoid.

**Residual, honestly flagged, NOT a current defect.** A future part with a
genuinely doubly-curved/saddle zero-draft-band face (meaningfully negative
AND positive sampled `g` averaging near zero) is not demonstrated to exist
on Part1 or Part3, but is not ruled out by this audit either — the
`min_g`/`max_g` data needed to detect it is already captured in
`FaceClassification` and needs no schema change if such a face is ever
observed. Logged in `.claude/memory/known-gaps.md` under "Unproven
Observations."

**Where.** No file changed. Evidence: this session's forensic run against
`backend/geometry/parting_line_v2/regions.py::classify_regions` +
`FaceClassification` (unmodified), real `Part1.stp`/`Part3.stp`.

---

## D-049 — Best-rejected H3-passing candidate's already-computed `RegionClassification` now exposed via explicit, separate top-level fields; `regions` continues to mean only "the accepted split" ⭐⭐⭐

**[2026-08-16] Implemented — `backend/geometry/parting_line_v2/engine.py`
(new fields only) and `frontend/app.py` (new opt-in preview + corrected
stale caption). No change to `separate_surface()`, `classify_regions()`,
H0-H7, `ranking.py`, the pull-direction optimizer, undercut detection,
core-pin semantics, or delegation semantics.**

**Root cause (Phase 4 forensic audit).** When no candidate passes every
gate (`selected=None`, e.g. Part3 at `+Z` with no manual core-pin/
delegation authorization: 159/310 candidates fail H3, 151/310 fail H4),
`PartingLineV2Result.regions` was hard-wired to `regions_by_candidate.get
(selected.candidate_id) if selected else None` — always `None` in this
case. Every face then rendered flat neutral gray in the frontend with zero
explanation, DESPITE Phase 3A already retaining a full, real
`RegionClassification` for the best-ranked rejected H3-passing candidate
in `regions_by_candidate` (and even attaching it to that candidate's own
object in the scorecard) — the data existed and was silently discarded
before reaching the API/frontend. Not a classification-algorithm defect;
an information-exposure gap.

**Fix.** Reused the pre-existing, deterministic `best_rejected_id`
selection (lowest `h4_orientation_violation_fraction` among non-selected,
H3-passing candidates — unchanged, not re-invented) and exposed it through
four new, explicitly separate `PartingLineV2Result` fields:
`best_rejected_candidate_id`, `best_rejected_regions`,
`best_rejected_failed_gate`, `best_rejected_reason`. `regions` itself is
untouched and never overloaded. Frontend: corrected a now-false caption
("region classification is only computed for the passing candidate") and
added an opt-in (default-off), separately-rendered viewport preview
banner-labeled "BEST REJECTED CANDIDATE {id} — PREVIEW ONLY" with the
concrete gate/reason, explicitly stating it is not feasible, not a valid
parting line, and not a final core/cavity split.

**Verified.** Part3 `+Z` no-auth: `regions=None` (unchanged), 
`best_rejected_candidate_id=218` (lowest-violation H3-passing rejection,
7.2% H4 violation — not hardcoded to candidate 110), `best_rejected_
regions` populated (316 cavity / 3 core / 95 ambiguous faces). Part3
candidate 110 (authorized): frozen Phase 3A values byte-identical
(`cavity_face_ids` len 410, `core_face_ids=={35,36,37,320,321}`,
`ambiguous_area_fraction==0.3271748971395147`, face-35 split areas
1302.33/130.23 mm²). Part1 `+Z`: unchanged (`selected.candidate_id==49`,
area fractions unchanged). `rejection_summary` gate counts on Part3
no-auth (`{"H3": 159, "H4": 151}`) confirm H0-H7 evaluation itself
untouched.

**Tests.** `tests/test_parting_line_v2_best_rejected.py` (new, 9 tests,
all 8 items requested by the implementing instruction). Full regression:
13 Phase 3A region-balance + 12 core-pin + 17 delegation + 34 API/Level-1
= 85/85 passed, 0 regressions.

---

# Phase 5B — Pull-direction optimizer: tiered evidence-based selection replaces raw-score sorting across candidates with fundamentally different verification status

## D-048 — All 6 principal axes and 12 configured diagonals are now always Boolean-refined regardless of the cheap bad_pct/accessibility_risk_pct screen; final selection is evidence-tier-first, score-second; the optimizer can now honestly report "no verified optimum" instead of silently returning an unverified best-scoring candidate ⭐⭐⭐⭐

**[2026-08-16] Implemented — `backend/geometry/direction_optimizer.py`
only. No change to `_compute_accessibility_risk`, the undercut detector,
H0-H7, `parting_line_v2`, core-pin/delegation, or the frontend.**

**Root cause (Phase 5B audit).** `_is_direction_suitable_cheap` (bad_pct
<=30%, accessibility_risk_pct<=15%) gated WHETHER a Stage 1/2 candidate
was ever Boolean-refined at all. Measured live: every one of Part1's 6
principal axes fails this gate (bad_pct 43-72%), so none were ever
Boolean-verified by the optimizer's own search, before or after D-046/
D-047 — those detector fixes, however correct, were structurally
unreachable for the directions with the strongest manufacturing
precedent. Separately, the final selection (`scored.sort(key=score);
best=scored[0]`) mixed candidates verified by different formulas (cheap
vs. Boolean-refined) and candidates never verified at all in one raw sort,
letting an unverified candidate's lower numeric score silently outrank a
verified one's.

**Fix.**
1. Stage 1+2 (6 principal + 12 configured diagonals) are now ALWAYS
   Boolean-refined, unconditionally. The cheap screen is no longer a
   pre-Boolean gate for these — it remains exactly as before for the
   Stage-3 spherical grid, where verifying every point really would be
   too expensive (`_select_boolean_refinement_candidates`, untouched).
2. Every `DirectionCandidateResult` now carries an explicit
   `evidence_tier` (`"verified_acceptable"` | `"verified_undercuts_present"`
   | `"unverified"`) and `confirmed_undercut_pct` (0.0 when unverified —
   never confused with "confirmed clean").
3. Final selection (`_tiered_best`) compares tier first, score second —
   an unverified candidate's score is never compared against a verified
   one's.
4. `DirectionOptimizationResult` gains `optimal_found` (True only when
   the winner's own tier is `"verified_acceptable"`), `best_evidence_tier`,
   `best_unverified_candidate` (populated, separately labeled, when
   `optimal_found=False`), and a permanent `residual_detector_limitation_note`
   documenting D-047's own known core-side-only gap — `evidence_tier=
   "verified_acceptable"` means no undercut was found BY THIS METHOD, not
   that none exists.
5. `best_direction`/`best_score`/`best_label` remain always-populated
   `Vec3`/`float`/`str` (backward compatible with every existing caller —
   `direction_optimizer.py`'s own agent-tool and v1 core-cavity consumers,
   verified unchanged) even when `optimal_found=False`, so no existing
   caller breaks; the new fields are the only way to detect the
   unvalidated case.

**Measured result, real parts, all 6 principal directions (this session,
post-implementation).** Part3: all 6 principal axes now boolean_refined
(previously only `+X`/`-X` were ever checked) — `+X`, `+Y`, `-Y`, `+Z`,
`-Z` all `"verified_acceptable"` (0% confirmed); `-X` also technically
acceptable at 9.8% confirmed (just under the 10% threshold) but loses on
score to `+X`'s cleaner result — winner unchanged from pre-Phase-5B
(`+X`), now for the right, fully-verified reason instead of an unverified
default. Dhukkan: `+X` correctly demoted to `"verified_undercuts_present"`
(10.8% confirmed, over threshold); winner unchanged (`+Z`), now
tier-justified. **UC3 (hand-verified ground truth) — the clean proof of
correctness**: `+Z`/`-Z` (the fixture's real, hand-computed 6400 mm³
undercut axis) are correctly `"verified_undercuts_present"` (13.6%
confirmed, rejected); `+X`/`-X`/`+Y`/`-Y` (verified clean by
construction) are all `"verified_acceptable"` (0% confirmed) — the
optimizer now separates true-bad from true-good axes on this fixture
using real Boolean evidence for BOTH conclusions, not heuristics. Part1:
all 6 principal axes now boolean_refined=True (confirmed directly,
matching the audit's own prediction); the overall search now reaches
`optimal_found=True` at Stage 2 (a validated diagonal) — the first time
in this entire investigation that Part1 has produced a genuinely
Boolean-verified, acceptable answer rather than relying on unverified or
degenerate-volume evidence.

**Performance note, not silently absorbed.** Always-Boolean-refining all
18 Stage 1+2 candidates measurably increases Part1's runtime, and its
observed cost varied substantially run-to-run in this session (144s to
1122s for otherwise-identical calls) — consistent with OCC's own
documented Boolean-retry brittleness (`boolean_retry_offset_multipliers`)
rather than a bug in this change, but not independently root-caused
further this session. Flagged as a real, unresolved performance-variance
observation for a future phase, not swept under the rug.

**Tests.** `tests/test_direction_optimizer.py`: 2 pre-existing tests
updated (`search_stage_reached==3` no longer means "search exhausted" —
Phase 5B redefined it to mean "which candidate pool the winner came
from"; both updated to assert the new, more precise `optimal_found`/
`best_evidence_tier` honesty fields instead, which is what they were
actually trying to test). `tests/test_direction_optimizer_evidence_tiers.py`
(new): tier-comparator correctness (deterministic, mock-based), Part1/
UC3 principal-axis Boolean-refinement characterization, no-acceptable-
candidate honesty (mock-based), Stage-3 triage-still-prunes (forced via
an unsatisfiable-threshold override, since UC3 now legitimately exits
early at Stage 2 — itself a positive side-effect of this fix), Part3/
Dhukkan/Part1 explainability and mirror-symmetry checks against live
real-part data. Full existing mock-based regression
(`test_direction_optimizer.py`): 28 passed, 0 failed.

**Full detail:** see the Phase 5B implementation deliverable report
(2026-08-16 session) for the complete before/after tables and the
answer to "can the optimizer now legitimately claim meaningful undercut
evidence".

---

# Phase 5A follow-up — Boolean candidate selection was draft-proxy-only, silently missing wrong-sign shelf undercuts; now the union of draft-proxy and accessibility-risk candidates

## D-047 — `check_ids` for Boolean verification is now `proxy_undercut_ids ∪ accessibility_risk_face_ids`; a face with excellent draft magnitude but the wrong sign relative to its local topology (e.g. a shelf underside) can now reach confirmation ⭐⭐⭐⭐

**[2026-08-16] Implemented — `undercut_detector.py` only. No change to
`direction_optimizer.py`, `_compute_accessibility_risk`,
`_face_access_direction`, `draft_angle_deg`, H0-H7, `parting_line_v2`,
core-pin/delegation, or the frontend.**

**Root cause.** `draft_angle_deg = asin(|g|)` is correctly sign-blind (it
answers a scuffing question, not a trapping question). The proxy pass
(`proxy_undercut_ids`) gates on this sign-blind angle, so a face with
`g=-1` (excellent draft magnitude, wrong sign — a classic shelf
underside) has `draft_angle_deg=90°` and is never a proxy candidate. Under
default settings (`boolean_check_all_faces=False`, which is exactly what
`direction_optimizer.py:408` hardcodes), such a face was never Boolean-
verified at all — invisible, not merely unconfirmed. `_compute_
accessibility_risk` (core-side `g<-threshold` AND >=1 concave bounding
edge) already existed, already correctly distinguished this class of face
from an ordinary negative-g face with no real risk, and was already
independently tested — but was never wired into Boolean candidate
selection, only used as a `direction_optimizer.py` scoring term.

**Fix.** `check_ids = proxy_undercut_ids ∪ accessibility_risk_face_ids`
when `boolean_check_all_faces=False`. Both candidate-generation passes
are unchanged; only which of their outputs feed the (unchanged) Boolean
verification step.

**Hand-verified proof, `UC3_spool_true_undercut.stp`** (built in Phase
5A): face 4 (genuine trapped shelf, `g=-1`) was previously invisible to
the default path; now confirmed at exactly `6400 mm³`, sourced purely via
`accessibility_risk` (`candidate_sources[4] == ["accessibility_risk"]`).
Face 15 (`g=-1`, same magnitude, no concave boundary, genuinely NOT an
undercut) remains correctly absent from every bucket — proving the fix
does not classify every negative-g face as an undercut. Face 10
(`g=+1` at `+Z`) is discoverable at `-Z` (where it becomes core-side) or
via `boolean_check_all_faces=True`, but **not** at `+Z` under the default
path — see "Newly discovered, not fixed" below.

**Provenance.** `UndercutDetectionResult.proxy_only_face_ids` (Phase 5A)
renamed to `candidate_unconfirmed_face_ids` (zero external consumers at
rename time, verified by repo-wide search) — "proxy only" became
misleading once a face can be a Boolean candidate without ever being a
draft-proxy candidate. New `candidate_sources: dict[int, list[str]]`
records, per processed face, `"draft_proxy"`, `"accessibility_risk"`, or
both, answering "why was this face sent to Boolean verification."

**Measured impact on real parts (Part1/Part3/Dhukkan, all 6 principal
directions) — the significant finding of this phase.** Part1 at `+Z`/`-Z`
remains 0 confirmed (40 and 2 additional accessibility-risk candidates
respectively, all Boolean-checked and correctly cleared — corroborating
Phase 5A's `boolean_check_all_faces=True` finding that Part1 has no local
undercut along the Z axis). But at **`+X`: 19 newly confirmed faces**
(previously entirely invisible), **`-X`: 12**, **`+Y`: 4** — all sourced
purely via `accessibility_risk`, none previously reachable. Spot-verified
non-degenerate: sampled faces carry meaningful `g` (−0.69 to −1.00, far
from the D-042 danger zone) and physically plausible interference
volumes (0.4-1433 mm³, no whole-part-volume signature). **Part1 was not
as undercut-free at off-axis directions as the pre-fix detector reported
— this was a real, previously-hidden false negative, not a synthetic
corner case.** Part3/Dhukkan: no new confirmations at any tested
direction — their accessibility-risk candidates (where any exist) all
checked out clean, a real result, not evidence the fix "doesn't work"
(cross-validated against the same non-degenerate-volume signature check).

**Newly discovered, not fixed in this phase.** `_compute_accessibility_
risk` only tests core-side (`signed < -threshold`) faces by design — a
cavity-side (positive-g) equivalent of a trapped shelf (UC3 face 10, at a
pull direction where it is NOT core-side) has no analogous
candidate-generation signal and remains reachable only via
`boolean_check_all_faces=True`. This is a narrower, direction-relative
gap (resolved for a given face once the pull direction makes it
core-side) rather than a universal blind spot, and is flagged for a
future phase rather than fixed here, per the explicitly bounded scope of
this correction.

**Tests.** `tests/test_undercut_detector_accessibility_union.py` (new, 8
tests, matrix A-I minus H): face 4 confirmed via the default path, face 15
never nominated, face 10 discoverable only via `boolean_check_all_faces`
(documenting the asymmetry above), provenance correctness (single- and
dual-source), near-zero-g guard composes correctly with the new candidate
source, three-bucket disjointness, and direct reproduction of
`direction_optimizer.py`'s exact call signature proving the fix is visible
through the unmodified consumer path. Full regression
(`test_undercut_detector.py` + both new semantic files +
`test_direction_optimizer.py` + `test_draft_analyzer.py` +
`test_parting_line_v2_contracts.py` + `test_step_loader.py`): 306 passed,
0 failed — zero pre-existing tests needed updating this time (unlike
Phase 5A's near-zero-g fix, this change only adds new confirmations, it
never removes an existing one that a mock fixture depended on).

**Full detail:** see the Phase 5A follow-up deliverable report
(2026-08-16 session) for the complete before/after table and the explicit
"is the detector trustworthy for Phase 5B" verdict.

---

# Phase 5A — Undercut detector: near-zero-g swept-volume degeneracy (D-042) fixed by exclusion, not repair; three-bucket evidence contract replaces the single flat undercut_face_ids set

## D-046 — `_swept_face_interference_volume` is mathematically well-posed only for faces with meaningfully non-zero g; faces tangent to the pull direction are now excluded from the sweep entirely (`boolean_not_applicable`) rather than fed to a test that cannot answer the question for them ⭐⭐⭐⭐

**[2026-08-16] Implemented — `undercut_detector.py`, `backend/config.py`,
`config.yaml`. No change to `direction_optimizer.py`, `parting_line_v2`,
H0-H7, or any candidate-generation/ranking code (explicitly out of scope
for this phase).**

**Root cause, proven not assumed.** `BRepPrimAPI_MakePrism` extrudes a face
along the access direction chosen by `_face_access_direction`
(`n.d>=0 -> +d`, `n.d<0 -> -d`). This is well-posed only when the sweep
direction has a meaningful component along the face's own normal. When
`g=n.d` is at or below floating-point noise (the sweep direction lies in
the face's own plane), the resulting "prism" is degenerate and its
intersection with the part collapses toward the part's own volume rather
than a local shadow. Isolated directly this session on a hand-built
synthetic fixture (`UC1_step_pyramid_tangent_walls.stp`, true volume 18560
mm^3 by construction): a face with `g=0.0` exactly reports `18560.000
mm^3` (the whole part); the identical face at `g=-1e-16` still reports
`18560.000`; at `g=-1e-14` it already reports the correct `0.0`. The
danger zone is the floating-point noise floor, not a "small g" region in
any practical sense.

**Threshold.** `cfg.boolean_near_zero_g_threshold = 1e-6`, mirroring
D-043's `core_pin_uniform_g_max` (also 1e-6, also "uniformly, genuinely
tangent to the pull direction") rather than inventing a new number.
Measured margin above the actual noise floor (~1e-16): 9+ orders of
magnitude — deliberately conservative, verified a face just outside the
tolerance (e.g. `g=1e-5`) still computes correctly and is not excluded.

**`_face_access_direction` itself needs no change.** It has exactly one
call site (inside `_swept_face_interference_volume`). Verified directly:
for a meaningfully-signed face (`g=+1` and `g=-1` tested), it correctly
returns `+pull`/`-pull` respectively. The fix lives entirely in its
caller's caller (`_boolean_refine_undercuts`), which now never invokes the
sweep at all for a near-zero-g face — the sign-flip-on-noise concern (the
other half of D-042) is resolved structurally, since the function is never
reached with a noise-dominated sign.

**Three-bucket evidence contract.** `UndercutDetectionResult` gains
`proxy_only_face_ids`, `boolean_confirmed_face_ids` (existing field,
narrower meaning now), `boolean_not_applicable_face_ids` +
`boolean_not_applicable_reasons` — disjoint by construction. The legacy
`undercut_face_ids` union is preserved for backward compatibility
(`direction_optimizer.py` reads it for display/reporting only, never for
scoring — verified by reading every call site) and still includes
not_applicable faces (flagged, uncertain — never silently cleared).

**Genuine positive case, hand-verified.** A new fixture,
`UC3_spool_true_undercut.stp` (bottom disk + narrow stem + top disk, all
coaxial), has a real trapped shelf: the top disk's underside ring (area
800 mm^2) swept down through the bottom disk (8mm thick) intersects
exactly `800*8=6400` mm^3 of real material — confirmed by the corrected
detector to that exact value. This proves the fix does not just suppress
false positives; the mechanism still correctly confirms genuine local
interference where one exists.

**Measured consequence on real parts (Part1/Part3/Dhukkan, all 6
principal directions).** Every proxy-flagged (low-draft) face on all
three real fixtures, at every tested direction, has `g` below the
threshold — meaning `boolean_confirmed_face_ids` is empty and
`boolean_not_applicable_face_ids` equals the full proxy set in every
case. Cross-checked with `boolean_check_all_faces=True` on Part1 +Z: 42
additional (non-proxy) faces were checked and all cleared with zero
interference — i.e. Part1 has zero Boolean-detectable local undercuts
along principal axes, whether restricted to proxy candidates or not. This
is reported as a real, honest finding, not tuned to produce it: the
teammate's proxy pass structurally only flags faces near the zero-draft
band, and typical axis-aligned CAD geometry's zero-draft faces are
overwhelmingly exactly tangent (OCC's analytic planar evaluator returns
bit-exact normals for exactly-axis-aligned planes) — so on this class of
part, this specific local-sweep mechanism currently has very little to
say. Flagged as a real limitation of the local-sweep approach for future
work, not something this phase's fix should paper over.

**Bosch Part1 reference (external evidence, not ground truth).** Before
this fix, Part1 +Z's Boolean layer reported one 10-face "critical" cluster
(depth 26.86mm — exceeding the part's own 30.78mm bbox diagonal, itself a
symptom of the corrupted volume feeding depth estimation) plus 7 small
perimeter features (8 features total) — a result whose *count* and
*shape* (a handful of localized groups, not the whole part) already
qualitatively resembled the Bosch reference's localized red-marker
pattern, but whose *confirmation and depth evidence* rested entirely on
now-proven-broken faces (every one of the 18 contributing faces measured
at `g=0.0000`). After the fix: the same 26 faces (a slightly larger,
more complete set — the old code's union formula silently dropped 9
checked-but-unconfirmed proxy faces from its own count; the new formula
never drops a proxy face without an explicit reason) now honestly report
`boolean_not_applicable`, split into 14 smaller `"minor"`-severity groups
with a physically plausible depth (0.97-1.45mm, not 26.86mm). No face-ID
level correspondence to the Bosch image markers is claimed — that would
require actual 3D visual comparison tooling, not available this session.

**Tests.** `tests/test_undercut_detector_semantics.py` (new, 8 tests):
`_face_access_direction` sign-correctness proof, near-zero-g boundary
calibration lock-in, true-tangent-wall exclusion, D-042 whole-part-volume
regression guard, genuine-undercut confirmation (exact 6400 mm^3), genuine
open-end clearance, mushroom near-zero-g exclusion, three-bucket
disjointness. `tests/test_undercut_detector.py`: 10 existing mock-based
tests updated (root cause: their `_make_face` fixtures used
axis-aligned-vs-axis-aligned normals, `g=0.0` by construction — an
intended semantic correction to keep them exercising Boolean-confirmation
mechanics rather than the now-excluded tangent-face category; a tiny
`g=0.005` perturbation preserves every test's original intent). Full
existing suite (`test_undercut_detector.py`, `test_direction_optimizer.py`,
`test_draft_analyzer.py`, `test_parting_line_v2_contracts.py`,
`test_step_loader.py`): 298 passed,
0 failed.

**Not done in this phase, explicitly deferred.** No wiring into H5 (still
awaits an evidence-quality-tagged adapter decision, per the earlier Phase
5 design report). No change to the proxy pass's inability to flag a
good-draft-but-wrong-signed shelf face (discovered this session while
building `UC2_mushroom_shelf_undercut.stp` — a face with `g=-1` has
excellent draft angle and is never proxy-flagged at all under default
settings, a distinct, real gap from D-042, flagged for a future phase, not
fixed here). No change to `direction_optimizer.py`.

---

# Phase — Core/cavity accounting contract (Phase 4): H4's gate-area convention and RegionClassification's reported-area convention are two different, both-legitimate answers to "how much area is in this region," and they were always meant to diverge — this phase names that fact and makes the frontend render it truthfully, without changing either convention's math

## D-045 — H4's per-region area sum and `RegionClassification.cavity_area_mm2`/`core_area_mm2` are two intentionally different area conventions over the same face set; neither is a bug, neither should be substituted for the other, and the UI must say so ⭐⭐⭐

**[2026-08-16] Implemented — `frontend/app.py`, `backend/api/main.py`. No
change to `gates.py`, `regions.py`, `engine.py`, or any H0-H7 math.**

**Decision.** Two area conventions coexist, both already present in code
before this entry, neither previously named outside inline comments:

- **Gate area** (H4, `gates.py:409-427`): `area(A) = Σ_{f∈A} face.area` over
  a region's raw H3 topological component membership. A face the parting
  boundary crosses (`split`/tooling-split) is a member of both components
  and is counted at full area in *both*; an `ambiguous`-labelled face is
  still counted at full area in whichever component it topologically sits
  in. This matches the plan's literal H4/C5 specification verbatim —
  `docs/PARTING_LINE_ALGORITHM_PLAN.md:59,680-686` defines `area(r)`/
  `area(A)` over the whole region, with no stated exclusion or
  apportionment.
- **Reported area** (`RegionClassification.cavity_area_mm2`/`core_area_mm2`,
  `regions.py:1082-1117`): `ambiguous` area is carved into its own bucket
  (`ambiguous_area_mm2`), and a `split` face's area is apportioned between
  sides by real geometric evidence (axial share for a D-043 tooling split,
  `mean_g` magnitude ratio for a genuine Track-B split), never
  double-counted. Explicitly self-documented as diagnostic-only: "NOT a
  feasibility gate: H3/H4 never read these" (`regions.py:906-909`).

Measured on Part3 +Z candidate 110: H4's own cavity-region denominator is
4424.787 mm²; `RegionClassification.cavity_area_mm2` reports 3651.175 mm²
for the same candidate. Both numbers are individually correct for what
they define; they are not the same measurement.

**Frozen for this phase.** Neither convention changes. H4 keeps using gate
area (it is the specified behaviour, not an oversight); the UI keeps
showing reported area (it is what a human means by "how much of this part
is cavity vs. core vs. undetermined"). The only change is that the gap
between them is now named, documented, and surfaced to the reader instead
of living only in a code comment.

**Where.** `frontend/app.py` (`_pv2_build_face_label_map`,
`_pv2_region_color`, v2 tab's Technical Details caption); `backend/api/
main.py` (`pv2_region_rgb` retired — see below).

**`pv2_region_rgb` retirement.** `main.py` computed a server-side
cavity/core-only RGB array (`pv2_region_rgb`), keyed off raw H3 component
membership (not the four-way label), on every `/parting-line-v2` request.
A repo-wide search found zero consumers — not the frontend, not tests, not
`backend/agent/`. Removed; the frontend already builds its own
label-accurate coloring directly from `payload["regions"]["faces"]`, and
already owns compositing for every other v2-tab overlay (undercuts,
core-pin, delegation groups), so a second, non-label-aware color source
was redundant by construction, not merely unused by oversight.

**Known gap, not closed in this phase.** H4's `measurements` dict
(`gates.py:428-429`) exposes only the final ratio
(`h4_orientation_violation_fraction`) and the delegated-face count, never
the raw numerator (violating area) or denominator (region area) that
produced it. Exposing those would require a `gates.py` change, which is
out of scope here — flagged as a small backend observability gap for a
future phase, not implemented now.

---

# Phase — Secondary-action delegation (plan D-044): H4 asks whether the geometry expected to move with the primary mould direction is orientation-consistent, not whether the whole part has no undercuts — an explicitly authorized, independently validated face set that is genuinely handled by a separate secondary mechanism can be excluded from that specific test, without ever claiming the mechanism has been proven to physically release it

## D-044 — `DelegatedSecondaryAction`/`validate_delegation`: H4's per-region orientation-area sums exclude only face ids from delegation records that independently pass structural validation for THAT candidate and THAT pull direction; validation proves self-consistency, never physical release ⭐⭐⭐

**[2026-08-15] Implemented — `contracts.py`, `types.py`, `regions.py`,
`gates.py`, `engine.py`.**

**Decision.** `evaluate_gates` gains an additive `delegations: tuple[
DelegatedSecondaryAction, ...] = ()` parameter. Each record is
re-validated, independently, per candidate and per `pull_direction`, by
`regions.validate_delegation`; only face ids from records that pass are
subtracted from BOTH the numerator (violating area) and denominator (total
area) of H4's per-region sums — region-aware, so a face delegated for one
candidate's cavity is never subtracted from an unrelated region or
candidate. `DelegationEligibility.eligible=True` means exactly one thing:
*"this explicitly authorized claim is structurally self-consistent for
this candidate"* — never that the secondary mechanism has been
geometrically proven to release the delegated faces.
`DelegationEvidence.geometric_verification` stays `"unverified"` — the
only legal value — regardless of validation outcome, and nothing in this
implementation reads it as anything stronger.

**Mathematics.** For each region `A ∈ {cavity, core}`, with `D` the union
of face ids from validated delegations: `area(A) = Σ_{f∈A\D} area(f)`,
`violation_area(A) = Σ_{f∈A\D, sign·g(f)<-ε} area(f)`,
`h4 = max_A violation_area(A)/area(A)`. Both sums are reduced together —
masking only the numerator (a naive "give credit" approach) would corrupt
the denominator's honest accounting of what area is actually being
claimed as primary-pull surface.

**Why.**
1. *Two-part gap, kept structurally separate throughout this design.* Gap
   A (detection): re-confirmed both `detect_undercuts` paths — fast-proxy
   returns `{35,37,38}` for Part3 +Z, Boolean-refined returns nothing at
   all — neither flags the rib lattice's radial trapping, a multi-face
   topological pattern no per-face draft heuristic can see. Gap B
   (semantics): even with a correctly-identified feature, H4 had no
   mechanism to exclude it. This milestone closes Gap B only; Gap A
   remains open, and `DelegatedSecondaryAction` is deliberately an
   AUTHORIZATION contract (mirroring `CorePinFaceRef`'s precedent), not a
   detector.
2. *`SideActionReferral` deliberately not reused.* It is H5's OUTPUT for
   one already-rejected candidate (`conflicting_segment_ids` only makes
   sense relative to a specific `Γ`) — the wrong lifecycle stage for a
   pre-candidate, part-level authorization. A new type was required.
3. *Validation is necessary, not sufficient, and the stress test proved
   it concretely, not just in principle.* Attempting to author ONE
   delegation record spanning Part3's ENTIRE rib lattice (`faces 0-16 ∪
   18-34`) was REJECTED by the connectedness check during implementation
   — measured directly, not hypothesized: the two mirror stacks are not
   adjacent to each other. This is the real-world confirmation of the
   design-phase question "can a connected face set requirement be
   violated by an overreaching claim" — split into two per-stack records
   (each independently confirmed connected), both pass.
4. *No confidence/readiness field.* Plan §12.7's ban, already enforced
   elsewhere in `parting_line_v2`, extends here:
   `DelegationEligibility` is boolean + reason (mirroring
   `CorePinEligibility`'s shape), and `geometric_verification` is a
   categorical admission of what has/has not been checked, never a score.
5. *`movement_type` is advisory-only, read by nothing.* Consistent with
   `.claude/rules/honesty-and-scope.md`'s existing "never claim the
   tooling mechanism" rule — H4's decision logic reads only the validated
   face-id set.
6. *No face-count/area threshold added*, per explicit instruction — a
   single small legitimate side-action face must remain representable;
   no concrete degenerate case has yet demonstrated the existing
   structural checks (connectedness, Γ-disjointness, non-parallel
   movement, provenance) are insufficient on their own.
7. *End-to-end confirmation on the real, unforced production pipeline.*
   `analyse_parting_line(Part3, +Z, core_pin_face_refs=(face 35,),
   delegations=(stack1, stack2))`: candidate 110 (`split_param=4.0`,
   already established as a real Round-1-discovered boundary) drops from
   `h4=7.56%` (0 delegated faces) to `h4=0.499%` (34 delegated faces) and
   **passes** — `outcome="feasible"`, this candidate selected. The
   residual 0.499% is real, un-delegated small transition-cluster faces,
   correctly still counted (not masked). The other two real core-pin
   candidates (`z=1.0`, `z=31.43`) receive the IDENTICAL two-record
   delegation and REMAIN REJECTED at H4 (12.6% and 23.8% respectively) —
   confirming nothing was tuned or additionally masked to force a result;
   the same authorized facts simply resolve one candidate's actual
   violation and not the others'.
8. *`CorePinInterface`/`tooling_split_face_ids` (D-043) and
   `DelegatedSecondaryAction` (D-044) coexist on the same candidate
   without interaction* — verified directly: the bore's core-pin face
   never appears in the validated delegated-face set, and the two
   mechanisms' face sets never overlap. They solve different problems
   (primary PL topology for a continuous coaxial face, vs. secondary-
   action geometry intentionally excluded from the primary rigid-body
   test) and remain reported through separate channels.

**Alternatives rejected.**
- *Reusing `undercut_face_ids` as delegation authorization* — an
  undercut/low-draft face is not automatically a side-action face (C4's
  formal statement and this project's own detector target different
  geometric properties; conflating them was explicitly rejected during
  design).
- *A numeric confidence/readiness score* — banned by plan §12.7; would
  also invite exactly the "passing validation proves feasibility"
  misreading this design exists to prevent.
- *Any geometric release/sweep/interference verification* — not
  implemented, not designed; D-042 already shows the one candidate
  mechanism (Boolean sweep) is unreliable for this class of geometry.
  `geometric_verification="unverified"` represents this limitation
  explicitly rather than manufacturing a stronger claim.
- *Face-count/area threshold* — deferred until a concrete degenerate case
  demonstrates the existing checks are insufficient; not before.

**Where.**
`backend/geometry/parting_line_v2/contracts.py` (`DelegationEvidence`,
`DelegatedSecondaryAction`, `DelegationEligibility`,
`GEOMETRIC_VERIFICATION_UNVERIFIED`, `DELEGATION_SOURCE_MANUAL_ENGINEERING`) ·
`backend/geometry/parting_line_v2/types.py`
(`FeasibilityReport.validated_delegations`) ·
`backend/geometry/parting_line_v2/regions.py`
(`_is_connected_subgraph`, `validate_delegation`) ·
`backend/geometry/parting_line_v2/gates.py` (H4's delegation-aware,
region-scoped area/violation-area computation; `validated_delegations`
threaded through every H4-and-later `FeasibilityReport`) ·
`backend/geometry/parting_line_v2/engine.py` (`delegations` parameter,
threaded through all three `evaluate_gates` call sites) ·
`config.yaml`/`backend/config.py` (`delegation_max_parallel_cos`) ·
`tests/test_parting_line_v2_delegation.py`.

---

# Phase — Core-pin / tooling-split mechanism (plan D-043): a coaxial through-bore has no B-Rep boundary or Track-B crossing anywhere along its length, so no candidate loop can ever be closed by cutting through it — closed instead via non-geometric H3 partition metadata, never a second curve on the real parting line

## D-043 — `tooling_split_face_ids`: a face exactly coaxial with the pull direction (Part3's bore, face 35, `g ≡ 0` across its entire length) is represented to H3 as a logical, axial-parameter-based split, kept structurally separate from `Γ` itself ⭐⭐⭐

**[2026-08-15] Implemented — `regions.py`, `contracts.py`, `types.py`,
`gates.py`, `engine.py`.**

**Decision.** A coaxial face bridging an otherwise-real candidate boundary
is split for H3 purposes by comparing each neighbouring edge's own axial
position against a canonically-derived `split_param`, via a new
`tooling_split_face_ids: dict[int, float]` argument to `separate_surface` —
**not** by adding a curve to `PartingLoopCandidate.segments`/`.loops`. The
real parting line stays exactly the candidate's genuine B-Rep boundary.

**Mathematics.** `separate_surface`'s existing split mechanism assigns a
neighbouring edge to one of a split face's two nodes by `sign(g)` at that
edge — exact when the cutting curve IS the `g=0` level set. A face with
`g≡0` everywhere (axis parallel to the pull direction) has no such level
set: `_g_at_edge_on_face` returns ≈0.0 at BOTH of the face's real ends,
which the existing `side >= 0.0` convention collapses onto the same node —
verified directly this session (naively adding face 35 to `split_face_ids`
merges its two ends instead of separating them). The new rule instead
computes `pos = dot(edge_midpoint, pull_direction) - split_param` and uses
the SAME `side >= 0.0` convention on that value — exact whenever the face
is genuinely coaxial (guaranteed by eligibility, below), because the two
ends then differ in axial position by construction.

**Why.**
1. *Representation gap, independently confirmed.* Face 35 (Part3's central
   bore) has exactly two B-Rep edges, both at its literal ends (z=1, z=39);
   nothing exists between them because Track B's silhouette detection is a
   `g`-crossing mechanism and `g≡0` the entire length. Any Z-primary H3-valid
   split is therefore forced to place its boundary at one of those two ends
   under the OLD representation — measured directly on the real candidate
   graph, not assumed.
2. *`ToolingBacking` (a fourth `CurveSegment` backing kind) was designed,
   then rejected after tracing the full lifecycle of `.segments`/`.loops`.*
   `ranking.score_candidate` computes coverage (T1), `excess_turning` (T5),
   and `length_3d_mm` (T6) directly from `.loops` with no regard to backing
   kind — a synthetic bore curve would inflate those measures with length
   that is not a real manufacturing seam. Plan §9.5 documents `.segments`/
   `.loops` as read by "the surface provider, the API payload, coverage and
   span measurement, the exporter, the agent" as the real, to-be-manufactured
   parting line; a core-pin's assigned split point fails that description
   (no flash risk, no witness mark). `H5`'s `loop_face_ids` is derived
   purely from `EdgeBacking` segments (`gates.py:279`, `364-367`) either
   way, so — correcting an earlier, wrong claim in this design's own
   derivation — adding `ToolingBacking` would NOT have caused a false H5
   undercut-touching referral; the decisive objection is the ranking/§9.5
   one, not H5.
3. *Bridge localization is topology-only, never proof of validity.*
   `find_bridge_faces` (iterative Tarjan articulation-point analysis on the
   plain edge-cut face-adjacency graph, reusing the exact edge-cutting rule
   `separate_surface` itself applies) answers only "does removing this face
   split the graph into two clean, one-neighbour-each-side components."
   Measured on the real z≈22 Part3 boundary: it returns 11 candidate faces
   (`{17,35,36,37,39,40,317,318,319,320,321}`), not just 35 — the base-flange
   and top-cap "stems" are simple unbranched paths, so every node on either
   one is individually a valid articulation-point bridge in the pure graph
   sense. `check_core_pin_eligibility` (five conditions: cylindrical, axis
   parallel/antiparallel within `cfg.core_pin_axis_angle_tol`, uniformly
   `|g| ≤ cfg.core_pin_uniform_g_max` over the WHOLE face — deliberately
   distinct config keys from H4's `orientation_epsilon`/
   `orientation_violation_max` — exactly two distinct neighbours, and
   `split_param` strictly inside the face's own longitudinal extent) is what
   actually narrows this to face 35 alone: every other candidate is a Plane,
   Cone, or Torus (fails condition a), and face 37 — the one other Cylinder
   in the set — fails only because `split_param=22` lies outside its own
   `z∈[1,4]` extent, not because it isn't a graph bridge.
4. *Naively bypassing eligibility can silently fabricate a passing H3.*
   Measured directly: calling `separate_surface` with
   `tooling_split_face_ids={37: 22.0}` (an ineligible face, both of whose
   real neighbours evaluate on the SAME side of 22) still returns
   `component_count == 2` — not because the split is meaningful, but because
   face 37's now-empty "other" node becomes its own trivial, isolated
   one-node component. This is why eligibility must run and be checked
   BEFORE `tooling_split_face_ids` is ever constructed for a real candidate,
   never treated as an optional/defensive check — `engine.py`'s Round 1.5
   only constructs the dict entry after `eligibility.eligible` is True.
5. *`split_param` is computed exactly once per candidate.* `
   resolve_primary_split_param` is the sole source of "where does this
   candidate's real boundary sit," passed by value into eligibility, the
   candidate's `tooling_split_face_ids`, `CorePinInterface`, and
   `separate_surface` — guarding against the class of defect already chased
   once in this project (two independently-sampled "same" geometric values
   silently disagreeing at the sub-millimetre level).
6. *End-to-end confirmation on the real production pipeline* (not just the
   isolated mechanism): `engine.analyse_parting_line(Part3, +Z,
   core_pin_face_refs=(CorePinFaceRef(35, ...),))` closes 3 independently
   Round-1-discovered candidates (real boundaries at z=1.0, z=4.0, z≈31.43)
   via the tooling mechanism, all subsequently and separately rejected at
   H4 — the pre-existing, deliberately untouched orientation-consistency
   gap this milestone does not address. `core_pin_face_refs=()` (the
   default) leaves every candidate's `tooling_split_face_ids`/
   `core_pin_interfaces` empty and Round 1.5 inert.

**Alternatives rejected.**
- *`ToolingBacking` as a fourth `SegmentBacking`/`CurveSegment` kind* — see
  point 2. Rejected after tracing the full consumer lifecycle
  (`ranking.py`, plan §9.5, the not-yet-built `PartingSurfaceProvider`),
  not merely asserted.
- *Iterating over all `CorePinFaceRef`-authorized faces and re-running H3 to
  see which one "makes it pass"* — rejected as opportunistic/search-based,
  not causal. `find_bridge_faces` must run first and its output intersected
  with authorization; a face never used merely because it is authorized,
  and never used merely because it is topologically a bridge — both plus
  eligibility, together, every time.
- *Reusing H4's `orientation_epsilon`/`orientation_violation_max` for the
  uniform-`g` eligibility check* — rejected: those are an AREA-FRACTION
  slack for a different purpose (whole-region orientation consistency); a
  dedicated, tight, per-point `core_pin_uniform_g_max` (default `1e-6`)
  keeps an edit to either from silently changing core-pin eligibility.

**Where.**
`backend/geometry/parting_line_v2/types.py` (`CorePinInterface`;
`PartingLoopCandidate.tooling_split_face_ids`/`.core_pin_interfaces`) ·
`backend/geometry/parting_line_v2/contracts.py` (`CorePinFaceRef`,
`CorePinEligibility`) ·
`backend/geometry/parting_line_v2/regions.py`
(`_axial_position_at_edge`, `separate_surface`'s tooling branch,
`_plain_face_adjacency`, `_components`, `_articulation_points`,
`find_bridge_faces`, `resolve_primary_split_param`,
`check_core_pin_eligibility`) ·
`backend/geometry/parting_line_v2/gates.py` (single-line
`tooling_split_face_ids` threading into the existing `separate_surface`
call) ·
`backend/geometry/parting_line_v2/engine.py` (Round 1.5) ·
`config.yaml`/`backend/config.py` (`core_pin_uniform_g_max`,
`core_pin_axis_angle_tol`) ·
`tests/test_parting_line_v2_core_pin.py`.

---

# Phase P3.19 — Workstream B side-core forensics on faces 325/366: BFS topology map built, then the Boolean-confirmed asymmetry between the two mirror faces traced to a floating-point sign-branch bug plus a deeper silhouette-sweep degeneracy in `undercut_detector.py`, NOT a real geometric difference

## D-042 — `detect_undercuts(boolean_refine=True)`'s per-face access-direction branch (`_face_access_direction`, strict `signed < 0.0`) mis-routes near-zero-g "silhouette" faces on floating-point sign noise (measured: `-9.9e-32` on one mirror twin, exact `0.0` on the other), and independently, `_swept_face_interference_volume` returns a degenerate whole-part-sized volume for this face type regardless of which direction it is swept — invalidating the "face 366 is critical / face 325 is clear" asymmetry that had been treated as the strongest side-core evidence ⭐⭐⭐⭐

**[P3.19, Workstream B] 2026-08-14.** No production code changed — this is a
finding, not yet a fix. All calls below invoke existing
`backend/geometry/undercut_detector.py` functions directly with explicit
arguments (read-only diagnosis).

**Motivation.** Workstream B asked for a geometrically-verified (not
assumed) characterization of faces 325/366 — Part3's only `+X`-undercut
faces (D-040-era B1/B2 survey, `boolean_refine=False`) and the strongest
evidence-backed side-core candidate at that point. Before building any
kinematic (main-cavity/main-core/side-core) decomposition on top of that
evidence, `detect_undercuts(..., boolean_refine=True)` was re-run to get
the full Boolean-confirmed picture Workstream B's steps 1-4 require.

**First finding — the asymmetry is real in the *report*, but the two faces
are geometrically indistinguishable.** `detect_undercuts` at `+X` with
`boolean_refine=True` returns `undercut_face_ids=[366]` only — face 325 is
absent, and 366 is `severity=critical`, `boolean_depth_proxy_mm=9.52`,
`depth_proxy_mm=53.97` (the latter LARGER than the part's own 40mm height —
a red flag on its own). Both `boolean_checked_face_ids` include 325 and
366; 325's own `_swept_face_interference_volume` returns exactly `0.0`
(clean), 366's returns `15062.3296mm3`.

**Second finding — that 15062.33mm3 is not a local pocket, it is the
entire part.** `GProp_GProps.VolumeProperties(part3.occ_shape)` gives
`15062.330994510356mm3`; the part's own bbox is
`(38.98, 38.98, 40.01)mm` centered at `(0,0,20)` — both match feature 366's
reported `boolean_region_geometry` to 5+ significant figures (vertex/edge
counts differ by 12/6, consistent with a Boolean-seam artifact on top of
an otherwise whole-part result, not literal shape identity). A 4.111mm2
planar shelf cannot legitimately have a 15062mm3 "local interference
volume" equal to 100% of the part's own material — this number is
degenerate, not evidence of a real trapped pocket.

**Root cause, part 1 (sign-branch bug).** `_face_access_direction` chooses
sweep direction by `signed = face.signed_dot(pull_direction); if signed <
0.0: return -pull_direction`. Both faces' normals are, geometrically,
EXACTLY `(0, 0, 1)` (perpendicular to `+X`, the textbook "silhouette"
case) — but `face.normal` for 325 evaluates to the literal tuple
`(0.0, 0.0, 1.0)` (`signed_dot = 0.0` exactly) while 366 evaluates to
`(-9.914e-32, -8.319e-32, 1.0)` (`signed_dot = -9.914e-32`) — floating-point
noise at the 1e-32 scale from whatever upstream normal computation
produced this specific face's vector. The **strict** `< 0.0` branch
treats these as opposite cases: 325 sweeps `+X` (correctly finds nothing,
`volume=0`), 366 sweeps `-X` (the "wrong"/backward direction for a face
that should be treated identically to its mirror twin).

**Root cause, part 2 (silhouette-sweep degeneracy, independent of the sign
bug).** Forcing BOTH faces through the SAME explicit access direction
(bypassing `_face_access_direction` entirely, calling
`_swept_face_interference_volume(part, face, direction)` directly) shows
the degeneracy is not explained by the sign bug alone: swept `+X`, 325=`0`
(clean) but 366=`15062.33` (still degenerate); swept `-X`, 325=`15061.48`
(ALSO ~whole-part-sized!) and 366=`15062.33` (same value, direction no
longer even changes the answer for 366). Two different faces produce the
same ~whole-part-volume reading when swept in their respective "wrong"
direction — strong corroborating evidence this is a general degeneracy of
sweeping a near-zero-g ("silhouette": face normal ~perpendicular to the
sweep direction) face's offset prism and Boolean-intersecting it with the
part: the prism's own side walls are then nearly tangent/coincident with
surrounding geometry, exactly the configuration OCC's Boolean kernel is
known to handle unreliably, and it does so here by returning something
close to the whole solid instead of failing loudly.

**Consequence — the "strongest side-core candidate" claim is retracted as
stated.** The 325/326 asymmetry (325 clear, 366 critical) that anchored
the side-core hypothesis through D-040/D-041 was never a proven geometric
fact — it is an artifact of applying an unreliable Boolean-refinement path
to exactly the face category (near-zero-g, silhouette) that path cannot
currently handle. The earlier `boolean_refine=False` survey (D-040-era
B1/B2) is UNAFFECTED (it never invokes this code path) and its finding
stands: both 325 and 366 are symmetric, moderate-severity, silhouette-type
proxy candidates — matching their genuinely mirror-symmetric B-Rep geometry
(identical 4.111mm2 area; centroids `(8.481,-10.167,22.0)` /
`(-8.481,10.167,22.0)`; both cap a near-identical stack of Cylinder /
Plane / Torus / Sphere-fillet ribs running from the part's base plane
(face 17, area 413mm2, `z=4.5`) up to `z=22.0`, where the rib meets the
underside of a full circumferential outer cylindrical band, face 38
(radius 12.5mm, centered on the part's own main Z axis, `z=22.0` to
`31.43`, confirmed via `BRepAdaptor_Surface.Cylinder()` — NOT an off-axis
pillar as an earlier informal read of its single centroid/normal
suggested; a full-circle face's own centroid/normal pair is not a
meaningful "direction" and should not have been read that way).

**Decision.** Do not build a kinematic main-cavity/main-core/side-core
decomposition on top of the Boolean-refined evidence for this feature type
— it is not currently trustworthy. Do not modify
`undercut_detector.py` in this turn (out of the scope explicitly given —
Workstream B asked for geometric characterization, not an algorithm fix,
and this defect needs its own regression fixture before any change is
trusted, per this project's standing discipline). Treat 325/366 as a
genuinely symmetric, moderate-confidence pair pending either (a) a fixed
Boolean layer, or (b) direct geometric/manual reasoning about the rib
structure's release kinematics that does not depend on the broken sweep
path.

**Alternatives rejected.** Silently using the Boolean-confirmed numbers
(depth, release direction, "critical" severity) to build the requested
kinematic decomposition — rejected: `release_direction=(-0.0, 0.859,
0.512)` for feature 0 is computed by
`release-direction-method: boolean-region-center-transverse`, i.e. directly
FROM the degenerate whole-part `boolean_region_geometry`'s center of mass
— a number derived from corrupted input is not usable evidence, and
reporting it as a finding would violate this project's explicit honesty
rules.

**Where.** Reproduction commands only (no new file yet — this is a
diagnosis, not an instrumented script): `backend.geometry.undercut_detector
._face_access_direction`, `_swept_face_interference_volume`,
`detect_undercuts`; `backend.geometry.step_loader.load_step_cached`;
BFS topology map obtained via `part.face_adjacency` (3 hops from face 366,
80 faces).

---

# Phase P3.18 — Workstream A1/B: same-piece self-closure welding defect proven on a controlled fixture, proven regression-safe, but proven NON-OPERATIVE for Part3's real odd-degree vertices; Formulation A/B side-core diagnostic re-interpreted accordingly

## D-041 — Two-stage welding correction (Stage 1 cross-piece unchanged, Stage 2 same-piece self-closure gated on chord/path ratio) reproduces and fixes the hypothesized defect on a controlled synthetic fixture and is byte-identical-safe on Part1, but produces ZERO change across all 25 Part3 (direction × objective) cells because a structurally distinct bypass mechanism — the same cross-piece tolerance transitively re-merging the same two vertices through a nearby legitimate near-degenerate piece — reproduces the identical erroneous merge ⭐⭐⭐

**[P3.18, Workstream A1] 2026-08-14.** No production code changed. New:
`backend/validation/parting_line_self_weld_diagnostic.py`.

**Motivation.** D-040's forensic trace of cluster 571 (`+Y`, `C_balanced_low`)
found piece 285 (a genuine, Track-B-confirmed OPEN curve on face 371, UV
span `[0,1]`, path length 1.09mm) marked `is_self_loop=True` by
`_weld_piece_endpoints` purely because its own endpoint chord (0.9312mm)
falls inside the general stitch tolerance (1.36mm) — the same flat
pairwise-distance test used for legitimate cross-piece stitching (D-022)
is applied, unmodified, to a single piece's own two ends. This is a
specific, generalizable hypothesis (not specific to piece 285): **open
curve + spatially-close endpoints is being conflated with closed/
near-degenerate curve**, and needed to be proven or falsified on a
controlled fixture before any correction could be trusted on Part3.

**Mathematics — the two-stage correction.** Stage 1 (cross-piece, UNCHANGED
from production): any two DIFFERENT pieces' endpoints within `tolerance`
are unioned exactly as `_weld_piece_endpoints` already does. Stage 2 (NEW):
a piece's own start/end are unioned only if BOTH (a) `chord <= tolerance`
(the existing spatial-closeness gate) AND (b)
`chord / path_length <= self_close_ratio_threshold`, where `path_length` is
the real polyline length through the piece's own already-sampled 3-D
points. This is a relative, scale-invariant criterion, not a new absolute
tolerance — verified explicitly with two closed-loop fixtures at radius
0.5mm and radius 2e-4mm (matching production's real near-degenerate scale,
piece 227's ~1.5e-4mm sub-arc), both correctly self-closing under the same
ratio rule.

**Fixture proof.** `fixture_open_hook` (circular arc, radius 0.5mm, 110deg
covered) reproduces the real defect almost exactly: chord=0.819mm,
path=0.958mm, ratio=0.855 (real piece 285: chord=0.931mm, path=1.090mm,
ratio=0.854) — production's `_weld_piece_endpoints` DOES incorrectly
self-weld it (defect reproduced on a clean, non-Part3-specific fixture);
`weld_piece_endpoints_v2` correctly refuses self-closure at every tested
ratio threshold (0.05, 0.1, 0.2, 0.3) — the huge separation between the
open-curve regime (ratio ~0.85) and the closed/near-degenerate regime
(ratio ~1e-16 to ~1e-3) means the exact threshold value is not
load-bearing. Cross-piece welding at realistic D-022 gaps (0.043mm,
0.5mm, 1.05mm) is byte-identical between old and new logic (Stage 1 is
untouched).

**Part1 regression.** `+Z`/`+X`, all 5 objectives: old vs new fingerprints
IDENTICAL in every cell that produces a real candidate (one `+X`
`B_silhouette_dominant` cell is `degenerate_cut` under both, unaffected).
`+Z`/`C_balanced_low` matches the golden fingerprint exactly
(`cavity=42, core=269, cavity_area_mm2=362.338, core_area_mm2=1203.814,
h3=2.0, h4=0.0, h7=0.9991608536203086`, single loop, `h1=0.0`).

**Part3 result — the important finding.** Patched into the full pipeline
(`run_experiment_nway_subedge`) via a scoped monkeypatch of
`proto._weld_piece_endpoints`, restored after every measurement: across
ALL 5 directions (`az15`, `(0,1,1)`, `+X`, `-X`, `+Y`) × all 5 objectives
(25 cells), OLD and NEW produce **byte-identical** `outcome`,
`failed_gate`, `loop_count`, `cavity_face_count`, `core_face_count`, and
every H0/H1/H3/H4/H7 measurement. The odd-degree-vertex tallies at
`C_balanced_low` are also identical in every direction (`az15`: 20/20,
`(0,1,1)`: 2/2, `+X`: 16/16, `-X`: 16/16, `+Y`: 8/8).

Directly re-checking piece 285 explains why: under `weld_piece_endpoints_v2`
piece 285's own two ends are correctly refused DIRECT self-union (ratio
0.854 > 0.1), but they still end up in the SAME connected component
(cluster 571) via a two-hop bypass — piece 285's start point is
cross-piece-welded (Stage 1, legitimate, chord~0) to piece 227's end
point; piece 227's own two ends ARE correctly self-welded (piece 227 is a
genuine near-degenerate arc, ratio~0); and piece 227's start, plus
piece 284's start (another face-backed piece touching the same physical
location), sit within the SAME 1.36mm tolerance of piece 285's END point's
own cross-piece cluster (piece 1 / piece 236, at the other, ~0.93mm-away
physical location) — closing the loop through a chain of individually
legitimate-looking pairwise unions. **The defect is real and was correctly
fixed at the level it targets (a piece's own direct self-closure), but it
is not the operative mechanism producing Part3's observed odd-degree
vertices** — a second, structurally similar phenomenon (the same shared
cross-piece tolerance bridging two physically distinct vertices through an
intermediary piece) reproduces the identical erroneous merge and was
explicitly out of this diagnostic's bounded scope (fixing it would mean
touching the shared cross-piece tolerance itself, which D-040's earlier
tightening experiment already showed makes things dramatically worse:
8→82 odd vertices — and which the standing instructions forbid weakening
or "fixing" merely to produce a cleaner topology).

**Decision (per the 5-way matrix).** Closest to option 3, precisely
qualified: the hypothesized welding defect is PROVEN real, PROVEN fixed at
its own level, PROVEN regression-safe — and PROVEN NOT SUFFICIENT to
change any Part3 outcome, because a related-but-distinct transitive-bypass
mechanism achieves the same erroneous merge through the same shared
tolerance. This is not "welding defect disproven" (option 2) — the fixture
proof stands — and it is not "rerun side-core analysis with a now-trustworthy
graph" (option 1) — the graph's odd-degree vertex set at `+X` (where the
side-core candidate faces 325/366 live) is completely unchanged by this
fix, so the topology is not "trustworthy" in the sense the instructions
require before returning to Workstream B.

**Alternatives rejected.** Tightening the shared cross-piece tolerance to
close the bypass — rejected, already shown (D-040) to make things far
worse and explicitly forbidden. Blocking any self-loop that shares a
cluster with another self-loop (a broader structural rule) — not
attempted: it would need its own fixture/validation cycle and risks
breaking legitimate multi-feature junctions (D-040's Fixture G/J
territory); flagged as a candidate follow-up hypothesis, not implemented,
per the standing instruction to stay bounded.

**Where.** `backend/validation/parting_line_self_weld_diagnostic.py`
(`weld_piece_endpoints_v2`, `run_fixture_tests`, `run_part1_regression`,
`run_part3_comparison`, `_patched_welding`); raw run log at
`/private/tmp/claude-501/-Users-abhinavgurkar-Bosch/327b3d9a-100f-4d64-8415-7e9e483cfc8f/scratchpad/a1_full_run.log`
(session-scoped scratch path, not committed).

---

# Phase P3.16-17 — N-way face partitioning + sub-edge-aware cross-face attachment; even-degree invariant proved; forensic odd-degree tracing; self-loop duplication investigation

## D-040 — Proper N-way (not binary) face-region topology solved generally via `shapely.polygonize`, validated on 12 synthetic fixtures before touching Part3; sub-edge-aware cross-face attachment (splitting shared edges at every real geometric breakpoint) fixes the coarse-midpoint-attachment gap; a mathematical proof establishes odd-degree vertices are NEVER legitimate topology; automated real-geometry-only forensic tracing (never comparing raw parameters across different OCC parameterizations) clears cross-face attachment as a cause at cluster 571 and instead finds a single-piece self-merge tolerance conflation (piece 285) ⭐⭐⭐⭐

**[P3.16-17] 2026-08-13/14.** No production code changed. New:
`backend/validation/parting_line_face_partition.py`,
`backend/validation/parting_line_odd_degree_trace.py`,
`backend/validation/parting_line_forensic_trace.py`; extended
`build_min_cut_partition_nway_subedge` in
`parting_line_region_partition_prototype.py` (diagnostic file, still no
production code touched).

**Motivation.** D-039 showed the binary (face, +-1) split model is wrong
whenever a face has more than one Track-B interior curve (45% of Part3's
split faces). The general topology question — how many regions does a
face's own boundary plus N interior curves actually create — needed a
non-hardcoded solver (explicitly NOT an "N curves -> N+1 regions" rule)
proven on synthetic fixtures before being trusted on Part3, per the
standing instruction.

**Mathematics — N-way partitioning.** A face's outer + inner wire boundary
edges, sampled in UV via `_sample_edge_uv`, plus its own Track-B interior
curves' UV samples, are fed to `shapely.ops.polygonize` after
`unary_union` + `set_precision` snapping — a general planar-arrangement
solver, not a curve-counting formula. `region_adjacency` requires
`boundary.intersection(other.boundary).length > touch_tolerance` (a
LENGTH, not a distance, test) so that two regions only touching at a
single point (e.g. diagonally, across intersecting curves) are correctly
NOT treated as edge-adjacent. `build_face_regions` filters out regions
bounded only by inner (hole) wire edges with no outer-wire or
interior-curve touch — these are hole interiors, not material.

**Fixtures A-L (+K), all PASS.** A (1 open curve -> 2 regions), B (2
disjoint open -> 3), C (3 disjoint open -> 4), D (1 closed -> 2), E (2
disjoint closed -> 3), F (open+closed -> 3), G (intersecting curves -> 4,
explicitly NOT N+1 — proves the solver is general), H (periodic-seam flat
domain, documented limitation), I/J (multi-face offset/multiple
breakpoints -> 3/4 sub-intervals), K (real `BRepPrimAPI_MakeCylinder`
lateral face, own seam edge appearing twice in its wire, zero interior
curves -> exactly 1 region, not 2), L ("Task 5" coincident junction — both
faces' curves reaching the shared edge at the SAME parameter must merge
into exactly 2 sub-intervals, not 3).

**Mathematics — the even-degree invariant (proof, not hypothesis).** For a
candidate curve `Gamma` satisfying C1 (disjoint union of simple closed
curves) and H2 (simple), ANY subdivision graph built from it — regardless
of how points are merged by welding — has every vertex at even degree.
Proof sketch: before any merging, every point on a simple closed curve has
degree exactly 2 (one edge in, one edge out along the curve). Merging two
points into one vertex sums their pre-merge degrees; summing any multiset
of 2's is always even. Therefore **odd degree is mathematically impossible
for a correctly-constructed representation of valid input geometry** — it
is not a tolerable edge case, and any occurrence must always trace to a
specific representation defect (a missing edge, a wrong attachment, or a
spurious edge), never to "legitimate high-valence B-Rep topology." This is
the standard the entire subsequent forensic investigation is held to.

**Sub-edge-aware cross-face attachment.** Earlier attachment sampled one
midpoint per shared B-Rep edge; `edge_subinterval_attachment` instead
splits a shared edge at every real breakpoint contributed by EITHER
adjacent face's region boundary, found via exact shapely geometric
intersection (never coarse resampling). Two representation bugs were
found and fixed via Part1 regression stress-testing before this was
trusted: (1) collinear-fragment over-fragmentation from two independently
discretized copies of the same boundary, fixed by collapsing to
min/max of each region's own projected extent; (2) ~1e-6mm floating-point
breakpoint noise, fixed via a `1e-4` merge pass. A sampling-density
mismatch (explicit `n=24` in the attachment call vs. the `n=12` default
used to build the regions themselves) alone produced 58/744 Part1 edges
(all `Circle`-type) with 21 spurious sub-intervals each — fixed by
removing the override so both call sites share one default.

**Odd-degree forensic tracing.** A systematic tracer
(`parting_line_odd_degree_trace.py`) found 20/2/16/16/8 odd-degree
vertices at `az15`/`(0,1,1)`/`+X`/`-X`/`+Y` (`C_balanced_low`). An early
programmatic classifier's "near_seam" heuristic was flagged as unreliable
(too broad) and its resulting "14 E_periodic_seam" count explicitly
marked not-trustworthy evidence. A manual trace of cluster 49 caught a
real self-inflicted error: conflating an edge's own curve parameter `t`
with a face's UV parameter `u` because both numerically resembled `pi` —
caught via direct `S(u,v)` evaluation showing a 23.23mm discrepancy,
self-reported rather than silently continued, and it produced the standing
rule that all subsequent tracing (`parting_line_forensic_trace.py`) uses
ONLY real OCC point evaluation (`BRepAdaptor_Curve.Value`, `Geom_Surface`
evaluation, `GeomAPI_ProjectPointOnCurve/OnSurf`), never raw parameter
comparison across different parameterizations.

**Cluster 571 self-loop investigation (Task: pieces 227 vs 285).** The
initial hypothesis — piece 227 and piece 285 are the same feature counted
twice — was DISPROVEN by direct geometric comparison. The real mechanism:
piece 285 is a genuine, Track-B-confirmed OPEN curve (face 371,
BSpline/NURBS, UV span `[0,1]`, path 1.09mm) whose own two ends (chord
0.9312mm) fall inside the general stitch tolerance (1.36mm), so
`_weld_piece_endpoints` incorrectly self-closes it — this is exactly the
defect later proven and bounded in D-041. Diagnostic removal experiments
(deleting pieces one at a time and rechecking parity: 7->5->5->3, all
still odd) explicitly did NOT restore even parity — used as evidence
AGAINST the "degree-becomes-even" test as proof of anything, per the
standing instruction never to use parity-restoration-by-deletion as
validation.

**Alternatives rejected.** Trusting the early near_seam classifier's tally
as a finished taxonomy — rejected pending the automated forensic tool.
Treating cluster 571's odd count as resolved once removal experiments
changed the number — rejected explicitly (parity was never restored, and
even if it had been, removal is not evidence of correctness per the
standing rule).

**Where.** `backend/validation/parting_line_face_partition.py` (fixtures
A-L+K, `build_face_regions`, `region_adjacency`, `edge_subinterval_attachment`);
`backend/validation/parting_line_odd_degree_trace.py`
(`trace_odd_degree_vertices`, `classify`); `backend/validation/parting_line_forensic_trace.py`
(`search_all_edges_near_point`, `forensic_trace`); sub-edge wiring in
`parting_line_region_partition_prototype.py`'s
`build_min_cut_partition_nway_subedge`.

---

# Phase P3.13-15 — Multi-curve split-face defect discovered and bounded (Option 2); proper N-way partitioning scoped as the correct fix

## D-039 — Binary (face, +-1) split-face model is provably wrong whenever a face has more than one Track-B interior curve (45% of Part3's split faces); Option 2 (single-curve-only faces get split, multi-curve faces treated as whole) isolates the defect's effect without yet fixing it ⭐⭐⭐

**[P3.13-15] 2026-08-13.** No production code changed. Extended
`parting_line_region_partition_prototype.py` (diagnostic file only):
`build_min_cut_partition_split`, `run_experiment_split`, `main_option2`.

**Motivation.** D-038's Experiment 1 (Track-B split-face nodes) modeled
each split face as exactly two sides, `(face_id, +1)`/`(face_id, -1)`,
implicitly assuming exactly one Track-B interior curve per face. A Part1
`+X` regression stress-test surfaced systematic H1 closure failures whose
cause traced to faces with MULTIPLE interior curves being forced into this
2-sided model — measured directly: 45% of Part3's Track-B split faces
have more than one curve, so the binary model is not a corner case, it is
close to half of the represented geometry.

**Mathematics.** `build_min_cut_partition_split` adds
`max_curves_per_split_face: int | None` — when set, faces with more curves
than the limit fall back to being treated as a single whole-face node
(their split is simply not represented, not silently corrupted).

**Diagnostic isolation (Option 2).** Comparing single-curve-only faces
(correctly representable in the binary model) against multi-curve faces
(known-wrong in the binary model) via `_gate_tally` across Part1 controls
and Part3 directions shows single-curve faces behave consistently with
D-038's whole-face baseline, while multi-curve faces show elevated,
inconsistent H1 failure rates — consistent with, but not yet a full fix
for, the multi-curve hypothesis. Per the standing "narrow interpretation
only" rule for this experiment, this was reported strictly as "the binary
model is confirmed insufficient for multi-curve faces," not as "the
general N-way model would fix Part3" — that claim required the separate
Option 1 fixture-first validation (D-040).

**Decision.** Do not patch the binary model with a special case; scope the
proper general fix (N-way partitioning, validated on synthetic fixtures
FIRST) as the next step — carried out in D-040.

**Alternatives rejected.** Extending the binary model to a fixed small N
(e.g. 3-sided) — rejected as still not general and still implicitly
hardcoding a curve-count assumption the geometry does not respect (some
faces have many more than 3 curves).

**Where.** `backend/validation/parting_line_region_partition_prototype.py`
(`build_min_cut_partition_split`, `run_experiment_split`, `main_option2`,
`_gate_tally`).

---

# Phase P3.12 — Region-partition candidate proposer (architecture-report follow-up): Part1 sanity confirmed, Part3 finding self-corrected, extended sweep finds no genuine separator

## D-038 — Global min-cut candidate PROPOSER (not a validator) tested against the unchanged production H0-H7 gates on Part1 controls + 3 Part3 directions; Part1 independently reproduced; Part3's apparent H3 pass was a degenerate 3-4-face pinch, not a real separator, and a 3-order-of-magnitude weight sweep found no regime that produces one ⭐⭐⭐⭐

**[P3.12] 2026-08-13.** No production code changed. New:
`backend/validation/parting_line_region_partition_prototype.py`,
`reports/region_partition_prototype.json`.

**Motivation.** The architecture-report investigation (this doc's own
summary, delivered as a 10-section report answering the standing question
"is the cycle-based candidate representation strong enough") identified one
untested representational question: the cycle-based pipeline's candidate
space has a hard ceiling of `max_loop_union_size=4` simultaneously-unioned
loops, chosen from an independently-enumerated pool (D-017, D-019). Every
prior Part3 forensic finding (D-027/D-028/D-033/D-034/D-036/D-037) traces a
failure to a candidate *within that space* not separating the part — none
of them tests whether a candidate *outside* that space (an unbounded number
of simultaneous components, read off a jointly-optimized global partition
rather than assembled from independently-found cycles) could succeed where
the bounded search structurally cannot even propose an answer. A follow-up
review correctly flagged that the report's original framing ("a min-cut
boundary is a valid candidate by construction") conflated two different
claims — a min cut gives a PARTITION OF FACES, not an H0-H7-valid parting
curve — and required this prototype to (a) treat the optimizer as a
proposer only, (b) route every candidate through the unmodified
`gates.evaluate_gates`, and (c) test at least 3 qualitatively different cost
formulations rather than trust a single arbitrary weighting.

**Mathematics.** Standard s-t minimum cut / binary image-segmentation
construction over the part's face-adjacency graph (nodes = whole faces;
Track-B split-face nodes are explicitly out of scope for this prototype —
every candidate boundary it can propose runs along existing B-Rep edges
only). Source `S` = cavity label, sink `T` = core label, `g(f) =
f.signed_dot(d)`:

```
capacity(S, f)  = unary_weight * area(f) * max(0, +g(f))
capacity(f, T)  = unary_weight * area(f) * max(0, -g(f))
capacity(a, b)  = smoothness_weight * shared_edge_length(a, b)
                  * (silhouette_discount if any shared edge is already
                     Track-A-flagged silhouette else 1.0)
```

`networkx.minimum_cut` solves the partition; the cut edge set is decomposed
into closed walks by a deterministic Hierholzer traversal (a 2-coloring
boundary on a closed 2-manifold has even degree at every vertex it touches
— a real topological guarantee, not an assumption; any component that turns
up odd-degree is skipped with a note, never forced closed); each walk's
direction is resolved by matching the weld-key vertex SHARED between
consecutive edges (anchoring on an arbitrary edge endpoint was tried first
and produced a systematic H1 closure failure on every candidate — Hierholzer
does not preserve which physical endpoint of the first edge begins the
cycle, so that anchor is topologically arbitrary); every point is then
sampled directly off the real OCC edge curve (`BRepAdaptor_Curve.Value(t)`,
never fitted/interpolated) and assembled into a real `PartingLoopCandidate`,
fed unmodified into `evaluate_gates`.

Five weightings tested per direction: `A_orientation_dominant` (1.0, 0.0,
1.0) — the naive per-face baseline D-033 already showed is too fragmented,
included as a negative control; `B_silhouette_dominant` (0.05, 1.0, 0.05);
`C_balanced_{low,mid,high}` (1.0, {0.10, 0.30, 1.00}, 0.10).

**Findings — Part1 (sanity gate, both pass).** `+Z`: 4/5 objectives (all but
the naive baseline) independently rediscover the known-good candidate —
`h3_region_count=2`, `h4_violation=0.0`, feasible, `h1_closure_error_mm`
exactly `0.0` after the direction-resolution fix. `A` correctly
over-fragments into 23 regions. `+X` (known cycle-search failure): all 5
correctly fail to separate (fragmentation or degenerate cut). The
machinery is doing the right thing on ground truth before touching Part3.

**Findings — Part3, first pass (3 directions: `az15` — D-036's strongest
single-loop direction; `(0,1,1)` — D-033's CASE-A cluster anchor; `+X` —
known control).** `B_silhouette_dominant` reached `h3_region_count=2` at
`az15` and `(0,1,1)` — the first time in the ENTIRE P3.x investigation H3
has returned exactly 2 for Part3 at any tested direction under any method.
Inspecting the actual candidate before reporting this as a breakthrough (per
the standing instruction not to trust a single arbitrary weighting):
`az15`'s candidate is cavity=411/core=3 faces over 2 cut edges;
`(0,1,1)`'s is cavity=410/core=4 over 3 cut edges. **This is a degenerate
artifact, not a discovery**: at `B`'s near-zero unary weight, the global
minimum of "total cut cost" is generically achieved by isolating whatever
local cluster has the least total boundary length, which on a real part is
almost always a small local feature — the same category of trivial pinch
D-027/D-028/D-032 already found and H4 already correctly rejects (34%
violation there; 21.1%/27.2% here, same mechanism, both correctly rejected
at H4 here too). The `C`-family (real orientation weight) never reached H3
in this first pass, but showed region counts falling as smoothness weight
rose (`az15`: 15→14→9; `(0,1,1)`: 18→16→4) while cavity/core face counts
stayed substantial and roughly balanced (e.g. 354/60, not a sliver) — an
initial, and in hindsight premature, reading treated this trend as
suggestive of convergence toward a genuine large-scale separator.

**Findings — Part3, extended sweep (self-correction).** Smoothness weight
swept 1.0→100.0 (unary=1.0, silhouette_discount=0.10 fixed) at the two
directions showing the trend. Both directions show the SAME shape, not
convergence toward 2: region count falls to a local minimum around a
genuinely balanced split (`az15` sw=2-5: 354/60, region_count=**3**, not
yet 2; `(0,1,1)` sw=1-3: 354/60 or 75/339, region_count=**4**), then at a
sharply higher weight (`az15` sw=8; `(0,1,1)` sw=5) the cut **jumps
straight to the same trivial 3-4-face pinch** `B` already found
(411/3 and 410/4, both `h3_region_count=2`, both rejected at H4 — identical
values to the first pass, confirming this is one specific, findable
attractor, not noise), and at even higher weight (`az15` sw≥60; `(0,1,1)`
sw≥20) the cut collapses entirely to "no separation" as the smoothness term
overwhelms the unary forcing signal. **There is no smoothness-weight regime,
across 3 orders of magnitude, where the cut converges to a genuine
non-trivial H3-passing global separator at either direction.** The earlier
"9→4 trending toward 2" reading is retracted: 9 and 4 were transit points on
the way to full collapse, not progress toward a real answer.

**Classification.** Genuinely new evidence, not previously obtainable: a
method structurally capable of proposing an UNBOUNDED number of
simultaneous components (no `max_loop_union_size` analog) — the
representational capacity the cycle-based search provably lacks (D-017,
D-019) — was tested against the unmodified H0-H7 gates at the two Part3
directions with the strongest prior circumstantial evidence (D-033's
"plausible" separability score, D-036's largest single loop), under 5
qualitatively different cost formulations spanning a 3-order-of-magnitude
weight range, and **found no genuine H3-passing candidate at either
direction**. This does not prove Hypothesis A (no feasible direction) — only
2 of Part3's 374+ tested directions were probed this way, and Track-B
split-face nodes remain out of scope for this prototype — but it is real
evidence *against* Hypothesis B (representational ceiling) being the whole
explanation at these specific two directions: removing the ceiling did not
produce an answer cycle-search was blocked from reaching. Consistent with,
not contradicting, D-034's finding that Part3's partial silhouette coverage
(the bore, the torus/boss pinches) reflects genuine geometry rather than a
detection gap.

**Alternatives rejected.** Reporting the first-pass `B`/`C`-trend finding at
face value without the face-count inspection and extended sweep — rejected
per the explicit standing instruction to test multiple cost formulations
specifically to catch this failure mode, and per this project's own
practice of correcting a claim in a later entry rather than leaving a
misleading one standing (see D-027→D-028).

**Where.** `backend/validation/parting_line_region_partition_prototype.py`
(full script); `reports/region_partition_prototype.json` (first-pass raw
results, 5 directions × 5 objectives); extended sweep run inline, not yet
persisted to a file — re-run from the module's `build_min_cut_partition` /
`decompose_into_loops` / `assemble_candidate` functions if the raw sweep
data is needed again.

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
