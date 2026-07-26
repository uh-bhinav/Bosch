# /status — Quick project status check

Run these checks and produce a concise summary:

1. `find data/parts/ -name "*.stp"` — which STEP files are available?
2. `wc -l backend/agent/dfm_agent.py backend/agent/tools.py` — is agent still empty?
3. `wc -l backend/geometry/core_cavity.py` — current core/cavity size
4. `grep -c "def " backend/geometry/*.py` — function count per module
5. `pytest tests/ -v --tb=line -q 2>&1 | tail -5` — quick test status
6. Check `docker compose ps` if Docker is running.

Then update `STATUS.md` with the current snapshot.
