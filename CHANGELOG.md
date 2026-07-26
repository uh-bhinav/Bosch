# Changelog — DfM Agent

> **Append-only.** Add new entries at the top. Format: `### YYYY-MM-DD — Summary`

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
