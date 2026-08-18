# Archive

Historical planning, audit, and prep material moved out of `docs/` during
the hackathon-submission cleanup pass (2026-08-18) so the top-level `docs/`
folder only holds documents a reviewer actually needs. Nothing here was
rewritten — files were moved as-is, with a short archive note prepended
where a document's claims have since been superseded by shipped code.

| File | What it was |
|---|---|
| `EVIDENCE_CHECKLIST.md` | Internal pre-submission screenshot/metrics checklist from an earlier cycle. |
| `DFM_REPORT_OUTLINE.md` | Original PDF-report structure sketch, written before PDF export existed. |
| `SLIDE_STORYBOARD.md` | Team's pitch-deck plan. |
| `handoff/` | Internal recovery notes from a past pull-direction/undercut debugging session, still cited from `docs/DECISIONS_AND_ALGORITHMS.md`. |

Not moved here despite being historical, because they are still cited by
in-code comments or other kept documents and moving them would leave those
references dangling: `docs/ARCHITECTURE_ROADMAP.md`,
`docs/PARTING_LINE_ALGORITHM_PLAN.md`,
`docs/PARTING_LINE_CORE_CAVITY_AUDIT.md`,
`docs/ENGINE_AUDIT_2026-07-27.md`, `docs/RECOVERY_PLAN.md`. Each already
carries its own "not current status, see IMPLEMENTATION_STATUS.md /
DECISIONS_AND_ALGORITHMS.md" header from when it was written.

For current, authoritative documentation start at the repository
`README.md`.
