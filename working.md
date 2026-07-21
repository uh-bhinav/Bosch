# Bosch DfM Agent — Complete Technical Guide

> **Purpose of this document:** Read this file top-to-bottom to understand what the Bosch RB-CoC Plastics Hackathon project does, how it is structured, what every important file and function does, and how to run and test each component.
>
> **Repo location:** `~/Desktop/bosch/Bosch` (the git repo lives inside the `Bosch` subfolder, not the parent `bosch` folder).
>
> **Remote:** `https://github.com/uh-bhinav/Bosch.git`

---

## Table of Contents

1. [What This Project Is](#1-what-this-project-is)
2. [Domain Concepts You Need First](#2-domain-concepts-you-need-first)
3. [High-Level Architecture](#3-high-level-architecture)
4. [Tech Stack](#4-tech-stack)
5. [Folder Structure — Every File Explained](#5-folder-structure--every-file-explained)
6. [The Core Data Model](#6-the-core-data-model)
7. [The Analysis Pipeline (Step by Step)](#7-the-analysis-pipeline-step-by-step)
8. [Backend Modules — Deep Dive](#8-backend-modules--deep-dive)
9. [REST API Reference](#9-rest-api-reference)
10. [Frontend (Streamlit UI)](#10-frontend-streamlit-ui)
11. [Configuration System](#11-configuration-system)
12. [Validation & Performance Harnesses](#12-validation--performance-harnesses)
13. [Testing Guide](#13-testing-guide)
14. [How to Run the Project](#14-how-to-run-the-project)
15. [What Is Implemented vs Planned](#15-what-is-implemented-vs-planned)
16. [Research Paper Mapping](#16-research-paper-mapping)
17. [Glossary](#17-glossary)

---

## 1. What This Project Is

**DfM Agent** = **Design for Manufacturability Agent** for **injection-molded automotive plastic parts**.

The project takes a real automotive CAD file in **STEP format** (`.stp` / `.step`) — a standard B-Rep (Boundary Representation) solid model — and automatically analyzes whether the part can be manufactured in an injection mold. It answers questions like:

- Can this part be pulled out of a mold in a given direction?
- Which faces have insufficient **draft angle** (taper)?
- Where are **undercuts** (features that block mold release)?
- What is the **best mold opening direction**?
- Where should the **parting line** (the seam where the two mold halves meet) go?

**Current maturity:** Level 1 geometry analysis is fully wired end-to-end (load → draft → undercuts → direction → parting line → 3D visualization). Level 2 (core/cavity split), AI agent orchestration, and PDF reports are planned but not yet implemented.

**Demo part:** `data/parts/Part1.stp` — an automotive plastic component used throughout tests and demos.

---

## 2. Domain Concepts You Need First

| Term | Meaning in this project |
|------|-------------------------|
| **STEP / STP** | CAD exchange format storing exact B-Rep geometry (faces, edges, solids), not meshes. |
| **B-Rep** | Boundary Representation — the mathematical surface/curve description of a solid. |
| **Pull direction** | The direction the mold opens (unit vector, usually +Z initially). |
| **Draft angle** | Angle between a face normal and the pull direction. Industry formula: `draft = asin(|n · d|)`. 0° = vertical wall (bad), 90° = horizontal (best). |
| **Undercut** | Geometry that blocks straight-line mold release along the pull direction. Requires side cores, lifters, or part redesign. |
| **Parting line** | The 3D curve where the two mold halves meet. Often lies on "silhouette" edges where adjacent face normals straddle the pull direction. |
| **Core / Cavity** | The two mold halves. Cavity = outer shell, Core = inner pins/features. Planned for Level 2. |
| **pythonOCC** | Python bindings to OpenCASCADE (OCC) — the CAD kernel that reads STEP and runs Boolean operations. |
| **Boolean operation** | 3D set operation (intersection/union/subtraction) used to verify if a face sweeps into the solid when pulled. |

---

## 3. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         USER / TESTER                                   │
│                    Browser at localhost:8501                            │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ HTTP (JSON)
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  FRONTEND — frontend/app.py (Streamlit + PyVista)                       │
│  • Guided 5-step workflow                                               │
│  • 3D mesh viewer with color overlays                                   │
│  • Calls backend API; does NOT run geometry itself                        │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ requests.get("http://backend:8000/...")
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  BACKEND — backend/api/main.py (FastAPI + uvicorn)                      │
│  • 8 REST endpoints                                                     │
│  • Loads STEP, runs geometry pipeline, returns JSON + mesh payloads     │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  GEOMETRY ENGINE — backend/geometry/ (modular monolith)                 │
│                                                                         │
│  step_loader → draft_analyzer → undercut_detector                       │
│              → direction_optimizer → parting_line                       │
│              → visualize_raw (mesh adapter for UI)                      │
│                                                                         │
│  Shared state: PartGeometry dataclass (flows through entire pipeline)   │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  CAD RUNTIME — pythonOCC (OpenCASCADE 7.7.2) + CadQuery                 │
│  • STEP parsing, face normals, Boolean sweeps, triangulation            │
└─────────────────────────────────────────────────────────────────────────┘

         data/parts/*.stp  ←── input files
         config.yaml       ←── all tunable thresholds
         reports/          ←── validation JSON, coverage HTML
```

**Key design decisions:**

1. **Frontend/backend split** — Frontend Docker image is lightweight (no OCC). All CAD work happens in the backend.
2. **B-Rep in, mesh out** — Algorithms use exact OCC geometry; only the visualization layer triangulates to triangles.
3. **Single pipeline object** — `PartGeometry` is progressively enriched by each module (draft fields, undercut flags, etc.).
4. **Dataclasses for geometry, Pydantic at API boundary** — OCC C-extension objects cannot be Pydantic-validated.
5. **No database** — File-based input, in-memory analysis, JSON API responses.

---

## 4. Tech Stack

### Core Languages & Runtimes

| Component | Technology | Version |
|-----------|-----------|---------|
| Language | Python | 3.11 (backend), 3.10-slim (frontend Docker) |
| CAD kernel | pythonocc-core (OpenCASCADE) | 7.7.2 — **conda only** |
| CAD wrapper | CadQuery | 2.4.0 |
| API server | FastAPI + uvicorn | 0.111.0 / 0.29.0 |
| UI | Streamlit | 1.33.0 |
| 3D rendering | VTK + PyVista + stpyvista | VTK 9.2.* |
| Charts | Plotly | 5.21.0 |
| Scientific | numpy, scipy | 1.26.4, 1.13.0 |
| Graph algorithms | networkx | 3.3 (parting-line path search) |
| Config | PyYAML | 6.0.1 |
| Testing | pytest, pytest-cov, pytest-asyncio | 8.2.0 / 5.0.0 / 0.23.6 |
| Containers | Docker Compose | 2 services |

### Planned but Not Yet Used in Code

These are listed in `requirements.txt` / `environment.yml` but have **zero Python imports** today:

- **LangChain + OpenAI** — planned AI agent orchestrator
- **ReportLab + Pillow** — planned PDF report generation

### Dependency Management

| File | Role |
|------|------|
| `environment.yml` | Primary conda environment (`dfm_agent`) with pythonOCC |
| `requirements.txt` | Pip-only deps; documents that OCC must come from conda |
| `Dockerfile.backend` | Multi-stage conda build with OCC |
| `Dockerfile.frontend` | Slim Python image with Streamlit/PyVista only |
| `docker-compose.yml` | Orchestrates both services with volume mounts |

---

## 5. Folder Structure — Every File Explained

```
Bosch/                                    # ← GIT REPO ROOT (work from here)
│
├── README.md                             # Project overview, quick start, architecture
├── Engine.md                             # Deep research notes on the 4 academic papers
├── understand.md                         # Hackathon problem statement / requirements notes
├── config.yaml                           # ALL runtime thresholds (draft, direction, parting line)
├── environment.yml                       # Conda environment definition
├── requirements.txt                      # Pip dependencies
├── docker-compose.yml                    # Starts backend:8000 + frontend:8501
├── Dockerfile.backend                    # Conda/pythonOCC backend container
├── Dockerfile.frontend                   # Lightweight Streamlit viewer container
│
├── backend/                              # All server-side logic
│   ├── config.py                         # Loads config.yaml into frozen dataclass Settings
│   │
│   ├── api/
│   │   └── main.py                       # FastAPI app — 8 REST endpoints, error handling, mesh payloads
│   │
│   ├── models/
│   │   └── geometry_models.py          # Foundation dataclasses: PartGeometry, FaceData, EdgeData, etc.
│   │
│   ├── geometry/                         # The geometry engine ("brain")
│   │   ├── step_loader.py                # Module 1: STEP file → PartGeometry
│   │   ├── draft_analyzer.py             # Module 2: Per-face draft angle analysis
│   │   ├── undercut_detector.py          # Module 3: Undercut detection + Boolean refinement
│   │   ├── direction_optimizer.py        # Module 4: Optimal mold opening direction search
│   │   ├── parting_line.py               # Module 5: Parting-line candidate detection + refinement
│   │   └── visualize_raw.py              # B-Rep → triangle mesh adapter for PyVista/Streamlit
│   │
│   └── validation/                       # Offline testing harnesses (not unit tests)
│       ├── __init__.py                   # Package marker
│       ├── part_validation.py            # CLI: smoke-test full pipeline on STEP files
│       └── performance_profile.py        # CLI: time each pipeline step vs budgets
│
├── frontend/
│   └── app.py                            # Streamlit UI (~3,400 lines) — guided workflow + 3D viewer
│
├── tests/                                # pytest test suite
│   ├── pytest.ini                        # Markers: unit, integration, slow; coverage config
│   ├── test_step_loader.py               # STEP loading, models, bounding box, config
│   ├── test_draft_analyzer.py            # Draft classification, formulas, suggestions
│   ├── test_direction_optimizer.py       # Candidate generation, Boolean pruning, caching
│   ├── test_undercut_detector.py         # Undercut detection, Boolean, feature typing, confidence
│   ├── test_parting_line.py              # Silhouette, wire ordering, conflict scoring, refinement
│   ├── test_visualize_raw.py             # Mesh payload JSON safety
│   ├── test_part_validation.py           # Validation harness logic
│   ├── test_performance_profile.py       # Performance budget status logic
│   ├── test_api_error_handling.py        # API error structure, path traversal, missing parts
│   └── test_api_boolean_regions.py       # Boolean region mesh payload JSON safety
│
├── scripts/
│   └── run_level1_docker_validation.sh   # Repeatable Docker validation (N runs → JSON reports)
│
├── data/
│   └── parts/
│       └── Part1.stp                     # Demo automotive STEP file (required for integration tests)
│
├── docs/                                 # Presentation / demo preparation materials
│   ├── README.md                         # Documentation index
│   ├── IMPLEMENTATION_STATUS.md          # ★ Truth source: what's implemented vs planned
│   ├── DEMO_SCRIPT.md                    # Live demo walkthrough script
│   ├── DFM_REPORT_OUTLINE.md             # Future PDF report structure
│   ├── SLIDE_STORYBOARD.md               # Presentation slides outline
│   └── EVIDENCE_CHECKLIST.md             # Screenshots/metrics checklist for submission
│
└── reports/                              # Generated output (not source code)
    └── level1_validation/                # JSON from validation/performance scripts
        ├── part_validation_run_*.json
        └── performance_profile_run_*.json
```

### Files That Are Planned But Do Not Exist Yet

| Planned path | Purpose |
|-------------|---------|
| `backend/geometry/core_cavity.py` | Level 2: split part into core and cavity mold halves |
| `backend/agent/dfm_agent.py` | LangChain orchestrator for natural-language DfM reports |
| `backend/agent/tools.py` | LangChain tool wrappers around geometry modules |

---

## 6. The Core Data Model

Everything flows through **`PartGeometry`** defined in `backend/models/geometry_models.py`. This file has **zero imports from the rest of the backend** — it is the foundation layer.

### Type Aliases

```python
Vec3 = tuple[float, float, float]   # (x, y, z) in millimeters
UVRange = tuple[float, float]        # parametric surface bounds
```

### Vector Helpers

| Function | Purpose |
|----------|---------|
| `dot3(a, b)` | 3D dot product |
| `normalize3(v)` | Unit vector; raises on zero vector |
| `cross3(a, b)` | 3D cross product |
| `mag3(v)` | Vector magnitude |

### `BoundingBox`

Axis-aligned bounding box of the part.

| Field/Property | Purpose |
|----------------|---------|
| `xmin, ymin, zmin, xmax, ymax, zmax` | AABB extents in mm |
| `.diagonal` | Space diagonal — used as sweep distance in Boolean checks |
| `.center` | Centroid of the box |
| `.dimensions` | (ΔX, ΔY, ΔZ) |
| `.to_dict()` | JSON-safe serialization |

### `VertexData`

A unique 3D point in the B-Rep topology (deduplicated by TShape hash).

| Field | Purpose |
|-------|---------|
| `vertex_id` | 0-based index |
| `occ_vertex` | Live OCC `TopoDS_Vertex` handle |
| `coordinates` | (x, y, z) in mm |

### `EdgeData`

A topological edge with geometry and adjacency.

| Field | Purpose |
|-------|---------|
| `edge_id` | 0-based index |
| `occ_edge` | Live OCC `TopoDS_Edge` handle |
| `edge_type` | "Line", "Circle", "BSpline", etc. |
| `length` | Arc length in mm |
| `adjacent_face_ids` | 1 = boundary, 2 = manifold interior, 3+ = non-manifold |
| `start_vertex`, `end_vertex` | Endpoint coordinates |
| `is_seam` | True for periodic surface seams (cylinders, spheres) |
| `convexity` | "convex" / "concave" / "tangent" — set by undercut_detector |
| `is_silhouette` | Set by parting_line when normals straddle pull direction |
| `is_parting_edge` | Set when edge is selected for the parting loop |

| Property | Purpose |
|----------|---------|
| `.is_boundary` | Only 1 adjacent face (outer rim) |
| `.is_manifold` | Exactly 2 adjacent faces |
| `.is_closed` | No distinct endpoints (full circles) |

### `FaceData`

All geometry for one B-Rep face. This is the most important per-element object.

**Set by `step_loader`:**
- `face_id`, `occ_face`, `surface_type`, `normal`, `centroid`, `area`
- `u_range`, `v_range`, `is_reversed`, `normal_valid`

**Set progressively by downstream modules:**
- `draft_angle_deg`, `draft_classification` — by `draft_analyzer`
- `is_undercut`, `undercut_depth_mm`, `undercut_type` — by `undercut_detector`
- `cavity_or_core` — planned by `core_cavity`

| Method | Purpose |
|--------|---------|
| `draft_angle_for_direction(pull_dir)` | `asin(|n · d|)` in degrees |
| `signed_dot(pull_dir)` | Signed `n · d` — positive = cavity-side, negative = core-side |
| `to_dict()` | JSON-safe (strips OCC handles) |

### `PartGeometry` — The Pipeline Hub

The single object that every module reads and enriches.

**Core fields (from step_loader):**
```
source_file, occ_shape, faces[], edges[], vertices[]
bounding_box, face_count, edge_count, vertex_count
face_adjacency, face_to_edges, edge_to_faces  ← topology graphs
load_time_s, warnings[], surface_type_counts, edge_type_counts
```

**Enriched by downstream modules:**
```
optimal_pull_direction, direction_score, inaccessible_face_ids
parting_edge_ids, parting_wire_points
```

**Key accessor methods:**

| Method | Purpose |
|--------|---------|
| `get_face(face_id)` | O(1) lookup with fallback scan |
| `get_adjacent_faces(face_id)` | Faces sharing an edge (Nee loop traversal) |
| `get_edge(edge_id)` | Edge lookup |
| `get_face_edges(face_id)` | All edges of a face |
| `get_boundary_edges()` | Rim edges (parting candidates) |
| `get_manifold_edges()` | Standard interior edges |
| `get_non_manifold_edges()` | CAD errors (3+ faces per edge) |
| `get_silhouette_edges()` | Edges flagged by parting_line |
| `adjacency_stats()` | Graph statistics for diagnostics |
| `summary()` | Human-readable console summary |
| `to_dict()` | JSON serialization with optional face/edge/vertex inclusion |

**Convenience properties:** `.valid_faces`, `.undercut_faces`, `.cavity_faces`, `.core_faces`

---

## 7. The Analysis Pipeline (Step by Step)

This is the exact order of operations when a user runs the full guided workflow:

```
Part1.stp
    │
    ▼
[1] step_loader.load_step()
    │  → PartGeometry with faces, edges, vertices, adjacency, bounding box
    │
    ▼
[2] draft_analyzer.analyze_draft()  [initial direction, usually +Z]
    │  → Per-face draft angles: good (green) / marginal (yellow) / bad (red)
    │
    ▼
[3] undercut_detector.detect_undercuts()
    │  → Proxy undercut faces (low draft) + optional Boolean refinement
    │  → Feature grouping, severity, mold action recommendations
    │
    ▼
[4] direction_optimizer.optimize_mold_direction()
    │  → Searches ~54 candidate directions on a sphere grid
    │  → Scores by draft quality + undercut count
    │  → Boolean-refines top candidates (Bassi 2010)
    │  → Returns best direction; re-runs draft + undercuts on winner
    │
    ▼
[5] parting_line.detect_parting_line_candidates()
    │  → Finds silhouette/near-parting edges (Nee 1998)
    │  → Orders into wire loops, scores undercut conflicts
    │  → Refines/smooths curve (Hou 2018 inspired)
    │
    ▼
[6] visualize_raw.build_display_mesh()  [at each step for UI]
    │  → Triangulates B-Rep → triangles with face_id mapping
    │
    ▼
    Streamlit 3D viewer with color overlays
```

**Planned future steps (not implemented):**
- `[7] core_cavity.py` — split into mold halves
- `[8] dfm_agent.py` — LLM generates natural-language report + PDF

---

## 8. Backend Modules — Deep Dive

### 8.1 `backend/geometry/step_loader.py` — Module 1: STEP Loading

**Purpose:** The **single entry point** for all geometry. Converts a `.stp` file into a `PartGeometry`.

**Main public functions:**

| Function | Purpose |
|----------|---------|
| `load_step(filepath)` | **Primary loader.** Raises on failure. Returns fully populated `PartGeometry`. |
| `load_step_with_fallback(filepath, strict=False)` | Same but returns `None` on failure (for batch/agent use). |

**Internal pipeline inside `load_step()`:**

1. `STEPControl_Reader().ReadFile()` — parse STEP via OCC
2. `_compute_bounding_box(shape)` — exact AABB
3. `_count_topology_raw(shape)` — count solids, shells, faces, edges, vertices
4. `_extract_all_faces(shape)` — per-face normals, surface types, areas, centroids
5. `_extract_edges_and_build_adjacency(shape, faces)` — edges + 3 adjacency maps
6. `_extract_vertices(shape)` — deduplicated vertex list
7. `_load_cadquery_part(path)` — optional CadQuery shape wrapper
8. Assemble and return `PartGeometry`

**Exceptions:**
- `STEPLoadError` — corrupt STEP, no solid, parse failure
- `FileNotFoundError` — file missing
- `ImportError` — pythonOCC not installed

**CLI usage:**
```bash
python -m backend.geometry.step_loader data/parts/Part1.stp --json
```

---

### 8.2 `backend/geometry/draft_analyzer.py` — Module 2: Draft Analysis

**Purpose:** Compute per-face draft angles relative to a pull direction and classify them.

**Draft formula (industry standard, SolidWorks-compatible):**
```
draft_angle = asin(|n · d|)
```
Where `n` = outward face normal, `d` = pull direction unit vector.

**Classification thresholds** (from `config.yaml`):
- `good` ≥ 1.5° (green)
- `marginal` ≥ 0.5° (yellow)
- `bad` < 0.5° (red)

**Main public functions:**

| Function | Purpose |
|----------|---------|
| `analyze_draft(part, pull_direction, ...)` | **Main entry.** Computes draft for all valid faces. `mutate=True` writes results onto `FaceData`. |
| `analyze_draft_default(part)` | Convenience: uses +Z direction. |
| `analyze_draft_optimal(part)` | Uses `part.optimal_pull_direction` if set. |
| `get_draft_color(face)` | RGB tuple for visualization. |
| `draft_colors_for_part(part)` | Color list for all faces. |

**Result object: `DraftAnalysisResult`**

Contains: `good_face_ids`, `marginal_face_ids`, `bad_face_ids`, area fractions, `severity`, `suggestions[]`, `face_results{}`, timing.

**Key internal functions:**

| Function | Purpose |
|----------|---------|
| `_classify_draft(angle, good_thresh, marginal_thresh)` | Maps angle → "good"/"marginal"/"bad" |
| `_mold_side(signed_dot)` | "cavity" / "core" / "parting" classification |
| `_assess_severity(bad_area_frac)` | Overall severity: "low" / "moderate" / "high" / "critical" |
| `_build_suggestions(part, pull_dir, ...)` | Actionable design suggestions for bad faces |

---

### 8.3 `backend/geometry/undercut_detector.py` — Module 3: Undercut Detection

**Purpose:** Find faces that block mold release and optionally confirm them with swept Boolean interference checks (Bassi/Sangolli inspired).

**Two-stage detection:**

1. **Fast proxy:** Faces with draft angle below marginal threshold (0.5°) are flagged as likely undercuts.
2. **Boolean refinement (optional):** Sweeps candidate faces along their access direction and checks for non-zero intersection volume with the solid.

**Main public function:**

| Function | Purpose |
|----------|---------|
| `detect_undercuts(part, pull_direction, mutate=True, boolean_refine=True, ...)` | **Main entry.** Returns `UndercutDetectionResult`. |

**Key result classes:**

| Class | Purpose |
|-------|---------|
| `UndercutFeature` | Grouped undercut region with face IDs, severity, depth, release direction, mold action |
| `UndercutDetectionResult` | Full result: face lists, features, Boolean metrics, reliability summary |
| `BooleanInterferenceMetrics` | Per-face Boolean sweep results (volume, depth, shape analysis) |
| `BooleanReliabilitySummary` | How trustworthy the Boolean results are |
| `MoldActionRecommendation` | Suggested action: "redesign", "side_core", "lifter", "review", etc. |

**Key internal functions:**

| Function | Purpose |
|----------|---------|
| `_boolean_refine_undercuts(...)` | Runs swept-face Boolean checks on ranked candidates |
| `_swept_face_interference_volume(...)` | Core OCC Boolean sweep for one face |
| `_group_undercut_faces_with_boolean_proximity(...)` | Groups nearby undercut faces into features |
| `_recommend_mold_action(...)` | Rule-based mold action recommendation |
| `_score_action_confidence(...)` | Confidence score with explanation breakdown |
| `_classify_undercut_type(...)` | "internal" / "external" / "interacting" classification |
| `_rank_boolean_candidate_faces(...)` | Prioritizes which faces get expensive Boolean checks |

---

### 8.4 `backend/geometry/direction_optimizer.py` — Module 4: Direction Search

**Purpose:** Find the best mold opening direction by searching candidate directions and scoring them (Bassi 2010 inspired).

**Algorithm:**

1. Compute initial direction draft + undercuts (for before/after comparison).
2. `generate_candidate_directions()` — sample ~54 directions on a sphere grid (15° steps) plus principal axes.
3. For each candidate: fast draft analysis + proxy undercut detection (no Boolean).
4. `_score_candidate()` — lower score = better (weighted bad area + undercut area + Boolean interference).
5. `_select_boolean_refinement_candidates()` — smart pruning: only run expensive Boolean on top ~5 promising candidates.
6. Re-score survivors with Boolean-refined undercuts.
7. Pick best direction; re-run draft + undercuts with `mutate=True` on the winner.
8. Store `part.optimal_pull_direction` and `part.direction_score`.

**Main public functions:**

| Function | Purpose |
|----------|---------|
| `optimize_mold_direction(part, ...)` | **Main entry.** Returns `DirectionOptimizationResult`. |
| `generate_candidate_directions(angular_step_deg, max_candidates)` | Sphere grid + axis directions. |

**Result: `DirectionOptimizationResult`**

Contains: `best_direction`, `best_score`, `initial_draft`, `initial_undercuts`, `optimal_draft`, `optimal_undercuts`, `candidates[]`, Boolean pruning summary, cache stats, timing.

**Performance optimizations:**

| Mechanism | Purpose |
|-----------|---------|
| `_cached_detect_boolean_undercuts()` | Per-direction result cache |
| `_select_boolean_refinement_candidates()` | Prefilter: skip Boolean on clearly bad directions |
| `BooleanVolumeCache` | Reuse Boolean volumes across directions |

---

### 8.5 `backend/geometry/parting_line.py` — Module 5: Parting Line

**Purpose:** Detect where the mold should split — the parting line curve (Nee 1998 + Hou 2018 inspired).

**Algorithm:**

1. `_classify_edge()` — for each edge, check if adjacent face normals straddle the pull direction (silhouette) or are near-vertical (near-parting).
2. `_candidate_components()` — group connected candidate edges into components.
3. `_build_ordered_wire()` — order edges into a traversable wire (open chain or closed loop).
4. `_select_projected_wire()` — pick best component using projection metrics (area, perimeter, closure).
5. `_wire_undercut_conflict()` — penalize wires that pass through undercut features.
6. `_refine_selected_wire()` — Hou-inspired graph cleanup + Chaikin smoothing for display.
7. `_parting_line_diagnostic_gate()` — readiness assessment for downstream core/cavity.

**Main public function:**

| Function | Purpose |
|----------|---------|
| `detect_parting_line_candidates(part, pull_direction, undercut_context, refine=True, ...)` | **Main entry.** Returns `PartingLineResult`. |

**Key result classes:**

| Class | Purpose |
|-------|---------|
| `PartingLineResult` | Selected edges, wire points, refinement, diagnostics, readiness |
| `PartingLineRefinement` | Smoothed display curve with quality metrics |
| `PartingLineDiagnosticGate` | ready/review/weak/failed status with blockers |
| `PartingLineUndercutConflict` | Conflict score with undercut features |

---

### 8.6 `backend/geometry/visualize_raw.py` — Mesh Adapter

**Purpose:** Convert exact OCC B-Rep shapes into triangle meshes for the UI, while preserving `face_id` per triangle.

**Why this exists:** All analysis uses exact B-Rep. Only visualization needs triangles. This module is the boundary.

**Main public functions:**

| Function | Purpose |
|----------|---------|
| `build_display_mesh(part, linear_deflection=0.5)` | Triangulate a `PartGeometry` |
| `build_shape_display_mesh(shape, linear_deflection=0.5)` | Triangulate any OCC shape (Boolean regions) |
| `build_raw_mesh(part, ...)` | Lower-level mesh builder |
| `to_pyvista(mesh)` | Convert `RawMeshData` → PyVista mesh object |

**Result: `RawMeshData`**

Contains: `points[]`, `triangles[]`, `face_ids[]` (one per triangle), counts.
Method: `.to_payload(include_geometry=True)` → JSON-safe dict for API.

---

### 8.7 `backend/config.py` — Settings Loader

**Purpose:** Load `config.yaml` into immutable frozen dataclasses.

**Settings hierarchy:**

```
Settings
├── dfm: DFMSettings
│   ├── draft: DraftSettings          (good_threshold_deg, marginal_threshold_deg)
│   ├── direction_search: DirectionSearchSettings  (angular_step, Boolean params, prefilter)
│   ├── parting_line: PartingLineSettings  (tolerances, smoothing, colors)
│   └── core_cavity: CoreCavitySettings    (planned viz colors)
└── agent: AgentSettings              (model, temperature — planned)
```

| Function | Purpose |
|----------|---------|
| `load_settings(config_path=None)` | Load YAML with precedence: arg → `DFM_CONFIG` env → repo `config.yaml` → defaults |
| `settings` | Module-level singleton used everywhere |

---

### 8.8 `backend/api/main.py` — FastAPI REST Layer

**Purpose:** HTTP facade over the geometry engine. Serializes results + mesh payloads for the frontend.

**Error model:** All errors return structured JSON:
```json
{
  "status": "error",
  "error": {
    "code": "step_load_failed",
    "message": "...",
    "operation": "draft analysis",
    "recovery_hint": "Check that the STEP file is valid...",
    "details": {}
  }
}
```

**Error codes:** `invalid_filename`, `part_not_found`, `cad_runtime_missing`, `step_load_failed`, `invalid_input`, `analysis_failed`

**Key helper functions:**

| Function | Purpose |
|----------|---------|
| `_part_path_or_raise(filename, operation)` | Validates filename, blocks path traversal (`../` attacks) |
| `_undercut_mesh_visual_payload(result, mesh)` | Feature-aware undercut coloring (confirmed vs proxy) |
| `_boolean_region_mesh_payloads(features, mesh_deflection)` | Converts Boolean interference shapes to renderable meshes |
| `_parting_line_paths_payload(parting_line)` | Raw + refined parting curve paths for overlay |

---

## 9. REST API Reference

**Base URL:** `http://localhost:8000`
**Interactive docs:** `http://localhost:8000/docs` (Swagger UI)

| Method | Endpoint | Purpose | Key Query Parameters |
|--------|----------|---------|---------------------|
| GET | `/` | Health message | — |
| GET | `/health` | Service health + parts dir status | — |
| GET | `/parts` | List `.stp`/`.step` files in `data/parts/` | — |
| GET | `/parts/{filename}/summary` | Load STEP + geometry summary | `include_faces`, `include_mesh`, `mesh_deflection` |
| GET | `/parts/{filename}/draft` | Draft analysis | `dx`, `dy`, `dz`, `include_mesh` |
| GET | `/parts/{filename}/undercuts` | Undercut detection | `boolean_refine`, `include_boolean_regions`, `max_boolean_faces` |
| GET | `/parts/{filename}/direction` | Optimal mold direction | `angular_step_deg`, `max_candidates`, `include_all_candidates` |
| GET | `/parts/{filename}/parting-line` | Parting-line candidate | `use_optimal_direction`, `refine`, `smoothing_iterations` |

**Example calls:**

```bash
# List available parts
curl http://localhost:8000/parts

# Load and summarize
curl "http://localhost:8000/parts/Part1.stp/summary?include_mesh=true"

# Draft analysis along +Z
curl "http://localhost:8000/parts/Part1.stp/draft?dx=0&dy=0&dz=1&include_mesh=true"

# Undercuts with Boolean regions
curl "http://localhost:8000/parts/Part1.stp/undercuts?include_boolean_regions=true"

# Best mold direction
curl "http://localhost:8000/parts/Part1.stp/direction?include_mesh=true"

# Parting line (uses optimal direction by default)
curl "http://localhost:8000/parts/Part1.stp/parting-line?include_mesh=true"
```

**Response structure pattern:**

Every analysis endpoint returns:
```json
{
  "part": { /* PartGeometry.to_dict() */ },
  "<analysis_type>": { /* module result.to_dict() */ },
  "display_mesh": { /* triangle mesh with per-triangle colors */ }
}
```

---

## 10. Frontend (Streamlit UI)

**File:** `frontend/app.py` (~3,400 lines)
**URL:** `http://localhost:8501`
**Backend connection:** `DFM_BACKEND_URL` env var (default: `http://localhost:8000`, Docker: `http://backend:8000`)

### Guided Workflow (5 Steps)

The UI runs a fixed sequence defined by:

```python
STEP_ORDER = ("Load STEP", "Draft", "Undercuts", "Direction", "Parting Line")
```

| Step | API Call | What the User Sees |
|------|----------|-------------------|
| 1. Load STEP | `GET /parts/{file}/summary?include_mesh=true` | Raw 3D mesh of the part |
| 2. Draft | `GET /parts/{file}/draft?include_mesh=true` | Green/yellow/red draft color overlay |
| 3. Undercuts | `GET /parts/{file}/undercuts?include_boolean_regions=true` | Red/orange undercut faces + Boolean volumes |
| 4. Direction | `GET /parts/{file}/direction?include_mesh=true` | Optimal direction + before/after comparison |
| 5. Parting Line | `GET /parts/{file}/parting-line?include_mesh=true` | Blue refined parting curve overlay |

### Key Frontend Functions

| Function | Purpose |
|----------|---------|
| `_backend_get(endpoint, params)` | HTTP client wrapper with error parsing |
| `_fetch_summary/draft/undercuts/direction/parting_line()` | Step-specific API callers |
| `_show_mesh(mesh_payload, overlays)` | PyVista/stpyvista 3D viewer with color overlays |
| `_run_named_step(step_name)` | Execute one pipeline step |
| `_run_step_sequence(step_names)` | Execute multiple steps in order |
| `_render_journey_status()` | Progress indicator for the 5-step workflow |
| `_render_level1_snapshot()` | Summary dashboard of all results |
| `_render_before_after_story()` | Before/after direction optimization comparison |
| `_render_boolean_refinement_visibility()` | Boolean reliability and failure diagnostics |
| `_render_major_undercut_callout()` | Highlights critical undercut features |

### Session State Keys

The UI stores results in Streamlit `session_state`:

| Key | Content |
|-----|---------|
| `summary_result` | STEP load response |
| `draft_result` | Draft analysis response |
| `undercut_result` | Undercut detection response |
| `direction_result` | Direction optimization response |
| `parting_line_result` | Parting line response |
| `analysis_step_failures` | Per-step error details |
| `analysis_step_runs` | Per-step timing and status |

### UI Architecture Note

The frontend is a **thin HTTP client**. It does NOT import pythonOCC or run any geometry. The frontend Docker image only has Streamlit + PyVista + requests. All CAD computation happens in the backend container.

---

## 11. Configuration System

**File:** `config.yaml` (repo root)
**Loader:** `backend/config.py`
**Override:** Set `DFM_CONFIG=/path/to/config.yaml` environment variable

### Draft Settings

```yaml
dfm:
  draft:
    good_threshold_deg: 1.5      # Green: draft ≥ this
    marginal_threshold_deg: 0.5  # Yellow: draft ≥ this (below good)
                                 # Red: draft < marginal
```

### Direction Search Settings

```yaml
  direction_search:
    angular_step_deg: 15.0           # Sphere grid resolution (finer = slower)
    max_candidates: 54               # Max directions to evaluate
    boolean_refine_top_candidates: 5 # How many get expensive Boolean checks
    boolean_refine_max_faces: 80     # Max faces per Boolean sweep
    boolean_interference_weight: 4000.0  # Score penalty for Boolean volume
    # ... many more Boolean tolerance/offset/retry parameters
```

### Parting Line Settings

```yaml
  parting_line:
    dot_tolerance: 0.01              # Silhouette detection threshold
    boundary_dot_tolerance: 0.15     # Boundary edge retention threshold
    smoothing_iterations: 6          # Chaikin smoothing passes
    refined_curve_color: [0.0, 0.72, 1.0]  # Blue
    raw_curve_color: [1.0, 0.72, 0.0]      # Orange
```

### Agent Settings (Planned)

```yaml
agent:
  model: "gpt-4o-mini"
  temperature: 0.1
```

### Environment Variables

| Variable | Used By | Default | Purpose |
|----------|---------|---------|---------|
| `DFM_CONFIG` | `backend/config.py` | `./config.yaml` | Config file path |
| `DFM_BACKEND_URL` | `frontend/app.py` | `http://localhost:8000` | Backend API URL |
| `OPENAI_API_KEY` | docker-compose | (empty) | Planned LLM agent |
| `GROK_API_KEY` | docker-compose | (empty) | Planned alternate LLM |
| `PYVISTA_OFF_SCREEN` | Docker frontend | `true` | Headless 3D rendering |
| `LOG_LEVEL` | docker-compose | `INFO` | Logging verbosity |
| `DFM_DOCKER_SERVICE` | validation script | `backend` | Docker service name override |

---

## 12. Validation & Performance Harnesses

These are **CLI tools** (not pytest tests) for generating evidence that the pipeline works on real STEP files.

### `backend/validation/part_validation.py`

**Purpose:** Smoke-test the full pipeline on available STEP files.

```bash
# Basic validation
python -m backend.validation.part_validation --json

# Full Level 1 with direction search and Boolean
python -m backend.validation.part_validation --direction --boolean-refine --json

# Skip parting line
python -m backend.validation.part_validation --no-parting-line --json
```

**Key functions:**

| Function | Purpose |
|----------|---------|
| `discover_step_files(parts_dir)` | Find `.stp`/`.step` files |
| `validate_part(path, ...)` | Run full pipeline, return `PartValidationResult` |
| `validate_available_parts(...)` | Validate all discovered files |

**Checks performed:** topology validity, draft results, undercut counts, direction optimization, parting-line readiness gate.

### `backend/validation/performance_profile.py`

**Purpose:** Time each pipeline step and compare against budgets.

```bash
python -m backend.validation.performance_profile --direction --boolean-refine --json

# Custom budget
python -m backend.validation.performance_profile --budget direction=120 --fail-on-warning
```

**Default time budgets (seconds):**

| Step | Budget |
|------|--------|
| STEP load | 30s |
| Display mesh | 20s |
| Draft analysis | 10s |
| Undercut detection | 60s |
| Direction search | 180s |
| Parting line | 45s |

**Key functions:**

| Function | Purpose |
|----------|---------|
| `profile_part(path, ...)` | Time each step, return `PartPerformanceProfile` |
| `profile_available_parts(...)` | Profile all discovered files |

### `scripts/run_level1_docker_validation.sh`

Repeatable Docker validation runner:

```bash
bash scripts/run_level1_docker_validation.sh 3   # 3 runs
```

Writes JSON to `reports/level1_validation/part_validation_run_*.json` and `performance_profile_run_*.json`.

---

## 13. Testing Guide

### Test Framework

- **Runner:** pytest
- **Config:** `tests/pytest.ini`
- **Coverage:** `--cov=backend` → HTML report at `reports/coverage_html/`

### Test Markers

| Marker | Meaning | Requirements |
|--------|---------|-------------|
| `@pytest.mark.unit` | Fast, no OCC, no files | Always runnable |
| `@pytest.mark.integration` | Needs `Part1.stp` + pythonOCC | Conda/Docker environment |
| `@pytest.mark.slow` | Long-running (Boolean ops) | Patience |

### Test Files and What They Cover

| Test File | What It Tests | Approx. Tests |
|-----------|--------------|---------------|
| `test_step_loader.py` | BoundingBox, FaceData, vector math, load errors, integration load | ~15 |
| `test_draft_analyzer.py` | Classification, formulas, suggestions, mutate behavior | ~20 |
| `test_direction_optimizer.py` | Candidate generation, scoring, Boolean pruning, caching | ~25 |
| `test_undercut_detector.py` | Proxy detection, Boolean refinement, feature grouping, confidence, mold actions | ~50+ |
| `test_parting_line.py` | Silhouette detection, wire ordering, projection, conflict scoring, refinement | ~30+ |
| `test_visualize_raw.py` | Mesh payload structure, JSON safety | ~4 |
| `test_part_validation.py` | Validation harness metrics and logic | ~8 |
| `test_performance_profile.py` | Budget status, warnings, overrides | ~6 |
| `test_api_error_handling.py` | API error codes, path traversal, missing files | ~10 |
| `test_api_boolean_regions.py` | Boolean region mesh JSON safety | ~5 |

### How to Run Tests

```bash
# All tests (needs conda env with OCC for integration tests)
cd ~/Desktop/bosch/Bosch
conda activate dfm_agent
pytest tests/ -v

# Unit tests only (no OCC needed)
pytest tests/ -v -m unit

# Integration tests only
pytest tests/ -v -m integration

# With coverage report
pytest tests/ -v --cov=backend --cov-report=html

# Single file
pytest tests/test_draft_analyzer.py -v

# Single test
pytest tests/test_step_loader.py::TestBoundingBox::test_diagonal -v
```

### What to Test as a New Tester

**Recommended testing order:**

1. **Environment check:**
   ```bash
   python -c "from OCC.Core.STEPControl import STEPControl_Reader; print('OCC OK')"
   ```

2. **Unit tests (fast, no CAD):**
   ```bash
   pytest tests/ -m unit -v
   ```

3. **STEP loader integration:**
   ```bash
   python -m backend.geometry.step_loader data/parts/Part1.stp --json
   pytest tests/test_step_loader.py -v -m integration
   ```

4. **Full pipeline validation:**
   ```bash
   python -m backend.validation.part_validation --direction --boolean-refine --json
   ```

5. **Performance profiling:**
   ```bash
   python -m backend.validation.performance_profile --direction --boolean-refine --json
   ```

6. **API tests:**
   ```bash
   # Start backend first
   uvicorn backend.api.main:app --port 8000 &
   pytest tests/test_api_error_handling.py tests/test_api_boolean_regions.py -v
   ```

7. **UI smoke test:**
   ```bash
   docker compose up
   # Open http://localhost:8501, select Part1.stp, click "Run Full Journey"
   ```

8. **Docker validation evidence:**
   ```bash
   bash scripts/run_level1_docker_validation.sh 3
   # Check reports/level1_validation/*.json
   ```

---

## 14. How to Run the Project

### Option A: Docker (Recommended)

```bash
cd ~/Desktop/bosch/Bosch

# Ensure demo part exists
ls data/parts/Part1.stp

# Start both services
docker compose up

# Open in browser:
#   UI:  http://localhost:8501
#   API: http://localhost:8000/docs
```

### Option B: Local Development (Conda)

```bash
cd ~/Desktop/bosch/Bosch

# Create environment (first time only)
conda env create -f environment.yml
conda activate dfm_agent

# Verify OCC
python -c "from OCC.Core.STEPControl import STEPControl_Reader; print('OCC OK')"

# Terminal 1: Backend
uvicorn backend.api.main:app --reload --port 8000

# Terminal 2: Frontend
streamlit run frontend/app.py
```

### Option C: CLI-Only (No UI)

```bash
conda activate dfm_agent

# Load STEP
python -m backend.geometry.step_loader data/parts/Part1.stp --json

# Validate pipeline
python -m backend.validation.part_validation --direction --boolean-refine --json

# Profile performance
python -m backend.validation.performance_profile --direction --boolean-refine --json
```

---

## 15. What Is Implemented vs Planned

| Capability | Status | Module |
|-----------|--------|--------|
| STEP B-Rep loading + topology | ✅ Implemented | `step_loader.py` |
| Face normals, areas, adjacency | ✅ Implemented | `step_loader.py` |
| Display mesh with face_id mapping | ✅ Implemented | `visualize_raw.py` |
| Draft angle analysis | ✅ Implemented | `draft_analyzer.py` |
| Undercut proxy detection | ✅ Implemented | `undercut_detector.py` |
| Swept Boolean undercut refinement | ✅ Implemented (selective) | `undercut_detector.py` |
| Undercut feature grouping + mold actions | ✅ Implemented | `undercut_detector.py` |
| Optimal mold direction search | ✅ Implemented | `direction_optimizer.py` |
| Parting-line candidate detection | ✅ Foundation | `parting_line.py` |
| Parting-line refinement + smoothing | ✅ Foundation | `parting_line.py` |
| Streamlit 3D UI with guided workflow | ✅ Implemented | `frontend/app.py` |
| FastAPI REST API | ✅ Implemented | `backend/api/main.py` |
| Validation + performance harnesses | ✅ Implemented | `backend/validation/` |
| pytest test suite | ✅ Implemented | `tests/` |
| Core/cavity extraction | ❌ Not implemented | planned `core_cavity.py` |
| LangChain AI agent | ❌ Not implemented | planned `dfm_agent.py` |
| PDF report export | ❌ Not implemented | planned (ReportLab) |
| Full Hou global graph optimization | ❌ Partial | `parting_line.py` has foundation |

**Truth source:** Always check `docs/IMPLEMENTATION_STATUS.md` for the latest capability matrix.

---

## 16. Research Paper Mapping

The geometry algorithms are inspired by four academic papers. The project implements partial versions with honest limitations documented.

| Paper | Year | What It Contributes | Implementation Status |
|-------|------|--------------------|-----------------------|
| **Bassi et al.** — Undercut-Free Parting Direction Determination | 2010 | Candidate direction search + swept Boolean accessibility | Partial: prefilter + selective Boolean on top candidates |
| **Sangolli et al.** — Algorithms for sorting and recognizing undercut features | 2021 | Feature grouping, typing, release direction, mold actions | Partial: Boolean-confirmed feature objects, no full volumetric decomposition |
| **Nee et al.** — Automatic Determination of 3-D Parting Lines | 1998 | Silhouette edge detection, wire ordering, loop selection | Started: adjacent-normal silhouette + projection-aware selection |
| **Hou et al.** — Hybrid approach for automatic parting curve generation | 2018 | Graph-weighted path optimization, curve smoothing | Started: bounded weighted path search + Chaikin smoothing; full global optimization planned |

See `Engine.md` for deep algorithm notes and `docs/IMPLEMENTATION_STATUS.md` for fidelity details.

---

## 17. Glossary

| Term | Definition |
|------|-----------|
| **AABB** | Axis-Aligned Bounding Box |
| **B-Rep** | Boundary Representation — exact CAD geometry |
| **Bassi algorithm** | Swept Boolean accessibility check for mold direction |
| **Boolean sweep** | Moving a face along pull direction and checking solid intersection |
| **CadQuery** | Python CAD scripting library wrapping OCC |
| **Chaikin smoothing** | Subdivision curve smoothing algorithm |
| **DfM** | Design for Manufacturability |
| **Draft** | Taper angle of a face relative to mold pull direction |
| **Face_id** | 0-based index mapping B-Rep faces → mesh triangles |
| **Level 1** | Current build: geometry analysis without core/cavity split |
| **Level 2** | Planned: core/cavity extraction |
| **Manifold edge** | Edge shared by exactly 2 faces (normal case) |
| **OCC / OpenCASCADE** | Open-source CAD kernel (C++), wrapped by pythonOCC |
| **PartGeometry** | Central pipeline data object |
| **Proxy undercut** | Fast heuristic undercut flag (low draft), before Boolean confirmation |
| **Pull direction** | Unit vector along which the mold opens |
| **Silhouette edge** | Edge where adjacent face normals straddle the pull direction |
| **STEP** | Standard for the Exchange of Product model data (.stp/.step files) |
| **Streamlit** | Python web framework for data apps |
| **TShape hash** | OCC internal topology hash for deduplication |
| **Undercut** | Geometry blocking straight mold release |

---

## Quick Reference Card

```
REPO:        ~/Desktop/bosch/Bosch
REMOTE:      https://github.com/uh-bhinav/Bosch.git
UI:          http://localhost:8501
API:         http://localhost:8000/docs
DEMO PART:   data/parts/Part1.stp
CONFIG:      config.yaml
TRUTH DOC:   docs/IMPLEMENTATION_STATUS.md

START:       docker compose up
TEST:        pytest tests/ -v
VALIDATE:    python -m backend.validation.part_validation --direction --boolean-refine --json
PROFILE:     python -m backend.validation.performance_profile --direction --boolean-refine --json
EVIDENCE:    bash scripts/run_level1_docker_validation.sh 3

PIPELINE:    step_loader → draft_analyzer → undercut_detector
             → direction_optimizer → parting_line → visualize_raw → Streamlit
```

---

*This document was generated from a full codebase audit. For the latest implementation status, always cross-check with `docs/IMPLEMENTATION_STATUS.md`.*
