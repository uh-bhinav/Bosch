---
name: pipeline-data-flow
description: Traces how data flows through the DfM pipeline — which fields are set by which module, which results feed into which downstream module. Use when adding a new module, tracing a bug, or understanding cross-module dependencies.
---

# Pipeline Data Flow

## Module Chain

```
step_loader.load_step(filepath) → PartGeometry
    │
    ├── draft_analyzer.analyze_draft(part, direction) → DraftAnalysisResult
    │       Sets: face.draft_angle_deg, face.draft_classification
    │
    ├── undercut_detector.detect_undercuts(part, direction) → UndercutDetectionResult
    │       Sets: face.is_undercut, face.undercut_depth_mm, face.undercut_type
    │       Returns: features[], boolean regions, interference volume
    │
    ├── direction_optimizer.optimize_mold_direction(part) → DirectionOptimizationResult
    │       Internally calls: analyze_draft(mutate=False) + detect_undercuts(mutate=False) per candidate
    │       Final best direction: analyze_draft(mutate=True) + detect_undercuts(mutate=True)
    │       Sets: part.optimal_pull_direction, part.direction_score, part.inaccessible_face_ids
    │       Returns: initial_draft, optimal_draft, initial_undercuts, optimal_undercuts, candidates[]
    │
    ├── parting_line.detect_parting_line_candidates(part, direction) → PartingLineResult
    │       Uses: part.edges, part.faces (normals), part.face_adjacency
    │       Returns: edge candidates, components, selected component, wire points, refined points
    │
    └── core_cavity.classify_core_cavity(part, direction) → CoreCavityResult
            Sets: face.cavity_or_core ("cavity"/"core"/"parting")
            Returns: cavity_face_ids, core_face_ids, parting_face_ids
```

## FaceData Fields Set by Each Module

| Field | Set by | When |
|---|---|---|
| `face_id`, `occ_face`, `surface_type`, `normal`, `centroid`, `area` | step_loader | Always |
| `u_range`, `v_range`, `is_reversed`, `normal_valid` | step_loader | Always |
| `draft_angle_deg` | draft_analyzer | mutate=True only |
| `draft_classification` | draft_analyzer | mutate=True only |
| `is_undercut` | undercut_detector | mutate=True only |
| `undercut_depth_mm` | undercut_detector | mutate=True only |
| `undercut_type` | undercut_detector | mutate=True only |
| `cavity_or_core` | core_cavity | mutate=True only |

## PartGeometry Fields Set by Each Module

| Field | Set by |
|---|---|
| `shape`, `faces`, `edges`, `vertices`, `bounding_box` | step_loader |
| `face_adjacency`, `face_to_edges`, `edge_to_faces` | step_loader |
| `cadquery_shape` | step_loader (optional, may be None) |
| `optimal_pull_direction` | direction_optimizer |
| `direction_score` | direction_optimizer |
| `inaccessible_face_ids` | direction_optimizer |

## Result Dataclass Hierarchy

```
DraftAnalysisResult
├── pull_direction, analysis_pass
├── good/marginal/bad_face_ids
├── area statistics
├── severity
├── face_results: dict[face_id → {angle, classification, mold_side}]
└── suggestions: list[DraftSuggestion]

UndercutDetectionResult
├── pull_direction
├── undercut/parting/accessible_face_ids
├── features: list[UndercutFeature]
│   ├── face_ids, severity, type, depth, release_direction
│   ├── action_recommendation, action_confidence
│   └── boolean_region: BooleanRegionGeometry
├── boolean_refined, boolean_checked_face_ids
└── interference_volume_mm3

DirectionOptimizationResult
├── best_direction, best_label, best_score
├── initial_draft, initial_undercuts
├── optimal_draft, optimal_undercuts
├── candidates: list[DirectionCandidateResult]
└── boolean pruning/caching stats

PartingLineResult
├── pull_direction
├── edge_candidates: list[PartingLineEdgeCandidate]
├── components: list[PartingLineComponent]
├── selected_component_id
├── selected_wire_points (raw), refined_display_points (smoothed)
├── readiness, quality, undercut_conflict
└── diagnostics

CoreCavityResult
├── pull_direction
├── cavity/core/parting_face_ids
├── area statistics
└── threshold_used
```

## API Endpoint → Module Mapping

| Endpoint | Calls |
|---|---|
| `/summary` | `load_step` |
| `/draft` | `load_step` → `analyze_draft` |
| `/undercuts` | `load_step` → `detect_undercuts` |
| `/direction` | `load_step` → `optimize_mold_direction` (calls draft + undercuts internally) |
| `/parting-line` | `load_step` → `optimize_mold_direction` → `detect_parting_line_candidates` |
| `/core-cavity` | `load_step` → `optimize_mold_direction` → `classify_core_cavity` |
| `/display-mesh` | `load_step` → `build_display_mesh` |
| `/boolean-regions` | `load_step` → `detect_undercuts(boolean_refine=True)` → `build_shape_display_mesh` per region |
