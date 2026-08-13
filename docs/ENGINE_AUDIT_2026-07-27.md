# Engine Audit & Recovery Plan — 2026-07-27

> **✅ STATUS 2026-07-28 — every defect in this audit is FIXED and verified.**
> This document is retained as the **diagnosis record**: it explains why the
> engine was rebuilt and what the failure modes were. It is *not* current
> status — see `STATUS.md`. The live plan is
> `docs/ARCHITECTURE_ROADMAP.md` §0.3.
>
> | Bug | Audit severity | Outcome |
> |---|---|---|
> | **A** Closure claimed, not performed | 🔴 Critical | ✅ Fixed — measured gap 0.000000 mm on both parts |
> | **B** Milestone 1.6 not done | 🔴 Critical | ✅ Fixed — real exact/contracted search in *both* wire paths |
> | **D** O(C³·E²) bridging | 🟠 High | ✅ Fixed — Part3 bridging 10+ min → **< 1 s** |
> | **E** No parting surface | 🟠 High | ✅ Fixed — both parts `generated_filling` |
> | **C** Docker/local renderer split | 🟡 Medium | ✅ Fixed — `DFM_FORCE_PLOTLY=1`, verified live |
>
> **Four further defects were found while fixing these** — none were visible
> until the ones above were repaired: **F** (bridging destroyed already-good
> loops), **G** (tests hung forever on real OCC, permanently `-k`-excluded),
> **H** (parting line selected the tidiest loop rather than the main
> silhouette — Nee's maximum-contour rule was ranked 5th), **H-2** (bridging
> built a spanning tree, which by construction contains no cycle, so closure
> was *topologically impossible*), **H-3** (wire quality scored from the whole
> input component rather than the loop selected out of it).
>
> §3.1's criteria table is superseded — criteria 3 and 4 are no longer broken;
> **criterion 5 (side core / lifter) remains genuinely missing** and is now
> scoped as Stage 4 in the roadmap.
>
> **Purpose**: independent review of Milestones 1.6–1.11 (implemented in a
> separate session), plus an assessment of whether the engine approach is
> correct against the six Bosch evaluation criteria.
> **Method**: code reading + empirical runs against the real `Part1.stp`
> inside the Docker/OCC environment. Every claim below is backed by a
> measured result, not inference.

---

## 1. Executive summary

Milestones 1.7, 1.9, 1.10, 1.11 were genuinely implemented and are
structurally sound. **Milestone 1.6 was effectively skipped**, and that skip
— combined with three defects introduced alongside it — is the direct cause
of the "results don't match the known-good solution" symptom.

**The single most important finding**: the parting-line stage currently
**reports success while producing a broken result**. On `Part1.stp` it
claims `closure_guaranteed=True, closure_error_mm=0.0` while the actual
curve has a **17.35 mm gap**. That false success propagates downstream and
silently invalidates core/cavity and export.

| ID | Severity | Finding | Status |
|---|---|---|---|
| **A** | 🔴 Critical | Loop closure *claims* success without closing the wire | Confirmed on Part1 |
| **B** | 🔴 Critical | Milestone 1.6 not done — bounded DFS still the search; real parts hit the **greedy fallback** | Confirmed on Part1 |
| **D** | 🟠 High | Component bridging is `O(C³·E²·Dijkstra)`, no caching — stage went 0.1 s → **>11 min** | Confirmed (timed out) |
| **E** | 🟠 High | No parting surface produced for Part1 (non-planar + `BRepFill_Filling` error) | Confirmed on Part1 |
| **C** | 🟡 Medium | Docker frontend renders a static image; local renders interactive Plotly | Confirmed by code |

---

## 2. Evidence

### 2.1 The measured Part1 result

```
reported closure_guaranteed : True
reported closure_error_mm   : 0.0
selected_wire.is_closed     : False
ACTUAL first->last gap (mm) : 17.346253      <-- measured from the real points

parting_surface.status      : failed
parting_surface.strategy    : none
planar_deviation_mm         : 2.140654

warn: Loop closed via 4 additional edge(s) through B-Rep geometry;
      original open gap was 17.3463 mm.
warn: Refinement candidate graph is large; bounded search skipped and
      greedy fallback used.
```

Read that warning pair together — it is the whole problem in two lines. The
system *says* it closed the loop through 4 edges, and *says* the error is
0.0 mm, but the geometry it hands downstream still has a 17.35 mm hole in
it. And the path that selected the curve in the first place was the
**greedy fallback**, not the optimiser.

### 2.2 Bug A — closure is claimed, not performed

`backend/geometry/parting_line.py::_attempt_loop_closure`

```python
def _attempt_loop_closure(...) -> tuple[bool, float, list[str]]:
    ...
    path = nx.shortest_path(G_cls, source=end_key, target=start_key, weight="cost")
    closing_edges = len(path) - 1
    return True, 0.0, [f"Loop closed via {closing_edges} additional edge(s)..."]
```

The shortest path **is** correctly computed — and then discarded. The
function's return type (`bool, float, list[str]`) has no channel to return
geometry, and it never mutates `refined_points`. The caller then does:

```python
if closure_guaranteed and refined_pts:
    parting_surface = _build_parting_surface(refined_pts, ...)   # still OPEN
```

So a parting **surface** is attempted from a curve with a 17 mm gap, while
every downstream consumer is told the loop is closed. This is also a direct
violation of the project's honesty rule: the tool asserts a geometric
guarantee it has not met.

### 2.3 Bug B — Milestone 1.6 was not delivered

The gate was *"real graph replaces bounded DFS."* What shipped:

```python
if _NX_AVAILABLE and endpoint_keys_by_edge:
    _G = nx.MultiGraph()
    ...
    def _neighbors_of(key): return {d["edge_id"] for _,_,d in _G.edges(key, data=True)}
    def _branch_point_count(): return sum(1 for n in _G.nodes() if _G.degree(n) > 2)
```

networkx replaced the **adjacency dictionary**, nothing more. The search is
untouched:

```python
search_edge_limit  = 22
max_search_states  = 75_000
strategy           = "bounded-dfs"
...
if len(endpoint_keys_by_edge) <= search_edge_limit:   # exact DFS
    ...
else:
    strategy = "greedy-fallback"                       # <-- real parts land here
```

Part1 has ~206 candidate edges. 206 ≫ 22, so **every real part takes the
greedy fallback** — the precise weakness Milestone 1.6 existed to remove.
The dependency became "used" without the algorithm becoming better. F4 is
therefore only cosmetically resolved.

### 2.4 Bug D — bridging is combinatorially expensive

`_bridge_disconnected_components` nests five loops:

```
rounds (C) → pairs (C²) → endpoints_i (E) → endpoints_j (E) → nx.shortest_path
```

For Part1 (12 components, ~10 endpoints each) that is on the order of
**11 × 66 × 100 ≈ 72,600 Dijkstra runs** over a 762-edge graph, and the
entire search is recomputed from scratch each round even though only one
pair merges per round. Measured: the stage did not finish in **11 minutes**
(previously ~0.1 s; the performance budget is 45 s).

### 2.5 Bug E — no parting surface is produced

Both strategies fail on Part1:

- **Planar**: max deviation 2.141 mm > `planar_tolerance_mm` 0.25 mm → rejected.
- **Filling fallback**: `Standard_ConstructionErrorGeomPlate : Number of
  iteration must be >= 1 raised from method Build of class BRepFill_Filling`
  — a genuine OCC parameter misconfiguration, not a geometry limitation.

Consequence: `parting_surface.status="failed"` → Milestone 1.10's solid
split is blocked → Milestone 1.11 has nothing to export. **The Level 2
deliverable does not currently produce output for Part1.** Note the 2.141 mm
deviation is itself measured on the *open* curve, so this must be
re-evaluated after Bug A is fixed.

### 2.6 Bug C — the Docker/local visual difference

`frontend/app.py:28`

```python
_USE_PLOTLY_VIEWER = sys.platform == "darwin" or os.environ.get("DFM_FORCE_PLOTLY") == "1"
```

- **Local (macOS)** → `darwin` → interactive **Plotly/WebGL** viewer.
- **Docker (Linux)** → falls through to **PyVista off-screen + `xvfb-run`**,
  i.e. a flat, software-rasterised static PNG.

Identical geometry, different renderer. This fully explains "the local
frontend looks better and truer." One-line fix: set `DFM_FORCE_PLOTLY=1` on
the frontend service in `docker-compose.yml`.

---

## 3. Is the engine approach correct?

**Yes — the architecture and paper mapping are sound.** Bassi (accessibility
→ direction), Sangolli (convexity/undercut features), Nee (silhouette
parting line), Hou (graph refinement) is the right decomposition, and the
staged prefilter → selective-Boolean design is the correct engineering
answer to OCC's cost and brittleness.

The problem is **not** the approach. It is that the last four milestones
were marked complete on the basis of "tests pass / function exists" rather
than "the output is geometrically correct on a real part." Every one of
these bugs survives a green test suite, because the tests are mock-based and
assert structure, not geometry.

### 3.1 Coverage against the six Bosch criteria

| # | Criterion | State | Note |
|---|---|---|---|
| 1 | Optimal mold direction from undercut detection | 🟢 Good | Works; improved 55–78% by Milestone 1.4 |
| 2 | Override mold direction (flash, other constraints) | 🟡 Partial | Flash *scoring* exists (1.4); no user override path in the UI |
| 3 | Main parting line creation | 🔴 Broken | Bugs A + B — reports success, emits an open curve chosen by greedy fallback |
| 4 | Core & cavity extraction | 🔴 Blocked | Code exists (1.10/1.11) but never runs — no parting surface (Bug E) |
| 5 | **Side core & lifter PL generation** | ⚫ **Missing** | Only recommendation *strings* in `undercut_detector.py`; **no geometry, and not in the roadmap** |
| 6 | Simple GUI & final visualisation | 🟡 Partial | Works; metrics are not interpretable (see §5) |

**Criterion 5 is a genuine gap nobody has scoped.** `grep` finds only
`"lifter-or-collapsible-core-review"` action text — no side-core parting
surface, no lifter geometry. This needs to be added to the plan explicitly.

### 3.2 "There can be multiple optimal solutions" — how do we prove robustness?

This is the right question, and it changes what we should build. If several
directions are legitimately acceptable, then "does our answer equal *the*
answer" is the wrong test. The defensible claims are:

1. **Validity** — is the returned direction genuinely undercut-free (or
   minimally-undercut), with a closed parting line and a clean split?
2. **Ranking transparency** — can we show *why* this direction beat the
   others, with the runner-ups and their scores?
3. **Stability** — small input perturbations shouldn't produce wildly
   different answers.
4. **Agreement where it matters** — for a part with an obvious answer
   (e.g. a simple box), do we return it?

That argues for a **candidate-comparison view** in the UI (top-N directions
side by side with score breakdowns) rather than a single "the answer" claim.
It is both more honest and more useful to a mold engineer, who will want to
apply their own judgement.

---

## 4. Phase 2 decision: stay with Streamlit ✅

**Agreed — cancel the React migration.** The original justification was
performance (server-side re-render per interaction, full mesh re-sent per
overlay). But the Plotly/WebGL viewer already in `frontend/app.py` renders
client-side and is interactive, which removes most of that pain. A rewrite
would consume the entire remaining budget and deliver no new *engineering*
capability.

What is worth keeping from the Phase 2 plan, applied to Streamlit:

- **Split geometry from analysis** — fetch the mesh once, swap overlays
  client-side via the existing `faceId` attribute. Big win, no rewrite.
- **`PartGeometry` LRU cache** in the backend — removes the repeated STEP
  re-parse on every endpoint call.
- **Metrics explainers** (§5) — highest user-facing value right now.
- **Candidate-comparison view** (§3.2).

---

## 5. Metrics are unreadable — this is a real blocker

You said you can't interpret the numbers well enough to debug. That is a
product defect, not a user problem: the end user is a mold engineer who must
reach a conclusion *in minutes*. Every metric should answer three things
inline: **what it means**, **what good looks like**, and **what to do if
it's bad**.

Priority additions:

| Metric | Needs to say |
|---|---|
| `readiness_status` / `score` | What "ready/review/weak" permits; what blocks the next stage |
| `closure_error_mm` | Whether the loop is physically closed, and the tolerance |
| `graph_cleanup.strategy` | **Whether the exact optimiser or the greedy fallback ran** — this alone would have exposed Bug B months earlier |
| `undercut_area_pct` / severity | What fraction of the part is problematic and whether tooling is implied |
| Direction `score` | That it is relative/unitless, plus the runner-up comparison |
| `depth_proxy_mm` | That it is a **conservative upper bound**, not a measurement (per the locked decision) |

Please do share the metrics screenshot when convenient — I'd like to
annotate the actual panel rather than guess at its layout.

---

## 6. Recommended plan

Ordered by "unblocks the most" and by risk. **Nothing here is a rewrite.**

### Stage 1 — Make the parting line true (highest priority)

1. **Fix Bug A.** Change `_attempt_loop_closure` to return the closing
   points and splice them into the curve; if it cannot close, report
   `closure_guaranteed=False` honestly and gate the surface. *No stage may
   report a guarantee it did not achieve.*
2. **Fix Bug D.** Replace the `O(C³·E²)` bridging with a single
   multi-source Dijkstra / MST over component supernodes, computed once and
   cached. Target: back under the 45 s budget.
3. **Do Milestone 1.6 properly.** Replace the 22-edge bounded DFS with a
   real min-cost path/cycle over the networkx graph, so real parts stop
   falling into the greedy fallback.
4. **Fix Bug E.** Correct the `BRepFill_Filling` parameters, then
   re-evaluate the planar tolerance against a genuinely closed loop.

**Gate for Stage 1**: on Part1 and Part3 — measured gap ≤ tolerance (not
just *reported*), a real parting surface, and the stage inside its time
budget.

### Stage 2 — Unblock Level 2

5. Re-run core/cavity solid split + STEP export against the now-valid
   surface; verify the exported file reloads with exactly 2 solids.

### Stage 3 — Make it legible (Streamlit)

6. Metrics explainers (§5).
7. Candidate-comparison view for the "multiple optimal solutions" story.
8. `DFM_FORCE_PLOTLY=1` in compose (Bug C) so Docker matches local.
9. Backend `PartGeometry` cache + mesh/analysis split.

### Stage 4 — Close the criteria gap

10. **Scope side-core / lifter PL generation (criterion 5)** — currently
    absent. Needs a design pass before estimation.

### Cross-cutting — stop this class of bug recurring

11. **Add real-geometry assertions to the validation harness**, not just
    mock tests: assert measured closure gap, assert surface exists, assert
    solid count is 2, assert the exact optimiser ran. Every bug in this
    audit would have been caught by one of these. Green mock tests gave
    false confidence four milestones in a row.

---

## 7. What I have *not* changed

Only documentation so far, plus the locked depth decision recorded in code
and `TODO.md`. **No engine code has been modified** — I want your call on
the plan first, and on whether Stage 1 order looks right to you.
