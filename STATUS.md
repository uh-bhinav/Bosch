# Project Status — DfM Agent

> **Last updated**: 2026-07-26  
> **Update this file after every change session.**
>
> **Master plan**: `docs/ARCHITECTURE_ROADMAP.md` — 4-phase specification
> (geometry hardening → frontend migration → real-world testing → AI agent),
> with algorithms, config keys, and per-milestone validation gates.
> Execution checklist: `TODO.md`.

## ⚠️ Open Blockers

| ID | Issue | Impact |
|---|---|---|
| **F1** | `Part1.stp` and `Part3.stp` are byte-identical (MD5 `a373ffdf…`, 863,881 B, both with internal `FILE_NAME 'Part3.stp'`). `rename.stp` (522 KB, `Element_Packaging_Cap.stp`) matches the size recorded below for Part1. | All "validated on two parts" claims are false — one part is being tested twice. Blocks Phase 3. |
| **F2** | `core_cavity.py` docstring cites `dfm.parting_line.silhouette_dot_tolerance`; the key does not exist in `config.yaml`. `threshold=0.05` is hardcoded in both the module and `main.py`. | Violates CLAUDE.md invariant #4. |
| **F3** | `.claude/rules/api-layer.md` lists `/display-mesh` and `/boolean-regions` endpoints that do not exist in `main.py`. | Misdirects future work. |
| **F4** | `networkx==3.3` pinned in `requirements.txt`, imported nowhere. | Parting line uses a hand-rolled bounded DFS instead of graph algorithms. |
| — | Every saved validation report shows `status: "skipped"` (no OCC in the test env). | No real evidence exists for any Level 1 claim. |

## Module Status

| Module | File | Lines | Status | Notes |
|---|---|---|---|---|
| STEP Loader | `backend/geometry/step_loader.py` | 1,010 | ✅ Done | Loads Part1.stp, extracts full topology |
| Draft Analyzer | `backend/geometry/draft_analyzer.py` | 772 | ✅ Done | Face-level draft with suggestions |
| Undercut Detector | `backend/geometry/undercut_detector.py` | 3,432 | ✅ Done | Selective Boolean refinement + feature grouping |
| Direction Optimizer | `backend/geometry/direction_optimizer.py` | 909 | ✅ Done | Candidate search + Boolean pruning |
| Parting Line | `backend/geometry/parting_line.py` | 2,870 | ⚠️ Foundation | Silhouette candidates + Chaikin smoothing; no full Hou optimization |
| Core/Cavity | `backend/geometry/core_cavity.py` | 140 | ⚠️ Partial | Face classification only; no solid split |
| Visualize Raw | `backend/geometry/visualize_raw.py` | 409 | ✅ Done | Display mesh with face_id mapping |
| Data Models | `backend/models/geometry_models.py` | 762 | ✅ Done | Shared dataclasses |
| Config | `backend/config.py` | 422 | ✅ Done | Frozen settings from config.yaml |
| FastAPI Backend | `backend/api/main.py` | 995 | ✅ Done | All endpoints functional |
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

| File | Size | MD5 | Internal `FILE_NAME` | Status |
|---|---|---|---|---|
| `data/parts/Part1.stp` | 863,881 B | `a373ffdf…` | `Part3.stp` | ⚠️ **Duplicate of Part3** — see blocker F1 |
| `data/parts/Part3.stp` | 863,881 B | `a373ffdf…` | `Part3.stp` | ✅ Present |
| `data/parts/rename.stp` | 522,419 B | `d0c89a7c…` | `Element_Packaging_Cap.stp` | ❓ Likely the original Part1 — needs team confirmation |
| `data/parts/Part2.stp` | — | — | — | ❌ Not present |

## Infrastructure

| Component | Status |
|---|---|
| Docker (backend + frontend) | ✅ Configured |
| Conda environment | ✅ `environment.yml` defined |
| Config system | ✅ `config.yaml` + frozen dataclasses |
| `.claude/` setup | ✅ Complete |
