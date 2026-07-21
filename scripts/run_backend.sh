#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export MAMBA_ROOT_PREFIX="$ROOT/.micromamba/root"
export PYTHONPATH="$ROOT"
exec "$ROOT/.micromamba/bin/micromamba" run -r "$MAMBA_ROOT_PREFIX" -n dfm_agent \
  uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
