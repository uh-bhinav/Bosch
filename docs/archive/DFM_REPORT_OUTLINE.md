> **Archived, superseded.** PDF export IS now implemented
> (`backend/report/pdf_export.py`, `GET /export/report`) — the "current
> code does not export PDF yet" line below predates that work. See
> `README.md` and `docs/IMPLEMENTATION_STATUS.md` for current capability.
> Kept for the original report-structure thinking, not as a live template.

# DFM Report Outline

This outline is the structure for the future Bosch-style PDF DFM report. The
current code does not export PDF yet; use this document as the reporting
template and fill metrics from the Streamlit UI, FastAPI JSON responses, and
validation/profiling harnesses.

## 1. Cover Page

- Project: Bosch RB-CoC Plastics DfM Agent
- Part file: `Part1.stp`
- Analysis date:
- Analysis level: Level 1
- Analysis status:
- Operator/team:

## 2. Executive Summary

Include:

- Recommended mold opening direction.
- Draft severity.
- Undercut feature count.
- Boolean refinement status.
- Main manufacturing risk.
- Recommended next engineering action.

Template:

```text
The DfM Agent analyzed [part file] using STEP-native B-Rep geometry.
The recommended Level 1 mold opening direction is [best label/vector].
Draft analysis found [good/marginal/bad percentages].
Undercut detection found [feature count] feature(s), with [severity summary].
The current recommendation is [primary mold action].
```

## 3. Input Geometry

Include:

- Source file name.
- Solid count.
- Face count.
- Edge count.
- Vertex count.
- Bounding box dimensions.
- Surface type counts.
- Loader warnings, if any.

Screenshots:

- Raw model view.
- Optional topology/summary panel.

## 4. Methodology

### STEP Loader

Describe:

- Native STEP B-Rep loading through pythonOCC.
- Preservation of OCC shape handles for downstream geometry operations.
- Extraction of face normals, areas, centroids, UV bounds, surface types,
  edges, vertices, and adjacency.
- Display mesh is separate from analysis geometry.

### Draft Analysis

Describe:

- Face draft angle computed relative to pull direction.
- Classification thresholds from `config.yaml`.
- Green/yellow/red display overlay.
- Non-mutating result support for before/after comparison.

### Undercut Detection

Describe:

- Fast proxy detection from draft/accessibility/topology.
- Optional swept-face Boolean refinement.
- Feature grouping by adjacency and Boolean-region proximity.
- Depth, severity, release direction, feature type, and action confidence.

### Direction Optimization

Describe:

- Candidate directions include principal axes and sampled directions.
- Draft/undercut scoring ranks candidates.
- Smart pruning limits expensive Boolean checks.
- Final best direction is recomputed and exposed to the UI/API.

## 5. Draft Results

Include table:

| Metric | Value |
|---|---:|
| Good faces | |
| Marginal faces | |
| Bad faces | |
| Good area percent | |
| Marginal area percent | |
| Bad area percent | |
| Severity | |

Screenshots:

- Draft color overlay.
- Suggestions panel.

## 6. Undercut Results

Include table:

| Metric | Value |
|---|---:|
| Undercut faces | |
| Parting faces | |
| Accessible faces | |
| Feature count | |
| Undercut area percent | |
| Boolean refined | |
| Boolean checked count | |

Feature table:

| Feature | Severity | Type | Geometric type | Depth mm | Release direction | Recommended action | Confidence |
|---|---|---|---|---:|---|---|---|
| | | | | | | | |

Screenshots:

- Undercut face overlay.
- Boolean region overlay.
- Mold action rationale.

## 7. Mold Direction Results

Include:

- Best label.
- Best vector.
- Candidate count.
- Best score.
- Initial draft summary.
- Optimal draft summary.
- Boolean pruning/refinement summary.
- Direction cache stats.

Candidate table:

| Rank | Label | Score | Bad area percent | Undercut area percent | Boolean refined |
|---:|---|---:|---:|---:|---|
| | | | | | |

Screenshots:

- Direction tab.
- Candidate table.
- Optimal overlay.

## 8. Recommendations

Summarize:

- Recommended pull direction.
- Faces/features requiring design review.
- Side-action or feature modification recommendations.
- Confidence and reason for each action.
- Known uncertainty or Boolean fallback notes.

## 9. Validation And Performance

Include output from:

```bash
python -m backend.validation.part_validation --direction --boolean-refine --json
python -m backend.validation.performance_profile --direction --boolean-refine --json
```

Report:

- Files discovered.
- Missing expected files.
- Validation status.
- Per-step runtime.
- Over-budget steps.
- Dependency skips, if any.

## 10. Current Limitations

State clearly:

- Backend parting-line candidate/projected-wire/refinement overlay exists, but
  final optimized split validation and export are not implemented yet.
- Core/cavity extraction is not implemented yet.
- LangChain tool-calling is not implemented yet.
- PDF export is not implemented yet.
- Boolean refinement is selective.
- Full Sangolli volumetric decomposition is not implemented.

## 11. Next Engineering Steps

Recommended order:

1. Validate on `Part2.stp` when available.
2. Implement final parting-line optimization polish.
3. Implement core/cavity classification and extraction.
4. Add LangChain tool-calling around deterministic geometry outputs.
5. Add automated PDF export using this report structure.
