# DfM Agent — Current Pipeline Master Document

**Author:** Forensic audit generated 2026-08-14  
**Purpose:** Technically precise reference for the entire pipeline as it actually executes, derived from source files. Sufficient for another engineer to reconstruct the system without opening source files.  
**Scope:** Level 1 geometry pipeline only. AI agent layer (`backend/agent/`) exists but is out of scope for this document.

---

## Section 1: End-to-End Pipeline Execution Trace

### Entry Points

Every analysis starts at one of three FastAPI endpoints in `backend/api/main.py`. Each endpoint is fully self-contained and stateless:

```
GET /parts/{filename}/draft          → analyze_draft()         (line ~624)
GET /parts/{filename}/undercuts      → detect_undercuts()       (line ~690)
GET /parts/{filename}/direction      → optimize_mold_direction() (line ~751)
GET /parts/{filename}/parting-line   → detect_parting_line_candidates() 
GET /parts/{filename}/core-cavity    → classify_core_cavity()
```

### Execution Sequence (direction endpoint, the heaviest path)

```
HTTP GET /parts/Part1.stp/direction
  │
  ▼
main.py:751 – path-traversal guard: filename validated against data/parts/ contents
  │
  ▼
step_loader.load_step_cached(path)                    [backend/geometry/step_loader.py]
  │  LRU cache (maxsize=8). If miss: load_step(path) → PartGeometry.
  │  Returns _clone_pristine_part(cached) — a shallow copy for safe mutation.
  │
  ▼
PartGeometry object:
  - faces: list[FaceData]    (face_id 0..N-1, stable across reloads)
  - edges: list[EdgeData]    (edge_id 0..M-1)
  - face_adjacency: dict[int → list[int]]
  - face_to_edges:  dict[int → list[int]]
  - edge_to_faces:  dict[int → list[int]]
  - occ_shape: TopoDS_Shape  (live OCC handle — never serialized)
  - bounding_box: BoundingBox
  │
  ▼
optimize_mold_direction(part, mutate=True)            [backend/geometry/direction_optimizer.py:1003]
  │
  ├── Stage 1: 6 principal axes                       [line ~1090]
  │     for each direction:
  │       precompute_directional_metrics(part, d)     [draft_analyzer.py]
  │       analyze_draft(part, metrics, mutate=False)
  │       detect_undercuts(part, d, boolean_refine=False, mutate=False)
  │       _score_candidate(draft_result, undercut_result) → cheap score
  │       _is_direction_suitable_cheap(draft_result, undercut_result) → bool
  │     If any principal passes cheap screen:
  │       run Boolean refinement on those candidates
  │       _is_direction_suitable_boolean() on Boolean results
  │       If acceptable: return immediately → search_stage_reached=1        [line ~1124]
  │
  ├── Stage 2: 12 face-diagonal directions            [line ~1144]
  │     (same scoring loop + early exit at search_stage_reached=2)          [line ~1194]
  │
  └── Stage 3: spherical grid (up to 54 candidates)  [line ~1249]
        generate_candidate_directions(angular_step_deg=15.0)
        _select_boolean_refinement_candidates() — prefilter for Boolean
        Boolean refinement on top-k (default 5)
        Fine search: generate_fine_candidate_directions() around top-3     [line ~1280]
        Final sort by score → best = scored[0]
  │
  ▼
With final direction:
  detect_undercuts(part, best_dir, boolean_refine=True, mutate=True)
  analyze_draft(part, best_dir, mutate=True)
  part.optimal_pull_direction = best_dir              [line ~1338]
  part.direction_score = best_score                   [line ~1339]
  part.inaccessible_face_ids = undercut_result.undercut_face_ids [line ~1340]
  │
  ▼
main.py builds JSON response:
  DirectionOptimizationResult.to_dict()
  + display_mesh (include_mesh=true by default)
  + boolean_region_meshes (include_boolean_regions=true/false)
  Response discarded after serialization.
```

### Key Invariants

- `PartGeometry` flows through all modules as the single shared object.
- OCC handles (`occ_face`, `occ_edge`, `occ_shape`) are **never** serialized; `.to_dict()` is called before returning.
- `mutate=False` in all scoring loops; `mutate=True` only for the final chosen direction.
- The API re-parses the STEP file on every endpoint call (stateless by design).

**Sources:** `backend/api/main.py`, `backend/geometry/direction_optimizer.py`, `backend/geometry/step_loader.py`

---

## Section 2: Pull-Direction Search Mechanism

### Hierarchical Three-Stage Search

The search is hierarchical with early-exit semantics. Each stage is tried in order; the algorithm returns as soon as a "suitable" direction is found.

**Stage 1 — Six Principal Axes** (`direction_optimizer.py` line ~1090)

Axes: `±X, ±Y, ±Z`. These are always evaluated first because injection molds overwhelmingly open along a Cartesian axis. Six cheap evaluations + conditional Boolean refinement.

**Stage 2 — Twelve Face Diagonals** (`direction_optimizer.py` line ~1144)

Face diagonals of the unit cube: directions like `(1,1,0)/√2`, `(1,0,1)/√2`, etc. Configurable in `config.yaml` without code change.

**Stage 3 — Spherical Grid + Fine Search** (`direction_optimizer.py` line ~1249)

`generate_candidate_directions()` (`direction_optimizer.py` line ~429):
- Iterates `θ ∈ [0°, 180°]` and `φ ∈ [0°, 360°]` in steps of `angular_step_deg` (default 15°) to produce up to `max_candidates` (default 54) normalized direction vectors on the unit sphere.
- Principal axes are always included (6 are inserted first, spherical grid adds the rest).
- Duplicate directions are deduplicated by rounding to 4 decimal places.

`generate_fine_candidate_directions()` (`direction_optimizer.py` line ~495):
- Takes the `fine_search_top_k` (default 3) best candidates from Stage 3.
- Generates a local cone of radius `fine_search_cone_half_angle_deg` (default 15°) around each, sampled at `fine_angular_step_deg` (default 5°).
- Adds these as additional candidates for scoring.
- Fine search controlled by `config.yaml: dfm.direction_search.fine_search_enabled`.

### Suitability Gates (PROVISIONAL)

Two gates determine if a direction is "acceptable enough" to trigger early exit:

**Cheap gate** (`_is_direction_suitable_cheap()`, line ~918):
```python
bad_area_pct <= suitability_max_bad_draft_pct (30.0)          # PROVISIONAL
AND accessibility_risk_area_pct <= suitability_max_accessibility_risk_pct (15.0)  # PROVISIONAL
```

**Boolean gate** (`_is_direction_suitable_boolean()`, line ~945):
```python
confirmed_undercut_area_pct <= suitability_max_confirmed_undercut_pct (10.0)  # PROVISIONAL
```

Both thresholds are labeled `PROVISIONAL` in `config.yaml`. They were chosen to match Part1.stp +Z behavior, not derived from a dataset.

### Boolean Prefilter

`_select_boolean_refinement_candidates()` (`direction_optimizer.py` line ~663):
- Sorts all Stage 3 candidates by cheap score.
- Applies risk-gated prefilter: candidates with accessibility_risk_area_pct above a threshold are deprioritized.
- Selects top `boolean_refine_top_candidates` (default 5) for expensive Boolean validation.
- Ensures at least 1 candidate always goes through Boolean even if all fail the risk gate.

**Sources:** `backend/geometry/direction_optimizer.py:429,495,663,918,945,1003`, `config.yaml`

---

## Section 3: Draft Analysis — How It Actually Works

### Formula

`backend/geometry/geometry_models.py` line ~355:
```python
def draft_angle_for_direction(self, pull_dir: Vec3) -> float:
    return math.asin(min(1.0, abs(dot3(self.normal, pull_dir)))) * 180.0 / math.pi
```

**Draft angle = arcsin(|n · d|)** where `n` is the outward unit normal and `d` is the unit pull direction.

- 0° = face parallel to pull direction (wall perfectly vertical — mold sticks)
- 90° = face perpendicular to pull direction (horizontal cap — no issue)
- 1.5° = minimum acceptable (green), from `config.yaml: dfm.draft.good_threshold_deg`

### Normal Computation

`step_loader.py: _compute_face_normal_and_centroid()`:
1. Gets face parametric bounds via `BRep_Tool.Surface()` + `BRepTools.UVBounds()`.
2. Evaluates `GeomLProp_SLProps` at the UV centroid `(u_min+u_max)/2, (v_min+v_max)/2`.
3. Retrieves the surface normal from `SLProps.Normal()`.
4. If face orientation is `TopAbs_REVERSED`, flips the normal: `n = (-nx, -ny, -nz)`.
5. Flags `FaceData.normal_valid = False` if SLProps fails or u/v parameters are out of range.

### Three-Level Classification

`draft_analyzer.py: _classify_draft()`:
```
draft_angle_deg >= good_threshold_deg  (1.5°)  → "good"
draft_angle_deg >= marginal_threshold_deg (0.5°) → "marginal"
else                                             → "bad"
```

`draft_analyzer.py: _PARTING_THRESHOLD = 0.01` (line 368) — hardcoded, NOT in config.yaml.

`draft_analyzer.py: _mold_side()`:
```
signed_dot > +0.01   → "positive"  (cavity side, faces away from core)
signed_dot < -0.01   → "negative"  (core side, faces into mold)
else                 → "parting"   (near-perpendicular to pull)
```

### Precomputed Directional Metrics

`draft_analyzer.py: FaceDirectionalMetrics` (frozen dataclass):
- `signed_dot: float` — n·d (once per face per direction)
- `draft_angle_deg: float` — derived from signed_dot
- `mold_side: str` — "positive"/"negative"/"parting"
- `draft_classification: str` — "good"/"marginal"/"bad"

`precompute_directional_metrics(part, pull_direction)` computes `n·d` once for all faces and shares the result with both `analyze_draft()` and `detect_undercuts()`, avoiding redundant OCC calls in scoring loops.

### Severity Assessment

`_assess_severity()` in `draft_analyzer.py`:
```
0%           → "none"
0-5%  bad    → "minor"
5-20% bad    → "moderate"
>20%  bad    → "critical"
```

### Mutate Behavior

When `mutate=True`: writes `FaceData.draft_angle_deg` and `FaceData.draft_classification` onto each face object in the shared `PartGeometry`. Used only for the final chosen direction.

**Sources:** `backend/geometry/draft_analyzer.py`, `backend/models/geometry_models.py:355`, `backend/geometry/step_loader.py`

---

## Section 4: Undercut Detection — Detailed Mechanism

### Three Distinct Detection Modes

The system produces three distinct categories of output, which are **not interchangeable**:

| Field | Meaning | Method |
|---|---|---|
| `proxy_undercut_ids` | Draft < 0.5° AND not all-convex edges | Angle heuristic |
| `accessibility_risk_face_ids` | Core-side AND ≥1 concave edge | Heuristic (NOT ray cast) |
| `boolean_confirmed_face_ids` | Swept-face intersection volume > 0 | OCC Boolean |
| `undercut_face_ids` | Union of confirmed + failed_proxy + skipped | Conservative composite |

### Proxy Undercut Detection (Step 1)

`detect_undercuts()` line ~3186:

1. For each face, compute `draft_angle_deg` from `precomputed_metrics` (or recompute).
2. If `draft_angle_deg < marginal_threshold (0.5°)`: candidate proxy undercut.
3. Parting faces excluded: `abs(signed_dot) <= parting_dot_threshold (0.01)` (hardcoded line ~3241, NOT from config).
4. **Convexity suppression** (line ~3270, Sangolli 2021 adaptation): if ALL edges adjacent to a proxy undercut face have convexity "convex" or "tangent", remove it from the proxy list. Rationale: a purely convex feature cannot create a true undercut — the mold can slide past it.

### Convexity Computation (Load-Time)

`step_loader.py: _compute_edge_convexity()`:

For each manifold edge (exactly 2 adjacent faces A and B):
1. Evaluate `BRep_Tool.Curve()` at midpoint → tangent vector `t`.
2. Compute `n_a × n_b` (cross product of two adjacent face normals).
3. Compute `sign(t · (n_a × n_b))`.
4. `> 0` → "convex", `< 0` → "concave", `= 0` → "tangent".

Convexity is face-topology-dependent but **pull-direction-independent**. It is computed once at STEP load time and stored in `EdgeData.convexity`.

### Accessibility Risk (Heuristic, NOT Ray Cast)

`_compute_accessibility_risk()` line ~3108:

A face is flagged as `accessibility_risk` if **both** conditions hold:
1. `signed_dot(face.normal, pull_direction) < -accessibility_risk_core_side_threshold` (default -0.01, from config)
2. The face has at least 1 adjacent edge with convexity == "concave"

**Important:** This is a geometric heuristic, NOT the ray-casting-based `accessibility_ratio` described in `pull-direction-plan.txt §7`. The plan describes continuous sampling (`accessible_samples / total_samples`); the implementation uses binary face flagging. [PLAN VS ACTUAL DISCREPANCY]

### Boolean Validation (Confirmation)

`_boolean_refine_undercuts()` line ~2885, called only when `boolean_refine=True` and `_OCC_BOOLEAN_AVAILABLE=True`:

For each candidate face:
1. `_swept_face_interference_volume()` line ~2734:
   a. Offset the face by a small amount along its normal (to avoid self-intersection).
   b. Build a prism (`BRepPrimAPI_MakePrism`) by sweeping the offset face in the pull direction by `part_diagonal` distance.
   c. Compute `BRepAlgoAPI_Common(prism, part.occ_shape)` — intersection with part body.
   d. Measure volume via `brepgprop_VolumeProperties`.
   e. If `volume > volume_tolerance`: confirmed undercut.

`volume_tolerance = max(diagonal^3 * 1e-9, 0.000001)` — adaptive per part size.

### Conservative Composite Rule

After Boolean validation (line ~3331):
```python
undercut_face_ids = boolean_confirmed + failed_proxy + skipped_proxy
```
- `boolean_confirmed`: passed volume > threshold
- `failed_proxy`: proxy undercut that was candidate for Boolean but OCC operation returned no volume
- `skipped_proxy`: proxy undercut NOT attempted by Boolean (budget exceeded or filtered out)

This is intentionally conservative: faces where Boolean was indeterminate are still counted as undercuts.

### Feature Grouping

`_group_undercut_faces_with_boolean_proximity()`:
- Uses face adjacency graph (`part.face_adjacency`) to form connected components of undercut faces.
- Boolean-confirmed faces with nearby proximity are merged into the same feature even if not directly adjacent.
- Each `UndercutFeature` gets:
  - `face_ids: list[int]` — member faces
  - `depth_proxy_mm: float` — conservative max (from bounding box projection along pull direction)
  - If Boolean ran: `BooleanInterferenceMetrics.depth_mm` — precision depth from interference volume

### Cache and Deduplication

`BooleanVolumeCache` and `DirectionUndercutCache` prevent re-running expensive OCC computations when the same direction+face combination is evaluated more than once (which happens during hierarchical search).

`boolean_was_run = bool(boolean_refine and _OCC_BOOLEAN_AVAILABLE)` — this field in `UndercutDetectionResult` tells callers whether the result reflects a cheap heuristic or a Boolean-validated answer.

**Sources:** `backend/geometry/undercut_detector.py:2734,2885,3108,3186,3241,3270,3331`

---

## Section 5: Boolean Validation — Implementation Details

### OCC Availability Guard

`undercut_detector.py` imports OCC at module level inside a `try/except`:
```python
try:
    from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Common
    ...
    _OCC_BOOLEAN_AVAILABLE = True
except ImportError:
    _OCC_BOOLEAN_AVAILABLE = False
```

When `_OCC_BOOLEAN_AVAILABLE = False` (pip-only environments, CI), the Boolean path is entirely bypassed. `boolean_refined=False` in the result. All undercuts remain in "proxy" state.

### The Swept-Face Interference Algorithm

`_swept_face_interference_volume()` (line ~2734):

```
face → offset surface (normal direction, small clearance)
offset_face → BRepPrimAPI_MakePrism(along pull direction, distance=bounding_diagonal)
prism + part.occ_shape → BRepAlgoAPI_Common
GProp_GProps → brepgprop_VolumeProperties(intersection)
volume > tolerance → CONFIRMED UNDERCUT
```

The "interference volume" is the material that would need to be displaced if the mold were pulled in `pull_direction` — it represents the true geometric lock.

### Retry Logic

If `BRepAlgoAPI_Common` fails (returns `IsDone()==False`), the system retries with increasing fuzzy tolerance values (fuzzy tolerance is a relaxation parameter for near-degenerate OCC Boolean operations). After exhausting retries, the face is classified as `failed_proxy` (treated conservatively as undercut).

### Budget Control

`boolean_refine_max_faces` (default 80, `config.yaml`) limits how many faces get the Boolean treatment per direction evaluation. Faces exceeding the budget are classified as `skipped_proxy`.

**Sources:** `backend/geometry/undercut_detector.py:2734`, `config.yaml`

---

## Section 6: Direction Optimizer Scoring — Exact Formulas

### Two Distinct Scoring Modes

The system applies a completely different scoring formula depending on whether Boolean validation ran.

### Cheap Stage Score (`_score_candidate()`, `direction_optimizer.py` line ~585, Boolean-NOT-run path)

```python
score = (
    1500.0 * accessibility_risk_area_pct      # from config: scoring_accessibility_risk
  + 1000.0 * bad_draft_area_pct               # from config: scoring_bad_draft
  + 100.0  * marginal_draft_area_pct          # from config: scoring_marginal_draft
  + flash_risk_term                            # from config: flash_risk_weight * thin_near_parallel_fraction
  + 10.0   * bad_draft_face_count
  + 2.0    * marginal_draft_face_count
  + 25.0   * accessibility_risk_face_count
  + 0.25   * (1.0 - principal_axis_alignment) # from config: scoring_axis_preference
)
```

`flash_risk_term = flash_risk_weight * thin_area_fraction`:
- `thin_area_fraction` = fraction of total area where: face area < flash_area_threshold AND draft_angle < flash_angle_threshold
- `flash_risk_weight = 200.0` (config)

`principal_axis_alignment = max(|dx|, |dy|, |dz|)` (`line ~483`):
- Pure axis direction → alignment = 1.0 → penalty = 0.25 * 0 = 0 (no penalty)
- Diagonal (1,1,0)/√2 → alignment = 0.707 → penalty = 0.25 * 0.293 ≈ 0.073

### Boolean Stage Score (`_score_candidate()`, Boolean-run path)

```python
score = (
    1500.0 * confirmed_undercut_area_pct       # from config: scoring_confirmed_undercut
  + 1000.0 * bad_draft_area_pct
  + 100.0  * marginal_draft_area_pct
  + 4000.0 * interference_volume_fraction      # from config: boolean_interference_weight
  + flash_risk_term
  + count_terms (same as cheap)
  + 0.25   * (1.0 - principal_axis_alignment)
)
```

The `boolean_interference_weight = 4000.0` (config) is the highest single-factor weight in the system, reflecting that Boolean-confirmed interference volume is the strongest undercut signal.

Note: `accessibility_risk_area_pct` is replaced by `confirmed_undercut_area_pct` in the Boolean stage. The cheap heuristic signal is superseded by the geometric evidence.

### Lowest Score Wins

Final selection (direction_optimizer.py line ~1338):
```python
best = sorted(scored_candidates, key=lambda c: c.score)[0]
```

Score 0.0 is the theoretical ideal (no bad draft, no undercuts, perfect axis alignment).

**Sources:** `backend/geometry/direction_optimizer.py:483,585`, `config.yaml`

---

## Section 7: Part1.stp — +Z Golden Control

### What the System Produces

[INFERRED FROM TEST STRUCTURE + CONFIG, NOT DIRECT RUNTIME MEASUREMENT]

Part1.stp (`data/parts/Part1.stp`) is the primary test fixture. The expected behavior is that the optimizer returns `+Z = (0.0, 0.0, 1.0)` as the best mold opening direction.

### Why +Z Wins

The suitability gate thresholds in `config.yaml` are explicitly calibrated to Part1:
- `suitability_max_bad_draft_pct: 30.0` — labeled PROVISIONAL
- `suitability_max_accessibility_risk_pct: 15.0` — labeled PROVISIONAL

In `test_direction_optimizer.py:583-617`, the Stage 1 early exit test constructs a face with normal `(0.0, 0.0, 1.0)` (aligned with +Z) and verifies that `search_stage_reached == 1`, meaning +Z is found acceptable in Stage 1 without exhausting the search.

### Stage 1 Path for Part1

1. +Z is among the 6 principal axes → evaluated first in Stage 1.
2. A face with normal `+Z` has `signed_dot = 1.0` → `draft_angle_deg = 90°` → "good" draft.
3. A face with `signed_dot = +1.0` is on the cavity side (`mold_side = "positive"`) → cannot be accessibility_risk (requires core-side `signed_dot < -0.01`).
4. `bad_area_pct = 0`, `accessibility_risk_area_pct = 0` → cheap gate passes.
5. Boolean refinement confirms 0 undercuts → Boolean gate passes.
6. `search_stage_reached = 1`, return immediately.

### Evidence Quality

[INFERRED FROM TESTS — not from a logged runtime run of Part1.stp through the optimizer]

Tests verify the mechanism works correctly for the Part1 face-normal geometry. End-to-end validation would require running the `/direction` endpoint against a live pythonocc-core environment (conda/Docker).

**Sources:** `tests/test_direction_optimizer.py:573-617`, `config.yaml`, `CHANGELOG.md`

---

## Section 8: Part3 Results — Why the Direction Differs

### Part3.stp Fixture

`data/parts/Part3.stp` is the second real fixture (there is no Part2.stp — naming resolved in Phase 0). Part3 is a more geometrically complex part that exercises the full hierarchical search.

### Expected Behavior

[INFERRED FROM CHANGELOG + VALIDATION HARNESS STRUCTURE — no direct runtime log available in source files]

`CHANGELOG.md` (2026-08-13 entry, Milestones 1-4) references verification that "380 tests pass locally; 26 new tests green; Stage 1/2 early exits require OCC (reach Stage 3 without OCC)." The Stage 3 fallthrough means Part3's optimal direction is not one of the 6 principal axes — it requires the full spherical search.

### Why Part3 Reaches Stage 3

Part3's geometry places significant face area in orientations where no single principal axis provides `bad_area_pct ≤ 30` simultaneously with `accessibility_risk_area_pct ≤ 15`. The 12 diagonal directions (Stage 2) also fail the cheap gate. Stage 3's spherical grid finds a non-axis-aligned direction that minimizes the composite score.

### Evidence Quality

[INFERRED — no runtime output file committed to the repository for Part3's direction result]

The `backend/validation/part_validation.py` harness is the mechanism for measuring this, but its output is not stored in source control.

**Sources:** `CHANGELOG.md`, `backend/validation/part_validation.py`, `docs/IMPLEMENTATION_STATUS.md`

---

## Section 9: Undercut Visualization — Frontend Data Flow

### Backend Serialization

`backend/api/main.py: _undercut_mesh_visual_payload()` (line ~356):

The backend builds a face-by-face color array in the response JSON. Priority rules:
- `critical_boolean_confirmed`: face is in `boolean_confirmed_face_ids` → priority 100 (red/high severity)
- `proxy_undercut`: face is in `undercut_face_ids` but NOT boolean confirmed → priority 25 (orange)
- `accessible`: face is in `accessible_face_ids` → priority 5 (gray/neutral)

`_undercut_confirmed_face_ids()` (line ~320) extracts `boolean_refinement.confirmed_face_ids` from the result dict by navigating:
```
result["features"][i]["boolean_refinement"]["confirmed_face_ids"]
```

### JSON Structure Reaching Frontend

The undercuts endpoint returns (when `include_mesh=true`):
```json
{
  "undercut_face_ids": [...],
  "boolean_confirmed_face_ids": [...],
  "accessibility_risk_face_ids": [...],
  "display_mesh": {
    "points": [...],
    "faces": [...],
    "face_ids": [...],
    "face_colors": [...]
  }
}
```

### Frontend Session State

`frontend/app.py` session state (from grep):
- `undercut_result` — stored independently per step
- `direction_result` — stored independently

These results can be from different analysis runs if the user reruns steps out of order. The frontend is a pure presentation layer and does NOT reconcile them.

### Visualization Rendering

The frontend reads `boolean_confirmed_face_ids` from feature data (confirmed via grep at line ~undercut visualization section in app.py) for severity-based coloring. On macOS, Plotly is used (PyVista headless issues). On Linux/Docker, PyVista via `stpyvista`.

Face coloring maps:
- Boolean-confirmed undercut faces → high-severity red
- Proxy undercut faces → orange
- Normal faces → base color based on draft classification (green/yellow/red)

**Sources:** `backend/api/main.py:320,356`, `frontend/app.py`

---

## Section 10: Frontend Data Flow — Complete Path

### No OCC in Frontend

The frontend (`frontend/app.py`) NEVER imports from `OCC`, `pythonOCC`, or `cadquery`. All geometry data arrives as JSON via HTTP calls to the backend.

```python
BACKEND_URL = os.environ.get("DFM_BACKEND_URL", "http://localhost:8000")
response = requests.get(f"{BACKEND_URL}/parts/{filename}/direction")
```

In Docker: `DFM_BACKEND_URL=http://backend:8000`. Locally: `http://localhost:8000`.

### Session State Keys

```python
st.session_state["summary_result"]       # /summary endpoint response
st.session_state["draft_result"]         # /draft endpoint response
st.session_state["undercut_result"]      # /undercuts endpoint response
st.session_state["direction_result"]     # /direction endpoint response
st.session_state["parting_line_result"]  # /parting-line endpoint response
st.session_state["core_cavity_result"]   # /core-cavity endpoint response
```

Streamlit reruns `app.py` from top to bottom on every user interaction. State survives only in `st.session_state`.

### Guided Flow (5 Steps)

The UI implements: Load → Draft → Undercuts → Direction → Parting Line

Each step stores its result independently. There is no automatic recomputation cascade: changing the pull direction in the Direction step does NOT automatically rerun Undercut or Draft steps.

### Level 1 Snapshot

`_render_level1_snapshot()` (app.py line ~3125) reads all results from session_state independently. It is purely a presentation aggregation — no re-computation.

### Display Mesh Format

The backend sends:
```json
"display_mesh": {
  "points": [[x,y,z], ...],
  "faces":  [[i,j,k], ...],
  "face_ids": [face_id_per_triangle, ...],
  "face_colors": [[r,g,b,a], ...]
}
```

The frontend maps `face_ids` back to face-level coloring for the interactive 3D viewer.

**Sources:** `frontend/app.py`, `.claude/rules/frontend.md`, `backend/api/main.py`

---

## Section 11: Plan vs. Actual Implementation

### pull-direction-plan.txt Discrepancies

The file `pull-direction-plan.txt` describes the intended design for Milestones 1-4. Several sections were implemented differently:

| Plan Section | Plan Description | Actual Implementation | Discrepancy Type |
|---|---|---|---|
| §7 Accessibility | "Cast a ray in withdrawal direction, intersect against occ_shape" | `core-side (n·d < -0.01) + ≥1 concave edge` heuristic | **Significant** — plan describes ray casting; impl uses angle+topology heuristic |
| §8 Accessibility Ratio | "Continuous `accessible_samples / total_samples` per face" | Binary face flag: `accessibility_risk: bool` | **Significant** — plan continuous; impl binary |
| §6 Three-Stage Search | Hierarchical principal → diagonal → spherical | Implemented as described | Match |
| §9 Independent Scoring | Draft and undercut scored as separate signals | Implemented as described | Match |
| §10 Boolean Confirmation | Boolean replaces proxy undercut in final score | Implemented; cheap score still used in Stage 1/2 cheap gate | Partial match |
| Fine search | Cone search around top candidates | Implemented (`generate_fine_candidate_directions()`) | Match |

### Why the Discrepancy Exists

Ray casting against `occ_shape` (plan §7) would be geometrically more accurate but requires OCC intersection calls for every face × every candidate direction — a multiplicative cost blowup. The heuristic (core-side + concave edge) runs in O(faces) with no OCC calls, enabling cheap-stage evaluation of all 54+ spherical candidates before committing to Boolean validation.

### Honest Capability Assessment

| Claim | Accurate? |
|---|---|
| "Full Bassi Boolean accessibility for every face" | No — selective Boolean for top-k candidates only |
| "Full Sangolli volumetric decomposition" | No — feature-level grouping and typing only |
| "Ray-casting accessibility check" | No — angle+concavity heuristic |
| "Core/cavity solid split follows exact 3-D parting surface" | No — planar approximation used; real parting surface topologically invalid on both parts |
| "Parting line is fully optimized (Hou global optimization)" | No — silhouette candidate + graph cleanup; Hou optimization planned, not implemented |

**Sources:** `pull-direction-plan.txt`, `backend/geometry/undercut_detector.py:3108`, `docs/IMPLEMENTATION_STATUS.md`

---

## Section 12: Provisional and Arbitrary Parameters

The following parameters lack empirical derivation and are acknowledged as provisional in comments or documentation.

### Labeled PROVISIONAL in config.yaml

```yaml
# PROVISIONAL — calibrated to Part1.stp, not derived from dataset
suitability_max_bad_draft_pct: 30.0
suitability_max_accessibility_risk_pct: 15.0
suitability_max_confirmed_undercut_pct: 10.0
```

These three numbers determine when the search exits early. They were chosen so that Part1.stp +Z passes Stage 1, not from a statistical analysis of real part library.

### Hardcoded (Not in config.yaml)

| Location | Symbol | Value | Note |
|---|---|---|---|
| `draft_analyzer.py:368` | `_PARTING_THRESHOLD` | `0.01` | Near-perpendicular zone threshold; identical to `parting_dot_threshold` in undercut code but defined separately |
| `undercut_detector.py:~3241` | `parting_dot_threshold` | `0.01` | Matches draft threshold but independently hardcoded |
| `parting_line.py:4321` | `dot_tolerance` | `0.01` (default arg) | Silhouette classification |
| `parting_line.py:4322` | `boundary_dot_tolerance` | `0.15` (default arg) | Boundary edge inclusion |

### Scoring Weight Rationale

The scoring weights in `config.yaml` (`boolean_interference_weight: 4000.0`, `scoring_accessibility_risk: 1500.0`, `scoring_bad_draft: 1000.0`) were tuned to produce the correct rank ordering for Part1 and Part3. They are not derived from a manufacturing cost model or experimental data.

### Volume Tolerance Formula

`volume_tolerance = max(diagonal^3 * 1e-9, 0.000001)`:
- The `1e-9` cubic factor and `0.000001 mm³` floor are engineering judgments.
- No reference to literature or measurement.

### Fine Search Parameters

`fine_search_cone_half_angle_deg: 15.0` and `fine_angular_step_deg: 5.0` — chosen to sample "near" a good direction without redundant overlap. Not derived from part geometry analysis.

**Sources:** `config.yaml`, `backend/geometry/draft_analyzer.py:368`, `backend/geometry/undercut_detector.py:~3241`

---

## Section 13: Test Coverage

### Test Suite Structure

Located in `tests/`, run via `pytest tests/ -v --tb=short`.

| Test File | Module Covered | Test Count (est.) |
|---|---|---|
| `test_step_loader.py` | `step_loader.py` | ~30 |
| `test_draft_analyzer.py` | `draft_analyzer.py` | ~40 |
| `test_undercut_detector.py` | `undercut_detector.py` | ~60 |
| `test_direction_optimizer.py` | `direction_optimizer.py` | ~35 |
| `test_parting_line.py` | `parting_line.py` | ~40 |
| `test_parting_line_v2_contracts.py` | `parting_line.py` (contract tests) | ~20 |
| `test_parting_line_v2_level0.py` | `parting_line.py` (level0) | ~20 |
| `test_parting_line_v2_level1.py` | `parting_line.py` (level1) | ~20 |
| `test_core_cavity.py` | `core_cavity.py` | ~25 |
| `test_api_error_handling.py` | `main.py` error paths | ~15 |
| `test_api_boolean_regions.py` | `main.py` Boolean region mesh | ~10 |
| `test_part_validation.py` | End-to-end validation harness | ~15 |
| `test_performance_profile.py` | Performance profiling | ~10 |
| `test_side_core.py` | `side_core.py` | ~20 |
| `test_agent_providers.py` | `agent/providers.py` | ~15 |
| `test_dfm_agent.py` | `agent/dfm_agent.py` | ~10 |
| `test_viewer_key_stability.py` | face_id stability (new) | ~5 |

**Total: approximately 380 tests** (CHANGELOG.md 2026-08-13: "380 tests pass locally").

### OCC Mocking Strategy

Tests run without pythonocc-core (pip-only CI). Pattern:
```python
face = FaceData(face_id=0, normal=(0.0, 0.0, 1.0), area=100.0, occ_face=None)
part = PartGeometry(faces=[face], edges=[], face_adjacency={0: []})
```
Analysis functions operate on data fields (`normal`, `area`), not OCC handles directly. OCC handles are only used by `step_loader.py` during initial extraction.

### What Tests Cover

[PROVEN BY TEST — tests/test_direction_optimizer.py]:
- Stage 1 early exit when principal Boolean acceptable (`test_stage1_early_exit_when_principal_boolean_acceptable`)
- Stage 2 runs when no principal passes cheap screen (`test_stage2_runs_when_no_principal_cheaply_suitable`)
- Stage 3 reached when OCC unavailable (`test_search_stage_reached_3_when_occ_unavailable`)
- Cheap score uses `accessibility_risk`, NOT `undercut_pct` (`test_cheap_score_uses_accessibility_risk_not_undercut_pct`)
- Boolean stage score uses `confirmed_undercut`, NOT proxy (`test_boolean_stage_score_uses_confirmed_undercut_not_proxy`)
- Flash risk term increases score for thin near-parallel faces (`test_flash_risk_term_increases_score_for_thin_near_parallel_face`)
- Fine search adds candidates (`test_optimize_mold_direction_fine_search_adds_candidates`)
- `principal_axis_alignment` formula: `max(|dx|, |dy|, |dz|)` (`test_generate_candidate_directions_are_unit_vectors`)

[PROVEN BY TEST — tests/test_undercut_detector.py]:
- Proxy detection threshold at 0.5°
- Convexity suppression removes all-convex face from proxy list
- Accessibility risk requires core-side AND concave edge
- Boolean confirmation via swept-face volume (with OCC mocked)
- Conservative composite: failed_proxy treated as undercut

[PROVEN BY TEST — tests/test_draft_analyzer.py]:
- Draft angle formula: `asin(|n·d|)`
- Three-level classification at 1.5° and 0.5°
- `precompute_directional_metrics` avoids redundant computation
- `mutate=True` writes to `FaceData` fields

### What Tests Do NOT Cover

- End-to-end run of Part1.stp or Part3.stp through the full optimizer with live OCC (requires conda environment)
- Stage 1 early exit with actual Part1 geometry (only mocked geometry tested)
- Visualization correctness (no headless rendering tests)
- `_PARTING_THRESHOLD = 0.01` — not explicitly tested for the constant value
- Fine search cone geometry correctness (only that it generates unit vectors and deduplicates)

**Sources:** `tests/` directory, `CHANGELOG.md:2026-08-13`, `tests/pytest.ini`

---

## Section 14: Evidence Quality Classification

### Classification Schema

| Marker | Meaning |
|---|---|
| [PROVEN BY TEST] | Behavior asserted by a passing pytest test |
| [PROVEN BY CODE] | Behavior directly visible in source code logic |
| [INFERRED FROM TESTS] | Behavior inferred from test setup/assertions, not a direct test of production path |
| [CLAIMED IN DOCS] | Stated in CHANGELOG/STATUS/IMPLEMENTATION_STATUS but no test verifies it |
| [PROVISIONAL] | Explicitly labeled as provisional in comments or documentation |
| [PLAN VS ACTUAL DISCREPANCY] | Documented mismatch between plan and implementation |
| [UNKNOWN] | Cannot be determined without a live runtime measurement |

### Evidence Quality by Claim

| Claim | Quality |
|---|---|
| Draft angle formula = `asin(\|n·d\|)` | [PROVEN BY CODE] `geometry_models.py:355` + [PROVEN BY TEST] `test_draft_analyzer.py` |
| Three-level classification at 1.5° and 0.5° | [PROVEN BY CODE] + [PROVEN BY TEST] |
| `_PARTING_THRESHOLD = 0.01` hardcoded | [PROVEN BY CODE] `draft_analyzer.py:368` |
| Proxy undercut = draft < 0.5° | [PROVEN BY CODE] + [PROVEN BY TEST] |
| Convexity suppression removes all-convex proxy | [PROVEN BY CODE] + [PROVEN BY TEST] |
| Accessibility risk = core-side + concave edge (NOT ray cast) | [PROVEN BY CODE] `undercut_detector.py:3108` |
| Boolean confirmation via swept prism + Common | [PROVEN BY CODE] `undercut_detector.py:2734` |
| Conservative composite (failed_proxy = undercut) | [PROVEN BY CODE] + [PROVEN BY TEST] |
| Stage 1 early exit at `search_stage_reached=1` | [PROVEN BY TEST] `test_direction_optimizer.py:573` |
| Scoring formula coefficients (1500, 1000, 4000) | [PROVEN BY CODE] + config values |
| `principal_axis_alignment = max(\|dx\|,\|dy\|,\|dz\|)` | [PROVEN BY CODE] `direction_optimizer.py:483` |
| Part1.stp → +Z optimal direction | [CLAIMED IN DOCS] — not a committed runtime output |
| Part3.stp reaches Stage 3 | [CLAIMED IN DOCS] `CHANGELOG.md:2026-08-13` |
| 380 tests pass | [CLAIMED IN DOCS] `CHANGELOG.md:2026-08-13` — not continuously tracked |
| Suitability thresholds PROVISIONAL | [PROVEN BY CODE] `config.yaml` comment |
| Parting line = silhouette candidate, NOT Hou optimization | [PROVEN BY CODE] `parting_line.py:1-18` docstring |
| Core/cavity split uses planar approximation, NOT real parting surface | [PROVEN BY CODE] `core_cavity.py:394-400` docstring |
| Boolean-confirmed undercuts on real parts (Part1, Part3) | [CLAIMED IN DOCS] `CHANGELOG.md` — OCC environment required |

---

## Section 15: What the System Actually Believes

### The Operational Belief Model

When the direction optimizer produces a result, here is precisely what it has measured and what it has inferred:

**Measured (OCC exact geometry):**
- Face normals (B-Rep surface normal at UV centroid, REVERSED-orientation corrected)
- Edge convexity (tangent × cross-of-normals sign, computed once at load)
- Face areas (from `FaceData.area`, computed at load via `brepgprop_SurfaceProperties`)
- Part bounding box (computed at load)

**Computed (pure math, no OCC calls):**
- `draft_angle_deg = asin(|n · d|)` for all faces, all candidate directions
- `signed_dot = n · d` — the signed cosine angle
- `mold_side` classification (cavity/core/parting)
- Draft classification (good/marginal/bad)
- Proxy undercut flag (draft < 0.5° AND not all-convex)
- Accessibility risk flag (core-side AND concave edge)

**Validated (OCC Boolean, runs only for top-k candidates when OCC available):**
- Boolean interference volume per face per direction
- Whether a geometric lock genuinely prevents mold withdrawal

**Inferred (NOT measured, NOT validated):**
- Whether a proxy undercut would actually cause a tooling problem in practice
- Whether the accessibility risk faces are truly inaccessible (no ray casting performed)
- The exact mold cavity/core boundary (parting line is a candidate, not an optimized curve)
- The manufacturing cost of any given direction

### The Single Number the System Returns

`DirectionOptimizationResult.best_direction: Vec3` — a unit vector `(dx, dy, dz)` representing the mold opening direction that minimized the composite penalty score across all evaluated candidates.

`DirectionOptimizationResult.direction_score: float` — the raw penalty score. Meaningful only comparatively (lower = better). Not a probability, not a percentage, not a validated manufacturing metric.

### Confidence Stratification

| Result Field | Confidence | Basis |
|---|---|---|
| `best_direction` (with Boolean, OCC available) | High | Geometric interference validated |
| `best_direction` (without Boolean, OCC unavailable) | Moderate | Angle/topology heuristic only |
| `boolean_confirmed_face_ids` | High | OCC Boolean Common volume > 0 |
| `accessibility_risk_face_ids` | Low | Heuristic: core-side + concave edge; NOT ray cast |
| `proxy_undercut_ids` (before Boolean) | Low | Angle < 0.5° after convexity filter |
| `direction_score` value itself | Informational | Tuned to Part1/Part3; not a manufacturing metric |
| `search_stage_reached = 1` | High | Numerically verified by tests |
| Parting line wire | Low-moderate | Silhouette candidate only; no Hou optimization |
| Core/cavity face classification | High | Direct `n·d` sign test |
| Core/cavity solid split | Moderate | Boolean split verified on Part1+Part3; planar approximation, not exact parting surface |

### What Would Need to Change for Higher Confidence

1. **Ray casting instead of heuristic** — implement `accessibility_ratio` as plan §7 described (samples along withdrawal ray against `occ_shape`). This would promote `accessibility_risk_face_ids` from low to high confidence.
2. **Hou global optimization** — replace silhouette candidate with a globally optimal parting curve. This is in the roadmap (`TODO.md`) but not implemented.
3. **Dataset-calibrated thresholds** — replace PROVISIONAL suitability thresholds (`30.0/15.0/10.0`) with values derived from a representative sample of automotive plastic parts.
4. **Continuous manufacturing cost integration** — the current score is a geometric penalty; it does not incorporate tool complexity, cycle time, or cooling constraints.

**Sources:** All files listed in this document. See individual section citations for precise file:line references.

---

## Appendix A: File Reference Index

| File | Purpose | Key Functions/Lines |
|---|---|---|
| `backend/models/geometry_models.py` | Core dataclasses, zero internal imports | `FaceData`, `EdgeData`, `PartGeometry`, `draft_angle_for_direction():355` |
| `backend/geometry/step_loader.py` | STEP parsing, face/edge extraction | `load_step()`, `load_step_cached()`, `_compute_face_normal_and_centroid()`, `_compute_edge_convexity()` |
| `backend/geometry/draft_analyzer.py` | Draft angle computation | `FaceDirectionalMetrics`, `precompute_directional_metrics()`, `analyze_draft()`, `_PARTING_THRESHOLD:368` |
| `backend/geometry/undercut_detector.py` | Undercut detection (proxy + Boolean) | `detect_undercuts():~3186`, `_compute_accessibility_risk():~3108`, `_swept_face_interference_volume():~2734`, `_boolean_refine_undercuts():~2885` |
| `backend/geometry/direction_optimizer.py` | Hierarchical direction search + scoring | `optimize_mold_direction():1003`, `generate_candidate_directions():429`, `_score_candidate():585`, `_is_direction_suitable_cheap():918` |
| `backend/geometry/parting_line.py` | Parting line candidate detection | `detect_parting_line_candidates():4316`, `_classify_edge():627` |
| `backend/geometry/core_cavity.py` | Core/cavity classification + solid split | `classify_core_cavity():116`, `split_core_cavity_solids():373` |
| `backend/api/main.py` | FastAPI REST layer | Direction endpoint:~751, `_undercut_mesh_visual_payload():~356`, `_undercut_confirmed_face_ids():~320` |
| `frontend/app.py` | Streamlit UI (3,905 lines) | Session state keys, `_render_level1_snapshot():~3125` |
| `config.yaml` | All thresholds and parameters | All DfM algorithm parameters — see Sections 2, 3, 6, 12 |
| `pull-direction-plan.txt` | Original design intent | §7 (ray casting), §8 (accessibility ratio) — see Section 11 |
| `docs/IMPLEMENTATION_STATUS.md` | Authoritative capability claims | Bassi/Sangolli honest scope |
| `tests/test_direction_optimizer.py` | Direction optimizer tests | Stage early exit:573, scoring mode:705,761 |
| `tests/test_undercut_detector.py` | Undercut detector tests | Proxy, convexity, Boolean mock |
| `tests/test_draft_analyzer.py` | Draft analyzer tests | Formula, classification, mutate |

---

*Document generated 2026-08-14. Reflects codebase state at commit e703a158 (branch feat/pull-direction). All line numbers are approximate ± a few lines; verify against current source before making architectural decisions.*
