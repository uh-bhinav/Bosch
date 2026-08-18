# TODO — DfM Agent

> **Remaining meaningful work only.** This file used to carry the full,
> dated execution history for every phase (React migration, parting-line
> v2 rebuild, agent layer, etc.) — that history is preserved in
> `CHANGELOG.md`, which is append-only and authoritative for "what was
> done and when." This file now lists only what is genuinely still open,
> condensed during the hackathon-submission cleanup pass (2026-08-18).
>
> Current state: `STATUS.md`. Architecture/algorithm rationale:
> `docs/DECISIONS_AND_ALGORITHMS.md`.

## Before presenting to a panel

- [ ] **Pull-direction search timing risk.** `optimize_mold_direction(Part1.stp)`
      was measured at ~29.6 minutes in one real run (2026-08-16),
      attributed to per-direction OCC Boolean-retry cost variance across
      the 18 principal/diagonal directions D-048 always Boolean-refines —
      not candidate-pool size (Part1 +Z's real pool is 68 faces against an
      80 budget, zero truncation). A ~15s run was also observed once in a
      "calm environment" before this rework, which points toward
      environmental/OCC-retry variance rather than a structural
      regression, but that is not proven. **This is the single largest
      risk to a live, undelayed demo.** Either instrument per-direction
      Boolean wall time to root-cause it, or pre-run the analysis on the
      demo part(s) before presenting and rely on cached/known-good timing.
- [ ] Part3 has not been live-timed for the same risk — only Part1 was
      measured on 2026-08-16.
- [ ] Part1's evidence-driven optimizer winner is a 45° diagonal
      `(-0.707, 0, 0.707)`, not `+Z` — `evidence_tier=verified_acceptable`,
      0% confirmed undercut, vs. `+Z`'s 4 Boolean-FAILED faces
      (manual-review). This is a product decision, not a bug: does the
      demo present the optimizer's genuine best-evidence answer, or is a
      principal-axis pull expected regardless? Decide before demoing so
      the presenter isn't surprised live.

## Known open engineering items (not demo-blocking)

- [ ] Milestone 5 (pull-direction): Docker regression matrix comparing
      `optimize_mold_direction()` on both real parts against the
      pre-hierarchical-search baseline (best direction, score, Boolean op
      count, wall time) — not yet run.
- [ ] Broader mock-test hygiene audit: confirm every mock-based
      `PartGeometry` test that calls `detect_undercuts()`/
      `optimize_mold_direction()` sets `boolean_refine=False` explicitly.
      Known call sites are already fixed; a full audit pass is not done.
- [ ] Volume conservation on the solid split is ~4%, not the originally
      -targeted 2% (tolerance raised and documented — not a correctness
      bug). Open: whether tuning the Splitter step's own fuzzy tolerance
      (separately from the Cut step's) closes the gap.
- [ ] `docs/DECISIONS_AND_ALGORITHMS.md` write-ups for D-061 (adaptive
      ray-based sweep verification) and D-062 (downstream feasibility
      gate) are referenced but not fully written up.
- [ ] `frontend-web/` F7+: per-tool independent run workflows in Expert
      mode (running Direction/Parting-Line/Core-Cavity individually rather
      than only through the one Guided/Manual orchestration call) — not
      started.

## Explicitly deferred (not planned for this submission)

- [ ] Exhaustive Bassi Boolean analysis (every face, every direction).
- [ ] Full Sangolli volumetric decomposition + radix sort.
- [ ] Synthetic known-answer geometry fixtures beyond `UC1–UC5` (most unit
      tests still use OCC mocks, not a fixture with a provably-correct
      answer).
- [ ] Real-OCC integration suite in CI (no CI is configured at all —
      intentional for this hackathon submission, see README).
- [ ] Performance budgets enforced in code (currently observed/reported,
      not gated).
- [ ] Production Docker build (multi-stage, no source mounts, health
      checks) — current Docker setup is dev-oriented and Streamlit-only;
      see `STATUS.md` Infrastructure.
- [ ] `mypy`/`ruff` config and type checking.
- [ ] Splitting `undercut_detector.py` (~4,630 lines) into smaller modules.
- [ ] Side-action tooling-mechanism selection (lifter vs. slide vs.
      collapsible core), a conversational agent endpoint, authentication,
      multi-user architecture — out of scope by explicit project decision,
      not partially built. See `STATUS.md` "Intentionally Out of Scope."

## Done

Everything else on the original, much longer version of this file —
STEP loading, draft analysis, undercut detection, direction optimization,
the `parting_line_v2` rebuild, mold orchestration (C1–C18A, O1–O3), the
AI agent layer, PDF export, and the `frontend-web/` React UI (F0–F6) — is
implemented and described in `STATUS.md` (current state) and
`CHANGELOG.md` (how it got there). Nothing above this section was
silently dropped; it was moved, not deleted — see `CHANGELOG.md` for the
full dated record.
