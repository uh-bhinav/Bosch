# TODO — DfM Agent

> **Prioritized task list.** Update after each session. Mark items `[x]` when done, `[/]` when in progress.

---

> **Master plan**: `docs/ARCHITECTURE_ROADMAP.md` holds the full 4-phase
> specification, algorithms, config keys, and per-milestone validation gates.
> The items below are its execution checklist.

---

## 🔴 P0 — Blockers (fix before any other work)

- [x] **F1 — `Part1.stp`/`Part3.stp` identity resolved (2026-07-27)**: confirmed genuine mix-up; `rename.stp` (`Element_Packaging_Cap.stp`, 522,419 B) has been restored as `Part1.stp`. Verified: `Part1.stp` = 522,419 B / MD5 `d0c89a7c…` (Level 1), `Part3.stp` = 863,881 B / MD5 `a373ffdf…` (Level 2) — two distinct files, `rename.stp` no longer exists. STEP schema confirmed as AP214 (`AUTOMOTIVE_DESIGN`) — Phase 1.11's mold-half export targets AP214 to match.
- [x] **F2 — fixed**: `dfm.core_cavity.threshold` added to `config.yaml` + `CoreCavitySettings`; `classify_core_cavity()` and the `/core-cavity` endpoint now default from settings instead of a hardcoded `0.05`.
- [x] **F3 — fixed**: `.claude/rules/api-layer.md` now documents `include_mesh` / `include_boolean_regions` as query flags on the real endpoints instead of two nonexistent routes.
- [x] **F4 — resolved (Milestone 1.6, 2026-07-27)**: `networkx` is now imported and used in `parting_line.py`. `_trace_best_weighted_path` uses `nx.MultiGraph` for the candidate edge graph instead of a hand-rolled `point_to_edges` dict. Adjacency queries, branch-point counting, and neighbor traversal all go through the networkx graph. The existing DFS and greedy traversal paths continue to work unchanged (verified: all 23 `tests/test_parting_line.py` tests pass).
- [x] **F5 — fixed (2026-07-27)**: documented test command (`docker compose exec backend pytest tests/ -v --tb=short`) never worked — no root `conftest.py`/`pytest.ini` puts `/app` on `sys.path`. Fixed with `pythonpath = ..` in `tests/pytest.ini`.
- [x] **F6 — fixed (2026-07-27)**: Streamlit frontend crashed on macOS with `tornado.websocket.WebSocketClosedError` flood during "Full Level 1 Flow". Root cause: 6 full mesh copies (~500 KB each) in `st.session_state` → RAM exhaustion. Fixed with `_cache_and_strip_mesh` (cache geometry once after first step, strip points/faces from subsequent results) + `_hydrate_mesh` (restore at render time) + `dfm.display.max_triangle_count: 100000` ceiling in `build_display_mesh()`. Changed files: `frontend/app.py`, `backend/geometry/visualize_raw.py`, `backend/config.py`, `config.yaml`.
- [x] **Run Docker validation with real OCC and commit the artifacts (2026-07-27)** — real (non-`skipped`) evidence in `reports/level1_validation/*_docker_20260727*`; both parts pass every stage. Authoritative post-Milestone-1.2 run: `part_validation_docker_20260727_post_1.2.json` + `performance_profile_part{1,3}_20260727.json` — combined `direction_search` time dropped from ~713s (pre-1.2) to ~15s (post-1.2, calm environment).
- [x] **Fix overclaims in SUBMISSION_REPORT.md** — already fixed during Phase 0 (2026-07-27): `docs/SUBMISSION_REPORT.md` evaluation matrix now says "Candidate/foundation" for parting line and "Complete for face classification only" for core/cavity.
- [ ] **Investigate genuine test failure** — `test_api_error_handling.py::test_parting_line_paths_payload_is_json_safe` fails for real (surfaced once F5's import bug was fixed, 2026-07-27)
- [ ] **Test-suite hygiene: mock-based tests need explicit `boolean_refine=False`** — found 2026-07-27 while verifying Milestone 1.2. Any test building a mock `PartGeometry` (`occ_face=MagicMock()`) and calling `detect_undercuts()`/`optimize_mold_direction()` without `boolean_refine=False` stalls for minutes against a container with real pythonocc-core installed (the mock isn't a valid SWIG-wrapped OCC object, and it gets fed straight into real `BRepAlgoAPI_Common`/`BRepPrimAPI_MakePrism` calls). This was invisible before F5 was fixed, since Docker test runs never worked at all. Affects at least `test_undercut_detector.py::test_detect_undercuts_flags_zero_draft_face`; needs an audit pass across `test_undercut_detector.py` and `test_direction_optimizer.py`.

## ❓ Needs a team decision

- **Undercut depth: precision vs. conservative safety margin.** `UndercutFeature.depth_proxy_mm` (feature-level) deliberately takes the *largest* of several depth candidates (precise Boolean-vertex evidence, a cruder centroid-projection proxy, and bounding-box spans) rather than preferring the precise one — likely intentional (safer to overestimate undercut depth than underestimate it), but this contradicts the *per-face* `BooleanInterferenceMetrics.depth_mm`, which deliberately prefers precision. Both are tested; nobody has reconciled the inconsistency. Decide: keep feature-level as a conservative upper bound (document it as such), or make it prefer precision too (drafted fix exists, reverted 2026-07-27 — see `docs/ARCHITECTURE_ROADMAP.md` Milestone 1.3 note)?

## 📌 Decisions locked in (2026-07-27)

- **STEP export schema**: match source files — AP214 (`AUTOMOTIVE_DESIGN`), confirmed via `FILE_SCHEMA` in `Part1.stp`/`Part3.stp`. Consistent with the Siemens NX origin of the input files.
- **PDF export**: still a deliverable. Scheduled as **Phase 5**, tackled after Phase 4 (agent layer) — not dropped, just sequenced last.
- **Texture marking**: selectable in the UI (Phase 1e option 1 — explicit per-face override from user selection), not inferred from surface type alone.

## 🟠 PHASE 1 — Geometry Engine Hardening

- [x] 1.1 Edge convexity computation in `step_loader.py` → populates `EdgeData.convexity` at load time (was always `None`). Verified: plain box → 12/12 convex; box-with-pocket → pocket floor's 4 edges concave; real `Part1.stp` → >90% of manifold edges classified. New config: `dfm.undercut.convexity_tangent_tolerance` (0.01). Tests: `tests/test_step_loader.py::TestEdgeConvexitySynthetic`.
- [x] 1.2 Convexity-gated undercut false-positive suppression in `detect_undercuts()`. Verified on real parts (suppression on/off): Part1 undercut count 44→18, Boolean-checked 78→27, 45.2s→13.4s; Part3 undercut count 16→0, Boolean-checked 97→3, 73.6s→1.9s. **Part3's 100% swing flagged for domain/visual review**, not just accepted. New: `UndercutDetectionResult.convexity_suppressed_face_ids`, config `dfm.undercut.convexity_suppression_enabled` (kill switch). Tests: `tests/test_undercut_detector.py` (4 new, mock-based).
- [x] 1.3 **Reassessed, no code change (2026-07-27)**: per-face depth (`_select_boolean_depth_details`) already does exact-vertex-first prioritization correctly (4 passing tests confirm). Feature-level aggregation deliberately takes the *largest* plausible estimate (conservative safety margin, not a bug) — an attempted "prefer precision" fix was reverted after it broke 3 tests with exact numeric assertions. See `docs/ARCHITECTURE_ROADMAP.md` Milestone 1.3 note. **Needs a team decision**, not something to silently change.
- [x] 1.4 Flash risk penalty term + coarse-to-fine (±5°) direction search. Verified on real geometry: Part1 best_score 0.692→0.313 (−54.8%), Part3 6.415→1.384 (−78.4%), both finding a genuinely better direction, +60 candidates as designed, no timing regression. New config: `flash_risk_weight`, `flash_angle_threshold_deg`, `flash_thin_area_factor`, `fine_search_enabled`, `fine_search_top_k`, `fine_angular_step_deg`, `fine_search_cone_half_angle_deg`, `fine_search_max_candidates`. Tests: `tests/test_direction_optimizer.py` (8 new, mock-based).
- [x] 1.5 Draft conditional thresholds — **scoped to explicit override → global default** (tiers 2/3 deliberately deferred, see roadmap note: surface-type defaults are a no-op today per the honesty ruling, deep-rib auto-detection needs real geometric work not yet done). `analyze_draft(..., face_conditions={face_id: "light_texture"|"heavy_texture"|"deep_rib"|"smooth"})`. Verified on real Part1.stp. New config: `dfm.draft.conditions.*`. Tests: `tests/test_draft_analyzer.py::TestFaceConditionThresholds` (6 new). API wiring deferred to Phase 2 (needs a frontend picker to call it from).
- [ ] 1.6 Replace bounded DFS with a real `networkx` graph in `parting_line.py`
- [x] 1.7 Bridge disconnected silhouette components via real B-Rep edges (`EdgeData.is_boundary`) — `_bridge_disconnected_components()` added; `detect_parting_line_candidates` wired with `bridge_components` param; all 23 parting line tests pass unchanged (2026-07-27).
- [x] 1.8 Guaranteed closed loop — `_attempt_loop_closure()` added; `PartingLineResult` gets `closure_error_mm` and `closure_guaranteed` fields; closure error gating added (downgrade to "review" if > 0.05 mm and no closing path found); all 23 tests pass (2026-07-27).
- [x] 1.9 Parting surface — `_build_parting_surface()` implemented: PCA planar extrusion first (`BRepBuilderAPI_MakeFace` + `BRepPrimAPI_MakePrism`), `BRepFill_Filling` fallback; `PartingSurfaceResult` dataclass added; `PartingLineResult.parting_surface` field added; all 23 tests pass (2026-07-27).
- [x] 1.10 Core/cavity **solid** split — `split_core_cavity_solids()` implemented; blank → `BRepAlgoAPI_Cut` → `BRepAlgoAPI_Splitter` → 2 solids
- [x] 1.11 Multi-solid STEP export via `STEPControl_Writer` — `export_mold_halves()` implemented; AP214 schema; path guard (never writes to data/parts/); `POST /parts/{filename}/export/mold-halves` endpoint; .gitignore updated; 28 tests pass (2026-07-27).

## 🟡 PHASE 2 — Frontend Migration (Streamlit → React + Vite + Three.js)

- [ ] 2.1 `PartGeometry` LRU cache keyed on `(path, mtime_ns)` + `mutate` regression test
- [ ] 2.2 Split `/geometry/mesh` (fetch once) from `/analysis/*` (no mesh in payload)
- [ ] 2.3 Binary mesh transport — base64 typed arrays, not JSON decimals
- [ ] 2.4 Vite + react-three-fiber scaffold
- [ ] 2.5 Client-side overlay switching via the `faceId` vertex attribute (zero refetch)
- [ ] 2.6 Parting-line fat lines + translucent undercut volumes
- [ ] 2.7 Draggable pull-direction gizmo
- [ ] 2.8 Split-screen before/after with shared camera
- [ ] 2.9 Panels + report view at parity with Streamlit
- [ ] 2.10 Retire `frontend/app.py` (3,966 lines) once React reaches parity

## 🟢 PHASE 3 — Real-World Testing & Production

- [ ] 3.1 Synthetic known-answer fixtures (box, box+boss) — current tests are all OCC mocks
- [ ] 3.2 Real-OCC integration suite running in Docker
- [ ] 3.3 Assertion flags in `part_validation.py` (`--assert-parting-line-closed`, `--assert-core-cavity-solids=2`)
- [ ] 3.4 Part3 Level 2 pass — solid split + export
- [ ] 3.5 Performance budgets for parting surface and solid split
- [ ] 3.6 Production Docker build — no source mounts, no Xvfb, multi-stage frontend
- [ ] 3.7 CI pipeline (GitHub Actions) running the OCC suite in the backend image

## 🔵 PHASE 4 — AI Agent Orchestration

> **Provider decision (2026-07-26)**: provider-agnostic abstraction with
> **Gemini as default** (cheaper, easier to test), Anthropic and OpenAI as
> swappable adapters. This supersedes `agent.model: "gpt-4o-mini"` in
> `config.yaml`.

- [ ] 4.1 `backend/agent/providers.py` — `LLMProvider` protocol + Gemini adapter
- [ ] 4.2 Anthropic + OpenAI adapters (author schemas to Gemini's JSON Schema subset — the most restrictive)
- [ ] 4.3 `backend/agent/tools.py` — 6 tools; **no OCC handles, `mutate=False` always, truncated payloads**
- [ ] 4.4 `backend/agent/schemas.py` + `prompts.py` — `DfMReport` with `evidence_source`; honesty rules in the system prompt
- [ ] 4.5 `backend/agent/dfm_agent.py` — bounded orchestration loop (`max_tool_iterations: 8`)
- [ ] 4.6 `/agent/analyze` + `/agent/chat` endpoints
- [ ] 4.7 Frontend agent panel with evidence-source badges
- [ ] 4.8 Accuracy validation — every number traceable to a tool result

## 🟣 PHASE 5 — PDF Report Export

Confirmed deliverable, deliberately sequenced last — needs a stable engine
(Phase 1), a UI to source screenshots/data from (Phase 2), and, ideally, agent
narrative content (Phase 4) to embed.

- [ ] 5.1 `backend/report/pdf_export.py` using `reportlab` (already pinned, unused)
- [ ] 5.2 Auto-fill metrics from geometry results (draft %, undercut count/severity, parting-line readiness, core/cavity split)
- [ ] 5.3 Embed viewport screenshots (from the React viewer) or generate charts
- [ ] 5.4 `POST /parts/{filename}/export/report` endpoint
- [ ] 5.5 "Export PDF Report" action in the frontend

## ⚪ Deferred / Unscheduled

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
