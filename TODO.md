# TODO — DfM Agent

> **Prioritized task list.** Update after each session. Mark items `[x]` when done, `[/]` when in progress.

---

## 🔴 P0 — Critical (Hackathon Deliverables Still Missing)

- [ ] **Implement AI Agent layer** — `backend/agent/dfm_agent.py` + `tools.py`
  - LangChain tool-calling wrapper around geometry functions
  - Natural-language analysis and suggestion generation
  - Use config: `agent.model: gpt-4o-mini`, `agent.temperature: 0.1`
  - Tools: `load_step`, `analyze_draft`, `detect_undercuts`, `optimize_direction`, `detect_parting_line`, `classify_core_cavity`
- [ ] **Get Part2.stp** and validate entire pipeline on it
- [ ] **Run Docker validation with OCC** and save real passing results (current reports show "skipped")
- [ ] **Fix overclaims in SUBMISSION_REPORT.md** — qualify parting line and core/cavity as partial

## 🟡 P1 — Important (Listed Deliverables, Not Started)

- [ ] **PDF report export** — use reportlab + `docs/DFM_REPORT_OUTLINE.md` template
  - Auto-fill metrics from geometry results
  - Embed screenshots or generate charts
- [ ] **Core/cavity Boolean solid split** (Level 2) — produce two separate `TopoDS_Shape` solids
- [ ] **Full parting line optimization** — Hou-style global graph minimum-cost closed loop

## 🟢 P2 — Nice to Have

- [ ] Parting surface generation (extend parting curve into ruled surface)
- [ ] Exhaustive Bassi Boolean analysis (every face, every direction)
- [ ] Sangolli volumetric decomposition (convex sub-volumes + radix sort)
- [ ] Edge convexity computation for Sangolli feature classification
- [ ] Frontend refactoring — break `app.py` monolith into components

## 🔵 P3 — Technical Debt

- [ ] Add `__init__.py` to `backend/geometry/`
- [ ] Add mypy/ruff config and type checking
- [ ] Set up CI/CD (GitHub Actions)
- [ ] Split `undercut_detector.py` (3,432 lines) into detection + Boolean + feature grouping
- [ ] Add integration tests that run with real OCC (requires conda CI)

## ✅ Done

- [x] STEP loader — full topology extraction
- [x] Draft analyzer — face-level analysis with suggestions
- [x] Undercut detector — selective Boolean + feature grouping
- [x] Direction optimizer — candidate search + Boolean pruning
- [x] Parting line foundation — silhouette candidates + Chaikin smoothing
- [x] Core/cavity face classification
- [x] FastAPI backend — all endpoints
- [x] Streamlit frontend — guided 5-step UI
- [x] Docker setup — backend + frontend
- [x] Config system — `config.yaml` + frozen dataclasses
- [x] Validation harnesses — part validation + performance profiling
- [x] Test suite — ~4,100 lines with OCC mocking
- [x] Documentation — IMPLEMENTATION_STATUS, DEMO_SCRIPT, EVIDENCE_CHECKLIST, etc.
- [x] Claude Code setup — `.claude/` with rules, skills, commands, memory
