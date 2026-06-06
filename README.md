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

### Prerequisites

- Anaconda or Miniconda
- Python 3.11

### Setup

```bash
# 1. Create conda environment with pythonOCC
conda env create -f environment.yml
conda activate dfm_agent

# 2. Verify pythonOCC is working
python -c "from OCC.Core.STEPControl import STEPControl_Reader; print('OCC OK')"

# 3. Run the STEP loader directly
python -m backend.geometry.step_loader data/parts/Part1.stp --json

# 4. Run tests
pytest tests/ -v

# 5. Validate available STEP demo files
python -m backend.validation.part_validation --json

# 6. Profile available STEP demo files
python -m backend.validation.performance_profile --json

# 7. Start Streamlit frontend
streamlit run frontend/app.py
```

> **Why conda?**  
> `pythonocc-core` has C++ extension modules that are reliably available only
> on conda-forge.  Pip builds exist but often fail on certain platforms.

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
