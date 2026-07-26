---
name: run-dfm-stack
description: Exact recipes for starting the full DfM stack locally or in Docker. Use when setting up, debugging, or demonstrating the application.
---

# Running the DfM Stack

## Docker (Recommended for Demo)

```bash
# Start everything
docker compose up

# Rebuild after code changes
docker compose up --build

# Start in background
docker compose up -d

# Check status
docker compose ps

# View logs
docker compose logs -f backend
docker compose logs -f frontend

# Run tests inside Docker
docker compose exec backend pytest tests/ -v --tb=short

# Run validation inside Docker
docker compose exec backend python -m backend.validation.part_validation --direction --boolean-refine --json

# Stop everything
docker compose down
```

**Ports**: Backend → http://localhost:8000 (FastAPI docs at /docs), Frontend → http://localhost:8501

## Local Conda/Micromamba

### One-Time Setup
```bash
# Create environment
conda env create -f environment.yml
conda activate dfm_agent

# Verify OCC
python -c "from OCC.Core.STEPControl import STEPControl_Reader; print('OCC OK')"

# Verify full stack
python -c "import OCC; import cadquery; import pyvista; import stpyvista; print('All deps OK')"
```

### Running (Two Terminals)
```bash
# Terminal 1: Backend
conda activate dfm_agent
uvicorn backend.api.main:app --reload --port 8000

# Terminal 2: Frontend
conda activate dfm_agent
streamlit run frontend/app.py
```

### Quick Validation
```bash
# Load a STEP file directly
python -m backend.geometry.step_loader data/parts/Part1.stp --json

# Run draft analysis
python -m backend.geometry.draft_analyzer data/parts/Part1.stp

# Run tests
pytest tests/ -v --tb=short

# Health check
curl http://localhost:8000/health
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `ImportError: pythonocc-core` | Use conda, not pip. `conda install -c conda-forge pythonocc-core=7.7.2` |
| PyVista rendering fails in Docker | Check `xvfb-run` is in the command. Set `PYVISTA_OFF_SCREEN=true` |
| Frontend can't reach backend | Check `DFM_BACKEND_URL` env var. In Docker: `http://backend:8000`. Locally: `http://localhost:8000` |
| Boolean operations crash | OCC Booleans are brittle. The detector has retry logic. Check logs for `BooleanShapeAnalysis.failure_reason` |
| `Part2.stp not found` | File is not in the repo yet. Add to `data/parts/` when received |
