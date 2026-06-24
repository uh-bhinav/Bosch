# DfM Agent — Bosch RB-CoC Plastics Hackathon

**STEP-Native DfM Analysis for Injection-Molded Automotive Parts**

---

## What This Is

An AI-driven DfM (Design for Manufacturability) Agent for injection-molded
automotive STEP parts. The current build is a Level 1 geometry-analysis demo
with a production-minded architecture:

1. **Loads** real STEP (`.stp`) B-Rep geometry from automotive CAD workflows.
2. **Extracts** solids, faces, normals, surface types, topology, and adjacency.
3. **Runs** draft analysis for a selected pull direction.
4. **Detects** undercut candidates and refines them with swept Boolean checks
   where the OCC runtime supports it.
5. **Searches** candidate mold-opening directions and recommends the best
   current Level 1 pull direction.
6. **Visualizes** raw geometry, draft colors, undercut faces, Boolean regions,
   feature rationale, and action confidence in Streamlit.

Parting line generation, core/cavity extraction, LangChain tool-calling, and
PDF report export are planned next-phase items. See
[docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md) for the exact
capability and limitation status.

---

## Quick Start (Docker)

```bash
# 1. Place your STEP file
cp Part1.stp data/parts/

# 2. Start everything
docker compose up

# 3. Open in browser
open http://localhost:8501     # Streamlit UI
open http://localhost:8000/docs  # FastAPI docs
```

For repeatable Level 1 validation evidence in Docker:

```bash
bash scripts/run_level1_docker_validation.sh 3
```

The script saves validation and performance JSON files under
`reports/level1_validation/`.

---

## Local Development (without Docker)

You can run the full app locally without Docker. The stack is two processes:

| Service | Port | Purpose |
|---------|------|---------|
| **FastAPI backend** | `8000` | STEP loading, draft/undercut/direction/parting-line APIs |
| **Streamlit frontend** | `8501` | Interactive UI and 3D visualization |

Place STEP files in `data/parts/` (e.g. `data/parts/Part1.stp`).

### Prerequisites

- **Git** — clone the repo
- **curl** and **tar** — for micromamba install (Option A)
- **Python 3.11** — provided by the conda environment
- **pythonOCC** — must come from conda-forge (not pip); see `environment.yml`

> **Why conda/micromamba?**  
> `pythonocc-core` has C++ extensions that are reliably available only on
> conda-forge. Pip builds often fail on macOS and Linux.

---

### Option A — Micromamba (recommended, no system conda required)

Micromamba installs into `.micromamba/` inside the project. This folder is
gitignored — recreate it on each machine.

#### 1. One-time environment setup

```bash
cd Bosch

# macOS Apple Silicon
mkdir -p .micromamba
curl -Ls https://micro.mamba.pm/api/micromamba/osx-arm64/latest \
  | tar -xj -C .micromamba bin/micromamba

# Linux x86_64 (use this instead on Linux)
# curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest \
#   | tar -xj -C .micromamba bin/micromamba

export MAMBA_ROOT_PREFIX="$PWD/.micromamba/root"
./.micromamba/bin/micromamba create -y -f environment.yml -n dfm_agent -r "$MAMBA_ROOT_PREFIX"
```

First create takes **5–15 minutes** and ~2–5 GB disk (pythonOCC, VTK, CadQuery).

#### 2. Verify the environment

```bash
export MAMBA_ROOT_PREFIX="$PWD/.micromamba/root"
export PYTHONPATH="$PWD"

./.micromamba/bin/micromamba run -r "$MAMBA_ROOT_PREFIX" -n dfm_agent \
  python -c "from OCC.Core.STEPControl import STEPControl_Reader; print('OCC OK')"

./.micromamba/bin/micromamba run -r "$MAMBA_ROOT_PREFIX" -n dfm_agent \
  python -m backend.geometry.step_loader data/parts/Part1.stp --json
```

#### 3. Run the application (two terminals)

**Terminal 1 — backend:**
```bash
cd Bosch
export MAMBA_ROOT_PREFIX="$PWD/.micromamba/root"
export PYTHONPATH="$PWD"
./.micromamba/bin/micromamba run -r "$MAMBA_ROOT_PREFIX" -n dfm_agent \
  uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
```

**Terminal 2 — frontend:**
```bash
cd Bosch
export MAMBA_ROOT_PREFIX="$PWD/.micromamba/root"
export PYTHONPATH="$PWD"
./.micromamba/bin/micromamba run -r "$MAMBA_ROOT_PREFIX" -n dfm_agent \
  streamlit run frontend/app.py --server.port 8501
```

#### 4. Open in browser

```bash
open http://localhost:8501     # Streamlit UI — select Part1.stp, run analysis steps
open http://localhost:8000/docs  # FastAPI interactive docs
```

In the Streamlit sidebar: confirm **Backend connected**, select **Part1.stp**,
then step through **Load STEP → Draft → Undercuts → Direction → Parting Line**.

---

### Option B — Miniconda / Miniforge

If you already have conda installed:

```bash
cd Bosch
conda env create -f environment.yml
conda activate dfm_agent
export PYTHONPATH="$PWD"

python -c "from OCC.Core.STEPControl import STEPControl_Reader; print('OCC OK')"
```

**Terminal 1 — backend:**
```bash
cd Bosch
conda activate dfm_agent
export PYTHONPATH="$PWD"
uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
```

**Terminal 2 — frontend:**
```bash
cd Bosch
conda activate dfm_agent
export PYTHONPATH="$PWD"
streamlit run frontend/app.py --server.port 8501
```

---

### Optional checks and dev commands

```bash
# Run tests
pytest tests/ -v

# Validate STEP demo files
python -m backend.validation.part_validation --json

# Profile STEP demo files
python -m backend.validation.performance_profile --json

# Desktop PyVista window (local inspection only, not Streamlit)
python -m backend.geometry.visualize_raw data/parts/Part1.stp
```

---

### Platform notes

| Platform | 3D viewer in Streamlit |
|----------|------------------------|
| **macOS** | Uses **Plotly** in the browser (avoids VTK Cocoa thread crashes) |
| **Linux / Docker** | Uses **PyVista + stpyvista** |

### Troubleshooting

| Issue | Fix |
|-------|-----|
| `ModuleNotFoundError: OCC` | Environment not activated, or create env from `environment.yml` |
| `Backend unavailable` in UI | Start the FastAPI server on port 8000 first |
| Micromamba lock error | Wait a few seconds and retry, or `rm -f ~/.cache/mamba/proc/proc.lock` |
| Empty parts list | Add a `.stp` file under `data/parts/` |
| `PYTHONPATH` errors | Always `export PYTHONPATH="$PWD"` from the `Bosch` repo root |

### Helper alias (optional)

Add to `~/.zshrc` or `~/.bashrc`:

```bash
bosch-env() {
  cd /path/to/Bosch
  export MAMBA_ROOT_PREFIX="$PWD/.micromamba/root"
  export PYTHONPATH="$PWD"
}
```

Then run `bosch-env` in each terminal before the `micromamba run` commands.

---

## Architecture

```
dfm_agent/
├── backend/
│   ├── geometry/           ← Geometry engine (the "brain")
│   │   ├── step_loader.py         # Module 1: STEP → PartGeometry
│   │   ├── draft_analyzer.py      # Module 2: Draft angle per face
│   │   ├── direction_optimizer.py # Module 3: Bassi 2010 optimal pull dir
│   │   ├── undercut_detector.py   # Module 4: Sangolli 2021 undercut features
│   │   ├── parting_line.py        # In progress: candidates + projected wire
│   │   └── core_cavity.py         # Planned: Level 2 core/cavity split
│   ├── models/
│   │   └── geometry_models.py     # Shared dataclasses (PartGeometry, FaceData…)
│   ├── agent/
│   │   ├── dfm_agent.py           # Planned: LangChain orchestrator
│   │   └── tools.py               # Planned: tool wrappers for geometry modules
│   ├── api/
│   │   └── main.py                # FastAPI app
│   └── config.py                  # Settings loader (reads config.yaml)
├── frontend/
│   └── app.py                     # Streamlit interactive 3D UI
├── tests/                         # pytest suite
├── data/parts/                    # Drop .stp files here
├── docs/
│   └── IMPLEMENTATION_STATUS.md   # Current truth source for capabilities
├── config.yaml                    # ALL thresholds and parameters
├── environment.yml                # Conda dependencies
├── requirements.txt               # Pip dependencies
├── Dockerfile.backend
├── Dockerfile.frontend
└── docker-compose.yml
```

## Documentation

Preparation materials live in [docs/README.md](docs/README.md):

- Current implementation truth source.
- Level 1 live demo script.
- DFM report outline.
- Slide storyboard.
- Evidence checklist for screenshots, metrics, and claims review.

---

## Pipeline

```
Part1.stp
    │
    ▼
[1] step_loader.py ──────────────── PartGeometry (faces, normals, bbox)
    │
    ▼
[2] draft_analyzer.py ───────────── Draft angle per face (green/yellow/red)
    │
    ▼
[3] direction_optimizer.py ──────── Optimal pull direction (Bassi 2010)
    + undercut_detector.py ──────── Undercut features (Sangolli 2021)
    │
    ▼
[4] draft_analyzer.py (re-run) ──── Final draft map on optimal direction
    │
    ▼
[5] parting_line.py ─────────────── Silhouette candidates + projected/refined wire
    │
    ▼
[6] core_cavity.py ──────────────── Planned: core / cavity split (Level 2)
    │
    ▼
[7] dfm_agent.py ────────────────── Planned: LLM tool-calling + PDF report
    │
    ▼
    Interactive 3D UI
```

---

## Research Mapping

| # | Paper | Role in Pipeline |
|---|-------|-----------------|
| 1 | Bassi et al. (2010) — *Undercut-Free Parting Direction Determination* | Partially implemented: candidate search plus selective swept Boolean refinement |
| 2 | Sangolli et al. (2021) — *Algorithms for sorting and recognizing undercut features* | Partially implemented: STEP-native undercut feature grouping, depth, release direction, action recommendation |
| 3 | Nee et al. (1998) — *Automatic Determination of 3-D Parting Lines* | Started: adjacent-normal silhouette candidates, wire ordering, projection-aware loop selection, and undercut-conflict scoring |
| 4 | Hou et al. (2018) — *Hybrid approach for automatic parting curve generation* | Started: graph-weighted cleanup/display smoothing; full global optimization planned |

---

## Evaluation Matrix Coverage

| Feature | Level 1 | Level 2 |
|---------|---------|---------|
| STEP parsing / topology | ✅ Implemented | ✅ Foundation |
| Draft analysis | ✅ Implemented | ✅ Foundation |
| Undercut detection | ✅ Implemented with selective Boolean refinement | ✅ Foundation |
| Optimal Mold Direction | ✅ Implemented | ✅ Foundation |
| Main Parting Line | Candidate/refined undercut-aware overlay implemented; full optimization planned | Planned |
| Core and Cavity Extraction | — | Planned |
| Simple GUI & Final Visualization | ✅ Implemented | ✅ Foundation |

---

## Configuration

All DfM thresholds and parameters are in `config.yaml`.  
Edit the file — no code changes needed:

```yaml
dfm:
  draft:
    good_threshold_deg: 1.5    # Change this to adjust "green" threshold
    marginal_threshold_deg: 0.5
  direction_search:
    angular_step_deg: 15       # Finer = more accurate, slower
```

---

## Extending the Code

The modular architecture means:
- **New constraint type?** Add a function in the appropriate geometry module.
- **Different LLM later?** Change `agent.model` in `config.yaml` once the
  LangChain agent layer is implemented.
- **Side cores (Level 3)?** Add `side_core_detector.py` in `backend/geometry/`.
- **Integrate with CATIA/NX?** The `PartGeometry` dataclass is the stable interface.

---

## Team Roles

| Role | Responsibility |
|------|---------------|
| Backend Engineer | `backend/geometry/` modules — pure geometry, no UI |
| Frontend Engineer | `frontend/app.py` — Streamlit 3D visualisation |
| Tester | `tests/` — accuracy metrics, ground truth validation |
| Presenter/Reporter | Report PDF, demo script, slides |
