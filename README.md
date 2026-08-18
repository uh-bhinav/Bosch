# DfM Agent — Bosch RB-CoC Plastics Hackathon

STEP-native Design-for-Manufacturability analysis for injection-molded
automotive plastic parts.

## 1. What this does

Given a real STEP (`.stp`) CAD file — exact B-Rep geometry, not a
triangle mesh — this tool analyzes it the way a mold designer would:
finds the best mold-opening (pull) direction, flags undercuts that would
lock the part in a steel mold, generates a parting-line candidate, and
splits the part into core and cavity halves. Results render in an
interactive 3-D viewer and export as a STEP mold-half file or a PDF
report.

## 2. What problem it solves

Manually checking a part design for moldability — draft angles, parting
line, undercuts, core/cavity split — is a multi-hour manual task done by
a mold designer in CAD tools like CATIA/NX before tooling can even start.
This tool automates the geometric analysis (not the manual redesign) so
that obvious manufacturability problems surface in seconds instead of
hours, working directly against the exact CAD geometry rather than an
approximated mesh.

## 3. High-level architecture

```
frontend-web/  (React + TypeScript, browser)
      │  REST/JSON over HTTP
      ▼
backend/api/main.py  (FastAPI)
      │
      ▼
backend/geometry/  (the DfM pipeline — pythonOCC / OpenCascade B-Rep)
  step_loader → draft_analyzer → direction_optimizer → undercut_detector
      → parting_line_v2 → core_cavity → side_core
      │
      ▼
backend/report/  (PDF export)   backend/agent/  (AI agent layer, see §17)
```

The backend is **stateless**: every request re-parses the STEP file and
re-runs whatever analysis was asked for. There is no OCC/geometry logic
duplicated in the frontend — `frontend-web/` talks to the backend's REST
API only and never imports pythonOCC.

## 4. Repository map

| Path | What's there |
|---|---|
| `frontend-web/` | **The intended UI.** React + TypeScript + Three.js. See §7. |
| `frontend/app.py` | Legacy Streamlit UI. Not the recommended demo path — see §7. |
| `backend/geometry/` | The geometry engine: STEP loading, draft analysis, undercut detection, pull-direction optimization, parting-line generation (`parting_line_v2/`), core/cavity split, side-core generation, and `mold_orchestration.py` (the single authoritative entry point both frontends call). |
| `backend/api/main.py` | FastAPI REST layer. |
| `backend/report/` | PDF report export. |
| `backend/agent/` | AI agent layer (tool-calling over the geometry engine) — see §17; not part of the primary demo flow. |
| `backend/validation/` | Standalone diagnostic/experiment scripts used during development. Not imported by the runtime pipeline. |
| `tests/` | pytest suite for the backend (42 files); `frontend-web/src/**/*.test.ts(x)` covers the frontend (Vitest, 18 files). |
| `data/parts/` | Demo STEP fixtures — `Part1.stp` (primary demo part) and `Part3.stp` (secondary, exercises undercuts/side-core paths). Read-only; never modified by the tool. |
| `data/fixtures/synthetic/` | Synthetic geometry fixtures required by the test suite. |
| `docs/` | Architecture decisions, algorithm rationale, implementation status, demo script. Start with `docs/README.md`. |
| `scripts/` | Convenience run scripts (`run_backend.sh`, `run_frontend_macos.sh`) and fixture generation. |
| `config.yaml` | All DfM thresholds and parameters — edit this, not source code, to change a threshold. |
| `requirements.txt`, `environment.yml` | Python dependencies — see §5. |

## 5. Prerequisites

- **Python 3.11**, installed via **conda or micromamba** — `pythonocc-core`
  (the OpenCascade B-Rep engine) ships reliable prebuilt binaries only on
  conda-forge; pip builds are not used for it.
- **Node.js 20+** and npm — for `frontend-web/`.
- A real `.stp` file to analyze. `data/parts/Part1.stp` and `Part3.stp`
  are already in the repo for the demo.

## 6. Environment setup

`requirements.txt` is the **single canonical source** for every
pip-installable dependency. `environment.yml` only owns the conda-only
packages (`python`, `pythonocc-core`, `cadquery`, `numpy`, `scipy`, `vtk`)
plus a pointer to `requirements.txt` for the rest — this was previously a
source of contradiction (`environment.yml` pinned a known-broken
`openai==1.25.0`, since fixed) and has been consolidated so there is one
answer to "what version of X do I need."

```bash
# 1. Create the conda env (conda or micromamba both work; example uses conda)
conda env create -f environment.yml
conda activate dfm_agent

# 2. Install the rest
pip install -r requirements.txt

# 3. Verify OCC is actually usable
python -c "from OCC.Core.STEPControl import STEPControl_Reader; print('OCC OK')"
```

If you don't have conda, install Miniforge/Miniconda first, or use
micromamba (`curl -Ls https://micro.mamba.pm/api/micromamba/<platform>/latest | tar -xj bin/micromamba`,
then `micromamba create -f environment.yml -n dfm_agent`, `micromamba activate dfm_agent`).

Set `PYTHONPATH` to the repo root before running the backend from a shell
that didn't `cd` there via a script:

```bash
export PYTHONPATH="$(pwd)"
```

**Secrets**: the AI agent layer (§17) reads provider API keys from a local
`.env` file (`GOOGLE_API_KEY=...` for the default Gemini provider). `.env`
is gitignored and never committed — supply your own locally if you want
to exercise that part of the system. Nothing else in the demo flow (§10)
requires any API key.

## 7. Which frontend to run

**`frontend-web/` is the intended UI for this submission.** It is the
actively developed React application covering the full guided + manual
analysis flow, diagnostics, and export.

`frontend/app.py` (Streamlit) is the original UI and is **not** the
recommended demo path. It has not been deleted — two real backend test
files (`tests/test_frontend_pv2_apptest.py`,
`tests/test_frontend_pv2_region_colors.py`) import functions from it
directly, so removing it would break real test coverage, not just an old
UI. It still runs and was kept functionally up to date, but it is legacy:
run `frontend-web/`, not this, for the demo.

## 8. Start the backend

```bash
conda activate dfm_agent
export PYTHONPATH="$(pwd)"
uvicorn backend.api.main:app --reload --port 8000
```

Or, if you already have a local micromamba install at `.micromamba/` in
this repo (a dev convenience, not portable to a fresh clone by default):
`bash scripts/run_backend.sh`.

## 9. Start the React frontend

```bash
cd frontend-web
npm install
npm run dev
```

This starts the Vite dev server (default `http://localhost:5173`). It
proxies `/api/*` to `http://localhost:8000` automatically — no CORS
setup needed for local dev. To point at a different backend host, set
`VITE_BACKEND_URL` before starting.

## 10. Access the application

Open `http://localhost:5173` in a browser. To confirm the backend is up
independently, `curl http://localhost:8000/health` should return
`{"status": "healthy", ...}`; `http://localhost:8000/docs` gives the full
interactive API reference.

## 11. The demo, step by step

1. **Import** a STEP file (upload `Part1.stp` or `Part3.stp`, or use
   whichever is already listed).
2. **Run Full Analysis** (Guided mode) — one call runs pull-direction
   search, undercut detection, parting-line generation, and the
   core/cavity split, and colors the 3-D viewport.
3. **Inspect results** — the status strip shows the outcome; the viewport
   shows the colored core/cavity split and parting line.
4. **Manually override the pull direction** if desired — enter a vector,
   pick an axis preset, or click a face to use its normal; compare
   against the optimizer's recommendation; optionally supply core-pin/
   delegation authorization for features that need it.
5. **Inspect diagnostics** — geometry, direction-search, parting-line,
   core/cavity, and performance detail, organized so the headline
   conclusion is visible first and raw numbers are one click away.
6. **Export** — download the split mold halves as an AP214 STEP file, or
   generate and download a PDF DfM report.

## 12. Guided vs. Expert mode

**Guided mode** is the one-button path described above: import, run,
inspect, override, export — everything driven through the single
authoritative analysis call. **Expert mode** exposes the same underlying
result through per-tool tabs (Pull Direction, Parting Line, Core/Cavity)
for reading detail without re-running anything. Running each tool
*independently* in Expert mode (rather than reading the shared result) is
not yet built — see `TODO.md`.

## 13. Major engineering concepts

- **Exact B-Rep geometry throughout** — every analysis operates on real
  OpenCascade faces/edges/surfaces (via pythonOCC), not a triangulated
  approximation. Meshes only exist for on-screen display.
- **Stateless backend** — no cached `PartGeometry` between requests; each
  API call reloads and reanalyzes from the STEP file. Simple, at the cost
  of repeated parse time.
- **Single authoritative orchestration path** — `mold_orchestration.py`
  is the one place that chains direction search → parting line →
  core/cavity split, for both the automatic (optimizer-chosen) and
  manual (user-supplied) pull-direction flows, so the two flows can never
  silently diverge in how they interpret a result.
- **Evidence-tiered pull-direction search** — candidate directions are
  scored with an independent, cheap accessibility-risk signal first, then
  Boolean-confirmed for the top candidates, rather than running expensive
  Boolean checks on every candidate.
- **Honest unavailability** — the frontend never fabricates a diagnostic
  value the backend doesn't return; it shows "Not available" with the
  reason instead.

## 14. Backend phases already completed

The geometry engine, orchestration layer, AI agent layer, and PDF export
are all implemented and have been exercised against both real demo parts
end-to-end (not just unit-tested in isolation) at some point in
development. See `STATUS.md` for current module-by-module status and
`CHANGELOG.md` for the full dated implementation history.

## 15. Metrics / diagnostics system

The diagnostics workspace in `frontend-web/` presents results in three
tiers per topic (Geometry, Pull Direction Search, Parting Line,
Core/Cavity, Performance, and others): a **Tier 1** headline conclusion,
**Tier 2** supporting detail, and **Tier 3** advanced/raw values —
collapsed by default so a reviewer sees the verdict first. Every group
reads from the one analysis result already computed in step 2 of the demo
flow; nothing in this workspace triggers an additional backend call.

## 16. Export functionality

- **STEP export** — the split core/cavity solids as a real, reloadable
  AP214 STEP file, downloaded through the browser.
- **PDF export** — a DfM report built from the already-computed analysis
  result (never recomputed for the report), with an optional Executive
  Summary section.

Both exports reuse the currently-resolved pull direction; neither
re-runs the pull-direction optimizer. One consequence: a PDF's own "Pull
Direction Optimization" section can never appear in a report generated
this way.

## 17. Known limitations

| Area | Limitation |
|---|---|
| Parting line | Candidate/foundation result — real graph search and a real parting surface, but full Hou (2018) global optimization is not applied. |
| Core/cavity split | Real Boolean solid split, verified on both real demo parts, but the Boolean tool is a labeled planar approximation of the parting surface, not the exact 3-D surface (which is topologically invalid on both parts and unfixable by standard OCC healing). |
| Side cores | Generates the volume that must retract and its direction; does not select a tooling mechanism (lifter vs. slide vs. collapsible core). |
| Pull-direction search timing | One real run on `Part1.stp` took ~29.6 minutes; root cause (per-direction OCC Boolean-retry variance) is not fully isolated. **See `TODO.md` — budget for this before a live, undelayed demo.** |
| AI agent (`backend/agent/`) | A real, tool-calling agent over the geometry engine exists and is Gemini-live-verified end-to-end; Anthropic/OpenAI/Grok adapters are structurally verified but not live-tested. It is reachable via the API and the legacy Streamlit UI's "AI Agent" tab — **it is not wired into `frontend-web/`** and is not part of the demo flow in §11. |
| Volume conservation | The solid split conserves tooling volume to ~4%, not the originally targeted 2% (documented, tolerance adjusted accordingly — not a silent failure). |

## 18. Intentionally not implemented

Side-action/lifter tooling-mechanism selection, a conversational agent
chat endpoint (only single-shot analysis exists), exhaustive Bassi
Boolean analysis over every face/direction, full Sangolli volumetric
decomposition, authentication, multi-user architecture, CI/CD, cloud
deployment, and production observability are all out of scope for this
submission by explicit decision — not partially built, not planned for
this pass. See `.claude/rules/honesty-and-scope.md` for the precise,
maintained "claims to avoid" list this project holds itself to.

## 19. Troubleshooting

| Problem | Likely cause / fix |
|---|---|
| `ModuleNotFoundError: OCC` | `pythonocc-core` wasn't installed via conda, or the `dfm_agent` env isn't activated. |
| Frontend shows a backend-unreachable error | Start the FastAPI server (§8) before `npm run dev`, and confirm `curl http://localhost:8000/health` works. |
| `npm install` fails on native deps | Confirm Node.js 20+ (`node -v`); delete `frontend-web/node_modules` and retry. |
| Empty parts list | Add a `.stp` file to `data/parts/`, or use the in-app upload. |
| A pull-direction/analysis call seems to hang | This is a known, disclosed timing risk (§17) — it can take many minutes on some parts, not a UI bug. |
| `pip install -r requirements.txt` fails on `pythonocc-core`/`cadquery` | Those two are conda-only by design — don't try to pip-install them; they come from `environment.yml`'s conda dependencies. |

## 20. Cross-platform notes

Only macOS was exercised while assembling this repository. Windows and
Linux setup below follows the same conda + Node.js flow and is expected
to work, since nothing in the backend or `frontend-web/` is
macOS-specific, but **it was not physically run on Windows or Linux
during this cleanup pass** — treat the platform-specific notes below as
unverified-but-expected, not tested.

- **macOS**: as documented above. Apple Silicon and Intel both work with
  conda-forge's `pythonocc-core` builds.
- **Linux**: same conda/npm flow. `xvfb` is only needed for the
  Docker/Streamlit headless rendering path (§21), not for
  `frontend-web/`, which renders in the browser.
- **Windows**: use conda (not micromamba's curl-based install script,
  which is Unix-oriented) and Git Bash or WSL for the shell commands
  above; `pythonocc-core` is available on conda-forge for Windows too.

## 21. Docker

`docker-compose.yml`, `Dockerfile.backend`, and `Dockerfile.frontend`
exist and build a working backend + **Streamlit** stack
(`docker compose up`, backend on `:8000`, Streamlit on `:8501`). There is
no Docker service for `frontend-web/` — adding one was out of scope for
this cleanup pass (no new Docker architecture was introduced). If you
want to use Docker for the backend only, it works as-is; for the
intended React demo, use the local setup in §8–§9, which is the simplest
reliable path with what's in this repository today.

## 22. Five-minute panel demo

1. `uvicorn backend.api.main:app --port 8000` (backend), `cd frontend-web && npm run dev` (frontend). Open `http://localhost:5173`.
2. Import `Part1.stp`.
3. Click **Run Full Analysis**. Wait for the result (see the timing note in §17 — if it's slow, narrate what's happening: pull-direction search, undercut detection, parting line, core/cavity split, all against exact B-Rep geometry).
4. Point out the colored core/cavity split and parting line in the viewport.
5. Open the diagnostics panel — show one Tier 1 conclusion, then expand it to Tier 2/3 to show the panel isn't hiding anything, it's just not leading with raw numbers.
6. Switch to manual pull direction, pick a different axis, re-run, and show the recommended-vs-manual comparison.
7. Export the STEP mold-half file and open it in any CAD viewer to show it's a real, reloadable solid, not a placeholder.
8. Export the PDF report and open it.
9. If time remains, load `Part3.stp` and repeat step 3 to show a part with real undercuts and a side-core feature.
10. Close on `STATUS.md`'s Known Limitations section — this project states its own gaps rather than leaving a judge to find them.
