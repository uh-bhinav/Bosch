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
- "The final parting line is implemented."
- "Core/cavity extraction is implemented." (face classification exists; solid split does not)
- "The LangChain agent is implemented." (`backend/agent/dfm_agent.py` and `tools.py` are empty files)
- "PDF report export is implemented." (reportlab is in requirements but never imported)
- "This is a full Bassi Boolean decomposition for every face and every direction."
- "This is full Sangolli volumetric decomposition."

## Correct Phrasing

Instead say:
- "Parting-line candidate/foundation overlay exists; final optimized parting line is next."
- "Core/cavity face classification is implemented; full Boolean solid split is Level 2."
- "The AI agent layer is planned; the infrastructure (tool-callable functions, agent context strings) is ready."
- "The current Bassi adaptation uses candidate search plus selective swept Boolean refinement."
- "The current Sangolli adaptation performs feature-level grouping and typing on detected undercut regions, not full-part volumetric decomposition."

## When Generating Documentation or Reports

Always check the actual state of:
- `backend/agent/dfm_agent.py` — is it still empty?
- `backend/agent/tools.py` — is it still empty?
- `backend/geometry/core_cavity.py` — is it still face-classification only (140 lines)?
- `data/parts/` — does Part2.stp exist yet?

If in doubt, read the file before making claims about it.

## SUBMISSION_REPORT.md Warning

The current `docs/SUBMISSION_REPORT.md` marks "Main Parting Line Creation" and "Core and Cavity face distinction" as "Complete" in the Level 1 Evaluation Matrix. These claims should be qualified before final submission.
