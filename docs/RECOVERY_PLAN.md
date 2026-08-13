# Recovery & Delivery Plan — finalised 2026-07-27

> **✅ STATUS 2026-07-28 — Stage 1 COMPLETE. This plan has been absorbed into
> `docs/ARCHITECTURE_ROADMAP.md` §0.3, which is now the live plan.**
> Keep this document for its diagnosis and reasoning; do not treat it as the
> current task list.
>
> | Stage | Plan status |
> |---|---|
> | 1.1 Fix A (loop closure lies) | ✅ Done — measured gap 0.000000 mm both parts |
> | 1.2 Fix D (O(C³·E²) bridging) | ✅ Done — Part3 bridging now < 1 s |
> | 1.3 Do 1.6 properly (Bug B) | ✅ Done — real exact/contracted search, both wire paths |
> | 1.4 Fix E (no parting surface) | ✅ Done — both parts `generated_filling` |
> | 3.6 `DFM_FORCE_PLOTLY=1` | ✅ Done — verified live against the running stack |
> | **Stage 2** (Level 2 unblock) | ⬜ **Next** |
> | Stage 3 (engineering-review UI) | ⬜ Pending |
> | Stage 4 (criterion #5) | ⬜ Pending |
> | Stage 5 (AI agent) | ⬜ Pending |
>
> **Beyond this plan**, four further defects were found and fixed while
> executing Stage 1: **Bug F** (bridging destroyed already-good loops),
> **Bug G** (tests hung on real OCC), **Bug H** (parting line picked the
> tidiest loop, not the main silhouette), **Bug H-2** (bridging built a
> spanning tree — topologically incapable of closing), and **Bug H-3** (wire
> quality scored from the whole component, not the selected loop).
>
> Supersedes the Phase 2 (React migration) section of
> `docs/ARCHITECTURE_ROADMAP.md`, which is **cancelled** — see §5.
> Evidence for every claim: `docs/ENGINE_AUDIT_2026-07-27.md`.

---

## 1. Where the pipeline actually stands

Measured from your live Part1 run (`metrics/*.csv`) plus Docker/OCC runs:

```
Geometry extraction    ✅ works
Direction optimisation ✅ works well      → 0 bad draft, 0% undercut area at optimum
Undercut detection     🟡 works, noisy    → 27% Boolean failure rate
Parting line           🔴 REGRESSED       → readiness 1.0 → 0.08
Core/cavity            ⛔ BLOCKED         → gated off by the parting line
STEP export            ⛔ BLOCKED         → nothing to export
Side core / lifter PL  ⚫ NOT BUILT       → Bosch criterion #5
```

**The engine is good up to the parting line, and broken from there on.**
Everything downstream is blocked by one stage. That is genuinely good news:
the fix is concentrated, not systemic.

### 1.1 The regression, in your own numbers

| Metric | Before 1.6–1.11 | Your live run now |
|---|---|---|
| `readiness_status` | `ready` | **Weak** |
| `readiness_score` | **1.0** | **0.08** |
| `gate_blocks_core_cavity` | `False` | **True** |
| report-ready | `True` | **Not report-ready** |
| refinement quality | `refined_closed` | open — **17.35 mm gap** |

Milestones 1.7/1.8/1.9 replaced a working, closed, report-ready parting
line with a broken one. Your CSV (`Parting line: Weak, score 0.08` /
`Downstream use: Not report-ready, core/cavity block: True`) and my Docker
runs agree exactly.

### 1.2 Why it broke — four defects

- **A (critical)** `_attempt_loop_closure` computes the closing path, then
  **discards it** and returns `(True, 0.0)` regardless. The wire stays open;
  the system reports it closed. Everything downstream trusts that lie.
- **B (critical)** Milestone 1.6 was **not done**. networkx replaced only an
  adjacency dict; the 22-edge bounded DFS is untouched, so real parts
  (~206 candidate edges) always take the **greedy fallback**.
- **D (high)** Bridging is `O(C³·E²·Dijkstra)` with no caching — the stage
  went 0.1 s → **did not finish in 11 min** (budget 45 s).
- **E (high)** No parting surface is produced: planar rejected
  (2.14 mm > 0.25 mm) and `BRepFill_Filling` throws
  `Number of iteration must be >= 1` — an OCC misconfiguration.

### 1.3 Why the test suite didn't catch any of it

All four survive a fully green suite, because the tests are mock-based and
assert **structure** (does the function return the right shape?) rather than
**geometry** (is the curve actually closed?). Four milestones were marked
complete on that basis. This is the root process issue, and §4 fixes it.

---

## 2. What is already good — do not touch

**Direction optimisation is working well and matches your vision.** From
your CSV, the chosen direction `(+0.232, +0.357, +0.905)` gives **0 bad
faces, 0% undercut area, 310/311 faces good**. It is a continuous unit
vector, exactly as §5 of your architecture doc requires. The Milestone 1.4
fine search measurably improved it (0.692 → 0.313).

Undercut detection correctly finds the real problem in +Z: a **critical
side-action feature, 10 faces, 26.86 mm deep, 14,401 mm³, Boolean-confirmed,
high confidence.** That is a genuine engineering finding, correctly typed
and correctly escalated.

---

## 3. The plan

Ordered strictly by what unblocks the most. Nothing here is a rewrite.

### Stage 1 — Make the parting line true *(unblocks 60% of the product)*

| # | Task | Gate (measured, not reported) |
|---|---|---|
| 1.1 | **Fix A** — return the closing points and splice them into the curve; if closure genuinely fails, report `closure_guaranteed=False` honestly | measured first→last gap ≤ tolerance on Part1 **and** Part3 |
| 1.2 | **Fix D** — replace `O(C³·E²)` with one cached multi-source Dijkstra / MST over component supernodes | parting-line stage < 45 s budget |
| 1.3 | **Do 1.6 properly** — real min-cost path/cycle over the networkx graph, retire the 22-edge DFS limit | `graph_cleanup.strategy` ≠ `greedy-fallback` on real parts |
| 1.4 | **Fix E** — correct `BRepFill_Filling` params; re-check planar tolerance against a *closed* loop | `parting_surface.status == "ok"` on Part1 |

**Stage 1 exit gate**: Part1 readiness back to `ready`, core/cavity
**unblocked**, and — critically — the *measured* gap, not the reported one.

### Stage 2 — Unblock Level 2 *(should mostly fall out of Stage 1)*

| # | Task | Gate |
|---|---|---|
| 2.1 | Re-run core/cavity solid split on the now-valid surface | exactly 2 solids; volumes sum to blank − part |
| 2.2 | Re-run AP214 STEP export | exported file reloads with 2 solids |

### Stage 3 — Make it an *engineering review*, not a metrics dump

This is where your architecture doc (§7, §9) and the "I can't read these
metrics" problem get addressed together.

| # | Task | Why |
|---|---|---|
| 3.1 | **Metrics explainers** — every number states *what it means / what good looks like / what to do*. Priority: `readiness`, `closure_error_mm`, **`graph_cleanup.strategy`**, `undercut_area_pct`, direction `score`, `depth_proxy_mm` (label it a conservative upper bound) | Your #1 debugging blocker. Exposing `strategy` alone would have caught Bug B immediately |
| 3.2 | **Issue-first layout** — lead with ranked *issues* (Critical/Warning + location + reason + recommendation), not module panels | Your §7/§9: "What is wrong? Why? How serious? What should I change?" |
| 3.3 | **Direction presented for humans** — vector **+ closest axis + tilt angle** ("(+0.232,+0.357,+0.905) ≈ +Z, tilted 25°") | Your §5 verbatim |
| 3.4 | **Override pull direction** — ±X/±Y/±Z/Custom, then recompute draft + undercuts + PL + core/cavity | **Bosch criterion #2, currently missing** |
| 3.5 | **Diverse** candidate comparison — see §3.1 below | Your "multiple optimal solutions" concern |
| 3.6 | `DFM_FORCE_PLOTLY=1` in compose (Bug C) | Makes Docker match your local view |
| 3.7 | Backend `PartGeometry` LRU cache + fetch-mesh-once | Removes STEP re-parse per endpoint |

#### 3.1 On "multiple optimal solutions" — a real finding

Your top candidates are **not** diverse; they're the same answer six times:

```
(+0.232,+0.357,+0.905) score 0.313   0.0° from best
(+0.211,+0.366,+0.906) score 0.348   1.3°
(+0.193,+0.380,+0.905) score 0.348   2.6°
(+0.218,+0.362,+0.906) score 0.385   0.9°
(+0.225,+0.359,+0.906) score 0.385   0.4°
(+0.326,+0.453,+0.829) score 0.532   8.9°
```

Six results within 3° — an artefact of the Milestone 1.4 fine-search cone.
Useless for an engineer asking "what are my options?". Fix: cluster
candidates by angular separation and surface the best of each *distinct*
family (e.g. ≥ 15° apart), with score breakdowns. That directly serves the
robustness story: we stop claiming *the* answer and start showing *the
defensible options and why this one ranks first*.

### Stage 4 — Close the criteria gap

| # | Task | Note |
|---|---|---|
| 4.1 | **Scope side-core / lifter PL generation** | **Bosch criterion #5 — no geometry exists**, only recommendation strings. Needs a design pass before estimation. Feature 0 on Part1 (critical, side-action, 26.86 mm) is exactly the input this would consume |
| 4.2 | Reduce Boolean noise | 27% failure rate → 7 low-confidence "proxy-retained" features cluttering the issue list |

### Stage 5 — AI agent (unchanged, still last)

Per your §3/§10: geometry stays the source of truth; the agent calls it as
tools and turns verified facts into an engineering review. Sequencing it
last is still right — an agent narrating a broken parting line is worse than
no agent. **Stage 3 is deliberately the agent's groundwork**: the issue
model, severity ranking, and explanation fields built there are exactly what
the agent will consume.

---

## 4. Cross-cutting: stop this recurring

Add **real-geometry assertions** to the validation harness (not mock tests):

- measured closure gap ≤ tolerance (**not** the reported flag)
- `parting_surface.status == "ok"`
- solid split returns exactly 2 solids
- `graph_cleanup.strategy` is the exact optimiser, not the fallback
- every stage inside its time budget

Every bug in this audit would have been caught by one of these. Green mock
tests gave false confidence four milestones running — that is the actual
process defect to fix.

---

## 5. Phase 2 (React) — cancelled ✅

Agreed. The original justification was rendering performance, but the
Plotly/WebGL viewer already in `frontend/app.py` renders client-side and
interactively. A rewrite would consume the remaining budget and add no
*engineering* capability. The valuable parts of that plan (mesh/analysis
split, backend caching, issue-first UI) are folded into **Stage 3** and
applied to Streamlit.

---

## 6. Sequencing

```
Stage 1  ██████████  parting line correctness   ← blocks everything
Stage 2  ███         Level 2 unblock            ← mostly falls out of Stage 1
Stage 3  ███████     engineering review UI      ← highest visible value
Stage 4  █████       criterion #5 gap
Stage 5  ██████      AI agent
```

**Recommendation: start at Stage 1.1.** It is the smallest change with the
largest unblock — one function that currently lies about its result, and
every blocked stage downstream depends on it telling the truth.

Awaiting your go-ahead.
