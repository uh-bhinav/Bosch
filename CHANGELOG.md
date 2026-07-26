# Changelog — DfM Agent

> **Append-only.** Add new entries at the top. Format: `### YYYY-MM-DD — Summary`

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
