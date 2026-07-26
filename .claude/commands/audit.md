# /audit — Check claims against actual code

Verify the honesty of project documentation by checking actual file contents:

1. Check `backend/agent/dfm_agent.py` and `backend/agent/tools.py` — are they still empty?
2. Check `backend/geometry/core_cavity.py` — is it still face-classification only?
3. Check `data/parts/` — does Part2.stp exist?
4. Check if `reportlab` is imported anywhere: `grep -r "import reportlab" backend/ frontend/`
5. Check if `langchain` is imported anywhere: `grep -r "import langchain" backend/ frontend/`
6. Compare findings against claims in `docs/SUBMISSION_REPORT.md` and `README.md`.
7. Report any overclaims or stale statements that need correction.

Also update `STATUS.md`, `CHANGELOG.md`, and `TODO.md` if any status has changed.
