---
paths:
  - "config.yaml"
  - "docker-compose.yml"
  - "environment.yml"
  - "Dockerfile.backend"
  - "Dockerfile.frontend"
  - "requirements.txt"
  - ".gitignore"
---

# Config & Infrastructure Rules

## config.yaml

All DfM thresholds and parameters live here. Structure:
```yaml
dfm:
  draft:
    good_threshold_deg: 1.5
    marginal_threshold_deg: 0.5
  direction_search:
    angular_step_deg: 15.0
    max_candidates: 54
    # ... Boolean pruning parameters
  parting_line:
    smoothing_iterations: 8
    # ... curve display parameters
  core_cavity:
    threshold: 0.05
    cavity_color: [0.2, 0.8, 0.3]
    core_color: [0.2, 0.45, 0.9]
agent:
  model: "gpt-4o-mini"
  temperature: 0.1
```

When changing thresholds: edit the YAML, run tests, verify.

## Docker Architecture

- `Dockerfile.backend`: Multi-stage conda build. Base = `continuumio/miniconda3:24.1.2-0`. Installs pythonocc-core=7.7.2 + cadquery=2.4.0 via conda-forge. Builder stage verifies `import OCC; import cadquery; import pyvista; import stpyvista`.
- `Dockerfile.frontend`: Python 3.10-slim + pip. VTK/PyVista/Streamlit only. Uses `xvfb-run` for headless rendering.
- `docker-compose.yml`: Two services — `backend` (:8000) and `frontend` (:8501). Backend has health check. Frontend depends on backend.

## Environment Dependencies

pythonocc-core and cadquery are CONDA-ONLY (not pip). Everything else is pip-installable. The `environment.yml` captures both conda and pip deps.

```
conda deps: python=3.11, pythonocc-core=7.7.2, cadquery=2.4.0, numpy, scipy, vtk
pip deps: streamlit, pyvista, stpyvista, fastapi, uvicorn, langchain, openai, reportlab, etc.
```

## Volume Mounts (Docker)

```
./data:/app/data          # STEP files (read-only in practice)
./reports:/app/reports    # Generated validation/perf reports
./backend:/app/backend    # Live-reload during dev
./frontend:/app/frontend  # Live-reload during dev
./tests:/app/tests        # Live-reload during dev (backend only; added 2026-07-28)
./config.yaml:/app/config.yaml:ro  # Config without image rebuild
```

## Ports

| Service | Port | URL |
|---|---|---|
| FastAPI backend | 8000 | http://localhost:8000/docs |
| Streamlit frontend | 8501 | http://localhost:8501 |
