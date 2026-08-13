# DfM Agent — Architecture Roadmap & Master Specification

> **Created**: 2026-07-26 · **Revised**: 2026-07-28
> **Authority**: This document describes *planned* work. For what the code does
> *today*, `docs/IMPLEMENTATION_STATUS.md` and the source remain authoritative.
> Where this document and `IMPLEMENTATION_STATUS.md` disagree about current
> state, `IMPLEMENTATION_STATUS.md` wins.
>
> **⚠️ 2026-07-28 revision.** Phase 1 (geometry engine) is now **substantially
> complete and verified against real geometry**. Phase 2 (React migration) is
> **CANCELLED** — see §0.2. The remaining work is re-planned into Stages 2–6
> in §0.3, driven by `docs/ENGINE_AUDIT_2026-07-27.md` and
> `docs/RECOVERY_PLAN.md`. Sections marked **[HISTORICAL]** describe the
> pre-fix state and are kept for context on *why* a design choice was made —
> they are not current status.

---

## ▶️ START HERE — next action

**Stage 2 is DONE (2026-07-28).** `split_core_cavity_solids()` and
`export_mold_halves()` are verified end-to-end on both real demo parts:
`split_ok`, exactly 2 solids, AP214 export that reloads with 2 solids. The
real 3-D parting surface turned out to be topologically invalid and
unfixable by standard OCC healing (`BRepCheck_Analyzer`,
`ShapeFix`/`Sewing` all tried) — the Boolean split now uses a separate,
honestly-labeled planar approximation tool instead
(`core_cavity.build_planar_split_tool`). See CHANGELOG.md "Stage 2b" and
`TODO.md` S2.3/S2.4/S2.5.

**Stage 3 is also DONE (2026-07-28), all of S3.1-S3.8.** Issue-first UI,
metric glossary, `graph_cleanup.strategy` always visible, direction
axis+tilt formatting, direction override (Bosch criterion #2), diverse
candidate clustering, and a backend LRU cache + mesh/analysis payload
split — all measured against real data, see `CHANGELOG.md` 2026-07-28
entries.

**Stage 4's first increment is DONE (2026-07-28).** `backend/geometry/
side_core.py` generates one side-core solid (Bosch criterion #5) for the
single highest-confidence critical undercut feature, Boolean-subtracted
from its containing mold half, exported as a third AP214 solid. §4.4's gate
is verified on both real parts: exported STEP reloads with exactly 3
solids, volumes conserve within 0.001%. §4.3's six design questions are all
answered explicitly (see §4.3 and `side_core.py`'s module docstring).
Grouped/multi-feature generation (§4.3 Q1) remains explicitly out of scope.

**Stage 5 (AI agent layer) is DONE (2026-07-28).** New `backend/agent/`
package — provider-agnostic tool-calling agent (Gemini/Anthropic/OpenAI/
Grok) driving the same 6 deterministic geometry functions the API already
exposes. Verified live, end-to-end, against real `Part1.stp` through
Gemini (`gemini-2.5-flash` — the roadmap's original `gemini-2.0-flash`
pick returns zero free-tier quota on the team's key, confirmed live).
Anthropic/OpenAI/Grok adapters are structurally verified against real SDK
signatures and unit-tested with mocks, not yet live-tested (no key
available for those three). See `CHANGELOG.md` 2026-07-28 for the two real
bugs found and fixed during live verification. **Stage 6 (PDF export) is DONE (2026-07-29).** New `backend/report/`
package finally uses `reportlab` (pinned since the initial scaffold,
imported nowhere until now) — a pure presentation layer over the same
`.to_dict()` payloads every analysis endpoint already returns, aggregating
every warning from every source rather than dropping any for a
cleaner-looking page. Verified end-to-end via `POST /parts/{filename}/
export/report` and a new frontend "PDF Report" section. Two real bugs
found and fixed, both known bug patterns from earlier stages this new
module had silently reintroduced (`best_label` duplication — the exact
S3.5 bug; a misleading 100% "conservation error" for `side_core.status ==
"no_feature"`). See `CHANGELOG.md` 2026-07-29.

**All six roadmap stages are now built.** The only work remaining is S4.3
(generalizing side-core generation to multiple/grouped features — now in
progress, partly motivated by a real robustness finding surfaced during
Stage 6 verification: a different undercut-detection parameterization on
Part1 hit a genuine 36.59% conservation error on a larger face grouping,
correctly caught by `side_core.py`'s own check) and the "Deferred/
Unscheduled" backlog in `TODO.md` (exhaustive Bassi Boolean analysis, full
Sangolli volumetric decomposition, `backend/geometry/__init__.py`, mypy/
ruff, splitting `undercut_detector.py`).
`TODO.md` S2.5 (tightening the ~4% volume-conservation gap in the *main*
core/cavity split) is a low-priority bounded follow-up, not a blocker.

| Doc | Read it for |
|---|---|
| `STATUS.md` | Current state of every module, open items, test status |
| `TODO.md` | Execution checklist |
| `CHANGELOG.md` | What changed and why, with measured evidence |
| `docs/ENGINE_AUDIT_2026-07-27.md` | Why Stage 1 was needed — the defect analysis |
| `docs/RECOVERY_PLAN.md` | The staged recovery this document now absorbs |
| This document | The plan and its rationale |

---

## 0. Execution Order and Rationale

### 0.1 Original five-phase plan — what actually happened

| Phase | Original scope | Outcome |
|---|---|---|
| **1** | Geometry engine hardening | ✅ **Done, then repaired.** Milestones 1.1–1.11 shipped, but an audit found four of the last six had been marked complete on "tests pass / function exists" rather than "output is geometrically correct". Nine defects (Bugs A–H-3) found and fixed 2026-07-27/28. |
| **2** | Frontend migration to React + Vite + Three.js | ❌ **CANCELLED** — see §0.2. Value redirected into Streamlit (Stage 3). |
| **3** | End-to-end real-world testing | 🔁 Partially absorbed into the cross-cutting geometry-assertion work (§0.4), which is the real fix for what Phase 3 was trying to catch. |
| **4** | AI agent orchestration | 📋 Still last, still deliberate — now Stage 5. |
| **5** | PDF report export | 📋 Still last. Now Stage 6. |

**The agent's placement remains deliberate.** An LLM narrating incorrect
undercut counts is more dangerous than no LLM at all, because it launders a
geometry bug into an authoritative-sounding engineering recommendation. The
audit proved this risk is not hypothetical: the parting-line stage reported
`closure_guaranteed=True, closure_error_mm=0.0` on a curve with a **17.35 mm
gap**. An agent wrapped around that would have confidently described a valid
mold split that did not exist.

### 0.2 Phase 2 (React migration) — cancelled

The original justification was rendering performance: server-side re-render
per interaction, full mesh re-sent per overlay. But the **Plotly/WebGL viewer
already in `frontend/app.py` renders client-side and interactively**, which
removes most of that pain. As of 2026-07-28 it is also the renderer in Docker
(`DFM_FORCE_PLOTLY=1`), so local and container now match.

A rewrite would consume the entire remaining budget and deliver **no new
engineering capability**. The genuinely valuable parts of the Phase 2 plan —
mesh/analysis split, backend `PartGeometry` caching, issue-first UI — are
folded into **Stage 3** and applied to Streamlit. The React specification in
the Phase 2 section below is retained as **[HISTORICAL]** for its transport
and caching design, which still applies.

### 0.3 Current plan — Stages 2 through 6

Stage 1 (parting-line correctness) is **complete**. What remains, ordered by
what unblocks the most:

| Stage | Scope | Status | Why here |
|---|---|---|---|
| **1** | Parting-line correctness | ✅ **Done** | Blocked everything. Bugs A, B, D, E, F, G, H, H-2, H-3 all fixed and verified on real geometry. |
| **2** | Unblock Level 2 — core/cavity + STEP export | ⬜ Next | Code exists and is unit-tested but has **never run against a valid parting surface**. Should mostly fall out of Stage 1. Small, high-confidence. |
| **3** | Engineering-review UI (Streamlit) | ⬜ Highest visible value | Metrics are visible but unreadable (§2.x). Also delivers Bosch criterion #2 (direction override), which is currently missing. |
| **4** | Side-core / lifter PL generation | ✅ First increment done | **Bosch criterion #5 — one side core generated, Boolean-subtracted, exported.** Grouped/multi-feature generation (§4.3 Q1) out of scope. |
| **5** | AI agent orchestration | ✅ Done | Provider-agnostic tool-calling agent (Gemini/Anthropic/OpenAI/Grok), Gemini live-verified end-to-end. Wraps the verified engine only — adds no new geometric capability. |
| **6** | PDF report export | ✅ Done | Pure presentation layer over already-computed results; `reportlab` finally imported. Verified end-to-end via the API + a frontend button. |

```
Stage 2  ███         Level 2 unblock            ← small, mostly falls out of Stage 1
Stage 3  ███████     engineering review UI      ← highest visible value
Stage 4  █████       criterion #5 first inc.    ← done
Stage 5  ██████      AI agent                   ← done
Stage 6  ███         PDF export                 ← done
```

### 0.4 Cross-cutting: the process defect that caused all of this

**Every bug in the 2026-07-27 audit survived a fully green test suite.** The
tests are mock-based and assert *structure* (does the function return the
right shape?) rather than *geometry* (is the curve actually closed?). Four
milestones were marked complete on that basis.

This is the actual root cause, and it is **not yet fixed**. Required, before
any further milestone is marked complete:

| Assertion | Catches |
|---|---|
| Measured first→last gap ≤ tolerance (**not** the reported flag) | Bug A |
| `graph_cleanup.strategy` is the exact optimiser, not `greedy-fallback` | Bug B |
| Every stage inside its time budget | Bug D |
| `parting_surface.status` is a generated status, not `failed` | Bug E |
| Solid split returns exactly 2 solids | Stage 2 gate |
| `silhouette_coverage_ratio` above threshold, or explicitly warned | Bug H |

These belong in `backend/validation/part_validation.py` as assertion flags
(`--assert-parting-line-closed`, `--assert-core-cavity-solids=2`,
`--assert-exact-optimiser`), runnable in CI against real OCC in Docker.

**Rule going forward: a milestone is complete when a real part produces
geometrically correct output, not when a mock test returns the right shape.**

---

## 0.1 Blocking Findings — original survey (all resolved)

These were found while surveying the repo for this roadmap. They are not
speculative.

### F1 — `Part1.stp`/`Part3.stp` identity (RESOLVED 2026-07-27)

Originally found byte-identical (both 863,881 bytes, MD5 `a373ffdf…`, both
carrying the internal STEP header `FILE_NAME('Part3.stp', ...)`), with a third
file `rename.stp` (522,419 bytes, internal name `Element_Packaging_Cap.stp`)
matching the size `STATUS.md` recorded for Part1.

**Resolved**: the team confirmed this was a genuine mix-up, and `rename.stp`
was restored as `Part1.stp`. Current verified state:

```
MD5 (data/parts/Part1.stp) = d0c89a7c67d40f3a0e18962d75947a2f   522419 bytes  (Level 1)
MD5 (data/parts/Part3.stp) = a373ffdf57ebb1036ec43b9e77025afa   863881 bytes  (Level 2)
```

Both declare `FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 3 1 1 1 }'))` —
**AP214** — which is now the confirmed target schema for Milestone 1.11's
mold-half STEP export (see Decisions Log). `data/parts/` now contains exactly
two distinct part files; `rename.stp` no longer exists. No further action
needed — Phase 3's two-part test matrix (§3.2) is valid as written.

### F2 — `core_cavity.py` reads a config key that does not exist (RESOLVED 2026-07-27, Phase 0.2)

`backend/geometry/core_cavity.py:14` documented:

> The threshold value is taken from config.yaml: `dfm.parting_line.silhouette_dot_tolerance`
> or defaults to 0.05

`config.yaml` had no `silhouette_dot_tolerance` key under `dfm.parting_line`,
and `classify_core_cavity()` took `threshold: float = 0.05` as a hardcoded
Python default; the API layer had its own hardcoded `Query(default=0.05)`.

This violated CLAUDE.md invariant #4 ("All config thresholds live in
`config.yaml`. No hardcoded magic numbers in algorithm code"). **Fixed**:
`dfm.core_cavity.threshold` added to `config.yaml` and `CoreCavitySettings`;
`classify_core_cavity(threshold: Optional[float] = None)` now defaults from
`settings.dfm.core_cavity.threshold` when the caller doesn't override it, and
the `/core-cavity` endpoint's `Query` default changed from a literal `0.05` to
`None` so it defers to the same settings value. Verified end-to-end via
`load_settings()`.

### F3 — `.claude/rules/api-layer.md` lists two endpoints that do not exist (RESOLVED 2026-07-27, Phase 0.3)

The rule file documented `/parts/{filename}/display-mesh` and
`/parts/{filename}/boolean-regions` as endpoints. Neither exists in
`backend/api/main.py`; both are query-parameter flags on other endpoints
(`include_mesh`, `include_boolean_regions`). **Fixed**: the endpoint table now
lists only the six real endpoints, with a note documenting `include_mesh` and
`include_boolean_regions` as the actual mechanism.

### F4 — `networkx==3.3` is a declared dependency with zero imports (RESOLVED 2026-07-28 — see the caveat)

`requirements.txt:44` pins it with the comment "Graph algorithms for Hou 2018
parting line". No file imports it. The current graph work in `parting_line.py`
is a hand-rolled bounded DFS (`_trace_best_weighted_path`, edge limit 22, state
limit 75,000) with a greedy fallback. Milestone 1.6 makes the dependency real.

**⚠️ This was marked resolved once, prematurely.** The first fix imported
`networkx` and used `nx.MultiGraph` for *adjacency queries only* — the actual
best-loop **search** remained the 22-edge bounded DFS with a non-backtracking
greedy fallback. Since real parts have ~206 candidate edges (206 ≫ 22),
**every real part still took the greedy fallback**. The dependency became
"used" without the algorithm becoming better. This is Bug B in the audit, and
it is the clearest example of the §0.4 process defect: a milestone marked
complete against its letter rather than its intent.

**Genuinely resolved 2026-07-28** via a shared exact-search dispatcher,
`_best_path_with_contraction_fallback`, used by **both** wire-ordering paths
(refinement *and* initial selection — the second one had no exact search at
all, which is why the first attempt at this fix didn't change real-part
behaviour). Degree-2 chains are contracted into hyper-edges so the search
scales with real branch points rather than raw edge count (Part3: 254 edges →
50 hyper-edges), with a polynomial-time `nx.cycle_basis` / `nx.find_cycle`
correctness fallback for when the exhaustive search exhausts its budget.

### F5 — the documented test command never actually worked (RESOLVED 2026-07-27, Phase 0.4)

Discovered while running Phase 0.4's real-OCC validation. `CLAUDE.md`
documents `docker compose exec backend pytest tests/ -v --tb=short` as the
test command; running it fresh in the `bosch-backend` image failed 100% of
206 tests with `ModuleNotFoundError: No module named 'backend'`.

Root cause: neither a root `conftest.py` nor a root `pytest.ini` exists —
only `tests/pytest.ini`. Bare `pytest tests/` from `/app` discovers that ini
file and, because it lives in `tests/`, pytest's `confcutdir` (and rootdir)
become `/app/tests` — so pytest never looks above `tests/` for a parent
conftest, and `/app` never lands on `sys.path`. A root-level `conftest.py`
does **not** fix this (verified — still failed with it present), because
`confcutdir` blocks its discovery regardless.

**Fixed**: added `pythonpath = ..` to `tests/pytest.ini` — pytest's native
ini option for exactly this "tests/ dir has no `__init__.py`, needs the
parent on sys.path" layout, resolved relative to rootdir (`/app/tests`), so
`..` → `/app`. Verified with the exact documented command
(`pytest tests/ -v --tb=short`) against `TestLoadStepIntegration::
test_loads_without_error` — passes.

**Side effect of the fix actually working**: one genuine test failure
surfaced that the import bug had been masking —
`test_api_error_handling.py::test_parting_line_paths_payload_is_json_safe`.
Not yet investigated; tracked in `TODO.md`.

---

# PHASE 1 — Geometry Engine Fixes & Innovations

> **✅ Substantially complete (2026-07-28).** The algorithm specifications below
> are still the reference for *how* each milestone works and are accurate.
> For what shipped, what broke, and what was repaired, see the execution table
> in "STEP-BY-STEP IMPLEMENTATION ROADMAP → Phase 1" and `STATUS.md`.

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

# STAGE 2 — Unblock Level 2 (core/cavity + STEP export)

> **✅ STATUS 2026-07-28 — DONE.** Two real bugs (dead import,
> `SetArguments` TypeError) plus a volume-sanity gap were found and fixed
> (Stage 2a). The predicted blocker (Part3 coverage) was NOT the real one —
> the real blocker was `BRepFill_Filling`'s patch never reaching the mold
> blank's bounds, THEN (once a shoulder extension was built) that the patch
> is topologically invalid independent of any extension, confirmed by
> `BRepCheck_Analyzer` and unfixable by `ShapeFix`/`Sewing` (Stage 2b). Fixed
> by using a separate, labeled planar-approximation Boolean tool instead of
> the real 3-D surface. Verified: `split_ok` + 2 solids + reloadable 2-solid
> STEP export on **both** Part1 and Part3. See CHANGELOG.md "Stage 2b" for
> full detail and `TODO.md` S2.1–S2.5. The plan below is kept for historical
> context on what was originally scoped.

## 2.1 What to do

1. Re-run `split_core_cavity_solids()` on both parts against the parting
   surface Stage 1 now produces (`generated_filling`, live `occ_shape`).
2. Re-run `export_mold_halves()` on the resulting solids.
3. **Reload the exported STEP file** and confirm it parses back to 2 solids.

## 2.2 Gates (measured, not reported)

| Gate | Assertion |
|---|---|
| Split succeeds | `solid_split_status` is a success status, not `blocked_by_parting_line` / `failed` |
| Exactly two solids | `split_solid_count == 2` |
| Volume conservation | cavity volume + core volume ≈ blank volume − part volume, within fuzzy tolerance |
| Export round-trips | exported `.stp` reloads via `load_step()` and yields 2 solids |
| Time budget | stage completes inside its performance budget |

## 2.3 Known risk

**Part3 may not pass.** Its parting loop covers only 18.1% of the projected
extent (its silhouette is genuinely fragmented across 22 B-Rep components), so
the surface built from it may not cleanly separate the blank. Part1 (94.8%
coverage) is the higher-confidence case.

If Part3 fails here, that is a **legitimate finding to report, not a bug to
hide** — it means fragmented-silhouette parts need either better loop
selection or manual parting-line input. The `silhouette_coverage_ratio`
warning already flags this honestly; Stage 2 should confirm what it means
downstream rather than paper over it.

---

# STAGE 3 — Engineering-Review UI (Streamlit)

> **Status**: ⬜ Highest visible value.
> **Replaces**: the cancelled Phase 2 React migration (§0.2).
> **Also delivers**: Bosch criterion #2 (direction override), currently missing.

## 3.1 The metrics problem — stated precisely

**The metrics are visible. That is not the problem.** The problem is that
there are a *lot* of them, presented as a flat dump, with no indication of
what any individual number means, what a good value looks like, or what to do
about a bad one. Two different people are failed by this:

- **The developer**, who cannot debug because they don't know what
  `depth_proxy_mm` or `pull_alignment=0.000` actually signify, or which
  numbers matter versus which are internal bookkeeping.
- **The mold engineer / viewer**, who needs to reach a conclusion in minutes
  and instead gets tables to scroll through.

**Critically: the engine already computes excellent explanation data.** This
is not a missing-data problem. `UndercutFeature` alone carries
`action_explanation`, `action_reason`, `action_confidence_factors`, and a
full `action_confidence_breakdown` with per-term `code` / `impact` /
`explanation` entries. Measured from a real Part1 export:

```
action_confidence_breakdown = {
  'base_score': 0.5, 'final_score': 0.98, 'label': 'high',
  'terms': [
    {'code': 'evidence.boolean_confirmed', 'impact':  0.25, ...},
    {'code': 'depth.vertex',               'impact':  0.12, ...},
    {'code': 'severity.critical',          'impact':  0.08, ...},
    {'code': 'type.silhouette',            'impact': -0.03, ...},   # negative!
  ],
  'summary': 'High confidence: Boolean-confirmed interference, depth from
              vertex-reference, critical severity; reduced by silhouette
              category is inherently ambiguous.'
}
```

That is genuinely well-designed provenance — it even tracks what *reduced*
confidence. **The failure is entirely presentational**: a real CSV export of
this data has ~45 columns, including `grouping_factors` with 25 repeated
`linked 30-31: bbox_gap_mm=0.0000 <= threshold_mm=4.6168` entries and
`boolean_intersection` containing ten identical repeated geometry analyses.

**So Stage 3 is an information-architecture task, not a data task.**

## 3.2 Three-layer progressive disclosure

Every metric surface should resolve to one of three layers. The default view
shows **Layer 1 only**.

### Layer 1 — Verdict (default, ≤ 5 items)

What a mold engineer needs to decide. Plain language, no jargon, no raw
numbers unless the number *is* the point.

```
🔴 Critical — Side action required
   A 26.9 mm deep undercut on 10 faces cannot release along the mold
   opening direction. This needs a side core.
   [ Show evidence ▾ ]

🟡 Review — Parting line covers 18% of the part outline
   Expected ≥ 35%. The part's silhouette is split across 22 separate
   edge groups, so the tool could not assemble one main loop.
   [ Show evidence ▾ ]

🟢 OK — Mold opening direction found
   (+0.232, +0.357, +0.905) ≈ +Z, tilted 25°
   0 faces with bad draft · 0% undercut area
   [ Compare alternatives ▾ ]
```

### Layer 2 — Evidence (one click)

*Why* the tool reached that verdict. This is where the existing `explanation`
/ `summary` / top confidence terms go — already computed, just not shown.

```
Confidence: high (0.98)
  ↑ +0.25  Boolean-confirmed interference
  ↑ +0.12  depth measured from vertex-reference
  ↑ +0.08  critical severity
  ↓ −0.03  silhouette category is inherently ambiguous
Depth 26.86 mm · interference volume 14,401 mm³ · 10/10 faces confirmed
```

### Layer 3 — Provenance / Debug (collapsed, developer-facing)

The full factor lists, method names, per-face IDs, raw breakdown dicts.
Everything currently dumped by default belongs **here**. Explicitly labelled
as diagnostic output.

## 3.3 Metric glossary — what each number means

A definition surface (inline tooltip **and** a reference page) covering, at
minimum:

| Metric | Must state |
|---|---|
| `readiness_status` / `score` | What ready/review/weak/failed *permit*; what blocks the next stage |
| `closure_error_mm` | Whether the loop is physically closed, and against what tolerance |
| **`graph_cleanup.strategy`** | **Whether the exact optimiser or the greedy fallback ran.** Exposing this alone would have caught Bug B immediately — it is the single highest-value metric to surface |
| `silhouette_coverage_ratio` | What fraction of the part outline the parting loop spans; that low means "probably a local feature, not the main line" |
| `undercut_area_pct` / severity | What fraction of the part is problematic; whether tooling is implied |
| Direction `score` | That it is **relative and unitless** — only meaningful compared to other candidates |
| `depth_proxy_mm` | That it is a **conservative upper bound, not a measurement** (per the locked decision in `TODO.md`) |
| `pull_alignment` | That 0.0 means fully transverse → side action; 1.0 means aligned with pull |
| `bridging_status` | Whether component bridging ran, was skipped, or was tried and discarded — and why |

**Each entry answers three questions: what it means · what good looks like ·
what to do if it's bad.**

## 3.4 Issue-first layout

Lead with **ranked issues**, not module panels. An engineer asks "what is
wrong, why, how serious, what should I change?" — the UI should answer in
that order. Module-by-module panels answer "what did each subsystem compute?",
which is a developer's question, and belongs in Layer 3.

This issue model is also **deliberate groundwork for Stage 5**: the agent will
consume exactly these `{severity, location, reason, recommendation, evidence}`
records.

## 3.5 Direction presented for humans

Show the vector **plus its closest axis and tilt angle**:

```
(+0.232, +0.357, +0.905)  ≈  +Z, tilted 25°
```

The pull direction is a continuous unit vector (correctly — it should not be
snapped to an axis), but "≈ +Z tilted 25°" is what a mold engineer actually
reasons about.

## 3.6 Direction override — Bosch criterion #2

**✅ DONE (2026-07-28).** ±X/±Y/±Z presets + a custom-vector input in the
Direction tab. Applying an override recomputes draft, undercuts, parting
line, and core/cavity against it via `_run_direction_override_pipeline()`,
stores the result separately (`override_result`) from the recommended
pipeline's own results — the recommendation is never overwritten — and
renders a "Recommended vs Override" comparison table plus an
always-visible "using an override" banner. The Findings panel (§3.1/§3.4)
switches to the override's results while one is active. Found and fixed a
real backend gap along the way: `/core-cavity` accepted
`use_optimal_direction=false` but silently ignored any supplied `dx/dy/dz`,
always falling back to a hardcoded `+Z` — fixed to match `/parting-line`'s
existing correct behavior. See `CHANGELOG.md` 2026-07-28 "S3.6" for full
detail and verification evidence.

## 3.7 Candidate comparison — the "multiple optimal solutions" story

**✅ DONE (2026-07-28).** `_cluster_diverse_candidates()` in
`frontend/app.py` greedily selects candidates ≥15° apart (candidates
pre-sorted best-first by score) instead of the raw top-N. The frontend now
fetches the full candidate set (`include_all_candidates=true`) — the
default top-10 the frontend previously requested is exactly where the
near-duplicate problem was hiding. Verified on real Part1: 114 scored
candidates → 17 genuinely distinct families. See `CHANGELOG.md` 2026-07-28
"S3.7" for full detail.

A real finding from the live Part1 run that motivated this fix: the top
candidates were **not diverse** — they were the same answer six times.

```
(+0.232,+0.357,+0.905) score 0.313   0.0° from best
(+0.211,+0.366,+0.906) score 0.348   1.3°
(+0.193,+0.380,+0.905) score 0.348   2.6°
(+0.218,+0.362,+0.906) score 0.385   0.9°
(+0.225,+0.359,+0.906) score 0.385   0.4°
(+0.326,+0.453,+0.829) score 0.532   8.9°
```

Six results within 9° — an artefact of the Milestone 1.4 fine-search cone.
Useless to an engineer asking "what are my options?"

**Fix**: cluster candidates by angular separation and surface the best of each
*distinct* family (≥ 15° apart) with score breakdowns. This directly serves
the robustness question: since multiple directions can be legitimately
acceptable, "does our answer equal *the* answer" is the wrong test. The
defensible claims are **validity** (is it genuinely undercut-free?),
**ranking transparency** (why did this beat the others?), **stability** (do
small perturbations change it wildly?), and **agreement where obvious** (does
a simple box give the obvious answer?).

Stop claiming *the* answer; start showing *the defensible options and why this
one ranks first*.

## 3.8 Performance items carried over from the cancelled React plan

**✅ DONE (2026-07-28).**

| Item | Benefit | Result |
|---|---|---|
| Backend `PartGeometry` LRU cache keyed on `(path, mtime_ns)` | Removes the STEP re-parse on every endpoint call — the single biggest latency source | `load_step_cached()` in `step_loader.py`. Measured: 0.79s cold → ~0.003s warm (≈250x). |
| Split `/geometry/mesh` (fetch once) from `/analysis/*` (no mesh in payload) | Stops re-downloading identical geometry on every overlay switch | The backend already had `to_payload(include_geometry=...)`; every endpoint just hardcoded `True`. New `include_mesh_geometry` query param + frontend `_mesh_geometry_already_cached()` check. Measured: same `/draft` call 682,742 → 224,780 bytes (≈67% smaller). |

Both were backend changes, independent of the UI framework — no React
migration needed to get them. The `mutate`-flag regression test the roadmap
called mandatory: `_clone_pristine_part()` ensures only a pristine,
never-mutated template is cached, and every caller gets an independently
mutable clone — `tests/test_step_loader.py::TestLoadStepCached` locks this
in directly (mutate one clone's fields, assert a second clone from the same
cache entry is unaffected). Mesh correctness verified by inspecting the
actual rendered Plotly `mesh3d` traces via `AppTest` across all 5 analysis
tabs — real vertex/face counts every time, zero regression. See
`CHANGELOG.md` 2026-07-28 "S3.8" for full detail.

## 3.9 Gates

- A first-time viewer can state the part's top 3 issues **without scrolling**. ✅
- Every number on screen has a reachable definition. ✅
- `graph_cleanup.strategy` is visible somewhere in the default view. ✅
- Direction override recomputes the full downstream chain and shows the delta. ✅
- Candidate list shows genuinely distinct directions, not near-duplicates. ✅

**All Stage 3 gates met (2026-07-28). Stage 3 is complete.**

---

# PHASE 2 — Frontend Migration: Streamlit → React + Vite + Three.js

> **⚠️ [HISTORICAL — CANCELLED 2026-07-28]** This migration is **not
> happening**; see §0.2. Retained because its transport format, client-side
> overlay-switching, and `PartGeometry` caching designs are still correct and
> partially carried into Stage 3.8. Read it as design rationale, not as a plan.

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

# STAGE 4 — Side-Core / Lifter PL Generation (Bosch criterion #5)

> **Status**: ✅ **First increment (§4.4) done, 2026-07-28.** All six §4.3
> design questions are answered (see §4.3 below and
> `backend/geometry/side_core.py`'s module docstring). §4.4's gate is
> verified on both real demo parts. §4.3 Q1 (grouped/multi-feature
> generation) is explicitly deferred — see §4.6.

## 4.1 What existed before this stage (historical)

Nothing geometric. A `grep` for lifter/side-core work found only
**recommendation strings** in `undercut_detector.py` — e.g. the
`"lifter-or-collapsible-core-review"` action text and
`recommended_mold_action="side-action"`. The engine correctly *identified*
that a side action was needed and *why*; it produced no side-core parting
surface, no lifter geometry, and no side-core pull direction.

## 4.2 Why this is tractable now

The hard input already exists and is high quality. Measured on Part1:

```
Feature 0 — critical, side-action, high confidence (0.98)
  10 faces · depth 26.86 mm · interference volume 14,401 mm³
  release_direction        [-0.680, +0.734, 0.000]   ← transverse to pull
  release_direction_method boolean-region-center-transverse
  pull_alignment           0.000                     ← fully transverse
  Boolean-confirmed on 10/10 faces
```

A per-feature **release direction**, a **confirmed Boolean interference
volume**, and the **exact face set** are exactly the inputs a side-core
generator consumes. The undercut engine has already done the analysis work.

## 4.3 Design questions — resolved (2026-07-28)

Each question below is answered with a concrete decision, implemented in
`backend/geometry/side_core.py` (see its module docstring for the same list
with the "why", kept in sync with this section):

1. **Per-feature or grouped?** → **Per-feature only.**
   `select_primary_side_core_feature()` picks the single highest-interference
   critical feature; `generate_side_core()` handles exactly one feature per
   call. Grouping spatially-close features into a shared side core is
   explicitly deferred — see §4.6.
2. **Side-core pull direction** → **Verbatim `release_direction`**, never
   snapped to a machine axis. The undercut engine already computed it from
   real Boolean-confirmed geometry; there is no concrete reason yet to
   distrust it.
3. **Parting surface per side core** → **NOT `BRepFill_Filling`** (this
   section originally speculated that as "most likely reuse" — it isn't).
   That machinery is confirmed topologically invalid on both real parts for
   the *main* parting surface (Stage 2, S2.3) and there is no reason to
   expect it more reliable on a smaller, still-curved side feature. Reuses
   Stage 2b's proven fix instead: a flat planar Boolean-split tool
   (`core_cavity.build_planar_split_tool`), sized to the feature's own local
   footprint (via each feature face's `Bnd_Box` corners — see §4.4) and swept
   along `release_direction`.
4. **Lifter vs. side core vs. collapsible core** → **Not decided by this
   module, and it must never be described as if it were.** This module
   answers only "what volume of steel must retract, and along which
   direction" — the actuation-mechanism choice is a tooling-design decision
   outside geometry.
5. **Interaction with the main split** → the side core is subtracted from
   whichever main half (cavity or core) has the larger `BRepAlgoAPI_Common`
   overlap with the swept side-core volume.
6. **Output format** → additional solid in the **same** AP214 STEP file as
   cavity/core. `core_cavity.export_mold_halves` gained
   `solid_overrides`/`extra_solids` parameters (plain OCC shapes, not a
   `side_core.py` import — that would have been circular, since
   `side_core.py` already imports from `core_cavity.py`).

## 4.4 First increment — done (2026-07-28)

The smallest useful slice, as originally scoped:

> For the single highest-confidence, Boolean-confirmed, critical side-action
> feature: generate one side-core solid by sweeping a planar proxy of its
> face set along its computed `release_direction`, subtract it from the
> containing mold half, and export it as a third solid.

**Gate — verified on both real demo parts**: the three solids (cavity,
core, side core) reload from STEP with exactly 3 `TopAbs_SOLID`s, and their
volumes are consistent with the blank minus the part
(`reduced_half + untouched_half + side_core` matches the original
`cavity + core` total to within 0.001% on both parts):

```
Part1 @ pull=(0,0,1): feature 0, 6 faces, depth 26.97mm
  side_core_volume=9219.8 mm³, containing_half=core, conservation_error=0.00%
Part3 @ pull=(0,0,-1): feature 0, 1 face, depth 40.01mm, release≈+X
  side_core_volume=46967.3 mm³, containing_half=cavity, conservation_error=0.00%
```

Both parts' *optimal* pull direction eliminates undercuts by design (that's
what the direction optimizer searches for), so demonstrating this required a
fixed non-optimal direction — the API and frontend both support this via the
same manual-direction override mechanism as S3.6 (Bosch criterion #2).

Two real sizing/tolerance bugs were found and fixed while prototyping this
against real geometry (full detail in `side_core.py`'s module docstring and
`CHANGELOG.md` 2026-07-28):
- Footprint sizing must use each feature face's `Bnd_Box` corners, not face
  centroids (zero scatter for a single-face feature) or vertex-only sampling
  (misses curved-edge extrema — measured a 24x undersizing on Part3).
- The `BRepAlgoAPI_Common` fuzzy tolerance that measures the side-core
  overlap must be reused, unchanged, for the following `BRepAlgoAPI_Cut` —
  a mismatched pair measured 37.72% volume-conservation error on Part1 even
  though both Boolean operations individually reported success.

## 4.5 Honesty constraint

**Criterion #5 may now be described as**: "a real side-core solid exists for
the single highest-confidence critical feature, Boolean-subtracted from the
containing mold half, and exported alongside cavity/core in the same AP214
STEP file." Do **not** describe it as "side-core generation is complete" —
grouped/multi-feature generation (§4.3 Q1, §4.6) is explicitly out of scope
— and do **not** describe it as "lifter/slide/collapsible-core selection is
implemented" (§4.3 Q4 is explicitly not decided by this module; it answers
only what volume must retract and along which direction, not what kind of
moving part does it).

## 4.6 Explicitly deferred — not this increment

Grouping multiple/spatially-close undercut features into a shared side core
(§4.3 Q1) needs its own design pass if/when it becomes a requirement:
ordering when several side cores interact with the same mold half, how to
decide "spatially close enough to share," and whether a shared side core
should use one release direction or per-feature directions swept
independently and then fused. Not attempted here — see `TODO.md` S4.3.

---

# PHASE 3 — End-to-End Real-World Testing

> **⚠️ [HISTORICAL — partially superseded]** F1 is resolved. The core intent of
> this phase — catching geometry defects that mock tests miss — is now the
> cross-cutting work in §0.4, which is more specific about *which* assertions
> would have caught *which* bugs. The test matrix and Docker-evidence sections
> below remain valid.

## 3.1 Prerequisite

**Resolve finding F1 first.** Testing "two parts" that are byte-identical
validates nothing about generalization. Restore the true `Part1.stp` (likely
`rename.stp` / `Element_Packaging_Cap.stp`), confirm with the team, and only
then proceed.

**[RESOLVED 2026-07-27]** — Part1 = 522,419 B / `d0c89a7c…` (311 faces,
30.78 mm bbox); Part3 = 863,881 B / `a373ffdf…` (414 faces, 68.12 mm bbox).
Genuinely different geometry. There is no `Part2.stp`.

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

# STAGE 5 — AI Agent Orchestration Layer — DONE (2026-07-28)

> *(Originally "Phase 4". Renumbered 2026-07-28 — content unchanged and still current.)*

> **Status, stated plainly**: `backend/agent/` is implemented and verified.
> Gemini live-verified end-to-end against real `Part1.stp`; Anthropic/
> OpenAI/Grok structurally verified (real SDK signatures, mocked-provider
> unit tests) but not live-tested — no key was available for those three
> this session. See `CHANGELOG.md` 2026-07-28 for full detail, including
> two real bugs found and fixed during live verification.

## 4.1 Provider strategy: provider-agnostic, Gemini default — resolved with corrections

**Decision (2026-07-26), reaffirmed 2026-07-28 against real conflicting
evidence**: the agent layer is built against a provider-agnostic interface.
This section originally named Gemini as default with Anthropic/OpenAI as
adapters — but the *actual* `docker-compose.yml` only ever wired through
`OPENAI_API_KEY`/`GROK_API_KEY`, and `requirements.txt` already pinned
`langchain-openai`/`openai`, never `google-generativeai`/`anthropic`. Per
this project's own honesty rules (actual source/config outranks a planning
doc when they disagree), this was surfaced to the user rather than
silently resolved either way. The user chose **provider-agnostic, all
three adapters** — Gemini, Anthropic, and OpenAI all built, plus Grok as a
fourth option reusing the OpenAI adapter class via its OpenAI-compatible
endpoint (matching the scaffold that was already there).

Rationale (still holds):

- Gemini is the cheapest per-token option of the three at the tier this project
  needs, and the team can test against it without budget friction.
- `understand.md` explicitly states Bosch must be able to "swap or upgrade the
  AI model" — an abstraction is a stated requirement, not gold-plating.
- All three providers expose equivalent function/tool-calling semantics, so the
  abstraction is thin.

**Two corrections made during live verification, before any code was
written against a wrong assumption:**

1. **Model**: `gemini-2.0-flash` (this section's original pick) returns
   **zero free-tier quota** on the team's real key — confirmed via a live
   `generateContent` call returning HTTP 429 `RESOURCE_EXHAUSTED` with
   `limit: 0`. `gemini-2.5-flash` works with real successful responses on
   the same key and was chosen as the default instead.
2. **Package**: `google-generativeai` (named below) is the **legacy** SDK.
   The current, actually-installable, maintained package is `google-genai`
   — verified via a real `pip install` + a real live tool-calling round
   trip, rather than guessing at the legacy package's API surface.

```yaml
agent:
  provider: "gemini"            # gemini | anthropic | openai | grok
  temperature: 0.1
  max_tool_iterations: 8
  max_face_ids_per_tool: 25
  models:
    gemini:    "gemini-2.5-flash"   # was gemini-2.0-flash -- see correction 1 above
    anthropic: "claude-opus-5"
    openai:    "gpt-4o-mini"
    grok:      "grok-2-latest"
```

Dependencies actually added to `requirements.txt` (all pip-installable, none
conda-only like OCC; also bumped `openai` 1.25.0 → 1.109.1 after a real
`httpx`-compatibility conflict — see `CHANGELOG.md`):

```
google-genai==2.14.0          # gemini -- the modern unified SDK, NOT google-generativeai (see correction 2)
anthropic==0.120.1            # anthropic adapter
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

# STAGE 6 — PDF Report Export — DONE (2026-07-29)

> *(Originally "Phase 5". Renumbered 2026-07-28 — content unchanged and still current.)*

> **Status**: ✅ Implemented and verified end-to-end. See `CHANGELOG.md`
> 2026-07-29 for full detail, including two real bugs found and fixed
> during verification.

## 5.1 Scope

Confirmed deliverable (2026-07-27), deliberately sequenced last. `reportlab`
had been pinned in `requirements.txt` since the initial scaffold and was
imported nowhere — `backend/report/pdf_export.py` is what finally uses it.

## 5.2 Content sourced from prior phases

| Section | Source | Status |
|---|---|---|
| Part summary, topology | `PartGeometry.to_dict()` (Phase 1, already exists) | ✅ |
| Draft compliance | `DraftAnalysisResult` — %s, bad face count | ✅ (`threshold_source` lives per-suggestion, not top-level — not surfaced as a standalone field) |
| Undercut findings | `UndercutDetectionResult.features` — severity, type, evidence source | ✅ |
| Pull direction | `DirectionOptimizationResult.best_direction` + ranking | ✅ |
| Parting line | Readiness, closure, silhouette coverage, bridging status, parting-surface status | ✅ (no embedded curve image — text/table only) |
| Core/cavity | Areas, solid split status, side-core status (Stage 4) | ✅ |
| Viewport screenshots | Frontend-supplied base64 PNG (NOT `renderer.domElement.toDataURL()` — that assumed the cancelled React viewer; the actual frontend is Streamlit, so the screenshot must come from whatever the client can capture) | ✅ opt-in, verified with a real embedded PNG |
| Narrative summary | `DfMReport.summary` + findings, if the agent has run (Stage 5) — optional, the report must be generatable without it | ✅ opt-in via `include_agent_narrative`, degrades gracefully on failure |

## 5.3 Module layout

```
backend/report/
  __init__.py
  pdf_export.py       reportlab Platypus document builder
  templates.py        section layout, styles, Bosch-neutral branding placeholders
```

`pdf_export.py`'s single entry point, `build_dfm_report_pdf()`, takes the
same `.to_dict()` payloads every analysis endpoint already returns as JSON
(not the dataclasses directly — this matches how `backend/api/main.py`
already assembles responses, and keeps `pdf_export.py` decoupled from
importing the geometry dataclasses at all) — it does not recompute
anything. This keeps the report a pure presentation layer over
already-validated engine output, which matters for the honesty rules: the
PDF can never say something the engine didn't already assert.

## 5.4 API surface

```
POST /parts/{filename}/export/report
     ?use_optimal_direction&dx&dy&dz            (S3.6 direction-override pattern)
     &include_solid_split&include_side_core&include_agent_narrative
     { screenshot_png_base64? }                 (optional JSON body)
     → application/pdf
```

Screenshots are supplied by the frontend as base64 PNG in the request body
(the backend has no renderer and must not gain one — CLAUDE.md invariant #3
keeps OCC/rendering out of anything client-facing, and the reverse holds too:
the backend should not attempt to rasterize a viewport itself). The original
text here referenced `renderer.domElement.toDataURL()`, which assumed the
cancelled React viewer (§0.2) — the actual frontend is Streamlit, so
screenshot capture is left entirely to whatever the client can produce; the
endpoint just accepts base64 PNG bytes from any source.

## 5.5 Honesty constraint

Every numeric claim in the PDF must trace to a field on one of the result
dataclasses above — no new computation happens in the report layer. If a
section's source data has warnings (e.g. `BooleanReliabilitySummary` showing
degraded confidence, or `PartingLineDiagnosticGate` blocking downstream use),
the PDF must surface that warning, not omit it for a cleaner-looking page.

---

# STEP-BY-STEP IMPLEMENTATION ROADMAP

Each milestone is self-contained and ends in a verifiable gate. **Do not start a
milestone until the previous gate passes.**

## Phase 0 — Unblock (½ day)

| # | Task | Gate | Status |
|---|---|---|---|
| 0.1 | Resolve F1: confirm and restore the true `Part1.stp` | Two distinct MD5s in `data/parts/`; both load | ✅ Done — `Part1.stp` (522,419 B) and `Part3.stp` (863,881 B) are distinct, both AP214 |
| 0.2 | Fix F2: add `core_cavity.threshold` to `config.yaml`, wire through `backend/config.py`, remove hardcoded defaults | No literal `0.05` default in `classify_core_cavity()`'s signature or the `/core-cavity` `Query()`; `load_settings().dfm.core_cavity.threshold == 0.05` | ✅ Done |
| 0.3 | Fix F3: correct `.claude/rules/api-layer.md` endpoint table | Documented endpoints match `main.py` | ✅ Done |
| 0.4 | Run the full OCC validation in Docker, commit real artifacts | No `status: "skipped"` in `reports/` | ✅ Done — evidence in `reports/level1_validation/` |

Also completed as part of Phase 0: corrected the overclaimed "Complete" status
for parting line and core/cavity in `docs/SUBMISSION_REPORT.md`'s evaluation
matrix (per `.claude/rules/honesty-and-scope.md`'s explicit warning about that
file).

## Phase 1 — Geometry Engine (7–10 days)

| # | Milestone | Deliverable | Gate | Status |
|---|---|---|---|---|
| 1.1 | Edge convexity in loader | `EdgeData.convexity` populated at load | Synthetic box: 12 convex edges, 0 concave. Box-with-pocket: pocket's 4 base edges concave | ✅ Done (2026-07-27) — see note below |
| 1.2 | Convexity-gated undercut suppression | False-positive suppression in `detect_undercuts` | Undercut count on Part1 unchanged or lower; Boolean call count measurably down | ✅ Done (2026-07-27) — see note below |
| 1.3 | Extremal vertex depth | Exact depth along release vector, parting-plane reference | Known-geometry boss: depth within 1% of hand calculation | ⚠️ Reassessed (2026-07-27) — see note below |
| 1.4 | Flash risk + coarse-to-fine direction search | New scoring term; two-stage search | Fine stage finds a direction scoring ≤ coarse winner on Part1. **`mutate=False` regression test passes** | ✅ Done (2026-07-27) — see note below |
| 1.5 | Draft conditional thresholds | Per-face override, surface-type table, deep-rib detection | Marking a face textured raises its requirement to 3.0°; `threshold_source` reported | ✅ Done, scoped down (2026-07-27) — see note below |
| 1.6 | networkx parting-line graph | Real graph replaces bounded DFS | ~~Existing `test_parting_line.py` passes unchanged~~ → **revised**: `graph_cleanup.strategy` ≠ `greedy-fallback` on a real part | ✅ Done 2026-07-28 (Bug B) — **first attempt failed this milestone's intent**, see F4 |
| 1.7 | Component bridging | Bridge via real B-Rep edges using `is_boundary` | A part with a split silhouette yields one connected path | ✅ Done, then repaired twice (Bug F, Bug D, Bug H-2) |
| 1.8 | Closed-loop guarantee | Min-cost cycle over components | ~~`is_closed == True`~~ → **revised**: *measured* first→last gap ≤ 0.05 mm, not the reported flag | ✅ Done, repaired (Bug A) — measured 0.000000 mm on both parts |
| 1.9 | Parting surface | Planar extrusion + `BRepFill_Filling` fallback | A valid `TopoDS_Face`/`Shell` covering the loop | ✅ Done, repaired (Bug E) — both parts `generated_filling`. **Filling is the normal path, not a fallback**: both parts have genuinely 3-D parting lines |
| 1.10 | Core/cavity solid split | Blank → cut → split → two solids | Exactly 2 solids; volumes sum to blank − part within tolerance | ⚠️ Implemented, **gate never verified** against a valid surface → **Stage 2** |
| 1.11 | Multi-solid STEP export | `STEPControl_Writer` | Written file reloads in pythonOCC with 2 solids; opens in a viewer | ⚠️ Implemented, **gate never verified** → **Stage 2** |

**Milestones 1.6–1.11 — what went wrong, and the lesson.** These six were
marked complete in a separate session on the basis of "tests pass / function
exists". An independent audit (`docs/ENGINE_AUDIT_2026-07-27.md`) found that
four of them did not actually produce correct geometry, and that the
parting-line stage was **reporting success while emitting a curve with a
17.35 mm gap** — a false guarantee that silently invalidated everything
downstream.

Note the gate revisions marked above. Several original gates were satisfiable
*without the feature working*:

- 1.6's gate ("existing tests pass unchanged") is satisfied by changing
  nothing that matters — which is exactly what happened.
- 1.8's gate (`is_closed == True`) checks a **reported flag**, which Bug A set
  unconditionally. A gate must measure the geometry, not read the claim.

Nine defects were found and fixed (Bugs A, B, D, E, F, G, H, H-2, H-3). The
full test suite now runs 237/237 with zero exclusions — previously 2–3 tests
hung indefinitely on real OCC and were permanently skipped, masking the
problem further.

**Every gate from here on must be measured against real geometry.** See §0.4.

**Milestone 1.5 implementation note — scoped down deliberately**: implemented
tiers 1 and 4 of the roadmap's resolution order (explicit per-face override
→ global default) plus the four named conditions
(`smooth`/`light_texture`/`heavy_texture`/`deep_rib`) with config-overridable
thresholds. Tiers 2 and 3 (surface-type defaults, automatic geometric
deep-rib detection) were **not** implemented, for reasons worth recording:

- **Tier 2 (surface-type defaults) is a no-op by the roadmap's own honesty
  ruling.** The roadmap explicitly says every surface type should default to
  `smooth` ("do not map freeform NURBS → textured... default everything to
  smooth and require explicit opt-in"). A configurable
  `surface_type_defaults` table would today just be an identity mapping to
  `smooth` for every surface type — no value in building the plumbing for a
  table that has nothing to configure yet. Trivial to add if a real
  surface-type-to-condition rule is ever identified.
- **Tier 3 (automatic deep-rib detection) needs real geometric analysis this
  milestone didn't have time to get right**: "a face whose bounding box has
  one dimension > `deep_rib_ratio` × another, and whose adjacent faces form
  a narrow channel" requires a per-face 3-D bounding box (not currently
  stored on `FaceData`, would need a fresh OCC `brepbndlib.Add` call per
  face) plus a genuinely fuzzy "forms a narrow channel" adjacency check.
  Rather than ship an unverified geometric heuristic, the `deep_rib`
  **condition** exists and is fully usable — a user (or a future automatic
  detector) can flag a face with it via `face_conditions` — but nothing
  triggers it automatically yet.

Resolution order actually implemented: **explicit per-face override → global
default**, exactly the tier the roadmap itself called "primary, honest."
`_build_suggestions` was extended to group by resolved condition too (not
just classification/surface_type/mold_side), so a mixed smooth+textured
group reports two suggestions with two different `required_angle_deg`
values instead of one averaged-and-wrong number.

Verified on real Part1.stp: marking a face `light_texture` changed its
`threshold_source` to `explicit_override`, raised its required draft to
3.0°, left every other face's `threshold_source` at `global_default`, and
split it into its own suggestion group with the correct required angle in
the action text. New tests: `tests/test_draft_analyzer.py::
TestFaceConditionThresholds` (6 new, mock-based). Full suite re-run: 57
passed, 0 regressions (`analyze_draft`'s existing thresholds/suggestions
behavior is unchanged when `face_conditions` is omitted).

API wiring (accepting `face_conditions` on the `/draft` endpoint) is
deferred to Phase 2, when the frontend actually has a texture-marking UI to
send it from — no value in exposing it earlier.

**Milestone 1.4 implementation note**: implemented as scoped — flash risk
term (`_flash_risk_area_fraction`, gated on face area vs.
`flash_thin_area_factor × bbox_diagonal²` as a wall-thinness proxy) and
coarse-to-fine search (`generate_fine_candidate_directions`, a local cone
sample around each of the top-K coarse winners, reusing the coarse stage's
own `mutate=False`/prefilter-only scoring path via a new shared
`_score_direction_candidate` helper — factored out to avoid duplicating the
~35-line candidate-scoring block for both stages). `mutate=True` still
happens exactly once, for the single final winner, unchanged.

Verified on real geometry (fine search on vs. off, `optimize_mold_direction`,
default config):

| Part | best_score off→on | candidates off→on |
|---|---|---|
| Part1 | 0.692 → 0.313 (−54.8%) | 54 → 114 |
| Part3 | 6.415 → 1.384 (−78.4%) | 54 → 114 |

The fine stage found a genuinely better direction on **both** real parts —
not a marginal tweak. Candidate count increased by exactly 60 (the
`fine_search_max_candidates` cap), confirming the cap is enforced as
designed. No timing regression observed (both runs stayed well under the
existing performance budgets).

New tests (`tests/test_direction_optimizer.py`, all mock-based, no OCC
needed): 3 for `_flash_risk_area_fraction` (thin+parallel flags, thick
doesn't, well-drafted-thin doesn't), 1 confirming the term actually moves
`_score_candidate`'s output, 3 for `generate_fine_candidate_directions`
(unit vectors within the cone, dedup against a shared `seen` set, empty for
non-positive parameters), and 1 end-to-end `optimize_mold_direction` check
(with `_OCC_BOOLEAN_AVAILABLE` explicitly forced `False` — see the
mock+real-Boolean finding in Milestone 1.2's note — confirming the fine
stage adds candidates without breaking the pipeline).

**Milestone 1.3 reassessment (2026-07-27) — no code change made**: this
milestone's stated gap was based on a shallower reading of the code than a
detailed pass revealed. Two distinct layers compute undercut depth, with two
different (and inconsistent) philosophies:

1. **Per-face** (`_select_boolean_depth_details` / `_estimate_boolean_depth`,
   in `undercut_detector.py`): already does exactly what this milestone asked
   for. It extracts exact B-Rep vertices of the confirmed Boolean intersection
   shape (`_shape_vertex_points`, via `TopExp_Explorer(shape, TopAbs_VERTEX)`
   — not mesh, not bounding-box), references depth against the source face's
   own offset centroid (arguably a *better* reference for "how far must a
   lifter travel to clear this" than a global parting-plane reference would
   be), and only falls back to bounding-box corners when exact vertices are
   unavailable. This priority order is deliberate and covered by four passing
   unit tests (`test_boolean_depth_selection_prefers_vertex_reference`,
   `test_boolean_depth_selection_keeps_reference_over_suspicious_span`,
   `test_boolean_depth_selection_uses_bbox_when_vertices_absent`,
   `test_boolean_depth_selection_falls_back_to_volume_area`). **No change
   needed here.**

2. **Feature-level aggregation** (`_estimate_release_and_depth_from_boolean_geometry`
   and the `base_depth_proxy = max(projection_depth, boolean_depth_proxy)`
   line in `detect_undercuts`): does the opposite — picks the **largest** of
   several candidates (the precise per-face depth from layer 1, a cruder
   centroid-projection proxy, and three bounding-box-derived spans), rather
   than preferring the precise one. An initial attempt to "fix" this to
   prefer precision (matching layer 1's philosophy) was **reverted** after
   discovering it breaks three existing, deliberately-asserting tests with
   exact numeric expectations
   (`test_boolean_geometry_refines_release_direction_and_depth`,
   `test_boolean_geometry_falls_back_when_unavailable`,
   `test_detector_uses_boolean_geometry_for_feature_release_and_depth` —
   e.g. `assert feature.depth_proxy_mm == 4.0` where the precise input was
   `1.0`). This is very likely a **deliberate conservative-safety-margin
   choice**: the feature-level number is what a mold engineer actually sees
   in the report, and overestimating undercut depth (oversized lifter/slide —
   a cost inefficiency) is a much safer failure mode than underestimating it
   (a mold that doesn't properly release — a real functional defect).
   Overriding tested, intentional behavior on my own judgment call is exactly
   the kind of decision that should go back to the team, not get silently
   changed. **Flagged for team discussion, not fixed.**

If the team decides layer 2 should also prefer precision, the fix is
straightforward (prioritize `fallback_depth_mm`/`boolean_depth_proxy` over
the cruder candidates, only falling back to them when the precise value is
`<= 0`) and was already drafted once — see git history around 2026-07-27 for
the reverted attempt. Until then, `depth_proxy_mm` on `UndercutFeature`
should be read as "a conservative upper-bound estimate," not "the precise
measured depth" — the per-face `BooleanInterferenceMetrics.depth_mm` values
underneath it are the precise ones.

**Milestone 1.2 implementation note**: verified against real Part1.stp and
Part3.stp (suppression on vs. off, `mutate=False`, `boolean_refine=True`,
calm environment):

| Part | undercut count off→on | Boolean-checked off→on | time off→on |
|---|---|---|---|
| Part1 | 44 → 18 | 78 → 27 | 45.2s → 13.4s |
| Part3 | 16 → 0 | 97 → 3 | 73.6s → 1.9s |

Both directions of the gate hold clearly. **Flagged for domain review, not
silently accepted**: Part3 dropping to zero undercuts is a large swing.
The suppression logic requires positive evidence (all bounding edges
convex/tangent, unclassified edges do NOT trigger suppression — see
`_compute_edge_convexity`'s docstring) and is verified against both the
synthetic box/pocket case (Milestone 1.1) and four targeted unit tests
(`tests/test_undercut_detector.py`, mock-based, no OCC needed), but a
100% swing on a real part is exactly the kind of result a mold engineer
should eyeball before trusting in a demo — it is plausible (Part3's
proxy-flagged faces may simply be smooth near-vertical sweeps with no
actual pocket) but has not been visually confirmed against the part.

Also discovered during verification (not a Milestone 1.2 bug — pre-existing,
orthogonal): `tests/test_undercut_detector.py::
test_detect_undercuts_flags_zero_draft_face` (and likely other pre-existing
mock-based tests that call `detect_undercuts`/`optimize_mold_direction`
without explicit `boolean_refine=False`) stall for minutes when run against
a container with **real** pythonocc-core installed, because their
`FaceData.occ_face` is a bare `MagicMock()` — not a valid SWIG-wrapped OCC
object — and the default `boolean_refine=True` path feeds it straight into
real `BRepAlgoAPI_Common`/`BRepPrimAPI_MakePrism` calls. Every test in this
suite that constructs a mock `PartGeometry` needs an explicit
`boolean_refine=False` to be Docker-safe now that F5 is fixed and these
tests can finally run against real OCC. Not fixed here — tracked in
`TODO.md` as a new item; fixing it is a test-suite hygiene pass across
`test_undercut_detector.py` and `test_direction_optimizer.py`, not a
Milestone 1.2 concern.

**Milestone 1.1 implementation note**: `BRepAdaptor_Curve.D1` does **not**
respect `TopoDS_Edge.Orientation()` — it always returns the tangent in the
underlying `Geom_Curve`'s own increasing-parameter direction, regardless of
how the edge is oriented in a face's wire. Naively using this tangent with an
arbitrarily-ordered pair of adjacent faces produces an essentially random
convex/concave split (empirically verified: a plain cube's 12 uniformly-convex
edges came back 6 convex / 6 concave). The fix, now in
`_compute_edge_convexity()`: use the edge occurrence exactly as encountered
while traversing one specific reference face's wire (which the existing
hash-based edge-dedup pass already tracks as `_eh_to_occ[h]`), manually flip
the tangent sign when that occurrence's `Orientation()` is `REVERSED`, and
always order the two adjacent-face normals with that same reference face
first. This is a genuine, non-obvious pythonOCC gotcha worth remembering for
any future edge-tangent work (e.g. Hou-style edge-weight curvature terms in
Milestone 1.6+).

**Phase 1 exit gate**: full validation harness passes on the restored `Part1.stp`
inside Docker, with a closed parting loop and two exported solids.

## ~~Phase 2 — Frontend (7–10 days)~~ — CANCELLED

> React migration cancelled 2026-07-28 (§0.2). Items 2.1–2.3 were backend
> work and survive as **Stage 3.8**; the rest is dropped.

| # | Milestone | Fate |
|---|---|---|
| 2.1 | `PartGeometry` LRU cache | ➡️ **Kept** — Stage 3.8. Backend work, framework-independent |
| 2.2 | Split geometry/analysis endpoints | ➡️ **Kept** — Stage 3.8 |
| 2.3 | Binary mesh transport | 🤔 Optional — revisit only if payload size is measured to be a real bottleneck in Streamlit |
| 2.4–2.9 | Vite/R3F scaffold, client overlays, gizmo, split-screen, panels | ❌ Dropped. The Plotly/WebGL viewer already renders client-side and interactively |

## Stage 2 — Unblock Level 2 (½–1 day)

| # | Milestone | Gate (measured on real geometry) |
|---|---|---|
| S2.1 | Re-run core/cavity solid split against the valid parting surface | Exactly 2 solids; volumes sum to blank − part within fuzzy tolerance |
| S2.2 | Re-run AP214 mold-half export | Exported file **reloads** via `load_step()` and yields 2 solids |
| S2.3 | Record the Part3 outcome honestly | Either it passes, or the failure and its cause (18.1% silhouette coverage) are documented — **not** worked around |

**Stage 2 exit gate**: Level 2 produces verified output for at least Part1,
with Part3's status recorded truthfully either way.

## Stage 3 — Engineering-Review UI (Streamlit)

| # | Milestone | Gate |
|---|---|---|
| S3.1 | Three-layer progressive disclosure (verdict / evidence / provenance) | Default view shows ≤ 5 verdict items; raw factor dumps are collapsed by default |
| S3.2 | Metric glossary — inline tooltips + reference page | Every number on screen has a reachable definition stating *meaning / good value / what to do* |
| S3.3 | Surface `graph_cleanup.strategy` in the default view | A greedy-fallback run is visible **without** opening a debug panel |
| S3.4 | Issue-first layout | Findings ranked by severity with location + reason + recommendation, not module-by-module panels |
| S3.5 | Direction shown as vector + closest axis + tilt | "(+0.232,+0.357,+0.905) ≈ +Z, tilted 25°" |
| S3.6 | **Direction override (Bosch criterion #2)** | ±X/±Y/±Z/custom recomputes the full downstream chain and shows the delta vs. optimal |
| S3.7 | Diverse candidate comparison | Candidate list shows directions ≥ 15° apart, not six near-duplicates |
| S3.8 | Backend `PartGeometry` LRU cache + mesh/analysis split | Second call ≥ 10× faster; cached `FaceData` provably unmutated (`mutate` regression test) |

**Stage 3 exit gate**: a first-time viewer can state the part's top three
issues without scrolling, and a developer can determine which code path ran
from the UI alone.

## Stage 4 — Side-Core / Lifter PL (Bosch criterion #5)

| # | Milestone | Gate |
|---|---|---|
| S4.1 | **Design pass** — answer the six questions in Stage 4 §4.3 | Written decisions, reviewed, before any code |
| S4.2 | First increment: one side core for Part1's critical feature | Three solids (cavity, core, side core) reload from STEP with consistent volumes |
| S4.3 | Generalize to multiple / grouped features | Documented grouping rule; no regression on Part1 |

**Stage 4 exit gate**: criterion #5 can be demonstrated with geometry, not
recommendation strings.

## Cross-cutting — Real-Geometry Assertions (do this alongside Stage 2)

| # | Milestone | Gate |
|---|---|---|
| X.1 | Assertion flags in `part_validation.py` | `--assert-parting-line-closed`, `--assert-core-cavity-solids=2`, `--assert-exact-optimiser` each **fail correctly on deliberately bad input** |
| X.2 | Synthetic known-answer fixtures | Box and box+boss produce hand-verified results |
| X.3 | Real-OCC integration suite in CI | Runs in the backend image; artifacts committed |
| X.4 | Performance budgets enforced | All stages within budget; recorded in `reports/` |
| X.5 | Production Docker build | No source mounts, multi-stage, health checks green |

**This is the highest-leverage non-feature work in the plan.** Every bug in
the 2026-07-27 audit would have been caught by X.1 alone.

## Stage 5 — AI Agent — DONE (2026-07-28)

| # | Milestone | Gate | Status |
|---|---|---|---|
| 4.1 | `providers.py` + Gemini adapter | Round-trip tool call against Gemini succeeds | ✅ Live-verified — real function-calling round trip against `gemini-2.5-flash` |
| 4.2 | Anthropic + OpenAI adapters | Same tool spec works on all three; provider swap needs only a config edit | ✅ Built + unit-tested against real SDK signatures (0.120.1 / 1.109.1); not live-tested (no key). Grok added as a 4th, reusing the OpenAI adapter class |
| 4.3 | `tools.py` — six tools | Each returns JSON-safe truncated dicts; **no OCC handle escapes** (assert in test) | ✅ Verified against real Part1.stp, including a direct mutate-safety check |
| 4.4 | `schemas.py` + `prompts.py` | `DfMReport` validates; prompt encodes the honesty rules | ✅ Done |
| 4.5 | `dfm_agent.py` loop | Full analysis on Part1 in ≤ 8 iterations | ✅ Live-verified — completed in 1-3 tool calls |
| 4.6 | `/agent/analyze` endpoint | Returns a valid `DfMReport` | ✅ Live-verified via FastAPI TestClient, success + error paths |
| 4.7 | Frontend agent panel | Findings render with evidence-source badges | ✅ Verified via Streamlit AppTest, including a real rate-limit error rendering gracefully |
| 4.8 | Accuracy validation | Every numeric claim in the report traces to a tool result | ✅ Confirmed on the one real live finding (face 232, 1.075°/1.5° draft) |

**Stage 5 exit gate met**: the agent produced a real DfM report on Part1.stp
whose every number (face 232, 1.075°/1.5° draft) traces to an actual tool
result, with `evidence_source="boolean_confirmed"` visually distinguished
from proxy heuristics. `tools_called`/`pull_direction`/
`pull_direction_source` are tracked mechanically, never taken from the
model's own text. See `CHANGELOG.md` 2026-07-28 for the two real bugs found
and fixed during live verification (direction-tracking mis-classification;
an `openai`/`httpx` version conflict).

**Deferred, not built this pass**: `/agent/chat` streaming endpoint (only
`/agent/analyze`'s single-shot sweep was built); Anthropic/OpenAI/Grok live
verification (no API key available for those three this session).

## Stage 6 — PDF Report Export — DONE (2026-07-29)

| # | Milestone | Gate | Status |
|---|---|---|---|
| 5.1 | `backend/report/pdf_export.py` + `templates.py` | A minimal PDF (part summary only) generates from a real `PartGeometry` | ✅ Verified on real Part1/Part3 |
| 5.2 | Section builders per result dict | Every section renders from its `.to_dict()` payload with no recomputation | ✅ |
| 5.3 | Screenshot embedding | Frontend-supplied base64 PNG embeds correctly in the PDF | ✅ Verified with a real embedded PNG via FastAPI TestClient |
| 5.4 | `/parts/{filename}/export/report` endpoint | Returns `application/pdf`; structured error on failure | ✅ Verified: success, 404 missing-part, 400 invalid-base64 |
| 5.5 | Frontend "Export PDF Report" action | One click produces a downloadable file end-to-end | ✅ Verified via Streamlit AppTest — real click, real bytes, no exception |
| 5.6 | Honesty audit | Every warning/degraded-confidence flag from the source dataclasses appears in the PDF | ✅ `_collect_warnings()` aggregates all sources; 2 real display bugs found and fixed (see CHANGELOG.md 2026-07-29) |

**Stage 6 exit gate met**: a generated PDF for both Part1 and Part3
contains every section, embeds a real screenshot when supplied, and
surfaces every engine warning rather than omitting any. 18 new tests in
`tests/test_pdf_export.py`.

---

## Cross-Cutting Invariants (apply to every milestone)

1. **A gate must measure geometry, not read a reported flag.** If a no-op
   change could satisfy a gate, the gate is wrong. *(Added 2026-07-28 — this
   is the single lesson from the 1.6–1.11 failure. Bug A set
   `closure_guaranteed=True` unconditionally; Bug B satisfied "existing tests
   pass unchanged" by changing nothing that mattered.)*
2. **"Tests pass" is necessary, never sufficient.** Mock tests assert
   structure; only real geometry proves correctness.
3. **Never leave a `-k` exclusion in a documented test command.** It hides
   exactly the thing it excludes (Bug G hid for weeks this way).
4. **`mutate=True` only for the final displayed result.** Never in a scoring
   loop. This gets more dangerous, not less, once `PartGeometry` is cached.
5. **No OCC in the frontend.** `frontend/` talks to the API only.
6. **No OCC via pip.** conda-forge only.
7. **No new magic numbers.** Every threshold introduced here goes in
   `config.yaml` and `backend/config.py`.
8. **`data/parts/` is read-only.** The F1 restoration is a one-time
   human-approved exception.
9. **Structured errors everywhere**: `code`, `message`, `operation`,
   `recovery_hint`, `details`.
10. **Update `STATUS.md`, `CHANGELOG.md`, `TODO.md` after every milestone.**
11. **Never claim a capability before its gate passes.**
    `IMPLEMENTATION_STATUS.md` is updated when a milestone lands, not when it
    starts.

---

## Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| **A milestone is marked complete without producing correct geometry** | 🔴 **MATERIALISED — this is what happened to 1.6–1.11.** Four milestones passed their gates while emitting broken output; the parting line reported a closed loop with a 17.35 mm gap | §0.4 real-geometry assertions (X.1). **Gates must measure geometry, not read a reported flag.** Rewrite any gate that a no-op change could satisfy |
| **Green mock tests give false confidence** | 🔴 **MATERIALISED — every audit bug survived a fully green suite** | Mock tests assert structure; add real-OCC assertions (X.1–X.3). Treat "tests pass" as necessary, never sufficient |
| **A test hangs on real OCC and gets permanently skipped** | 🟠 **MATERIALISED (Bug G)** — 2–3 tests hung indefinitely and were excluded via `-k` for weeks, masking further problems | Fixed by an `isinstance` type guard before SWIG calls. **Never leave a `-k` exclusion in a documented test command** — it hides the thing it excludes |
| Part3's fragmented silhouette blocks Level 2 | Level 2 may only work on Part1 | Already flagged honestly by `silhouette_coverage_ratio`. Stage 2 gate S2.3 requires recording the outcome truthfully rather than working around it |
| `BRepFill_Filling` fails on complex non-planar loops | Blocks 1.9 → 1.10 → 1.11 | ✅ Handled: fixed constructor args + loop decimation. Note **filling is the normal path, not a fallback** — both parts have genuinely 3-D parting lines |
| Boolean split yields ≠ 2 solids | Blocks 1.10 | Report actual count and the fuzzy value used; do not guess. Usually means the sheet did not fully cut the blank — extend it further. **Gate S2.1** |
| Caching + `mutate` interaction corrupts state | Silent wrong results across users | Rule: analysis handlers use `mutate=False`. Add the regression test in **S3.8**, before any caching ships |
| Fine-grained search inflates `/direction` runtime | Poor UX | Fine stage is prefilter-only, no Booleans. `fine_search_enabled: false` is a one-line rollback. **Side effect found**: the fine cone makes top candidates near-duplicates — see Stage 3.7 |
| Convexity sign convention inverted | Systematically wrong undercut suppression | Milestone 1.1's gate is a synthetic box with hand-known answers. **Still open**: Part3's 16 → 0 undercut swing needs mold-engineer sign-off |
| Agent narrates wrong geometry convincingly | Worst-case failure for a DfM tool | Stage 5 is last, by design — and the audit proved the risk is real, not hypothetical. Every number must trace to a tool result (gate 4.8) |
| Gemini's JSON Schema subset rejects a tool schema | Blocks 5.1 | Author all schemas to Gemini's subset — the most restrictive of the three — so the other adapters are trivial |

---

## Decisions Log (resolved 2026-07-27)

These were open questions in the original draft. Recorded here, with the
original question preserved for context, so the reasoning isn't lost.

1. **F1 — Part1/Part3 identity.** *Was*: which file is the true Level 1 input?

   > **⚠️ CORRECTED 2026-07-28.** This entry previously read "no mix-up …
   > no data restoration needed — F1 is closed without any change to
   > `data/parts/`." That **contradicted** `TODO.md` and `STATUS.md`, which
   > both record a genuine mix-up and a restoration. Re-verified against the
   > filesystem; the correction below reflects the evidence.

   *Resolved*: there **was** a genuine mix-up — `Part1.stp` and `Part3.stp`
   originally shared an MD5 (both were the Level 2 file). `rename.stp`
   (`Element_Packaging_Cap.stp`) was restored as `Part1.stp`.

   Verified state (2026-07-28):

   | File | Size | MD5 | Geometry |
   |---|---|---|---|
   | `Part1.stp` | 522,419 B | `d0c89a7c…` | 311 faces, 30.78 mm bbox (Level 1) |
   | `Part3.stp` | 863,881 B | `a373ffdf…` | 414 faces, 68.12 mm bbox (Level 2) |

   Two genuinely different parts. `rename.stp` no longer exists — its content
   *is* `Part1.stp`. This is the one human-approved exception to the
   "`data/parts/` is read-only" invariant.
2. **Level 2 part.** `Part3.stp` is confirmed as the intended Level 2 input —
   no third file is expected.
3. **Mold-half STEP export schema.** *Was*: AP203 vs AP214? *Resolved*: match
   the source files. `Part1.stp`/`Part3.stp` both declare
   `FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 3 1 1 1 }'))` — AP214,
   consistent with their Siemens NX origin. Milestone 1.11's
   `STEPControl_Writer` export targets **AP214** to match. If the OCC
   `STEPControl_Writer` binding does not expose an explicit AP214 schema
   selector, the reader/writer defaults for the pinned pythonOCC 7.7.2 build
   are AP214-compatible and should be verified against a round-trip read of
   the exported file's `FILE_SCHEMA` line, not assumed.
4. **PDF export.** *Was*: still a deliverable? *Resolved*: yes. Added as
   **Phase 5**, sequenced after Phase 4 deliberately — it draws on a stable
   engine (Phase 1), UI screenshots (Phase 2), and optionally agent narrative
   content (Phase 4). See the new Phase 5 section below and `TODO.md`.
5. **Texture marking.** *Was*: UI-selectable or config/sidecar file?
   *Resolved*: UI-selectable, confirming §1e option 1 (explicit per-face
   override supplied by the frontend from user selection). No sidecar file
   format is needed.
