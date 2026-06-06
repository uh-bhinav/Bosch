# DfM Agent Implementation Status

This document is the current truth source for what the Bosch RB-CoC Plastics
DfM Agent can do today, what is intentionally approximate, and what remains
planned for later phases.

## Current Level 1 Build

The current build supports a complete Level 1 analysis flow for `Part1.stp`:

1. Load STEP B-Rep geometry through pythonOCC.
2. Extract solids, faces, edges, vertices, topology, face normals, surface types,
   face areas, centroids, and adjacency.
3. Build a display-only PyVista mesh while preserving `face_id` mapping back to
   exact B-Rep faces.
4. Run draft analysis for a selected pull direction.
5. Detect undercut candidates using draft/accessibility/topology heuristics.
6. Refine selected undercut candidates with swept-face Boolean interference
   checks when the OCC runtime is available.
7. Group undercut faces into feature-level objects.
8. Estimate undercut severity, type, local release direction, depth, Boolean
   interference volume, and recommended mold action.
9. Search candidate mold-opening directions using a fast prefilter plus
   Boolean refinement on promising candidates.
10. Display raw geometry, draft colors, undercut highlights, Boolean region
    volumes, best direction, action confidence, and feature rationale in
    Streamlit.
11. Detect initial parting-line candidate edges from silhouette/near-parting
    topology for a selected/optimal pull direction, order the selected
    component into a first-pass wire, score it for undercut conflicts,
    refine/smooth it, display it as an overlay in Streamlit, and report
    readiness/diagnostic-gate status through validation/performance harnesses.

## Implemented Modules

| Module | Status | Notes |
|---|---:|---|
| `backend/geometry/step_loader.py` | Implemented | STEP-native B-Rep load, topology extraction, face normals, surface metadata, warnings. |
| `backend/geometry/visualize_raw.py` | Implemented | Converts exact OCC shapes to display meshes while keeping face IDs. Used for part mesh and Boolean region mesh payloads. |
| `backend/geometry/draft_analyzer.py` | Implemented | Non-mutating and mutating draft analysis, classifications, suggestions, before/after support. |
| `backend/geometry/undercut_detector.py` | Implemented | Proxy undercut detection, optional swept Boolean refinement, feature grouping, feature typing, action confidence, performance metrics. |
| `backend/geometry/direction_optimizer.py` | Implemented | Candidate direction generation, draft scoring, smart Boolean pruning, caching, final optimal direction. |
| `backend/api/main.py` | Implemented | FastAPI endpoints for parts, summary, draft, undercuts, direction, parting line, Boolean region visualization, structured errors. |
| `frontend/app.py` | Implemented | Guided Streamlit UI, step failure diagnostics, PyVista viewer, legends, summaries, parting-line overlay, undercut-conflict display, manual and guided workflows. |
| `backend/geometry/parting_line.py` | Foundation implemented | Nee-style adjacent-normal silhouette and near-parting edge candidates, connected components, ordered wire construction, projection-aware loop selection, undercut-conflict scoring, and Hou-inspired graph cleanup/display smoothing; full Hou global optimization still planned. |
| `backend/validation/part_validation.py` | Implemented | STEP smoke validation, topology checks, draft/undercut/direction checks, and parting-line readiness reporting. |
| `backend/validation/performance_profile.py` | Implemented | Pipeline timing budgets for load, display mesh, draft, undercuts, direction search, and parting-line readiness. |
| `backend/geometry/core_cavity.py` | Not implemented yet | Planned Level 2 item after parting line is stable. |
| `backend/agent/dfm_agent.py` | Not implemented yet | Current UI uses deterministic geometry outputs and explanations; LangChain layer is planned. |
| `backend/agent/tools.py` | Not implemented yet | Planned wrapper layer for LangChain tool-calling. |

## Research Fidelity

### Bassi et al. 2010

Implemented:

- Candidate pull-direction search.
- Surface accessibility proxy using face normals, draft, topology, and signed
  directionality.
- Swept-face Boolean interference check for selected candidates.
- Interference volume and Boolean failure reporting.
- Boolean retry offsets, fuzzy tolerance, sliver-face guard, caching, and
  performance summary.

Not fully implemented:

- Full regularized Boolean accessibility analysis for every face of every
  candidate direction.
- Full exact inaccessible-region classification for all sampled directions.

Reason:

OpenCASCADE Booleans are expensive and can be brittle on real STEP files. The
current architecture uses the production-safe staged approach: fast prefilter
first, then swept Boolean refinement where it most affects the decision.

### Sangolli et al. 2021

Implemented:

- STEP-native undercut feature representation.
- Feature grouping from face adjacency plus Boolean-region proximity.
- Internal/external/interacting classification heuristics.
- Release direction and depth estimates from face and Boolean region geometry.
- Rule-based action recommendation with confidence and explanation.

Not fully implemented:

- Full volumetric decomposition of the entire solid.
- Radix sort over decomposed volumes.
- Complete industrial undercut taxonomy across all possible plastic features.

Reason:

The current Phase 3 scope intentionally limits feature understanding to
Boolean-confirmed undercut regions. This gives useful feature-level output
without the high failure risk of full-part volumetric decomposition.

### Nee et al. 1998 and Hou et al. 2018

Implemented:

- Initial adjacent-normal silhouette edge detection.
- Near-parting edge candidate retention for faces close to the pull-direction
  parting plane.
- Boundary/rim edge candidate support.
- Connected-component grouping over candidate edges.
- Deterministic first-pass wire ordering for simple open chains and closed
  loops, with explicit flags for branches, gaps, and unorderable edges.
- Projection metrics in the pull-normal plane: area, perimeter, bounding-box
  area, projected closure, and quality.
- Projection-aware component selection that prefers clean closed projected
  loops over longer but less plausible candidate chains.
- Undercut-aware conflict scoring using direct edge/face overlap and projected
  proximity to undercut feature locations.
- Wire quality scoring that combines topology quality, projection quality,
  non-manifold/boundary penalties, and undercut-conflict penalties.
- Readiness scoring that summarizes the selected parting-line candidate as
  ready/review/weak/failed with reasons and blockers.
- Diagnostic gate that tells downstream consumers whether the curve can be
  displayed, used in a report, or should block core/cavity extraction.
- Structured parting-line diagnostics with skipped-edge reasons, failure
  codes, recovery hints, branch/gap counts, and unorderable-edge counts.
- Boundary-candidate filtering so open/rim edges are retained only when their
  adjacent face is close to the pull-direction parting plane.
- Candidate component noise scoring for boundary-only and non-manifold-heavy
  components.
- Hou-inspired graph cleanup for branched/gapped candidate components,
  including bounded weighted path search for small/medium candidate graphs and
  deterministic greedy fallback for large graphs.
- Display smoothing for the refined parting-curve candidate while preserving
  raw selected B-Rep edge IDs.
- API and Streamlit overlay support for raw/refined candidate curves.

Planned:

- Full Hou-style global graph optimization for difficult competing paths.
- Final production-grade parting-curve visualization polish and validation.

## Known Limitations

- Final fully optimized and visualized parting line generation is not available yet.
- Undercut-aware parting-line conflict scoring is still an engineering
  heuristic, not an exact proof that a line is mold-safe.
- Core/cavity extraction is not available yet.
- The LangChain AI agent layer is not available yet.
- PDF report export is not available yet.
- Boolean refinement is selective, not exhaustive across every candidate.
- Undercut depth is still an engineering estimate, although it now prefers
  Boolean geometry evidence when available.
- Internal/external feature typing is rule-based and may misclassify complex
  interacting or nested geometry.
- UI quality depends on PyVista, VTK, stpyvista, and an Xvfb-capable Docker
  runtime.

## Graceful Degradation

The app is designed to continue working when optional or expensive pieces fail:

- If CadQuery is unavailable, pythonOCC STEP loading can still proceed.
- If PyVista is unavailable, the frontend shows mesh counts and structured JSON
  fallback instead of crashing.
- If Boolean refinement fails on a face, the detector reports failure details
  and preserves proxy evidence where appropriate.
- If `data/parts` is missing, `/parts` returns an empty list plus a warning.
- API errors return structured `code`, `message`, `operation`, `recovery_hint`,
  and `details` fields for frontend display.

## Current Demo Flow

Recommended Level 1 demo sequence:

1. Start Docker.
2. Open Streamlit at `http://localhost:8501`.
3. Select `Part1.stp`.
4. Click `Run Full Level 1 Flow`.
5. Review:
   - Raw topology and display mesh.
   - Draft color map.
   - Undercut highlights and Boolean volumes.
   - Best mold opening direction and candidate ranking.
   - Parting-line candidate/refinement overlay.
   - Mold action rationale and confidence.

## Validation Harness

Use the validation harness to smoke-test every STEP file currently available in
`data/parts`:

```bash
python -m backend.validation.part_validation --json
```

Current workspace status:

- `Part1.stp` is present in `data/parts`.
- `Part2.stp` is not present yet, so the harness reports it in
  `missing_expected_files`.

For a deeper Docker/conda validation pass with the full direction optimizer:

```bash
python -m backend.validation.part_validation --direction --boolean-refine --json
```

To make CI fail when an expected hackathon input is missing:

```bash
python -m backend.validation.part_validation --fail-on-missing-expected
```

## Performance Profiling

Use the performance profiler to measure the current Level 1 pipeline:

```bash
python -m backend.validation.performance_profile --json
```

The default profile measures:

- STEP load
- Display mesh generation
- Default +Z draft analysis
- Default +Z undercut detection
- Parting-line readiness and quality

For a deeper demo-readiness profile in Docker/conda:

```bash
python -m backend.validation.performance_profile --direction --boolean-refine --json
```

Default timing budgets are intentionally conservative and can be overridden:

```bash
python -m backend.validation.performance_profile \
  --budget load_step=20 \
  --budget display_mesh=15 \
  --budget direction_search=120 \
  --budget parting_line=30 \
  --json
```

## Next Implementation Phases

1. Validate current Level 1 flow on `Part2.stp` when available.
2. Capture Docker/conda validation and performance results for `Part1.stp`.
3. Implement full Hou-style parting-line optimization and final visualization polish.
4. Implement Level 2 core/cavity classification and extraction.
5. Add LangChain tool-calling agent using the deterministic geometry outputs.
6. Add PDF DFM report export with snapshots and annotations.
