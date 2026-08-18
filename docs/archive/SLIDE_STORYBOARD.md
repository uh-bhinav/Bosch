> **Archived.** Original team pitch-deck plan. Kept for reference; the
> README's "5-minute panel demo" section is the current judge-facing walk-
> through, not this deck.

# Slide Storyboard

This storyboard is a concise deck plan for the Bosch RB-CoC Plastics hackathon
presentation. It is designed for a 7-10 minute pitch plus live demo.

## Slide 1: Title

Title:

```text
STEP-Native DfM Agent for Injection-Molded Automotive Plastics
```

Subtitle:

```text
Exact B-Rep geometry engine + guided mold-engineer copilot UI
```

Visual:

- Screenshot of Streamlit app with Part1 loaded.

Speaker point:

- We are automating the first mold-design review loop: load STEP, inspect
  draft, identify undercuts, recommend pull direction.

## Slide 2: Problem

Message:

- Mold engineers spend hours checking draft, undercuts, and pull direction.
- Automotive plastic parts have complex ribs, bosses, pockets, and freeform
  surfaces.
- Mesh-only checks can lose B-Rep accuracy.

Visual:

- Simple workflow: CAD file -> manual DfM review -> redesign loop.

## Slide 3: Our Approach

Message:

- Use exact STEP B-Rep geometry for analysis.
- Use display mesh only for visualization.
- Add lightweight AI/copilot interaction around deterministic geometry outputs.

Visual:

```text
STEP B-Rep -> Geometry Engine -> FastAPI -> Streamlit Viewer
```

## Slide 4: Geometry Engine

Message:

- `step_loader.py`: exact topology, normals, surface types, adjacency.
- `draft_analyzer.py`: face-by-face draft classification.
- `undercut_detector.py`: undercut features with Boolean refinement.
- `direction_optimizer.py`: best mold-opening direction.

Visual:

- Module pipeline diagram.

## Slide 5: Research Mapping

Message:

- Bassi et al. 2010: candidate direction search and swept Boolean accessibility.
- Sangolli et al. 2021: feature-level undercut classification and metrics.
- Nee/Hou: started with candidate/projected-wire foundation, graph cleanup, and
  visible curve overlay; final optimization is next.

Important wording:

- "Partially implemented" for Bassi/Sangolli.
- "Started" for Nee/Hou; final optimized/visualized parting line remains
  planned.

## Slide 6: Live Demo

Message:

- Guided Level 1 flow:
  1. Load STEP.
  2. Draft.
  3. Undercuts.
  4. Direction.

Visual:

- Use the live Streamlit app.

Speaker point:

- The important proof is traceability: face-level analysis maps back to the
  exact highlighted geometry.

## Slide 7: Results On Part1

Fill after Docker run:

| Metric | Value |
|---|---:|
| Solids | |
| Faces | |
| Best direction | |
| Candidate directions tested | |
| Bad draft area before | |
| Bad draft area after | |
| Undercut features | |
| Boolean regions | |

Visual:

- Raw, draft, undercut, and direction screenshots.

## Slide 8: Engineering Quality

Message:

- Modular backend.
- Config-driven thresholds.
- Structured API errors.
- Graceful fallback when dependencies/Booleans fail.
- Validation and performance harnesses.
- Honest implementation-status documentation.

Visual:

- Small checklist or architecture block.

## Slide 9: Limitations And Next Steps

Message:

- Not yet implemented: final optimized parting line,
  core/cavity extraction, LangChain tools, PDF export.
- Next phase: Level 2
  core/cavity split.

Speaker point:

- We are deliberately building the system in stable layers instead of
  overclaiming a brittle one-shot implementation.

## Slide 10: Closing

Message:

- The current tool turns STEP-native DfM analysis into a guided, visual,
  repeatable workflow.
- It gives Bosch a maintainable foundation for Level 1 now and Level 2/3 later.

Visual:

- Final screenshot of the Direction tab with best direction and action
  rationale.
