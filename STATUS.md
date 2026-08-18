# Project Status — DfM Agent

> **Last updated**: 2026-08-18 (hackathon-submission cleanup pass).
> This file is a **current-state snapshot**, not a log. For the detailed,
> dated history of how each module got here, see `CHANGELOG.md`. This file
> used to duplicate that history in a long "Headline" section; that section
> has been replaced with the condensed "Recent Milestones" list below.

## Current Demo Capabilities

What actually works end-to-end today, against real STEP geometry
(`data/parts/Part1.stp`, `Part3.stp`), through `frontend-web/`:

- Import a `.stp` file, view it in the persistent 3-D viewport.
- Run Full Analysis (Guided mode): one authoritative backend call
  (`GET /core-cavity`) runs pull-direction search → parting line →
  core/cavity split and colors the model.
- Override the pull direction manually (vector entry, axis presets, or
  "use selected face normal"), with structured core-pin/delegation
  authorization editing, compared against the optimizer's recommendation.
- Inspect a three-tier (conclusion / details / advanced) diagnostics
  workspace across geometry, direction search, parting line, core/cavity,
  and performance — anything the backend doesn't serialize is shown as
  "Not available," never invented.
- Export the split mold halves as an AP214 STEP file, and export a PDF
  DfM report (with an optional Executive Summary section), both via real
  browser downloads.

## Known Limitations

| Area | Limitation |
|---|---|
| Parting line | Candidate/foundation result — real graph search, verified closure, real parting surface — but full Hou (2018) global optimization is not applied. |
| Core/cavity split | Real Boolean solid split, verified on both real parts (2 solids, reloadable STEP), but the Boolean tool is a labeled planar approximation of the parting surface (`split_tool_kind="planar_approximation"`), not the exact 3-D surface — that surface is topologically invalid on both real parts and unfixable by standard OCC healing. |
| Volume conservation | Tooling-volume conservation on the solid split is ~4%, not the originally-targeted 2% (tolerance raised and documented, not silently loosened). |
| Side cores | `side_core.py` generates one side-core solid for the single highest-confidence critical feature (or a combined multi-feature body per mold half) — it decides *what volume must retract and along which direction*, never *which mechanism* (lifter vs. slide vs. collapsible core). |
| Pull-direction search timing | `optimize_mold_direction(Part1.stp)` has been measured as high as ~29.6 minutes in one run (2026-08-16), attributed to per-direction OCC Boolean-retry variance, not candidate-pool size. Root cause not fully isolated — **the single largest live-demo risk**; budget for this or pre-compute results before presenting. |
| AI agent providers | Only the Gemini provider has been live-tested end-to-end. Anthropic/OpenAI/Grok adapters are built from verified real SDK signatures and covered by mocked-provider tests, but have not been called against a live API key. |
| Mock-test hygiene | Some mock-based geometry tests still lack explicit `boolean_refine=False`; known call sites are fixed, a broader audit pass is not complete. |

## Intentionally Out of Scope (this submission)

Per project scope decisions — not bugs, not partially done, not planned
for this pass: side-action/lifter tooling-mechanism selection, exhaustive
Bassi Boolean analysis (every face × every direction), full Sangolli
volumetric decomposition, a conversational agent chat endpoint,
authentication, multi-user architecture, CI/CD, cloud deployment,
Kubernetes, production observability, or a managed database. See
`docs/IMPLEMENTATION_STATUS.md` and `.claude/rules/honesty-and-scope.md`
for the full, precise phrasing on what not to claim.

## Module Status

| Module | File | Lines | Notes |
|---|---|---|---|
| STEP Loader | `backend/geometry/step_loader.py` | ~1,240 | Full topology + edge convexity + `load_step_cached()` LRU cache. |
| Draft Analyzer | `backend/geometry/draft_analyzer.py` | ~960 | Face-level draft classification, precomputed directional metrics. |
| Undercut Detector | `backend/geometry/undercut_detector.py` | ~4,630 | Selective Boolean refinement, feature grouping, convexity suppression, bilateral core+cavity-side accessibility risk. |
| Direction Optimizer | `backend/geometry/direction_optimizer.py` | ~2,690 | Hierarchical staged search, evidence-tier scoring, optional core-pin/delegation authorization threading, parting-line feasibility gating. See timing risk above. |
| Parting Line v2 | `backend/geometry/parting_line_v2/` (engine, gates, measures, regions, track_a, track_b, graph, stitch, ranking, contracts, types) | ~5,700 total | Current parting-line engine — rebuilt (started 2026-08-09) to replace the original `parting_line.py`. |
| Parting Line (v1, retained) | `backend/geometry/parting_line.py` | ~4,750 | Original engine; superseded by `parting_line_v2` as the active path but retained — see code/tests for current wiring. |
| Core/Cavity | `backend/geometry/core_cavity.py` | ~1,020 | Face classification + Boolean solid split + AP214 export. Planar-approximation split tool — see Known Limitations. |
| Mold Orchestration | `backend/geometry/mold_orchestration.py` | ~585 | Single authoritative entry point chaining direction → parting line → core/cavity for both automatic and manual flows. |
| Side Core / Lifter | `backend/geometry/side_core.py` | ~810 | Per-feature and combined multi-feature side-core generation (Bosch criterion #5). Does not select a tooling mechanism. |
| Visualize Raw | `backend/geometry/visualize_raw.py` | 442 | Display mesh with `face_id` mapping + triangle ceiling. |
| Data Models | `backend/models/geometry_models.py` | 768 | Shared dataclasses, zero internal imports. |
| Config | `backend/config.py` | ~1,270 | Frozen settings, all thresholds. |
| FastAPI Backend | `backend/api/main.py` | ~2,300 | All endpoints, including upload, STEP export + download, PDF report export. |
| AI Agent | `backend/agent/dfm_agent.py`, `tools.py`, `providers.py`, `schemas.py`, `prompts.py` | ~880 total | Provider-agnostic tool-calling agent. Gemini live-verified; Anthropic/OpenAI/Grok structurally verified only. |
| PDF Export | `backend/report/pdf_export.py`, `templates.py` | ~550 | Presentation layer over already-computed results; optional Executive Summary section. |
| **`frontend-web/`** (React + TypeScript + Three.js) | `frontend-web/src/` | — | **The intended demo UI.** Persistent viewport, guided + manual analysis, diagnostics workspace, STEP/PDF export — talks to the backend over its REST API only. |
| `frontend/app.py` (Streamlit) | `frontend/app.py` | ~6,160 | Legacy UI, superseded by `frontend-web/`. Kept in the repo (not deleted) because two real pytest files exercise its functions directly — see README "Streamlit" note. Not part of the recommended demo path. |
| Validation scripts | `backend/validation/*.py` | — | Ad hoc validation/profiling/experiment entry points used during development; not imported by the runtime pipeline. |

## Test Status

42 files under `tests/` (backend, pytest) and 18 `*.test.ts(x)` files under
`frontend-web/src/` (Vitest). **Pass/fail counts are not reported here** —
this cleanup pass did not execute the test suites (explicitly out of
scope for this pass; see `CHANGELOG.md` for the most recent dated,
verified run results). Real-fixture tests are gated on
`data/parts/Part1.stp`/`Part3.stp` and pythonocc-core availability and
skip gracefully otherwise.

Known, previously-disclosed pre-existing gap: real-geometry assertions
exist in `backend/validation/part_validation.py` (`--assert-*` flags), but
synthetic known-answer fixtures for pure unit coverage are still limited —
most geometry tests use OCC mocks rather than a fixture with a
provably-correct answer.

## Data Status

STEP schema: `AUTOMOTIVE_DESIGN` (AP214). Mold-half export targets AP214
to match.

| File | Role |
|---|---|
| `data/parts/Part1.stp` | Primary demo part — simple, Level 1. |
| `data/parts/Part3.stp` | Secondary demo part — complex, exercises undercuts/side-core/authorization paths. |
| `data/fixtures/synthetic/UC1–UC5*.stp` | Synthetic fixtures required by the geometry/direction test suite. |

There is no `Part2.stp` — an earlier naming mix-up, resolved long before
this pass.

## Infrastructure

| Component | Status |
|---|---|
| Local run (recommended) | conda/micromamba env (`environment.yml` + `pip install -r requirements.txt`) for the backend, Node.js + npm for `frontend-web/`. See root `README.md`. |
| Docker (`docker-compose.yml`, `Dockerfile.backend`, `Dockerfile.frontend`) | Builds and runs the backend + **legacy Streamlit** frontend only. There is no Docker service for `frontend-web/`. Not the recommended demo path — kept as-is, documented honestly in README rather than silently implying it covers the React UI. |
| Config system | `config.yaml` + frozen dataclasses in `backend/config.py`. |
| `.claude/` setup | Rules, skills, commands, memory — present, governs how Claude Code should work in this repo. |

## Recent Milestones

Condensed pointer list — full detail (evidence, verification steps, real
numbers) for every entry below lives in `CHANGELOG.md` under the matching
heading.

- **F6** — STEP mold-half export download endpoint + PDF Executive
  Summary flag; `ExportPanel` in `frontend-web/`.
- **F5** — Three-tier diagnostics workspace in `frontend-web/`, honest
  "Not available" for ungenerated backend fields.
- **F4** — Manual pull-direction entry + structured core-pin/delegation
  authorization editor in `frontend-web/`.
- **F3** — Guided "Run Full Analysis" wired to the authoritative
  `/core-cavity` orchestration call.
- **F2** — Real STEP upload wired into the `frontend-web/` shell.
- **F1** — `frontend-web/` application shell (persistent viewport, top
  bar, tool rail, context inspector, status strip) proven.
- **C1–C18A / O1–O3** — `mold_orchestration.py` built as the single
  authoritative automatic/manual entry point; parting-line/undercut
  authorization threading; shared authoritative parting-line result reused
  across `/core-cavity` and `/export/report` instead of being recomputed.
- **`parting_line_v2` rebuild** (started 2026-08-09) — new engine
  (`engine.py`, `gates.py`, `regions.py`, `track_a.py`, `track_b.py`, …)
  built to replace the original silhouette-based `parting_line.py`.
- **Stage 6 / Stage 5 / Stage 4 / Stage 3** — PDF export, AI agent layer,
  side-core generation, engineering-review Streamlit UI — each shipped
  and verified against both real parts before this pass began.

For anything earlier (the original engine build, the 2026-07-27/28 audit
and bug-fix cycle, Milestones 1.1–1.11), see `CHANGELOG.md`.
