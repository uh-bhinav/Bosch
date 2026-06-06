#!/usr/bin/env bash
set -euo pipefail

# Repeatable Phase A/A3 validation runner.
# Usage:
#   bash scripts/run_level1_docker_validation.sh        # 3 runs
#   bash scripts/run_level1_docker_validation.sh 5      # 5 runs

RUN_COUNT="${1:-3}"
SERVICE="${DFM_DOCKER_SERVICE:-backend}"
REPORT_DIR="/app/reports/level1_validation"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker command is not available in this shell." >&2
  exit 127
fi

if [ ! -f "data/parts/Part1.stp" ]; then
  echo "data/parts/Part1.stp is missing. Add Part1.stp before validation." >&2
  exit 2
fi

echo "Starting Docker services..."
docker compose up -d backend frontend

echo "Preparing report directory in ${SERVICE} container..."
docker compose exec -T "${SERVICE}" mkdir -p "${REPORT_DIR}"

echo "Checking backend health..."
docker compose exec -T "${SERVICE}" python -c \
  "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=10).read(); print('backend health OK')"

for run_id in $(seq 1 "${RUN_COUNT}"); do
  echo "Run ${run_id}/${RUN_COUNT}: validation"
  docker compose exec -T "${SERVICE}" /bin/bash -lc \
    "python -m backend.validation.part_validation --direction --boolean-refine --json > ${REPORT_DIR}/part_validation_run_${run_id}.json"

  echo "Run ${run_id}/${RUN_COUNT}: performance profile"
  docker compose exec -T "${SERVICE}" /bin/bash -lc \
    "python -m backend.validation.performance_profile --direction --boolean-refine --json > ${REPORT_DIR}/performance_profile_run_${run_id}.json"
done

echo "Level 1 Docker validation complete."
echo "Host path: reports/level1_validation/"
