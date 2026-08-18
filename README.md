# DfM Agent — Bosch RB-CoC Plastics Hackathon

STEP-native Design-for-Manufacturability analysis for injection-molded
automotive plastic parts.

## Quick start — two supported ways to run this

**Recommended — Docker** (platform-isolated, one command):

```bash
docker compose up --build
```

Open **http://localhost:5173** — this launches `frontend-web/` (the React
UI, F1–F7), talking to the FastAPI backend on `:8000` inside Docker's own
network. `http://localhost:8000/docs` gives the backend's interactive API
docs directly. Full detail in §21.

**Alternative — Manual setup** (conda backend + npm/Vite frontend, no
Docker):

```bash
conda env create -f environment.yml && conda activate dfm_agent
pip install -r requirements.txt
uvicorn backend.api.main:app --reload --port 8000   # terminal 1
cd frontend-web && npm install && npm run dev        # terminal 2
```

Open **http://localhost:5173**. Full detail, including Windows-specific
commands, in §5–§9.

Both paths launch the exact same `frontend-web/` React application against
the exact same backend — pick whichever is more convenient. Neither path
launches the legacy Streamlit UI (`frontend/app.py`) — see §7.

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
that obvious manufacturability problems surface in minutes instead of
hours, working directly against the exact CAD geometry rather than an
approximated mesh (see §17 for real measured full-analysis timing).

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

- **Python 3.11**, installed via **conda** (Miniconda, Miniforge, or
  Anaconda — any of these work identically for this project) —
  `pythonocc-core` (the OpenCascade B-Rep engine) ships reliable prebuilt
  binaries only on conda-forge; pip builds are not used for it. Get the
  Windows/macOS/Linux installer from whichever distribution you prefer;
  no platform-specific fork of these instructions is needed once conda
  itself is installed.
- **Node.js 20+** and npm — for `frontend-web/`. The official Windows
  installer from nodejs.org puts both on `PATH` automatically.
- A real `.stp` file to analyze. `data/parts/Part1.stp` and `Part3.stp`
  are already in the repo for the demo — no extra download needed.
- **Windows note**: run the commands below in **PowerShell** (the default
  terminal in Windows Terminal / VS Code). Where a command differs from
  macOS/Linux, both are given explicitly.

## 6. Environment setup

`requirements.txt` is the **single canonical source** for every
pip-installable dependency. `environment.yml` only owns the conda-only
packages (`python`, `pythonocc-core`, `cadquery`, `numpy`, `scipy`, `vtk`)
plus a pointer to `requirements.txt` for the rest — this was previously a
source of contradiction (`environment.yml` pinned a known-broken
`openai==1.25.0`, since fixed) and has been consolidated so there is one
answer to "what version of X do I need."

These commands are identical on Windows (PowerShell), macOS, and Linux —
conda itself abstracts the platform difference:

```bash
# 1. Create the conda env
conda env create -f environment.yml
conda activate dfm_agent

# 2. Install the rest
pip install -r requirements.txt

# 3. Verify OCC is actually usable
python -c "from OCC.Core.STEPControl import STEPControl_Reader; print('OCC OK')"
```

If step 3 fails or hangs, see Troubleshooting (§19) before continuing —
don't skip the verification.

> `pythonocc-core=7.7.2`, `cadquery=2.4.0`, and `vtk=9.2.*` are all
> published for Windows (`win-64`) on conda-forge, so this is expected to
> work the same way it does on macOS. **This was not independently
> re-verified on a Windows machine during this documentation pass** — if
> the conda solve fails or a package is unavailable for your platform,
> that is the first thing to report back, not a setup mistake on your
> part.

Set `PYTHONPATH` to the repo root before starting the backend (needed so
`backend.*` imports resolve; the run scripts under `scripts/` already do
this for macOS/Linux, but those are bash scripts and won't run on Windows
without WSL or Git Bash — set it directly instead):

```bash
# macOS / Linux (bash/zsh)
export PYTHONPATH="$(pwd)"
```

```powershell
# Windows (PowerShell)
$env:PYTHONPATH = (Get-Location).Path
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
recommended demo path — neither the Docker path (§21) nor the manual
setup (§8–§9) launches it. It has not been deleted — two real backend
test files (`tests/test_frontend_pv2_apptest.py`,
`tests/test_frontend_pv2_region_colors.py`) import functions from it
directly, so removing it would break real test coverage, not just an old
UI. It still runs and was kept functionally up to date, but it is legacy:
run `frontend-web/`, not this, for the demo. If you want to run it
anyway, it's still reachable manually (`streamlit run frontend/app.py`)
or via `docker build -f Dockerfile.frontend .` — just not through
`docker compose up`.

## 8. Start the backend

```bash
# macOS / Linux (bash/zsh)
conda activate dfm_agent
export PYTHONPATH="$(pwd)"
uvicorn backend.api.main:app --reload --port 8000
```

```powershell
# Windows (PowerShell)
conda activate dfm_agent
$env:PYTHONPATH = (Get-Location).Path
uvicorn backend.api.main:app --reload --port 8000
```

Run this from the repository root on any platform. The backend listens
on port `8000` regardless of OS.

**Make sure `conda activate dfm_agent` actually activated the environment
you created in §5** before running `uvicorn` — if it silently does nothing,
or `python -c "import OCC"` fails with `No module named 'OCC'` afterward,
`uvicorn` is running against the wrong Python. This most often happens when
the environment was created with `micromamba` rather than `conda` itself; in
that case activate it the same way you created it, e.g.:

```bash
micromamba activate dfm_agent
# or, if you know the environment's install path:
conda activate /path/to/your/micromamba/envs/dfm_agent
```

`pythonocc-core`/`cadquery` only ever install correctly through
`environment.yml`'s conda-forge channel (§5) — never `pip` — so
`No module named OCC` always means "wrong/unactivated environment," never a
missing package to `pip install`.

`scripts/run_backend.sh` exists as a macOS/Linux convenience wrapper —
it is a bash script and assumes a local micromamba install at
`.micromamba/` inside the repo, which is not part of a fresh clone. It is
**not** portable to Windows; use the command above instead.

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
| AI agent (`backend/agent/`) | A real, tool-calling agent over the geometry engine exists and is Gemini-live-verified end-to-end; Anthropic/OpenAI/Grok adapters are structurally verified but not live-tested. It is reachable via the API and the legacy Streamlit UI's "AI Agent" tab — **it is not wired into `frontend-web/`** and is not part of the demo flow in §11. |
| Volume conservation | The solid split conserves tooling volume to ~4%, not the originally targeted 2% (documented, tolerance adjusted accordingly — not a silent failure). |
| Full-analysis timing | "Run Full Analysis" chains several sequential backend calls (direction search + solid split, then draft, undercuts, parting-line, and a conditional side-core check) against exact B-Rep geometry, not a mesh approximation — this is not instant. Measured: the primary direction-search + solid-split call alone took ~195s on `Part1.stp` in one real run; the full Guided sequence (that call plus all its follow-ups) has been observed around ~350s on `Part1.stp` and ~250s on `Part3.stp`. This varies by part complexity and by OCC Boolean-retry variance (§19) — it is not a fixed number. |

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
| Windows: `'uvicorn' is not recognized` / `'conda' is not recognized` | The conda env isn't activated in this terminal, or you're in `cmd.exe` instead of the Anaconda/PowerShell prompt conda configured. Open "Anaconda Prompt" (or re-run `conda init powershell` once, then open a new PowerShell window) and `conda activate dfm_agent` again. |
| Windows: backend starts but every request 404s or import-errors | `PYTHONPATH` wasn't set in that terminal session — it does not persist across terminal windows. Re-run `$env:PYTHONPATH = (Get-Location).Path` from the repo root in the same window you start `uvicorn` from. |
| Windows: `conda env create -f environment.yml` fails resolving `pythonocc-core`/`cadquery`/`vtk` | These are published for `win-64` on conda-forge but this was not independently re-verified on Windows this pass (§20) — capture the exact solver error; it likely means a channel/version needs adjusting for your conda version, not that Windows is unsupported. |
| Docker: `frontend` container shows "Could not reach the backend" in the UI | Check `docker compose ps` — if `backend` isn't healthy yet, wait for its healthcheck; `frontend` starts as soon as its own container is up, not after the backend is ready. |
| Docker: port `5173` or `8000` already in use | Something else on the host is already bound to that port — stop it, or edit the left-hand side of the `ports:` mapping in `docker-compose.yml` (e.g. `"5174:5173"`) and open that port instead. |

## 20. Cross-platform notes

This repository was developed and physically exercised on **macOS**
only. The setup path in §6–§9 is designed to need nothing
macOS-specific — plain conda and plain npm, no shell scripts, no
hardcoded absolute paths, no `micromamba`-specific commands — but
**Windows and Linux have not been physically run this pass.** Where a
command genuinely differs by OS (environment variables, path syntax), an
explicit Windows and macOS/Linux version is given side by side above;
where nothing differs (conda commands, npm commands, the demo flow
itself), one command is given because it is genuinely the same command.

- **macOS**: fully exercised. Apple Silicon and Intel both work with
  conda-forge's `pythonocc-core` builds.
- **Linux**: expected to work via the same conda + npm flow as macOS —
  nothing in `backend/` or `frontend-web/` is OS-conditional. Not
  physically tested this pass. (`xvfb` only matters if you separately
  run the legacy Streamlit UI's own Dockerfile, per §7 — it is not part
  of the recommended Docker path in §21, which runs `frontend-web/` and
  renders in a normal browser.)
- **Windows**: expected to work via conda + npm in PowerShell, using the
  Windows-specific commands given in §6/§8 for `PYTHONPATH`. Not
  physically tested this pass — specifically unverified: (1) that
  `conda env create -f environment.yml` resolves cleanly for `win-64`
  (the packages are published for Windows on conda-forge, but the exact
  solve was not run here), and (2) that no shell-quoting difference in
  PowerShell trips up any command above. Do not use `scripts/run_backend.sh`
  or `scripts/run_frontend_macos.sh` on Windows — both are bash and
  assume a macOS/Linux-style local micromamba install; they are dev
  conveniences, not part of the documented setup path.

If Windows setup fails at the conda-solve step specifically, that is the
one genuine cross-platform risk in this repository worth flagging back —
everything else in the setup path (Python imports, FastAPI, Vite/npm) is
plain and platform-agnostic once the conda environment exists.

## 21. Docker (recommended path)

```bash
docker compose up --build
```

This builds and runs two containers:

| Service | Built from | Published port | What it is |
|---|---|---|---|
| `backend` | `Dockerfile.backend` | `8000` | FastAPI backend — same code path as the manual setup. |
| `frontend` | `Dockerfile.frontend-web` | `5173` | The React `frontend-web/` UI, running Vite's dev server bound to `0.0.0.0` inside the container. |

Open **http://localhost:5173** — this is `frontend-web/`, the same UI
described throughout this README, not Streamlit. The frontend container
talks to the backend over Docker's internal network
(`VITE_BACKEND_URL=http://backend:8000`, resolved server-side by Vite's
own proxy — the same proxy mechanism used for local `npm run dev`); the
browser on your host machine only ever talks to `localhost:5173` and
never needs to resolve `backend` itself.

The legacy Streamlit UI is **not** part of this Docker path.
`Dockerfile.frontend` (Streamlit) still exists and still builds
standalone if you explicitly target it
(`docker build -f Dockerfile.frontend .`), but `docker-compose.yml`'s
`frontend` service no longer references it — it was not deleted only
because nothing requires deleting it, not because it's still recommended.

**Windows note**: Docker is the platform-isolation path specifically
*because* it avoids conda/Windows solver risk (§20) — the same Linux
container image runs regardless of host OS via Docker Desktop. That said,
**Windows execution of this Docker setup has not been physically tested
this pass.** Docker Desktop with the WSL2 backend is required on Windows;
beyond that, this should behave identically to macOS/Linux since nothing
in either Dockerfile is OS-conditional, but treat that as expected, not
demonstrated.


