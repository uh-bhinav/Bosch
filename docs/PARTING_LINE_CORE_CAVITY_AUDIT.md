# Parting Line & Core/Cavity — What Is Actually Implemented, and Why It Does Not Generalize

> **Scope of this document.** Only the two modules our sub-team owns:
> `backend/geometry/parting_line.py` (4,746 lines) and
> `backend/geometry/core_cavity.py` (715 lines).
> Pull direction (`direction_optimizer.py`) and undercut detection
> (`undercut_detector.py`) are **treated as upstream inputs** and are not
> audited here.
>
> **Method.** Every claim below was read out of the source on 2026-08-08 and is
> cited by `file:line`. Measured numbers are quoted from `STATUS.md` /
> `CHANGELOG.md` where they were recorded from real runs on `Part1.stp` /
> `Part3.stp`; nothing here is estimated.
>
> **Status honesty.** `.claude/memory/known-gaps.md` is stale (last updated
> 2026-07-27, before the agent layer, PDF export, and Boolean solid split
> existed). Do not use it as the status source. This file supersedes it for
> parting line and core/cavity.

---

## Part 0 — The measured bottom line

| Part | Parting readiness | Silhouette coverage | Parting surface | Boolean split | Split tool |
|---|---|---|---|---|---|
| `Part1.stp` | `ready` (0.792) | **94.8%** | `generated_filling` | `split_ok`, 2 solids | flat plane |
| `Part3.stp` | `ready` (0.806) | **18.1%** ⚠ | `generated_filling` | `split_ok`, 2 solids | flat plane |

Read that table carefully, because it contains the whole problem in one row:

- Part3 reports **`ready` with 0.806 confidence** while its selected loop wraps
  **18.1%** of the part's projected outline. A parting line that covers 18% of
  the silhouette is not a parting line. The engine's own quality score does not
  know this — coverage is reported as a *separate warning field*
  (`silhouette_coverage_ratio`, `parting_line.py:4674-4691`), not as a gate.
- Both parts produce a parting *surface* that is `generated_filling` — and that
  surface is **topologically invalid** (`BRepCheck_Analyzer`), unfixable by
  `ShapeFix_Shape` / `ShapeFix_Face` / `BRepBuilderAPI_Sewing`
  (`CHANGELOG.md`, "Stage 2b"). It is drawn on screen. It cannot be used for
  anything.
- The Boolean split therefore uses a **different geometry entirely**: a flat
  plane through the loop centroid (`core_cavity.py:321-370`,
  `build_planar_split_tool`). Measured volume-conservation error 4.04% (Part1)
  / 3.81% (Part3) — that error *is* the geometric cost of replacing the real
  3-D parting line with a plane.

So the 1D → 2D → 3D progression you described is **broken at the 2D stage**.
The 1D curve exists. The 2D surface exists but is unusable. The 3D split is
done with a substitute.

---

## Part 1 — Exactly what the parting-line pipeline does today

Entry point: `detect_parting_line_candidates()` — `parting_line.py:4316`.

### Stage 1 — Edge classification (`_classify_edge`, line 627)

For every edge in the part, look up its adjacent faces, take each face's
normal `n`, compute `s = n · d` where `d` is the unit pull direction.

| Case | Condition | Kind | Score |
|---|---|---|---|
| 1 adjacent face | `\|s\| ≤ 0.15` | `boundary` | `max(0.15, 1 − \|s\|/0.15)` |
| 1 adjacent face | `\|s\| > 0.15` | `skipped` | 0 |
| > 2 adjacent faces | — | `non_manifold` | 0.25 |
| 2 faces | `s_a > τ ∧ s_b < −τ` (or swapped) | `silhouette` | `0.75 + 0.25·min(1, \|s_a−s_b\|/2)` |
| 2 faces | `min(\|s_a\|,\|s_b\|) ≤ τ` | `near_parting` | `0.35 + 0.25·closeness` |
| 2 faces | otherwise | `skipped` | 0 |

with `τ = dfm.parting_line.dot_tolerance = 0.01`,
`boundary τ = 0.15` (`config.yaml:49-50`).

This is exactly the sign-flip test from your Part 7. **It is implemented
correctly for what it is.** The problem is not this test — it is the input it
is given (Root Cause 1 below).

### Stage 2 — Connected components (`_candidate_components`, line 809)

Builds your **Option 2** graph: nodes = candidate edges, connected when they
share a vertex. Vertex identity is by a quantized key
(`_point_key`, line 800) at `point_tolerance = 1e-4 mm` (`config.yaml:51`).
Components found by iterative DFS, then sorted by total length desc.

### Stage 3 — One ordered wire per component (`_build_ordered_wire`, line 2044)

A greedy walk over edge endpoints. Reports `branch_point_count`, `gap_count`,
`skipped_edge_ids`. Labels the wire `closed_loop` / `open_chain` / `branched` /
`partial` / `empty` (`_wire_quality`, line 1536).

> ⚠ **One wire per component. Not one wire per possible loop.** This is
> Root Cause 3.

### Stage 4 — Wire scoring (`_assess_wire_quality`, line 1952)

A weighted sum:

```
score  = base[wire.quality]              # closed_loop 0.86 | open_chain 0.60
                                          # branched 0.38 | partial 0.25
       + projection_bonus                 # closed_area +0.10 | open_degenerate −0.10 …
       − 0.08·branch_points   (cap 0.25)
       − 0.12·gaps            (cap 0.30)
       − 0.04·skipped_edges   (cap 0.22)
       − 0.34·component_noise (cap 0.34)
       − 0.06·non_manifold    (cap 0.20)
       − 0.04·boundary_only   (cap 0.18)
       − 0.42·undercut_conflict_score
score  = clamp(score, 0, 1)
```

Every constant here is hardcoded in the function body. None of them are in
`config.yaml`. None of them is derived from a molding argument.

### Stage 5 — Selection (`_wire_selection_key`, line 2295)

This part is **better than the rest** and deserves credit — it is a
**lexicographic** tuple, not a weighted sum:

```
(  projection_rank,                  # validity gate
  −undercut_conflict.conflict_score, # Nee criterion 3
   projection.abs_area_mm2,          # Nee criterion 1 — MAXIMUM CONTOUR RULE
   quality_assessment.score,         # Nee criterion 2
   quality_rank,
   projection.bbox_area_mm2,
   silhouette_count,
   total_length_mm,
  −(branch_points + gaps),
  −len(skipped_edge_ids)          )
```

`max()` over that tuple. The ordering follows Nee et al. (1998) §5 and was
deliberately re-ordered on 2026-07-27 to put projected area above tidiness —
that fix raised Part1's coverage from **27.6% → 94.8%** (`STATUS.md`, Bug H).

**But**: the candidate set it maximizes over is one wire per component. On
Part3 that is 22 candidates, none of which is the real parting line.

### Stage 6 — Component bridging (`_bridge_disconnected_components`, line 1155)

Runs **only as a fallback**, when the selected wire is not closed OR its
coverage < `min_silhouette_coverage_ratio = 0.35` (`config.yaml:65`, gate at
`parting_line.py:4441`). Routes between components through the *full* part edge
graph with Dijkstra:

```
cost(edge) = 1.0 × length          if edge is already a candidate
           = 0.6 × length          if boundary edge
           = 4.0 × length          otherwise
           = excluded from graph   if adjacent to any undercut face
```

Two strategies: `_bridge_via_angular_ring` (line 909) orders components by
angle around their collective centroid in the pull-normal plane and links each
to its angular neighbour, wrapping around, so the result is a **cycle**; the
original `union-find` MST strategy is the fallback — and, as the code's own
comment documents, a spanning tree *can never contain a closed loop*, which is
why an exhaustive 177,032-state search over Part3's tree-bridged graph found
none.

The bridged result is kept only if `improved or not_worse`, with magic margins
`+0.05` / `−0.02` (line 4470-4478).

### Stage 7 — Graph cleanup / best path (`_trace_best_weighted_path`, line 3103)

Bounded search with a degree-2 chain-contraction fallback.
Limits: `search_edge_limit = 22`, `max_search_states = 75_000` (lines 3238-3239)
— both hardcoded.

```
edge_weight(e)        = candidate.score + kind_bonus − undercut_penalty
   kind_bonus         = silhouette +0.35 | near_parting +0.12
                        boundary +0.05  | non_manifold −0.15 | else −0.25
edge_scalar_weight(e) = max(0.01, edge_weight) × max(1e-6, length)
```

Maximizes total weight along a path; prefers closed.

### Stage 8 — Closure (`_attempt_loop_closure`, line 4167)

Splices real B-Rep edges to close an open wire.
`max_closure_error_mm = 0.05` (`config.yaml:61`). Reports
`closure_bridge_edge_count` so an engineer can see how much was spliced.

### Stage 9 — Display smoothing (`_refine_selected_wire`, line 3377)

```
raw_points → _resample_polyline(≥96 pts) → _chaikin_smooth(8 iters) → refined_points
```

Chaikin iterations auto-reduce to stay under `max_refined_display_points = 32,000`.

> ⚠ **Chaikin is an *approximating* subdivision scheme, not an interpolating
> one.** It cuts corners: the output curve does not pass through the input
> vertices. So `refined_points` **no longer lies on the part's B-Rep.** This
> matters far more than "display smoothing" implies — see Root Cause 7.

### Stage 10 — Parting surface (`_build_parting_surface`, line 3901)

Input: `refined_pts` (the *smoothed* points, line 4571 → 4612).

1. **PCA plane.** SVD of the centred point cloud; plane normal = smallest
   singular vector. Accept the planar path only if
   `max_deviation ≤ 0.25 mm` **AND** `|n_plane · d| ≥ 0.90`
   (`config.yaml:128,136`). The second test exists because on Part3 PCA finds a
   plane fitting the loop to 0.74 mm but sitting ~60° off the pull axis — using
   it would slice the mold diagonally.
2. **`BRepFill_Filling`** N-sided patch otherwise, after decimating the loop to
   `filling_max_constraint_edges = 120` segments.

Real parting loops on both parts are non-planar (measured pull-axis span:
Part1 16.16 mm on a 30.78 mm part; Part3 7.14 mm on 68.12 mm), so path 2 is
the normal path. It returns `generated_filling` on both parts — **and the
resulting face is topologically invalid.**

---

## Part 2 — Exactly what core/cavity does today

### Face classification (`classify_core_cavity`, `core_cavity.py:116`)

The **entire** algorithm:

```python
sdot = dot3(face.normal, pull_direction)
if   sdot >  threshold: "cavity"
elif sdot < -threshold: "core"
else:                   "parting"
```

with `threshold = 0.05` (`config.yaml:67`) — i.e. `|n·d| ≤ 0.05` ⇒ within
±2.87° of perpendicular ⇒ "parting".

That is 12 lines of logic. Note what is **absent**:

- It never looks at the parting line.
- It never looks at the parting surface.
- It never samples the face — one normal, at the UV centroid, per face.
- There is no accessibility / visibility test, no ray casting, no
  half-space test against a separating surface.

This is **not** the classification you described in Lecture 4 §14–16. It is a
pure normal-sign test that happens to coincide with the correct answer on
simple convex parts.

### Boolean solid split (`split_core_cavity_solids`, `core_cavity.py:373`)

```
blank  = Box(part bbox + 0.25·diag margin)                 # config.yaml:70
tooling = BRepAlgoAPI_Cut(blank, part)                     # retries fuzzy ×1, ×5, ×25
tool    = build_planar_split_tool(loop_centroid, d,        # ← A FLAT PLANE
                                  2.0 · bbox_diag)
split   = BRepAlgoAPI_Splitter(tooling, tool)
→ must yield exactly 2 solids
→ label each by sign of dot(centre_of_mass − loop_centroid, d)
→ validate: each solid ≥ 1% of tooling volume
            |cavity + core − tooling| / tooling ≤ 6%   # config.yaml:83
```

`parting_sheet` is a **required argument that is never used as the tool** — it
serves only as a "was a surface generated at all?" precondition
(`core_cavity.py:396-400`). The honest label `split_tool_kind =
"planar_approximation"` is set on success and surfaced in the UI.

The 6% conservation tolerance exists to accommodate a measured 4.04% / 3.81%
error. **That error is not numerical noise — it is the plane-vs-real-surface
approximation.**

---

## Part 3 — Root causes: why this does not generalize

Ordered by how much each one blocks a real industrial part.

---

### RC-1 ⭐⭐⭐⭐⭐ — One normal per face

`FaceData.normal` is documented as *"Outward unit normal at **UV centroid**,
orientation-corrected"* (`geometry_models.py:306`), computed once at load by
`_compute_face_normal_and_centroid` (`step_loader.py:345`).

For a **planar** face this is exact. For a cylinder, cone, torus, B-spline or
any curved face, `n` varies over `(u,v)` and a single centroid sample is a
lossy summary.

Now recall your own cylinder example. The parting line runs *around the
circumference of the cylindrical face*. On that face, `n(u,v) · d` changes sign
**inside the face**, not at a B-Rep edge. But:

- `_classify_edge` only ever tests **edges**;
- both adjacent faces of every edge on that cylinder report the *same* single
  centroid normal;
- so **no edge is classified as a silhouette**, and the true parting line is
  **not in the candidate set at all.**

> This is the single deepest reason the engine cannot generalize.
> **The mathematically correct silhouette is a curve `{(u,v) : n(u,v)·d = 0}`
> on the face interior. The current candidate set cannot represent it.**

It also explains Part3's fragmentation directly: where the true silhouette
crosses curved faces, the edge-only detector finds nothing, so the silhouette
arrives as **22 disconnected components** with the real connecting arcs missing.
Bridging then tries to reconstruct those arcs by routing through *unrelated*
B-Rep edges — which is why the ring bridge closes a loop that scores 0.70
against the unbridged 0.77 and gets discarded (`STATUS.md`, Open Items).

---

### RC-2 ⭐⭐⭐⭐⭐ — The candidate set is B-Rep edges only

Direct consequence of RC-1, stated separately because it is a *separate fix*.
Neither Nee nor Hou restricts the parting line to existing topological edges.
A parting line is a curve on the part's surface; the B-Rep edge set is only
where it happens to coincide with a topological boundary.

**Nothing downstream can recover a curve that was never generated.**

---

### RC-3 ⭐⭐⭐⭐⭐ — There is no candidate *set* to optimize over

You correctly identified that the interesting problem starts once you have
multiple loops. **That problem is not reached today.**

- One ordered wire is built per connected component (`_build_ordered_wire`).
- `_trace_best_weighted_path` returns exactly **one** best path per component,
  bounded at 22 edges / 75,000 states.
- No cycle basis, no enumeration of simple cycles, no branch-alternative
  expansion.

So `_wire_selection_key`'s carefully-ordered Nee lexicography maximizes over a
set of size *N_components*, where each element is itself an arbitrary greedy
choice. The optimizer is fine; **it is being handed the wrong feasible set.**

---

### RC-4 ⭐⭐⭐⭐⭐ — Feasibility and scoring are fused

Your point 2 ("separate feasibility from optimization") is violated
structurally. `_assess_wire_quality` folds *validity* signals (gaps, branches,
missing endpoints) into the same 0–1 number as *preference* signals
(projection quality, noise). Consequences:

- **Nothing is ever rejected.** The pipeline always returns a result. A
  `partial` wire with 15 gaps still scores 0.25 and still becomes
  `selected_wire` if it is the only thing there.
- **`readiness` is computed after the fact**, from the selected wire plus the
  accumulated warning list (`_parting_line_readiness`, line 3607) — it is a
  *report*, not a gate. Hence Part3: `ready(0.806)` at 18.1% coverage.
- The one real gate that exists, `_parting_line_diagnostic_gate`
  (line 3697, with `blocks_core_cavity`), is **not consulted** by
  `core_cavity.classify_core_cavity` — which, per RC-8, does not read the
  parting line at all.

---

### RC-5 ⭐⭐⭐⭐☆ — Missing hard validity tests

Grepped across `backend/geometry/`: **no self-intersection test exists**
anywhere. Neither does any of the following:

| Test from your Lecture 4 | Present? |
|---|---|
| Closedness (‖P_end − P_start‖ < ε) | ✅ `_attempt_loop_closure`, 0.05 mm |
| No self-intersection | ❌ **absent** |
| Actually separates the geometry | ❌ absent — only a bbox-extent *proxy* (`silhouette_coverage_ratio`) that is a warning, not a gate |
| Parting surface constructible | ⚠ attempted, but validity of the result is never checked in-module — the invalidity was found by an external `BRepCheck_Analyzer` audit |
| Core/cavity classification stays valid | ❌ absent (RC-8) |

`silhouette_coverage_ratio` deserves special mention: it is computed from the
loop's **projected bounding-box area** over the part's projected bbox area
(line 4677-4682). A bounding box is a coarse proxy — an L-shaped loop and a
rectangle with the same extent score identically.

---

### RC-6 ⭐⭐⭐⭐☆ — The 2D stage is broken, so 2D→3D is a substitution

`BRepFill_Filling`'s N-sided patch through the loop is topologically invalid on
both real parts, independent of any extension, and survives no standard OCC
healing (verified 2026-07-28, "Stage 2b"). `BRepAlgoAPI_Splitter` cannot
consume it. So:

- **displayed** parting surface = the invalid filling patch;
- **used** splitting geometry = a flat plane through the loop centroid.

These are two different objects. Everything downstream — the exported STEP
mold halves, the volume numbers, the side cores — is built on the plane. The
project labels this honestly (`split_tool_kind`), which is the right call, but
it is a substitution, not a solution.

Root reason the filling fails is worth naming: an N-sided `BRepFill_Filling`
patch spanning a 120-segment, highly non-planar 3-D loop is a badly-posed
surfacing problem. **Method D from your Lecture 4 §10 — extend the neighbouring
faces — is the mold-aware construction and has never been attempted.**

---

### RC-7 ⭐⭐⭐☆☆ — The final curve does not lie on the part

Chaikin smoothing is *approximating*: after 8 iterations the curve is pulled
noticeably inside every corner, and it is this smoothed polyline — not the raw
B-Rep-derived one — that is:

1. fed to `_build_parting_surface` (line 4612),
2. serialized as `refined_wire_points` and drawn in the viewer,
3. used to compute `silhouette_coverage_ratio` (line 4676).

So the reported parting line is a display artefact that has drifted off the
geometry it claims to describe, and the drift is not measured anywhere. For a
DfM deliverable this is the difference between "here is a curve on your part"
and "here is a curve near your part".

The fix is not to delete smoothing — a real parting line *should* be smooth —
but smoothing must be **constrained to the surface** (project each smoothed
point back onto the underlying faces) and the deviation must be reported.

---

### RC-8 ⭐⭐⭐⭐⭐ — Core/cavity is disconnected from the parting line

`classify_core_cavity` takes `(part, pull_direction, threshold)`. It does not
take the parting line, the parting surface, or the loop points. It is a
per-face normal-sign test.

Two failures follow, both of which you predicted in Lecture 4 §16:

1. **A face that straddles the parting surface gets one label.** A large curved
   flank whose upper half belongs to the cavity and lower half to the core is
   assigned entirely to whichever side its UV-centroid normal happens to
   favour. There is no multi-sample test, no bbox test, no
   surface-intersection test.
2. **Classification can contradict the parting line.** Because the two are
   computed independently, a face on the cavity side of the *actual* parting
   loop can be labelled `core` purely from its normal, and nothing detects the
   contradiction.

The `threshold = 0.05` band is also a **normal-direction** band, not a
**position** band. Calling those faces "parting faces" conflates "nearly
vertical" with "on the parting line" — a vertical wall 40 mm below the parting
line is labelled `parting`.

---

### RC-9 ⭐⭐⭐☆☆ — Thresholds are absolute, not scale- or tolerance-aware

| Threshold | Value | Problem at industrial scale |
|---|---|---|
| `point_tolerance` | `1e-4 mm` absolute | Vertex-welding tolerance independent of the STEP file's own declared tolerance and of part size. A 600 mm bumper exported from a different CAD system will have vertex gaps above this and fragment further. |
| `dot_tolerance` | `0.01` | An angular band of ±0.57°. Not derived from anything; too tight for tessellated/imported geometry, and it is a *dot* band, so its angular width varies. |
| `boundary_dot_tolerance` | `0.15` | ±8.6°. 15× looser than the interior band, with no stated reason. |
| `min_silhouette_coverage_ratio` | `0.35` | A single global number for "is this the main loop", applied to bbox-area ratio. |
| `search_edge_limit` / `max_search_states` | `22` / `75,000` | **Hardcoded in the function body**, not in `config.yaml` — violating the project's own invariant #4. A 400-edge silhouette exceeds 22 immediately and silently drops to the contracted/fallback strategy. |
| Chaikin `iterations` | `8` | Fixed regardless of edge count or part scale. |

The `_assess_wire_quality` constants (0.86 / 0.60 / 0.38 / 0.25, the seven
penalty coefficients and their caps) are likewise all hardcoded.

---

### RC-10 ⭐⭐⭐☆☆ — Accumulated fix scar tissue

4,746 lines, 15 dataclasses, and a control flow shaped by named historical
bugs (A, B, D, E, F, G, H, H-2, H-3 — see `STATUS.md`). Concretely:

- Bridging has **two** strategies (ring, then union-find tree) plus an
  accept/reject heuristic with margins `+0.05` / `−0.02`.
- Bridging is gated OFF when a good closed loop already exists, because running
  it unconditionally took Part1 from `ready(1.000)` / 0.2 s to `weak(0.080)` /
  49.8 s (Bug F).
- `_wire_quality` carries a long comment explaining why `skipped_edge_ids`
  must *not* downgrade the label (Bug H-3).

None of this is wrong — each fix was a real fix, evidenced. But the module is
now a sequence of patches over a candidate-generation stage that was
under-specified from the start (RC-1/RC-2/RC-3). **Fixing selection harder
cannot compensate for a feasible set that does not contain the right answer.**

---

### RC-11 ⭐⭐⭐☆☆ — Why it does not visualize well

Four distinct causes, worth separating because they need different fixes:

1. **The drawn surface is not the used surface** (RC-6). Whatever an engineer
   sees on screen is not what produced the exported mold halves.
2. **The drawn curve has drifted off the part** (RC-7).
3. **There is nothing to compare against.** The viewer shows *the* answer. It
   does not show the rejected candidates, the silhouette edges that were found
   but not selected, the component fragmentation, or the bridge edges that were
   spliced in. On Part3 — 22 fragments, 18.1% coverage — the picture that would
   instantly explain the failure to a mold engineer is exactly the picture that
   is never drawn.
4. **Point budget over fidelity.** `max_refined_display_points = 32,000` with
   auto-reduced Chaikin iterations means the *rendered* curve silently changes
   fidelity depending on edge count, and `_parting_display_metrics` reports the
   reduction as a warning rather than as a labelled visual state.

---

## Part 4 — What is genuinely good and must be kept

Being fair to the existing code, because the rewrite should not throw these away:

| Keep | Where | Why |
|---|---|---|
| Lexicographic selection ordering | `_wire_selection_key:2295` | Already the right *shape* of decision rule — priority ordering, not a weighted sum. Directly matches Nee §5. |
| Undercut conflict placed above area | same | A loop through an undercut is not manufacturable at any size. Correct engineering call, and it is tested. |
| Bridging through **real B-Rep edges**, never straight lines | `_bridge_disconnected_components:1155` | The bridge always lies on the part. Non-negotiable property to preserve. |
| Undercut faces excluded from the bridge graph (∞ cost) | line 1225 | A hard constraint, correctly implemented as a hard constraint. |
| Ring (cycle) bridging over MST | `_bridge_via_angular_ring:909` | The insight that a spanning tree can never contain a loop is correct and hard-won. |
| Measured closure, not assumed | `_attempt_loop_closure:4167` | Reports `closure_error_mm` and `closure_bridge_edge_count`. |
| `silhouette_coverage_ratio` as a first-class reported metric | line 4674 | The right *metric*; wrong *role* (warning, should be a gate). |
| `split_tool_kind` honesty label | `core_cavity.py:212` | Prevents a false claim reaching a report. Keep this pattern. |
| Structured results everywhere, never raises | all | Every failure returns a typed result with a reason. Matches your point 11. |
| `_validate_split_volumes` as a **pure function** | `core_cavity.py:251` | Unit-testable without OCC. Exactly the right factoring. |

---

## Part 5 — Mapping the root causes onto your framework

| Your principle | Current state |
|---|---|
| Define the problem mathematically first | ⚠ Partial. Silhouette test is correct; "valid parting line" is never formally defined. |
| Separate feasibility from optimization | ❌ **Violated** (RC-4). One fused 0–1 score; nothing is rejected. |
| Hierarchical / lexicographic optimization | ✅ **Done** in `_wire_selection_key` — the best part of the module. |
| Establish a baseline before optimizing | ❌ No baseline. No brute-force reference implementation to compare against. |
| Coarse → refine | ❌ Single-pass. |
| Exploit problem structure | ⚠ Partial — the graph is built, but no cycle structure is exploited. |
| Reduce the search space before optimizing | ❌ Inverted: the search space is *too small* (RC-3), not too large. |
| Cache expensive computations | ✅ `load_step_cached()` (0.79 s → 0.003 s warm); Dijkstra SSSP cached per endpoint (Bug D fix: >373,000 Dijkstra calls → O(endpoints)). |
| Separate preprocessing from optimization | ⚠ Partial — one 430-line entry function does classification, bridging, refinement, closure, and surfacing. |
| Deterministic objective | ✅ Fully deterministic; no random seeds anywhere. |
| Track the optimization itself | ✅ **Strong.** `graph_cleanup` reports strategy, state counts, limits; `diagnostics`, `readiness`, `diagnostic_gate` all structured. |
| Validate the answer independently | ⚠ Partial. `part_validation.py` has 5 `--assert-*` flags checking *measured* geometry — genuinely good. But nothing validates the loop *as a loop* (RC-5). |
| Test pathological cases | ❌ Two real STEP fixtures only. No cube, no cylinder, no symmetric part, no degenerate geometry, no equivalent-optima case. |
| Sensitivity analysis | ❌ None. Nobody has measured what happens to the selected loop when `d` is perturbed by 1°. |
| Don't chase fake precision | ⚠ `to_dict()` rounds to 4–6 dp on quantities whose real accuracy is far coarser. |
| Measure more than objective value | ✅ Runtime, areas, volumes, conservation error all measured and recorded. |
| Profile before optimizing | ✅ `performance_profile.py` exists. |
| Parallelize independent evaluations | ❌ Not attempted (correct call for now — OCC thread-safety). |
| Build an optimization ladder | ❌ **Not done.** No Level 0 baseline exists, so no level's value has ever been measured. |

---

## Part 6 — The one-paragraph summary

The silhouette mathematics is implemented correctly and the *selection* rule is
already the right shape (lexicographic, Nee-ordered). The failure is upstream
of both: **the candidate set is restricted to existing B-Rep edges, classified
by a single normal sample per face**, so on any part whose parting line crosses
a curved face the true answer is never generated — it arrives instead as
disconnected fragments that bridging tries to reassemble out of unrelated
edges. Because feasibility was never separated from scoring, the pipeline
cannot say "no valid parting line found"; it reports `ready(0.806)` on a loop
covering 18.1% of the part. And because the 3-D parting surface is
topologically invalid, the Boolean split is performed with a flat plane, at a
measured ~4% volume cost. **Fixing the scoring function will not help. The
generation stage and the feasibility stage are what need to be built.**

---

*Next document: `docs/PARTING_LINE_ALGORITHM_PLAN.md` — the algorithm,
formulas, thresholds, data structures, and the staged ladder for building it.*
