# Honesty & Scope Rules — Always Loaded

This rule is NOT path-scoped. It applies to EVERY interaction.

## Authority Table — One Source of Truth Per Topic

| Topic | Authoritative Source | Why |
|---|---|---|
| Exact current code behavior | Actual source files | Code is truth |
| What's implemented vs planned | `docs/IMPLEMENTATION_STATUS.md` | Self-declared truth source |
| Testing approach | `tests/` directory + `tests/pytest.ini` | Matches actual layout |
| Domain concepts | `understand.md` Parts 1–2 | Most complete domain breakdown |
| Research paper fidelity | `Engine.md` + `IMPLEMENTATION_STATUS.md` | Paper content + honest gaps |
| Demo narration / what NOT to claim | `docs/DEMO_SCRIPT.md` | Has explicit "claims to avoid" |
| Background/planning docs | `README.md`, `understand.md` | Superseded — use for color only |

When docs contradict each other, defer to **actual source code**, then `IMPLEMENTATION_STATUS.md`, then everything else.

## Claims to Avoid (from DEMO_SCRIPT.md)

Do NOT say or write:
- "The final parting line is implemented." (candidate/foundation, not final-optimized — Hou global optimization is still planned)
- "The AI agent uses LangChain." (it doesn't — `backend/agent/providers.py` calls each provider's native SDK directly; `langchain`/`langchain-openai` stay pinned in `requirements.txt` but unused, same as `reportlab`)
- "The AI agent has been verified across all its providers." (only Gemini has been live-tested end-to-end, 2026-07-28; Anthropic/OpenAI/Grok are structurally verified against real SDK signatures and covered by mocked-provider unit tests, but no live call has been made against any of the three — no API key was available for them)
- "The agent supports a conversational chat interface." (only `POST /agent/analyze`'s single-shot sweep is implemented; a streaming `/agent/chat` endpoint was scoped in the roadmap but not built)
- "PDF report export includes a screenshot or AI agent narrative by default." (both are opt-in query/body params; the report is always generatable without either — see `backend/report/pdf_export.py`, implemented and verified 2026-07-29)
- "This is a full Bassi Boolean decomposition for every face and every direction."
- "This is full Sangolli volumetric decomposition."
- "Core/cavity solid split follows the exact 3-D parting surface." (as of Stage 2b, 2026-07-28, it does not — the real `BRepFill_Filling` parting surface is confirmed topologically invalid on both real parts via `BRepCheck_Analyzer`, unfixable by `ShapeFix`/`Sewing`. The Boolean split uses a separate, labeled planar approximation instead — `CoreCavitySolidResult.split_tool_kind="planar_approximation"`. It IS verified `split_ok` with 2 solids + a reloadable STEP export on **both** `Part1.stp` and `Part3.stp` — see `CHANGELOG.md` "Stage 2b" — but never claim the exported solids follow the exact candidate parting-line curve/surface shown elsewhere in the UI.)
- "The side-core generator decides the tooling mechanism." (`backend/geometry/side_core.py` answers only "what volume must retract, and along which direction" — it never decides lifter vs. slide vs. collapsible-core, see roadmap §4.3 Q4/§4.6. As of S4.3 (2026-07-29) it DOES handle multiple/grouped features — see below — so don't undersell that half of the old claim either.)
- "Individual per-feature side-core volumes can be summed to get total tooling volume removed." (S4.3, 2026-07-29: nearby features' local sweep footprints can physically overlap — measured ~128mm3 of real overlap across 4 feature pairs on Part1 — so summing `SideCoreResult.side_core_volume_mm3` across features sharing a half double-counts that overlap. Only `combine_side_cores_per_half()`'s fused-then-cut-once result is volume-conserving.)
- "A side core (or combined multi-feature side-core body) is always a single connected solid." (Confirmed NOT always true: Part1 feature 0's own side core is a genuine 5-piece disconnected compound from a non-convex 11-face Boolean region, and the S4.3 combined per-half body inherits that plus further fragmentation — 6 pieces total on Part1's real case. Volume still conserves; only the solid count varies. This is real geometry, not a bug.)

## Correct Phrasing

Instead say:
- "Parting-line candidate/foundation overlay exists; final optimized parting line (full Hou global optimization) is next."
- "Core/cavity is a real Boolean solid split (`split_core_cavity_solids()`) plus AP214 STEP export (`export_mold_halves()`), not just face classification — verified `split_ok` with exactly 2 solids and a STEP file that reloads with 2 solids on both `Part1.stp` and `Part3.stp`. The Boolean tool is a labeled planar approximation (`split_tool_kind`), not the real 3-D parting surface, which is topologically invalid on both parts and unfixable by standard OCC healing."
- "The AI agent layer (`backend/agent/`) is implemented — a provider-agnostic tool-calling agent (Gemini/Anthropic/OpenAI/Grok) driving the same deterministic geometry engine used elsewhere in this app. Gemini is live-verified end-to-end against real Part1.stp geometry; Anthropic/OpenAI/Grok are structurally verified but not yet live-tested."
- "The current Bassi adaptation uses candidate search plus selective swept Boolean refinement."
- "The current Sangolli adaptation performs feature-level grouping and typing on detected undercut regions, not full-part volumetric decomposition."
- "PDF report export (`backend/report/`) is a pure presentation layer over already-computed analysis results — it recomputes nothing, and aggregates every warning from every source rather than dropping any. Screenshot embedding and AI agent narrative inclusion are both opt-in; the report is always generatable without them."
- "The side-core generator (Bosch criterion #5) produces one side-core solid for the single highest-confidence critical feature, Boolean-subtracted from its containing mold half and exported as a third AP214 solid — verified end-to-end on both real parts. It does not group multiple features or select a tooling mechanism."

## When Generating Documentation or Reports

Always check the actual state of:
- `backend/agent/dfm_agent.py` / `tools.py` / `providers.py` — read them directly rather than assuming from a remembered summary; confirm which providers have actually been live-tested (check `CHANGELOG.md`'s most recent agent-layer entry) before claiming verification for a provider other than Gemini.
- `backend/geometry/core_cavity.py` / `side_core.py` — both have grown well past their original scope; read them directly rather than trusting a remembered line count, since they change as work continues.
- `data/parts/` — `Part1.stp` and `Part3.stp` are the two real fixtures (there is no `Part2.stp`; an earlier naming mix-up was resolved in Phase 0 — see `TODO.md` item F1).

If in doubt, read the file before making claims about it.

## SUBMISSION_REPORT.md Warning

The current `docs/SUBMISSION_REPORT.md` marks "Main Parting Line Creation" and "Core and Cavity face distinction" as "Complete" in the Level 1 Evaluation Matrix. These claims should be qualified before final submission.
