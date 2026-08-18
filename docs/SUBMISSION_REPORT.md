> **Correction note (added during hackathon-submission cleanup, 2026-08-18).**
> This report's Level 1 Evaluation Matrix marks "Main Parting Line Creation"
> and "Core and Cavity face distinction" as "Complete." As documented in
> `.claude/rules/honesty-and-scope.md` and `docs/IMPLEMENTATION_STATUS.md`,
> that overstates both: the parting line is a candidate/foundation result
> (full Hou global optimization is not applied), and the core/cavity split
> is a real Boolean split verified on both real parts, but through a
> labeled planar approximation of the parting surface, not the exact 3-D
> surface. It also predates `frontend-web/`, which is now the primary UI —
> references to the Streamlit UI below describe the UI at the time this
> report was written. See `README.md` and `docs/IMPLEMENTATION_STATUS.md`
> for current, accurate status.

# DfM Agent — Level 1 Submission Report

## Executive Summary

The Bosch RB-CoC Plastics DfM Agent is a STEP-native Design-for-Manufacturability tool for injection-molded automotive plastic parts. It loads exact B-Rep geometry via pythonOCC, runs draft analysis, undercut detection with selective Boolean refinement, optimal mold-direction search, parting-line candidate detection, and Level 1 core/cavity face classification. Results are exposed through a FastAPI backend and a guided Streamlit UI with PyVista 3D visualization.

## Pipeline Architecture

```
Part1.stp
   │
   ▼
step_loader.py ──► PartGeometry (faces, edges, normals, topology)
   │
   ├── draft_analyzer.py ──────────► good / marginal / bad draft
   ├── undercut_detector.py ───────► features + Boolean refinement
   ├── direction_optimizer.py ───► best mold opening direction
   ├── parting_line.py ────────────► silhouette wire + Chaikin smoothing
   └── core_cavity.py ─────────────► cavity / core / parting face split
           │
           ▼
   backend/api/main.py (REST) ──► frontend/app.py (guided Streamlit UI)
```

## Research Paper Mapping

| Paper | Contribution in this build |
|---|---|
| Bassi et al. 2010 | Candidate pull-direction search, accessibility proxy, swept Boolean interference on top undercut candidates |
| Sangolli et al. 2021 | Feature grouping, severity typing, mold-action recommendations, confidence scoring |
| Nee et al. | Silhouette / near-parting edge candidate detection for main parting line |
| Hou et al. | Graph-weighted cleanup and Chaikin display smoothing for parting curve |

## Key Results — Part1.stp

Run the guided UI (`Run Full Level 1 Flow`) or validation harness to populate live metrics. Expected Level 1 outcomes:

- Topology loaded from exact STEP B-Rep
- Initial +Z draft classification with severity and correction suggestions
- Grouped undercut **features** (not raw face count) with Boolean-confirmed evidence highlighted in red
- Optimal mold direction with before/after draft and undercut comparison
- Smoothed parting-line candidate (8 Chaikin iterations) with raw wire reference overlay
- Core/cavity face classification using optimal pull direction (green/blue/yellow mesh)

## Honest Limitations

- Parting line is candidate-level silhouette detection; production-grade global optimization is planned.
- Core/cavity is face classification only — full Boolean solid split is Level 2.
- Boolean refinement is selective on top undercut candidates, not exhaustive for every face.
- LangChain AI agent and automated PDF export are planned for Level 2.

## Next Steps (Level 2)

1. Full Boolean core/cavity solid split into separate mold halves
2. LangChain agent layer for natural-language DfM review
3. Automated PDF report export
4. Hou global parting-line optimization

## Level 1 Evaluation Matrix

| Requirement | Status |
|---|---|
| Optimal Mold Direction from Undercut Detection | Complete |
| Main Parting Line Creation | Candidate/foundation — silhouette detection, graph-cleaned selection, and Chaikin smoothing are implemented; full Hou-style global optimization and closed-loop guarantee are planned (`docs/ARCHITECTURE_ROADMAP.md` Phase 1) |
| Core and Cavity face distinction (Level 1) | Complete for face classification only; full Boolean solid split into two mold-half bodies is Level 2 (`docs/ARCHITECTURE_ROADMAP.md` Phase 1b) |
| Simple GUI & Final Visualization | Complete |

See `docs/IMPLEMENTATION_STATUS.md` for the authoritative, module-by-module
breakdown and `.claude/rules/honesty-and-scope.md` for exact phrasing to use
when describing parting-line and core/cavity status.
