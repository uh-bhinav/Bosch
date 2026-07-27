# Changelog — DfM Agent

> **Append-only.** Add new entries at the top. Format: `### YYYY-MM-DD — Summary`

---

### 2026-07-27 — Phase 0 fixes + Phase 1.1 (edge convexity) + Phase 1.2 (convexity-gated suppression) + Phase 1.3 (reassessed, no change) + Phase 1.4 (flash risk + coarse-to-fine search) + Phase 1.5 (draft conditional thresholds, scoped)

**Phase 1.5 — Draft conditional thresholds (`backend/geometry/draft_analyzer.py`),
scoped to explicit override + global default:**
- `analyze_draft(..., face_conditions: Optional[dict[int, str]] = None)` —
  per-face override to one of four named conditions
  (`smooth`/`light_texture`/`heavy_texture`/`deep_rib`), each with its own
  config-overridable good/marginal thresholds
  (`dfm.draft.conditions.<name>.{good,marginal}`). Unknown condition names
  log a warning and fall back to the global default rather than raising.
  Every face's resolved threshold, source (`explicit_override` |
  `global_default`), and applied condition are reported in `face_results`.
- `_build_suggestions` now also groups by resolved condition, so a mixed
  smooth+textured group produces separate suggestions with the correct
  `required_angle_deg` each, instead of one group averaged across
  incompatible requirements.
- **Deliberately did not implement** the roadmap's tiers 2 (surface-type
  defaults) and 3 (automatic deep-rib geometric detection) — tier 2 is a
  no-op today since the roadmap's own honesty ruling defaults every surface
  type to "smooth" (STEP carries no texture data to justify anything else),
  and tier 3 needs a per-face 3-D bounding box plus a fuzzy
  "forms a narrow channel" adjacency check that wasn't verified in the time
  available. The `deep_rib` *condition* exists and is usable via
  `face_conditions` even without automatic detection. Full reasoning in
  `docs/ARCHITECTURE_ROADMAP.md` Milestone 1.5 note.
- Verified on real Part1.stp: marking a bad-draft face `light_texture`
  correctly raised its required threshold to 3.0°, correctly tagged
  `threshold_source=explicit_override`, left all other faces at
  `global_default`, and split it into its own suggestion group with the
  right required angle in the action text.
- New tests: `tests/test_draft_analyzer.py::TestFaceConditionThresholds` (6
  new, mock-based). Full suite re-run: 57 passed, 0 regressions.
- API wiring (accepting `face_conditions` on `/draft`) deferred to Phase 2
  — no value exposing it before the frontend has a texture-marking UI to
  call it from.

**Phase 1.4 — Flash risk term + coarse-to-fine direction search
(`backend/geometry/direction_optimizer.py`):**
- `_score_candidate` now includes a flash-risk term: faces nearly parallel
  to the pull direction (`|n·d| < sin(flash_angle_threshold_deg)`) AND thin
  (area below `flash_thin_area_factor × bbox_diagonal²`, a coarse
  wall-thinness proxy — true thickness needs ray casting/medial-axis
  analysis, out of scope) contribute to a weighted penalty term, placed
  between marginal-draft and bad-draft in the scoring hierarchy.
- New two-stage search: after the existing 54-candidate coarse grid is
  scored and sorted, a local cone (`generate_fine_candidate_directions`,
  ±15° at 5° steps by default) is sampled around each of the top-3 coarse
  winners, scored with the identical prefilter-only path
  (`mutate=False`, `boolean_refine=False`), merged in, and re-sorted before
  Boolean refinement selection. Capped at 60 additional candidates. The
  per-candidate scoring block (draft + undercuts + score + result
  construction) was factored into a shared `_score_direction_candidate`
  helper to avoid duplicating it for both stages.
- `mutate=True` still happens exactly once, for the single final winner —
  unchanged contract.
- Verified on real geometry (fine search on vs. off): Part1 best_score
  0.692→0.313 (−54.8%), Part3 6.415→1.384 (−78.4%) — the fine stage found a
  genuinely better direction on both real parts, not a marginal tweak.
  Candidate count increased by exactly 60 as designed; no timing regression.
- New config: `flash_risk_weight` (200.0), `flash_angle_threshold_deg` (5.0),
  `flash_thin_area_factor` (0.02), `fine_search_enabled` (true),
  `fine_search_top_k` (3), `fine_angular_step_deg` (5.0),
  `fine_search_cone_half_angle_deg` (15.0), `fine_search_max_candidates` (60).
- New tests: `tests/test_direction_optimizer.py` (8 new, mock-based, no OCC
  needed). The end-to-end test explicitly forces
  `_OCC_BOOLEAN_AVAILABLE=False` to avoid the mock+real-Boolean stall found
  during Phase 1.2 verification.

**Phase 1.3 — reassessed, no code change.** The roadmap's stated gap
("bounding-box span over-reports undercut depth") was based on a shallower
reading of `undercut_detector.py` than a detailed pass revealed. The
per-face depth function (`_select_boolean_depth_details`) already extracts
exact B-Rep vertices of the Boolean intersection shape and prioritizes them
over bounding-box/volume fallbacks — exactly what this milestone asked for,
already covered by 4 passing tests. Attempted the same "prefer precision"
fix at the feature-level aggregation layer
(`_estimate_release_and_depth_from_boolean_geometry`,
`base_depth_proxy = max(...)`), then **reverted it** after discovering it
broke 3 existing tests with exact numeric assertions
(e.g. `assert feature.depth_proxy_mm == 4.0` against a precise input of
`1.0`) — the feature-level "take the largest plausible estimate" behavior is
very likely an intentional conservative-safety-margin choice (overestimating
undercut depth is a cheap tooling inefficiency; underestimating it is a real
mold defect), not a bug. Flagged as a team decision in `TODO.md` rather than
silently overridden. Full reasoning in `docs/ARCHITECTURE_ROADMAP.md`
Milestone 1.3 note.

**Phase 0 (all verified against real OCC in Docker, not mocks):**
- **F1 resolved**: confirmed `Part1.stp` (522,419 B) and `Part3.stp` (863,881 B)
  are genuinely distinct Level 1 / Level 2 inputs, both AP214. Verified via a
  real Docker validation run: Part1 = 311 faces / 30.78mm bbox diagonal,
  Part3 = 414 faces / 68.12mm bbox diagonal — geometrically distinct, and
  Part3's much longer `direction_search` (628s vs Part1's 85s) is consistent
  with it being the more complex Level 2 part.
- **F2 fixed**: `dfm.core_cavity.threshold` added end-to-end (`config.yaml` →
  `CoreCavitySettings` → `classify_core_cavity()` → `/core-cavity` endpoint).
- **F3 fixed**: `.claude/rules/api-layer.md` endpoint table corrected.
- Corrected the "Complete" overclaims for parting line and core/cavity in
  `docs/SUBMISSION_REPORT.md`'s evaluation matrix.
- **New finding (F5, fixed)**: the documented test command
  (`docker compose exec backend pytest tests/ -v --tb=short`) never actually
  worked — no root `conftest.py` or root `pytest.ini` put `/app` on
  `sys.path`, so every test failed collection with `ModuleNotFoundError: No
  module named 'backend'`. A root-level `conftest.py` doesn't fix it either:
  `tests/pytest.ini` being the discovered config file pins pytest's
  `confcutdir` to `tests/`, so it never looks above that directory for a
  parent conftest. Fixed with one line — `pythonpath = ..` in
  `tests/pytest.ini` — pytest's native mechanism for exactly this layout.
  Verified with the exact documented command.
- Ran real OCC validation (`part_validation.py --direction --boolean-refine`)
  and the performance profiler in Docker; committed real (non-`skipped`)
  evidence to `reports/level1_validation/`. Both parts pass every stage:
  load, topology, draft, undercut detection, direction search, parting line
  (both report `readiness: ready` with an already-closed wire under the
  *existing* heuristics — a useful baseline ahead of Phase 1.8's closure
  guarantee).
- Also surfaced (not yet fixed): `test_api_error_handling.py::
  test_parting_line_paths_payload_is_json_safe` is a genuine test failure,
  unrelated to the import bug — needs investigation.

**Phase 1.1 — Edge convexity (`backend/geometry/step_loader.py`):**
- `EdgeData.convexity` (declared since the initial scaffold, never populated)
  is now computed at load time for every manifold, non-seam edge —
  pull-direction-independent, so it's cached once rather than recomputed per
  direction downstream.
- New config: `dfm.undercut.convexity_tangent_tolerance` (default 0.01).
- Discovered and worked around a genuine pythonOCC gotcha:
  `BRepAdaptor_Curve.D1` ignores `TopoDS_Edge.Orientation()`, so both the
  tangent sign and the adjacent-face order must be tied to the *same*
  reference face to get a consistent convexity classification — verified
  empirically (a cube's 12 edges came back 6/6 split before the fix, 12/0
  after). See `docs/ARCHITECTURE_ROADMAP.md` Milestone 1.1 note for detail.
- Verified against: a synthetic 10×10×10 cube (12/12 convex), a cube with a
  rectangular pocket (pocket floor's 4 edges concave, matching the roadmap's
  stated gate; pocket's 4 internal vertical corners also correctly concave;
  rim and original box edges correctly convex), and real `Part1.stp` (>90%
  of manifold edges classified). New tests:
  `tests/test_step_loader.py::TestEdgeConvexitySynthetic`.

**Phase 1.2 — Convexity-gated undercut false-positive suppression
(`backend/geometry/undercut_detector.py`):**
- A proxy-undercut face (draft angle below the marginal threshold) whose
  bounding edges are ALL convex/tangent — no concave edge, so no genuine
  pocket — is now cleared before Boolean refinement ever sees it. An
  unclassified (`None`) edge does NOT trigger suppression: this requires
  positive evidence, not merely the absence of a concave edge.
- New: `UndercutDetectionResult.convexity_suppressed_face_ids` (full
  traceability — suppressed faces are never silently dropped), config
  `dfm.undercut.convexity_suppression_enabled` (default `true`, kill switch).
- Fixed a real bug found during verification: a suppressed face that also
  falls inside the parting-region dot-product band (which, given the shipped
  defaults, is essentially every suppressed face — `sin(0.5°) ≈ 0.0087` is
  smaller than `parting_dot_threshold=0.01`) was left with `is_undercut=None`
  instead of an explicit `False`, because the pre-existing final mutate block
  only clears faces outside the parting band. Now mutated explicitly at the
  point of suppression.
- Verified on real geometry (suppression on vs. off, calm Docker environment):
  Part1 undercut count 44→18, Boolean-checked 78→27, 45.2s→13.4s;
  Part3 undercut count 16→0, Boolean-checked 97→3, 73.6s→1.9s. **Both
  directions of the gate hold** ("count unchanged or lower", "Boolean calls
  measurably down"). Part3's 100%-suppression swing is flagged for a mold
  engineer's visual sanity check, not just accepted on the strength of unit
  tests — see `docs/ARCHITECTURE_ROADMAP.md` Milestone 1.2 note.
- New tests: `tests/test_undercut_detector.py` (4 new, mock-based, no OCC
  needed — suppression logic is deterministic given `EdgeData.convexity`).
- **Found, not fixed (pre-existing, orthogonal to this milestone)**: any
  mock-based test building `FaceData(occ_face=MagicMock())` and calling
  `detect_undercuts()`/`optimize_mold_direction()` without explicit
  `boolean_refine=False` stalls for minutes against a container with real
  pythonocc-core, because the mock is fed straight into real
  `BRepAlgoAPI_Common`/`BRepPrimAPI_MakePrism` calls. Invisible before F5 was
  fixed (Docker test runs never worked at all until today). Tracked in
  `TODO.md`.

**Environment note**: mid-session, this machine's Docker VM was shared with
several unrelated heavy tenants (`redline_*`, `k3d-*`, 9+ days uptime,
individually using 70-80% CPU) that caused severe slowdown and at least one
OOM-kill (exit 137) of a `performance_profile.py` run. Those containers were
not touched (not this project's). They exited independently partway through
the session (unrelated teardown), after which the shared VM had far more
headroom and subsequent runs completed quickly and reliably. Worth remembering
if a future session sees inexplicably slow or OOM-killed Docker runs on this
machine: check `docker stats` across ALL containers, not just this project's.

**Why:**
Executing the roadmap phase-by-phase as agreed: Phase 0 unblocks everything
downstream; Phase 1 proceeds one milestone at a time, each with a Docker-verified
gate before moving to the next, per the user's explicit instruction not to
batch or rush ahead.

---

### 2026-07-26 — Architecture Roadmap & Master Specification

**What changed:**
- Created `docs/ARCHITECTURE_ROADMAP.md` — full 4-phase master specification:
  - **Phase 1 — Geometry engine hardening**: closed-loop parting line via `networkx`
    with B-Rep edge bridging (`EdgeData.is_boundary`); parting surface via PCA planar
    extrusion with `BRepFill_Filling` fallback; real core/cavity solid split
    (`BRepAlgoAPI_Cut` → `BRepAlgoAPI_Splitter`) and multi-solid `STEPControl_Writer`
    export; edge convexity to kill undercut false positives; extremal vertex depth;
    flash-risk scoring term and coarse-to-fine (±5°) direction search; surface-type
    conditional draft thresholds.
  - **Phase 2 — Frontend migration**: Streamlit → React + Vite + react-three-fiber.
    Core design decision is splitting `/geometry/mesh` (fetched once) from
    `/analysis/*` (per-face results only), with client-side overlay switching driven
    by the existing `faceId` triangle attribute. Requires a `PartGeometry` LRU cache,
    which deliberately amends the stateless-backend decision.
  - **Phase 3 — Real-world testing**: synthetic known-answer fixtures, real-OCC
    Docker suite, assertion flags in the validation harness, production Docker build, CI.
  - **Phase 4 — AI agent**: provider-agnostic layer, tool definitions, senior mold
    engineer prompt, structured `DfMReport` schema with `evidence_source`.
- Rewrote `TODO.md` around the roadmap's phase/milestone structure.
- Added an "Open Blockers" table and a corrected data inventory to `STATUS.md`.

**Findings recorded (all verified against the repo, not speculative):**
- **F1 (blocker)**: `Part1.stp` and `Part3.stp` are byte-identical — same MD5
  `a373ffdf57ebb1036ec43b9e77025afa`, same 863,881 bytes, both carrying the internal
  header `FILE_NAME('Part3.stp', …)`. `rename.stp` is 522,419 bytes with internal name
  `Element_Packaging_Cap.stp`, matching the 522 KB that STATUS.md records for Part1.
  The original Part1 appears to have been overwritten by a copy of Part3.
- **F2**: `core_cavity.py:14` documents a config key
  `dfm.parting_line.silhouette_dot_tolerance` that does not exist; `threshold=0.05`
  is hardcoded in the module and again in `main.py`.
- **F3**: `.claude/rules/api-layer.md` documents `/display-mesh` and
  `/boolean-regions` endpoints that do not exist in `main.py`.
- **F4**: `networkx==3.3` is pinned for "Hou 2018 parting line" but never imported.
- `EdgeData.convexity` exists as a field and is never populated by any module.

**Decisions:**
- Phase 4 (AI agent) is sequenced **last**, deliberately. An LLM narrating incorrect
  geometry launders a bug into an authoritative-sounding engineering recommendation.
- Agent layer is **provider-agnostic with Gemini as the default** (cost and testing
  ease), Anthropic and OpenAI as swappable adapters. Supersedes
  `agent.model: "gpt-4o-mini"` in `config.yaml`. Tool schemas are authored to
  Gemini's JSON Schema subset — the most restrictive of the three.
- Frontend migration follows a strangler-fig pattern: Streamlit stays runnable
  through milestone 2.6 so the demo always has a working fallback.

**Why:**
Establishing one execution-ordered plan across geometry, frontend, testing, and the
agent layer, with explicit validation gates so no capability gets claimed before it
is demonstrated.

---

### 2026-07-26 — Claude Code Setup

**What changed:**
- Created root `CLAUDE.md` (~110 lines) with project identity, architecture, run commands, invariants, and honesty rules.
- Created `.claude/settings.json` with safe permissions (allow test/git/docker commands, deny STEP file edits and pip pythonocc).
- Created `.claude/settings.local.json` for per-developer overrides (gitignored).
- Created 6 path-scoped rules in `.claude/rules/`:
  - `geometry-engine.md` — PartGeometry patterns, mutate flag, Boolean pruning
  - `api-layer.md` — endpoint list, stateless design, structured errors
  - `frontend.md` — no OCC imports, session state, PyVista rendering
  - `testing.md` — layered test order, OCC mocking, threshold sources
  - `config-and-infra.md` — Docker, conda, config.yaml structure
  - `honesty-and-scope.md` — authority table, claims to avoid (always loaded)
- Created 6 on-demand skills in `.claude/skills/`:
  - `dfm-domain-knowledge` — injection molding domain concepts
  - `occ-pythonocc-reference` — OCC class glossary and patterns
  - `research-paper-fidelity` — exact gap mapping vs. 4 papers
  - `pipeline-data-flow` — field-level data flow across modules
  - `evidence-and-validation` — validation harness usage
  - `run-dfm-stack` — Docker/conda recipes
- Created 4 commands in `.claude/commands/`: test, debug, audit, status-check.
- Created 2 memory files: `decisions.md` (architecture log), `known-gaps.md` (what's missing).
- Created 3 project tracking files: `STATUS.md`, `CHANGELOG.md`, `TODO.md`.
- Updated `.gitignore` to include `.claude/settings.local.json`.

**Why:**
Setting up Claude Code for optimal context management. Rules are path-scoped so they only load when relevant. Skills are on-demand so CLAUDE.md stays under 200 lines. Tracking files keep the team aligned across sessions.

---

### Pre-2026-07-26 — Existing Codebase

Full Level 1 geometry pipeline built:
- STEP loader, draft analyzer, undercut detector, direction optimizer (all fully implemented)
- Parting line (foundation), core/cavity (face classification only)
- FastAPI backend, Streamlit frontend, validation harnesses
- Docker setup, conda environment, config system
- ~20,800 lines of Python across the project
- AI agent layer and PDF export remain unstarted
