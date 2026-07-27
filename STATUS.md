# Project Status — DfM Agent

> **Last updated**: 2026-07-27  
> **Update this file after every change session.**
>
> **Master plan**: `docs/ARCHITECTURE_ROADMAP.md` — 4-phase specification
> (geometry hardening → frontend migration → real-world testing → AI agent),
> with algorithms, config keys, and per-milestone validation gates.
> Execution checklist: `TODO.md`.

## ⚠️ Open Blockers

| ID | Issue | Impact |
|---|---|---|
| ~~**F4**~~ | ~~`networkx==3.3` pinned in `requirements.txt`, imported nowhere.~~ | **Resolved 2026-07-27 (Milestone 1.6)**: `networkx` imported in `parting_line.py`; `_trace_best_weighted_path` now uses `nx.MultiGraph` for adjacency instead of hand-rolled `point_to_edges` dict. All 23 parting line tests pass unchanged. |
| **F6** | Streamlit frontend floods terminal with `tornado.websocket.WebSocketClosedError` / `StreamClosedError` when running "Full Level 1 Flow" on macOS; laptop crashes. Root cause: 6 full copies of the same mesh geometry (points+faces, ~500 KB each) accumulated in `st.session_state` — one per analysis step — causing RAM exhaustion and Tornado WebSocket buffer failures. | Fix applied 2026-07-27: `_cache_and_strip_mesh` caches base mesh once after the first step and strips `points`/`faces` from subsequent results; `_hydrate_mesh` merges cached geometry back at render time. Also added `dfm.display.max_triangle_count: 100000` triangle ceiling in `build_display_mesh()`. Verification: load Part3.stp + "Full Level 1 Flow" on macOS — no WebSocketClosedError, RSS stays under ~500 MB. |
| — | `test_api_error_handling.py::test_parting_line_paths_payload_is_json_safe` fails for real (not the F5 import bug — surfaced once F5 was fixed). | Stale test assertions. `raw.visible_by_default` asserts `False` but code sets `True`; `legend.refined.label` asserts old string. Fix: update assertions (Phase 2a). |
| — | Mock-based tests (`occ_face=MagicMock()`) calling `detect_undercuts()`/`optimize_mold_direction()` without explicit `boolean_refine=False` stall for minutes against real pythonocc-core — the mock isn't a valid SWIG-wrapped OCC object and gets fed into real Boolean calls. Invisible until F5 was fixed. | Needs a test-suite hygiene audit across `test_undercut_detector.py` and `test_direction_optimizer.py`. Found 2026-07-27 while verifying Phase 1.2. |
| — | Part3.stp's undercut count drops to 0 with convexity suppression enabled (was 16). Logic is verified (synthetic box/pocket + 4 unit tests) but a 100% swing on a real part needs a mold engineer's visual sanity check before being trusted in a demo. | Domain analysis (Phase 2e): if ALL 16 originally flagged faces sit on external convex features (bosses, ribs with all-convex edge transitions), suppression to 0 is geometrically correct — those faces have no concave edges, so they cannot be pockets. However, a 100% swing warrants Docker verification: run with `convexity_suppression_enabled: false` vs `true`, compare suppressed face_ids, surface types, and edge convexity classifications. Needs mold engineer sign-off before the result is used in demo claims. |

## ✅ Resolved

| ID | Issue | Resolution |
|---|---|---|
| **F1** | `Part1.stp` and `Part3.stp` shared an MD5 (`a373ffdf…`, 863,881 B, both with internal `FILE_NAME 'Part3.stp'`) — a genuine mix-up. | Fixed by restoring `rename.stp` (`Element_Packaging_Cap.stp`) as `Part1.stp`. Verified 2026-07-27: `Part1.stp` = 522,419 B / MD5 `d0c89a7c…` (Level 1), `Part3.stp` = 863,881 B / MD5 `a373ffdf…` (Level 2) — distinct files, both AP214, `rename.stp` no longer exists. Further verified via real OCC load: Part1 = 311 faces/30.78mm bbox, Part3 = 414 faces/68.12mm bbox — genuinely different geometry, consistent with Level 1 (simple) vs Level 2 (complex). |
| **F2** | `core_cavity.py` docstring cited a nonexistent config key; `threshold=0.05` was hardcoded in the module and `main.py`. | Fixed 2026-07-27: `dfm.core_cavity.threshold` added to `config.yaml` and `CoreCavitySettings`; `classify_core_cavity()` and the `/core-cavity` endpoint now default from settings, not a literal. |
| **F3** | `.claude/rules/api-layer.md` listed `/display-mesh` and `/boolean-regions` endpoints that don't exist. | Fixed 2026-07-27: corrected to document `include_mesh` / `include_boolean_regions` as query flags on the real analysis endpoints. |
| **F5** (new, found during Phase 0.4) | The documented test command (`docker compose exec backend pytest tests/ -v --tb=short`, from `CLAUDE.md`) never actually worked in a clean container — no root `conftest.py` or root `pytest.ini` puts `/app` on `sys.path`, so every test failed collection with `ModuleNotFoundError: No module named 'backend'`. A root `conftest.py` doesn't fix it either: `tests/pytest.ini` being the discovered config file pins pytest's `confcutdir` to `tests/`, blocking discovery of any parent conftest. | Fixed 2026-07-27 with `pythonpath = ..` added to `tests/pytest.ini` — pytest's native option for exactly this layout. Verified with the exact documented command. |
| Real OCC validation | Every saved validation report showed `status: "skipped"` (no OCC in the test env). | Fixed 2026-07-27: ran `part_validation.py` and `performance_profile.py` with real pythonocc-core in Docker; both Part1 and Part3 pass every stage. Authoritative (post-Milestone-1.2) evidence: `reports/level1_validation/part_validation_docker_20260727_post_1.2.json`, `performance_profile_part1_20260727.json`, `performance_profile_part3_20260727.json`. Combined `direction_search` time for both parts dropped from ~713s (pre-1.2, contention-inflated) to ~15s (post-1.2, calm) — Milestone 1.2's Boolean-call reduction compounds across every candidate direction in the search. |

## Module Status

| Module | File | Lines | Status | Notes |
|---|---|---|---|---|
| STEP Loader | `backend/geometry/step_loader.py` | 1,010 | ✅ Done | Loads Part1.stp, extracts full topology |
| Draft Analyzer | `backend/geometry/draft_analyzer.py` | 772 | ✅ Done | Face-level draft with suggestions |
| Undercut Detector | `backend/geometry/undercut_detector.py` | 3,432 | ✅ Done | Selective Boolean refinement + feature grouping |
| Direction Optimizer | `backend/geometry/direction_optimizer.py` | 909 | ✅ Done | Candidate search + Boolean pruning |
| Parting Line | `backend/geometry/parting_line.py` | ~3,200 | ✅ Substantial | networkx graph (1.6), component bridging (1.7), closure guarantee (1.8), PCA parting surface (1.9); full Hou global optimization not yet applied |
| Core/Cavity | `backend/geometry/core_cavity.py` | ~500 | ✅ Substantial | Face classification (Level 1) + Boolean solid split (1.10) + AP214 STEP export (1.11) |
| Visualize Raw | `backend/geometry/visualize_raw.py` | ~380 | ✅ Done | Display mesh with face_id mapping + triangle ceiling (Phase 0) |
| Data Models | `backend/models/geometry_models.py` | 762 | ✅ Done | Shared dataclasses |
| Config | `backend/config.py` | ~600 | ✅ Done | Frozen settings; DisplaySettings, PartingSurfaceSettings added |
| FastAPI Backend | `backend/api/main.py` | ~1,080 | ✅ Done | All endpoints + solid_split param + POST /export/mold-halves |
| Streamlit Frontend | `frontend/app.py` | 3,966 | ✅ Done | Guided 5-step UI with PyVista. **Slated for replacement** — see Roadmap Phase 2 |
| React Frontend | `frontend-web/` | — | 📋 Planned | React + Vite + Three.js. Roadmap Phase 2 |
| AI Agent | `backend/agent/dfm_agent.py` | 0 | ❌ Empty | Not started. Roadmap Phase 4 |
| Agent Tools | `backend/agent/tools.py` | 0 | ❌ Empty | Not started. Roadmap Phase 4 |
| Agent Providers | `backend/agent/providers.py` | — | 📋 Planned | Provider-agnostic; **Gemini default**, Anthropic/OpenAI swappable |
| Validation | `backend/validation/part_validation.py` | 526 | ✅ Done | Smoke tests for all steps |
| Performance | `backend/validation/performance_profile.py` | 448 | ✅ Done | Timing budgets |
| PDF Export | — | 0 | ❌ Missing | No code exists |

## Test Status

| Test File | Lines | Last Known Status |
|---|---|---|
| `test_step_loader.py` | 393 | Needs OCC for full run |
| `test_draft_analyzer.py` | 573 | Passes with mocks |
| `test_undercut_detector.py` | 1,565 | Passes with mocks |
| `test_direction_optimizer.py` | 382 | Passes with mocks |
| `test_parting_line.py` | 720 | Passes with mocks |
| `test_part_validation.py` | 230 | Passes |
| `test_performance_profile.py` | 89 | Passes |

## Data Status

STEP schema: `AUTOMOTIVE_DESIGN` (AP214), per `FILE_SCHEMA` in the source files.
Any future STEP export (mold-half solids, Phase 1.11) targets AP214 to match.

| File | Size | MD5 | Role | Status |
|---|---|---|---|---|
| `data/parts/Part1.stp` | 522,419 B | `d0c89a7c…` | Level 1 input | ✅ Present — restored/confirmed genuine (2026-07-27) |
| `data/parts/Part3.stp` | 863,881 B | `a373ffdf…` | Level 2 input | ✅ Present — confirmed genuine (2026-07-27) |
| `data/parts/Part2.stp` | — | — | — | ❌ Not present (see `docs/IMPLEMENTATION_STATUS.md`) |

(`rename.stp` no longer exists — its content is now `Part1.stp`.)

## Infrastructure

| Component | Status |
|---|---|
| Docker (backend + frontend) | ✅ Configured |
| Conda environment | ✅ `environment.yml` defined |
| Config system | ✅ `config.yaml` + frozen dataclasses |
| `.claude/` setup | ✅ Complete |
