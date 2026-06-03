# DfM Agent — Bosch RB-CoC Plastics Hackathon

**Automatic Parting Line Detection & DfM Analysis for Injection-Molded Automotive Parts**

---

## What This Is

A production-ready AI-driven DfM (Design for Manufacturability) Agent that:

1. **Loads** a real STEP (`.stp`) B-Rep file from Siemens NX/CATIA
2. **Detects** the optimal mold opening direction (Bassi 2010 algorithm)
3. **Recognises** undercut features with depth/type/location (Sangolli 2021)
4. **Generates** and refines the main parting line (Nee 1998 + Hou 2018)
5. **Extracts** Core vs Cavity surfaces (Level 2)
6. **Visualises** everything in an interactive 3D web UI
7. **Generates** an intelligent AI explanation + PDF DFM report

Reduces the mold engineer's DfM verification from **3–4 hours → 5–10 minutes**.

---

## Quick Start (Docker)

```bash
# 1. Place your STEP file
cp Part1.stp data/parts/

# 2. Set API key (optional — agent works without LLM for geometry analysis)
export OPENAI_API_KEY=sk-...   # or GROK_API_KEY

# 3. Start everything
docker compose up

# 4. Open in browser
open http://localhost:8501     # Streamlit UI
open http://localhost:8000/docs  # FastAPI docs
```

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

# 5. Start Streamlit frontend
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
│   │   ├── parting_line.py        # Module 5: Nee 1998 + Hou 2018
│   │   └── core_cavity.py         # Module 6: Level 2 core/cavity split
│   ├── models/
│   │   └── geometry_models.py     # Shared dataclasses (PartGeometry, FaceData…)
│   ├── agent/
│   │   ├── dfm_agent.py           # LangChain orchestrator
│   │   └── tools.py               # Tool definitions wrapping geometry modules
│   ├── api/
│   │   └── main.py                # FastAPI app
│   └── config.py                  # Settings loader (reads config.yaml)
├── frontend/
│   └── app.py                     # Streamlit interactive 3D UI
├── tests/                         # pytest suite
├── data/parts/                    # Drop .stp files here
├── reports/                       # Generated PDF DFM reports
├── config.yaml                    # ALL thresholds and parameters
├── environment.yml                # Conda dependencies
├── requirements.txt               # Pip dependencies
├── Dockerfile
└── docker-compose.yml
```

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
[5] parting_line.py ─────────────── Parting line (Nee 1998 + Hou 2018)
    │
    ▼
[6] core_cavity.py ──────────────── Core / Cavity split (Level 2)
    │
    ▼
[7] dfm_agent.py ────────────────── LLM reasoning + natural-language suggestions
    │
    ▼
    Interactive 3D UI + PDF Report
```

---

## Research Papers Implemented

| # | Paper | Role in Pipeline |
|---|-------|-----------------|
| 1 | Bassi et al. (2010) — *Undercut-Free Parting Direction Determination* | Optimal mold direction via sweeping + Boolean accessibility |
| 2 | Sangolli et al. (2021) — *Algorithms for sorting and recognizing undercut features* | STEP-native undercut classification, depth, release direction |
| 3 | Nee et al. (1998) — *Automatic Determination of 3-D Parting Lines* | Silhouette projection → initial parting line loop |
| 4 | Hou et al. (2018) — *Hybrid approach for automatic parting curve generation* | Graph-based smoothing → manufacturable parting curve |

---

## Evaluation Matrix Coverage

| Feature | Level 1 | Level 2 |
|---------|---------|---------|
| Optimal Mold Direction | ✅ | ✅ |
| Main Parting Line | ✅ | ✅ |
| Core and Cavity Extraction | — | ✅ |
| Simple GUI & Final Visualization | ✅ | ✅ |

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
- **Different LLM?** Change `agent.model` in `config.yaml`.
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