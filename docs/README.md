# Documentation Index

Start at the repository root `README.md`. It covers setup, running the
demo, and the panel walkthrough. The documents here go deeper on specific
topics.

| Document | Purpose |
|---|---|
| `IMPLEMENTATION_STATUS.md` | Current truth source for what's implemented, approximate, or planned. |
| `DECISIONS_AND_ALGORITHMS.md` | Architecture decisions and the algorithm choices behind the geometry engine, with evidence. |
| `DEMO_SCRIPT.md` | Step-by-step live demo script, including an explicit "claims to avoid" list. |
| `SUBMISSION_REPORT.md` | Original Level 1 submission report. Carries a correction note at the top — two of its evaluation-matrix claims are now known overstated; see `IMPLEMENTATION_STATUS.md` for accurate current status. |
| `ARCHITECTURE_ROADMAP.md` | Original phased specification. Describes *planned* work — where it disagrees with `IMPLEMENTATION_STATUS.md` about current state, `IMPLEMENTATION_STATUS.md` wins (says so in its own header). Still cited from code comments, kept in place. |
| `PARTING_LINE_ALGORITHM_PLAN.md`, `PARTING_LINE_CORE_CAVITY_AUDIT.md` | Companion planning/audit pair behind the `parting_line_v2` engine rebuild. Still cited from code comments, kept in place. |
| `ENGINE_AUDIT_2026-07-27.md`, `RECOVERY_PLAN.md` | Diagnosis record for an earlier engine rebuild. Both self-mark as historical (not current status) in their own headers. |
| `archive/` | Superseded planning/prep material (evidence checklist, report outline, slide storyboard, debugging handoff notes) moved out of the way but not deleted. See `archive/README.md`. |

Recommended reading order for a reviewer: root `README.md` →
`DECISIONS_AND_ALGORITHMS.md` → `IMPLEMENTATION_STATUS.md` → source code.
