---
paths:
  - "frontend/**"
---

# Frontend Rules

## No OCC Imports

The frontend NEVER imports anything from `OCC`, `pythonOCC`, or `cadquery`. It talks to the backend API only. All geometry data arrives as JSON via `requests.get(BACKEND_URL/...)`.

## Streamlit Rerun Model

Streamlit reruns the entire `app.py` script on every user interaction. State survives only in `st.session_state`. Key session state keys:
- `dfm_step` — current pipeline step index
- `dfm_part` — selected STEP filename
- `dfm_results` — dict of step results from API
- `dfm_error` — last error for display

## PyVista / VTK Rendering

- macOS: uses Plotly fallback (PyVista headless issues).
- Linux/Docker: uses PyVista via `stpyvista` with `xvfb-run`.
- Environment variables set at top of `app.py`: `PYVISTA_OFF_SCREEN=true`, `VTK_DEFAULT_RENDER_WINDOW_OFFSCREEN=1`.
- If PyVista fails, the app shows mesh counts + JSON instead of crashing.

## Single-File Architecture

`frontend/app.py` is currently 3,905 lines in one file. When modifying:
- All CSS is injected via `_inject_app_styles()` at the top.
- The guided flow has 5 steps: Load → Draft → Undercuts → Direction → Parting Line.
- Status chips use custom HTML/CSS classes (`dfm-chip-complete`, `dfm-chip-failed`, etc.).
- The "AI Mold Engineer Journey" is the main UI paradigm.

## Backend Communication

```python
BACKEND_URL = os.environ.get("DFM_BACKEND_URL", "http://localhost:8000")
response = requests.get(f"{BACKEND_URL}/parts/{filename}/summary")
```

In Docker, `DFM_BACKEND_URL=http://backend:8000` (service name). Locally, it defaults to `http://localhost:8000`.
