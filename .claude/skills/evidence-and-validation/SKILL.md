---
name: evidence-and-validation
description: How to run validation harnesses, collect demo evidence, and fill the evidence checklist. Use during demo prep or when asked for metrics/screenshots.
---

# Evidence & Validation

## Validation Harness

```bash
# Basic validation (no Boolean, no direction search)
python -m backend.validation.part_validation --json

# Full validation with direction + Boolean refinement
python -m backend.validation.part_validation --direction --boolean-refine --json

# Fail if expected files are missing
python -m backend.validation.part_validation --fail-on-missing-expected
```

Output: JSON with per-part status, per-step status (load, draft, undercuts, direction, parting-line), warnings, and metrics.

## Performance Profiling

```bash
# Basic profiling
python -m backend.validation.performance_profile --json

# Full profiling with direction + Boolean
python -m backend.validation.performance_profile --direction --boolean-refine --json

# Custom timing budgets
python -m backend.validation.performance_profile \
  --budget load_step=20 \
  --budget display_mesh=15 \
  --budget direction_search=120 \
  --budget parting_line=30 \
  --json
```

Output: JSON with per-step timing, budget status, over-budget warnings.

## Docker Validation Script

```bash
bash scripts/run_level1_docker_validation.sh 3   # 3 runs
```

Runs N iterations inside Docker container, saves to `reports/level1_validation/`.

## Evidence Checklist (from docs/EVIDENCE_CHECKLIST.md)

### Required Screenshots
- [ ] Raw tab with Part1 loaded
- [ ] Draft tab with color legend and metrics
- [ ] Undercut tab with red/blue/gray face overlay
- [ ] Boolean volume overlay (if rendered)
- [ ] Direction tab with best direction and candidate table
- [ ] Mold Action Rationale table
- [ ] Validation harness JSON output
- [ ] Performance profiler JSON output

### Required Metrics
- Part file name, topology counts (solids, faces, edges, vertices)
- Bounding box dimensions
- Draft good/marginal/bad face counts and area percentages
- Undercut face/feature counts and area percentage
- Boolean refined status and checked count
- Best direction label and vector
- Initial vs. optimal bad draft area percentage
- Parting-line readiness status and score

### Current Input Status
- `Part1.stp`: present in `data/parts/`
- `Part2.stp`: NOT present — validation reports it as `missing_expected_files`

### Saved Report Status
The JSON reports currently in `reports/level1_validation/` were generated WITHOUT pythonocc-core. All show `status: "skipped"`. New Docker/conda runs are needed for real evidence.
