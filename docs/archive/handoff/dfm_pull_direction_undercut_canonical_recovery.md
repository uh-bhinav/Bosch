# DfM Pull-Direction + Undercut Detection — Canonical Recovery Specification

## Purpose

The current `French` branch is at the early pull-direction implementation, where draft, marginal draft, and undercut-like signals were mixed into large weighted scores. This document is the canonical target for rebuilding the pipeline. It intentionally does **not** reproduce every historical intermediate implementation; it preserves the final semantic decisions, correctness constraints, performance fixes, and validation requirements established during the previous iterations.

The target is:

**STEP/OCC geometry → directional draft metrics → accessibility-risk analysis → small Boolean candidate pool → face-level OCC validation → semantic undercut classification → hierarchical direction search → validated ranking → cached final result.**

Primary reference cases: `Part1(original).stp` should select approximately `+Z`; Part3 must remain free to select a legitimate off-axis direction.

---

## 1. What Was Wrong With the Original French-Branch Architecture

The old optimizer used large weighted terms such as approximately:

```text
1000 × bad-draft contribution
10000 × undercut contribution
+ marginal-draft penalty
+ other directional penalties
```

The fundamental problem was not merely the numeric weights. It was **double-counting correlated evidence**.

A face with `draft_angle < marginal_threshold` could already be treated as suspicious draft and then be promoted into the undercut calculation. If the Boolean result was then also counted as undercut risk, the same geometry influenced the optimizer multiple times.

That caused:

- redundant calculations;
- inflated undercut scores;
- ordinary near-vertical walls being mistaken for undercuts;
- expensive OCC work on huge candidate pools;
- unstable/wrong direction ranking.

### Non-negotiable conceptual rule

**Low draft is not an undercut.**

Draft analysis answers:

> How well does this face satisfy the draft requirement for this pull direction?

Undercut analysis answers:

> Does the geometry actually obstruct mold withdrawal?

Those must remain separate signals.

---

# 2. Ideal End-to-End Pipeline

```text
STEP file
  ↓
OCC geometry loading
  ↓
Directional metrics for candidate pull direction d
  ├─ face normals
  ├─ n·d
  ├─ draft angle
  ├─ mold side
  └─ draft classifications
  ↓
Cheap accessibility analysis
  ├─ marginal/proxy draft evidence
  ├─ perpendicular-dot classification
  └─ core-side + concave/re-entrant risk
  ↓
Boolean candidate construction
  ├─ genuine accessibility-risk candidates
  ├─ optional proxy evidence only when demonstrably useful
  └─ exclude perpendicular-dot faces for the CURRENT swept-face formulation
  ↓
OCC Boolean validation
  ├─ offset
  ├─ sweep/prism
  ├─ intersect with part
  └─ measure volume
  ↓
Semantic classification
  ├─ confirmed
  ├─ suspected/inconclusive
  ├─ no_interference
  ├─ failed
  └─ skipped
  ↓
Strict boolean_validation_complete
  ↓
Direction optimizer
  ├─ Stage 1: ±X, ±Y, ±Z
  ├─ Stage 2: diagonals
  └─ Stage 3: spherical/fine candidates
  ↓
Validated direction ranking
  ↓
Winning direction + cached validated undercut result
```

---

# 3. Draft Layer — Protect It

`backend/geometry/draft_analyzer.py` is already considered correct. Do not redesign it to solve pull-direction problems.

For each direction it should continue to compute:

- face normal;
- signed `n·d`;
- draft angle;
- mold side;
- good/bad/marginal draft.

Keep the existing `suitability_max_bad_draft_pct = 30.0` unless future evidence proves that threshold itself is wrong. The previous Part1 behavior of approximately `71.7%` bad draft at +Z means +Z can legitimately fail the Stage-1 cheap suitability gate and still be recovered by later validated ranking. fileciteturn45file0L23-L31

**Do not change draft analysis merely because direction optimization is wrong.**

---

# 4. Separate the Four Geometry Classifications

These are independent and must never be conflated.

| Classification | Meaning |
|---|---|
| Perpendicular-dot | `|n·d| <= 0.01`; current code calls these `parting_ids`, but this is NOT topological parting-line membership |
| Proxy/marginal draft | `draft_angle < marginal_threshold` (about `0.5°`); heuristic draft evidence only |
| Accessibility risk | Core-side orientation + at least one concave/re-entrant edge; actual undercut candidate signal |
| Actual parting line | Separate silhouette/topological result from `parting_line.py` |

A face may belong to more than one classification.

The old implementation incorrectly allowed the low-draft classification to dominate the undercut calculation. The new pipeline must not do that. The forensic analysis explicitly found that most Part1 proxy faces also satisfy the perpendicular-dot condition, making the old pool massively redundant. fileciteturn45file0L37-L52

---

# 5. Critical False-Positive Problem: Perpendicular-Dot Faces

The current Boolean formulation uses an access direction derived approximately as:

```python
signed = n_dot_d
access = -d if signed < 0 else d
```

When `|n·d| ≈ 0`, the face normal is nearly perpendicular to the pull direction. Either `+d` or `-d` is therefore essentially tangent to the face.

The current OCC sequence is:

```text
offset face
  ↓
sweep along access direction
  ↓
BRepAlgoAPI_Common(swept_volume, part)
  ↓
intersection volume
```

For these perpendicular-dot faces, the sweep can run alongside/through adjacent part material and produce non-zero volume that does **not** represent a genuine mold-withdrawal obstruction. This is an implementation-specific failure of the current access-direction formulation, not a universal statement about accessibility analysis. fileciteturn45file0L46-L52

### Required policy

For the current swept-face formulation, candidate construction should become conceptually:

```python
perpendicular_set = set(parting_ids)
check_ids = sorted((set(risk_face_ids) | optional_proxy_ids) - perpendicular_set)
```

But this blanket exclusion is permitted only after real-OCC verification on Part1 and Part3.

### Mandatory STOP condition

If a genuine re-entrant undercut is found on a perpendicular-dot face and no adjacent non-perpendicular risk face captures that obstruction, **do not implement blanket exclusion**. Redesign the candidate/access-direction formulation instead. The prior plan explicitly identifies this as the critical safety condition. fileciteturn44file1L84-L98

---

# 6. Candidate Pool: Fix Correctness and Performance at the Same Time

The old pool was approximately:

```text
proxy_underCut_ids ∪ risk_face_ids
```

For Part1 +Z this produced roughly `~230` candidates, while the Boolean budget was only `80`. Since only 80 could be checked, `boolean_validation_complete=False` was correctly produced. The resulting suitability gate then prevented early acceptance and caused the optimizer to fall through the full search. fileciteturn45file0L37-L44

The fix is **not** to redefine completeness.

The fix is to stop sending unreliable/redundant faces into expensive OCC validation.

Expected Part1 scale after the perpendicular-dot policy:

```text
~230 candidates → ~15–20 meaningful candidates
```

Then all candidates fit inside the `80` Boolean budget and completeness becomes true naturally.

---

# 7. Boolean Validation Semantics

For each candidate:

```text
access direction
→ face offset
→ prism/sweep
→ OCC intersection with part
→ volume measurement
→ semantic result
```

Possible results:

```text
confirmed
suspected
no_interference
failed
skipped
```

### Hard invariant

`boolean_validation_complete` is TRUE **iff every Boolean candidate has been checked or explicitly resolved**.

Examples:

```text
20 candidates, 20 checked → True
200 candidates, 80 checked → False
```

Never weaken this rule to make the optimizer faster. Performance comes from candidate reduction, selective Boolean refinement, and caching. The previous plan explicitly requires this semantic contract to remain unchanged. fileciteturn45file0L23-L31

---

# 8. Remove Redundant Expanded Validation

The previous R1-R5 path introduced a second, expanded validation configuration using approximately:

```text
boolean_check_all_core_side=True
final_direction_max_boolean_faces=150
```

This was expensive and also defeated direction-level caching because the scoring pass and final pass used different cache parameters. The result was repeated OCC work. fileciteturn45file0L41-L44

### Final architecture

Use one standard Boolean validation configuration for candidate scoring and final result application.

If the winning direction was already Boolean-refined using the standard parameters:

```text
candidate scoring
  ↓
Boolean result cached
  ↓
winning direction
  ↓
cache lookup
  ↓
CACHE HIT
  ↓
apply result
```

There should be no second expensive 150-face/core-side pass.

Remove dead `boolean_check_all_core_side` and `final_direction_max_boolean_faces` infrastructure only after searching all references and updating tests/mocks.

---

# 9. Direction Search

Use hierarchical search; do not brute-force an enormous sphere with expensive OCC operations.

## Stage 1 — Principal directions

```text
+X, -X, +Y, -Y, +Z, -Z
```

Run cheap metrics first.

A direction failing the 30% bad-draft gate is not necessarily globally bad; it simply cannot be accepted by the cheap Stage-1 gate.

## Stage 2 — Diagonals

Evaluate predefined diagonal candidates. Cheap-screen first, Boolean-refine only promising directions.

## Stage 3 — Spherical/fine search

Evaluate a bounded fine candidate set. Boolean-refine only the top candidates.

The previous architecture used 6 principals, 12 diagonals, then roughly 54 spherical/fine candidates with only a small number of Boolean refinements. Preserve that hierarchical philosophy. fileciteturn45file0L56-L86

---

# 10. Direction Scoring — Replace the Old Double-Counting Philosophy

Do NOT restore arbitrary terms such as:

```text
1000 × draft
+ 10000 × undercut
+ marginal draft penalty
```

The scoring model must separate evidence sources.

Recommended conceptual priority:

1. **validated confirmed-undercut risk**;
2. **validated accessibility risk**;
3. **draft quality**;
4. **small axis/stability preference as a tiebreaker**.

The exact numeric coefficients must be calibrated from actual candidate results, not selected simply to force Part1 to +Z.

### Critical rule

A marginal-draft face contributes to draft quality. It becomes undercut evidence only if the actual undercut path validates it.

Do not count the same face once as `bad draft`, again as `marginal draft`, and again as `undercut` merely because all three labels originated from the same low-angle geometry.

---

# 11. Why Part1 Should Select +Z

The desired result is not:

```text
if Part1: return +Z
```

That would be a fake fix.

The desired result is:

```text
+Z
→ low/no validated undercut obstruction
→ zero principal-axis preference penalty
→ complete Boolean validation
→ competitive draft/accessibility score
→ wins validated ranking
```

The previous forensic plan specifically expects +Z to win after candidate-pool correction even though its cheap bad-draft percentage is about `71.7%`. It also expects Part3 to remain free to choose an off-axis direction. fileciteturn45file1L121-L148

If the live numbers do not cause +Z to win, inspect the actual score breakdown before changing weights. The optimizer must explain why direction A beats direction B from measured data.

---

# 12. Direction Cache

Cache keys must represent the actual validation configuration.

After expanded validation is removed, dead fields such as `boolean_check_all_core_side` must not remain in the cache key.

Required behavior:

```text
Boolean-refine candidate
→ store result
→ later select candidate
→ lookup same parameters
→ cache hit
→ no duplicate OCC work
```

---

# 13. Performance Target

Performance must come from eliminating unnecessary OCC operations, not weakening validation.

Primary levers:

1. reduce candidate pool;
2. do cheap screening before Boolean validation;
3. Boolean-refine only top directions;
4. remove expanded duplicate validation;
5. reuse cached results;
6. avoid retrying equivalent geometry unnecessarily.

The forensic plan estimated roughly `~15–20` meaningful Part1 candidates after exclusion and approximately `~22s` worst-case search, with a target `<30s`. Treat those as targets to verify, not guarantees. fileciteturn45file1L193-L277

Never turn incomplete validation into complete validation to meet the time target.

---

# 14. Face-Level Diagnostics — Mandatory

Real OCC validation must expose enough information to prove correctness.

For every confirmed/suspected/no-interference face, expose:

```text
face_id
 draft_angle
normal
n·d
mold_side
risk
proxy
perp_dot
boolean_status
volume_mm3
```

At direction level expose:

```text
candidate_total
checked
failed
skipped
validation_complete
confirmed_count
suspected_count
no_interference_count
elapsed
```

At optimizer level expose:

```text
direction
stage
cheap score
Boolean score
confirmed undercut percentage
risk percentage
draft percentage
axis preference
final score
Boolean-refined
validation_complete
cache hit
```

This is essential because the system must answer **why** a direction won, not merely return a vector.

The prior plan requires this full diagnostic for Part1 +Z and Part3 selected direction. fileciteturn45file1L193-L355

---

# 15. Frontend Semantics

The UI must distinguish:

```text
confirmed undercut → red
suspected/inconclusive → amber
no_interference/accessibile → neutral gray
proxy/marginal draft → heuristic-only visualization
```

`no_interference` must not be rendered as an undercut-like green face. Keep its API data for diagnostics, but render it neutrally. No broader frontend redesign is required. fileciteturn45file1L152-L162

---

# 16. Tests

Required semantic coverage:

- perpendicular-dot face is excluded from the Boolean candidate pool under the validated policy;
- non-perpendicular accessibility-risk face is Boolean-tested;
- risk + perpendicular-dot follows the exclusion policy;
- no-interference renders as accessible/neutral;
- vertical/near-zero-draft wall is not automatically confirmed as undercut;
- candidate reduction naturally yields `boolean_validation_complete=True`;
- partial Boolean coverage remains `False`;
- final validation uses standard parameters;
- final validation reuses the cache;
- `confirmed ∩ suspected == ∅` remains true.

The previous plan defines the corresponding undercut semantic and direction-optimizer regression tests. fileciteturn45file1L166-L191

---

# 17. Real-OCC Acceptance Tests

## Part1(original).stp

Must verify:

```text
winning direction ≈ +Z
best_direction[2] > 0.9
boolean_validation_complete = True
validation_fallback = False
no perpendicular-dot face confirmed as undercut
confirmed undercuts are genuine re-entrant features
runtime < 30s
```

Also verify the draft metrics remain unchanged.

## Part3

Run the optimizer normally. Do NOT force +Z.

Must verify:

```text
normalized valid direction
no timeout/crash
meaningful Boolean validation
no false perpendicular-dot confirmed undercuts
no genuine undercut silently lost because of candidate exclusion
```

The prior acceptance criteria explicitly require Part1 +Z, runtime, validation completeness/fallback, no perpendicular false positives, unchanged draft behavior, and full Part3 diagnostics. fileciteturn45file1L363-L381

---

# 18. Implementation Order From the French Branch

```text
0. Git safety + baseline
   ↓
1. Measure the current French-branch behavior
   ↓
2. Protect draft_analyzer.py
   ↓
3. Separate draft evidence from undercut evidence
   ↓
4. Add face-level diagnostics
   ↓
5. Run UNMODIFIED Part1 +Z baseline
   ↓
6. Prove the perpendicular-dot Boolean false-positive mechanism
   ↓
7. Apply perpendicular-dot candidate exclusion for this formulation
   ↓
8. Remove expanded core-side validation
   ↓
9. Standardize Boolean parameters
   ↓
10. Make final result reuse the direction cache
   ↓
11. Remove dead expanded-validation configuration
   ↓
12. Replace old double-counting direction scoring
   ↓
13. Keep marginal draft as draft evidence, not confirmed undercut evidence
   ↓
14. Add/update semantic tests
   ↓
15. Run Part1 real-OCC regression
   ↓
16. Run Part3 real-OCC regression
   ↓
17. Validate frontend classification
   ↓
18. Update CHANGELOG / STATUS / TODO
```

The previous implementation sequence independently specifies instrumentation, an unmodified baseline, perpendicular-dot exclusion, expanded-validation removal, rendering correction, tests, real-OCC validation, and documentation. fileciteturn44file0L9-L36

Each stage should be measurable. Do not make a large multi-variable refactor and then guess which change fixed the result.

---

# 19. Files / Change Boundaries

Expected change surface:

```text
backend/geometry/undercut_detector.py
backend/geometry/direction_optimizer.py
backend/api/main.py
backend/config.py
config.yaml
tests/test_undercut_semantic_contract.py
tests/test_direction_optimizer.py
CHANGELOG.md
STATUS.md
TODO.md
```

Protected unless direct evidence requires otherwise:

```text
backend/geometry/draft_analyzer.py
backend/geometry/parting_line.py
backend/geometry/core_cavity.py
backend/geometry/side_core.py
backend/geometry/step_loader.py
backend/agent/
backend/report/
frontend/app.py
data/parts/
backend/models/geometry_models.py
```

The prior plan explicitly identifies these protected modules and fixtures. fileciteturn44file1L65-L78

---

# 20. Failure / Rollback Rules

### If Part3 loses a genuine undercut

Revert blanket perpendicular-dot exclusion and redesign the candidate/access-direction formulation. Do not hide the failure by labeling the face inaccessible.

### If candidate pool still exceeds 80

Measure why. Do not automatically increase the budget. Determine whether the risk heuristic is too broad or whether another redundant class is entering the pool.

### If optimizer still chooses the diagonal for Part1

Do not hard-code +Z. Print the score decomposition for +Z versus the winning diagonal and identify the exact term causing the ranking.

### If runtime is still too high

Profile Boolean operations and cache misses. Do not weaken `boolean_validation_complete`.

### If the backend appears to timeout

Distinguish:

```text
actual application exception
vs
frontend HTTP read timeout
vs
backend not running / connection refused
vs
request cancelled by Ctrl+C
```

Do not treat these as one bug.

---

# 21. Final Semantic Contract

The finished system should reason as follows:

```text
DRAFT
= "How well does this surface satisfy draft requirements?"

ACCESSIBILITY RISK
= "Does orientation + topology suggest a possible mold-trapping obstruction?"

BOOLEAN
= "Does the actual OCC withdrawal test demonstrate geometric interference?"

CONFIRMED UNDERCUT
= "Validated geometric obstruction, not merely low draft."

DIRECTION OPTIMIZATION
= "Which pull direction gives the best validated manufacturing outcome?"

PERFORMANCE
= "Avoid unnecessary candidates and duplicate OCC work; never weaken correctness."
```

---

# 22. Definition of Done

- [ ] Old `1000 × draft + 10000 × undercut + marginal-draft` double-counting architecture is gone.
- [ ] Draft analyzer remains unchanged/correct.
- [ ] Marginal draft is not treated as a confirmed undercut.
- [ ] Accessibility risk is based on directional orientation + re-entrant topology.
- [ ] Perpendicular-dot handling is validated against real Part1 and Part3 geometry.
- [ ] OCC Boolean validation is the authority for confirmed undercuts.
- [ ] `boolean_validation_complete` remains strict.
- [ ] Expanded duplicate validation is removed.
- [ ] Final winner reuses the Boolean cache.
- [ ] Part1 selects approximately +Z.
- [ ] Part1 has no perpendicular-dot false-positive confirmed undercuts.
- [ ] Any confirmed Part1 undercuts are geometrically genuine.
- [ ] Part1 optimization is <30s in the target environment.
- [ ] Part3 can legitimately select an off-axis direction.
- [ ] No genuine Part3 undercut is lost.
- [ ] `no_interference` is rendered neutrally.
- [ ] Semantic tests pass.
- [ ] Real-OCC Part1 and Part3 validation passes.
- [ ] CHANGELOG / STATUS / TODO reflect the actual implementation.

---

## Canonical Rule

**Never use a heuristic label as a substitute for geometric proof.**

Draft tells us that a face is difficult to draft. Accessibility tells us that geometry may trap a mold. OCC Boolean validation tells us whether the implemented withdrawal test actually finds interference. The optimizer must rank directions using these distinct pieces of evidence without double-counting them.

That separation is the foundation of the final pull-direction + undercut pipeline.
