# Level 1 Demo Script

This script is for the Bosch RB-CoC Plastics hackathon Level 1 demo. It is
written to match the current implementation honestly: STEP load, draft analysis,
undercut detection, Boolean region visualization where available, optimal mold
direction, and backend parting-line candidate/projected-wire/refinement
foundation. Do not claim the final optimized/visualized parting line,
core/cavity, LangChain, or PDF export as
complete until those modules are built.

## Demo Setup

Run from the repository root:

```bash
docker compose up
```

Open:

```text
http://localhost:8501
```

Optional validation commands before the demo:

```bash
python -m backend.validation.part_validation --direction --boolean-refine --json
python -m backend.validation.performance_profile --direction --boolean-refine --json
```

These JSON outputs now include parting-line readiness, quality, undercut
conflict, refinement status, and timing budget data.

Expected current input status:

- `Part1.stp`: present.
- `Part2.stp`: not present in this workspace yet.

## 5 Minute Demo Flow

### 1. Opening

Say:

> This is a STEP-native DfM Agent for injection-molded automotive plastic
> components. The important design choice is that the backend analyzes exact
> B-Rep geometry through pythonOCC, while the frontend only receives a
> display mesh with preserved face IDs.

Point to:

- `STEP file` selector.
- `AI Mold Engineer Journey`.
- The five guided steps: `Load STEP`, `Draft`, `Undercuts`, `Direction`,
  `Parting Line`.
- Failed steps appear with a red status chip and a diagnostics panel with the
  backend recovery hint.

### 2. Load STEP

Action:

- Select `Part1.stp`.
- Click `Run Next Step` or `Run Full Level 1 Flow`.
- If using step-by-step mode, stop after `Load STEP`.

Say:

> The loader extracts solids, faces, edges, vertices, bounding box, surface
> types, normals, areas, centroids, and adjacency from the native STEP B-Rep.
> The mesh shown here is only for visualization. Analysis still references the
> exact OCC faces.

Show:

- Raw tab.
- Topology counts.
- Neutral display mesh.

Evidence to capture:

- Screenshot of Raw tab.
- Topology counts from the Level 1 snapshot.

### 3. Draft Analysis

Action:

- Click `Run Next Step` if not using full flow.
- Open `Draft` tab.

Say:

> Draft analysis computes face-by-face draft relative to the selected pull
> direction. Green faces are good, yellow faces are marginal, and red faces
> are bad or near-zero draft. The result is stored separately from the later
> optimal-direction result, so the UI can show before and after behavior.

Show:

- Draft legend.
- Draft color overlay.
- Good/marginal/bad metrics.
- Suggestions.

Evidence to capture:

- Screenshot of Draft tab.
- Good/marginal/bad percentage values.

### 4. Undercut Detection

Action:

- Click `Run Next Step` if not using full flow.
- Open `Undercuts` tab.

Say:

> The undercut detector starts with a fast accessibility and draft prefilter,
> then uses swept-face Boolean refinement for selected suspect faces when the
> OCC runtime supports it. Confirmed undercut faces are grouped into features,
> with severity, depth estimate, type, local release direction, and recommended
> mold action.

Show:

- Red undercut faces.
- Blue parting/silhouette faces.
- Translucent Boolean volumes if available.
- Mold Action Rationale table.
- Confidence chips.

Evidence to capture:

- Screenshot of undercut face overlay.
- Screenshot of Boolean volumes if rendered.
- Feature count and action confidence rows.

### 5. Direction Optimization

Action:

- Click `Run Next Step` if not using full flow.
- Open `Direction` tab.

Say:

> The direction optimizer samples candidate mold-opening directions, scores
> them with draft and undercut metrics, prunes poor candidates, and applies
> Boolean refinement on promising candidates. The selected direction becomes
> the recommended Level 1 pull direction.

Show:

- Best direction label and vector.
- Initial bad vs optimal bad metric.
- Candidate table.
- Optimal undercut summary.

Evidence to capture:

- Screenshot of Direction tab.
- Candidate count.
- Best label/vector.
- Initial vs optimal bad area.

### 6. Close

Say:

> The current Level 1 build already demonstrates the critical backend
> discipline: exact STEP B-Rep analysis, deterministic geometry outputs,
> traceable face IDs, Boolean refinement where it matters, a guided UI, and the
> first Nee/Hou-style parting-line candidate/refinement layer with a visible
> curve overlay and validation readiness score. The next engineering phase is
> final parting-line polish, then Level 2 core/cavity extraction.

## Fallback Paths

If PyVista rendering fails:

- The app displays mesh counts and structured JSON fallback.
- Say: "The geometry analysis is still running; this is only a viewer runtime
  dependency issue."

If Boolean refinement fails on some faces:

- Show structured Boolean warnings/failure details.
- Say: "The detector keeps proxy evidence and reports Boolean failures
  explicitly instead of hiding them."

If Part2 is requested:

- Say: "Part2 is not present in this workspace yet. The validation harness
  reports it under `missing_expected_files` and will run the same pipeline
  automatically when the file is added."

## Claims To Avoid

Do not say:

- "The final parting line is implemented."
- "Core/cavity extraction is implemented."
- "The LangChain agent is implemented."
- "PDF report export is implemented."
- "This is a full Bassi Boolean decomposition for every face and every
  direction."
- "This is full Sangolli volumetric decomposition."

Say instead:

- "Parting-line candidate/projected-wire/refinement overlay exists; final
  optimized parting line and core/cavity are next modules."
- "The current Bassi adaptation uses candidate search plus selective swept
  Boolean refinement."
- "The current Sangolli adaptation performs feature-level grouping and typing
  on detected undercut regions, not full-part volumetric decomposition."
