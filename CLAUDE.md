# DfM Agent — Bosch RB-CoC Plastics Hackathon

## Identity

STEP-native DfM (Design for Manufacturability) Agent for injection-molded automotive plastic parts. Analyzes exact B-Rep geometry from `.stp` files via pythonOCC. Level 1 geometry pipeline is end-to-end; AI agent layer and Level 2 solid extraction are in progress.

## Run Commands

```bash
# Docker (recommended — includes pythonocc-core)
docker compose up                         # backend :8000, frontend :8501
docker compose exec backend pytest tests/ -v --tb=short

# Local conda/micromamba (two terminals)
conda activate dfm_agent                  # or: micromamba activate dfm_agent
uvicorn backend.api.main:app --reload --port 8000   # terminal 1
streamlit run frontend/app.py                        # terminal 2

# Validation & profiling
python -m backend.validation.part_validation --direction --boolean-refine --json
python -m backend.validation.performance_profile --direction --boolean-refine --json
```

## Architecture (Critical)

```
Part1.stp
   │
   ▼
step_loader.py ──► PartGeometry (faces, edges, normals, topology, adjacency)
   │
   ├── draft_analyzer.py ──────► good / marginal / bad draft per face
   ├── undercut_detector.py ───► features + Boolean refinement
   ├── direction_optimizer.py ──► best mold opening direction
   ├── parting_line.py ─────────► silhouette wire + Chaikin smoothing
   └── core_cavity.py ──────────► cavity / core / parting face split
           │
           ▼
   backend/api/main.py (REST) ──► frontend/app.py (Streamlit UI)
```

**Stateless backend**: The API re-parses the STEP file on every endpoint call. There is no shared in-memory part state between requests. Each endpoint loads → analyzes → returns → discards.

**Pull direction is foundational**: Everything downstream (draft, undercuts, parting line, core/cavity) is computed relative to a pull direction. If the direction changes, everything must be recomputed.

## The `mutate` Flag Contract

Most geometry functions accept `mutate: bool`:
- `mutate=False` — scoring/comparison loops. Does NOT modify `FaceData` fields. Returns a standalone result snapshot.
- `mutate=True` — final displayed result. WRITES `draft_angle_deg`, `draft_classification`, `is_undercut`, `cavity_or_core` etc. onto `FaceData` objects.

**Rule**: Never use `mutate=True` inside a candidate-scoring loop. Only the final chosen direction gets `mutate=True`.

## Data Flow Invariants

- `PartGeometry` is the single object that flows through the entire pipeline. Every module takes it as input.
- `face_id` values are sequential integers (0-based) assigned by `step_loader` in TopExp_Explorer order. They are **stable** across reloads of the same `.stp` file.
- `occ_face`, `occ_edge`, `occ_shape` are live C++ handles. They **never** get serialized directly. Always use `.to_dict()` for API/JSON output.
- Display meshes (PyVista) are separate from analysis geometry. Analysis always uses exact B-Rep faces.

## Hard Invariants — Do Not Violate

1. **OCC only via conda/micromamba, NEVER pip.** `pythonocc-core` C++ extensions are only reliably available on conda-forge. The loader itself warns about this.
2. **Never modify files in `data/parts/`.** STEP fixtures are read-only inputs.
3. **Never import OCC in `frontend/`.** The frontend talks to the backend API only. All OCC usage is backend-only.
4. **All config thresholds live in `config.yaml`.** No hardcoded magic numbers in algorithm code. Edit the YAML, not the source.
5. **Structured API errors.** Every error response from `backend/api/main.py` must include: `code`, `message`, `operation`, `recovery_hint`, `details`.

## Honesty Rule

This project has an explicit honesty policy. See `.claude/rules/honesty-and-scope.md` for the full "claims to avoid" list. Short version:
- Never claim the AI agent layer is implemented (files are empty).
- Never claim full Bassi/Sangolli paper implementation (it's selective/partial).
- Never claim core/cavity solid extraction (it's face classification only).
- Never claim PDF export (zero code exists).
- Parting line is "candidate/foundation," not "final optimized."

## Current Gaps

See `.claude/memory/known-gaps.md` for the live list of what's not implemented.

## Project Tracking

Three files are maintained for cross-team documentation:
- `STATUS.md` — current state of every module, updated after each change session.
- `CHANGELOG.md` — append-only log of what changed, when, and why.
- `TODO.md` — prioritized list of what remains to be done.

## Key Paths

| Path | Purpose |
|---|---|
| `backend/geometry/` | Core geometry engine (the "brain") |
| `backend/models/geometry_models.py` | Shared dataclasses — zero internal imports |
| `backend/api/main.py` | FastAPI REST layer |
| `backend/agent/` | AI agent layer (NOT implemented yet) |
| `frontend/app.py` | Streamlit UI (3,905 lines, single file) |
| `tests/` | pytest suite (~4,100 lines) |
| `config.yaml` | All thresholds and parameters |
| `data/parts/` | STEP input files (read-only) |
| `docs/IMPLEMENTATION_STATUS.md` | Authoritative capability status |
| `docs/DEMO_SCRIPT.md` | Demo narration with "claims to avoid" |

## Rules, Skills, and Memory

- **Path-scoped rules** → `.claude/rules/` (loaded only when touching matching files)
- **Domain knowledge** → `.claude/skills/` (loaded on demand, not always in context)
- **Architecture decisions** → `.claude/memory/decisions.md`
- **Known gaps** → `.claude/memory/known-gaps.md`
- **Subagent definitions** → `.claude/agents/` (isolated context for verbose ops)
