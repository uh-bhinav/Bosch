# DfM Agent — Deep Dive Supplement

### Everything `DFM_TECHNICAL_DEEP_DIVE.md` doesn't tell you

---

## 0. Purpose, scope, and methodology

`DFM_TECHNICAL_DEEP_DIVE.md` (25 sections) is an excellent, code-accurate
walkthrough of the **core geometry pipeline**: `step_loader.py` →
`draft_analyzer.py` → `direction_optimizer.py` → `undercut_detector.py` →
`parting_line.py` (v1, briefly) → `core_cavity.py` (face classification +
Boolean split). It is the right document to present that half of the system.

This supplement exists because that pipeline is **not the whole project**.
Reading only the deep dive, a Bosch engineer would not know that:

- The parting-line engine actually running in production is a **5,700-line,
  H0–H7-gated system** (`parting_line_v2/`) the deep dive mentions in one
  paragraph.
- The **demo UI is not Streamlit**. It's a React + Three.js app
  (`frontend-web/`) the deep dive never discusses (its §17 "Frontend Data
  Flow" describes the *legacy, non-demo* UI).
- There is a working **side-core/lifter generator**, a **provider-agnostic
  AI agent** (Gemini/Anthropic/OpenAI/Grok), and a **PDF report builder** —
  three entire subsystems absent from the deep dive.
- The four founding research papers (Bassi, Sangolli, Nee, Hou) were
  **partially implemented and heavily extended**, and one of the four
  (Sangolli's volumetric decomposition) was **explicitly not built at all**.
  The deep dive never compares "what the paper said" to "what we shipped."
- A handful of **root-level docs in the repo are stale** and will actively
  mislead you if you open them expecting current state.

**Methodology.** I read `DFM_TECHNICAL_DEEP_DIVE.md` in full, then fetched
and read directly from `github.com/uh-bhinav/Bosch`: the root `README.md`,
`Engine.md` (the original paper-to-pseudocode mapping), `understand.md`
(the original hackathon problem breakdown), `CLAUDE.md`, `config.yaml`
(full file, all 353 lines), `docker-compose.yml`, `requirements.txt`, and
`Dockerfile.frontend-web`. I cross-checked all of it against your project's
own `STATUS.md`, `CHANGELOG.md`, `TODO.md`, `SUBMISSION_REPORT.md`, and
`docs/DECISIONS_AND_ALGORITHMS.md`.

**What I could not do**: GitHub's `robots.txt` blocks automated access to
directory (`/tree/…`) pages, and I can only fetch a URL that a prior fetch
actually surfaced — I can't guess a path like
`backend/geometry/parting_line_v2/gates.py` and fetch it directly. So for
the nested Python/TypeScript source files (`gates.py`, `ranking.py`,
`mold_orchestration.py`, everything under `backend/agent/` and
`frontend-web/src/`), everything below is reconstructed from your project's
own extremely detailed `CHANGELOG.md`/`DECISIONS_AND_ALGORITHMS.md` entries
(which quote exact function names, config keys, and measured numbers) —
**not** from re-reading the raw `.py`/`.ts` files myself this session. I've
flagged every place where you should pull up the actual file before
presenting it, so you're never caught quoting a number you can't back up
live.

---

## 1. Read this first: documentation drift you must resolve before presenting

Every project this size accumulates docs that fall out of sync with the
code. Here are the specific ones I found — resolve these *before* you're
in front of Bosch, because each is exactly the kind of thing a sharp
reviewer opens first.

### 1.1 The root `CLAUDE.md` is a fossil from day one

I fetched it directly. It says, verbatim: *"Level 1 geometry pipeline is
end-to-end; **AI agent layer and Level 2 solid extraction are in
progress**,"* and its Honesty Rule section says *"Never claim the AI agent
layer is implemented (files are empty)... Never claim PDF export (zero
code exists)... Never claim core/cavity solid extraction."*

None of that is true anymore. Your own `CHANGELOG.md` documents the AI
agent shipping and being live-verified against Gemini (Stage 5,
2026-07-28), the PDF exporter shipping with 18 passing tests the same day
(Stage 6), and the Boolean core/cavity solid split shipping earlier that
same day (Milestone 1.10). `STATUS.md` and `TODO.md` are current
(`STATUS.md` says "Last updated: 2026-08-19"); the root `CLAUDE.md` was
simply never touched again after the initial scaffold.

**Action**: don't open or quote root `CLAUDE.md` in front of Bosch. If
asked "what's the source of truth for current status," the answer is
`STATUS.md` + `CHANGELOG.md` (or `docs/IMPLEMENTATION_STATUS.md`, which
`README.md`'s own docs index calls "the current truth source"), not
`CLAUDE.md`.

### 1.2 `SUBMISSION_REPORT.md` flags its own two claims as overstated

It carries a correction note at the very top (added during the
2026-08-18 cleanup pass) saying its evaluation matrix's "Complete" labels
for parting line and core/cavity overstate reality, and that the whole
report predates `frontend-web/`. If you're pulling talking points from it,
pull from `README.md` §17 ("Known limitations") and
`docs/IMPLEMENTATION_STATUS.md` instead — those are the maintained,
current sources.

### 1.3 `requirements.txt`, as currently committed, doesn't list the AI-agent SDKs

I fetched it directly (46 lines). It lists `fastapi`, `pydantic`,
`uvicorn`, `numpy`, `pyvista`, `streamlit`, `plotly`, `reportlab`,
`networkx`, `pytest`, etc. — but **no `openai`, `anthropic`, or
`google-genai` package**. Your Stage 5 CHANGELOG entry explicitly records
pinning `google-genai==2.14.0`, `anthropic==0.120.1`, and bumping
`openai` `1.25.0 → 1.109.1` to fix a real `httpx`-compatibility crash.
Either that update never landed in `requirements.txt` (a real gap — a
fresh `pip install -r requirements.txt` would leave the agent layer
unimportable) or it landed somewhere I couldn't see. **Verify this one
directly with `pip list` inside the actual environment before your demo**
— if the packages are genuinely missing from the pinned file, a clean
clone won't have a working agent layer.

### 1.4 The `parting_line.engine` config flag vs. what actually runs — read this carefully

This is the single most likely "gotcha" question a Bosch reviewer asks,
so get the nuance right.

`config.yaml` (verified, exact text):

```yaml
parting_line:
  # Which engine runs. v1 stays the default until v2 wins or ties on every
  # corpus part (docs/PARTING_LINE_ALGORITHM_PLAN.md, P6 cutover). v1 is
  # frozen -- bug fixes only -- so this stays a genuine A/B.
  engine: "v1"   # v1 | v2
```

Read in isolation, this says v1 is what runs. But `STATUS.md`'s own module
table calls `parting_line_v2` **"Current parting-line engine — rebuilt...
to replace the original `parting_line.py`"** and calls v1 **"superseded...
but retained."** And `CHANGELOG.md`'s Phase C14 entry (2026-08-17) is
unambiguous about what the actual production orchestration calls: *"New
module `mold_orchestration.py`, one entry point
`resolve_winning_direction_mold(part, direction_result, ...)`...
`analyse_parting_line` for the winning direction."*

`analyse_parting_line` is v2's own top-level function
(`parting_line_v2/engine.py`) — it is named and referenced that way in
dozens of `DECISIONS_AND_ALGORITHMS.md` entries (D-043's "Round 1.5 in
`analyse_parting_line`", D-048's "wraps `analyse_parting_line`", etc.).

**The reconciliation, best-evidenced from what I have**: `mold_orchestration.py`
calls `analyse_parting_line` (v2) **directly and unconditionally** — it
does not appear to read `config.parting_line.engine` at all. That
orchestrator is what `/core-cavity` calls (the one endpoint
`frontend-web/`'s "Run Full Analysis" button hits), so **the real demo
path always runs v2**, regardless of what the YAML flag says. The YAML
flag most likely only still governs the two *standalone*, side-by-side A/B
endpoints — `/parting-line` (v1, via `parting_line.py`'s own
`detect_parting_line_candidates`) and `/parting-line-v2` (v2, direct) —
which exist for comparison/experimentation and are not part of the guided
demo flow.

**Before you present this**: open `backend/geometry/mold_orchestration.py`
and confirm it never branches on `settings.dfm.parting_line.engine`, and
open `backend/api/main.py` to confirm `/parting-line` and `/parting-line-v2`
are in fact two separate routes. If that holds, say exactly this to Bosch:
*"the config flag is a leftover A/B switch for two experimental endpoints;
the one authoritative pipeline (`mold_orchestration.py`, used by the demo)
always runs the v2 engine."* That is a much stronger, clearer story than
leaving the YAML comment to speak for itself.

### 1.5 File line counts in the deep dive may be stale — and stale from the *same* source

The deep dive's §4 file tree lists `frontend/app.py` at **"3,905 lines"**.
Root `CLAUDE.md` — the stale file from §1.1 — states the *exact same*
number. `STATUS.md`, written later, lists `frontend/app.py` at **"~6,160
lines"**. This strongly suggests the deep dive's line-count table was
copied forward from `CLAUDE.md`'s early snapshot rather than freshly
measured, despite the deep dive's own claim to have traced everything
"directly from the source code."

**Action**: before quoting *any* line count to Bosch, run `wc -l` on the
actual file. Don't trust either document's number verbatim. This is a
good live-demo moment, too — "let's check how big this file actually is"
takes five seconds and immediately demonstrates you're working from real
code, not a stale doc.

### 1.6 `docs/PARTING_LINE_ALGORITHM_PLAN.md` and `docs/PARTING_LINE_CORE_CAVITY_AUDIT.md`

`README.md`'s own documentation index calls these "companion planning/audit
pair" documents "still cited from code comments" — the `config.yaml`
excerpt above literally references `docs/PARTING_LINE_ALGORITHM_PLAN.md`
§13 and P6 by name. If you want to explain *why* v2 exists at all (not
just what it does), that audit document is the place — it's the one that
catalogued v1's structural defects (see §3.1 below for the summary) before
any v2 code was written. It wasn't in your uploaded materials; check it in
the repo (`docs/`) directly if you want the original defect catalogue
verbatim rather than my summary of it.

---

## 2. The four founding papers: what they specified vs. what actually shipped

This is the material in `Engine.md` (the original paper-to-pseudocode
mapping document, written to justify the approach before any code was
written). It is **not referenced anywhere in the technical deep dive**,
and it's exactly the kind of thing a Bosch reviewer familiar with the
literature will ask about: *"your README says you implement Bassi/Sangolli/
Nee/Hou — show me where."* The honest answer for each paper is "we
implemented the core mechanism, then found real problems with the paper's
own simplifying assumptions on real automotive geometry, and built our way
around them." That's a *better* answer than pretending the code is a
literal transcription — but only if you can articulate the divergence.

### 2.1 Bassi et al. (2010) — pull-direction search

**Paper's algorithm** (from `Engine.md`'s own pseudocode): for each
candidate direction, sweep every face along it by 2× the bounding-box
diagonal, Boolean-subtract the swept solid from the part
(`BRepAlgoAPI_Cut`/`BOPAlgo`), and if the result shows interference, count
the face as inaccessible and accumulate an interference volume. Score =
`inaccessible_count + undercut_volume`. Pick the minimum.

**What actually shipped, and why it grew**:

| Paper's assumption | What broke on real parts | What was built instead |
|---|---|---|
| Sweep + Boolean-check *every* face for *every* candidate | On a 311-face part × 54 candidates, that's tens of thousands of expensive Boolean ops — impractical | A cheap **draft + concave-edge heuristic** pre-filters candidates first; only survivors get the expensive Boolean check (the "cheap stage" → "Boolean pruning gate" → "Boolean-refined stage" pipeline, deep dive §8) |
| Boolean ops are reliable if you just call them | Repeated Boolean calls in the *same* OCC process were empirically found to degrade later results | Every surviving candidate's Boolean check runs in a **fresh OS subprocess** (O22 isolation, `undercut_isolation_worker.py`), up to `direction_parallelism=8` concurrent |
| A sweep direction/distance is unambiguous | A face nearly tangent to the pull direction (`g≈0`) produces a mathematically ill-posed sweep — one real bug (D-042) returned the **entire part's volume** as "interference" for such faces | Faces with `|g| < boolean_near_zero_g_threshold (1e-6)` are excluded from the sweep entirely and reported `boolean_not_applicable`, not silently swept anyway (D-046); a separate **ray-cast pre-verification** (D-061) finds a safe, non-degenerate sweep distance before the expensive Boolean runs at all |
| Score = simple sum, pick the minimum | An *unverified* candidate's raw score could numerically beat a *verified* one, silently reporting an unconfirmed answer as the optimum | **Evidence tiers** (`unverified` / `verified_undercuts_present` / `verified_acceptable`) are compared *before* score — an unverified candidate can never win regardless of its number (D-048) |
| Direction-finding is independent of parting-line generation | A direction with zero undercuts can still have **no valid parting line** at all | `optimize_mold_direction` now calls into `parting_line_v2`'s own feasibility gate before declaring a direction the winner (D-062) — direction search and parting-line generation are now mutually gating, something the paper never considers |

The one-paragraph version for Bosch: *"Bassi's core mechanism — sweep,
Boolean-subtract, measure interference — is exactly what
`_swept_face_interference_volume` still does. Everything else in
`direction_optimizer.py`'s 2,690 lines is infrastructure we had to build
because that mechanism, taken naively, is too slow and too fragile to run
literally 'for every face, every direction' on real automotive parts."*

### 2.2 Sangolli et al. (2021) — undercut feature recognition

**Paper's algorithm**: parse STEP → volumetric decomposition of the solid
into convex sub-volumes (Boolean-based splitting) → per-sub-volume feature
classification via normals/edge-convexity/directionality → **radix sort**
features by release direction and type → output per-feature location,
depth, type, release direction.

**This is the one paper with a real, disclosed, and explicitly-scoped-out
gap**: `TODO.md`'s "Explicitly deferred" section lists, verbatim, **"Full
Sangolli volumetric decomposition + radix sort"** as out of scope for this
submission — not partially built, not attempted. There is no
convex-sub-volume decomposition anywhere in `undercut_detector.py`, and
no radix sort anywhere in the codebase.

**What was actually taken from Sangolli and built**: the *edge-convexity*
piece. `step_loader.py` computes convexity (convex / concave / tangent)
for every manifold edge at load time — this is genuinely Sangolli's
"classification via edge convexity" idea, just applied per-face-and-edge
rather than via a volumetric split. It's used two ways: (1) suppressing a
proxy undercut candidate whose bounding edges are *all* convex/tangent
(can't be a genuine pocket — a curved boss, not a trap), and (2) as the
concave-edge half of the "accessibility risk" heuristic that feeds
candidate generation for Boolean verification. Per-feature output
(location, depth, type, release direction, confidence) is produced too —
just via a completely different mechanism: BFS grouping of Boolean-
confirmed faces by adjacency (`_group_undercut_faces_with_boolean_proximity`),
not a radix sort over decomposed sub-volumes.

**The talking point**: *"We took Sangolli's insight — draft angle alone
can't tell you if something is a real pocket, edge convexity can — and
built it into the pre-filter. We did not build the full convex
decomposition + radix sort pipeline; that's an explicit, disclosed scope
cut, not an oversight, and it's still on the roadmap."*

### 2.3 Nee et al. (1998) — parting-line silhouette detection

**Paper's algorithm**: fix direction, project the part onto the
perpendicular plane, find silhouette edges (visibility changes between
adjacent faces), build a vertex/edge graph, extract **all** closed loops,
and select the best by (in order): (1) largest projected area, (2) fewest
sharp turns / highest flatness, (3) avoidance of critical regions.

**v1 (`parting_line.py`) is the direct, literal attempt at this** — and
its history is a case study in how many ways a "simple" graph algorithm
can go wrong on real geometry. Three of the bugs your own CHANGELOG
documents are worth knowing cold, because they map exactly onto Nee's
three-part selection rule:

- **Bug H**: the "largest projected area" criterion — Nee's own **first
  and primary** rule — was ranked only **5th** in v1's actual sort key.
  The system was choosing small, tidy hole-rim loops over the true main
  silhouette because they scored better on secondary criteria. Fixing the
  ranking order took Part1's silhouette-coverage measurement from 27.6%
  to 94.9% overnight — same code, same geometry, just the criteria back
  in the order the paper actually specifies.
- **Bug A**: the closure step *claimed* success (`closure_guaranteed=True,
  closure_error_mm=0.0`) while silently leaving a real **17.35mm gap** in
  the curve. The function computed the correct closing path and then threw
  it away before returning.
- **Bug B**: "traverse the graph to extract closed loops" quietly
  degraded to a non-backtracking greedy walk once the graph got large,
  which cannot find a true closed loop that a real search would. It took
  an exact search with graph contraction (collapsing degree-2 chains into
  hyper-edges) to actually deliver on this step of the paper.

**v2 goes structurally beyond Nee's formulation.** Nee's model implicitly
assumes a single closed loop is the answer. That's false for any part with
a through-hole: cutting only the outer rim leaves the top face still
connected to the bottom face *through the hole wall*. v2 formalizes this
as **Γ = a disjoint union of up to 4 simple closed curves** (D-007), a
generalization the paper doesn't state and your team discovered was
necessary while building fixture F9 (a box with a through-hole).

### 2.4 Hou et al. (2018) — parting-curve refinement

**Paper's algorithm**: build a visibility map, generate candidate curves
from silhouette edges, model them as a weighted graph (weight = length +
curvature penalty + flatness + distance-from-critical-region), run a
shortest-path/min-cost-closed-loop search, then B-spline-fit the winner
for smoothness.

**v1's "Hou-like" element is much thinner than it sounds**: it's Chaikin
corner-cutting subdivision (8 iterations) applied purely for **display**
smoothness — not a graph-weighted optimization at all. Worse, this
smoothed curve was never re-validated against the real B-Rep surface — the
audit's "levitating parting line" defect (RC-7): a curve with no OCC
backing, whose drift from the actual geometry was never measured.

**v2 is much closer to Hou's spirit, but via a different algorithm**: it
doesn't run a single shortest-path search. It builds the graph, strips
non-cyclic ("dangling") material via 2-core reduction, **enumerates every
simple cycle** (via a fundamental cycle basis, or optionally the more
expensive Johnson's algorithm), and then picks among the *entire*
candidate set with a **lexicographic multi-tier ranking** (§3.6 below) —
generate-and-filter-and-rank, not Hou's single-objective shortest path.
Whether to use the cheaper basis or the more complete Johnson enumeration
was itself a measured decision (D-017): Johnson changed **zero real-part
outcomes** while costing up to 22× more candidates and 10× more runtime,
so the basis stays the default and Johnson is opt-in
(`enumeration_strategy: "basis" | "johnson"`).

Two things Hou's paper covers that v2 deliberately does **not** implement:
B-spline fitting of the final answer (smoothing only ever happens for
*display*, gated behind `allow_smoothed_as_geometry` which **defaults to
false**, specifically so the RC-7 "levitating curve" defect can never
silently recur), and the "distance from critical/cosmetic regions" cost
term — the project has never had a data source telling it which surfaces
are cosmetically critical, so this term is honestly absent rather than
faked.

---

## 3. The parting-line-v2 engine — the largest undocumented subsystem

This is roughly **5,700 lines** across ten files
(`types.py`, `contracts.py`, `track_a.py`, `track_b.py`, `graph.py`,
`stitch.py`, `regions.py`, `gates.py`, `ranking.py`, `engine.py`) — bigger
than the entire undercut detector, and it is the module with the single
richest engineering history in your `DECISIONS_AND_ALGORITHMS.md` (60+
dated decision entries). The technical deep dive gives it one paragraph
in §13. This section is the missing explanation.

### 3.1 Why it exists at all

`docs/PARTING_LINE_CORE_CAVITY_AUDIT.md` catalogued the v1 engine's
structural defects (referenced as "RC-1" through "RC-7" throughout
`CHANGELOG.md`). The two worth knowing by name:

- **RC-4**: v1 "does not fail loudly." Fed a shape whose silhouette lives
  entirely inside a curved face's *interior* (a sphere, a cylinder swept
  perpendicular to the pull axis — no qualifying B-Rep *edge* exists at
  all), v1 doesn't error — it returns `status = ok` with 0.0% coverage. A
  confident wrong answer is worse than a stated failure.
- **RC-7**: the "levitating parting line" — v1's final displayed curve is
  unconstrained Chaikin-smoothed output with **no OCC backing whatsoever**.
  There is no edge or face it can be checked against, so its geometric
  drift from the real part was never measured in the feature's entire
  life.

v2 is the structural fix for both, encoded at the **type level**, not just
as a runtime check.

### 3.2 The core data-model guarantee: no curve segment can exist without provenance (D-001)

```python
CurveSegment  # cannot be constructed without a `backing`
  EdgeBacking(edge_id, t_start, t_end)   # a real OCC edge curve, C(t)
  FaceBacking(face_id, uv_points)        # a real OCC face surface, S(u,v)
```

There is no `backing: None` option. This is the direct structural answer
to RC-7: a segment that can't be evaluated against real OCC geometry
**cannot be built** — H0 (below) doesn't have to catch it after the fact,
because the type system already refused to create it. Worth walking a
Bosch engineer through this specific design choice — it's a genuinely
elegant "make the bug unrepresentable" pattern, and a good example of
learning from a production defect at the architecture level rather than
patching around it.

A second, related type-level rule (D-002): **there is no `confidence` or
`readiness` field anywhere in v2**, and a test enforces this. No labelled
outcomes exist to calibrate a probability against, so no fabricated
confidence score is allowed to exist either — this directly targets a
different v1 defect class the audit found (a numeric "confidence" that
looked authoritative but wasn't backed by anything measurable).

### 3.3 Track A and Track B — the two silhouette-detection mechanisms

**Track A** (edge-local, closest to Nee's original method): tests each
manifold edge's two adjacent faces' signed dot products `g_a = n_a·d`,
`g_b = n_b·d`. The critical correction here (D-005) is that the test must
be **inclusive** — an edge is on the silhouette if `0 ∈ [min(g_a,g_b),
max(g_a,g_b)]`, *not* the naive `g_a · g_b < 0`. Across a sharp edge the
normal is set-valued (it sweeps the arc between the two face normals), so
if either endpoint is exactly zero the silhouette still passes through
that edge — the strict-product test misses this and, on a plain cube, it
literally finds no silhouette on the top rim (`1 × 0 = 0`, not negative).

**Track B** (face-interior, the mechanism Nee's paper and v1 both lack
entirely): for a face where the silhouette runs through the *middle* of a
curved surface — a sphere's great circle, a cylinder's rulings when pulled
perpendicular to its axis — there is no B-Rep edge to test at all. Track B
marches a grid across the face's UV domain (8×8 up to 256×256,
`uv_grid_min`/`uv_grid_max`), finds where `g(u,v) = n(u,v)·d` changes sign,
and Newton-iterates to the exact zero-crossing (`newton_max_iterations: 8`,
`newton_tolerance: 1e-9`). This is what makes fixtures F2–F5 and F17 (a
cylinder ∥ pull, a cylinder ⟂ pull, a sphere, a cone, a lofted barrel) go
from v1's confident "0.0% coverage, no error" to v2's honest, exact
analytic answers (a sphere's great circle to `|z| < 1e-6`, `r = 20.000000`
exactly).

Two Track-B refinements worth knowing: the boundary termination originally
stopped at the last marching-squares grid point classified "inside,"
undershooting the true trim boundary by up to 0.14mm — fixed by bisecting
against the real trim classifier (D-023). And the projector used to
*verify* that fix (`GeomAPI_ProjectPointOnSurf`) turned out to silently
restrict its own search to the surface's declared `Bounds()`, not the
face's actual (larger) trim extent — a second, independent bug in the
*checker itself*, not the thing being checked (D-024). This pair is a
genuinely good "even your test harness can have bugs" story for Bosch.

### 3.4 Graph construction and cycle enumeration

Silhouette segments are welded into a graph (endpoint tolerance,
`weld_tolerance_rel`, scaled by the part's own bounding-box diagonal — no
absolute millimeter constant anywhere, deliberately, because a hardcoded
`search_edge_limit=22`/`max_search_states=75000` silently degrading v1's
own search was exactly the kind of invisible fallback this rebuild set
out to eliminate).

**A closed circular edge is a graph self-loop of degree 2, not 1** (D-006)
— textbook graph convention, but easy to get wrong, and getting it wrong
silently deletes every hole rim and cylinder rim from the candidate pool
during 2-core pruning (degree-1 nodes are pruned as dangling ends). This
single convention fix is what made fixtures F2, F5, and F9 (a hole rim
that must survive) go from "no feasible candidate" to correct.

After 2-core reduction (which is provably lossless for cycle content —
verified directly, see D-028's bypass experiment below), cycles are
enumerated either via `networkx.cycle_basis` (default,
`enumeration_strategy: "basis"`) or, opt-in, a bounded Johnson's-algorithm
enumeration (`"johnson"`, capped by `mu_max_for_johnson: 12`). Multi-curve
answers — a candidate that's really an outer loop *plus* a hole-rim loop —
are formed as **subsets** (not just pairs) of up to `max_loop_union_size:
4` independently-enumerated cycles, tried smallest-subset-first (a
descending-size bug that starved smaller, correct subsets of the candidate
budget was caught and fixed, D-019).

### 3.5 The H0–H7 hard-gate system

This is the part of the codebase closest to a formal specification, and
it's completely absent from the technical deep dive. Every candidate loop
must pass all of these, in order, before it's even eligible for ranking.
All thresholds below are the *exact* values from `config.yaml`.

| Gate | What it checks | Config key(s) | Notes |
|---|---|---|---|
| **H0** | *On-surface invariant.* Every point on the curve must be recoverable from real OCC geometry within tolerance — `p = C(t)` for an edge point, `p = S(u,v)` for a face point. Sub-checks H0.1 (structural: must have a real `EdgeBacking`/`FaceBacking`, enforced at the type level, D-001) and H0.3 (numeric: projected surface deviation via `GeomAPI_ProjectPointOnSurf`, D-024). | `surface_tolerance_rel`, `edge_tolerance_rel`, `silhouette_error_factor` | Both tolerances are floored and then max'd against OCC's own kernel-declared tolerance for that specific face/edge — never used bare. |
| **H1** | *Closure.* First and last point of the assembled loop must coincide within tolerance. | `closure_tolerance_rel` (×bbox diagonal) | This is the gate Bug A (§2.3) silently bypassed in v1. |
| **H2** | *Simple curve.* The loop must not self-intersect (Jordan-curve requirement, generalized to a disjoint union of simple closed curves per D-007). | — | Purely topological; no numeric threshold. |
| **H3** | *Topological separation.* Cutting the part's face-adjacency graph along Γ must yield **exactly 2** connected components (`separate_surface`, `region_count == 2`). | (fed by `weld_tolerance_rel`/`stitch_snap_tolerance_rel` upstream) | **The primary validity test** — described across dozens of decision entries as "the real test; if H3 and H7 disagree, H3 is right." |
| **H4** | *Orientation consistency.* Within each of the two separated regions, the fraction of face area whose normal faces "the wrong way" for a rigid mold-half pull must stay under a violation ceiling. | `orientation_epsilon` (0.05, per-face slack), `orientation_violation_max` (0.02, i.e. ≤2% area) | **Core-pin** (D-043) and **delegation** (D-044) authorization mechanisms — see §3.7 — can exclude specific, explicitly-authorized face sets from *both* the numerator and denominator here. |
| **H5** | *Undercut-touching check.* If the loop's faces overlap the undercut detector's flagged faces, this does **not** reject the candidate — it emits a `SideActionReferral` (reporting-only). | — | Enforced by an AST-level import test: no module under `parting_line_v2/` may ever import `side_core` — referrals are surfaced, never auto-routed. |
| **H6** | *Non-degeneracy.* Minimum curve length and minimum projected area. | `min_length_rel`, `min_projected_area_rel` (both ×bbox diagonal / diagonal²) | Rules out degenerate zero-length/zero-area loops. |
| **H7** | *Coverage ratio.* Largest loop's projected area ÷ a Cauchy-bound estimate of the part's total projectable area must exceed `κ_min`. | `min_coverage_ratio` (0.50) | Explicitly labeled **provisional, not a manufacturing law** in the config comment. Empirically found to currently reject *nothing* across the real corpus (D-020) — H3/H4/H6 already filter out everything it would have caught. Left in place as a diagnostic, not tightened, because the denominator (`A_cauchy`) itself measurably overestimates by up to 59% on non-convex real parts (D-011, D-019/B-19) — raising the threshold on unreliable data would risk false rejections. |

### 3.6 Ranking — the T1–T7 lexicographic tiers

Once a candidate clears H0–H7, ranking picks among survivors. The deep
dive's own §13 lists this as "coverage ratio, undercut proximity, pull-axis
span, turning excess, and 3D length" (5 criteria) — but `config.yaml`'s
`tier_epsilon` block defines **six** named dimensions, in this exact
order, each with a "tie band" (a difference smaller than the epsilon
counts as a tie and falls through to the next tier — so near-equal
candidates aren't separated by numerical noise):

```yaml
tier_epsilon:
  coverage: 0.01
  undercut_proximity: 0.02
  pull_axis_span_mm: 0.10
  ambiguous_area_fraction: 0.01   # ← missing from the deep dive's own list
  excess_turning: 0.02
  length_3d_mm: 0.50
```

That gives T1 = coverage, T2 = undercut proximity, T3 = pull-axis span,
T4 = ambiguous area fraction, T5 = excess turning, T6 = 3D length — six
tiers. `docs/DECISIONS_AND_ALGORITHMS.md` (D-010) explicitly references a
"T7" as the final decider in a genuine tie case (two candidates — a cube's
top and bottom rim — that tie on every other tier). What exactly T7
compares isn't stated in any doc I have access to; **before you present
this, open `ranking.py` and confirm the seventh tier's exact key** (it's
almost certainly some fully-deterministic tiebreak like candidate ID or
insertion order, so that ranking can never be ambiguous — but confirm the
literal code before you say so out loud).

Note the fourth tier, `ambiguous_area_fraction`, ties directly to the
five-way region-classification model in §3.8 below — it's measuring how
much of the split couldn't be confidently called cavity or core.

### 3.7 Core-pin and delegation — two authorization mechanisms not mentioned anywhere in the deep dive

Both exist to solve the same category of problem: **some real geometry
genuinely cannot be released by a single rigid mold-half pull, and no
amount of better silhouette detection changes that** — the fix has to be
mechanical (a moving core pin, a slide, a lifter), which is knowledge no
purely geometric algorithm can derive on its own. Rather than silently
ignore this class of feature or silently force a wrong answer, v2 lets a
human engineer **explicitly authorize** specific faces as handled by a
named secondary mechanism, and only then adjusts the gates.

**Core-pin / tooling-split (D-043)**. Part3's central bore is exactly
coaxial with the pull direction — `g ≡ 0` across its entire length, so it
has no `g=0` crossing anywhere (Track B needs a sign *change*; a constant
zero has none) and no natural place for H3 to "cut" it. `CorePinFaceRef`
lets an engineer name that bore face; a five-condition eligibility check
(`check_core_pin_eligibility` — cylindrical, axis-parallel within
`core_pin_axis_angle_tol`, uniformly zero-draft within
`core_pin_uniform_g_max` over the *whole* face, exactly two topological
neighbors, and a valid split parameter inside the face's own extent)
verifies the claim is geometrically sound before a purely **logical,
non-geometric** axial split (`tooling_split_face_ids`) is handed to H3.
Critically, this metadata is kept structurally separate from the real
parting curve (`.segments`/`.loops`) — a rejected earlier design
(`ToolingBacking`, a fourth `CurveSegment` backing kind) would have
polluted length/coverage/turning measurements with a synthetic curve that
has no real manufacturing meaning (no flash risk, no witness mark). The
core-pin split only lets the bore *participate* in H3 — it never
guarantees a Z candidate passes H4 or anything downstream.

**Delegation (D-044)**. `DelegatedSecondaryAction` authorizes a specific,
connected face set as handled by an explicitly named secondary mechanism
(a slide, a lifter — `movement_type` is advisory-only, read by nothing
downstream). Once independently validated (`validate_delegation`: real
provenance present, a genuinely non-parallel movement direction via
`delegation_max_parallel_cos`, structural connectedness, disjoint from the
loop's own real faces), the delegated faces are subtracted from **both**
the numerator and denominator of H4's per-region area sum — so a feature
correctly handled by a side-action mechanism doesn't count against
"orientation consistency," which was only ever meant to test the *primary*
rigid pull. On Part3's real rib lattice, this dropped H4's violation from
7.56% to 0.499% and flipped that candidate to feasible — while the *other*
two real candidates receiving the *identical* delegation stayed correctly
rejected, which is the evidence that nothing was tuned to force a result.

**The honesty boundary, worth repeating verbatim to Bosch**: neither
mechanism ever claims the secondary geometry has been *proven* to
physically release. `DelegationEvidence.geometric_verification` has
exactly one legal value: `"unverified"`. Passing validation proves only
that the *claim* is structurally self-consistent (real faces, real
provenance, a genuinely different movement direction, connected) — never
that a slide or lifter has actually been designed and shown to clear the
part. That distinction is deliberate and load-bearing; don't blur it in
your presentation.

### 3.8 Region classification — the five-state model

`RegionClassification` labels every face one of: `cavity`, `core`,
`split` (the parting curve runs through the middle of this face; its area
is apportioned between sides by real evidence — axial share for a
core-pin split, `mean_g` magnitude ratio for a genuine Track-B split, never
double-counted), `ambiguous` (near-zero mean signed-dot, doesn't touch the
loop — genuinely can't be called either side), or a fifth no-classification-
data state for faces where `normal_valid=False`. This replaced a v1 model
that only had cavity/core and silently rendered everything else as
indistinguishable gray (D-045).

Also worth knowing: this module's own reported `cavity_area_mm2`/
`core_area_mm2` numbers are a **deliberately different convention** from
what H4 itself uses internally for its own violation-fraction math (H4
counts a `split`/tooling-split face's *entire* area toward both sides it
touches; the reporting layer apportions it). Both are correct for what
they define — they're just not interchangeable, and the frontend has an
explicit caption saying so rather than silently picking one (D-045).

### 3.9 Best-rejected candidate exposure (D-049)

When *nothing* passes every gate (Part3 without core-pin/delegation
authorization, for example — 159/310 candidates failing H3, 151/310
failing H4), v2 doesn't just return `regions=None` and leave the viewport
gray. It separately exposes the best-ranked *rejected* H3-passing
candidate's own region classification, with explicit fields
(`best_rejected_candidate_id`, `best_rejected_regions`,
`best_rejected_failed_gate`, `best_rejected_reason`) so the frontend can
show a clearly-labeled "BEST REJECTED CANDIDATE — PREVIEW ONLY" overlay
instead of an unexplained blank viewport. `regions` itself is never
overloaded to mean this — it continues to mean strictly "the accepted
candidate," full stop.

---

## 4. `mold_orchestration.py` — the actual production entry point

Not mentioned anywhere in the technical deep dive, but this is the single
module every real demo click flows through. It exists because, before it,
`backend/api/main.py`'s three call sites (`/core-cavity`,
`/export/mold-halves`, `/export/report`) each independently re-derived the
chain "optimizer → parting line → solid split" with small, drifting
differences — most seriously, a stale re-derivation
(`_resolve_v2_parting_line`) that always called v2 with
`undercuts=UndercutInput.empty()`, even when the winning direction had
real, non-empty undercut evidence available. That's the exact kind of
silent divergence a stateless-backend architecture is supposed to prevent.

Two entry points, one for each pull-direction source:

- **`resolve_winning_direction_mold(part, direction_result, ...)`** — the
  automatic path. Requires `optimal_found=True` from the direction
  optimizer (never proceeds on an unverified "best guess"), re-derives the
  parting line **with the winning direction's own real undercut evidence**
  (fixing the stale-empty-undercuts bug above), splits the solids, and
  selects side-core features from that direction's `optimal_undercuts.
  features` — never from `SideActionReferral`, which stays reporting-only.
- **`resolve_manual_direction_mold(...)`** — the engineer-supplied-direction
  path (from `frontend-web`'s Pull Direction panel). A zero/degenerate
  manual vector now returns HTTP 200 with `orchestration.status =
  "invalid_direction"` rather than an incidental 400 the old code path
  raised — a deliberate, disclosed contract change (C18A).

Both accept optional `precomputed_pl_result`/`precomputed_undercuts`
parameters so a caller that already computed them (for the unconditional
Level-1 face-classification display) can hand them in rather than the
orchestrator silently re-deriving — this is what makes `/core-cavity` and
`/export/report` compute the parting line **exactly once** per request
instead of two or three times with a chance of disagreement (C18A's exact
test: `analyse_parting_line`/`detect_undercuts` call-count proven to be 1,
not 2, via mocks).

A **direction-consistency invariant** is enforced at two points, not just
by construction: `optimal_undercuts.pull_direction` and the re-derived
parting line's own pull direction are both explicitly compared against
`best_direction`, so the orchestration chain can never silently mix
directions between stages — a class of bug that would be very hard to spot
visually (the mesh would still render; the numbers would just be wrong).

---

## 5. `side_core.py` — Bosch criterion #5 (side-actions / lifters)

Also absent from the deep dive except as a file-tree entry. This is the
first and only geometry this project has for "side-action" tooling.

**What it computes**: for the single highest-confidence critical undercut
feature (or, in the multi-feature extension below, every qualifying
feature), a solid representing the volume that must retract, along the
feature's own release direction. Built as a flat, feature-sized planar
Boolean-split tool (reusing the same proven pattern as the main core/cavity
split — see §5.1 below for why), swept along `release_direction`, Boolean-
subtracted from whichever mold half contains it.

**What it explicitly does *not* do, stated three separate times across the
codebase's own comments so no one can miss it**: decide *which kind* of
mechanism releases the feature — lifter, slide, or collapsible core. It
answers "what volume, which direction," never "what hardware."

### 5.1 Two real bugs worth knowing, because they're good "how we found this" stories

- **Footprint sizing** originally used a face's *vertex-only* sampling to
  size the sweep plane — for a curved-edge face, the widest point relative
  to the feature's centroid usually isn't at either endpoint vertex.
  Measured on Part3: vertex sampling gave a 1.50mm radius against the
  face's real bounding-box extent of 36mm — a ~24× undersizing. Switching
  to `Bnd_Box` corner sampling fixed it.
- **Fuzzy-tolerance mismatch**: the Boolean `Common` operation that
  *measures* the side core's overlap and the following `Cut` that
  *removes* it must use the **identical** fuzzy tolerance value — using
  0.01 for one and a "safe-sounding" larger 0.1 for the other measured a
  **37.72% volume-conservation error** even though *both* individual
  Boolean calls reported success. Root cause: at a higher fuzzy value,
  `BRepAlgoAPI_Common` can silently return a smaller or empty result while
  still reporting `IsDone()=true` — so the following `Cut` operates
  against geometry that doesn't match what was actually measured. A
  consistent 0.01 for both measured 0.00–0.02% error across every test.

### 5.2 Multi-feature generalization (S4.3)

The single-feature entry point (`generate_primary_side_core`) stayed
available unchanged; a newer, additive layer
(`select_side_core_features`, `generate_side_cores_for_features`,
`combine_side_cores_per_half`) generates one side core **per qualifying
feature** — every feature measured independently against the same
pristine cavity/core solid (never against a half already cut by an
earlier feature, so results never depend on generation order) — then
combines them into **at most one exported body per mold half**, because
STEP-exporting each feature's side core as a *separate* body double-counts
physical overlap between adjacent features (measured on Part1: ~128mm³
of real overlap across 4 adjacent feature pairs). API surface:
`multi_feature_side_cores`, `side_core_severities`,
`side_core_max_features` query params on `/core-cavity` and
`/export/mold-halves`.

---

## 6. The AI agent layer (`backend/agent/`)

Zero mention in the technical deep dive. This is a real, tool-calling,
provider-agnostic LLM agent sitting on top of the deterministic geometry
engine — reachable via `POST /parts/{filename}/agent/analyze` and (in the
legacy Streamlit UI only) an "AI Agent" tab. **It is not wired into
`frontend-web/` and is explicitly not part of the demo flow** — say this
plainly if asked, since a Bosch reviewer clicking around the React UI will
never find it.

**Providers**: Gemini (default — `gemini-2.5-flash`), Anthropic
(`claude-opus-5`), OpenAI (`gpt-4o-mini`), and Grok (`grok-2-latest`, which
reuses the OpenAI adapter class via Grok's OpenAI-compatible endpoint).
**Only Gemini has been live-verified end-to-end against a real key** —
the other three are structurally verified and unit-tested with mocks, not
live-tested. Say this distinction out loud; don't let "provider-agnostic"
imply all four are equally proven.

**Six tools** wrap the geometry engine (`optimize_pull_direction`,
`analyze_draft`, `detect_undercuts`, and others — exact names/signatures
are in `backend/agent/tools.py`, which I couldn't fetch directly this
session; verify the exact tool list there before quoting it).

**Four "hard rules," enforced structurally, not by convention**:

1. Every tool result is built from a dataclass's own `.to_dict()` — never
   touches an `occ_*` field, so no OCC handle can ever leak into an LLM
   prompt or response.
2. Every geometry call the agent makes passes `mutate=False` explicitly.
3. Face-ID lists returned to the model are capped
   (`max_face_ids_per_tool`, default 25) with an explicit `truncated: true`
   marker rather than silently dropping context.
4. A `_tool_safe` decorator catches every exception from a tool call and
   returns the same structured `{status: "error", code, message,
   recovery_hint}` shape the REST API already uses — a tool failure is
   data the model can reason about, never an unhandled crash.

**Three genuine, disclosed engineering findings** worth using as
"real AI-integration war stories" for Bosch:

- The team's Gemini key had **zero free-tier quota** on the originally-
  planned `gemini-2.0-flash` model (confirmed via a live 429), forcing a
  switch to `gemini-2.5-flash` — the kind of thing you only discover by
  actually calling the real API, not by reading documentation.
- The originally-planned `google-generativeai` package is the **legacy**
  SDK; the actually-maintained one is `google-genai` — again, only
  discoverable by trying to `pip install` it.
- A real, live-verification-caught bug: once the optimizer establishes a
  direction as `"optimal"`, every downstream tool call in the same run
  should keep citing that provenance — but the original code naively
  re-classified "a `pull_direction` argument was supplied" as
  `"user_specified"`, silently downgrading a genuine optimizer result to
  a fabricated user-override label on every propagating call after the
  first. Fixed and locked in with a regression test
  (`test_track_direction_optimal_source_is_not_overwritten_by_propagated_calls`).

**Output contract**: the model's final answer is a structured
`DfMReport`/`DfMFinding` pydantic schema, parsed from plain JSON in the
model's own text output (not a provider-specific structured-output API —
a deliberate "author once, all adapters stay trivial" choice). Three
fields on the final report — `tools_called`, `pull_direction`,
`pull_direction_source` — are tracked **mechanically** by the orchestration
loop from what the model actually called, never self-reported by the model
in its JSON. This directly enforces the project's honesty policy at the
agent layer too: an LLM narrating its own audit trail is exactly the class
of unverifiable claim this project's rules exist to prevent everywhere
else.

---

## 7. PDF report export (`backend/report/`)

Also absent from the technical deep dive beyond an endpoint-table mention.
`pdf_export.py` (reportlab Platypus) + `templates.py`. **Pure presentation
layer** — it takes the same `.to_dict()` payloads every analysis endpoint
already returns as JSON and lays them out; it recomputes nothing.

Two bugs worth knowing (both were *reintroductions* of already-fixed
frontend bugs — a good example of why a fix in one presentation layer
doesn't automatically propagate to another):

- **`best_label` duplication**: `direction_optimizer.py`'s direction-label
  helper falls back to the raw vector string for non-axis-aligned
  directions, so printing `best_label` and `best_direction` as two
  separate rows produced the same string twice (e.g.
  `"(+0.232, +0.357, +0.905) (+0.232, +0.357, +0.905) ≈ +Z, tilted 25°"`).
  This exact bug had already been fixed once in the Streamlit frontend;
  the new PDF module reintroduced it independently and needed its own
  guard.
- **The 100%-error illusion**: `SideCoreResult.conservation_error`
  defaults to `1.0` as an *unset placeholder* when no side core was
  generated at all (no undercuts existed at that pull direction — a
  correct, expected state, not a failure). Rendering that number
  unconditionally would print "100% conservation error" for a state that
  isn't an error at all. Fixed by branching on `status` before ever
  showing the volume numbers.

An **Executive Summary** section (`include_executive_summary`, default
`true`) prepends a "read this first" verdict block built entirely from the
same dicts every other section already renders — zero new computation.
Every warning source in the system (`parting_line.warnings`,
`core_cavity.warnings`, undercut Boolean-reliability flags, the
`planar_approximation` split-tool label, a failed side-core attempt, the
AI agent's own warnings) is aggregated into one "Warnings" section at the
top — nothing gets dropped for a cleaner-looking page. Screenshots are
**always frontend-supplied** (base64 PNG in the POST body) — the backend
has no renderer and deliberately never gains one, keeping OCC/rendering
strictly server-side and viewport rendering strictly client-side.

---

## 8. `frontend-web/` — the actual demo UI (not covered by the deep dive at all)

This is the single biggest gap. The technical deep dive's §17 ("Frontend
Data Flow") describes `frontend/app.py` — the Streamlit UI. Every path in
the README, `docker-compose.yml`, and `CLAUDE.md` says explicitly: **the
Streamlit UI is not the demo path.** `frontend-web/` (React 19 + TypeScript
+ Vite + Zustand + Three.js) is what Bosch will actually see when they run
`docker compose up --build` and open `localhost:5173`. I could not fetch
its nested source files directly (robots-blocked directory listing), so
everything here is reconstructed from `CHANGELOG.md`'s F1–F7 phase
entries — verify exact component/file names against
`frontend-web/src/` yourself before quoting them line-by-line.

### 8.1 Why a persistent-viewport architecture, and what "persistent" means precisely

The central engineering requirement of Phase F1 was: **one Three.js
engine instance for the entire session**, not recreated per tool switch.
`ViewportEngine` is a module-level singleton
(`engineSingleton.ts`), mounted once as a permanent sibling of
`ContextInspector`, never conditionally rendered. Camera position/zoom,
loaded geometry, and face-selection state survive every tool switch **by
construction** (there's nothing that could reset them), not by
special-case code that remembers to restore them. It also degrades to a
headless no-op renderer when `WebGLRenderer` construction fails
(jsdom/CI-safe), so the same engine code is exercised in automated tests
without a real GPU.

### 8.2 One shared state store, typed ahead of when it's needed

A single Zustand store (`analysisStore.ts`) holds `currentPart`,
`activeTool`, `mode` (Guided/Expert), `pipelineStatus`,
`selectedFaceIds`/`selectedEdgeIds`, `pullDirection`/
`pullDirectionSource`, `camera`, `overlay`. Fields needed only by later
phases (F2+) were typed empty from F1 onward specifically so the store
never needed a later restructure — a small but telling piece of forward
planning worth mentioning if Bosch asks about maintainability.

### 8.3 The overlay/color system, and the specific honesty fix it embodies

`geometry/overlayColors.ts` maps a face's undercut *category* — not a
binary flag — to a color: bright red (Boolean-confirmed, needs a mold
action), faint red (the same feature's tangent/zero-draft boundary
member — an ambiguity, not independently confirmed trapped material), or
teal (`ray_verified_clear` — an independently, positively checked
clearance). This exists because an earlier version painted **both**
members of a feature pair identically bright red, overstating the
tangent member's own evidence and making the genuinely dangerous member
visually indistinguishable from it — the exact same "don't let two
different evidence strengths look identical" principle that shows up
repeatedly in the backend (evidence tiers, region-classification labels,
etc.). A `coreCavityOverlayOrder` stack determines which layer wins where
undercut/core-pin/side-action overlays visually conflict — whichever was
**most recently toggled on** takes precedence, so toggling a layer off
and back on always visibly changes something.

### 8.4 The three-tier diagnostics workspace

Eight groups (Geometry, Pull Direction Search, Parting Line, Core/Cavity,
Undercuts, Side Cores, Performance, Advanced/Engineering Diagnostics),
each collapsed to a one-line status dot by default, each with Tier 1
(always-visible conclusion), Tier 2 ("Details" toggle), Tier 3
("Advanced" toggle, raw/debug JSON). **Zero additional backend calls** —
it reads only fields already present in the one `/core-cavity` response
already fetched for Guided mode. Three real backend-contract gaps are
disclosed explicitly here rather than silently worked around: pull-
direction search detail (candidate counts, evidence tiers) only exists on
`/direction`'s own response, never `/core-cavity`'s — fetching it
separately would mean re-running the expensive optimizer search a second
time, so it's simply shown as "Not available from current response,"
with the reason spelled out, not fabricated.

### 8.5 Manual pull-direction override + the authorization editor

X/Y/Z fields, six axis presets, and "use selected face normal" (computed
client-side from the already-loaded display mesh's own triangle
positions — no second backend round trip). A structured
`AuthorizationEditor` lets an engineer enter core-pin face references and
delegated secondary actions through validated fields — explicitly **not**
a raw-JSON editor (an earlier experimental tab had one, flagged in an
audit as "isolated... wired to nothing else," and deliberately not
repeated here).

### 8.6 Before/after comparison mode

A `compareMode` toggle splits the persistent viewport into two panes: the
left pane is the *same*, unchanged persistent engine showing whatever the
current tool already shows (state *after* any manual authorization); the
right pane is a second, disposable `ViewportEngine` instance, created only
while comparing, loaded with the *automatic* run's own real
`display_mesh`/`core_cavity_rgb` (state *before* authorization) — both
real, already-fetched backend responses, nothing synthesized for the
comparison.

### 8.7 The one disclosed, deliberately-not-built piece: Expert-mode independent tool runs

`README.md` §12 states this precisely: Expert mode currently reads the
*one shared* analysis result through per-tool tabs — running
Direction/Parting-Line/Core-Cavity **independently** of each other (rather
than only via the single Guided orchestration call) is not yet built.
This is the one item in `TODO.md`'s "not demo-blocking" list tied directly
to the frontend, and it's worth having a one-sentence answer ready for
"can I re-run just the parting line without redoing the direction search"
— the honest answer today is no, not from Expert mode's UI.

---

## 9. The corrected, expanded API surface

The deep dive's §16 endpoint table has two naming inaccuracies worth
fixing before you present it, plus several endpoints/params it never
lists at all. Cross-checked against `CHANGELOG.md`'s dated endpoint
additions:

| Endpoint | Deep dive says | Actually (per CHANGELOG) |
|---|---|---|
| STEP export | `GET /parts/{filename}/export/step` | `POST /parts/{filename}/export/mold-halves` |
| PDF export | `GET /parts/{filename}/export/report` | `POST /parts/{filename}/export/report` (JSON body for an optional embedded screenshot) |

Endpoints the deep dive never mentions at all:

- `POST /parts/upload` — multipart `.stp`/`.step`, 200MB cap, extension
  validated, content non-empty-validated, stored UUID-prefixed under
  `data/uploads/` (deliberately never `data/parts/`, which stays
  read-only per the project's hard invariant). `GET /parts` merges both
  directories transparently — every existing per-part endpoint works on
  an uploaded file with zero special-casing.
- `GET /parts/{filename}/export/download/{filename}` — the actual
  browser-download path for a STEP export; path-traversal-guarded, scoped
  strictly to the configured export directory.
- `POST /parts/{filename}/agent/analyze` — optional `query`/`provider`
  query params; runs the full agent tool-calling sweep.
- `GET /agent/providers` — which providers are importable in this
  environment vs. actually configured (lets the frontend build a live
  provider picker rather than a hardcoded one).
- `GET /parts/{filename}/parting-line-v2` — the standalone v2-direct
  endpoint referenced in §1.4 above.

`/core-cavity`'s full query-parameter surface (worth having memorized,
since it's the one endpoint that does everything): `use_optimal_direction`,
`dx`/`dy`/`dz` (manual override), `solid_split`, `generate_side_core`,
`multi_feature_side_cores`, `side_core_severities`,
`side_core_max_features`, `core_pin_face_refs`, `delegations`,
`include_mesh_geometry` (Stage S3.8 — defaults `true`, but the frontend
requests `false` once it has already cached the base mesh, cutting a
typical response by roughly two-thirds — 682KB → 224KB measured on
Part1's `/draft` call — by never re-sending geometry it already has).

---

## 10. `config.yaml` — reading the whole threshold surface

The deep dive never explains the config *system* as a system — only
individual thresholds in passing. Two architectural points worth making
to Bosch, both enforced as hard invariants (`CLAUDE.md`, `config.yaml`'s
own comments): **every** algorithmic threshold lives in this one YAML
file, loaded through `backend/config.py`'s Pydantic settings classes —
never a hardcoded magic number in algorithm code — and it's mounted
**read-only** into the Docker backend container (`./config.yaml:/app/
config.yaml:ro`) specifically so a threshold can be tuned live without a
full image rebuild.

The file is organized into nine top-level blocks under `dfm:` — `draft`,
`direction_search`, `parting_line` (v1), `parting_line_v2`, `core_cavity`,
`side_core`, `display`, `parting_surface`, `undercut` — plus a top-level
`agent:` block. A pattern worth pointing out explicitly: **most values
carry an inline comment citing the exact decision (`D-0XX`) and the
measured evidence that produced the number** — e.g.
`stitch_snap_tolerance_rel` isn't just `2.0e-2`, its comment explains it
was raised from `weld_tolerance_rel*100` after a controlled-direction
diagnostic measured real junction gaps of 0.043–1.05mm on Part3, 6× to
150× the old radius. This traceability — every number has a "why," and
the "why" is a measurement, not a guess — is itself a good thing to
highlight as an engineering-culture point, independent of any single
threshold's value.

A handful of values worth being ready to explain on sight, since they're
the ones most likely to come up in a live Q&A:

- `direction_parallelism: 8` — matches this dev machine's physical core
  count (`sysctl hw.physicalcpu`), not an arbitrary number; each unit is a
  real isolated OS subprocess doing genuine OCC Boolean work, so
  throughput is bounded by physical cores.
- `min_coverage_ratio: 0.50` (H7) — explicitly commented **"a
  configuration decision, NOT an engineering truth and NOT a manufacturing
  law... never quote this as 'a valid parting line covers ≥ 50% of
  projected area.'"** If a Bosch engineer asks "why 50%," the honest
  answer in the file's own words is "provisional, calibrated from corpus
  data, and currently inert in practice" (§3.5 above).
- `volume_conservation_tolerance: 0.06` (core/cavity) — raised from an
  originally-targeted 0.02 to match the *measured* 4.04%/3.81% error on
  Part1/Part3, with margin — a tolerance change driven by measurement, not
  loosened to make a test pass.

---

## 11. Testing posture, and the mock-safety gotcha that bit the team repeatedly

The deep dive doesn't discuss testing infrastructure at all. Two things
worth knowing:

**Scale and gating**: 42 backend pytest files, 18 frontend Vitest files.
No CI is configured — an *explicit* decision, documented in `TODO.md`'s
"Explicitly deferred" list, not an oversight. Real-fixture tests (the ones
exercising actual `Part1.stp`/`Part3.stp` geometry through real OCC) are
gated on both the STEP files existing on disk *and* `pythonocc-core`
being importable, and skip gracefully — not fail — when either is absent.
`STATUS.md` deliberately does **not** report a pass/fail count as of its
last update, since that pass didn't re-execute the suites; the most
recent *verified* run numbers live in the relevant dated `CHANGELOG.md`
entries, not in `STATUS.md` itself.

**The recurring gotcha, worth explaining as its own topic**: any
mock-based unit test that constructs a `FaceData`/`EdgeData` with
`occ_face=MagicMock()` and then calls `detect_undercuts()` or
`optimize_mold_direction()` **without** explicitly passing
`boolean_refine=False` will feed that mock straight into a *real*
`BRepAlgoAPI_Common`/`BRepPrimAPI_MakePrism` call in any environment where
real `pythonocc-core` is actually installed (i.e., Docker/conda, not a
plain pip-only CI runner) — and can hang for minutes, since a real OCC
call against a non-OCC mock object doesn't reliably error, it can loop.
This bit the team at least twice independently: once as a class of
mock-hygiene bugs across `test_undercut_detector.py`/
`test_direction_optimizer.py` (fixed with explicit
`boolean_refine=False` and `monkeypatch.setattr(..., "_OCC_BOOLEAN_AVAILABLE",
False)`), and once, more subtly, inside `parting_line.py`'s own
`_sample_closed_edge_points`, where the fix was an
`isinstance(edge.occ_edge, TopoDS_Edge)` guard — a fast, pure-Python type
check *before* the function ever reaches the native OCC layer, since a
Python `try/except` around a SWIG-wrapped C++ call **cannot** catch or
interrupt a hang happening inside that C++ layer. `TODO.md` still lists a
"broader mock-test hygiene audit" (confirming every mock-based
`PartGeometry` test sets this guard) as an open, not-yet-complete item —
worth knowing that this is a known, tracked, partially-fixed class of
risk rather than a fully closed one.

The fixture corpus itself is worth a one-line mention: 17 synthetic,
analytic-answer STEP fixtures (`F1`–`F17`, each targeting one named
algorithmic failure mode with a closed-form correct answer — e.g. F4 is a
sphere whose exact parting line is the great circle `z=0, r=20`), plus
`UC1`–`UC5` hand-verified undercut fixtures, plus two adversarial fixtures
(`ADV1`/`ADV2`) purpose-built to stress-test the algorithm with heavy
local-feature noise around a known-correct global answer.

---

## 12. Docker & infrastructure

Not discussed at all in the technical deep dive. The verified
`docker-compose.yml` runs exactly two services:

- **`backend`** (`Dockerfile.backend`, port 8000) — `uvicorn ... --reload`,
  with `./data`, `./reports`, `./backend`, `./config.yaml` (read-only),
  and **`./tests`** all live-mounted. That last mount matters: without it,
  `docker compose exec backend pytest tests/` silently runs whatever
  `tests/` tree happened to be baked into the image at the last build —
  a real bug found once (6 of 12 test files were missing from a running
  container, meaning an earlier "all tests pass in Docker" claim had
  never actually exercised current source). A health check polls
  `/health` every 30s.
- **`frontend`** (`Dockerfile.frontend-web`, port 5173) — a plain Vite dev
  server (`node:22-slim`, `npm install`, `npm run dev -- --host 0.0.0.0`),
  **no production build step** — a deliberate simplicity choice for a
  judge-facing demo, not an oversight. `VITE_BACKEND_URL=http://backend:8000`
  is read **server-side** by Vite's own dev-server proxy inside the
  container; the browser on the judge's host machine only ever talks to
  `localhost:5173` and never needs to resolve the `backend` hostname
  itself.

`Dockerfile.frontend` (the legacy Streamlit image) still exists and still
builds standalone (`docker build -f Dockerfile.frontend .`) but is
**not** referenced by `docker-compose.yml` at all — kept only because two
real backend test files (`tests/test_frontend_pv2_apptest.py`,
`tests/test_frontend_pv2_region_colors.py`) import functions directly out
of `frontend/app.py`, so deleting the Streamlit app would break real test
coverage, not just retire an old UI.

Secrets flow through `docker-compose.yml`'s `environment:` block for the
`backend` service: `OPENAI_API_KEY`, `GROK_API_KEY`, `GOOGLE_API_KEY`,
`ANTHROPIC_API_KEY`, all defaulting to empty (`${VAR:-}`) so the container
starts cleanly with none set — everything except the AI agent tab works
with zero keys configured.

---

## 13. Greatest-hits bug log, organized by lesson (not by date)

`docs/DECISIONS_AND_ALGORITHMS.md` has 60+ dated entries. You will not
present all of them. These are the dozen most illustrative for a
developer audience, grouped by the *kind* of lesson each teaches — this
is genuinely some of the best material in the whole repo for demonstrating
engineering rigor to Bosch, because each one is a real defect, a real
measurement, and a real fix, not a hypothetical.

**"A green test suite doesn't mean the geometry is right"**
- Bug A: `closure_guaranteed=True` reported while a real 17.35mm gap sat
  in the curve — the closing path was computed and then discarded before
  being used.
- Bug B: "traverse the graph to find loops" silently degraded to a
  non-backtracking greedy walk on large graphs — passed every existing
  test because no existing test's graph was large enough to trigger the
  fallback.
- D-042: a face nearly tangent to the pull direction made the "swept
  interference volume" calculation return the **entire part's own
  volume** as the answer — passed because no test happened to construct
  a near-zero-g face.

**"The metric can look healthy while the underlying decision is wrong"**
- Bug H: readiness scored 1.000, wire quality scored 0.96, while the
  selected "parting line" was actually a small hole rim covering 1–27.6%
  of the part's real silhouette. Every individual number was internally
  consistent; none of them checked against the part's own actual extent.
- D-058: `confirmed_undercut_pct` (a scoring input) attributes a face's
  *entire* area to "confirmed" the moment any real interference is found
  anywhere on it — provably not invariant to how a surface happened to be
  split into B-Rep faces at authoring time. Flagged, not fixed
  (recommended: add a second, complementary metric rather than redesign
  the existing one).

**"Fix the checker, not just the thing being checked"**
- D-024: the code being verified (Track B's boundary point) was correct.
  The verifier itself (`GeomAPI_ProjectPointOnSurf`) was silently
  searching the wrong domain.

**"Reused thresholds create invisible coupling"**
- The core-pin uniform-draft check deliberately uses its **own** config
  key (`core_pin_uniform_g_max`) rather than reusing H4's
  `orientation_epsilon` or Track B's `silhouette_epsilon` — an edit made
  for an unrelated reason (H4's whole-region area slack, or Track B's
  band width) could otherwise silently change which faces are eligible
  core-pin candidates.

**"Measure before you build the expensive version"**
- D-017: bounded Johnson cycle enumeration was built (as the corpus's
  measured μ-distribution justified) and then measured to change **zero**
  real-part outcomes at up to 22× the candidates and 10× the runtime —
  kept, but opt-in, not default.
- D-020: H7's coverage threshold was left at its provisional value rather
  than "calibrated," because the actual corpus data showed it rejecting
  nothing — there was no signal to calibrate against.

**"A convention that looks pedantic can be load-bearing"**
- D-006: a closed circular B-Rep edge must be recorded as a graph
  self-loop of **degree 2**, not 1 — get this wrong and every hole rim
  and cylinder rim in the corpus gets silently pruned as a "dangling"
  degree-1 node.

---

## 14. Honest capability matrix — final, reconciled version

Combining `README.md` §17, `STATUS.md`'s Known Limitations table, and
everything above, here is the single most current, most complete honesty
table for the whole system:

| Subsystem | Status |
|---|---|
| STEP loading, topology, edge convexity | Real, exact B-Rep, no approximation. |
| Draft analysis | Real, exact, `asin(\|n·d\|)`, conditional (texture-aware) thresholds. |
| Direction optimization | Real, hierarchical + fine search, subprocess-isolated Boolean verification, evidence-tiered — but can still take minutes and has one recorded ~29.6-minute outlier on Part1, root cause not fully explained. |
| Undercut detection | Real Boolean confirmation on a filtered candidate pool; core-side-only accessibility-risk was found and fixed to be bilateral; a known granularity limitation remains in `confirmed_undercut_pct` (§13). |
| Parting line (v2) | Real candidate-level result — H0–H7-gated, ranked, with core-pin/delegation authorization — but full Hou-2018 global optimization is not applied, and the config-level v1/v2 A/B flag needs the reconciliation from §1.4 before you present it. |
| Core/cavity split | Real Boolean solid split, verified on both real parts, but the Boolean tool is a **labeled planar approximation** of the true 3-D parting surface (the real surface is confirmed topologically invalid on both real parts, unfixable by standard OCC healing) — `split_tool_kind="planar_approximation"` is always present in the response so this can never be silently misread as exact. |
| Side cores | Real geometry (volume + release direction), single- and multi-feature; does **not** select a tooling mechanism. |
| AI agent | Real, tool-calling, provider-agnostic; only Gemini is live-verified; **not wired into `frontend-web/`**, reachable via API/legacy UI only. |
| PDF export | Real, presentation-only, built from already-computed results. |
| `frontend-web/` | The real, intended demo UI; Expert mode's per-tool *independent* re-run is the one disclosed not-yet-built piece. |
| CI/CD, auth, multi-user, production Docker build | Explicitly, deliberately out of scope for this submission — not partially built. |

---

## 15. Glossary additions (terms the deep dive's own glossary doesn't define)

| Term | Meaning |
|---|---|
| **Evidence tier** | A direction candidate's verification status: `unverified` / `verified_undercuts_present` / `verified_acceptable`. Compared *before* raw score in final selection, so an unverified candidate can never numerically outrank a verified one. |
| **H0–H7** | The eight hard-validity gates every parting-line candidate must pass in `parting_line_v2` before it's even eligible for ranking. Full table in §3.5. |
| **T1–T7** | The lexicographic ranking tiers used to pick among gate-surviving candidates. Full list in §3.6. |
| **Core-pin** | An authorization mechanism (D-043) letting a specific coaxial bore face participate in the topological-separation test via a non-geometric axial split, without adding a fake segment to the real parting curve. |
| **Delegation** | An authorization mechanism (D-044) excluding a validated, human-authorized secondary-mechanism face set from H4's orientation-consistency test — never a claim that the mechanism has been proven to physically release. |
| **`planar_approximation`** | The label on every core/cavity Boolean split result, disclosing that the Boolean tool used is a flat plane through the parting loop's centroid, not the exact (and topologically-invalid-on-real-parts) 3-D parting surface. |
| **O22 / process isolation** | Running each candidate direction's Boolean undercut check in a fresh OS subprocess, because repeated Boolean calls in the same OCC process were empirically found to degrade later results. |
| **O24 / `direction_parallelism`** | How many O22 subprocesses run concurrently per direction search — bounded by physical CPU cores, dispatched via `threading.Thread` (which achieves real OS concurrency here because `subprocess.run` releases the GIL while blocked). |
| **`mutate` flag** | `False` for scoring/comparison loops (never writes `FaceData` fields); `True` only for the one final, chosen result. |
| **Levitating curve** | The v1 defect (RC-7) of a displayed parting curve with no OCC backing — structurally prevented in v2 by requiring every `CurveSegment` to carry a real `EdgeBacking` or `FaceBacking`. |

---

## 16. Quick file-pointer index for your presentation

Use this as a checklist of where to open your editor for each topic —
line numbers aren't included since I couldn't verify them directly this
session; open each file and confirm before you present specific numbers.

| Topic | File(s) |
|---|---|
| The four papers vs. reality | root `Engine.md` (original pseudocode), `docs/DECISIONS_AND_ALGORITHMS.md` (actual implementation) |
| H0–H7 gates | `backend/geometry/parting_line_v2/gates.py` |
| T1–T7 ranking | `backend/geometry/parting_line_v2/ranking.py` |
| Core-pin / delegation | `backend/geometry/parting_line_v2/contracts.py`, `regions.py`, `engine.py` |
| Region 5-state model | `backend/geometry/parting_line_v2/regions.py` (`classify_regions`) |
| Production orchestration | `backend/geometry/mold_orchestration.py` |
| Side cores | `backend/geometry/side_core.py` |
| AI agent | `backend/agent/dfm_agent.py`, `tools.py`, `providers.py`, `schemas.py`, `prompts.py` |
| PDF export | `backend/report/pdf_export.py`, `templates.py` |
| Demo UI shell / viewport | `frontend-web/src/` (`store/analysisStore.ts`, `viewport/engineSingleton.ts`, `viewport/ViewportEngine.ts`) |
| Overlay colors | `frontend-web/src/geometry/overlayColors.ts` |
| Manual direction + authorization UI | `frontend-web/src/analysis/`, `components/PullDirectionPanel`, `AuthorizationEditor` |
| Every threshold, with rationale | `config.yaml`, loaded by `backend/config.py` |
| Endpoint list, ground truth | `backend/api/main.py` |
| Infra | `docker-compose.yml`, `Dockerfile.backend`, `Dockerfile.frontend-web` |

---

## 17. Appendix — the original hackathon framing (from `understand.md`)

For context you may want when explaining *why* the project is shaped the
way it is (this document predates all the code and isn't referenced by
the deep dive at all):

- **Problem statement (verbatim from the hackathon brief)**: *"Develop an
  AI-driven solution that analyzes 3D CAD model of an injection-molded
  automotive component and automatically provides the corrections needed
  in the part design to ensure trouble free manufacturing."*
- **Two input files were specified from the start**: one simple (Level 1
  — optimal direction + main parting line + visualization) and one
  complex (Level 2 — adds core/cavity extraction). This is exactly why
  `Part1.stp` and `Part3.stp` exist and are described as "primary/simple"
  and "secondary/complex" throughout `STATUS.md` — it's not an arbitrary
  naming choice, it's the brief's own two-tier structure. (`Part2.stp`
  never existed — an early naming mix-up resolved long ago, in case
  anyone asks.)
- **Original planned team structure**: Backend Engineer (owns the
  geometric tools), Frontend Engineer (displays results + agent output),
  Tester (validates both geometry and agent suggestions), Presenter/
  Reporter/Documenter. Useful context if Bosch asks how the work was
  divided.
- **The explicit long-game framing**: the brief states *"Code should be
  easy to update for future revisions or correction,"* and the project's
  own planning doc treats that as a north-star requirement — positioning
  the submission not as a one-off demo but as a starting point for a
  stated follow-on **4-month internship (Level 3)** opportunity. Worth
  saying out loud if you want to frame the codebase's heavy documentation
  and honesty-policy investment as a deliberate choice, not overhead.
- **Why pythonOCC over a mesh library**: confirmed as a deliberate,
  early, documented choice — STL/mesh-based approaches were ruled out
  specifically because draft-angle tolerances in real mold design (often
  sub-2°) are smaller than the error a practical mesh tessellation
  introduces, and Boolean operations on mesh-mesh intersections are
  numerically unstable at that precision in a way exact B-Rep Booleans
  are not.

---

*This document supplements, and should be read alongside,
`DFM_TECHNICAL_DEEP_DIVE.md`. Everything above was cross-checked against
your project's own `STATUS.md`, `CHANGELOG.md`, `TODO.md`,
`SUBMISSION_REPORT.md`, and `docs/DECISIONS_AND_ALGORITHMS.md`, and
against files fetched directly from `github.com/uh-bhinav/Bosch`
(`README.md`, `Engine.md`, `understand.md`, `CLAUDE.md`, `config.yaml`,
`docker-compose.yml`, `requirements.txt`, `Dockerfile.frontend-web`).
Every item flagged "verify before presenting" is flagged because GitHub's
`robots.txt` blocked automated access to nested source-file listings this
session — those specific claims come from your project's own detailed
documentation of the code, not from me reading the `.py`/`.ts` files
directly. Open the named file before you state a specific number or line
reference to Bosch.*