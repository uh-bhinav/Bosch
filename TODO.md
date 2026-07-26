# TODO — DfM Agent

> **Prioritized task list.** Update after each session. Mark items `[x]` when done, `[/]` when in progress.

---

> **Master plan**: `docs/ARCHITECTURE_ROADMAP.md` holds the full 4-phase
> specification, algorithms, config keys, and per-milestone validation gates.
> The items below are its execution checklist.

---

## 🔴 P0 — Blockers (fix before any other work)

- [ ] **F1 — `Part1.stp` and `Part3.stp` are byte-identical** (same MD5 `a373ffdf…`, both 863,881 bytes, both with internal `FILE_NAME 'Part3.stp'`)
  - `rename.stp` (522 KB, internal name `Element_Packaging_Cap.stp`) matches the size STATUS.md records for Part1
  - Original Part1 was almost certainly overwritten; confirm with the team and restore
  - Until fixed, all "validated on two parts" claims are false — it is one part tested twice
- [ ] **F2 — `core_cavity.py` docstring references `dfm.parting_line.silhouette_dot_tolerance`, which does not exist in `config.yaml`**
  - `threshold=0.05` is hardcoded in `classify_core_cavity()` and again in `main.py`
  - Violates CLAUDE.md invariant #4 (no hardcoded magic numbers)
- [ ] **F3 — `.claude/rules/api-layer.md` documents `/display-mesh` and `/boolean-regions` endpoints that do not exist** (they are query flags on other endpoints)
- [ ] **F4 — `networkx==3.3` is pinned but never imported** — parting line uses a hand-rolled bounded DFS instead
- [ ] **Run Docker validation with real OCC and commit the artifacts** — every saved report currently shows `status: "skipped"`
- [ ] **Fix overclaims in SUBMISSION_REPORT.md** — qualify parting line and core/cavity as partial

## 🟠 PHASE 1 — Geometry Engine Hardening

- [ ] 1.1 Edge convexity computation in `step_loader.py` → populate `EdgeData.convexity` (currently always `None`)
- [ ] 1.2 Convexity-gated undercut false-positive suppression
- [ ] 1.3 Extremal vertex projection for exact undercut depth (parting-plane reference, not bbox span)
- [ ] 1.4 Flash risk penalty term + coarse-to-fine (±5°) direction search
- [ ] 1.5 Draft conditional thresholds (per-face override → deep-rib detection → surface-type table → global)
- [ ] 1.6 Replace bounded DFS with a real `networkx` graph in `parting_line.py`
- [ ] 1.7 Bridge disconnected silhouette components via real B-Rep edges (`EdgeData.is_boundary`)
- [ ] 1.8 Guaranteed closed loop — min-cost cycle over components
- [ ] 1.9 Parting surface — PCA planar extrusion first, `BRepFill_Filling` fallback
- [ ] 1.10 Core/cavity **solid** split — blank → `BRepAlgoAPI_Cut` → `BRepAlgoAPI_Splitter` → 2 solids
- [ ] 1.11 Multi-solid STEP export via `STEPControl_Writer`

## 🟡 PHASE 2 — Frontend Migration (Streamlit → React + Vite + Three.js)

- [ ] 2.1 `PartGeometry` LRU cache keyed on `(path, mtime_ns)` + `mutate` regression test
- [ ] 2.2 Split `/geometry/mesh` (fetch once) from `/analysis/*` (no mesh in payload)
- [ ] 2.3 Binary mesh transport — base64 typed arrays, not JSON decimals
- [ ] 2.4 Vite + react-three-fiber scaffold
- [ ] 2.5 Client-side overlay switching via the `faceId` vertex attribute (zero refetch)
- [ ] 2.6 Parting-line fat lines + translucent undercut volumes
- [ ] 2.7 Draggable pull-direction gizmo
- [ ] 2.8 Split-screen before/after with shared camera
- [ ] 2.9 Panels + report view at parity with Streamlit
- [ ] 2.10 Retire `frontend/app.py` (3,966 lines) once React reaches parity

## 🟢 PHASE 3 — Real-World Testing & Production

- [ ] 3.1 Synthetic known-answer fixtures (box, box+boss) — current tests are all OCC mocks
- [ ] 3.2 Real-OCC integration suite running in Docker
- [ ] 3.3 Assertion flags in `part_validation.py` (`--assert-parting-line-closed`, `--assert-core-cavity-solids=2`)
- [ ] 3.4 Part3 Level 2 pass — solid split + export
- [ ] 3.5 Performance budgets for parting surface and solid split
- [ ] 3.6 Production Docker build — no source mounts, no Xvfb, multi-stage frontend
- [ ] 3.7 CI pipeline (GitHub Actions) running the OCC suite in the backend image

## 🔵 PHASE 4 — AI Agent Orchestration

> **Provider decision (2026-07-26)**: provider-agnostic abstraction with
> **Gemini as default** (cheaper, easier to test), Anthropic and OpenAI as
> swappable adapters. This supersedes `agent.model: "gpt-4o-mini"` in
> `config.yaml`.

- [ ] 4.1 `backend/agent/providers.py` — `LLMProvider` protocol + Gemini adapter
- [ ] 4.2 Anthropic + OpenAI adapters (author schemas to Gemini's JSON Schema subset — the most restrictive)
- [ ] 4.3 `backend/agent/tools.py` — 6 tools; **no OCC handles, `mutate=False` always, truncated payloads**
- [ ] 4.4 `backend/agent/schemas.py` + `prompts.py` — `DfMReport` with `evidence_source`; honesty rules in the system prompt
- [ ] 4.5 `backend/agent/dfm_agent.py` — bounded orchestration loop (`max_tool_iterations: 8`)
- [ ] 4.6 `/agent/analyze` + `/agent/chat` endpoints
- [ ] 4.7 Frontend agent panel with evidence-source badges
- [ ] 4.8 Accuracy validation — every number traceable to a tool result

## ⚪ Deferred / Unscheduled

- [ ] PDF report export (`reportlab` pinned but unused) — **not scheduled in the roadmap**; confirm if still a deliverable
- [ ] Exhaustive Bassi Boolean analysis (every face, every direction)
- [ ] Sangolli full volumetric decomposition + radix sort
- [ ] Add `__init__.py` to `backend/geometry/`
- [ ] Add mypy/ruff config and type checking
- [ ] Split `undercut_detector.py` (3,432 lines) into detection + Boolean + feature grouping

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
