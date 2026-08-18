> **Archived.** Internal prep checklist from an earlier submission cycle.
> Kept for reference; not required reading for reviewing the current build.

# Evidence Checklist

Use this checklist before the final demo or report submission. Every number and
screenshot should come from a real run, not from memory.

## Required Screenshots

- [ ] Raw tab with Part1 loaded.
- [ ] Draft tab with color legend and metrics.
- [ ] Undercut tab with red/blue/gray face overlay.
- [ ] Boolean volume overlay, if rendered successfully.
- [ ] Direction tab with best direction and candidate table.
- [ ] Mold Action Rationale table.
- [ ] Validation harness JSON output.
- [ ] Performance profiler JSON output.

## Required Metrics

- [ ] Part file name.
- [ ] Solid count.
- [ ] Face count.
- [ ] Edge count.
- [ ] Vertex count.
- [ ] Bounding box dimensions or diagonal.
- [ ] Draft good/marginal/bad face counts.
- [ ] Draft good/marginal/bad area percentages.
- [ ] Undercut face count.
- [ ] Undercut feature count.
- [ ] Undercut area percentage.
- [ ] Boolean refined status.
- [ ] Boolean checked count.
- [ ] Best direction label.
- [ ] Best direction vector.
- [ ] Candidate count.
- [ ] Initial bad draft area percentage.
- [ ] Optimal bad draft area percentage.
- [ ] Parting-line readiness status and score.
- [ ] Parting-line diagnostic failure code, if any.
- [ ] Parting-line undercut conflict level and score.
- [ ] Parting-line undercut context source.
- [ ] Whether the parting-line step used Boolean-refined undercut context.

## Validation Commands

Recommended repeatable Docker evidence run:

```bash
bash scripts/run_level1_docker_validation.sh 3
```

This writes JSON artifacts to:

```text
reports/level1_validation/
```

Run:

```bash
python -m backend.validation.part_validation --direction --boolean-refine --json
```

Record:

- [ ] Overall status.
- [ ] Discovered files.
- [ ] Missing expected files.
- [ ] Per-step status.
- [ ] Runtime dependency skips.

## Performance Commands

Run:

```bash
python -m backend.validation.performance_profile --direction --boolean-refine --json
```

Record:

- [ ] Per-step runtime.
- [ ] Budget status.
- [ ] Over-budget steps.
- [ ] Direction cache stats.
- [ ] Boolean performance summary, if present.

## Claims Review

Before presenting, verify these are still true:

- [ ] Final parting line is not claimed as complete unless Hou-style
      refinement, visualization, and validation are implemented.
- [ ] Core/cavity extraction is not claimed as implemented unless
      `core_cavity.py` is actually built and validated.
- [ ] LangChain agent is not claimed as implemented unless `backend/agent/`
      contains working code and tests.
- [ ] PDF export is not claimed as implemented unless a real PDF is generated
      and visually checked.
- [ ] Part2 results are not claimed unless `Part2.stp` is present and validated.

## Files To Reference

- `README.md`
- `docs/IMPLEMENTATION_STATUS.md`
- `docs/DEMO_SCRIPT.md`
- `docs/DFM_REPORT_OUTLINE.md`
- `docs/SLIDE_STORYBOARD.md`
- `backend/validation/part_validation.py`
- `backend/validation/performance_profile.py`
