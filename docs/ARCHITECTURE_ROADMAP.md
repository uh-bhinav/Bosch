# DfM Agent — Architecture Roadmap & Master Specification

> **Status**: Specification. Nothing in this document is implemented yet unless
> explicitly marked "Implemented today".
> **Created**: 2026-07-26
> **Authority**: This document describes *planned* work. For what the code does
> *today*, `docs/IMPLEMENTATION_STATUS.md` and the source remain authoritative.
> Where this document and `IMPLEMENTATION_STATUS.md` disagree about current
> state, `IMPLEMENTATION_STATUS.md` wins.

---

## 0. Execution Order and Rationale

Four phases, strictly ordered. Each phase's output is the next phase's input.

| Phase | Scope | Why it comes here |
|---|---|---|
| **1** | Geometry engine hardening | Everything downstream consumes geometry results. A frontend rewrite over an unfinished engine means rewriting the frontend twice. |
| **2** | Frontend migration to React + Vite + Three.js | Needs stable result schemas from Phase 1 to design against. Also unblocks visual verification of Phase 1 output. |
| **3** | End-to-end real-world testing | Needs both a correct engine and a UI that can render its output for visual confirmation. |
| **4** | AI agent orchestration | Wraps a *verified* engine. Wrapping an unverified one produces confident natural-language descriptions of wrong geometry — the worst possible failure mode for a DfM tool. |

**The Phase 4 placement is deliberate.** An LLM narrating incorrect undercut
counts is more dangerous than no LLM at all, because it launders a geometry bug
into an authoritative-sounding engineering recommendation.

---

## 0.1 Blocking Findings (address before Phase 3, ideally before Phase 1)

These were found while surveying the repo for this roadmap. They are not
speculative.

### F1 — `Part1.stp` and `Part3.stp` are the same file (BLOCKER for Phase 3)

```
MD5 (data/parts/Part1.stp)  = a373ffdf57ebb1036ec43b9e77025afa   863881 bytes
MD5 (data/parts/Part3.stp)  = a373ffdf57ebb1036ec43b9e77025afa   863881 bytes
MD5 (data/parts/rename.stp) = d0c89a7c67d40f3a0e18962d75947a2f   522419 bytes
```

Both `Part1.stp` and `Part3.stp` carry the internal STEP header
`FILE_NAME('Part3.stp', '2026-07-23T09:15:51+05:30', ...)`.
`rename.stp` carries `FILE_NAME('Element_Packaging_Cap.stp', '2026-05-25T10:33:37+05:30', ...)`
and is 522 KB — which matches the size `STATUS.md` records for `Part1.stp`
("✅ Present (522 KB)").

**Conclusion**: the original Part1 was overwritten by a copy of Part3 and
survives as `rename.stp`. Any Phase 3 claim of "validated on two parts" is
currently false — it is one part tested twice.

**Action**: confirm with the team which file is the real Level 1 input, restore
it to `Part1.stp`, and re-run the validation harness. Per CLAUDE.md invariant #2
(`data/parts/` is read-only), this restoration is a deliberate, human-approved
exception — do not let an automated step do it.

### F2 — `core_cavity.py` reads a config key that does not exist

`backend/geometry/core_cavity.py:14` documents:

> The threshold value is taken from config.yaml: `dfm.parting_line.silhouette_dot_tolerance`
> or defaults to 0.05

`config.yaml` has no `silhouette_dot_tolerance` key under `dfm.parting_line`,
and `classify_core_cavity()` takes `threshold: float = 0.05` as a hardcoded
Python default. The API layer passes its own hardcoded `Query(default=0.05)`.

This violates CLAUDE.md invariant #4 ("All config thresholds live in
`config.yaml`. No hardcoded magic numbers in algorithm code"). Fixed as part of
Milestone 1.5.

### F3 — `.claude/rules/api-layer.md` lists two endpoints that do not exist

The rule file documents `/parts/{filename}/display-mesh` and
`/parts/{filename}/boolean-regions` as endpoints. Neither exists in
`backend/api/main.py`; both are query-parameter flags on other endpoints
(`include_mesh`, `include_boolean_regions`). Correct the rule file so it stops
misdirecting future work.

### F4 — `networkx==3.3` is a declared dependency with zero imports

`requirements.txt:44` pins it with the comment "Graph algorithms for Hou 2018
parting line". No file imports it. The current graph work in `parting_line.py`
is a hand-rolled bounded DFS (`_trace_best_weighted_path`, edge limit 22, state
limit 75,000) with a greedy fallback. Milestone 1.1 makes the dependency real.

---

# PHASE 1 — Geometry Engine Fixes & Innovations

## 1a. Parting Line: Guaranteed Closed Loop + Parting Surface

### Implemented today

`backend/geometry/parting_line.py` (2,869 lines) does:

- Nee-style adjacent-normal silhouette classification (`_classify_edge`)
- Connected-component grouping over candidate edges (`_candidate_components`)
- Deterministic wire ordering for simple chains and loops (`_build_ordered_wire`)
- Projection-aware component selection (`_select_projected_wire`)
- Undercut-conflict scoring (`_wire_undercut_conflict`)
- Bounded-DFS best-path extraction with greedy fallback (`_trace_best_weighted_path`)
- Chaikin display smoothing (`_chaikin_smooth`)
- Readiness scoring and a diagnostic gate

### The gap

Three specific things are missing:

1. **No closure guarantee.** `_points_are_closed()` *reports* whether the result
   happens to close; nothing *makes* it close. An open chain is a valid output
   of the current pipeline.
2. **No bridging across disconnected components.** `_select_projected_wire`
   picks the single best component and discards the rest. If the true silhouette
   is split into three arcs by a rib or a boss, two arcs are thrown away.
3. **No parting surface.** The output is a polyline for display. A mold needs a
   sheet.

### Proposed algorithm

**Step 1 — Build a real graph (networkx).**

Replace the ad-hoc `point_to_edges` dict in `_trace_best_weighted_path` with an
explicit `networkx.Graph`:

- **Nodes**: quantized vertex keys from `_point_key(point, point_tolerance)` —
  the existing quantization is already correct, reuse it.
- **Edges**: one per candidate edge, carrying
  `weight = f(candidate.score, kind_bonus, undercut_conflict_penalty, length)`.
  The existing `edge_weight()` closure already computes this — lift it out.

**Step 2 — Bridge disconnected components through real B-Rep geometry.**

This is the key innovation and the reason `EdgeData.is_boundary` matters.

When the candidate graph has *k* > 1 components, do **not** synthesize straight
line segments between them — that produces a curve that does not lie on the
part, and a parting surface built from it will not seal.

Instead, build a **secondary graph over all part edges** (not just candidates)
and route between components along real edges:

```
G_all      = Graph over every EdgeData in part.edges
G_cand     = subgraph induced by candidate edges
components = connected_components(G_cand)

for each pair of components (Ci, Cj):
    bridge = nx.shortest_path(
        G_all,
        source=nearest_endpoint(Ci),
        target=nearest_endpoint(Cj),
        weight=bridge_cost,          # penalizes non-candidate edges heavily
    )
```

`bridge_cost` should be:

- `1.0 × length` for a candidate edge (free to reuse)
- `bridge_penalty_factor × length` for a non-candidate manifold edge
- `boundary_bridge_factor × length` for a boundary edge
  (`EdgeData.is_boundary` — an open rim is often exactly where the parting line
  *should* run on an open shell, so this should be *cheaper* than an interior
  detour, not more expensive)
- `+inf` for edges that overlap a major undercut feature
  (reuse `_edge_undercut_conflict_penalty`)

**Step 3 — Force a closed loop.**

Contract each component to a supernode, build the component-level complete graph
weighted by the bridge costs from Step 2, and find a minimum-weight Hamiltonian
cycle over the components. For the component counts seen on real parts (*k*
typically < 8) exact DP (Held–Karp, O(2ᵏ·k²)) is affordable; fall back to a
nearest-neighbour + 2-opt heuristic above a configured `k`.

Expand the cycle back into the full edge path. The result is closed by
construction.

**Step 4 — Validate and gate.**

Reuse `_closure_error_mm`. If closure error exceeds
`parting_line.max_closure_error_mm`, mark the result `readiness: "review"` and
**do not** proceed to surface generation. This preserves the existing honest
diagnostic-gate behaviour rather than silently emitting a bad sheet.

**Step 5 — Parting surface.**

Two strategies, tried in order:

| Strategy | When | OCC API |
|---|---|---|
| **Planar extrusion** | Loop flatness is high — max deviation from the PCA best-fit plane < `parting_surface.planar_tolerance_mm` | PCA over loop points → best-fit plane → `BRepBuilderAPI_MakeFace` on the plane trimmed by the wire, then `BRepPrimAPI_MakePrism` outward past the bbox |
| **N-sided patch** | Non-planar loop | `BRepFill_Filling` — add the wire's edges as boundary constraints, `Build()`, `Face()` |

Planar is tried first because it is dramatically more robust, and because a
planar parting line is what a mold engineer *wants* whenever the geometry
permits it. `BRepFill_Filling` is the fallback, not the default.

The surface must extend beyond the part bounding box (factor
`parting_surface.extension_factor`, default 1.5 × bbox diagonal) so the
subsequent Boolean split in §1b cleanly separates the mold blank.

**New config keys** (`config.yaml` → `dfm.parting_line` and a new
`dfm.parting_surface`):

```yaml
dfm:
  parting_line:
    bridge_penalty_factor: 4.0
    boundary_bridge_factor: 0.6
    max_closure_error_mm: 0.05
    max_components_exact_cycle: 8
  parting_surface:
    planar_tolerance_mm: 0.25
    extension_factor: 1.5
    filling_max_degree: 3
    filling_tolerance_mm: 0.01
```

### Honest labelling after this milestone

This becomes a **closed-loop parting line with a generated parting surface**.
It is still not a full Hou global multi-criteria optimization — the cost
function is length + candidate score + undercut conflict, without the curvature
and cosmetic-region terms Hou describes. Say "graph-optimized closed parting
loop", not "full Hou implementation".

---

## 1b. Core/Cavity: Real 3D Solid Split

### Implemented today

`backend/geometry/core_cavity.py` is **139 lines** and does exactly one thing:
per-face classification by `sign(n · d)` into `cavity` / `core` / `parting`,
with area totals and a `mutate` flag writing `FaceData.cavity_or_core`.

There is no solid, no Boolean, and no export. The module docstring says so
plainly, and that honesty should be preserved until this milestone lands.

### Proposed algorithm

```
1. blank      = BRepPrimAPI_MakeBox(...)         # oversized mold blank
2. mold_body  = BRepAlgoAPI_Cut(blank, part)     # blank minus part = tooling
3. sheet      = parting surface from §1a
4. halves     = BRepAlgoAPI_Splitter(mold_body, sheet)
5. classify each resulting solid as cavity or core by
   sign(dot(center_of_mass(solid) - parting_centroid, pull_direction))
6. export     = STEPControl_Writer, one Transfer() per solid
```

**Step-by-step detail:**

**1. Mold blank.** `BRepPrimAPI_MakeBox` sized to
`part.bounding_box` inflated by `core_cavity.blank_margin_factor` (default 0.25
of the bbox diagonal) on every side. Must fully contain both the part and the
extended parting sheet.

**2. Tooling volume.** `BRepAlgoAPI_Cut(blank, part.occ_shape)`. Set
`SetFuzzyValue()` using the same tolerance ladder `undercut_detector.py` already
uses (`boolean_fuzzy_factor`, `boolean_max_fuzzy_value_mm`) — that ladder exists
because OCC Booleans are brittle on real STEP, and the same brittleness applies
here.

**3–4. Split.** Prefer `BRepAlgoAPI_Splitter` (BOPAlgo splitter) with
`mold_body` as the argument and `sheet` as the tool. If `Splitter` is
unavailable in the pinned pythonOCC 7.7.2 build, fall back to two
`BRepAlgoAPI_Cut` operations against a solid half-space built by extruding the
sheet in each direction.

**5. Side assignment.** For each solid in the split result, compute
`GProp_GProps` center of mass, then assign by the sign of its projection onto
the pull direction relative to the parting-surface centroid. This is more robust
than face-normal voting because it works on the *solid*, which is what actually
has to come apart.

**6. Export.** `STEPControl_Writer`:

```python
writer = STEPControl_Writer()
writer.Transfer(cavity_solid, STEPControl_AsIs)
writer.Transfer(core_solid,   STEPControl_AsIs)
status = writer.Write(str(output_path))
```

Write to `reports/` or a new `output/` directory — **never** to `data/parts/`
(CLAUDE.md invariant #2).

### Failure handling

Every step must degrade gracefully, matching the existing engine's philosophy:

| Failure | Behaviour |
|---|---|
| Parting surface unavailable (gate blocked in §1a) | Return face classification only, `solid_split_status: "blocked_by_parting_line"` |
| `BRepAlgoAPI_Cut` fails | Retry with the fuzzy ladder; on exhaustion return classification only with structured failure detail |
| Split yields ≠ 2 solids | Report actual count, do not guess; likely means the sheet did not fully cut the blank |
| Export fails | Return in-memory result, report write failure separately |

**New config keys:**

```yaml
dfm:
  core_cavity:
    threshold: 0.05                    # fixes finding F2 — currently hardcoded
    blank_margin_factor: 0.25
    solid_split_enabled: true
    export_dir: "output/mold_halves"
    split_fuzzy_factor: 0.1
```

### New API surface

```
GET  /parts/{filename}/core-cavity?solid_split=true
POST /parts/{filename}/export/mold-halves   → writes STEP, returns paths
```

---

## 1c. Undercut Engine: Edge Convexity + Extremal Vertex Depth

### Implemented today

`EdgeData.convexity` exists as a field (`geometry_models.py:236`) documented as
`"convex" | "concave" | "tangent" | None`, and is **always `None`** — nothing
populates it. `step_loader.py:64` notes it is "set later by undercut_detector",
which never happens.

Undercut detection currently uses `signed_dot(pull_direction)` on the
**centroid normal** of each face, plus swept-Boolean refinement on selected
candidates.

### The false-positive problem

A single centroid normal is a poor descriptor of a curved face. On a cylindrical
boss aligned with the pull direction, the centroid normal is radial —
perpendicular to the pull — so `signed_dot ≈ 0` and it lands in the "parting"
bucket. On a *partially* swept cylindrical face, the centroid normal can point
away from the pull direction and register as a negative-draft undercut even
though every point on that face is fully accessible.

Edge convexity resolves this because it is a *local, differential* property that
distinguishes an outside corner (material falls away — accessible) from an
inside corner (material closes in — a real pocket).

### Convexity computation

For each manifold edge (`EdgeData.is_manifold`, exactly 2 adjacent faces):

```
1. Sample a point P at the edge's mid-parameter via BRepAdaptor_Curve.
   Get the curve tangent T at P.
2. For each adjacent face fi:
     project P into fi's UV space (ShapeAnalysis_Surface or
     GeomAPI_ProjectPointOnSurf)
     evaluate the outward normal ni at that UV using GeomLProp_SLProps,
     orientation-corrected exactly as step_loader already does
3. cross = n1 × n2
   sign  = dot(cross, T)
4. |sign| < convexity_tangent_tolerance  → "tangent"
   sign > 0                              → "convex"
   sign < 0                              → "concave"
```

All required OCC classes (`BRepAdaptor_Curve`, `BRepAdaptor_Surface`,
`GeomLProp_SLProps`) are **already imported** in `step_loader.py:80,109` under
the existing guarded-import pattern — no new dependency, and the
orientation-correction logic to reuse is already proven there.

**Where to compute it**: in `step_loader.py`, during edge extraction. It is a
pure topological property independent of pull direction, so computing it once at
load time and caching it on `EdgeData` is strictly better than recomputing per
direction. This also makes it available to the parting line module for free.

### Using convexity to suppress false positives

Add a gate in `undercut_detector.detect_undercuts()`:

> A face whose negative draft comes only from centroid-normal evaluation, and
> **all** of whose bounding edges are convex or tangent, is downgraded from
> `undercut` to `review` and is **not** submitted for expensive Boolean
> refinement.

A genuine pocket always has at least one concave bounding edge. This directly
cuts the Boolean workload — which is the dominant cost in the `/direction`
endpoint's 30–60 s runtime.

### Extremal vertex projection for exact depth

Currently `_estimate_boolean_depth` measures the projection span of the Boolean
intersection shape's **bounding box corners** (`_shape_bbox_points`) or its
vertices. Bounding-box span over-reports depth on any feature that is not
axis-aligned with the release vector.

Replace with exact extremal vertex projection along the release vector:

```
1. Collect every TopoDS_VERTEX of the undercut feature's faces
   (TopExp_Explorer over each face, deduplicated by the existing
   HashCode approach — see decisions.md, hash-based deduplication)
2. r = feature.release_direction  (already computed today)
3. proj_i = dot(vertex_i, r)
4. depth  = max(proj_i) - reference
```

The `reference` should be the projection of the **parting plane**, not
`min(proj_i)`. Undercut depth in mold terms is "how far the side action must
travel to clear the feature", which is measured from where the mold opens — not
from the feature's own far edge. Using `min(proj_i)` measures the feature's own
extent, which is a different (and smaller) number.

Keep the current bbox-span value as a fallback when the parting plane is
unavailable, and report which method produced the number — the existing
`depth_method` field on `BooleanInterferenceMetrics` already carries exactly
this, so extend its vocabulary rather than adding a new field.

**New config keys:**

```yaml
dfm:
  undercut:
    convexity_tangent_tolerance: 0.01
    convexity_suppression_enabled: true
    depth_reference: "parting_plane"    # | "feature_extent" | "bbox_span"
```

---

## 1d. Direction Optimizer: Flash Risk + Coarse-to-Fine Search

### Implemented today

`generate_candidate_directions()` emits 6 principal axes then a uniform
spherical grid at `angular_step_deg` (15°), capped at `max_candidates` (54).
`_score_candidate()` is a weighted sum of undercut area %, bad draft %, marginal
draft %, Boolean interference volume fraction, count fractions, and a small
non-principal-axis penalty.

`_select_boolean_refinement_candidates()` then applies a well-developed
multi-guard prefilter before spending Booleans.

### Gap 1 — No flash risk term

Flash is molten plastic escaping at the parting line. Its dominant geometric
cause is a face lying nearly *parallel* to the pull direction near the
silhouette: the two mold halves meet at a shallow angle there, clamping force is
poorly transmitted, and the shut-off is unreliable.

The current scoring function has no term for this. A direction that produces
zero undercuts but drags the parting line across a long shallow shut-off will
score perfectly and be wrong.

**Proposed term:**

```
flash_risk_faces = { f : |n_f · d| < sin(flash_angle_threshold_deg) }
flash_area_frac  = Σ area(f) for f in flash_risk_faces / total_area
```

with default `flash_angle_threshold_deg: 5.0` (giving |n·d| < 0.0872).

Weight it as a **secondary** term — flash risk is a manufacturability nuisance,
undercuts are a tooling-cost catastrophe:

```python
+ flash_risk_weight * flash_area_frac      # default flash_risk_weight = 200.0
```

For scale: undercut area carries weight 1500, bad draft 1000, marginal draft
100. 200 places flash risk between bad and marginal draft — meaningful, never
dominant.

**Refinement — only thin-walled faces matter.** A thick structural rib at a
shallow angle is not a flash risk; a thin wall is. Approximate wall thinness
with the face's own extent: gate the term on
`area(f) < flash_thin_area_factor × bbox_diagonal²`. This is an approximation,
not a wall-thickness measurement — label it as such in any report. True wall
thickness needs ray casting or medial-axis analysis, which is out of scope here.

### Gap 2 — Coarse grid misses the true optimum

A 15° global grid cannot resolve an optimum that sits 3° off a sampled
direction. Real parts are frequently drafted at 1–3° from an axis, so the best
direction is routinely *just* off-grid.

**Proposed two-stage search:**

```
STAGE 1 (coarse — existing):
    54 candidates at 15°, prefilter scoring, smart Boolean gate
    → rank, take top-K (fine_search_top_k, default 3)

STAGE 2 (fine — new):
    for each of the top-K coarse winners d_i:
        generate a local cone of candidates around d_i:
            half-angle    = fine_search_cone_half_angle_deg  (default 15°)
            angular step  = fine_angular_step_deg            (default 5°)
        score with mutate=False prefilter only
    merge, re-rank, Boolean-refine the overall best

FINAL:
    exactly one direction gets mutate=True
```

**Critical constraint (CLAUDE.md, the `mutate` flag contract):** every candidate
in both stages must be scored with `mutate=False`. Only the single final winner
is re-run with `mutate=True`. The fine stage multiplies the number of scored
candidates by roughly 3 × 20 = 60, so a `mutate=True` leak here would corrupt
the display overlay far more visibly than it does today. The existing
`analyze_initial_draft_no_mutation` / `_apply_undercut_result_to_part`
separation is the pattern to follow.

**Cost control**: Stage 2 uses the *prefilter only* — no Booleans. Boolean
refinement still runs only on the final merged shortlist, governed by the
existing `_select_boolean_refinement_candidates` guards. Added cost is therefore
~60 cheap normal-based scoring passes, not 60 Boolean passes.

**New config keys:**

```yaml
dfm:
  direction_search:
    flash_risk_weight: 200.0
    flash_angle_threshold_deg: 5.0
    flash_thin_area_factor: 0.02
    fine_search_enabled: true
    fine_search_top_k: 3
    fine_angular_step_deg: 5.0
    fine_search_cone_half_angle_deg: 15.0
    fine_search_max_candidates: 60
```

---

## 1e. Draft Analysis: Surface-Type Conditional Thresholds

### Implemented today

Two global thresholds from `config.yaml`:

```yaml
draft:
  good_threshold_deg: 1.5
  marginal_threshold_deg: 0.5
```

`_classify_draft(angle, good_thresh, marginal_thresh)` applies them uniformly to
every face.

### The gap

Required draft is not a constant. Industry practice (and `understand.md` §4,
"industry minimum ~0.5–2°; textured parts need more"):

| Surface condition | Typical minimum draft |
|---|---|
| Smooth / polished, shallow | 0.5° |
| Standard smooth | 1.5° |
| Light texture (MT-11010) | 3.0° |
| Heavy texture (MT-11030) | 5.0°+ |
| Deep ribs (depth > 3× width) | 2.0°+ |

A single 1.5° threshold either over-flags smooth cosmetic faces or, worse,
green-lights a textured face at 1.6° that will scuff badly on ejection.

### Honest problem statement

**STEP AP203/AP214 does not carry texture information.** There is no field to
read. Any claim that the tool "detects textured surfaces" would be false.

Three tractable inputs instead:

**1. Explicit per-face override (primary, honest).** Accept an optional
`face_conditions: dict[int, str]` parameter on `analyze_draft()`, mapping
`face_id` → a named condition from the config table. The frontend supplies this
from user selection ("mark these faces as textured"). This is exactly how
SolidWorks and Moldflow handle it — the engineer tells the tool.

**2. Surface-type defaults (secondary, heuristic).** A config table keyed on
`FaceData.surface_type`, which the loader already populates:

```yaml
draft:
  good_threshold_deg: 1.5           # default, unchanged
  marginal_threshold_deg: 0.5
  conditions:
    smooth:        { good: 1.5, marginal: 0.5 }
    light_texture: { good: 3.0, marginal: 2.0 }
    heavy_texture: { good: 5.0, marginal: 3.5 }
    deep_rib:      { good: 2.0, marginal: 1.0 }
  surface_type_defaults:
    Plane:        smooth
    Cylinder:     smooth
    Cone:         smooth
    "BSpline/NURBS": smooth        # NOT auto-textured — see note
```

**Note on NURBS**: it is tempting to map freeform NURBS → textured, since
cosmetic A-surfaces are usually NURBS. Do not. Plenty of structural NURBS faces
are not textured, and silently demanding 3° on them produces a flood of false
"bad draft" flags that destroys user trust in the whole report. Default
everything to `smooth` and require explicit opt-in.

**3. Deep-rib geometric detection (tertiary, genuinely derivable).** Rib depth
vs. width *is* computable from B-Rep: a face whose bounding box has one
dimension > `deep_rib_ratio` × another, and whose adjacent faces form a narrow
channel, is a deep rib. This one can be automatic because it rests on geometry,
not on surface finish.

### Resolution order

```
per-face explicit override
  → geometric deep-rib detection
    → surface_type default
      → global default
```

Every `DraftSuggestion` must report **which rule fired and why** — extend the
existing suggestion structure with `threshold_source` and `condition_applied`.
An engineer who sees "3.0° required" needs to know whether that came from their
own texture marking or from a heuristic they can override.

---

# PHASE 2 — Frontend Migration: Streamlit → React + Vite + Three.js

## 2.1 Why migrate

`frontend/app.py` is 3,966 lines in a single module. The performance problem is
structural, not tunable:

1. **Every interaction is a full server round-trip.** Streamlit re-executes the
   entire script on any widget change.
2. **Every analysis endpoint re-sends the whole mesh.** `/draft`, `/undercuts`,
   `/direction`, `/parting-line`, and `/core-cavity` each return
   `display_mesh.points` and `display_mesh.faces` in full. Switching from the
   draft overlay to the undercut overlay re-downloads identical geometry.
3. **Rendering is server-side.** PyVista/VTK rasterizes on the backend under
   `xvfb-run`; the client receives an image. There is no client-side camera, so
   every rotation is a network round-trip.
4. **The backend re-parses the STEP file on every request** (`load_step(path)`
   at the top of every handler). This is the documented stateless design
   (`decisions.md`, 2026-07-26), and it is why `/direction` takes 30–60 s.

Points 2–4 compound: rotating the model can trigger a full STEP re-parse.

## 2.2 Target architecture

```
                     ┌──────────────────────────────────────┐
                     │  React + Vite + react-three-fiber    │
                     │                                      │
   ┌─────────────┐   │  ┌────────────────────────────────┐  │
   │  /geometry  │──►│  │ BufferGeometry (fetched ONCE)  │  │
   │   /mesh     │   │  │  position  Float32Array        │  │
   └─────────────┘   │  │  index     Uint32Array         │  │
                     │  │  faceId    Uint16Array  ◄──────┼──┼── the key attribute
   ┌─────────────┐   │  └────────────────────────────────┘  │
   │ /analysis/  │──►│  ┌────────────────────────────────┐  │
   │   draft     │   │  │ overlay LUT: faceId → RGB      │  │
   │   undercuts │   │  │ swapped client-side, no refetch│  │
   │   direction │   │  └────────────────────────────────┘  │
   │   parting   │   │                                      │
   │   core-cav  │   │  60 fps orbit / pan / zoom locally   │
   └─────────────┘   └──────────────────────────────────────┘
```

### The central design decision: separate geometry from analysis

**Mesh is fetched once. Analysis endpoints return only per-face result arrays.**

This single change eliminates the dominant payload cost. `RawMeshData` already
carries `face_ids: list[int]` — one source `face_id` per display triangle
(`visualize_raw.py:62`). That mapping is exactly what makes client-side overlay
switching possible, and it already exists.

New endpoint shapes:

```
GET /parts/{f}/geometry/mesh          → positions, indices, faceId attribute,
                                         bbox, faceCount   (fetch once, cache)

GET /parts/{f}/analysis/draft         → { faceResults: {faceId: {angle, class}},
                                          summary: {...} }        NO MESH
GET /parts/{f}/analysis/undercuts     → { faceResults, features, summary }
GET /parts/{f}/analysis/direction     → { best, candidates, faceResults }
GET /parts/{f}/analysis/parting-line  → { rawPoints, refinedPoints, readiness }
GET /parts/{f}/analysis/core-cavity   → { faceResults, areas }
GET /parts/{f}/geometry/undercut-volumes → separate translucent meshes
```

The existing endpoints stay, deprecated, until the Streamlit app is retired —
this is a strangler-fig migration, not a big-bang cutover.

### Transport format

**Recommendation: JSON envelope + base64 typed arrays. Not glTF.**

glTF is the wrong fit here despite being the obvious choice. The reason is
`faceId`: glTF has no native concept of "source B-Rep face index per triangle",
so it would have to ride as a custom `_FACEID` attribute or a `KHR_*` extension,
and every consumer would need custom code to read it anyway. At that point glTF
buys packaging overhead without buying interoperability.

```json
{
  "format": "dfm-mesh-v1",
  "pointCount": 48213,
  "triangleCount": 91044,
  "positions": "<base64 Float32Array, 3 per vertex>",
  "indices":   "<base64 Uint32Array,  3 per triangle>",
  "faceIds":   "<base64 Uint32Array,  1 per triangle>",
  "faceCenters": { "0": [x,y,z], "1": [x,y,z] },
  "boundingBox": { "min": [...], "max": [...], "center": [...], "diagonal": 0.0 }
}
```

Base64 of a packed Float32Array is ~1.37 bytes/float vs. ~8–12 bytes/float for
JSON decimal text — roughly a 6–8× payload reduction over the current format,
before gzip. Decoding to a `Float32Array` on the client is a
`Uint8Array.from(atob(...))` plus a buffer view, then straight into
`THREE.BufferAttribute` with no per-element JS loop.

Offer glTF/GLB later as an *export* format for CAD interoperability. That is a
different requirement from the viewport transport, and conflating them is what
makes people pick glTF too early.

### Client-side overlay switching

```ts
// Fetched once
geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
geometry.setAttribute('faceId',   new THREE.BufferAttribute(faceIds, 1))

// Swapped freely, zero network
function applyOverlay(faceResults: Record<number, RGB>) {
  const colors = new Float32Array(vertexCount * 3)
  for (let t = 0; t < triangleCount; t++) {
    const rgb = faceResults[faceIds[t]] ?? NEUTRAL
    // write rgb to the three vertices of triangle t
  }
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3))
}
```

Overlay switching becomes a local array write — sub-millisecond, no request.

### Component structure

```
frontend-web/
  src/
    api/
      client.ts                 typed fetch wrappers + structured error handling
      types.ts                  mirrors backend to_dict() schemas
    viewer/
      Viewport.tsx              <Canvas>, camera, lights, controls
      PartMesh.tsx              BufferGeometry + overlay material
      PartingLineOverlay.tsx    Line2 / LineMaterial (fat lines)
      UndercutVolumes.tsx       translucent Boolean region meshes
      MoldHalves.tsx            Phase 1b core/cavity solids
      PullDirectionGizmo.tsx    draggable arrow
    panels/
      DraftPanel.tsx            legend, histogram, suggestion list
      UndercutPanel.tsx         feature table, severity, mold actions
      DirectionPanel.tsx        candidate ranking, before/after
      PartingLinePanel.tsx      readiness, diagnostics, conflicts
      ReportPanel.tsx           export
    compare/
      SplitView.tsx             before/after, shared camera
    state/
      useAnalysisStore.ts       zustand — mesh cached, overlays swappable
```

### Split-screen before/after comparison

Two `<Canvas>` elements sharing one camera state object. Both read the **same**
cached `BufferGeometry` — geometry does not change between "before" (initial +Z)
and "after" (optimal direction); only the per-face color LUT and the parting
line polyline do. So the comparison view costs one extra draw call, not a second
mesh download.

`_before_after_rows` and `_render_before_after_story` in the Streamlit app
(`frontend/app.py:542,636`) already compute the comparison semantics — port that
logic, do not redesign it.

### Backend change required: PartGeometry caching

This is the one place Phase 2 forces a backend architectural change, and it
**deliberately breaks a documented invariant**, so it needs to be recorded in
`.claude/memory/decisions.md`.

Current: stateless, re-parse per request (`decisions.md`, "Stateless Backend
Design"). That decision's own stated trade-off is "`/direction` endpoint takes
30-60s". With a 60 fps client, re-parsing on interaction is untenable.

Proposed: an LRU cache keyed on `(resolved_path, stat.st_mtime_ns)`.

```python
@lru_cache(maxsize=CACHE_SIZE)
def _load_step_cached(path_str: str, mtime_ns: int) -> PartGeometry: ...

def get_part(path: Path) -> PartGeometry:
    return _load_step_cached(str(path.resolve()), path.stat().st_mtime_ns)
```

Including `mtime_ns` in the key means editing a STEP file invalidates its entry
automatically — no manual invalidation, no stale geometry.

**The `mutate` flag becomes considerably more dangerous under caching.** Today a
`mutate=True` leak is contained to one request because the object is discarded.
With caching, a mutated `PartGeometry` persists and every later request sees the
contamination. Mitigation, in order of preference:

1. Analysis handlers call with `mutate=False` and build response payloads from
   the returned result object rather than from `FaceData` fields.
2. Where mutation is genuinely needed, deep-copy the scalar analysis fields off
   the cached object first (never the OCC handles — those are C++ pointers and
   must be shared, not copied).
3. Add a regression test asserting a cached `PartGeometry`'s `FaceData` fields
   are unchanged after a full analysis sweep.

Config: `api.part_cache_size` (default 4), `api.part_cache_enabled` (default
true, so it can be switched off if a correctness bug is suspected).

### Migration sequencing (strangler fig)

| Step | Streamlit | React | Notes |
|---|---|---|---|
| 2.1 | live | — | Add new `/geometry` + `/analysis` endpoints alongside old ones |
| 2.2 | live | scaffold | Vite + R3F, mesh render only |
| 2.3 | live | overlays | Draft, undercut, core/cavity overlays |
| 2.4 | live | parting line + volumes | Fat lines, translucent regions |
| 2.5 | live | before/after | Split view |
| 2.6 | demo fallback | primary | Both work; React is the demo path |
| 2.7 | retired | primary | Remove `frontend/app.py`, drop deprecated endpoints |

Streamlit stays runnable through 2.6. If the React app is not ready on demo day,
the fallback is real, not theoretical.

CLAUDE.md invariant #3 ("Never import OCC in `frontend/`") extends to
`frontend-web/` unchanged — it talks to the API only.

---

# PHASE 3 — End-to-End Real-World Testing

## 3.1 Prerequisite

**Resolve finding F1 first.** Testing "two parts" that are byte-identical
validates nothing about generalization. Restore the true `Part1.stp` (likely
`rename.stp` / `Element_Packaging_Cap.stp`), confirm with the team, and only
then proceed.

## 3.2 Test matrix

| Part | Level | Must pass |
|---|---|---|
| `Part1.stp` (restored) | 1 | Load, draft, undercuts, direction, closed parting loop, core/cavity classification |
| `Part3.stp` | 2 | All of Level 1 + parting surface + solid split + multi-solid STEP export |
| Synthetic simple box | Regression | Known-answer: 6 faces, 0 undercuts, +Z optimal, planar parting line |
| Synthetic box + boss | Regression | Known-answer: exactly 1 undercut for an off-axis pull |

The two synthetic parts are new and matter more than they look. Every current
test mocks OCC (`test_undercut_detector.py` is 1,565 lines of mock-based tests).
Mocks verify plumbing, not geometry. A hand-built box whose correct answers are
known by inspection is the only way to catch a sign error in the convexity
computation. Generate them with CadQuery in a fixture, write to a temp dir, and
never commit them to `data/parts/`.

## 3.3 Validation gates per milestone

Extend `backend/validation/part_validation.py` with assertions, not just
reporting:

```bash
python -m backend.validation.part_validation \
  --direction --boolean-refine \
  --assert-parting-line-closed \
  --assert-core-cavity-solids=2 \
  --fail-on-missing-expected \
  --json
```

Extend `backend/validation/performance_profile.py` with budgets for the new
stages:

```bash
python -m backend.validation.performance_profile \
  --budget load_step=20 \
  --budget direction_search=120 \
  --budget parting_surface=45 \
  --budget solid_split=90 \
  --json
```

## 3.4 The OCC evidence problem

`known-gaps.md` records: "Saved validation reports — all show `status:
"skipped"` (no OCC in test env)". Every saved validation artifact is currently
evidence of nothing.

**This must be fixed before any Phase 3 claim is made.** Required:

1. Run the full harness inside the Docker backend image (which *does* have
   pythonocc-core 7.7.2 + cadquery 2.4.0 via conda-forge).
2. Commit the resulting JSON to `reports/` with the runtime environment recorded
   in the artifact.
3. Add a CI job that runs the OCC-dependent suite in that image. Without it,
   this regresses silently the first time someone runs pytest on a laptop.

```bash
docker compose up -d backend
docker compose exec backend python -m backend.validation.part_validation \
  --direction --boolean-refine --json > reports/validation_docker.json
docker compose exec backend python -m backend.validation.performance_profile \
  --direction --boolean-refine --json > reports/performance_docker.json
docker compose exec backend pytest tests/ -v --tb=short
```

## 3.5 Production Docker build

Current setup is dev-oriented: source is bind-mounted for live reload
(`./backend:/app/backend`), and the frontend uses `xvfb-run`.

Production changes:

| Concern | Change |
|---|---|
| Source mounts | Remove; `COPY` into the image so it is reproducible |
| Frontend | Multi-stage: `node:20` build → static `dist/` served by nginx or FastAPI `StaticFiles` |
| Xvfb | Drop entirely — rendering moves to the client in Phase 2 |
| Health checks | Keep the backend check; add one for the static frontend |
| Config | Keep `./config.yaml:/app/config.yaml:ro` — per CLAUDE.md invariant #4, tuning without a rebuild is the point |
| Image size | The conda/OCC backend layer is large; use a multi-stage build that discards conda build artifacts |

---

# PHASE 4 — AI Agent Orchestration Layer

> **Current state, stated plainly**: `backend/agent/dfm_agent.py` and
> `backend/agent/tools.py` are **0 bytes**. Nothing exists. Per
> `.claude/rules/honesty-and-scope.md`, do not describe this layer as
> implemented, partially implemented, or scaffolded until code lands.

## 4.1 Provider strategy: provider-agnostic, Gemini default

**Decision (2026-07-26)**: the agent layer is built against a provider-agnostic
interface, with **Google Gemini as the default provider** for cost and ease of
testing, and Anthropic and OpenAI as first-class swappable adapters.

This supersedes the `agent.model: "gpt-4o-mini"` value currently in
`config.yaml` and the matching note in `TODO.md`.

Rationale:

- Gemini is the cheapest per-token option of the three at the tier this project
  needs, and the team can test against it without budget friction.
- `understand.md` explicitly states Bosch must be able to "swap or upgrade the
  AI model" — an abstraction is a stated requirement, not gold-plating.
- All three providers expose equivalent function/tool-calling semantics, so the
  abstraction is thin.

```yaml
agent:
  provider: "gemini"            # gemini | anthropic | openai
  temperature: 0.1
  max_tool_iterations: 8
  models:
    gemini:    "gemini-2.0-flash"
    anthropic: "claude-opus-5"
    openai:    "gpt-4o-mini"
```

New dependencies (add to `requirements.txt`; all pip-installable, none are
conda-only like OCC):

```
google-generativeai          # gemini
langchain-google-genai       # only if the LangChain path is kept
anthropic                    # anthropic adapter
# openai / langchain-openai already pinned
```

## 4.2 Module layout

```
backend/agent/
  __init__.py
  providers.py       LLMProvider protocol + Gemini/Anthropic/OpenAI adapters
  tools.py           tool definitions wrapping the geometry engine
  schemas.py         pydantic models for structured DfM recommendations
  prompts.py         senior mold engineer system prompt
  dfm_agent.py       orchestration loop
```

### `providers.py`

```python
class LLMProvider(Protocol):
    name: str
    def invoke(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> ProviderResponse: ...

@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict          # JSON Schema — the common denominator
    fn: Callable[..., dict]

@dataclass
class ProviderResponse:
    text: str | None
    tool_calls: list[ToolCall]
    finish_reason: str
    usage: TokenUsage
```

Each adapter translates `ToolSpec` into its native format:

| Provider | Tool format | Notes |
|---|---|---|
| Gemini | `FunctionDeclaration` in `Tool` | JSON Schema subset; `additionalProperties` unsupported — strip it |
| Anthropic | `{name, description, input_schema}` | JSON Schema directly |
| OpenAI | `{type: "function", function: {...}}` | JSON Schema directly |

Write the tool schemas once as plain JSON Schema and let each adapter down-convert.
Gemini's subset is the most restrictive, so authoring to Gemini's constraints
keeps all three adapters trivial.

## 4.3 Tool definitions

Tools wrap the geometry engine. Six tools mirror the six analysis endpoints:

| Tool | Wraps | Returns |
|---|---|---|
| `load_part_summary` | `load_step` + `PartGeometry.to_dict()` | topology counts, bbox, surface-type histogram |
| `analyze_draft` | `draft_analyzer.analyze_draft` | class counts, %s, bad face IDs, suggestions |
| `detect_undercuts` | `undercut_detector.detect_undercuts` | features, severity, types, mold actions, confidence |
| `optimize_pull_direction` | `direction_optimizer.optimize_mold_direction` | best direction, score, candidate ranking |
| `detect_parting_line` | `parting_line.detect_parting_line_candidates` | readiness, closure, conflicts, diagnostics |
| `classify_core_cavity` | `core_cavity.classify_core_cavity` | cavity/core/parting areas and %s |

### Four hard rules for tool implementations

**1. Never return OCC handles.** Every tool returns the result of `.to_dict()`
or a plain dict. `occ_face`, `occ_edge`, `occ_shape` are live C++ pointers; they
are not JSON-serializable and must never approach the LLM boundary. This is
CLAUDE.md's data-flow invariant, and the agent layer is where it is most likely
to be violated by accident.

**2. Always `mutate=False`.** The agent may call `analyze_draft` a dozen times
across different directions while exploring. Under Phase 2's `PartGeometry`
cache, a single `mutate=True` call would corrupt state for every other user.
Tools are strictly read-only against the cached geometry.

**3. Truncate aggressively.** `UndercutDetectionResult.to_dict()` on a
200-face part is large, and `DirectionOptimizationResult.to_dict(include_all_candidates=True)`
is larger. Feeding raw dicts wastes context and degrades reasoning. Each tool
gets a summarizer that returns decision-relevant fields plus counts, with an
explicit `detail_available: true` flag the agent can act on by calling a
narrower tool. Cap face-ID lists at `agent.max_face_ids_per_tool` (default 25)
with a `truncated: true` marker.

**4. Surface failures as data, not exceptions.** A Boolean failure is
information the agent should reason about ("Boolean refinement failed on 3
faces, so this undercut count is a lower bound"), not a crash. Return
`{"status": "partial", "warnings": [...], ...}`. The engine already produces
exactly this structure via `BooleanReliabilitySummary` and the structured error
schema — pass it through rather than flattening it.

## 4.4 System prompt

Full text lives in `backend/agent/prompts.py`. Shape:

```
You are a senior injection mold design engineer with 15+ years of experience
in automotive plastic components, performing a Design for Manufacturability
review.

## Your tools
You have access to a STEP-native geometry engine that computes exact B-Rep
results. Call tools to obtain measurements. Never estimate a number you can
measure.

## Analysis order
Pull direction is foundational — every other result is computed relative to
it. Establish it first (or accept the user's), then draft, undercuts, parting
line, core/cavity.

## Evidence discipline
- Cite face IDs and measured values in every finding.
- Distinguish Boolean-confirmed evidence from proxy/heuristic evidence. The
  tools tell you which is which — carry that distinction into your output.
- When a tool reports warnings or partial results, say so. A qualified answer
  beats a confident wrong one.
- Never state a number the tools did not give you.

## What you must not claim
- Do not claim wall thickness analysis, mold flow simulation, or cycle time
  estimation. The engine does not compute them.
- Do not claim a parting line is final or verified unless readiness is "ready".
- Undercut depth is an engineering estimate; label it as such.

## Output
Return findings as structured DfM recommendations. Prioritize by
manufacturing cost impact: undercuts requiring side actions first, then draft
violations, then parting-line concerns.
```

The "what you must not claim" section maps 1:1 to
`.claude/rules/honesty-and-scope.md`. The project's honesty policy is enforced
in the system prompt, not just in documentation — otherwise the LLM layer
becomes the exact mechanism by which the honesty rules get bypassed.

## 4.5 Structured recommendation schema

```python
class Severity(str, Enum):
    CRITICAL = "critical"    # part cannot be molded as designed
    HIGH     = "high"        # needs expensive tooling (side action, lifter)
    MEDIUM   = "medium"      # quality/cosmetic risk
    LOW      = "low"         # minor optimization

class EvidenceSource(str, Enum):
    BOOLEAN_CONFIRMED = "boolean_confirmed"
    PROXY_HEURISTIC   = "proxy_heuristic"
    USER_SUPPLIED     = "user_supplied"

class DfMFinding(BaseModel):
    finding_id: str
    category: Literal["draft", "undercut", "parting_line",
                      "core_cavity", "pull_direction"]
    severity: Severity
    title: str                          # "12 faces below minimum draft"
    description: str                    # engineer-readable explanation
    affected_face_ids: list[int]
    measured_values: dict[str, float]   # {"min_draft_deg": 0.3, ...}
    evidence_source: EvidenceSource
    confidence: float                   # 0.0 - 1.0
    recommendation: str                 # the concrete design change
    estimated_tooling_impact: str | None # "requires side-action slide"

class DfMReport(BaseModel):
    part_name: str
    pull_direction: tuple[float, float, float]
    pull_direction_source: Literal["optimal", "user_specified", "default_z"]
    overall_manufacturability: Literal["good", "acceptable",
                                       "problematic", "not_manufacturable"]
    findings: list[DfMFinding]
    summary: str
    analysis_warnings: list[str]        # engine warnings, surfaced not swallowed
    tools_called: list[str]             # audit trail
    generated_at: datetime
```

`evidence_source` and `analysis_warnings` are the schema's honesty enforcement.
A finding derived from proxy heuristics is structurally distinguishable from a
Boolean-confirmed one, so the frontend can render them differently and a reader
can weigh them appropriately.

## 4.6 Orchestration loop

```python
def run_dfm_analysis(part_file, user_query=None, provider=None) -> DfMReport:
    provider = provider or build_provider(settings.agent)
    messages = [system_prompt(), user_message(part_file, user_query)]

    for iteration in range(settings.agent.max_tool_iterations):
        response = provider.invoke(messages, tools=TOOL_SPECS)
        if not response.tool_calls:
            break
        messages.append(assistant_message(response))
        for call in response.tool_calls:               # execute all, then append
            result = execute_tool(call, part_file)     # never raises
            messages.append(tool_result_message(call.id, result))

    return parse_report(response.text)
```

Notes:

- **Bound the loop.** `max_tool_iterations` (default 8) prevents a runaway
  spend. Six tools with a coherent analysis order should converge in 4–6.
- **Batch tool results.** When a provider returns several tool calls in one
  response, execute all of them and append all results together. Splitting them
  across turns degrades parallel tool-calling on every provider.
- **`execute_tool` never raises.** It catches and returns
  `{"status": "error", "code", "message", "recovery_hint"}` — the same
  structured shape the API layer already uses (CLAUDE.md invariant #5).

## 4.7 API surface

```
POST /agent/analyze
     { filename, query?, provider? }  → DfMReport

POST /agent/chat
     { filename, messages[] }         → streaming response

GET  /agent/providers                 → available + configured providers
```

`/agent/analyze` runs the full sweep. `/agent/chat` supports the conversational
follow-up mode described in `understand.md` ("Talks to the designer in natural
language").

---

# STEP-BY-STEP IMPLEMENTATION ROADMAP

Each milestone is self-contained and ends in a verifiable gate. **Do not start a
milestone until the previous gate passes.**

## Phase 0 — Unblock (½ day)

| # | Task | Gate |
|---|---|---|
| 0.1 | Resolve F1: confirm and restore the true `Part1.stp` | Two distinct MD5s in `data/parts/`; both load |
| 0.2 | Fix F2: add `core_cavity.threshold` to `config.yaml`, wire through `backend/config.py`, remove hardcoded defaults | `grep -rn "0.05" backend/geometry/core_cavity.py` returns nothing |
| 0.3 | Fix F3: correct `.claude/rules/api-layer.md` endpoint table | Documented endpoints match `main.py` |
| 0.4 | Run the full OCC validation in Docker, commit real artifacts | No `status: "skipped"` in `reports/` |

## Phase 1 — Geometry Engine (7–10 days)

| # | Milestone | Deliverable | Gate |
|---|---|---|---|
| 1.1 | Edge convexity in loader | `EdgeData.convexity` populated at load | Synthetic box: 12 convex edges, 0 concave. Box-with-pocket: pocket's 4 base edges concave |
| 1.2 | Convexity-gated undercut suppression | False-positive suppression in `detect_undercuts` | Undercut count on Part1 unchanged or lower; Boolean call count measurably down |
| 1.3 | Extremal vertex depth | Exact depth along release vector, parting-plane reference | Known-geometry boss: depth within 1% of hand calculation |
| 1.4 | Flash risk + coarse-to-fine direction search | New scoring term; two-stage search | Fine stage finds a direction scoring ≤ coarse winner on Part1. **`mutate=False` regression test passes** |
| 1.5 | Draft conditional thresholds | Per-face override, surface-type table, deep-rib detection | Marking a face textured raises its requirement to 3.0°; `threshold_source` reported |
| 1.6 | networkx parting-line graph | Real graph replaces bounded DFS | Existing `test_parting_line.py` passes unchanged |
| 1.7 | Component bridging | Bridge via real B-Rep edges using `is_boundary` | A part with a split silhouette yields one connected path |
| 1.8 | Closed-loop guarantee | Min-cost cycle over components | `is_closed == True` and closure error < 0.05 mm on Part1 |
| 1.9 | Parting surface | Planar extrusion + `BRepFill_Filling` fallback | A valid `TopoDS_Face`/`Shell` covering the loop; planar path taken on Part1 |
| 1.10 | Core/cavity solid split | Blank → cut → split → two solids | Exactly 2 solids; volumes sum to blank − part within tolerance |
| 1.11 | Multi-solid STEP export | `STEPControl_Writer` | Written file reloads in pythonOCC with 2 solids; opens in a viewer |

**Phase 1 exit gate**: full validation harness passes on the restored `Part1.stp`
inside Docker, with a closed parting loop and two exported solids.

## Phase 2 — Frontend (7–10 days)

| # | Milestone | Deliverable | Gate |
|---|---|---|---|
| 2.1 | `PartGeometry` LRU cache | mtime-keyed cache + mutation regression test | Second `/direction` call ≥ 10× faster; cached `FaceData` provably unmutated |
| 2.2 | Split geometry/analysis endpoints | `/geometry/mesh` + `/analysis/*` | Analysis payloads carry no mesh arrays |
| 2.3 | Binary mesh transport | base64 typed arrays | Mesh payload ≥ 5× smaller than current JSON |
| 2.4 | Vite + R3F scaffold | App shell, part list, mesh render | Part renders; orbit at 60 fps (Chrome perf panel) |
| 2.5 | Client-side overlays | Draft, undercut, core/cavity via `faceId` LUT | Overlay switch issues zero network requests |
| 2.6 | Parting line + undercut volumes | Fat lines, translucent regions | Refined curve renders over the part; volumes are translucent |
| 2.7 | Pull-direction gizmo | Draggable arrow, re-analyze on release | Direction change triggers exactly one analysis round-trip |
| 2.8 | Split-screen before/after | Shared camera, dual viewport | Both panes render; cameras stay synchronized |
| 2.9 | Panels + report view | Findings, tables, legends | Feature parity with the Streamlit panels |

**Phase 2 exit gate**: React app covers every Streamlit capability; Streamlit
still runs as fallback.

## Phase 3 — Testing & Production (4–6 days)

| # | Milestone | Gate |
|---|---|---|
| 3.1 | Synthetic known-answer fixtures | Box and box+boss produce hand-verified results |
| 3.2 | Real-OCC integration suite | Runs in Docker; no mocks; committed artifacts |
| 3.3 | Assertion flags in validation harness | `--assert-parting-line-closed` etc. fail correctly on bad input |
| 3.4 | Part3 Level 2 pass | Solid split + export succeed on Part3 |
| 3.5 | Performance budgets | All stages within budget; recorded in `reports/` |
| 3.6 | Production Docker build | No source mounts, no Xvfb, multi-stage frontend, health checks green |
| 3.7 | CI pipeline | GitHub Actions runs the OCC suite in the backend image |

**Phase 3 exit gate**: both parts pass end-to-end in a production image with
committed evidence.

## Phase 4 — AI Agent (4–6 days)

| # | Milestone | Gate |
|---|---|---|
| 4.1 | `providers.py` + Gemini adapter | Round-trip tool call against Gemini succeeds |
| 4.2 | Anthropic + OpenAI adapters | Same tool spec works on all three; provider swap needs only a config edit |
| 4.3 | `tools.py` — six tools | Each returns JSON-safe truncated dicts; **no OCC handle escapes** (assert in test) |
| 4.4 | `schemas.py` + `prompts.py` | `DfMReport` validates; prompt encodes the honesty rules |
| 4.5 | `dfm_agent.py` loop | Full analysis on Part1 in ≤ 8 iterations |
| 4.6 | `/agent/analyze` endpoint | Returns a valid `DfMReport` |
| 4.7 | Frontend agent panel | Findings render with evidence-source badges |
| 4.8 | Accuracy validation | Every numeric claim in the report traces to a tool result |

**Phase 4 exit gate**: agent produces a DfM report whose every number is
traceable to engine output, with proxy and Boolean-confirmed evidence visually
distinguished.

---

## Cross-Cutting Invariants (apply to every milestone)

1. **`mutate=True` only for the final displayed result.** Never in a scoring
   loop. This gets more dangerous, not less, once `PartGeometry` is cached.
2. **No OCC in any frontend.** Applies to `frontend-web/` exactly as it does to
   `frontend/`.
3. **No OCC via pip.** conda-forge only.
4. **No new magic numbers.** Every threshold introduced here goes in
   `config.yaml` and `backend/config.py`.
5. **`data/parts/` is read-only.** The F1 restoration is a one-time
   human-approved exception.
6. **Structured errors everywhere**: `code`, `message`, `operation`,
   `recovery_hint`, `details`.
7. **Update `STATUS.md`, `CHANGELOG.md`, `TODO.md` after every milestone.**
8. **Never claim a capability before its gate passes.** `IMPLEMENTATION_STATUS.md`
   is updated when a milestone lands, not when it starts.

---

## Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| `BRepFill_Filling` fails on complex non-planar loops | Blocks 1.9 → 1.10 → 1.11 | Planar-first strategy; most automotive parts admit a planar or near-planar parting line. Gate on flatness and report honestly when it fails |
| Boolean split yields ≠ 2 solids | Blocks 1.10 | Report actual count and the fuzzy value used; do not guess. Usually means the sheet did not fully cut the blank — extend it further |
| Caching + `mutate` interaction corrupts state | Silent wrong results across users | Rule: analysis handlers use `mutate=False`. Add the regression test in 2.1, before any caching ships |
| Fine-grained search inflates `/direction` runtime | Poor UX | Fine stage is prefilter-only, no Booleans. Budget-gated in 3.5. `fine_search_enabled: false` is a one-line rollback |
| React migration overruns | No demo UI | Strangler fig: Streamlit stays live through 2.6 |
| Convexity sign convention inverted | Systematically wrong undercut suppression | Milestone 1.1's gate is a synthetic box with hand-known answers — precisely to catch this |
| Agent narrates wrong geometry convincingly | Worst-case failure for a DfM tool | Phase 4 is last, by design. Every number must trace to a tool result (gate 4.8) |
| Gemini's JSON Schema subset rejects a tool schema | Blocks 4.1 | Author all schemas to Gemini's subset — the most restrictive of the three — so the other adapters are trivial |

---

## Open Questions for the Team

1. **F1**: which file is the true Level 1 `Part1.stp`? Is `rename.stp`
   (`Element_Packaging_Cap.stp`) it?
2. Is there a third `.stp` for Level 2, or is `Part3.stp` the intended Level 2
   part?
3. Should mold-half STEP export target a specific AP schema (AP203 vs AP214)
   for Bosch's downstream CAD?
4. Is PDF export (`reportlab`, pinned but unused) still a deliverable? It is not
   scheduled in this roadmap.
5. Texture marking: should textured faces be selectable in the UI (per §1e
   option 1), or supplied as a config/sidecar file?
