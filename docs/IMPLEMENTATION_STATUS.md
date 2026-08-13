# DfM Agent Implementation Status

This document is the current truth source for what the Bosch RB-CoC Plastics
DfM Agent can do today, what is intentionally approximate, and what remains
planned for later phases.

## Current Level 1 Build

The current build supports a complete Level 1 analysis flow for both
`Part1.stp` and `Part3.stp`:

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

## Current Level 2 Build (partial)

Beyond Level 1, the build also supports:

1. Guaranteed loop closure and parting-surface generation (PCA planar
   extrusion, `BRepFill_Filling` fallback) from the selected parting-line
   candidate.
2. Real Boolean core/cavity solid split (`split_core_cavity_solids()`),
   verified `split_ok` with exactly 2 solids on both real demo parts,
   classified by pull-direction sign. The Boolean splitting tool is a
   separate, labeled planar approximation
   (`build_planar_split_tool()`/`split_tool_kind="planar_approximation"`),
   not the surface from (1) above — that real 3-D `BRepFill_Filling` patch
   is confirmed topologically invalid on both parts (see CHANGELOG.md
   "Stage 2b", 2026-07-28) and cannot currently be used as a Boolean tool.
3. AP214 STEP export of the resulting mold halves (`export_mold_halves()`,
   `POST /parts/{filename}/export/mold-halves`), verified to reload with
   exactly 2 solids on both real demo parts.
4. Side-core generation (Bosch criterion #5, first increment,
   `backend/geometry/side_core.py`): one side-core solid for the single
   highest-confidence critical undercut feature, Boolean-subtracted from its
   containing mold half, exported as a third solid in the same AP214 file.
   Verified 3-solid STEP export/reload with conserved volumes on both real
   demo parts. Grouped/multi-feature generation is not implemented.

This is face/solid-level Level 2 work, not full mold-design validation —
see Known Limitations below, and `CHANGELOG.md`'s Bug H/H-2/H-3 entries for
how selection quality on fragmented-silhouette parts (`Part3.stp`) was
measured and improved.

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
| `backend/geometry/core_cavity.py` | Implemented, verified end-to-end | Grown from face-classification-only (139 lines) to a real Boolean solid split: oversized mold blank via `BRepPrimAPI_MakeBox`, `BRepAlgoAPI_Cut` against the part, `BRepAlgoAPI_Splitter` against a labeled planar-approximation tool (`build_planar_split_tool()`) → 2 solids, classified cavity/core by centroid-offset sign along the pull direction. `export_mold_halves()` writes them to AP214 STEP via `STEPControl_Writer`. Both stages report structured failure reasons rather than raising. Verified `split_ok` + reloadable 2-solid STEP export on both `Part1.stp` and `Part3.stp` (Stage 2b, 2026-07-28). |
| `backend/geometry/side_core.py` | First increment implemented, verified end-to-end | Bosch criterion #5. Generates ONE side-core solid for the single highest-confidence critical undercut feature: sweeps a planar proxy of its face footprint along its `release_direction`, Boolean-subtracts it from whichever mold half contains it, exports as a third AP214 solid alongside cavity/core. Verified 3-solid STEP export/reload with conserved volumes (<0.001% error) on both `Part1.stp` and `Part3.stp` (Stage 4, 2026-07-28). Grouped/multi-feature generation and lifter-vs-slide-vs-collapsible-core classification are explicitly out of scope — see `docs/ARCHITECTURE_ROADMAP.md` Stage 4 §4.3/§4.6. |
| `backend/agent/dfm_agent.py` | Implemented, verified end-to-end | Provider-agnostic tool-calling orchestration loop (NOT LangChain — calls each provider's native SDK directly via `backend/agent/providers.py`). Verified live against real `Part1.stp` through Gemini: real tool calls, a schema-valid `DfMReport` citing a genuine measured finding (face 232, 1.075°/1.5° draft). `tools_called`/`pull_direction`/`pull_direction_source` are tracked mechanically, never model-reported. |
| `backend/agent/tools.py` | Implemented, verified end-to-end | 6 tools wrapping `analyze_draft`/`detect_undercuts`/`optimize_mold_direction`/`detect_parting_line_candidates`/`classify_core_cavity`/part loading. Never returns OCC handles, always `mutate=False`, truncates face-ID lists, never raises (structured `{"status":"error",...}` instead) — all four verified against real Part1.stp geometry. |
| `backend/agent/providers.py` / `schemas.py` / `prompts.py` | Implemented | `LLMProvider` protocol + Gemini (live-verified)/Anthropic/OpenAI/Grok adapters; pydantic `DfMReport`/`DfMFinding` with `evidence_source`; system prompt enforcing this project's own honesty rules. Anthropic/OpenAI/Grok built from verified real SDK signatures and unit-tested with mocks, not live-tested (no API key available for those three). |
| `backend/report/pdf_export.py` / `templates.py` | Implemented, verified end-to-end | Pure presentation layer: takes the same `.to_dict()` payloads every analysis endpoint returns and lays them out via reportlab's Platypus — no recomputation. Aggregates every warning/degraded-confidence flag from every source into a top-of-report "Warnings" section. Verified on real `Part1.stp`/`Part3.stp` and via the live `POST /parts/{filename}/export/report` endpoint + frontend button. |

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
- Core/cavity real solid split and AP214 mold-half STEP export are
  implemented (`backend/geometry/core_cavity.py`), but on parts whose
  parting surface is fragmented (e.g. `Part3.stp`'s silhouette is split
  across many disconnected B-Rep components) the split can fail or the
  resulting solids can be lower quality than on a clean single-loop part.
  Not a substitute for a full mold-design review.
- The AI agent layer (`backend/agent/`) is implemented and live-verified
  against Gemini (not LangChain — a provider-agnostic layer calling each
  provider's native SDK directly). Anthropic/OpenAI/Grok are structurally
  verified, not yet live-tested.
- PDF report export (`backend/report/`) is implemented and verified
  end-to-end — a pure presentation layer over already-computed analysis
  results, no new computation. Screenshot embedding and AI agent narrative
  inclusion are both opt-in.
- Boolean refinement is selective, not exhaustive across every candidate.
- Undercut depth is still an engineering estimate, although it now prefers
  Boolean geometry evidence when available.
- Internal/external feature typing is rule-based and may misclassify complex
  interacting or nested geometry.
- The interactive Plotly viewer is used on both macOS (`sys.platform ==
  "darwin"`) and Docker (`DFM_FORCE_PLOTLY=1` in `docker-compose.yml`), so
  both environments now render identically; a PyVista/VTK/stpyvista/Xvfb
  fallback remains for non-Plotly environments.

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

- `Part1.stp` and `Part3.stp` are both present in `data/parts` and both
  validated end to end (Level 1 flow plus core/cavity solid split and
  mold-half STEP export).

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

1. Implement full Hou-style parting-line optimization and final visualization polish.
2. Improve core/cavity solid-split robustness on parts with fragmented
   silhouettes (see Bug H-2/H-3 in `CHANGELOG.md` — ring bridging now
   produces a genuinely closeable loop on `Part3.stp`, but the split itself
   isn't yet re-verified against the newest parting-line output).
3. Generalize side-core/lifter generation (`backend/geometry/side_core.py`,
   Bosch criterion #5) beyond its current first-increment scope: grouped/
   multi-feature side cores, and lifter-vs-slide-vs-collapsible-core
   mechanism classification (both explicitly deferred — see
   `docs/ARCHITECTURE_ROADMAP.md` Stage 4 §4.3/§4.6).
4. Add a streaming `/agent/chat` endpoint (the agent layer's `/agent/analyze`
   single-shot sweep is implemented; conversational follow-up is not) and
   live-verify the Anthropic/OpenAI/Grok adapters once an API key is
   available for one of them.
5. PDF DFM report export (`backend/report/`) is implemented and verified —
   remaining polish is optional (e.g. embedding the refined parting-curve
   image directly rather than text/table only), not a functional gap.
