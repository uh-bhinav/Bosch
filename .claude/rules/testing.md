---
paths:
  - "tests/**"
---

# Testing Rules

## Test Execution

```bash
# Full suite
pytest tests/ -v --tb=short -s

# Single module
pytest tests/test_draft_analyzer.py -v --tb=short

# With coverage
pytest tests/ --cov=backend --cov-report=term-missing
```

## Layered Test Order

Tests should be run and validated in this order. Don't skip layers — each builds on the previous:

1. **Data models** — `geometry_models.py` dataclasses, `Vec3` helpers, `to_dict()` serialization
2. **Step loader** — STEP parsing, face/edge/vertex extraction, adjacency
3. **Draft analyzer** — angle computation, classification, suggestions
4. **Undercut detector** — proxy detection, Boolean refinement, feature grouping
5. **Direction optimizer** — candidate generation, scoring, pruning
6. **Parting line** — silhouette edges, components, wire ordering
7. **API** — endpoint responses, error handling, structured errors
8. **Validation harnesses** — end-to-end smoke tests

## OCC Mocking Strategy

Tests mock OCC objects because pythonocc-core may not be installed in the test environment (pip-only CI). The pattern:
- Create `FaceData` with explicit `normal`, `area`, `face_id` but `occ_face=None` or a mock.
- Create `PartGeometry` with pre-populated `faces`, `edges`, `face_adjacency`.
- The analysis functions work on the data fields, not the OCC handles directly (OCC handles are only used by `step_loader` during initial extraction).

## Threshold Source

All test thresholds come from `config.yaml` via `backend.config.settings`. Tests should NOT hardcode threshold values — import them from config so tests stay in sync.

## Test Naming Convention

```
test_{module}_{scenario}_{expected_behavior}
```

Example: `test_draft_analyzer_bad_face_gets_red_classification`

## pytest Config

`tests/pytest.ini` contains markers and default options. Key settings:
- `markers`: unit, integration, slow, requires_occ
- Default args: `-v --tb=short`
