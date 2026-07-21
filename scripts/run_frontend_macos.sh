#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export MAMBA_ROOT_PREFIX="$ROOT/.micromamba/root"
export PYTHONPATH="$ROOT"
export DFM_FORCE_PLOTLY=1
export PYVISTA_OFF_SCREEN=true
export VTK_DEFAULT_RENDER_WINDOW_OFFSCREEN=1
# pyarrow's bundled mimalloc (3.3.x) segfaults on macOS the first time a new
# thread performs an Arrow allocation after the thread that first touched
# libarrow has exited (upstream bug microsoft/mimalloc#1287, apache/arrow#50471).
# Streamlit reruns each interaction on a fresh-ish thread, so this crashes the
# whole app whenever st.dataframe() is rendered. Must be set before the
# streamlit process starts (setting it inside app.py is too late).
export ARROW_DEFAULT_MEMORY_POOL=system
exec "$ROOT/.micromamba/bin/micromamba" run -r "$MAMBA_ROOT_PREFIX" -n dfm_agent \
  streamlit run frontend/app.py \
  --server.port 8501 \
  --server.headless true \
  --server.fileWatcherType none \
  --global.developmentMode false
