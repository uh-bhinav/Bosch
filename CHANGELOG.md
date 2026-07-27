# Changelog — DfM Agent

> **Append-only.** Add new entries at the top. Format: `### YYYY-MM-DD — Summary`

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
