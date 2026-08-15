# Forensic Implementation Plan: Pull-Direction Timeout + Undercut False Positives (v2)
/Users/abhisheklgowda/.claude/plans/dapper-discovering-sundae.md.
## Context

Two blockers remain before the final demo:

**A. Pull-direction optimization times out** (>240s, frontend HTTP timeout) on real Part1.stp geometry. The pre-R1-R5 baseline was ~13s. The R1-R5 semantic correction (2026-08-14) introduced expanded Boolean validation and a strict `boolean_validation_complete` gate that, combined, cause the hierarchical search to never early-exit and then perform expensive redundant work at the end.

**B. Undercut detection produces visual false positives** — an "extra green face" and potentially wrong confirmed-undercut faces. The root cause is twofold: (1) parting-line faces with near-zero n·d are Boolean-tested using an ambiguous sweep direction that always finds interference, and (2) `no_interference` faces are rendered with a distinct pale green color that confuses the viewer.

Draft analysis is working correctly and must not be touched.

### Design Constraints (from review)

1. **`boolean_validation_complete` retains its original meaning.** True ONLY when every candidate has been checked or explicitly resolved. Partial coverage (80/200) is NOT complete. Performance improvements must come from reducing the candidate pool, not from redefining completeness.

2. **`suitability_max_bad_draft_pct` stays at 30.0.** No threshold changes until correctness is established and benchmarked. Stage 2/3 fallthrough is acceptable.

3. **Real-OCC face-level diagnostic is mandatory.** Every confirmed/suspected/no-interference face on Part1 +Z must be reported with full geometric detail to validate against the Bosch reference.

4. **Parting-face exclusion must be geometrically justified**, not threshold-dependent. The geometric condition that makes near-zero n·d faces unsuitable for the current sweep formulation must be established and verified on both parts.

---

## 1. ROOT-CAUSE HYPOTHESES (ranked by confidence)

### Timeout — PROVEN

| # | Hypothesis | Confidence | Evidence |
|---|---|---|---|
| T1 | `boolean_validation_complete` is correctly False, but the candidate pool is bloated with geometrically unsuitable faces | **HIGH** | For Part1 at +Z: ALL proxy undercuts (draft < 0.5°, ~220 faces / 71.7%) have `|n·d| < sin(0.5°) = 0.00873`. These are also parting faces (`|n·d| ≤ 0.01`). The candidate pool = `proxy_undercut_ids ∪ risk_face_ids` = ~230 faces. With `max_boolean_faces=80`, only 80 are checked → `boolean_validation_complete=False` (correctly: 80/230). Suitability gate rejects → no early exit → full Stage 3 search. The fix is NOT to redefine completeness, but to exclude geometrically unsuitable candidates from the pool, reducing it to ~10-20 meaningful faces. |
| T2 | Expanded validation (`boolean_check_all_core_side=True`, 150 faces) runs redundantly | **HIGH** | Three call sites: Stage 1 exit (`direction_optimizer.py:1157-1165`), Stage 2 exit (`1230-1238`), Stage 3 end (`1368-1376`). Direction-level cache key includes `max_boolean_faces` and `boolean_check_all_core_side` (`direction_optimizer.py:55-62`), so the 80-face result from candidate scoring NEVER satisfies the 150-face expanded request → guaranteed direction-cache miss → full `detect_undercuts()` re-run with ~70-120 NEW core-side faces at 0.1-2s each → 10-60s per expanded call. |
| T3 | Stage 1 cheap suitability gate rejects +Z for Part1 | **PROVEN** | Part1 at +Z: `bad_pct = 71.7% > 30.0%`. No principal direction passes. This is PRE-EXISTING (not R1-R5), but R1-R5 made it worse because Stage 2/3 now also fail (T1). With the pool reduction (Fix D), Stage 2 or 3 will find the right direction with `boolean_validation_complete=True`, just not at Stage 1. Threshold stays at 30.0 per review directive. |
| T4 | Total Boolean ops are proportional to bloated candidate pool × retry multipliers | **MEDIUM** | Each face gets up to 3 retry attempts (multipliers [1.0, 5.0, 25.0]). With 80+ face budget × 3 retries × 0.1-2s each = 24-480s per direction. Pool reduction to ~20 faces → 60s max per direction. |

### False Positives — PROVEN

| # | Hypothesis | Confidence | Evidence |
|---|---|---|---|
| U1 | Parting-line proxy undercuts produce false-positive Boolean confirmations | **HIGH** | Geometric proof in Section 4 below. Summary: the Bassi sweep test requires a well-defined withdrawal direction. For faces with `|n·d| ≈ 0`, the access direction is perpendicular to the face surface. The swept prism passes through the part solid itself, which trivially produces non-zero intersection volume. This is NOT testing withdrawal obstruction — it is testing whether part material exists in front of/behind the face, which is always true for any face on a closed solid. |
| U2 | `no_interference` faces rendered with distinct green color | **PROVEN** | `main.py:114-118`: `"no_interference"` style = RGB(180,230,180). `_undercut_mesh_visual_payload` at line 416-417 assigns this style. These are NOT undercuts but are visually prominent. |
| U3 | Expanded validation adds many `no_interference` faces that weren't in prior runs | **HIGH** | `boolean_check_all_core_side=True` adds ALL core-side faces to the candidate pool. Well-drafted core-side faces with all-convex edges return volume=0. Before R1-R5, these were never tested and had no visual distinction. |

---

## 2. CURRENT-CODE TRACE

### Direction Optimization Call Chain

```
API: /parts/{filename}/direction  (main.py:771)
  → optimize_mold_direction()     (direction_optimizer.py:1022)
    → Stage 1: 6 principals, cheap-score each via _score_direction_candidate()
      → precompute_directional_metrics()  (draft_analyzer.py:620)
      → analyze_draft(mutate=False)       (draft_analyzer.py)
      → detect_undercuts(boolean_refine=False)  (undercut_detector.py:3229)
      → _is_direction_suitable_cheap()    (direction_optimizer.py:931)
      → IF cheap-suitable: _boolean_refine_candidates()
        → _cached_detect_boolean_undercuts(max_faces=80)
          → detect_undercuts(boolean_refine=True, max_faces=80)
            → _boolean_refine_undercuts(candidate_ids[:80])
              → PER FACE: _swept_face_interference_volume()
                → _face_access_direction()  ← PROBLEMATIC for parting faces
                → BRepBuilderAPI_Transform (offset)
                → BRepPrimAPI_MakePrism (sweep)
                → BRepAlgoAPI_Common (intersect with part)
                → GProp volume measurement
        → _is_direction_suitable_boolean()  (direction_optimizer.py:958)
          → requires boolean_validation_complete == True  ← correct, but pool is bloated
      → IF acceptable: EARLY EXIT with expanded validation  ← REDUNDANT
    → Stage 2: 12 diagonals, same pattern
    → Stage 3: 54 spherical + fine search
      → top ~5 Boolean-refined
      → select best validated
      → expanded final validation  ← EXPENSIVE
```

### Key Line Numbers

| Function | File | Line | Role |
|---|---|---|---|
| `optimize_mold_direction` | `direction_optimizer.py` | 1022 | Entry point |
| `_is_direction_suitable_cheap` | `direction_optimizer.py` | 931 | Cheap screen (bad_pct + risk_pct) |
| `_is_direction_suitable_boolean` | `direction_optimizer.py` | 958 | Boolean gate (requires validation_complete) |
| `_cached_detect_boolean_undercuts` | `direction_optimizer.py` | 400 | Direction-level caching |
| `_lookup_direction_cache` | `direction_optimizer.py` | 337 | Cache reuse logic (rejects key mismatch) |
| `DirectionUndercutCacheKey` | `direction_optimizer.py` | 47 | Cache key (includes max_faces, all_core_side) |
| `detect_undercuts` | `undercut_detector.py` | 3229 | Main undercut detection |
| `check_ids` construction | `undercut_detector.py` | 3378-3397 | Boolean candidate pool |
| `_boolean_refine_undercuts` | `undercut_detector.py` | 2917 | Face-level Boolean loop |
| `[:max_faces]` truncation | `undercut_detector.py` | 2969 | Budget enforcement |
| `boolean_validation_complete` | `undercut_detector.py` | 3446-3448 | Completeness check — PRESERVED |
| `_face_access_direction` | `undercut_detector.py` | 2217 | Access direction — PROBLEMATIC for parting |
| `_swept_face_interference_volume` | `undercut_detector.py` | 2766 | OCC Boolean geometry |
| Composite rule | `undercut_detector.py` | 3432-3448 | Confirmed/suspected/no-interference split |
| `_undercut_mesh_visual_payload` | `main.py` | 366 | Face-to-color mapping |
| `no_interference` style | `main.py` | 114-118 | Pale green RGB(180,230,180) |

---

## 3. EXPERIMENTAL / FORENSIC PHASE

### Phase 0: Instrumentation + face-level diagnostic

Add `logging.info()` calls at strategic points, AND produce a mandatory face-level diagnostic report for Part1.

**File: `direction_optimizer.py`**

1. After each stage's cheap screening, log:
   - `stage={N}, cheap_suitable_count={len(suitable)}, directions_scored={len(scored)}`

2. In `_boolean_refine_candidates` (line 1089), log per-candidate:
   - `direction={label}, boolean_candidate_total={result.boolean_candidate_count}, checked={len(checked)}, validation_complete={result.boolean_validation_complete}, suitability={pass/fail}`

3. At function exit (lines 1174, 1247, 1393), log:
   - `stage_reached={N}, elapsed_s={total}, best={label}, fallback={validation_fallback}`

**File: `undercut_detector.py`**

4. At line 3398 (after `boolean_candidate_total`), log:
   - `candidate_pool={N}, proxy_count={len(proxy)}, risk_count={len(risk)}, parting_excluded={N}, max_faces={max}, budget_limited={pool > max}`

5. At line 3446 (validation_complete assignment), log:
   - `checked={len(checked)}, skipped={len(skipped)}, candidate_total={N}, validation_complete={result}`

**Mandatory face-level diagnostic (new function):**

Add a `_dump_face_diagnostic()` helper that, when called for Part1 +Z, prints a table for every face in the confirmed/suspected/no-interference sets:

```
face_id | draft_angle | normal        | n·d     | mold_side | risk | proxy | parting | boolean_status | volume_mm3
--------|-------------|---------------|---------|-----------|------|-------|---------|----------------|----------
42      | 0.12°       | (0.99,0.02,0) | 0.002   | parting   | no   | yes   | yes     | confirmed      | 0.0031
117     | 32.1°       | (-0.5,-0.8,0) | -0.846  | core      | yes  | no    | no      | confirmed      | 12.41
203     | 0.45°       | (0.01,1.0,0)  | 0.008   | parting   | yes  | yes   | yes     | no_interf      | 0.0
```

This runs once during Phase 0 validation (real OCC, Part1 +Z) to verify which faces are being classified and whether they match expected Bosch geometry.

### Distinguishing evidence

- If T1+Fix D are correct: after excluding parting faces, `boolean_candidate_total` drops to ~10-20, well under 80 budget → `boolean_validation_complete=True` naturally
- If U1 is correct: the diagnostic will show parting-line faces (|n·d| < 0.01) with non-zero Boolean volume being falsely confirmed — these faces will disappear after Fix D
- Part3 diagnostic: same format, verifying that non-principal directions still produce correct undercut classifications

---

## 4. UNDERCUT FIX — GEOMETRIC JUSTIFICATION FOR PARTING-FACE EXCLUSION

### The geometric argument (not a threshold hack)

The Bassi-style swept-face interference test (`_swept_face_interference_volume`, line 2766) works as follows:

1. Determine **access direction**: the direction the mold half withdraws from this face
2. **Offset** the face slightly along the access direction (to exclude self-contact)
3. **Sweep** the offset face along the access direction for 2× the part diagonal
4. **Intersect** the swept prism with the part solid
5. Non-zero volume = physical obstruction to mold withdrawal

**The test has a geometric precondition:** the access direction must be approximately ALIGNED WITH the face normal. Specifically, the swept prism must extend AWAY from the part material behind the face. When this precondition holds, the intersection detects re-entrant pockets/hooks that obstruct withdrawal.

**The precondition fails for parting-line faces.** Here is why:

For a face with outward normal `n` and pull direction `d`:
- `_face_access_direction` returns `+d` when `n·d ≥ 0`, and `-d` when `n·d < 0`
- For a parting-line face: `|n·d| ≈ 0`, so `n ⊥ d` (normal perpendicular to pull)
- The access direction is `±d` — which is perpendicular to the face normal
- The swept prism therefore extends **along the face surface**, not away from it
- The prism passes through the **part interior** (the solid material behind the face)
- `BRepAlgoAPI_Common(part.occ_shape, swept)` finds the intersection of the part solid with a prism that runs through it → **non-zero volume is guaranteed** for any face on a closed solid

This is not testing withdrawal obstruction. It is testing whether part material exists adjacent to the face along the pull axis, which is trivially true for any interior face of a solid part.

**The distinguishing geometric condition:**

A face is unsuitable for the Bassi sweep test when its normal is nearly perpendicular to the pull direction: `|n·d| ≤ parting_dot_threshold` (currently 0.01).

This is NOT an arbitrary epsilon. It is the SAME threshold already used throughout the pipeline to classify parting-region faces (line 3285: `parting_dot_threshold = 0.01`, used at line 3302). Faces meeting this criterion are geometrically at the parting line — the boundary between cavity and core mold halves. Their mold-side assignment is ambiguous, their access direction is perpendicular to their surface, and the sweep test produces meaningless results.

**What about genuine undercuts at the parting line?**

A re-entrant feature (hook, snap-fit, lateral slot) at the parting line consists of multiple faces:
- The **hook/slot walls**: these extend AWAY from the parting plane into the core side, so their normals have significant components along `-d` (i.e., `n·d << -0.01`). They are core-side faces and will be caught by `_compute_accessibility_risk()` (core-side + concave edge → risk face → Boolean-tested).
- The **hook/slot tip**: if it points laterally, its normal is perpendicular to `d`, placing it in the parting region. But the tip alone is not the undercut — the WALLS are what trap the mold. The walls ARE tested.

**Verification plan:**
1. Run Part1 +Z with parting exclusion → inspect confirmed undercuts → verify they are genuine re-entrant features (core-side walls with concave edges), not vertical walls at the parting line
2. Run Part3 with its optimal direction → verify same behavior
3. If any genuine parting-line undercut is found that is NOT covered by an adjacent core-side risk face, that case must be analyzed and the exclusion condition refined

### Fix D: Exclude parting-line faces from Boolean candidate pool

**File: `backend/geometry/undercut_detector.py`**

**Change at line 3383:**

Current:
```python
check_ids = sorted(set(proxy_undercut_ids) | set(risk_face_ids))
```

New:
```python
# Parting-line faces are geometrically unsuitable for the Bassi sweep test:
# their normals are perpendicular to pull, making the access direction
# perpendicular to the face surface. The swept prism passes through the
# part solid, producing false-positive interference. See Section 4 of
# the implementation plan for the full geometric argument.
parting_set = set(parting_ids)
check_ids = sorted((set(proxy_undercut_ids) | set(risk_face_ids)) - parting_set)
```

**Impact on `boolean_validation_complete`:**

Before fix: `boolean_candidate_total ≈ 230` (Part1 +Z), `max_faces=80` → `checked ≤ 80 < 230` → `validation_complete=False`

After fix: `boolean_candidate_total ≈ 15-20` (only risk faces), `max_faces=80` → `checked ≤ 20 < 80` → all candidates checked → `validation_complete=True`

The semantic meaning of `boolean_validation_complete` is preserved: every candidate in the (now geometrically meaningful) pool has been checked. The pool is smaller because geometrically unsuitable candidates have been removed, not because the definition of "complete" was weakened.

### Fix E: Suppress `no_interference` rendering

**File: `backend/api/main.py`**

**Change at line 416-417 in `_undercut_mesh_visual_payload()`:**

Current:
```python
elif face_id in no_interference_ids:
    style_key = "no_interference"
```

New:
```python
elif face_id in no_interference_ids:
    style_key = "accessible"
```

The data remains in the API response (`boolean_no_interference_face_ids`) for programmatic access. The face just renders as neutral gray instead of pale green.

---

## 5. PERFORMANCE FIX

### Primary fix: candidate pool reduction (Fix D) solves both correctness AND performance

With parting faces excluded from the Boolean candidate pool:

| Metric | Before Fix D | After Fix D |
|---|---|---|
| Candidate pool (Part1 +Z) | ~230 (proxy+risk) | ~15-20 (risk only) |
| Budget-limited? | Yes (230 > 80) | No (20 < 80) |
| `boolean_validation_complete` | False | True |
| Suitability gate | Always rejects | Can accept |
| Boolean ops per direction | 80 (budget-capped) | ~15-20 (all candidates) |
| Time per direction | ~8-16s | ~2-4s |

### Secondary fix: Remove expanded validation (Fix B+C)

**File: `backend/geometry/direction_optimizer.py`**

**Change at lines 1157-1165 (Stage 1 early exit), 1230-1238 (Stage 2), 1368-1376 (Stage 3):**

Replace all three expanded validation calls:
```python
optimal_undercuts, cache_hit = _cached_detect_boolean_undercuts(
    ...
    max_boolean_faces=cfg.final_direction_max_boolean_faces,  # 150
    boolean_check_all_core_side=True,
)
```

With standard-parameter calls:
```python
optimal_undercuts, cache_hit = _cached_detect_boolean_undercuts(
    ...
    max_boolean_faces=cfg.boolean_refine_max_faces,  # 80
)
```

**Effect:** The final pass uses the SAME parameters as the per-candidate scoring pass. Since the winning direction was already Boolean-refined during candidate evaluation with identical parameters, `_lookup_direction_cache()` finds a matching entry → **cache HIT** → zero additional Boolean ops.

When `mutate=True` and a cache hit occurs, `_apply_undercut_result_to_part()` (line 363) applies face overlays from the cached result. This is correct and fast.

### Tertiary fix: Remove `boolean_check_all_core_side` infrastructure

Since the expanded validation is removed, the `boolean_check_all_core_side` parameter and `final_direction_max_boolean_faces` config are dead code.

**Files:**
- `undercut_detector.py`: Remove `boolean_check_all_core_side` parameter from `detect_undercuts()` (line 3235) and the associated `check_ids` expansion block (lines 3385-3397)
- `direction_optimizer.py`: Remove `boolean_check_all_core_side` from `DirectionUndercutCacheKey` (line 55-62), `_direction_cache_key()` (line 303-321), `_lookup_direction_cache()` (line 337-361), `_cached_detect_boolean_undercuts()` (line 400-439)
- `config.py`: Remove `final_direction_max_boolean_faces` from `DirectionSearchSettings`
- `config.yaml`: Remove `final_direction_max_boolean_faces: 150` (line 71)

### Expected performance after all fixes

With `suitability_max_bad_draft_pct` unchanged at 30.0:

- Stage 1: +Z has `bad_pct=71.7% > 30.0%` → all 6 principals fail cheap screen → NO early exit
- Stage 2: some diagonals may pass cheap screen → Boolean-refine with ~15-20 candidates → `validation_complete=True` → possible early exit
- Stage 3 (if needed): full search, ~5 Boolean refinements with ~15-20 candidates each
- Final pass: cache hit (zero cost)

| Phase | Boolean-refined dirs | Candidates per dir | OCC ops | Time est. |
|---|---|---|---|---|
| Initial +Z | 1 | ~15 risk faces | ~15 | ~2s |
| Stage 1 cheap | 6 | 0 (boolean_refine=False) | 0 | ~0.5s |
| Stage 2 cheap | 12 | 0 | 0 | ~1s |
| Stage 2 Boolean | ~4 | ~15 each | ~60 | ~8s |
| Stage 3 (if needed) | ~5 | ~15 each | ~75 | ~10s |
| Final pass | 1 | **cache hit** | 0 | ~0s |
| **Total (worst case)** | | | **~150** | **~22s** |

Pre-R1-R5 baseline was ~13s. Target: < 30s. This is achievable.

---

## 6. DIRECTION-SELECTION FIX

### How +Z correctly wins Part1

Even without Stage 1 early exit (threshold stays at 30.0):

1. Stage 2/3 scores +Z and many other directions cheaply
2. +Z gets Boolean-refined: ~15 risk faces checked, few/no confirmed undercuts → low score
3. +Z has `axis_preference` penalty = 0 (perfect principal alignment, weight 0.25)
4. The scoring formula (`direction_optimizer.py:598-673`) favors +Z because:
   - Low `confirmed_undercut_pct` (few Boolean-confirmed faces)
   - Zero axis preference penalty
   - Bad draft contribution is high but CONSISTENT across most directions for Part1 (the part has many walls regardless of direction)
5. +Z wins as best validated direction
6. `validation_fallback=False` because +Z has `boolean_refined=True` and `boolean_validation_complete=True`

### How Part3 handles non-principal directions

Part3 (414 faces, 68mm diagonal) has different geometry. Its optimal direction may be off-axis:
- All three stages still execute when no early exit occurs
- The scoring formula applies identically to all directions
- Boolean candidate pool (risk faces only) varies per direction based on geometry
- The `axis_preference` penalty (weight 0.25) provides only a tiebreaker
- Part3 freely selects diagonal or spherical directions based on scoring

### Verification

Both parts must be validated with the face-level diagnostic (Phase 0) before declaring correctness.

---

## 7. FRONTEND FIX

### Only change: suppress `no_interference` green rendering (Fix E in Section 4)

No other frontend changes needed. The confirmed/suspected distinction is already correctly wired:
- `critical_boolean_confirmed` = red (RGB 255,50,50) — confirmed undercuts
- `suspected_undercut` = amber (RGB 255,200,80) — inconclusive Boolean
- `no_interference` → changed to `accessible` = neutral gray (Fix E)
- `proxy_undercut` = light orange (RGB 255,230,150) — heuristic evidence only

The legend data and API response fields remain unchanged.

---

## 8. TEST PLAN

### New tests

**File: `tests/test_undercut_semantic_contract.py`** (append)

| Test | Scenario | Expected |
|---|---|---|
| `test_parting_faces_excluded_from_boolean_candidates` | Face with `|n·d|=0.005`, draft=0.3° (proxy+parting) | NOT in `boolean_checked_face_ids` |
| `test_risk_face_not_parting_is_boolean_tested` | Face with `n·d=-0.5`, concave edge (risk, NOT parting) | IN `boolean_checked_face_ids` |
| `test_parting_risk_face_excluded_if_also_parting` | Face with `n·d=-0.005` (parting + risk) | NOT in `boolean_checked_face_ids` (parting takes precedence) |
| `test_no_interference_rendered_as_accessible` | API-level: `no_interference` face in mesh payload | `undercut_classification == "accessible"` |
| `test_vertical_wall_not_confirmed_undercut` | Vertical wall face (n·d≈0, draft≈0°) with Boolean | NOT in `undercut_face_ids`; IS in `suspected_undercut_face_ids` |
| `test_pool_reduction_enables_validation_complete` | 20 candidates, max_faces=80, all 20 checked | `boolean_validation_complete=True` (naturally, not redefined) |

**File: `tests/test_direction_optimizer.py`** (append/update)

| Test | Scenario | Expected |
|---|---|---|
| `test_final_pass_uses_standard_params` | Mock optimizer to select a direction | Final `_cached_detect_boolean_undercuts` uses `max_faces=80`, NOT 150; no `boolean_check_all_core_side` |
| `test_final_pass_is_cache_hit` | Direction already Boolean-refined | Final call returns `cache_hit=True` |

### Existing test updates

- `test_direction_optimizer.py`: Remove `boolean_check_all_core_side` kwarg from mock functions (parameter removed)
- `test_undercut_semantic_contract.py`: Verify T6 (budget exhaustion) still correctly reports `boolean_validation_complete=False` when checked < candidate_total — no semantic change to this test

### Real OCC regression commands

```bash
# Part1 face-level diagnostic (Phase 0 — MANDATORY before declaring correctness)
python -c "
import time, json
from backend.geometry.step_loader import load_step_cached
from backend.geometry.undercut_detector import detect_undercuts
from backend.geometry.draft_analyzer import precompute_directional_metrics

part = load_step_cached('data/parts/Part1.stp')
d = (0.0, 0.0, 1.0)
metrics = precompute_directional_metrics(part, d)
t0 = time.perf_counter()
r = detect_undercuts(part, d, mutate=False, boolean_refine=True, max_boolean_faces=80)
elapsed = time.perf_counter() - t0

print(f'elapsed={elapsed:.1f}s confirmed={len(r.undercut_face_ids)} suspected={len(r.suspected_undercut_face_ids)} no_interf={len(r.boolean_no_interference_face_ids)} validation_complete={r.boolean_validation_complete}')
print(f'candidate_total={r.boolean_candidate_count} checked={len(r.boolean_checked_face_ids)} failed={len(r.boolean_failed_face_ids)} skipped={len(r.boolean_skipped_face_ids)}')
print()
print('=== CONFIRMED UNDERCUTS ===')
for fid in r.undercut_face_ids:
    f = part.get_face(fid)
    m = metrics.get(fid)
    bm = r.boolean_metrics_by_face.get(fid) if hasattr(r, 'boolean_metrics_by_face') else None
    vol = bm.volume_mm3 if bm else '?'
    print(f'  face={fid:3d} draft={m.draft_angle_deg:.2f} n=({f.normal[0]:.3f},{f.normal[1]:.3f},{f.normal[2]:.3f}) nd={m.signed_dot:.4f} side={m.mold_side} risk={fid in r.accessibility_risk_face_ids} proxy={fid in set([])} vol={vol}')
print()
print('=== SUSPECTED UNDERCUTS ===')
for fid in r.suspected_undercut_face_ids:
    f = part.get_face(fid)
    m = metrics.get(fid)
    print(f'  face={fid:3d} draft={m.draft_angle_deg:.2f} n=({f.normal[0]:.3f},{f.normal[1]:.3f},{f.normal[2]:.3f}) nd={m.signed_dot:.4f} side={m.mold_side} risk={fid in r.accessibility_risk_face_ids}')
print()
print('=== NO INTERFERENCE ===')
for fid in r.boolean_no_interference_face_ids:
    f = part.get_face(fid)
    m = metrics.get(fid)
    print(f'  face={fid:3d} draft={m.draft_angle_deg:.2f} n=({f.normal[0]:.3f},{f.normal[1]:.3f},{f.normal[2]:.3f}) nd={m.signed_dot:.4f} side={m.mold_side} risk={fid in r.accessibility_risk_face_ids}')
"

# Part1 direction optimization regression
python -c "
from backend.geometry.step_loader import load_step_cached
from backend.geometry.direction_optimizer import optimize_mold_direction
import time
part = load_step_cached('data/parts/Part1.stp')
t0 = time.perf_counter()
r = optimize_mold_direction(part)
elapsed = time.perf_counter() - t0
print(f'Part1: {elapsed:.1f}s stage={r.search_stage_reached} dir=({r.best_direction[0]:.3f},{r.best_direction[1]:.3f},{r.best_direction[2]:.3f}) score={r.best_score:.4f}')
print(f'  confirmed={len(r.optimal_undercuts.undercut_face_ids)} suspected={len(r.optimal_undercuts.suspected_undercut_face_ids)} no_interf={len(r.optimal_undercuts.boolean_no_interference_face_ids)}')
print(f'  validation_complete={r.optimal_undercuts.boolean_validation_complete} fallback={r.validation_fallback}')
assert r.best_direction[2] > 0.9, f'+Z expected, got {r.best_direction}'
assert r.validation_fallback == False
assert elapsed < 30, f'Performance regression: {elapsed:.1f}s'
"

# Part3 regression
python -c "
from backend.geometry.step_loader import load_step_cached
from backend.geometry.direction_optimizer import optimize_mold_direction
import time
part = load_step_cached('data/parts/Part3.stp')
t0 = time.perf_counter()
r = optimize_mold_direction(part)
elapsed = time.perf_counter() - t0
print(f'Part3: {elapsed:.1f}s stage={r.search_stage_reached} dir=({r.best_direction[0]:.3f},{r.best_direction[1]:.3f},{r.best_direction[2]:.3f}) score={r.best_score:.4f}')
print(f'  confirmed={len(r.optimal_undercuts.undercut_face_ids)} suspected={len(r.optimal_undercuts.suspected_undercut_face_ids)}')
print(f'  validation_complete={r.optimal_undercuts.boolean_validation_complete} fallback={r.validation_fallback}')
assert elapsed < 60, f'Performance regression: {elapsed:.1f}s'
"

# Full test suite
pytest tests/ -v --tb=short
```

---

## 9. ACCEPTANCE CRITERIA

| # | Criterion | Measurement | Pass |
|---|---|---|---|
| AC1 | Part1 direction ≈ +Z | `best_direction[2] > 0.9` | Yes/No |
| AC2 | Part1 runtime < 30s | Wall-clock `optimize_mold_direction()` in Docker/conda | Yes/No |
| AC3 | Part1 `validation_fallback == False` | Result field | Yes/No |
| AC4 | Part1 `boolean_validation_complete == True` | Result field (via pool reduction, NOT redefinition) | Yes/No |
| AC5 | No extra green faces in Part1 visualization | `no_interference` faces rendered as neutral/accessible | Yes/No |
| AC6 | Vertical walls NOT confirmed undercuts | Face-level diagnostic: no face with `|n·d| < 0.01` in `undercut_face_ids` | Yes/No |
| AC7 | Confirmed undercuts are genuine re-entrant features | Face-level diagnostic: confirmed faces have `|n·d| > 0.01` and concave edges | Yes/No |
| AC8 | Part3 produces a valid direction | No timeout, no crash, direction norm ≈ 1.0 | Yes/No |
| AC9 | Draft analysis unchanged | `draft.bad_pct`, `draft.good_pct` identical pre/post | Yes/No |
| AC10 | All existing tests pass | `pytest tests/ -v` | Yes/No |
| AC11 | `confirmed ∩ suspected == ∅` | R1-R5 invariant preserved | Yes/No |
| AC12 | `boolean_validation_complete` semantics unchanged | True IFF all candidates checked/resolved; partial coverage is False | Yes/No |
| AC13 | `suitability_max_bad_draft_pct` unchanged | Config value remains 30.0 | Yes/No |
| AC14 | Face-level diagnostic produced for Part1 +Z | Report with confirmed/suspected/no-interference face details | Yes/No |

---

## 10. FILES TO CHANGE

| File | Changes | Why |
|---|---|---|
| `backend/geometry/undercut_detector.py` | (1) Line 3383: exclude `parting_ids` from `check_ids` with geometric justification comment. (2) Lines 3385-3397: remove `boolean_check_all_core_side` block. (3) Line 3235: remove `boolean_check_all_core_side` parameter. (4) Add instrumentation logging at lines 3398, 3446. | Fixes U1 (false positives), reduces candidate pool (fixes T1 indirectly) |
| `backend/geometry/direction_optimizer.py` | (1) Lines 1157-1165, 1230-1238, 1368-1376: replace expanded validation with standard params. (2) Remove `boolean_check_all_core_side` from `DirectionUndercutCacheKey`, `_direction_cache_key()`, `_lookup_direction_cache()`, `_cached_detect_boolean_undercuts()`. (3) Add instrumentation logging. | Fixes T2 (redundant expanded validation), simplifies cache |
| `backend/api/main.py` | Line 416-417: render `no_interference` as `accessible`. | Fixes U2 (extra green face) |
| `backend/config.py` | Remove `final_direction_max_boolean_faces` from `DirectionSearchSettings`. | Dead config cleanup |
| `config.yaml` | Remove `final_direction_max_boolean_faces: 150` (line 71). | Dead config cleanup |
| `tests/test_undercut_semantic_contract.py` | Add 6 new tests (see Test Plan section). | Regression coverage for parting exclusion and rendering |
| `tests/test_direction_optimizer.py` | Remove `boolean_check_all_core_side` from mocks. Add 2 new tests. | Interface cleanup + regression |
| `CHANGELOG.md` | Append entry documenting all changes with geometric rationale. | Project tracking |
| `STATUS.md` | Update undercut detector and direction optimizer rows. | Project tracking |
| `TODO.md` | Mark completed items, note real-OCC validation results. | Project tracking |

---

## 11. FILES NOT TO CHANGE

| File/Module | Reason |
|---|---|
| `backend/geometry/parting_line.py` | Unrelated pipeline |
| `backend/geometry/core_cavity.py` | Unrelated pipeline |
| `backend/geometry/side_core.py` | Unrelated pipeline |
| `backend/geometry/draft_analyzer.py` | Working correctly, explicitly protected |
| `backend/geometry/step_loader.py` | Stable, no changes needed |
| `backend/agent/` | Unrelated pipeline |
| `backend/report/` | Unrelated pipeline |
| `frontend/app.py` | No frontend changes needed (backend fix sufficient) |
| `data/parts/` | Read-only fixtures, never modify |
| `backend/models/geometry_models.py` | R1-R5 fields preserved; no new fields needed |

---

## 12. RISK / ROLLBACK PLAN

### Risk 1: Part3 loses genuine undercuts after parting exclusion

**Risk:** Part3's optimal direction may create genuine undercuts at parting-line faces that would be excluded by Fix D.

**Mitigation:** The face-level diagnostic (Phase 0) must be run on Part3 to verify. If a genuine undercut is found at a parting face that is NOT covered by an adjacent core-side risk face, the exclusion condition must be refined. The geometric argument (Section 4) predicts this won't happen: re-entrant features always have core-side walls (|n·d| >> 0.01) that are caught by accessibility risk.

**Rollback:** Revert line 3383 to original `check_ids = sorted(set(proxy_undercut_ids) | set(risk_face_ids))`.

### Risk 2: Candidate pool still exceeds budget after parting exclusion

**Risk:** For some Part3 direction, `risk_face_ids` alone may exceed 80 → `boolean_validation_complete=False` → suitability gate still rejects.

**Mitigation:** Monitor `boolean_candidate_total` in instrumentation. If risk faces exceed 80 for Part3, the budget (`boolean_refine_max_faces`) may need to be raised for that part, OR the risk heuristic may need tightening. This would be a separate, evidence-driven follow-up.

**Rollback:** N/A — `boolean_validation_complete` semantics are preserved; the gate correctly reports incomplete validation when budget is exceeded.

### Risk 3: `boolean_check_all_core_side` removal breaks tests

**Risk:** Existing tests may reference the removed parameter.

**Mitigation:** Search for all `boolean_check_all_core_side` references before removal. Known locations: `test_direction_optimizer.py` (2 mock functions), `test_undercut_semantic_contract.py` (possible references). Update mocks to remove the parameter.

**Rollback:** Keep the parameter but hardcode to `False` everywhere (effectively disabled).

### Git safety

All changes are on the `feat/pull-direction` branch. Main branch is untouched. Each phase produces an independently testable commit. If any phase causes regression, that commit can be reverted without losing the others.

---

## Implementation Order

```
Phase 0: Instrumentation + face-level diagnostic function (additive, no control flow changes)
   ↓
Phase 1: Exclude parting faces from Boolean candidates (Fix D — core correctness fix)
   ↓
Phase 2: Remove expanded validation / boolean_check_all_core_side (Fix B+C — performance)
   ↓
Phase 3: Suppress no_interference rendering (Fix E — visual fix)
   ↓
Phase 4: Tests (new + updated, run full mock-based suite)
   ↓
Phase 5: Real OCC validation with face-level diagnostic (Part1 + Part3 in Docker/conda)
   ↓
Phase 6: Documentation (CHANGELOG, STATUS, TODO)
```

Each phase is independently testable. Phase 5 is the decisive validation gate — correctness is not declared until the face-level diagnostic confirms that confirmed undercuts are genuine re-entrant features and no vertical walls appear as confirmed undercuts.
