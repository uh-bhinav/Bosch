# Known Gaps — What's Not Implemented

> Update this file whenever a gap is closed or a new one is discovered.
> Last updated: 2026-07-27

## ❌ Not Implemented (Empty / Missing)

| Gap | File(s) | Impact |
|---|---|---|
| AI Agent layer (LangChain tool-calling) | `backend/agent/dfm_agent.py` (0 lines), `backend/agent/tools.py` (0 lines) | Core hackathon deliverable — it's an "AI Agent" hackathon |
| PDF report export | No code anywhere | `reportlab` in requirements but never imported |
| Part2.stp analysis | `data/parts/Part2.stp` does not exist | Cannot validate Level 2 complexity |

## ⚠️ Partially Implemented

| Gap | Current State | What's Missing |
|---|---|---|
| Core/cavity extraction | Face classification only (140 lines in `core_cavity.py`) | Boolean solid split into two separate mold-half bodies |
| Parting line | Candidate silhouette overlay with Chaikin smoothing | Full Hou-style global graph optimization, parting surface generation |
| Bassi 2010 fidelity | Selective swept Boolean on top candidates | Exhaustive Boolean for every face of every direction |
| Sangolli 2021 fidelity | Adjacency + Boolean-region feature grouping; edge convexity computed at load time and used to suppress centroid-normal false positives (2026-07-27) | Volumetric decomposition, radix sort |

## 📋 Infrastructure Gaps

| Gap | Notes |
|---|---|
| No type checking | No mypy, pyright, or ruff config |
| Frontend is monolith | `app.py` is 3,905 lines in one file |
| No `__init__.py` in `backend/geometry/` | Module works via relative imports but isn't a proper package |
| No CI/CD | No GitHub Actions, no automated testing pipeline |
