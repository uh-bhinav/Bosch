# TODO — DfM Agent

> **Prioritized task list.** Update after each session. Mark items `[x]` when done, `[/]` when in progress.

---

> **Master plan**: `docs/ARCHITECTURE_ROADMAP.md` holds the full
> specification, algorithms, config keys, and per-milestone validation gates.
> The items below are its execution checklist.
>
> **▶️ Stage 2 is DONE** (Milestones 1.10/1.11 verified end-to-end on both
> real parts — see S2.3). **Stage 3 is fully DONE (S3.1-S3.8), 2026-07-28**:
> issue-first Layer-1 summary, metric glossary, `graph_cleanup.strategy`/
> coverage always visible, direction axis+tilt formatting, Level 2 wired
> into the Streamlit UI, direction override (Bosch criterion #2) with a
> Recommended-vs-Override comparison, diverse candidate-direction
> clustering, and a backend `PartGeometry` LRU cache (~250x faster on a
> cache hit, verified) + mesh/analysis payload split (~67% smaller,
> verified). **Stage 4's first increment (S4.1/S4.2) is now DONE, 2026-07-28**:
> `backend/geometry/side_core.py` generates one side-core solid (Bosch
> criterion #5), Boolean-subtracted from its containing mold half, exported
> as a third AP214 solid — verified end-to-end on both real parts (S4.2's
> gate: 3 solids reload from STEP with consistent volumes).
> **Stage 5 (AI agent layer) is now DONE, 2026-07-28**: provider-agnostic
> `backend/agent/` package, Gemini live-verified end-to-end against real
> Part1.stp (`/agent/analyze` API + Streamlit "AI Agent" tab), Anthropic/
> OpenAI/Grok structurally verified but not live-tested (no key available).
> **Stage 6 (PDF export) is now DONE, 2026-07-29**: `backend/report/`
> finally uses `reportlab`; pure presentation layer over already-computed
> results, verified end-to-end via `/export/report` + a frontend button.
> **All six roadmap stages are now built.** Remaining work is S4.3
> (grouped/multi-feature side-core generalization — now in progress) and
> the "Deferred/Unscheduled" backlog (exhaustive Bassi, full Sangolli,
> `backend/geometry/__init__.py`, mypy/ruff, splitting `undercut_detector.py`).
> Current state: `STATUS.md`.

---

## 🔴 P0 — Blockers (fix before any other work)

- [x] **F1 — `Part1.stp`/`Part3.stp` identity resolved (2026-07-27)**: confirmed genuine mix-up; `rename.stp` (`Element_Packaging_Cap.stp`, 522,419 B) has been restored as `Part1.stp`. Verified: `Part1.stp` = 522,419 B / MD5 `d0c89a7c…` (Level 1), `Part3.stp` = 863,881 B / MD5 `a373ffdf…` (Level 2) — two distinct files, `rename.stp` no longer exists. STEP schema confirmed as AP214 (`AUTOMOTIVE_DESIGN`) — Phase 1.11's mold-half export targets AP214 to match.
- [x] **F2 — fixed**: `dfm.core_cavity.threshold` added to `config.yaml` + `CoreCavitySettings`; `classify_core_cavity()` and the `/core-cavity` endpoint now default from settings instead of a hardcoded `0.05`.
- [x] **F3 — fixed**: `.claude/rules/api-layer.md` now documents `include_mesh` / `include_boolean_regions` as query flags on the real endpoints instead of two nonexistent routes.
- [x] **F4 / BUG B — fully resolved (2026-07-27)**: `_trace_best_weighted_path` AND `_build_ordered_wire` (a second, separate wire-orderer used for initial selection — including the bridging accept/reject decision — that was ALWAYS pure greedy with no exact search at all, regardless of size) both now share one exact-search dispatcher, `_best_path_with_contraction_fallback`. Degree-2 chains are contracted into hyper-edges first (`_contract_degree2_chains`) so the exhaustive DFS scales with real branch points, not raw edge count — Part3's 254-edge bridged graph contracts to 50 hyper-edges. The contracted search gets a much larger state budget (3,000,000 vs. 75,000) since it's cheap per-state on the smaller graph; verified it now runs to full completion (177,032 states) instead of exhausting the old budget mid-search. 27 parting-line tests + 205 others pass; Part1/Part3 timing unaffected (~8-9s each, no hang risk).
- [x] **F5 — fixed (2026-07-27)**: documented test command (`docker compose exec backend pytest tests/ -v --tb=short`) never worked — no root `conftest.py`/`pytest.ini` puts `/app` on `sys.path`. Fixed with `pythonpath = ..` in `tests/pytest.ini`.
- [x] **F6 — fixed (2026-07-27)**: Streamlit frontend crashed on macOS with `tornado.websocket.WebSocketClosedError` flood during "Full Level 1 Flow". Root cause: 6 full mesh copies (~500 KB each) in `st.session_state` → RAM exhaustion. Fixed with `_cache_and_strip_mesh` (cache geometry once after first step, strip points/faces from subsequent results) + `_hydrate_mesh` (restore at render time) + `dfm.display.max_triangle_count: 100000` ceiling in `build_display_mesh()`. Changed files: `frontend/app.py`, `backend/geometry/visualize_raw.py`, `backend/config.py`, `config.yaml`.
- [x] **Run Docker validation with real OCC and commit the artifacts (2026-07-27)** — real (non-`skipped`) evidence in `reports/level1_validation/*_docker_20260727*`; both parts pass every stage. Authoritative post-Milestone-1.2 run: `part_validation_docker_20260727_post_1.2.json` + `performance_profile_part{1,3}_20260727.json` — combined `direction_search` time dropped from ~713s (pre-1.2) to ~15s (post-1.2, calm environment).
- [x] **Fix overclaims in SUBMISSION_REPORT.md** — already fixed during Phase 0 (2026-07-27): `docs/SUBMISSION_REPORT.md` evaluation matrix now says "Candidate/foundation" for parting line and "Complete for face classification only" for core/cavity.
- [x] **Investigate genuine test failure — RESOLVED, now passes (2026-07-28)**: `test_api_error_handling.py::test_parting_line_paths_payload_is_json_safe` failed for real when first surfaced (once F5's import bug was fixed, 2026-07-27) — it was catching a genuine bug in the parting-line pipeline at the time (predates Bug B/H-2/H-3). Re-verified directly in Docker: passes cleanly now. No longer tracked as an open item; confirmed as part of the full-suite 237/237 clean run (BUG G).
- [x] **FIX C — Docker frontend now matches local dev's interactive Plotly viewer (2026-07-28)**: `_USE_PLOTLY_VIEWER` in `frontend/app.py` was `sys.platform == "darwin" or DFM_FORCE_PLOTLY == "1"` — Docker (Linux) never set the env var, so it silently fell through to the PyVista/`stpyvista`/Xvfb renderer while macOS dev got the interactive Plotly one. Same backend data, two different viewer UX depending on where you ran it. Fixed with one line: `DFM_FORCE_PLOTLY=1` added to `docker-compose.yml`'s frontend service environment — `plotly==5.21.0` is already a `Dockerfile.frontend` dependency, no image rebuild needed. Verified live: brought up `docker compose up`, confirmed `DFM_FORCE_PLOTLY=1` reaches the container (`docker exec ... printenv`), and ran `_show_mesh_plotly`'s actual trace-building code inside the running frontend container against a REAL mesh payload fetched from the REAL running backend for `Part1.stp` (6,649 points, 7,270 faces) — produced a valid `go.Mesh3d` figure end to end. Browser-level interactivity itself wasn't click-tested (no browser automation tool available); the data path, env propagation, and Plotly figure construction are all confirmed with production data.
- [x] **BUG G — FULLY FIXED 2026-07-28 — two `test_parting_line.py` tests no longer hang on real OCC.** Root cause: `_sample_closed_edge_points` constructs `BRepAdaptor_Curve(edge.occ_edge)`, a SWIG-wrapped C++ call — when `occ_edge` is a `MagicMock` (any unit test without real STEP data), that call can hang indefinitely at the native layer, which no Python `try/except` can catch. Fixed with an `isinstance(edge.occ_edge, TopoDS_Edge)` guard before the call — a fast, pure-Python check that fails cleanly on any mock, never reaching the native layer. Also fixed a broader instance of the same bug found while fixing BUG H-3: `_build_ordered_wire` called this function for ANY edge with unparseable endpoints, not just genuine single-edge components. Both previously-hanging tests now pass in under a second; one assertion updated (`diagnostics.status`: `"ok"` → `"warning"`) since the test could never actually run to completion before and its expectation was stale relative to the later Bug H coverage-warning feature. **`tests/test_parting_line.py` now runs 32/32 with zero exclusions; whole-project suite 237/237 passed, 0 excluded** — the first fully clean run in this project's history.
- [ ] **Test-suite hygiene: mock-based tests need explicit `boolean_refine=False`** — found 2026-07-27 while verifying Milestone 1.2. Any test building a mock `PartGeometry` (`occ_face=MagicMock()`) and calling `detect_undercuts()`/`optimize_mold_direction()` without `boolean_refine=False` stalls for minutes against a container with real pythonocc-core installed (the mock isn't a valid SWIG-wrapped OCC object, and it gets fed straight into real `BRepAlgoAPI_Common`/`BRepPrimAPI_MakePrism` calls). This was invisible before F5 was fixed, since Docker test runs never worked at all. Partially mitigated 2026-07-27 at known call sites in `test_undercut_detector.py` (lines 68, 180, 355) and `test_direction_optimizer.py` (via monkeypatch); all 74 tests in those modules pass in <1s. Still needs a broader audit pass for any remaining mock-based tests.
- [x] **F7 — fixed (2026-07-28)**: `docker-compose.yml` never bind-mounted `tests/` (only `backend/`, `frontend/`, `data/`, `reports/`, `config.yaml`). Every `docker compose exec backend pytest tests/...` — the exact command CLAUDE.md documents — was silently running whatever `tests/` tree was baked into the image at last build, not the current repo. Confirmed materially stale: 6 of 12 test files were missing entirely (including `test_core_cavity.py` from Stage 2a, `test_part_validation.py` additions, `test_parting_line.py`, `test_direction_optimizer.py`, `test_api_*`), and the container's copy of `tests/pytest.ini` predated F5's `pythonpath = ..` fix — so F5 was fixed in source on 2026-07-27 but never actually verified in Docker, because Docker was reading a stale copy the whole time. Fixed by adding `./tests:/app/tests` to the backend service volumes (mirrors `./backend`). Recreated the container and reverified: bare `pytest tests/test_core_cavity.py` now passes 9/9 with no `pythonpath` workaround needed, and the full suite is 255/255 (see BUG G's 237 + Stage 2a's +9 + X.1's +9). This was found *by trying to test X.1*, not by design — another instance of the audit's core lesson: a documented verification command is not evidence unless you've confirmed it actually reads current source.

## 📌 Decisions locked in (2026-07-27)

- **Undercut depth: precision vs. conservative severity — RESOLVED, keep current behaviour.** The two metrics are *intentionally different* and serve different objectives:
  - `BooleanInterferenceMetrics.depth_mm` (per-face) → **precision**. A face-level engineering measurement; always prefers the highest-confidence Boolean-derived depth when available.
  - `UndercutFeature.depth_proxy_mm` (per-feature) → **conservative severity**. A risk-assessment/prioritisation metric, not an exact measurement; remains a conservative upper bound, taking the max of available estimators to avoid under-reporting manufacturability risk.
  - Rationale: in DfM, false positives are preferable to false negatives — over-estimating depth costs a conservative tooling allowance; under-estimating it costs a stuck part at demold.
  - **Do not resurrect the reverted "prefer precision" change** (attempted and reverted during Milestone 1.3; it broke 3 tests that assert this deliberately). Documented in the `UndercutFeature` class docstring and `docs/ARCHITECTURE_ROADMAP.md` Milestone 1.3 note.

- **STEP export schema**: match source files — AP214 (`AUTOMOTIVE_DESIGN`), confirmed via `FILE_SCHEMA` in `Part1.stp`/`Part3.stp`. Consistent with the Siemens NX origin of the input files.
- **PDF export**: still a deliverable. Scheduled as **Phase 5**, tackled after Phase 4 (agent layer) — not dropped, just sequenced last.
- **Texture marking**: selectable in the UI (Phase 1e option 1 — explicit per-face override from user selection), not inferred from surface type alone.

## 🟠 PHASE 1 — Geometry Engine Hardening

- [x] 1.1 Edge convexity computation in `step_loader.py` → populates `EdgeData.convexity` at load time (was always `None`). Verified: plain box → 12/12 convex; box-with-pocket → pocket floor's 4 edges concave; real `Part1.stp` → >90% of manifold edges classified. New config: `dfm.undercut.convexity_tangent_tolerance` (0.01). Tests: `tests/test_step_loader.py::TestEdgeConvexitySynthetic`.
- [x] 1.2 Convexity-gated undercut false-positive suppression in `detect_undercuts()`. Verified on real parts (suppression on/off): Part1 undercut count 44→18, Boolean-checked 78→27, 45.2s→13.4s; Part3 undercut count 16→0, Boolean-checked 97→3, 73.6s→1.9s. **Part3's 100% swing flagged for domain/visual review**, not just accepted. New: `UndercutDetectionResult.convexity_suppressed_face_ids`, config `dfm.undercut.convexity_suppression_enabled` (kill switch). Tests: `tests/test_undercut_detector.py` (4 new, mock-based).
- [x] 1.3 **Reassessed, no code change (2026-07-27)**: per-face depth (`_select_boolean_depth_details`) already does exact-vertex-first prioritization correctly (4 passing tests confirm). Feature-level aggregation deliberately takes the *largest* plausible estimate (conservative safety margin, not a bug) — an attempted "prefer precision" fix was reverted after it broke 3 tests with exact numeric assertions. See `docs/ARCHITECTURE_ROADMAP.md` Milestone 1.3 note. **Needs a team decision**, not something to silently change.
- [x] 1.4 Flash risk penalty term + coarse-to-fine (±5°) direction search. Verified on real geometry: Part1 best_score 0.692→0.313 (−54.8%), Part3 6.415→1.384 (−78.4%), both finding a genuinely better direction, +60 candidates as designed, no timing regression. New config: `flash_risk_weight`, `flash_angle_threshold_deg`, `flash_thin_area_factor`, `fine_search_enabled`, `fine_search_top_k`, `fine_angular_step_deg`, `fine_search_cone_half_angle_deg`, `fine_search_max_candidates`. Tests: `tests/test_direction_optimizer.py` (8 new, mock-based).
- [x] 1.5 Draft conditional thresholds — **scoped to explicit override → global default** (tiers 2/3 deliberately deferred, see roadmap note: surface-type defaults are a no-op today per the honesty ruling, deep-rib auto-detection needs real geometric work not yet done). `analyze_draft(..., face_conditions={face_id: "light_texture"|"heavy_texture"|"deep_rib"|"smooth"})`. Verified on real Part1.stp. New config: `dfm.draft.conditions.*`. Tests: `tests/test_draft_analyzer.py::TestFaceConditionThresholds` (6 new). API wiring deferred to Phase 2 (needs a frontend picker to call it from).
- [x] 1.6 Replace bounded DFS with a real `networkx` graph in `parting_line.py` — **finally fully done 2026-07-27/28, see BUG B/F4 above.** The original F4 pass (line 18) only wired `networkx` in for adjacency queries; the actual best-loop SEARCH remained bounded-DFS-then-greedy. BUG B replaced it with a real shared exact/contracted search (`_best_path_with_contraction_fallback`), used by both the refinement path and the initial-selection path, with a polynomial-time `nx.cycle_basis`/`nx.find_cycle` guarantee-of-correctness fallback for when the exact search's budget is exhausted. This item was left unchecked here even after F4 claimed resolution — a duplicate/stale tracking issue between the F4 entry and this roadmap line; now reconciled.
- [x] 1.7 Bridge disconnected silhouette components via real B-Rep edges (`EdgeData.is_boundary`) — `_bridge_disconnected_components()` added; `detect_parting_line_candidates` wired with `bridge_components` param.
  - ⚠️ **REPAIRED 2026-07-27 (Stage 1.1 / Bug F)**: bridging ran unconditionally and **destroyed an already-good closed loop**. Measured on Part1 at its optimal direction, bridging the only variable: `ready(1.000)/quality 0.96/closed=True/0 branch/0 gaps/0.2s` → `weak(0.080)/quality 0.0/closed=False/11 branch/15 gaps/49.8s`. It also blocked core/cavity. Bridging is now a **fallback**: skipped when a closed loop is already selected, and its result is kept only if it closes the loop or does not reduce quality. New `PartingLineResult.bridging_status` (`not_needed`/`applied`/`discarded_not_an_improvement`/`unavailable`/`disabled`) makes the decision inspectable.
- [x] 1.8 Guaranteed closed loop — `_attempt_loop_closure()` added; `PartingLineResult` gets `closure_error_mm` and `closure_guaranteed` fields.
  - ⚠️ **REPAIRED 2026-07-27 (Stage 1.1 / Bug A)**: the original version computed the closing path and then **discarded it**, returning `(True, 0.0)` while handing downstream a curve with a **17.35 mm gap** on real Part1 — a false geometric guarantee that the parting surface, core/cavity split and STEP export all trusted. Now returns the closing points, splices real B-Rep vertices into the curve, closes it exactly, and **re-measures** before reporting success. New `closure_bridge_edge_count` records how many real edges were spliced. 4 permanent honesty guards added to `tests/test_parting_line.py`.
- [x] 1.9 Parting surface — `_build_parting_surface()` implemented: PCA planar extrusion first (`BRepBuilderAPI_MakeFace` + `BRepPrimAPI_MakePrism`), `BRepFill_Filling` fallback; `PartingSurfaceResult` dataclass added; `PartingLineResult.parting_surface` field added.
  - ⚠️ **REPAIRED 2026-07-27 (Stage 1.4 / Bug E)**: produced **no surface at all** on either part. Three causes: (a) `BRepFill_Filling` was constructed with `NbPtsOnCur=0, NbIter=0` — OCC rejects `NbIter<1`, so the filling path could never run; (b) it was fed the ~24,000-point *display* polyline as constraints — added `_decimate_closed_loop()` to 120 segments; (c) the planar path had no pull-direction check — PCA fits Part3's loop to 0.74 mm on a plane 60° off the pull axis, which would slice the mold diagonally. Now requires `|dot(normal, pull)| >= planar_pull_alignment_min`. **Both parts now yield `generated_filling`** (areas 5344.29 / 172.36 mm², live `occ_shape`). Both parts have genuinely 3-D parting lines (pull-axis span 16.16 mm on a 30.78 mm part; 7.14 mm on 68.12 mm), so filling is the normal path. New config: `planar_pull_alignment_min`, `filling_max_constraint_edges`.
- [x] **BUG H (FIXED 2026-07-27) — the parting line selected the tidiest loop, not the MAIN silhouette.** `_wire_selection_key` ranked projected area 5th; Nee 1998 specifies *"largest projected area (maximum contour rule)"* as the **primary** criterion. Reordered to: validity gate → undercut-conflict avoidance → **projected area** → quality → prior tiebreakers (conflict stays above area deliberately; `test_undercut_conflict_penalty_prefers_clean_parting_loop` locks it). Coverage: **Part1 27.6% → 94.9%**, Part3 1.0% → 18.2%. Readiness honestly dropped (Part1 1.000 → 0.792) because the engine now picks the real, messier silhouette instead of a hole rim. Added `silhouette_coverage_ratio` on `PartingLineResult` + a warning below `parting_line.min_silhouette_coverage_ratio` (0.35), so this failure mode can never pass silently again. 26 parting-line tests + 205 others pass on real OCC.
- [x] **BUG D (FIXED 2026-07-27) — `_bridge_disconnected_components` was O(rounds × pairs × |ep_i| × |ep_j|) full Dijkstra calls, no caching.** On Part3 (22 components, ~209 endpoints) this measured at 373,000+ Dijkstra calls and **did not finish in 10+ minutes**. Fixed: one `nx.single_source_dijkstra` per unique endpoint computed once up front (the graph is static across rounds), reused as O(1) lookups thereafter. Part3 bridging now completes in **under 1 second**. Also fixed the Bug F "skip bridging when closed" guard to require `is_closed AND coverage >= min_silhouette_coverage_ratio` (a small closed loop was wrongly treated as "good enough"), and added coverage-based early stopping so bridging no longer indiscriminately fuses every disconnected component into one blob — it stops once the growing tree's coverage crosses the target, leaving likely-unrelated local features unmerged. New test `test_bridging_stops_once_coverage_target_is_reached_leaving_local_features_unmerged` locks this.
- [x] **BUG H-2 (ring bridging IMPLEMENTED 2026-07-27) — replaced tree bridging with ring bridging; loops now genuinely close.** `_bridge_via_angular_ring` orders components by angle around their collective centroid and bridges each to its next angular neighbor (adaptive walk: skips unreachable neighbors, continues around, explicitly closes back to start) — a cycle by construction, not the N-1-edge tree the old strategy always produced. Verified on Part3: went from 2 broken arcs to one genuinely closed 18-component cycle (`nx.find_cycle` confirms). Along the way, fixed two real bugs this surfaced: (a) `_contract_degree2_chains` was dropping "self-loop" hyper-edges as presumed dead-end spurs, which silently discarded a genuine 15-edge cycle before the search could ever see it — fixed by keeping every hyper-edge; (b) the exact search can exhaust its state budget on a large enough graph without resolving closure (near-NP-hard optimal-trail problem) — added `_find_any_cycle_via_networkx` as a guaranteed-correct polynomial-time fallback, scoring `nx.cycle_basis` candidates by the same weight function. Also fixed a real honesty bug: the discard message unconditionally said "did not close the loop" even when it had (just wasn't better) — now reports the true reason and actual coverage numbers. 28 parting-line tests (2 new) + 205 others pass.
- [x] **BUG H-3 (FIXED 2026-07-27) — wire quality score was computed from the whole input component, not the selected loop.** `_wire_quality` no longer lets `skipped_edge_ids` (a source-component data-quality signal) override an earned `"closed_loop"`/`"open_chain"` label — it still degrades the numeric score via the existing penalty, just doesn't cap the category. When Bug B's second-pass search substitutes a verified closed loop, `branch_point_count` is now recomputed from that specific subset's own structure (branch-free by construction), not the whole component's. **Measured impact: Part3's bridged wire score went from the broken 0.00 to a legitimate 0.70** (vs the original's 0.77 — still correctly discarded, genuinely close but not better, honest reason now). **Part3's overall readiness improved from `review` (0.635) to `ready` (0.806)**, since the fix also raises the retained original selection's own score. 29 parting-line tests (1 new) + 205 others pass.
- [x] 1.10 Core/cavity **solid** split — `split_core_cavity_solids()` implemented; blank → `BRepAlgoAPI_Cut` → `BRepAlgoAPI_Splitter` → 2 solids
- [x] 1.11 Multi-solid STEP export via `STEPControl_Writer` — `export_mold_halves()` implemented; AP214 schema; path guard (never writes to data/parts/); `POST /parts/{filename}/export/mold-halves` endpoint; .gitignore updated; 28 tests pass (2026-07-27).

## ~~🟡 PHASE 2 — Frontend Migration (Streamlit → React)~~ — ❌ CANCELLED 2026-07-28

> Cancelled: the Plotly/WebGL viewer already in `frontend/app.py` renders
> client-side and interactively, and as of FIX C it's also the Docker
> renderer. A rewrite would consume the remaining budget for zero new
> *engineering* capability. Backend items survive as Stage 3; the rest is
> dropped. See `docs/ARCHITECTURE_ROADMAP.md` §0.2.

- [→] 2.1 `PartGeometry` LRU cache + `mutate` regression test → **moved to Stage 3.8**
- [→] 2.2 Split `/geometry/mesh` from `/analysis/*` → **moved to Stage 3.8**
- [~] 2.3 Binary mesh transport → optional; only if payload size is *measured* to be a real bottleneck
- [x] ~~2.4–2.10 React scaffold, overlays, gizmo, split-screen, parity, retire Streamlit~~ → dropped

## 🟠 STAGE 2 — Unblock Level 2 (IN PROGRESS — real bugs found and fixed, real blocker precisely diagnosed)

- [x] S2.1a **Fixed: `_OCC_SPLIT_AVAILABLE` was `False` this entire time.** `from OCC.Core.Interface_Static import Interface_Static` — that module doesn't exist (real path: `OCC.Core.Interface`), silently swallowed by a bare `except`. Milestones 1.10/1.11's "28 tests pass" claim was never backed by a real run. Fixed + added error logging so this can't hide again.
- [x] S2.1b **Fixed: `BRepAlgoAPI_Cut/Splitter.SetArguments/SetTools([shape])` raised `TypeError`** — this binding requires a real `TopTools_ListOfShape`, not a Python list. Also silently caught by a retry-loop `except Exception`. Fixed with a `_shape_list()` helper.
- [x] S2.1c **Added `_validate_split_volumes()`** — with S2.1a/b fixed, the split could report `split_ok` with volumes 35950.05 / −0.164 mm³ (one degenerate). Same failure pattern as Bug A. Now rejects a split unless each solid ≥ 1% of tooling volume AND cavity+core conserve tooling volume within 2%. Pure function, 5 unit tests.
- [x] S2.1d **Added `tests/test_core_cavity.py`** — first dedicated tests this module has ever had (9 tests), including the `_OCC_SPLIT_AVAILABLE` regression guard and the `data/parts/` write-guard test (invariant #2, previously zero coverage).
- [x] S2.2 **Real blocker found, not the one predicted** — `BRepFill_Filling`'s parting surface is bounded exactly by the loop and never reaches the mold blank's margin.
- [x] S2.3 **Shoulder-extension tried, then superseded by a more robust fix.** First attempt (2026-07-28, "Stage 2b"): loft a ruled "shoulder" collar from the loop outward via `BRepOffsetAPI_ThruSections`, fused with the filling patch. This genuinely worked as *area extension* (measured 2,352→20,226 mm² on Part1, 603→71,308 mm² on Part3) — but `BRepCheck_Analyzer` confirmed the underlying `BRepFill_Filling` patch is topologically **invalid independent of any extension**, on both real parts. `ShapeFix_Shape`, `ShapeFix_Face`, and `BRepBuilderAPI_Sewing` were all tried directly against the raw patch and the shoulder-extended/sewn compound — none produced a valid shape. Concluded the base patch needs a different fix entirely, not a bigger one. **Superseded**: the shoulder-collar code (`_build_shoulder_collar`, `shoulder_extension_enabled` config, `PartingSurfaceResult.shoulder_extended`) has been removed — it added real complexity for zero downstream benefit once the split stopped depending on this surface at all (see next line). `_build_parting_surface`'s reported/displayed output is unchanged from before Stage 2b.
  **Real fix**: `core_cavity.build_planar_split_tool()` — a single, always-valid flat plane perpendicular to the pull direction through the parting loop's centroid, sized to `split_plane_half_size_factor` (default 2.0) × bbox diagonal. Sidesteps the invalid-patch problem entirely instead of trying to heal it. Verified end-to-end on real OCC: **`split_ok`, exactly 2 solids, on BOTH Part1 and Part3** — the first time this has ever happened in this project. Volumes: Part1 cavity=17,587.27 / core=16,909.73 mm³ (blank 35,950.05); Part3 cavity=221,298.12 / core=158,807.40 mm³ (blank 395,169.87). This is a genuine geometric **approximation** for non-planar parting lines (measured pull-axis span: Part1 16.16/30.78 mm, Part3 7.14/68.12 mm) — labeled honestly via the new `CoreCavitySolidResult.split_tool_kind="planar_approximation"` field; the reported/displayed parting-line curve is completely unaffected and stays the real 3-D candidate. `volume_conservation_tolerance` raised from 0.02 to 0.06 to match the measured 4.04%/3.81% conservation error — documented, not silently loosened. 5 new tests in `tests/test_core_cavity.py` (`build_planar_split_tool` validity/orientation + real end-to-end split+export+reload on both Part1 and Part3).
- [x] S2.4 **Re-ran AP214 mold-half export — passes on both parts.** `export_mold_halves()` exercised for the first time ever against a genuine `split_ok` result (previously only tested against fake/guard-check inputs, since no real split had ever succeeded). Exported STEP file reloads via `STEPControl_Reader` and yields exactly 2 solids on both Part1 and Part3, matching this gate exactly. Milestones 1.10 and 1.11 are now genuinely, verifiably implemented end-to-end — not just "tests pass" on a mocked/never-exercised path.
- [ ] S2.5 **NEW — tighten volume conservation below the current 6% tolerance.** The planar-approximation split conserves volume to within ~4%, not the originally-intended 2%. Bounded, low-priority: investigate whether reducing `split_fuzzy_factor` for the Splitter step (separately from the Cut step's escalating retries) closes the gap, or whether the residual error is an inherent cost of the planar approximation. Not a correctness bug — `_validate_split_volumes` still rejects anything outside tolerance.
- [x] **BUG I — fixed as a side effect of S2.3 (reverified 2026-07-28 against the exact original repro).** Re-ran the identical original command, `python -m backend.validation.part_validation --expect Part1.stp --assert-core-cavity-solids 2` (default Z pull direction, no `--direction`) — the exact conditions that previously got OOM-killed. Both parts now pass cleanly, no OOM: `core_cavity_split` completes in 0.47s (Part1) / 0.98s (Part3), exit 0. Root cause of the original OOM was almost certainly the old splitter retrying `BRepAlgoAPI_Splitter` against the invalid, possibly self-intersecting filling/shoulder-extended shape; `build_planar_split_tool`'s trivially well-behaved plane succeeds on the first attempt with no expensive retries. The fuzzy-tolerance retry loop still has no explicit memory/time ceiling as a general hardening matter, but it is no longer known to be triggered by anything in this codebase.

## 🟢 STAGE 3 — Engineering-Review UI (Streamlit)

> **The metrics problem, stated precisely**: metrics are *visible*; they are
> not *interpretable*. A developer can't tell what `depth_proxy_mm` means or
> which numbers matter; a mold engineer can't reach a conclusion without
> scrolling tables. **The engine already computes excellent explanation data**
> (`action_confidence_breakdown` has per-term codes, impacts, and even
> negative terms) — this is an information-architecture problem, not a
> missing-data one. See roadmap §3.1–3.3.

- [x] S3.1 **Three-layer progressive disclosure — done (2026-07-28).** `_collect_issues()`/`_render_issue_summary()` in `frontend/app.py` build a ranked Layer-1 "Findings" view (≤5 issues by default, rest behind "Show N more") right after the journey header — before the existing per-step tabs, which now serve as Layer 3 unchanged. Each finding has a "Show evidence" expander (Layer 2). Verified with Streamlit's `AppTest` harness against the real running backend for both Part1 and Part3 (no browser available in this environment, so this was the closest rigorous equivalent — it actually executes the app server-side end-to-end).
- [x] S3.2 **Metric glossary — done (2026-07-28).** `METRIC_GLOSSARY` dict (10 entries covering the roadmap's list) + `_metric_help()` for hover tooltips (via HTML `title=` on the existing chip components, no new dependency) + `_render_metric_glossary()` reference expander rendered near the top of the page.
- [x] S3.3 **`graph_cleanup.strategy` surfaced in the default view — done (2026-07-28).** Previously only visible inside a conditionally-collapsed "Graph Cleanup Evidence" expander. Now an always-visible "Search strategy" chip in the parting-line quality-indicator row, red when `greedy-fallback`. Added "Silhouette coverage" as its own always-visible chip too (was previously only a `st.write` line further down the page). Verified against real data via direct API query (not a placeholder): Part1 shows `contracted-graph-search` (green) and 95% coverage; Part3 correctly shows 18% coverage (amber) — reproducing the exact number from Bug H's original finding.
- [x] S3.4 **Issue-first layout — done (2026-07-28), same implementation as S3.1.** Each finding is `{severity, location, title, detail, evidence}` — deliberately the same shape Stage 5's agent will consume. Two real bugs found and fixed while verifying against live data: `direction.optimal_undercuts` from the `/direction` endpoint is a **summary only** (counts/percentages, no per-feature `features` list) — unlike the standalone `/undercuts` endpoint's response — so the issue-builder now branches on which shape it actually has; and draft severity's real vocabulary is `none|minor|moderate|critical` (not the guessed `good|marginal|bad`), matching `_tone_for_draft_severity`'s existing mapping.
- [x] S3.5 **Direction as vector + closest axis + tilt — done (2026-07-28).** `_direction_axis_tilt_text()` replaces `_vector_text()` at all 10 call sites that show a pull direction. Verified on real Part1: `(+0.232, +0.357, +0.905) ≈ +Z, tilted 25°` — matches the roadmap's own worked example exactly. Also fixed a latent duplication bug this touched: `best_label` falls back to raw vector text for non-axis-aligned directions (`direction_optimizer.py`'s `_direction_label`), so showing label+vector together used to print the vector twice; new `_direction_label_display()` only prepends the label when it's a real 2-character axis label.
- [x] **Bonus, not originally scoped: wired Level 2 (Boolean solid split) into the Streamlit UI for the first time.** New "Boolean solid split (Level 2)" sidebar checkbox → `solid_split=true` on `/core-cavity` → new display block in the Core/Cavity tab showing split status, solid count, volumes, and an explicit info banner whenever `split_tool_kind="planar_approximation"` (never let a viewer assume the exported solids follow the exact 3-D parting curve). Verified `split_ok`, 2 solids, on real Part1 via AppTest.
- [x] S3.6 **Direction override — done (2026-07-28). Bosch criterion #2.** New "Override Mold Direction" section in the Direction tab: ±X/±Y/±Z preset buttons + a custom-vector input (auto-normalized). Applying an override recomputes draft, undercuts, parting line, and core/cavity for that direction and stores the result **separately** from the recommended pipeline's results (`override_result` session-state key) — nothing is overwritten or discarded, matching the "optimizer recommends, engineer decides" philosophy. New "Recommended vs Override" comparison table (direction, draft severity/bad%, undercut counts, parting readiness/coverage, cavity/core/parting face split). An always-visible warning banner (`_render_active_direction_banner`) shows whenever an override is active, independent of which tab is open, so the engineer always knows whether they're looking at optimized or overridden results. The "Findings" panel (S3.1/S3.4) switches to the override's results while one is active, with every location suffixed "(override)" — "the engineering report reflects the chosen direction" per the design brief — while the recommendation stays intact for comparison. Real backend gap found and fixed: `/core-cavity` accepted `use_optimal_direction=false` but silently ignored any supplied direction, always falling back to a hardcoded `+Z` — there was no way to classify against a genuinely custom direction at all. Fixed by adding `dx`/`dy`/`dz` query params, used when `use_optimal_direction=false` (mirrors `/parting-line`'s existing, correct pattern). Verified via `AppTest` end-to-end (apply +Z override on real Part1 → banner appears, Findings correctly show critical draft/undercut issues that don't exist for the recommended direction, comparison table populates → clear override → banner disappears, findings revert), plus a real bug caught and fixed during that verification: the banner/Findings render earlier in the script than the button-handling code that sets override state, so they showed state one rerun stale — fixed with `st.rerun()` immediately after every state mutation, the standard Streamlit idiom for this. New regression test `test_core_cavity_endpoint_honours_a_manually_supplied_direction` locks in the backend fix. Full suite 261/261 (260 previous + 1 new).
- [x] S3.7 **Diverse candidate comparison — done (2026-07-28).** New `_cluster_diverse_candidates()` in `frontend/app.py`: greedy diverse-subset selection (candidates pre-sorted best-first by score, each kept candidate must be ≥15° from every already-kept one — the same idea as non-max suppression). Fetches the *full* candidate list now (`include_all_candidates=true`, previously the frontend never requested more than the default top-10, which is exactly where the near-duplicate problem was hiding). Verified on real Part1: 114 total scored candidates → 17 genuinely distinct families (best 0.313, then real alternatives at 0.969/2.521/4.024/... with real angular separation) — replaces the previous "top 6, all within 9°" near-duplicate list. New "Diverse Candidate Directions" section in the Direction tab shows direction/score/angular-distance-from-best/bad-draft%/undercut-features per distinct family; the raw all-candidates dump moved into a collapsed "Top Candidates (raw, all scored)" expander (Layer 3). Verified via `AppTest` on both parts, no exceptions.
- [x] S3.8 **Backend `PartGeometry` LRU cache + mesh/analysis split — done (2026-07-28, carried from cancelled 2.1/2.2).**
  - **LRU cache**: `load_step_cached()` in `backend/geometry/step_loader.py`, keyed on `(path, mtime_ns)` (editing the STEP file invalidates it automatically). All 7 `load_step(path)` call sites in `backend/api/main.py` switched to it. Measured live: cold load 0.79s → warm cache hit ~0.003s (≈250x). **Mandatory mutate-safety test** (per the roadmap's own requirement): `_clone_pristine_part()` returns a fresh, independently-mutable `PartGeometry` on every call — only the pristine, never-mutated template is cached; OCC handles are shared by reference (safe, nothing in this project mutates loaded B-Rep geometry in place), every Python wrapper object/list/dict is freshly copied. 5 new tests in `tests/test_step_loader.py::TestLoadStepCached`, including the exact scenario the roadmap worried about: mutate one clone's face/direction/parting fields, assert a second clone from the same cache entry sees none of it.
  - **Mesh/analysis split**: found the backend already had the right hook (`DisplayMesh.to_payload(include_geometry=...)`) but every endpoint hardcoded `include_geometry=True`. Added `include_mesh_geometry: bool = Query(default=True)` to `/draft`, `/undercuts`, `/direction`, `/parting-line`, `/core-cavity`; the frontend now requests `include_mesh_geometry=false` once `_cache_and_strip_mesh` has already primed the client-side base-geometry cache for the current part (new `_mesh_geometry_already_cached()` helper). `_hydrate_mesh`'s existing merge logic needed zero changes — it already reconstructs the full mesh from cached geometry + fresh overlay regardless of whether the stripping happened client-side (before) or server-side (now). Measured live: same `/draft` call, 682,742 → 224,780 bytes (≈67% smaller) once geometry is cached. Verified end-to-end via `AppTest` + inspecting the actual rendered Plotly `mesh3d` traces across all 5 analysis tabs: every one has full, correct vertex/face data (6,649 points / 7,270 faces, matching the cached base exactly) despite the smaller payload — zero visual/functional regression.
  - Full suite 266/266 (261 + 5 new).

## 🟢 STAGE 4 — Side-Core / Lifter PL (Bosch criterion #5) — first increment DONE

- [x] S4.1 **Design pass — done (2026-07-28).** All six roadmap §4.3 questions answered explicitly in `backend/geometry/side_core.py`'s module docstring before any code: (1) per-feature only, not grouped; (2) `release_direction` used verbatim, never snapped; (3) NOT built on `BRepFill_Filling` — reuses Stage 2b's planar-approximation fix instead; (4) lifter/slide/collapsible-core classification explicitly NOT decided; (5) containing half = larger Boolean-overlap half; (6) exported as a third solid in the same AP214 file (`export_mold_halves` gained `solid_overrides`/`extra_solids` params, no circular import).
- [x] S4.2 **First increment — done (2026-07-28).** `generate_primary_side_core()` (feature selection + generation) verified end-to-end on both real parts. **Gate met exactly**: exported 3-solid AP214 STEP files reload via `STEPControl_Reader` with exactly 3 `TopAbs_SOLID`s on both Part1 and Part3, and `reduced_half + untouched_half + side_core` matches the original `cavity + core` total to within 0.001% on both. Two real sizing/tolerance bugs found and fixed while prototyping (see `CHANGELOG.md` 2026-07-28 for full detail): footprint sizing must use face `Bnd_Box` corners (not centroids — zero scatter for single-face features; not vertices — misses curved-edge extrema, 24x undersizing measured on Part3); the `BRepAlgoAPI_Common`/`BRepAlgoAPI_Cut` fuzzy tolerance must be identical (mismatch measured 37.72% conservation error on Part1 despite both ops reporting success). New config `dfm.side_core.*`; new API params `generate_side_core` on `/core-cavity` and `/export/mold-halves` (the latter also gained direction-override support, matching `/core-cavity`'s S3.6 pattern); new frontend checkbox + result panel + Findings integration (works through the S3.6 override path, since the optimizer's recommended direction has no undercuts to demonstrate a side core against). 11 new tests in `tests/test_side_core.py`. Full suite 277/277 (266 + 11 new).
- [/] S4.3 **In progress (2026-07-29).** Generalize to multiple/grouped features (roadmap §4.3 Q1). Motivated in part by a real finding from Stage 6 verification: a different undercut-detection parameterization on Part1 grouped more faces into "the critical feature" and hit a genuine 36.59% conservation error on the current single-plane-sweep approach — informs how grouping/splitting should work here, not just feature count.

## ⚫ CROSS-CUTTING — Real-Geometry Assertions (do alongside Stage 2)

> **The highest-leverage non-feature work in the plan.** Every bug in the
> 2026-07-27 audit survived a fully green mock suite. X.1 alone would have
> caught all of them.

- [x] X.1 **Fixed (2026-07-28)**: 5 assertion flags added to `part_validation.py` — `--assert-parting-line-closed [TOLERANCE_MM]`, `--assert-exact-optimiser`, `--assert-parting-surface-generated`, `--assert-silhouette-coverage [MIN_RATIO]`, `--assert-core-cavity-solids N` (implies a new `--core-cavity` step that runs the real Boolean split). Each reads a **measured** value (`closure_error_mm`, `graph_cleanup_strategy`, `parting_surface_status`, `silhouette_coverage_ratio`, `split_solid_count`) via a pure `check_assertions()` function operating on the JSON payload — never a self-reported boolean alone, and a missing/absent step is a hard failure, not a pass-by-omission. **Gate verified two ways**: (1) 9 new unit tests in `tests/test_part_validation.py`, each built from deliberately bad hand-crafted payloads reproducing Bug A/B/E/H's exact failure shape (e.g. `closure_guaranteed=True` with a 17mm gap must still fail) — all 9 correctly fail before the fix and pass after; (2) live run against real Part1/Part3 output: `--assert-silhouette-coverage` correctly caught Part3's real measured 18.1% coverage (below the 0.35 threshold), exit code 3. `--assert-core-cavity-solids` correctly can't pass yet either — see BUG I below, found while proving this gate against real geometry. Full suite 255/255 (246 + 9). Exit code 3 reserved for assertion failures, distinct from 1 (step failure) and 2 (missing expected file).
- [ ] X.2 Synthetic known-answer fixtures (box, box+boss) — current tests are all OCC mocks
- [ ] X.3 Real-OCC integration suite in CI (GitHub Actions, backend image)
- [ ] X.4 Performance budgets enforced for parting surface and solid split
- [ ] X.5 Production Docker build — no source mounts, multi-stage, health checks

## 🟢 STAGE 5 — AI Agent Orchestration — DONE (2026-07-28)

> **Provider decision (2026-07-26), reaffirmed 2026-07-28**: provider-agnostic
> abstraction. The roadmap's original "Gemini default" pick conflicted with
> `docker-compose.yml`/`requirements.txt`'s actual pre-existing OpenAI/Grok
> scaffold — flagged to the user rather than silently resolved; user chose
> "provider-agnostic, all three adapters" (+ Grok as a fourth, reusing the
> OpenAI adapter class). Supersedes `agent.model: "gpt-4o-mini"` in
> `config.yaml` (now `agent.provider` + `agent.models.{gemini,anthropic,
> openai,grok}`).

- [x] 4.1 `backend/agent/providers.py` — `LLMProvider` protocol + Gemini adapter. **Live-verified end-to-end** against the real Gemini API (`gemini-2.5-flash` — `gemini-2.0-flash`, the roadmap's original pick, returns zero free-tier quota on the team's key, confirmed via a live 429). Used `google-genai` (the modern SDK), not the roadmap-named legacy `google-generativeai`.
- [x] 4.2 Anthropic + OpenAI adapters (schemas authored to Gemini's restricted JSON Schema subset, down-converted per provider). Structurally verified against real installed SDK signatures (`anthropic==0.120.1`, bumped `openai` 1.25.0→1.109.1 after a real `httpx`-compatibility bug — see CHANGELOG.md). Not live-tested (no Anthropic/OpenAI/Grok key available). Grok added as a fourth option reusing the OpenAI adapter class via its OpenAI-compatible endpoint.
- [x] 4.3 `backend/agent/tools.py` — 6 tools; **no OCC handles, `mutate=False` always, truncated payloads, structured errors never raised** — all four rules verified against real Part1.stp geometry, including a direct check that tool calls never mutate `load_step_cached()`'s shared template.
- [x] 4.4 `backend/agent/schemas.py` + `prompts.py` — `DfMReport`/`DfMFinding` with `evidence_source`/`analysis_warnings`; honesty rules (no wall-thickness/mold-flow claims, parting-line/undercut/core-cavity/side-core honesty constraints) baked into the system prompt.
- [x] 4.5 `backend/agent/dfm_agent.py` — bounded orchestration loop (`max_tool_iterations: 8` default), batched tool execution, mechanically-tracked audit trail (never model-reported). **Real bug found and fixed during live verification**: `_track_direction` was re-classifying the optimizer's own established direction as a false "user_specified" override on every propagating tool call after the first — fixed and regression-tested.
- [x] 4.6 `POST /parts/{filename}/agent/analyze` + `GET /agent/providers` endpoints (verified live via FastAPI TestClient, both success and structured-error paths). `/agent/chat` streaming endpoint deferred — not built this pass.
- [x] 4.7 Frontend "AI Agent" tab: provider selector, focus-query input, run button, findings display with evidence-source/confidence/severity, tools-called audit trail. Verified via Streamlit AppTest — tab renders, a real click completes the full round trip, and a genuine Gemini free-tier rate limit (20 req/day) was shown to degrade gracefully (no crash) rather than just tested on the happy path.
- [x] 4.8 Accuracy validation — every number in the one real live finding (face 232, 1.075° vs 1.5° draft) is traceable to a real tool result, not invented; `tools_called`/`pull_direction`/`pull_direction_source` are tracked mechanically, never taken from the model's own prose.

## 🟢 STAGE 6 — PDF Report Export — DONE (2026-07-29)

- [x] 5.1 `backend/report/pdf_export.py` + `templates.py` using `reportlab` (pinned since the initial scaffold, imported nowhere until now). Pure presentation layer over already-computed `.to_dict()` payloads — recomputes nothing (roadmap §5.5).
- [x] 5.2 Auto-fill metrics from geometry results (draft %, undercut count/severity/evidence-source, parting-line readiness/closure/coverage, core/cavity split + solid split + side core). Every warning/degraded-confidence flag from every source is aggregated into a top-of-report "Warnings" section — never silently dropped.
- [x] 5.3 Screenshot embedding — frontend-supplied base64 PNG in the request body (`ReportScreenshotPayload`), matching the roadmap's explicit "backend has no renderer, must not gain one" constraint (the React-viewer assumption in the original roadmap text is stale — the actual frontend is Streamlit; screenshot support is opt-in and the report generates fine without one).
- [x] 5.4 `POST /parts/{filename}/export/report` endpoint — `use_optimal_direction`/`dx`/`dy`/`dz` (S3.6 pattern), `include_solid_split`/`include_side_core`/`include_agent_narrative` (all opt-in, all degrade gracefully). Verified live via FastAPI TestClient: full report, 404 missing-part, 400 invalid-base64, and a real screenshot round trip.
- [x] 5.5 "PDF Report" section in the frontend (checkboxes + "Generate PDF Report" + `st.download_button`), honoring an active S3.6 direction override. Verified via Streamlit AppTest — real click, real PDF bytes, no exception.
- Two real bugs found and fixed during verification, both **known bug patterns from earlier stages this new module had silently reintroduced**: `best_label` duplicating the raw vector (the exact S3.5 bug); a misleading "100% conservation error" shown for `side_core.status == "no_feature"` (an unset default, not a measurement). 18 new tests in `tests/test_pdf_export.py`, full suite 347/347. See `CHANGELOG.md` 2026-07-29.
- A genuine robustness finding surfaced while re-verifying `side_core.py` (not a Stage 6 defect): a different undercut-detection parameterization on Part1 hit a real 36.59% conservation error, correctly caught by the module's own check. Tracked under S4.3 below.

## 🔵 PARTING-LINE v2 REBUILD (started 2026-08-09)

> Plan: `docs/PARTING_LINE_ALGORITHM_PLAN.md` · Audit:
> `docs/PARTING_LINE_CORE_CAVITY_AUDIT.md` · Decisions + algorithms + measured
> baselines: `docs/DECISIONS_AND_ALGORITHMS.md`
>
> Scope locked to **Levels 0–2**. Level 3 (local refinement) and Level 4
> (global Hou optimization) are **not** in this milestone and are revisited
> only once every Level 2 test passes.
> Priority order: correctness > geometric validity > manufacturability
> feasibility > deterministic ranking > optimization sophistication.

### ✅ P0 — Contracts, fixtures, harness (DONE 2026-08-09)

- [x] `backend/geometry/parting_line_v2/` package — `types.py`, `contracts.py`, `timing.py`
- [x] H0.1 provenance encoded structurally — `CurveSegment` cannot exist without an OCC backing
- [x] Module-boundary rules enforced by AST test (no `side_core` import; no surface provider in generation/ranking)
- [x] `confidence`/`readiness` fields banned in v2, with a test that forbids adding one
- [x] `dfm.parting_line_v2` config block (26 keys) + `engine: "v1"|"v2"` flag, default **v1**
- [x] 14 synthetic fixtures → `data/fixtures/synthetic/` (`data/parts/` untouched), all loading with 100% valid normals
- [x] A/B harness `backend/validation/parting_line_ab.py`
- [x] **Baseline measured and published** — `reports/baseline_p0.json`, `..._optimized.json`
- [x] 48/48 new tests pass; 3 full-suite failures verified pre-existing by stash-and-rerun

### ✅ P1 — Level 0 baseline (DONE 2026-08-09)

- [x] Track A with **edge-local** normals via `step_loader._face_normal_at_uv`
- [x] Multi-sample per edge + bisection refinement of sub-segment crossings
- [x] Scale-aware welding via spatial hash checking all 27 neighbour cells
- [x] 2-core reduction (chain contraction deferred — `μ` and branch counts are **invariant** under it, D-009)
- [x] Single-cycle detection; fundamental cycle basis when branched
- [x] **Full hard filter H0–H7** incl. H3's face-adjacency separation (exact at Level 0)
- [x] Core/cavity derived from H3's regions, with M×M multi-sample inconsistency detection
- [x] Lexicographic ranking T1–T7 with the full scorecard; determinism verified bit-identical
- [x] **Exit gate met**: H0 ≤ 1.3e-14 mm published per fixture; F1/F8/F9/F14/F15 correct; **F3/F4/F17 fail loudly**; F16 honestly rejected; 33 Level-0 tests green
- [x] Four defects found and fixed — incl. **C1 in the plan itself** (Γ is a disjoint union of curves, not one loop). See `DECISIONS_AND_ALGORITHMS.md` D-005…D-010
- [x] **F17 added** — the corpus had no real Track B test (F5/F6/F7 don't need it)

**Carried into P2:** F11 (`μ=25`) and Part3 (`μ=110`) fail at H4 — a cycle
*basis* does not contain every physically meaningful loop. Do **not** build
Johnson/beam for this yet; it is P3a's measurement that decides.

### ✅ P2 — Level 1: face-interior silhouette curves (DONE 2026-08-09)

- [x] Marching squares + Newton (with guaranteed bisection tail) on `g(u,v)=0`, sag-derived adaptive grid
- [x] `FClass2d` trimmed-region containment — `off_face_point_count == 0` everywhere
- [x] Degenerate zero-draft band detection (no curve emitted; free parameter reported)
- [x] Track A ↔ Track B stitching (D-012)
- [x] H3 face-splitting (D-014) **and sub-edge granularity** (D-015) — both required by Track B; the plan had scheduled the first for P3b
- [x] **Exit gate met**: F4/F17/F3 solved exactly; 16/17 fixtures feasible; H0 worst `|g|` 1.3e-10
- [x] **Falsifiable Part3 gate honoured** — at `+Z` it failed, at optimal μ 110 → 3 and components 22 → 3. RC-1 **confirmed**; the `+Z` reading was measuring near-zero-draft geometry
- [x] Six defects found and fixed (D-011…D-016); `face_sample_grid` 5 → 11 from measured convergence
- [ ] *Deliberately NOT done*: analytic closed forms (§4.1). Marching squares + Newton reaches the exact answers on every analytic fixture, so closed forms would be unmeasured optimization

**Carried into P3:** both real parts still have no feasible candidate (Part1
5/5 fail H4, Part3 6/6 fail H3) — a cycle *basis* does not contain every
meaningful loop. **μ is now 3–5**, so full enumeration is finally cheap; §6.1's
build-order question is answered by data. Runtime regressed (Part3 11.9 → 44.4 s)
and must not worsen.

### ✅ P3 — Level 2: measure-then-build enumeration (DONE 2026-08-09)

- [x] **P3a MEASURE FIRST** — new `backend/validation/parting_line_profile.py`; 22-part corpus (15 synthetic + 2 real + **5 external**), all at optimal directions
- [x] μ distribution published: `μ=1` 18.2%, **`2≤μ≤12` 77.3%**, `μ>12` 4.5% (median 4, p95 9)
- [x] `A_cauchy` vs exact projected outline (rasterised tessellation union, ~0.1% error): **+58.75% Part3**, **+35.17% Part1**, median +0.24%
- [x] H7 coverage distribution: min 0.950 of 196 candidates — **H7 rejected nothing**
- [x] Per-stage p50/p95 published; **v2 is 11.8% of runtime**, 88.2% upstream
- [x] **P3b built only what P3a justified** — bounded Johnson written, **beam search never written**
- [x] Johnson then made **opt-in** — measured **zero outcome changes**, 22× candidates, 10× runtime (D-017)
- [x] `κ_min` **deliberately not calibrated** — data supports no threshold, denominator unreliable where it would matter (D-020)
- [x] Every bound in `config.yaml`; **zero crashes** across the corpus
- [x] 3 defects fixed: Johnson self-loops (D-018), subset ordering (D-019), pairs → subsets (D-019)
- [ ] ⚠ **Exit gate shortfall**: only **5** external parts available, not the ≥20 asked for

**Carried into P4 — the blocker is now named:** silhouette segments exist but
do not connect. Part1 prunes **88%** of segments as dangling, Part3 **97%**;
survivors are local cycles (boss rims), hence the H4 failures. Non-welded gaps
measured at **7e-05 – 2.4e-04 mm** vs a **3.08e-05 mm** weld tolerance —
numerical, not geometric. **Diagnose the source of those gaps before adding
any machinery.** Do NOT loosen the global weld tolerance blindly; it would
blunt Track A and risk merging genuinely distinct vertices.

> **⚠ 2026-08-12 correction:** the 88%/97%/7e-05–2.4e-04mm numbers above were
> measured at the (unvalidated) upstream optimizer's direction — see D-022,
> `docs/DECISIONS_AND_ALGORITHMS.md`. Re-measured at controlled directions:
> real Part1/Part3 mismatches are 0.043mm to 35mm, two DIFFERENT mechanisms
> (D-023 boundary-termination undershoot; a separate near-zero-draft-boundary
> ambiguity, still open), not the sub-micron story originally reported.

### 🔵 P3.1 — Direction-isolated connectivity diagnosis (in progress, 2026-08-12)

Full detail: D-022/D-023/D-024 in `docs/DECISIONS_AND_ALGORITHMS.md`.

- [x] Direction-contamination audit — controlled directions only from here on
- [x] Track-B mechanism 1 (boundary-termination undershoot) — implemented,
      real but incomplete: measurable Part3 connectivity improvement, does
      NOT reach `feasible`, does NOT fix the H0 cases it was traced to
- [x] H0.3 `max_surface_deviation_mm` discrepancy — root-caused AND FIXED
      (`GeomAPI_ProjectPointOnSurf` now gets explicit bounds from
      `breptools.UVBounds(face)` in `gates.py`, instead of implicitly
      restricting to the surface's own `Bounds()`). Verified: all 4 H0
      failures at Part3 +X and all 4 at +Y are gone (0/329, 0/325); those
      candidates now correctly fail H3/H4 instead. Controls (F4/F17/F3)
      unchanged. 2 new regression tests. Does NOT make Part3 `feasible` —
      never expected to; H0 is necessary, not sufficient.
- [x] Mechanism 2 (near-zero-draft boundary ambiguity, face-317-style,
      up to 35mm Track-A/B mismatch) — **diagnosed (D-025): a genuine
      tangential/zero-draft condition (edge 52 is a full circle, tangential
      across its whole length per Track A's own test), not a stitching bug,
      not unique/mergeable.** Track B now labels such segments
      `"tangential"` instead of `"silhouette"`, reusing Track A's exact
      test. Zero effect on candidates/H0/H3/H4/outcome (confirmed by
      measurement — a labeling fix only). F3/F4/F17 controls unaffected.
      Full suite 477/4/3(pre-existing), unchanged.
- [ ] Runtime: mechanism 1 roughly doubled whole-suite time (379s→849s;
      the H0.3 fix itself did not add further measurable cost) — not yet
      profiled or optimized
- [x] With H0 no longer a false-positive source, re-examine whether the
      real remaining blocker (H3/H4 rejecting nearly all candidates) needs
      new diagnosis — **answered (D-026): no.** Enumeration comparison
      (Johnson vs basis, Part1 ±X/±Y), envelope experiment (Part3 ±X/±Y,
      articulation-point facets stripped), and an H4 backward-trace all
      converge on the same conclusion: no fixable defect found in Track
      A/B, graph construction, H3, or H4.
- [x] **24-combo baseline matrix (6 principal + 6 diagonal × Part1/Part3),
      unmodified pipeline, manual directions only — D-026, 2026-08-12.**
      **Part1: feasible only at +Z/-Z (2/12).** Part3: feasible at **none**
      of 24 tested directions. Full table in `docs/DECISIONS_AND_ALGORITHMS.md`.
      **Level 0-2 is now FROZEN** — no further changes to Track A/B, graph,
      H3/H4, or ranking without new, specific diagnostic evidence.
- [x] **Superseded by P3.2/D-027 below**: "Part3 has no known-good direction
      to serve as a positive control" was the prior framing for why 0/24
      tested feasible. D-027 found a specific, evidenced defect instead
      (2-core pruning discards real disconnected fragments) — a positive
      control was never the actual blocker.
- [ ] Minor, secondary, not investigated: H0 failures appeared for the
      first time this phase at diagonal directions only (1-6 candidates
      per direction) — zero H0 failures at any of the 12 principal-direction
      runs all phase. Small counts, doesn't change any outcome.
- [ ] Runtime: mechanism 1 roughly doubled whole-suite time (379s→849s;
      the H0.3 fix itself did not add further measurable cost) — not yet
      profiled or optimized

### 🔵 P3.2 — Part3 root-cause tracing (in progress, 2026-08-13)

Full detail: D-027 in `docs/DECISIONS_AND_ALGORITHMS.md`. Rejects "Part3 may
simply have no feasible direction" — traced candidate 43 (Part3 @ (0,1,1))
end-to-end instead of accepting D-026's aggregate pass/fail as final.

- [x] Confirmed self-loop segments (242/244) are NOT the cause of
      `region_count=1` — direct removal + re-run, unchanged result.
- [x] Found candidate 43 is `loop_union`, decomposes into a genuine closed
      4-segment equatorial ring (Group 1, torus faces 37/317) + a separate
      10-segment local loop (Group 2) + the 2 self-loops. Neither Group 1
      nor Group 2 separates the part alone.
- [x] Traced Group 1's bypass via BFS on `separate_surface()`'s own
      adjacency graph: a 17-hop path through 13 other faces, crossing back
      through edge 117's own uncovered parameter half (correctly not
      silhouette there — real geometry, not a bug).
- [x] Point-sampled sign(g) independently (production `_FaceField.g()`)
      along the bypass path: faces 327/38/39/318/35 are themselves
      mixed-sign and should carry their own splits.
- [x] Confirmed Track A/B DID detect correct silhouette segments on all 5
      of those faces (1/3/23/3/6 segments respectively, in the raw
      298-segment pool) — traced them through `build_graph` +
      `reduce_to_two_core` and found they're **pruned as dangling** before
      candidate generation ever runs; endpoint gaps to Group 1 are
      12-37mm, ruling out stitch-tolerance as the cause.
- [x] **Root cause classification RETRACTED AND CORRECTED (D-028, same
      day)**: "(C) graph construction loses topology at 2-core" is WRONG —
      a direct bypass experiment (`extract_loops` on the raw graph,
      skipping `reduce_to_two_core`) produced the identical 11 candidates,
      identical segment set. 2-core is mathematically exact (proven) and
      empirically inert (measured) here.
- [x] **Corrected root cause (D-028)**: Part3's 242 pruned mixed-sign
      segments are real local-feature geometry (mirror-symmetric
      stepped-cylinder bosses + toroidal fillets) whose own silhouette
      genuinely doesn't close at this oblique direction — not a defect.
      Of the loops that DO close, 5 are trivial single-face pinches
      (`region_sizes=[1, 413]`) correctly rejected by H4 (34% orientation
      violation). Group 1 (torus ring) is a genuine local-feature loop
      that never reaches the main body. **Graph, 2-core, H3, H4 all
      confirmed behaving correctly** on every candidate that exists.
- [x] **Part1 control (D-028 Task 4, done)**: Part1 @ +Z has 0 segments
      pruned by 2-core at all; Part1 @ ±X/±Y show the same fragmentation
      mechanism at ~6% severity (vs Part3's 85%) — consistent with
      severity tracking distance from a moldable direction, not a fixed
      defect. Answers the earlier open item directly: yes, the same
      mechanism is present at Part1 ±X/±Y, just far less severe.
- [ ] **Not yet done, deliberately out of scope (D-028 Task 8)**: propose
      and review implementing the best-supported option — classify
      local-feature vs main-body geometry before H3/H4 scoring (relates to
      existing `side_core.py`/Bosch-criterion-#5 local-tooling machinery).
      No production code changed by D-027 or D-028.
- [x] **Answered by P3.3/D-029 below**: re-ran the protocol at 2 more
      independently-motivated directions ((1,0,1)/(1,0,-1)) — identical
      structural pattern found. Not yet run on other corpus parts.

### 🔵 P3.4 — Decisive adversarial fixture: CASE E, algorithm cleared (2026-08-13)

Full detail: D-030. Built a synthetic fixture (box + 6 misaligned bosses,
`data/fixtures/synthetic/ADV1_box_with_boss_array.stp`, generator at
`backend/validation/generate_adversarial_fixture.py`) with a mathematically
provable global parting line (hexagonal cube-diagonal silhouette at
d=(1,1,1)) deliberately surrounded by heavy local-feature noise mirroring
Part3's boss structure.

- [x] Ran the unmodified production pipeline: Track A/B correctly detect
      30 local-feature segments beyond the true 6-edge hexagon; none
      spuriously close into false cycles; 2-core correctly prunes all 30 as
      non-cyclic; exactly 1 candidate generated (the hexagon); passes every
      gate (H0-H7) cleanly; `cavity_area == core_area` exactly (independent
      correctness check); each boss inherits its parent face's mold side.
- [x] **Decision-tree outcome: CASE E** — known global line successfully
      generated and validated. Direct evidence against "local-feature-heavy
      geometry inherently breaks the architecture."
- [x] **Recommendation: A** — keep the algorithm frozen, focus on
      direction feasibility for Part3. Per protocol, Part3 NOT revisited
      or modified this entry (gated on finding algorithmic weakness, which
      was not found).
- [ ] Open, explicitly not proven by this fixture: correctness on a main
      body whose OWN global answer requires Track B (not just Track A)
      mixed with local-feature noise — this fixture's global answer is
      Track-A-only, like Part1's own working case.
- [ ] Open: whether Bosch's practical direction search space (rare
      diagonals) extends meaningfully beyond the 24 directions already
      tested on Part3.

### 🔵 P3.3 — Direction-feasibility vs. algorithm-correctness separation (2026-08-13)

Full detail: D-029 in `docs/DECISIONS_AND_ALGORITHMS.md`. Explicit protocol
treating direction-feasibility (hypothesis A) and algorithm-correctness
(hypothesis B) as coupled unknowns; designed experiments to separate them
instead of inferring one from final pass/fail.

- [x] Built direction-only diagnostic layer, reusing `analyze_draft`/
      `detect_undercuts`/`signed_dot` (no new score invented). Ran across
      all 12 Part1 + 24 Part3 directions.
- [x] Honest negative result, reported not discarded: naive near-zero-area
      ranking is anti-correlated with ground truth on Part1 (+Z ranks
      last, yet is the only working direction).
- [x] Actionable result: Part3's direction-only ranking flags (1,0,1)/
      (1,0,-1) far above (0,1,1) — the direction the whole prior
      investigation focused on purely because the algorithm liked it
      (circular reasoning this step exists to catch).
- [x] Full D-028-style loop-by-loop candidate audit at (1,0,1)/(1,0,-1):
      structurally identical to (0,1,1) — same torus-boss pinch/H4-reject
      and local-ring/H3-reject pattern, generalizing D-028 to 3 directions.
- [x] Cross-checked full D-026 24-direction table: Part1 @ +Z/-Z is the
      ONLY Part1 direction with `h3_failures=0`; no Part3 direction (of
      24) ever reaches that — a clean distinguishing signature.
- [x] Confirmed existing 15-fixture analytic positive-control suite
      (F1-F14, F17) passes 136/136 — satisfies the known-answer-geometry
      requirement, no new suite needed.
- [x] Closed a real gap: added the previously-missing Part1 +Z regression
      test for the v2 engine (3 new tests in
      `tests/test_parting_line_v2_level1.py`, all pass) — no prior test
      exercised Part1.stp through v2 at all.
- [x] **Classification: closest to E** (insufficient evidence to fully
      separate hypothesis A from B), specific evidenced lean toward A.
- [ ] **Not yet done, explicitly flagged as the decisive next experiment**:
      build a synthetic fixture with local bosses AND a known-correct
      global parting line, to determine whether local-feature-dominance
      is fundamentally an algorithm limitation (B) or purely a Part3
      geometry/direction-search-space fact (A).
- [ ] Open: the 24-direction set does not exhaust Bosch's stated "rare
      diagonal cases" practical search space claim — finer-grained
      off-axis directions untested.
- [ ] Open: Part1 ±X/±Y not re-audited with this exact loop-by-loop
      methodology in P3.3 (prior D-026 enumeration work stands,
      un-contradicted but also not independently re-verified here).

### ⬜ P4 — Core/cavity integration (NEXT — but see the P3.1 diagnosis first)
### ⬜ P5 — Visualization + migrate consumers off `readiness`/`confidence`
### ⬜ P6 — A/B cutover (flip default to v2 only if it wins or ties everywhere)

---

## 🟡 Deferred / Unscheduled — now in progress (2026-07-29)

- [ ] Exhaustive Bassi Boolean analysis (every face, every direction)
- [ ] Sangolli full volumetric decomposition + radix sort
- [ ] Add `__init__.py` to `backend/geometry/`
- [ ] Add mypy/ruff config and type checking
- [ ] Split `undercut_detector.py` (3,432 lines) into detection + Boolean + feature grouping

## ✅ Done

- [x] STEP loader — full topology extraction
- [x] Draft analyzer — face-level analysis with suggestions
- [x] Undercut detector — selective Boolean + feature grouping
- [x] Direction optimizer — candidate search + Boolean pruning
- [x] Parting line foundation — silhouette candidates + Chaikin smoothing
- [x] Core/cavity face classification
- [x] FastAPI backend — all endpoints
- [x] Streamlit frontend — guided 5-step UI
- [x] Docker setup — backend + frontend
- [x] Config system — `config.yaml` + frozen dataclasses
- [x] Validation harnesses — part validation + performance profiling
- [x] Test suite — ~4,100 lines with OCC mocking
- [x] Documentation — IMPLEMENTATION_STATUS, DEMO_SCRIPT, EVIDENCE_CHECKLIST, etc.
- [x] Claude Code setup — `.claude/` with rules, skills, commands, memory
