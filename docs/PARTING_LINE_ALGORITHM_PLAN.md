# Parting Line & Core/Cavity — Algorithm & Execution Plan

> **Companion document.** Read `docs/PARTING_LINE_CORE_CAVITY_AUDIT.md` first —
> it establishes what exists today and the eleven root causes (RC-1 … RC-11)
> this plan is written against.
>
> **Locked scope decisions** (2026-08-08):
>
> | Decision | Choice |
> |---|---|
> | Existing module | New clean module **alongside** `parting_line.py`; old stays working behind a flag until v2 beats it on measured metrics |
> | Test corpus | Part1 + Part3 + public CAD (GrabCAD / ABC) + **synthetic fixtures with analytic ground truth** |
> | 3-D parting surface | **Planar approximation retained and labelled.** A true B-Rep surface is a stretch goal. The split approximation must **not** contaminate candidate generation or ranking — interfaces designed so it can be swapped without touching either |
> | Ladder depth | **Level 0, 1, 2 only.** Level 3 (local refinement) and Level 4 (global Hou optimization) are explicitly deferred until every Level 2 test passes |
> | Engineering priority | correctness > geometric validity > manufacturability feasibility > deterministic ranking > optimization sophistication |
>
> **Revised after review, 2026-08-08** — full rationale in §16:
>
> | Decision | Choice |
> |---|---|
> | **On-surface invariant** | ⭐ **H0, ahead of every other gate.** Every segment must be backed by an OCC edge curve or `S(u,v)` on a named face; deviation measured against the **B-Rep** (never the mesh or the camera projection); failing candidates are not ranked, rendered, or surfaced. Geometry is the source of truth, display is derived (§9.5) |
> | Primary validity test | **H3** (topological separation), not H7 (coverage). H7 is a provisional sanity gate and a ranking signal. If they disagree, H3 wins |
> | Undercut intersection | **Not infeasibility.** Disqualifies the loop as a *main-split* candidate and routes the feature to side-action analysis (`side_core.py`) |
> | `κ_min` | **0.50, provisional**, calibrated from corpus data in P3a. Never quoted as a manufacturing law |
> | Enumeration strategy | **Measure `μ` across the corpus before writing any search code.** If `μ = 1` dominates, Johnson and beam search are never built |
> | Confidence output | **Banned.** No labelled outcomes ⇒ no calibrated probabilities. Report feasibility / tier / invariants / evidence separately |
> | Runtime | **No SLA provided, none invented.** Instrument per stage, publish p50/p95, optimize only measured bottlenecks |
> | Part3 ground truth | **None exists.** F16 scored on feasibility, fragmentation, and honesty — never correctness |
> | Side-action referrals | **Emit only.** `side_core.py` is not called from v2 in P0–P6; the v2 package must not import it. Interface preserved so auto-routing switches on later without a data-model change |
> | `readiness` / `confidence` | **`null` + `deprecated`** for backward compatibility. v2 never computes or relabels them. Consumers migrated in P5; fields removed in a later breaking API version |
>
> **Upstream inputs, treated as given:** unit pull direction `d̂`, and the
> undercut feature set. Owned by teammates. This plan defines the *contract*
> for consuming them (§10) and never re-derives them.

---

# PART I — THE MATHEMATICS

## 1. Formal problem statement

Before choosing an algorithm, state the problem. Everything downstream is
judged against this.

**Given**
- A closed, orientable B-Rep solid `S` with boundary `∂S`, composed of faces
  `{f_i}`, each a parametric patch `S_i(u,v)` over domain `D_i`.
- A unit pull direction `d̂ ∈ ℝ³`.
- An undercut face set `U ⊆ {f_i}` from the upstream detector.

**Find** a curve `Γ ⊂ ∂S` such that:

| # | Requirement | Formal statement |
|---|---|---|
| C1 | Closed | `Γ` is a **disjoint union of simple closed curves** `Γ = Γ₁ ⊔ … ⊔ Γₖ`, each closed within `τ_close` |
| C2 | Simple | `Γ` does not self-intersect |
| C3 | Lies on the part | every point of `Γ` is on `∂S` |
| C4 | **Separates** | `∂S \ Γ` has **exactly two** connected components `R⁺`, `R⁻` |
| C5 | Orientation-consistent | `n̂·d̂ ≥ −ε` a.e. on `R⁺`, and `n̂·d̂ ≤ +ε` a.e. on `R⁻` |
| C6 | Undercut-clear *(main split only)* | `Γ ∩ U = ∅`. Violating loops are **routed to side-action analysis**, not discarded — see H5 |

**Then** among all `Γ` satisfying C1–C6, select the one that minimizes an
ordered (lexicographic) engineering cost — §8.

> **This is the definition the current code never wrote down.** C4 in
> particular — the Jordan-curve condition on the surface — is the "does it
> actually separate the geometry" test the audit found missing (RC-5), and it
> is what makes core/cavity classification fall out for free (§9).

> ### ⚠ C1 corrected 2026-08-09 — `Γ` is not a single loop
>
> An earlier draft required `Γ ≅ S¹` — **one** closed curve. That is wrong for
> any part with a through-hole, and it was caught by fixture F9 during P1.
>
> Measured on F9 (box + through-hole, pull `+Z`): cutting the outer top rim
> alone leaves the top face still connected to the bottom face **through the
> hole's cylindrical wall**, so `∂S \ Γ` has **1** component and H3 correctly
> rejects it. The parting line that actually separates the part is the
> **outer rim ⊔ hole rim** — two disjoint closed curves. Verified: that union
> yields exactly 2 regions, `{top face}` and the rest.
>
> This is a genuine flaw in the formal statement, not an implementation bug.
> A part of genus `g` generally needs `g + 1` loops, and holes are ubiquitous
> in real automotive plastic parts — so the single-loop model would have made
> a large fraction of real geometry unanalysable.
>
> **C4 is unchanged and remains the arbiter**: exactly two components. It is
> C4 that decides how many loops are needed, which is why making the
> topological separation test primary (§7.0) was the right call — the test
> caught the error in the definition above it.

**Decision variables:** which curve segments (from a generated pool) form the
loop set. Combinatorial, not continuous. That matters — it rules out gradient
methods and rules *in* graph algorithms.

**Feasible region:** the set of closed simple separating loops. Possibly
empty. **The pipeline must be able to say "empty".** Today it cannot (RC-4).

---

## 2. The visibility function `g`

Everything reduces to one scalar field on the boundary.

```
        g : ∂S → [−1, +1]
        g(p) = n̂(p) · d̂
```

where `n̂(p)` is the **outward** unit normal. On a face patch:

```
        S_u = ∂S/∂u ,  S_v = ∂S/∂v
        N   = S_u × S_v
        n̂   = ± N / ‖N‖          (sign flipped if face orientation is REVERSED)
        g(u,v) = n̂(u,v) · d̂
```

Interpretation (this is exactly back-face culling):

| `g` | Meaning | Mold |
|---|---|---|
| `g > +ε` | faces toward `+d̂` | cavity-accessible |
| `g < −ε` | faces toward `−d̂` | core-accessible |
| `\|g\| ≤ ε` | perpendicular to pull | **silhouette band** — zero-draft wall |

And the draft angle is `α = 90° − θ = asin(|g|)` — the same identity already
implemented at `geometry_models.py:357`.

**The silhouette is the zero set of `g`:**

```
        Σ = { p ∈ ∂S : g(p) = 0 }
```

### 2.1 The critical structural fact

`∂S` is **piecewise** smooth. `g` therefore has two qualitatively different
kinds of zero, and they need two different algorithms:

| Where | Behaviour of `n̂` | Silhouette condition | Method |
|---|---|---|---|
| **Face interior** | continuous | `g(u,v) = 0` — an implicit curve in `(u,v)` | **Track B** — §4 |
| **Sharp edge** | *set-valued*: jumps from `n̂_a` to `n̂_b` | `0 ∈ [g_a, g_b]` — i.e. `g_a` and `g_b` **straddle zero** | **Track A** — §3 |

> **This is the central design insight of the whole plan.**
> The existing code implements **only Track A**, and implements it with
> face-*centroid* normals. Track A is *correct for sharp edges* and *cannot
> see* face-interior silhouettes. The two tracks are **complementary, not
> redundant** — together they cover `Σ` completely.
>
> RC-1 and RC-2 are therefore not one bug but a missing half of the method.

---

## 3. Track A — silhouette at sharp edges (fixing what exists)

For an edge `e` with adjacent faces `f_a`, `f_b`:

```
        g_a = n̂_a(uv_e) · d̂
        g_b = n̂_b(uv_e) · d̂
        e is a silhouette edge  ⟺  g_a · g_b < 0   (strict straddle)
        e is a tangent/zero-draft edge  ⟺  max(|g_a|, |g_b|) ≤ ε
```

**The one change that matters:** evaluate `n̂_a`, `n̂_b` **at the edge**, not at
each face's UV centroid.

> ✅ **The primitive already exists in this codebase and is unused by
> `parting_line.py`.**
> `step_loader._face_normal_at_uv(face, u, v)` (`step_loader.py:656`) returns
> the orientation-corrected outward normal at an arbitrary `(u,v)`, and
> `_compute_edge_convexity` (`step_loader.py:588-653`) already demonstrates the
> exact recipe: `BRep_Tool.CurveOnSurface(edge, face)` gives the pcurve, whose
> parameter is shared with the edge's own 3-D curve parameter, so one
> mid-parameter value evaluates both faces consistently.

**Improvement over mid-parameter only:** sample at `K` parameters along the
edge (`K = 5` default, more for long/curved edges per §6.3), giving
`g_a(t_k), g_b(t_k)`. This detects an edge that is silhouette over only part
of its length — sub-segment splitting at the crossing parameter, found by
bisection/Newton on `t`:

```
        find t* ∈ [t_k, t_{k+1}]  such that  g_a(t*)·g_b(t*) = 0
```

**Cost:** `O(E · K)` `GeomLProp_SLProps` evaluations. On a 3,000-edge part
with `K=5` that is 30,000 surface evaluations — sub-second. Cache per
`(face_id, u, v)`.

**Output:** curve segments, each = a polyline sampled along the edge's real
3-D curve, tagged `provenance="edge"`, `edge_id`, `face_ids`.

### 3.1 Zero-draft (tangential) edges

When `|g_a| ≤ ε` **and** `|g_b| ≤ ε`, the edge sits in a zero-draft band, not
at a clean sign flip. These must be tagged `kind="tangential"` and handled by
§5.3 (band collapse) — **not** promoted to silhouette. The current code's
`near_parting` kind conflates these two very different situations.

---

## 4. Track B — silhouette curves in face interiors (new)

### 4.1 Analytic surfaces — closed form

Most automotive plastic B-Rep area is analytic. Solve `g = 0` exactly.
`face.surface_type` is already available from the loader.

Let `(x̂, ŷ, â)` be an orthonormal frame with `â` = surface axis, and
```
        a = x̂·d̂ ,   b = ŷ·d̂ ,   c = â·d̂ ,   R = √(a²+b²) ,   φ = atan2(b, a)
```

| Surface | Normal | `g` | Zero set `Σ_f` |
|---|---|---|---|
| **Plane** | constant `n̂` | constant | **empty** if `g≠0`; **entire face** if `g=0` (zero-draft wall) |
| **Cylinder** (radius `r`, axis `â`) | `n̂(u) = cos u·x̂ + sin u·ŷ` (independent of `v`) | `R·cos(u−φ)` | `u = φ ± π/2` — **two straight rulings**. Degenerate (`g≡0`, whole face) iff `R = 0`, i.e. `d̂ ∥ â` |
| **Cone** (half-angle `α`) | `n̂(u) = cos α(cos u·x̂ + sin u·ŷ) − sin α·â` | `cos α·R·cos(u−φ) − sin α·c` | `u = φ ± arccos(tan α · c / R)` — **two rulings**, existing iff `\|tan α·c/R\| ≤ 1` |
| **Sphere** (centre `C`) | `n̂ = (p−C)/r` | `(p−C)·d̂ / r` | the **great circle** ⟂ `d̂`. Always exists |
| **Torus** (`R_maj`, `r_min`) | `n̂(u,v) = cos v(cos u·x̂+sin u·ŷ) + sin v·â` | `cos v·R·cos(u−φ) + c·sin v` | `tan v = −R·cos(u−φ)/c` (if `c≠0`); else `u = φ ± π/2`. A genuine curve, evaluable in closed form per `u` |

**Two consequences worth stating explicitly:**

1. **A cylinder or cone yields *straight* silhouette lines.** The classic
   split line on a shaft. Track A can never find these — they are interior
   isoparametric curves, not B-Rep edges.
2. **A cylinder pulled along its own axis is degenerate**: `g ≡ 0` over the
   entire lateral face. This is the case from your cylinder sketch. There is
   **no unique silhouette curve** — *every* circumferential ring is an equally
   valid parting line. That is not a bug and not a failure; it is a genuine
   **infinite family of equal optima**, and it belongs in the pathological
   test set (§12 — F1, F2, F14). The engine must detect it, report it as such, and
   break the tie **deterministically** (§8.3) rather than pretend to have
   found "the" answer.

### 4.2 Free-form surfaces — marching squares + Newton

For B-spline / Bézier / offset / any `surface_type` without a closed form:

**Step 1 — sample.** Build an `N_u × N_v` grid over the (clamped, via the
existing `_clamp_uv`) UV domain. Evaluate `g_{ij} = g(u_i, v_j)`.

**Step 2 — grid resolution, scale-aware (fixes RC-9).** Do not use a fixed
grid. Derive it from a **sag tolerance**. For a curve of curvature `κ`
sampled with chord `h`, the chordal deviation (sag) is

```
        sag ≈ h²·κ / 8      ⟹      h ≤ √(8·τ_sag / κ)
```

Take `τ_sag = bbox_diag × 1e-3` (configurable) and bound `κ` per face using
`GeomLProp_SLProps`' principal curvatures at a coarse pre-pass. Then

```
        N_u = clamp( ⌈ L_u / h ⌉ , N_min=8 , N_max=256 )
```

where `L_u ≈ (u_max−u_min)·‖S_u‖` at mid-`v`. This is the same principle
OCC's own `BRepMesh` deflection uses, so it is defensible and familiar.

**Step 3 — crossings.** For each grid edge with `g_i · g_j < 0`, linear
interpolation seeds `t₀ = g_i / (g_i − g_j)`, then **Newton refine** in
parameter space:

```
        t_{k+1} = t_k − g(t_k) / ( ∇g · Δ )
        ∇g = (∂g/∂u, ∂g/∂v)      Δ = (u_j−u_i, v_j−v_i)
```

`∇g` by central differences on `g` (robust) — 3–4 iterations converge to
`|g| < 1e-9` in practice. Fall back to bisection if Newton diverges.

**Step 4 — connect.** Standard marching-squares 16-case table. Resolve the two
ambiguous saddle cases (5 and 10) by sampling `g` at the **cell centre** and
using its sign — the cheap, deterministic form of the asymptotic decider.
Never resolve ambiguity arbitrarily; determinism is a hard requirement (§8.3).

**Step 5 — trim to the face.** A face's UV domain is a rectangle, but the face
itself is bounded by its wires. Discard curve points outside via
`BRepTopAdaptor_FClass2d` / `BRepClass_FaceClassifier` (`TopAbs_IN`). Clip
segments that cross a wire at the crossing point — those become **connection
vertices to Track A segments**, which is precisely how the two tracks stitch
together.

**Step 6 — lift to 3-D.** `p = S(u,v)` for each refined `(u,v)`. Output
polyline segments tagged `provenance="face_interior"`, `face_id`.

### 4.3 Degenerate regions

If `|g| ≤ ε` over a whole *area* of a face (zero-draft wall), marching squares
produces a band of noise, not a curve. **Detect and handle explicitly:**

```
        if max|g| over the face ≤ ε:   tag face  DEGENERATE_ZERO_DRAFT
```

Do not emit interior curves for it. Instead record it as a *region* for §5.3.

---

## 5. Graph construction

### 5.1 Nodes and edges

Following your Option 2 — and it is the right choice, for a reason worth
naming: nodes = faces (Option 1) answers *"which side is this face on"*, which
is the **core/cavity** question; nodes = curve endpoints answers *"which
segments form a loop"*, which is the **parting-line** question. We need both,
for their respective stages (§9 uses Option 1).

```
        Node  = a welded 3-D point (endpoint of one or more segments)
        Edge  = one silhouette curve segment (from Track A or Track B)
```

### 5.2 Vertex welding tolerance (fixes RC-9)

The current flat `point_tolerance = 1e-4 mm` is scale- and
kernel-blind. Replace with:

```
        τ_weld(v) = max( BRep_Tool.Tolerance(vertex_v) ,      # the kernel's own
                         bbox_diag × 1e-6 ,                    # scale-relative
                         1e-7 mm )                             # absolute floor
```

**Why:** a STEP file carries its own per-vertex tolerance, set by the
originating CAD system. Ignoring it is the standard cause of "the same model
works in NX and fragments in our tool." Use a spatial hash / KD-tree keyed at
`τ_weld` rather than the current integer quantization, which has a
grid-boundary failure mode (two points `0.6·τ` apart can land in different
cells).

### 5.3 Zero-draft band collapse

For each `DEGENERATE_ZERO_DRAFT` region (§4.3), the band's two boundaries
would otherwise enter the graph as two parallel loops. Instead:

- Compute the band's **medial curve** — for a swept/extruded band, the
  iso-curve at the mid-value of the pull coordinate `p·d̂`.
- Emit **one** segment set for that band, tagged `kind="zero_draft_band"`,
  carrying `band_span_mm = max(p·d̂) − min(p·d̂)` over the band.
- Record that the parting line's position within this band is **free** — a
  genuine degree of freedom, not a determined answer. Report it. (Level 3
  would optimize within it; we are not building Level 3.)

### 5.4 Graph reduction — do this before any search

Two `O(V+E)` reductions that collapse most real graphs to something trivial:

1. **2-core reduction.** Iteratively delete every node of degree ≤ 1. A
   degree-1 node cannot lie on any cycle. Repeat to fixpoint. What remains is
   the 2-core — the only part of the graph that can contain a loop.
2. **Degree-2 chain contraction.** Replace every maximal path of degree-2
   nodes with a single super-edge carrying the concatenated polyline and
   summed length. (The existing `_contract_degree2_chains`, `parting_line.py:2746`,
   already does this — port it.)

**After both reductions, a clean silhouette becomes a single cycle with zero
branch nodes.** That is the common case, and it costs `O(V+E)`.

> **Diagnostic value:** branch nodes surviving reduction are not noise —
> each has a specific geometric cause. Report which:
> - a zero-draft band boundary that §5.3 failed to collapse,
> - a non-manifold or self-touching region of the B-Rep,
> - a tolerance artefact (two nearby-but-unwelded vertices),
> - a genuine topological branch (the part really does have multiple valid
>   loops through this point — e.g. a hole rim meeting the outer silhouette).
>
> Only the last is a real optimization question. The first three are data
> problems that should be *fixed*, not *optimized around*. The existing engine
> treats all four identically, which is why bridging accumulated so much
> heuristic (RC-10).

---

## 6. Loop enumeration — the candidate set (fixes RC-3)

### 6.1 Decision: which algorithm, and why

You listed DFS / Union-Find / Johnson / Tarjan. The honest answer is that the
choice depends on the graph *after* §5.4 reduction, so branch on it:

| Reduced graph | Cyclomatic number `μ = E − V + P` | Strategy | Cost |
|---|---|---|---|
| Empty | — | **Reject**: no loop exists. Report it. | `O(1)` |
| Single cycle, no branch nodes | `μ = 1` | **Done.** One candidate. | `O(V+E)` |
| Small branching | `μ ≤ μ_max` (default 12) | **Johnson's algorithm**, bounded by `K_max` candidates and a wall-clock budget | output-sensitive |
| Heavy branching | `μ > μ_max` | **Fundamental cycle basis** (μ cycles, from a spanning tree, `O(E)`) **+ beam search** at branch nodes | `O(B · E)` |

> ### ⛔ Build order: measure `μ` before implementing any of this
>
> **Do not build Johnson enumeration or beam search in P2.** §5.4 predicts
> that after welding → 2-core → degree-2 contraction, most parts collapse to a
> single cycle (`μ = 1`), where the answer is immediate and no search is
> needed at all. If that prediction holds, a sophisticated cycle-search engine
> is dead code protecting against a case that does not occur.
>
> **Mandatory gate (P3, §12):** instrument the reduction to emit `μ`, node
> count, edge count, and branch-node count for **every part in the corpus**,
> and publish the distribution *first*. Then decide:
>
> | Measured `μ` distribution | Build |
> |---|---|
> | `μ = 1` on ≳ 90% of parts | Single-cycle path + cycle basis only. **Skip Johnson and beam entirely.** |
> | Long tail of `2 ≤ μ ≤ 12` | Add bounded Johnson. Still skip beam. |
> | Real mass at `μ > 12` | Add beam search — and only then |
>
> This is your point 17 (profile before optimizing) applied to the algorithm
> rather than the implementation. The strategy table above is the *design*;
> which branches get written is a decision the corpus makes, not this document.

**Why not just Johnson everywhere:** simple-cycle count is exponential in `μ`.
Bounding is mandatory, and bounding must be *reported*, never silent — the
current engine's hidden `search_edge_limit = 22` / `max_search_states = 75_000`
(hardcoded at `parting_line.py:3238-3239`, violating config invariant #4) is
exactly the failure mode to avoid.

**Why not just cycle basis everywhere:** a fundamental cycle basis spans the
cycle *space*, but its `μ` members are not necessarily the `μ` most
*physically meaningful* loops — a basis cycle can be a small artefact loop.
It is a good cheap **seed set**, not a complete candidate set.

### 6.2 Beam search at branch nodes

When arriving at a branch node along segment `e_in`, rank continuations
`e_out` by a **local geometric** criterion (not the global score — that comes
later, §8):

```
        turn(e_out) = arccos( T_in · T_out )     T = unit tangent at the node
        Δg(e_out)   = |mean g along e_out|        (silhouette stays near g=0)

        local_cost  = w_t · turn + w_g · Δg
```

Keep the best `B` (default 3). This is your Option C from Lecture 3 —
"follow connected silhouette edges while respecting their geometric
orientation" — and it is CAD-aware in the way generic cycle enumeration is
not. **Tangent continuity is the dominant term**: a real silhouette curve is
`C¹` almost everywhere, so the correct continuation is nearly always the
straight-ahead one.

### 6.3 Output

A `list[PartingLoopCandidate]`, each carrying its segments, its polyline, its
provenance mix, and **how it was found** (`single_cycle` / `johnson` /
`cycle_basis` / `beam`). Bound: `K_max` (default 200) with the bound and
whether it was hit both reported.

---

## 7. Hard feasibility filter (fixes RC-4, RC-5)

**Every candidate passes or is rejected with a named reason. Nothing is
scored until it has passed.** This is the separation you insisted on, and it
is the single most important structural change in this plan.

```
    candidate ──► H0 ─► H1 ─► H2 ─► H3 ─► H4 ─► H5 ─► H6 ─► H7 ──► feasible pool
                   │     │     │     │     │     │     │     │
                   └─────┴─────┴─────┴─────┴─────┴─────┴─────┴──► rejected(reason)
```

Ordered cheapest-first so expensive tests run on few candidates — **except
H0, which runs first regardless of cost**, because every test after it is
measuring a curve that must be proven to be on the part.

### 7.0 The gates are not equal — read this before implementing

They fall into three classes, and conflating them is how a heuristic gets
mistaken for a law.

| Class | Tests | Status |
|---|---|---|
| **Definitional** — falsifying one means it is *not a parting line* | **H0** on-surface, **H1** closed, **H2** simple, **H3** separates, **H6** non-degenerate | Mathematical consequence of §1's C1–C4. Not tunable. Not negotiable. |
| **Physical** — falsifying one means it is not a *mold* split | **H4** orientation consistency | Follows from C5. `ε_orient` and `ρ_max` are tolerances on a real physical condition, not preferences. |
| **Routing / sanity** — falsifying one means *something else should handle this* | **H5** undercut, **H7** coverage | ⚠ **Heuristic.** Provisional thresholds. See each test's own caveat. |

> **H3 is the primary validity criterion.** "Does this curve actually
> partition the part into the two regions a mold needs?" is the fundamental
> question, and it is topological — it needs no tuned constant.
>
> **H7 (coverage) is a conservative sanity check and a strong ranking signal
> — not a definition of validity.** There is no manufacturing law stating a
> valid parting line covers ≥ X% of projected area, and §8.1's cheap
> denominator is a Cauchy-type **upper bound** on non-convex parts, so the
> measured ratio is itself conservative. Treat a H7 rejection as *"this is
> very probably a local feature loop, look at it"*, never as *"this is
> geometrically invalid"*. If H3 and H7 ever disagree, **H3 is right.**

### H0 — ON-SURFACE VALIDITY ⭐ (runs before everything)

> **The invariant, stated once and non-negotiably:**
>
> **Every parting-line segment must be backed by either an OCC B-Rep edge
> curve or a parameterized point/curve on a specific B-Rep face. Its 3-D
> representation is obtained from the underlying OCC geometry — the edge
> curve, or `S(u,v)` — never from an unconstrained fitted, projected, or
> smoothed curve. Maximum deviation from the B-Rep must be measured and
> reported. Any candidate exceeding tolerance fails validation and is not
> rendered as a parting line.**

**Why this is H0 and not a P5 display concern.** §1 already states this as
**C3** ("lies on the part") — but the first draft of this filter had no test
enforcing C3. A requirement in the formal statement with no gate behind it is
decoration. And the audit's RC-7 documents the exact mechanism by which v1
violates it: `raw_points → resample → Chaikin(8) → refined_points`, where
Chaikin is an **approximating** subdivision scheme, and those drifted points
are what feed `_build_parting_surface` (`parting_line.py:4612`), the API
payload, the viewer, and `silhouette_coverage_ratio`. **That is the
levitating parting line.** It is a geometric defect, not a rendering one.

The correct data flow, and the only one permitted:

```
    CAD B-Rep
       │
       ├── existing edge ──────► exact 3-D edge curve  (BRepAdaptor_Curve)
       │
       └── face-interior silhouette
                 ↓
              (u,v)                   ← solved in parameter space
                 ↓
              S(u,v)                  ← evaluated on the real surface
                 ↓
              exact 3-D surface point
```

Explicitly forbidden:

```
    silhouette calculation ──► 2-D projected curve ──► "draw approximately here"
```

#### The four sub-tests

```
    H0.1  Provenance      every segment carries a resolvable OCC backing:
                          ("edge", edge_id)  or  ("face", face_id, [(u,v)…])
                          A segment with no backing is REJECTED, not repaired.

    H0.2  Edge-derived    for each point p from an edge segment:
                          dist(p, edge_curve)      ≤ τ_edge

    H0.3  Face-derived    for each point p = S(u,v) from a face segment:
                          (u,v) classifies TopAbs_IN on that face   (FClass2d)
                          |g(u,v)|                 ≤ τ_silhouette
                          dist(p, face_surface)    ≤ τ_surface

    H0.4  No projection-only geometry
                          no segment may exist solely in the pull-normal
                          plane. Projection is an ACCELERATION for H2 and a
                          MEASURE for T1 — never a source of geometry.
```

#### How deviation is measured — against the B-Rep, never the mesh

This matters and is easy to get wrong. A curve can look perfect from the
camera and still sit 0.5 mm off the surface:

```
           _________
          /  PART   \
         /___________\
            --------          ← looks correct in projection
                              ← may be 0.5 mm above the real surface in 3-D
```

So validation runs against the **actual OCC geometry**:

- edge points → `BRepAdaptor_Curve` + `GeomAPI_ProjectPointOnCurve`
- face points → `GeomAPI_ProjectPointOnSurf` against `BRep_Tool.Surface(face)`,
  plus a `BRepClass_FaceClassifier` / `BRepTopAdaptor_FClass2d` containment
  test so a point on the *surface* but outside the *face's trimmed region*
  still fails

**Never** against the display tessellation, and **never** against the camera
projection. Both are derived artefacts with their own error.

#### Output — an automated validator, not an eyeball check

```
    PartingLineValidation
    ---------------------
    on_surface             = PASS
    max_surface_deviation  = 0.000004 mm
    max_edge_deviation     = 0.000002 mm
    max_silhouette_error   = 0.000001        (max |g| along Γ)
    off_face_point_count   = 0
    unbacked_segment_count = 0
```

```python
@dataclass(frozen=True)
class OnSurfaceReport:
    passed: bool
    max_surface_deviation_mm: float
    max_edge_deviation_mm: float
    max_silhouette_error: float          # max |g| on Γ
    off_face_point_count: int
    unbacked_segment_count: int
    worst_offender: tuple[int, Vec3] | None   # (segment_id, point)
```

**If `on_surface = FAIL`, the candidate is not ranked, not rendered as a
parting line, and not passed to the surface provider.** It may still be shown
as a *diagnostic overlay*, clearly labelled as failing.

#### Tolerances (scale-aware, §13)

```
    τ_surface     = max( bbox_diag × 1e-6 , max face tolerance , 1e-7 mm )
    τ_edge        = max( bbox_diag × 1e-6 , BRep_Tool.Tolerance(edge) , 1e-7 mm )
    τ_silhouette  = silhouette_epsilon × 0.1        (10× tighter than the band)
```

`τ_surface` and `τ_edge` are **max'd with the kernel's own declared
tolerance** for the specific face/edge — the same principle as §5.2's welding
tolerance. A STEP file from a different CAD system carries different
tolerances, and ignoring them is the standard cause of "works in NX, fails
here".

---

### H1 — Closed
```
        ‖P_end − P_start‖ ≤ τ_close       τ_close = max(bbox_diag × 1e-5, τ_weld)
```

### H2 — Simple (non-self-intersecting)

Two-phase, and the direction of the logic matters:

1. **Project** the loop into the pull-normal plane (basis from
   `_projection_basis`, `parting_line.py:1592` — port it). Run a sweep-line
   (Bentley–Ottmann) segment-intersection test, `O((n + k) log n)`.
2. **If zero 2-D crossings → PASS, proven.** Projection can only *create*
   apparent crossings, never destroy real ones, so "no crossing in 2-D" is a
   *proof* of "no crossing in 3-D".
3. **If 2-D crossings exist**, they may be spurious. Decide in **3-D**: for
   each flagged non-adjacent segment pair compute the minimum distance between
   the two 3-D segments; a true intersection iff `d_min < τ_weld`.

> This is your "use 3-D first, projection as acceleration" advice implemented
> in the only order that is actually sound: projection as a **conservative
> filter**, 3-D as the **decider**.

### H3 — Separates `∂S` into exactly two regions ⭐ (the core test)

This is C4, and it is what the current engine approximates with a bounding-box
ratio.

1. **Split faces.** Any face carrying a Track-B interior curve is subdivided
   in UV by that curve into sub-regions. Faces without one stay whole.
2. **Build the region-adjacency graph** (Option 1 from your framing): nodes =
   sub-regions; connect two if they share boundary that is **not** part of
   `Γ`.
3. **Count connected components.**

```
        components == 2   →  PASS.  R⁺, R⁻ fall out directly → §9
        components == 1   →  REJECT "loop does not separate the part"
        components  > 2   →  REJECT "loop over-partitions (n regions)"
```

**Level-0 cheap variant** (exact whenever `Γ` runs only along B-Rep edges, so
exact for the whole Level-0 baseline): skip step 1 and use the existing
`part.face_adjacency`, deleting adjacencies whose shared edge is on `Γ`. Count
components. `O(F + E)`.

> **This test replaces `silhouette_coverage_ratio` as the gate.** Coverage
> stays as a *ranking* key (§8, T1) — a real geometric measure — but the
> pass/fail decision is topological, which is what "does it separate the mold"
> actually means.

### H4 — Orientation consistency (C5)

For each region `R` in component A, area-weighted:
```
        violation_area(A) = Σ_{r ∈ A}  area(r) · [ mean_g(r) < −ε_orient ]
        REJECT if violation_area(A)/area(A) > ρ_max      (default ρ_max = 0.02)
```
and symmetrically for B. This catches a loop that closes and separates but
puts up-facing and down-facing geometry on the same side — geometrically
valid, physically not a mold split.

### H5 — Undercut interaction (C6) — a **routing** decision, not a verdict

> ⚠ **Corrected 2026-08-08.** An earlier draft of this plan said
> `REJECT if Γ touches an undercut face`, full stop. **That is too strong and
> would have been wrong.** An undercut does not make a design impossible — it
> makes it require a **side action**: a side core, lifter, insert, or
> collapsible core. Bosch's own criteria explicitly include side cores and
> lifters, and this repo already has `backend/geometry/side_core.py` (Stage 4)
> built to handle exactly that. A filter that declared such parts infeasible
> would reject the very geometry the project exists to analyse.

Correct semantics — the candidate is disqualified **as a main-split
candidate**, and the offending feature is **routed onward**:

```
        Γ intersects a confirmed undercut face
                    ↓
        DISQUALIFY as MAIN-SPLIT candidate       ← not "part impossible"
                    ↓
        EMIT SideActionReferral(feature_ids, segments, release_direction_hint)
                    ↓
        → side_core.py  (Stage 4)  decides what tooling resolves it
```

```python
@dataclass(frozen=True)
class SideActionReferral:
    feature_ids: tuple[int, ...]
    conflicting_segment_ids: tuple[int, ...]
    conflict_length_mm: float
    note: str          # "main parting line cannot pass cleanly through this
                       #  feature; requires a side action"
```

Rules:

1. The rejection reason string is **`"requires_side_action"`**, never
   `"infeasible"` / `"impossible"`.
2. Referrals are returned on the result even when *every* candidate is
   disqualified — a part whose only loops cross undercuts is a part that
   **needs side actions**, which is a finding, not a failure.
3. **Never claim the tooling mechanism.** Per
   `.claude/rules/honesty-and-scope.md`, `side_core.py` answers only *"what
   volume must retract, along which direction"* — it does not decide lifter
   vs. slide vs. collapsible core. The referral carries a
   `release_direction_hint`, not a mechanism.
4. `undercut_proximity` stays a **soft ranking key** (T2, §8) for candidates
   that pass — skirting close to an undercut is a preference, not a gate.
5. ⛔ **Emit only. `side_core.py` is NOT called from v2 in P0–P6** — the v2
   package must not even import it, enforced by the module-dependency test.
   The referral carries everything Stage 4 would need so automatic routing
   can be switched on later without a data-model change. **§12.8.**

This also corrects §1's C6, which should read: *`Γ ∩ U = ∅` for the **main**
parting line; loops violating it are routed to side-action analysis rather
than discarded.*

### H6 — Non-degenerate
```
        length_3d(Γ) ≥ bbox_diag × 0.05
        |projected signed area| ≥ (bbox_diag)² × 1e-4
        distinct point count ≥ 4
```

### H7 — Minimum coverage — **provisional sanity gate**
```
        coverage(Γ) = A_proj(Γ) / A_proj(∂S)   ≥  κ_min
        κ_min = 0.50      ← PROVISIONAL. Not an engineering truth.
```

See §8.1 for how `A_proj(∂S)` is computed properly.

> ⚠ **`κ_min = 0.50` is a configuration decision, not a mathematical
> discovery.** An earlier draft of this plan quoted 0.60 in the config and
> 0.50 in the open questions — two different decisions stated as one.
> Resolved: **0.50 everywhere, explicitly labelled provisional**, calibrated
> against the corpus in P3 (§12).
>
> Why gate at all from P1 rather than warn: today's 0.35 threshold exists and
> is *only a warning*, which is precisely how Part3 reports `ready (0.806)` at
> 18.1% coverage. A provisional gate makes that silent pass impossible from
> day one. Why 0.50 rather than 0.60: it is the more conservative choice for
> a number we cannot yet defend — it rejects less, and over-rejection on a
> heuristic gate is the worse error.
>
> **What this gate does and does not mean** (see §7.0): a H7 rejection means
> *"very probably a local feature loop — look at it"*. It does **not** mean
> the loop is geometrically invalid. That is H3's job. Rejections carry
> reason `"below_provisional_coverage_gate"`, and the candidate is retained in
> the scorecard so a reviewer can overrule it.

Every H7 rejection is recorded with its measured coverage so P3 can compute
the distribution and set the real value from data.

### H-output

```python
@dataclass(frozen=True)
class FeasibilityReport:
    passed: bool
    failed_test: str | None          # "H3"
    reason: str                      # human-readable
    measurements: dict[str, float]   # every test's measured value, pass or fail
```

**Rejected candidates are retained and returned.** They are the material for
the AI agent's explanation ("Candidate B was geometrically cleaner but was
rejected at H3: it partitioned the part into 3 regions") and for debugging.

---

## 8. Lexicographic ranking of feasible candidates (Level 2)

**Not a weighted sum.** Your Candidate A/B table is the argument: with a
weighted sum, the weights decide the winner, and we have no evidence for any
particular weights. A priority ordering encodes *engineering precedence*,
which we can defend.

Ordering follows the locked priority: geometric validity → manufacturability
→ determinism.

| Tier | Key | Direction | Rationale |
|---|---|---|---|
| **T1** | `coverage` | **max** | Nee (1998) §5 maximum-contour rule. A parting line wraps the outer silhouette. Dominant criterion. |
| **T2** | `undercut_proximity` | **min** | A loop skirting an undercut risks a side action however pretty it is. (H5 already *referred out* loops running **through** undercuts; T2 ranks the survivors by **distance to** them.) |
| **T3** | `pull_axis_span_mm` | **min** | How far the mold must step along `d̂`. Directly proportional to tooling cost and mismatch/flash risk. |
| **T4** | `ambiguous_area_fraction` | **min** | Your criterion 3 (separability), made concrete — §8.2. |
| **T5** | `excess_turning` | **min** | Manufacturability/smoothness — §8.2. |
| **T6** | `length_3d_mm` | **min** | Less machining. Weak tie-break. |
| **T7** | `stable_id` | — | **Determinism.** Sorted tuple of segment IDs. Guarantees byte-reproducibility. |

Comparison uses a tolerance band per tier — `|Δ| ≤ tier_epsilon` counts as a
tie and falls through to the next tier — so near-equal candidates are not
separated by numerical noise (your point 15, fake precision).

### 8.1 `coverage` — done properly

The audit's RC-5 objection to today's metric is that it uses **bounding-box**
areas, so an L-shaped loop and a rectangle of equal extent score identically.
Replace both terms:

**Numerator** — the loop's true projected area, by the shoelace formula on the
projected polyline (the existing `_polygon_signed_area`, `parting_line.py:1622`,
is already correct):
```
        A_proj(Γ) = ½ | Σ_i (x_i·y_{i+1} − x_{i+1}·y_i) |
```

**Denominator** — the part's true projected outline area. Two ways:

*Cheap (default).* For a **closed** solid, integrate:
```
        A_cauchy = ½ · Σ_f ∫_f |n̂·d̂| dA  ≈  ½ · Σ_f A_f · |g_f|
```
Exact for a convex solid. For a non-convex solid the boundary projection covers
some points more than twice, so `A_cauchy ≥ A_true`. **State this honestly:
`A_cauchy` is an upper bound, which makes `coverage` a conservative
under-estimate — safe for a gate, but not a number to quote as "the" coverage
without the caveat.** (Use the mid-face `g_f` from the existing per-face
normal here; this is the one place a single sample is adequate, since it is an
area-weighted aggregate, not a sign decision.)

*Exact (verification path).* Project the part's display tessellation triangles
into the plane and compute the **union** area. Heavier, but exact, and we
already generate tessellation for the viewer. Use it in the validation
harness to quantify the `A_cauchy` overestimate per part, then decide whether
the cheap path is good enough. **Do not assume it is — measure it.**

### 8.2 The other measures, defined

**`pull_axis_span_mm`** — replaces PCA-based planarity, which caused a real
bug (Part3: PCA fits to 0.74 mm but 60° off the pull axis, `config.yaml:132-136`).
The mold-relevant quantity fixes the plane normal to `d̂`:
```
        s = max_i (P_i·d̂) − min_i (P_i·d̂)
```
`s = 0` ⟺ a flat parting plane. Measured today: Part1 16.16 mm / 30.78 mm
part, Part3 7.14 mm / 68.12 mm. **This number is also exactly the geometric
error the planar split tool introduces** — so reporting it is the honest
quantification of the approximation we are keeping (§11).

**`ambiguous_area_fraction`** — from H3's regions:
```
        ambiguous = Σ area(r) over regions with |mean_g(r)| ≤ ε  and  r ∉ ∂Γ
        fraction  = ambiguous / total_area
```
Your criterion 3: reward a loop after which ~95% of faces are cleanly core or
cavity, penalize one leaving 50% ambiguous.

**`excess_turning`** — resolves your own objection that "curvature = bad" is
wrong. Use *excess* turning over the minimum any closed planar loop must have:
```
        K = Σ_i θ_i ,  θ_i = arccos(T_i · T_{i+1})
        E = (K − 2π) / 2π              (clamped at 0)
```
- A **circle** — the correct parting line on a turned part — has `K = 2π`, so
  `E = 0`. **Not penalized.** This is the cylinder case from your Lecture 4,
  handled correctly by construction.
- A **rectangular housing** outline has `K = 2π` too. **Not penalized.** Your
  criterion-6 concern ("corners aren't automatically bad") is resolved.
- A **zigzag** accumulates turning well past `2π`. Penalized, correctly.

`E` is dimensionless, scale-invariant, and needs no tuned threshold. It is the
cleanest of the soft criteria and the one I would defend most confidently in
front of Bosch.

**`undercut_proximity`** — min distance from `Γ` to any undercut feature,
normalized by `bbox_diag`, inverted so smaller-is-better:
```
        prox = 1 / (1 + d_min/bbox_diag)
```

### 8.3 Determinism (your point 10)

Non-negotiable:
- No randomness anywhere. No `set` iteration order dependence — sort before
  every iteration over a set.
- Marching-squares saddle ambiguity resolved by cell-centre sign, never
  arbitrarily.
- Beam search ties broken by `stable_id`.
- **T7 guarantees a total order**, so the same input always yields the same
  loop, bit for bit.
- Regression test: run twice, assert identical `stable_id` and identical
  point list.

### 8.4 Output — a scorecard, not a score

Exactly as you specified:

```json
{
  "selected": {"candidate_id": 3, "stable_id": "a91c…"},
  "scorecard": [
    {"candidate_id": 3, "feasible": true,
     "coverage": 0.948, "undercut_proximity": 0.12, "pull_axis_span_mm": 16.16,
     "ambiguous_area_fraction": 0.031, "excess_turning": 0.08,
     "length_3d_mm": 214.7, "won_at_tier": "T1"},
    {"candidate_id": 7, "feasible": false,
     "failed_test": "H3", "reason": "partitions the part into 3 regions",
     "measurements": {"components": 3, "coverage": 0.91}}
  ],
  "bounds": {"k_max": 200, "k_max_hit": false, "mu": 4, "strategy": "johnson"}
}
```

The comparison sentence the agent can then produce — *"Candidate 3 was
selected on coverage (94.8% vs 91.0%); Candidate 7 was geometrically smoother
but was rejected because it partitions the part into three regions rather than
two"* — is worth far more to a Bosch reviewer than `Score = 88.2`.

---

## 9. Core/cavity, redesigned (fixes RC-8)

### 9.1 The key insight

**Core/cavity classification is a byproduct of H3, not an independent
computation.** H3 already produced `R⁺` and `R⁻` as connected components of
`∂S \ Γ`. Assign:

```
        cavity side = the component whose area-weighted mean g is positive
        core   side = the other
```

That is the whole classification, and by construction it is **consistent with
the parting line** — the contradiction described in RC-8 becomes structurally
impossible.

### 9.2 Faces that straddle

Your Lecture 4 §16 objection, handled directly:

```python
@dataclass(frozen=True)
class FaceClassification:
    face_id: int
    label: Literal["cavity", "core", "split", "ambiguous"]
    cavity_area_mm2: float      # non-zero for "split"
    core_area_mm2: float
    mean_g: float
    sample_count: int
```

- Face wholly in one region → `cavity` / `core`.
- Face **cut by `Γ`** → `label="split"`, **both** sub-areas reported. Never
  forced to one side. (Today the UV-centroid normal silently picks one.)
- Face in a zero-draft band not touching `Γ` → `ambiguous`, reported as such.

**Multi-sample validation** on top: sample `g` at an `M×M` UV grid per face
(`M=5` default, adaptive by area) and record `min_g`, `max_g`. If
`sign(min_g) ≠ sign(max_g)` on a face labelled non-`split`, that is an
**inconsistency** — count it, report it, do not hide it.

### 9.3 Independent validator (your point 12)

A separate function that **recomputes** the invariants from the outputs and
never trusts a flag:

```
        V1  every face is in exactly one of cavity/core/split/ambiguous
        V2  Σ(cavity_area + core_area + split areas + ambiguous) == total_area ± tol
        V3  no face labelled "cavity" has max_g < −ε        (and symmetric)
        V4  the cavity/core region sets are each connected
        V5  Γ's segments all lie on faces adjacent to both regions
        V6  ON-SURFACE (H0) re-verified independently of the filter:
              every Γ point within tau_surface / tau_edge of its OCC backing,
              every face-derived (u,v) classifies TopAbs_IN,
              max |g| along Γ <= tau_silhouette.
            Recomputed from the stored points + provenance, NOT read back
            from the OnSurfaceReport the filter produced.
```

Wire these into `part_validation.py` as `--assert-*` flags, matching the
existing pattern (which the audit credits as genuinely good).

### 9.4 What stays exactly as it is

The Boolean solid split, the blank construction, the volume-conservation
check, `export_mold_halves`, and the `split_tool_kind` honesty label all stay.
Per the locked decision, the planar approximation is retained and labelled —
see §11 for the boundary that keeps it out of the parting-line architecture.

---

## 9.5 Geometry is the source of truth; display is derived

The corollary of H0, and the rule that kills v1's "smooth it and hope"
behaviour.

```
                        PartingLoop
                             │
                 ┌───────────┴───────────┐
                 │                       │
            GEOMETRY                VISUALIZATION
        exact on-surface           tessellated for
        points + OCC backing         rendering
                 │                       │
                 └───────────┬───────────┘
                             ↓
                    the SAME underlying Γ
```

**Rules:**

1. **The raw on-surface representation is the source of truth.** Every
   consumer — the surface provider, the API payload, coverage and span
   measurement, the exporter, the agent — reads *that*, never the display
   curve. v1 inverts this: the Chaikin output is what everything downstream
   sees (RC-7).
2. **The renderer tessellates the geometric curve.** It does not
   independently fit a spline through the points. Tessellation may add
   points *along* the exact curve; it may not move them off it.
3. **No unconstrained 3-D smoothing.** Ordinary Chaikin/spline smoothing in
   ℝ³ is unconstrained and will leave the surface — that is precisely v1's
   defect, not an incidental one.
4. **If a smooth display curve is wanted, it must be surface-constrained**:
   smooth in each face's `(u,v)` domain and re-evaluate `S(u,v)`, so the
   result is on the surface by construction. Across a face boundary, smooth
   only within the tangent-continuous run, or re-project each smoothed point
   with `GeomAPI_ProjectPointOnSurf`.
5. **Even then, smoothing is visualization-only unless it proves its
   deviation.** A smoothed representation may be promoted to geometry only if
   it passes H0 in its own right, with its measured
   `max_surface_deviation_mm` reported. Otherwise it is tagged
   `display_only=True` and no downstream consumer may read it.

> **This promotes what the first draft had as a P5 display metric ("show the
> measured deviation between raw and smoothed") into a geometric invariant
> with a gate.** Displaying a number nobody blocks on is how the drift went
> unnoticed in v1 for the entire life of the feature.

---

## 10. Contracts

### 10.1 Upstream (teammates' modules)

Consume via explicit types, never by reaching into their internals:

```python
@dataclass(frozen=True)
class PullDirectionInput:
    direction: Vec3                # unit; validated ‖d‖ = 1 ± 1e-9 on entry
    source: Literal["optimizer", "user_override", "fixture"]
    confidence: float | None = None

@dataclass(frozen=True)
class UndercutInput:
    undercut_face_ids: frozenset[int]
    features: tuple[UndercutFeatureRef, ...]   # id, face_ids, severity, centroid
```

Adapters translate the current `direction_optimizer` / `undercut_detector`
outputs into these. If a teammate's module changes shape, only the adapter
changes. **Both inputs are validated on entry** — a non-unit `d̂` or a face id
not present in the part is a hard error, not a silent default. (Today
`classify_core_cavity` silently falls back to `+Z`, `core_cavity.py:137-139`.)

### 10.2 Downstream — the swappable surface boundary ⭐

Per the locked decision, this is the interface that keeps the planar
approximation from contaminating the architecture:

```python
class PartingSurfaceProvider(Protocol):
    def build(self, loop: PartingLoop, part: PartGeometry,
              d: Vec3) -> SplitTool: ...

@dataclass
class SplitTool:
    occ_shape: object
    kind: Literal["planar_approximation", "ruled_extension",
                  "face_extension", "brep_filled"]
    max_deviation_from_loop_mm: float   # MEASURED; 0.0 only if genuinely exact
    is_topologically_valid: bool        # BRepCheck_Analyzer, ALWAYS measured
    failure_reason: str | None
```

**Rules, enforced by review and by a test:**

1. **Candidate generation (§3–§6) and ranking (§8) never import, call, or
   reference `PartingSurfaceProvider`.** The selected parting line is a real
   geometric result about the part, independent of how we currently split it.
   A unit test asserts the module dependency direction.
2. `PlanarSplitToolProvider` — today's behaviour — reports
   `max_deviation_from_loop_mm = pull_axis_span_mm` (§8.2). **That number is
   currently computed nowhere and reported nowhere.** Surfacing it is the
   honest quantification of the approximation: "the split plane deviates from
   the true parting line by up to 16.16 mm on Part1."
3. A future `FaceExtensionProvider` (Method D from your Lecture 4 §10 — extend
   the faces adjacent to the loop and sew, which is the mold-aware
   construction and has never been attempted here) drops in behind the same
   Protocol with **zero changes** to §3–§9.
4. `is_topologically_valid` is measured on every build. The audit's RC-6 —
   an invalid surface shipped and displayed for weeks — was possible only
   because nothing in-module ever checked.

---

# PART II — THE EXECUTION PLAN

## 11. The ladder — and the discipline of climbing it

Your point 19, applied. **At every level, the question is "did the complexity
buy us something?" — measured, not asserted.**

```
  LEVEL 0   Baseline: Track A only, reduce, single-cycle-or-basis,
            full hard filter, lexicographic rank
              │  ← measure everything here. This is the reference.
  LEVEL 1   Track B: face-interior silhouette curves (analytic + marching squares)
              │  ← must beat Level 0 on the corpus or it does not ship
  LEVEL 2   Bounded loop enumeration (Johnson / basis+beam) + full H0–H7
              │  ← STOP HERE for this milestone
  ─────────────────────────────────────────────────────────────
  LEVEL 3   Constrained local refinement (deferred — needs Level 2 green)
  LEVEL 4   Global Hou-style optimization (deferred)
```

**We are building 0, 1, 2.** Levels 3 and 4 are named here only so the
interfaces do not preclude them.

---

## 12. Phases, with exit gates

Each phase has a **measured** exit gate. No phase is "done" on a green mock
suite — the audit's cross-cutting finding X.1 was that every 2026-07-27 bug
survived a fully green mocked test suite.

### P0 — Contracts, fixtures, harness *(no algorithm yet)*

**Build**
- `backend/geometry/parting_line_v2/` package: `types.py`, `contracts.py`.
- All dataclasses from §6.3, §7, §8.4, §9.2, §10.
- Feature flag `dfm.parting_line.engine: "v1" | "v2"` (default `v1`).
- Synthetic fixture generator → `data/fixtures/synthetic/` (**new directory**
  — `data/parts/` is read-only per CLAUDE.md invariant #2). Built with
  **cadquery**, already a conda dependency.
- A/B harness: run v1 and v2 on the same part+direction, emit a comparison
  table of every §8 measure plus runtime.

**Fixtures — with analytic ground truth**

Built deliberately around **algorithmic failure modes**, not around "some CAD
models". Every synthetic fixture has a checkable answer.

| # | Fixture | Pull | Known answer | Failure mode it targets |
|---|---|---|---|---|
| **F1** | Cube | `+Z` | 4 side faces zero-draft; every horizontal ring valid | **Planar sharp edges only.** Track A ground truth; many-equal-optima; determinism |
| **F2** | Cylinder, axis ∥ pull | `+Z` | `g ≡ 0` on the lateral face — **infinitely many** valid rings | Degenerate zero-draft band (§4.3, §5.3). Must report the free parameter, not invent a curve |
| **F3** | Cylinder, axis ⟂ pull | `+Z` | exactly **2 straight rulings** + 2 end arcs → one clean loop | ⭐ **Cylindrical face-interior silhouette. Track A provably fails, Track B provably passes.** The A/B fixture for the whole architecture |
| **F4** | Sphere | any | the great circle ⟂ `d̂` | Track B on a face with **no usable edges at all** |
| **F5** | Cone | `+Z` | 2 rulings at `u = φ ± arccos(tan α·c/R)` | §4.1 closed form, incl. the no-solution case `\|tan α·c/R\| > 1` |
| **F6** | Filleted box (constant-radius edge blends) | `+Z` | silhouette runs **across** the fillet faces | ⭐ **Fillet faces.** Semi-analytic (a constant-radius blend is toroidal) — checkable against §4.1's torus form |
| **F7** | Lofted / B-spline lid | `+Z` | **no closed form** — see convergence note below | ⭐ **Pure marching-squares path (§4.2).** Newton refinement, adaptive grid |
| **F8** | Box + boss on top | `+Z` | outer rim, not the boss rim | Local-feature rejection (the Bug-H failure mode) |
| **F9** | Box + through-hole | `+Z` | outer rim wins; hole rim is feasible but loses on T1 | **Multiple genuine competing loops** — both feasible, ranking decides |
| **F10** | Rib meeting the outer wall at a T-junction | `+Z` | branch node survives §5.4 reduction | ⭐ **Branches.** Beam search / enumeration input. Distinguishes a *real* topological branch from tolerance noise (§5.4) |
| **F11** | Alternating draft pockets | `+Z` | silhouette genuinely fragments into ≥ 3 pieces | ⭐ **Disconnected candidates.** The Part3 failure mode, reproduced small and understandable |
| **F12** | Draft-free rib | `+Z` | zero-draft band with a free position | §5.3 band collapse |
| **F13** | Peanut (two-lobed) | `+Z` | non-convex projected outline | **bbox coverage lies here; §8.1 must not.** Also quantifies the `A_cauchy` overestimate against a known shape |
| **F14** | Mirror-symmetric part | `+Z` | two mirror-equivalent optima | Determinism under **exact** ties (§8.3) |
| **F15** | `Part1.stp` | optimizer | coverage ≥ 0.90 (v1 achieves 94.8%) | No regression on a working case |
| **F16** | `Part3.stp` | optimizer | **unknown** — see note | ⭐ The real generalization test |
| **F17** | Lofted barrel (r 10→16→10) | `+Z` | silhouette **circle inside** the BSpline face, at mid-height | ⭐ **The only fixture that truly needs Track B.** Added 2026-08-09 after P1 measured that F6/F7 do not — see below |
| **F18+** | GrabCAD / ABC parts | various | none — unlabelled | Generalization, crash-resistance |

> ### ⚠ Three expectations corrected 2026-08-09 by P1 measurement
>
> **F5, F6 and F7 were predicted to need Track B. They do not.** The a-priori
> error was assuming *"has curved faces"* ⇒ *"needs Track B"*. The real
> criterion is whether **`g` changes sign inside a face**:
>
> * **F6** — the top fillets span `g ∈ [0,1]`, from the vertical wall to the
>   horizontal top. They *touch* zero at the fillet/wall edge and never cross
>   it internally, so Track A finds that edge. Measured feasible, 99.1%.
> * **F7** — all five lofted faces have `g_centroid ∈ [0.33, 0.44]`, strictly
>   positive: a monotone inward slope with no sign change. Measured 100.0%.
> * **F5** — the cone's `g` is constant on the lateral face; the answer is the
>   base rim, an edge. Measured 99.4%.
>
> Consequence: **the original corpus contained no real test of Track B.** F17
> exists to close that gap — one BSpline face measuring `min_g = −0.47`,
> `max_g = +0.47`, with no B-Rep edge anywhere near the correct curve.
> Without it, P2 would have had nothing to prove itself against.

**Ground truth for F7 (no closed form).** Extract the silhouette once on a
dense `1024²` reference grid with tight Newton tolerance, freeze that as the
reference curve, and assert the production adaptive-grid result agrees with it
to within `τ_sag`. This is a **numerical convergence test**, not an analytic
one — say so, and never describe F7's reference as "the exact answer".

**F16 (Part3) has no ground truth.** Bosch has not disclosed an expected
solution, and no mold engineer has supplied one. So F16 **cannot be scored on
correctness** — only on: (a) fragmentation measurably reduced after §5.4,
(b) any answer produced is *feasible* under H1–H4, (c) if no feasible loop
exists, the engine says so honestly. **Beating 18.1% coverage is not by itself
evidence of a correct answer** — a wrong loop with high coverage is still
wrong. Treat coverage here as a diagnostic, not a score.

**Exit gate:** all fixtures generate and load; harness runs v1 end-to-end on
every one and records a baseline table. **No v2 algorithm code yet.**

---

### P1 — Level 0 baseline

**Build**
- Track A with **edge-local normals** (§3), reusing `_face_normal_at_uv`.
- Scale-aware welding (§5.2), 2-core + chain reduction (§5.4).
- Single-cycle detection; fundamental cycle basis when branched.
- **Full hard filter H0–H7** (§7) — H0 on-surface first, then the real H3
  separation test in
  its cheap face-adjacency form, which is *exact* at Level 0.
- Lexicographic ranking (§8) with the full scorecard.
- Core/cavity from H3 regions (§9) + independent validator (§9.3).

**Deliberately NOT in P1:** face-interior curves, Johnson enumeration, beam
search, bridging of any kind.

**Exit gate (measured, on the corpus)**
- ⭐ **H0 passes on every fixture that produces a loop at all**, with
  `max_surface_deviation_mm` and `max_edge_deviation_mm` **published per
  fixture**. A loop that cannot prove it is on the part is not a Level 0
  result. This gate is live from P1 — not deferred to P5.
- **F1, F8, F9, F14, F15 produce the analytically-correct loop.**
- **F3, F4, F17 are expected to FAIL** (no interior curves yet) — and must
  fail *loudly*, reporting `no_feasible_candidate` with a stated reason,
  **not** a plausible-looking wrong answer. This is the acceptance criterion
  that proves the hard filter works. *(F5/F6/F7 were originally listed here;
  P1 measurement proved that wrong — see the fixture-table callout.)*
- F10, F11 record their branch-node count and component count — the **baseline
  numbers** P2 must improve.
- F16 (Part3): either a feasible loop, or an **honest rejection**. Either is a
  pass. `ready(0.806)` at 18.1% coverage is a fail.
- Determinism test green on every fixture.
- **Per-stage timing instrumented** (§12.5) and the baseline p50/p95 table
  published. Everything later is measured against it.

---

### P2 — Level 1: face-interior silhouette curves

**Build**
- §4.1 closed forms: plane, cylinder, cone, sphere, torus.
- §4.2 marching squares + Newton for free-form, with sag-derived adaptive grid.
- §4.3 degenerate-region detection; §5.3 band collapse.
- Track A ↔ Track B stitching at face-wire crossings (§4.2 step 5).

**Exit gate**
- ⭐ **H0 still passes with Track B active** — the harder case, since
  face-interior points come from `S(u,v)` rather than an edge curve.
  `max_surface_deviation_mm` and `off_face_point_count` published per fixture;
  `off_face_point_count` must be **0** (the `FClass2d` containment test in
  H0.3 is what catches marching-squares points that escaped the trimmed
  region).
- **F3, F4 now pass**, with the found curve within `τ_sag` of the closed-form
  answer — verified numerically against §4.1, not by eye.
- **F17 passes against its dense-grid reference** (convergence, not analytic).
  This is the fixture P2 exists for: its answer is a circle in the middle of a
  BSpline face, unreachable by any edge test.
- F2, F12 correctly report a degenerate band with its span and its free
  parameter, rather than inventing a specific curve.
- **F15 (Part1) does not regress** below Level 0.
- **F16 (Part3): the falsifiable test.** Component count after §5.4 reduction
  must drop sharply from 22 if RC-1 is the real cause. **If it does not, that
  hypothesis is wrong and we stop and re-diagnose** rather than layering on
  more machinery. Written down here so we honour it when it is inconvenient.
- Per-stage timing re-measured; Track B's cost attributed to the specific
  stage that spent it (§12.5). No optimization yet — measurement only.

---

### P3 — Level 2: bounded enumeration + full ranking

**P3a — MEASURE FIRST (no enumeration code)**

- Instrument §5.4 to emit `μ`, node/edge/branch-node counts per part.
- Run across the **entire** corpus (F1–F16 + all GrabCAD/ABC parts).
- **Publish the `μ` distribution.** This decides what P3b builds — see §6.1's
  build-order gate.
- Measure `A_cauchy` vs the exact tessellation-union projected area on every
  corpus part; publish the overestimate distribution.
- Collect every H7 measurement recorded since P1 and plot the coverage
  distribution for candidates that passed H1–H4.

**P3b — BUILD ONLY WHAT P3a JUSTIFIED**

- §7 H3 in its **full** face-splitting form (needed once Track B cuts faces).
  Unconditional — this is definitional, not an optimization.
- §6.1 strategy dispatch **only for the branches P3a showed real mass in.**
  If `μ = 1` dominates, ship the single-cycle path plus cycle basis and
  **write neither Johnson nor beam search.** Record that decision and its
  evidence in `CHANGELOG.md`.
- `κ_min` (H7) **set from P3a's distribution**, replacing the provisional
  0.50. If the data does not support any clean threshold, say so and keep it a
  reported diagnostic rather than inventing one.

**Exit gate**
- Every fixture F1–F16 passes or is honestly rejected.
- ≥ 20 GrabCAD/ABC parts processed with **zero unhandled exceptions**, and a
  published outcome distribution (feasible / rejected-with-reason /
  bounded-out / referred-to-side-action). A high rejection rate is an
  acceptable P3 outcome; a crash or a confidently-wrong answer is not.
- Every bound actually implemented (`K_max`, `μ_max`, beam width) lives in
  `config.yaml` — no hardcoded limits, unlike v1's `22` / `75_000`.
- p50/p95 per-stage runtime published (§12.5). **Bottlenecks identified before
  any optimization is attempted.**

---

### P4 — Core/cavity integration

**Build**
- §9 classification from H3 regions, replacing the normal-sign test for v2.
- `split` and `ambiguous` labels surfaced through the API and UI.
- §9.3 validators wired into `part_validation.py` as `--assert-*` flags.
- §10.2 `PartingSurfaceProvider` boundary; `PlanarSplitToolProvider` reporting
  `max_deviation_from_loop_mm`.

**Exit gate**
- V1–V6 green on every fixture — including **V6**, which recomputes the
  on-surface invariant from stored points + provenance rather than trusting
  the filter's own report.
- Boolean split still `split_ok` with 2 solids on Part1 and Part3 (no
  regression on a working capability).
- `max_deviation_from_loop_mm` reported and shown in the UI next to
  `split_tool_kind`.
- Module-dependency test asserts §10.2 rule 1: the candidate-generation and
  ranking modules do not import the surface provider.

---

### P5 — Visualization (fixes RC-11)

Deliberately its own phase — the audit found four *distinct* visualization
causes, three of which are data problems the earlier phases already fix.

**Build**
- **Candidate overlay:** draw the top-`N` feasible candidates in muted colour,
  the selected one highlighted, rejected ones toggleable **with their
  rejection reason on hover**. On Part3 this is the single picture that would
  have explained everything.
- **Provenance colouring:** edge-derived segments vs face-interior segments vs
  spliced/bridge segments in distinct colours. Instantly shows whether Track B
  is doing the work.
- **Curve fidelity honesty:** the renderer **tessellates the exact on-surface
  geometry** (§9.5 rule 2) — it never fits its own curve. Raw on-surface
  polyline by default; a surface-constrained smoothed variant only as an
  explicit toggle, tagged `display_only` unless it passed H0 itself, with its
  measured `max_surface_deviation_mm` shown. (Today the unconstrained Chaikin
  curve is the *only* one shown, and it is also what every downstream consumer
  reads — RC-7.)
- **On-surface badge:** `PartingLineValidation`'s result displayed next to the
  curve — `on_surface PASS · max deviation 0.000004 mm`. A failing candidate
  is drawn only as a labelled diagnostic overlay, never as a parting line.
- **Side-action referrals surfaced** (§12.8): H5-disqualified candidates
  listed with their referred features and `conflict_length_mm`, phrased as
  *"requires a side action"* — never as part-level infeasibility. Display
  only; no call into `side_core.py`.
- ⭐ **Consumer migration off `readiness` / `confidence`** (§12.9): rewrite the
  `frontend/app.py` panels and the `backend/report/pdf_export.py` sections to
  read feasibility / validation / ranking / evidence, per §12.9's replacement
  mapping. **This is the milestone where the deprecated fields stop being
  read** — they are removed from the API only in a later breaking version.
- **Split-tool truth:** draw the plane that *actually* splits, labelled, next
  to the loop, with `max_deviation_from_loop_mm` shown. Never show a surface
  that is not the one used.
- **Region shading:** cavity / core / **split** / ambiguous, four colours —
  `split` faces shaded per sub-region, not forced to one colour.

> ### ⚠ The remaining honesty boundary — enforce this in the UI
>
> After §9, core/cavity **classification** is derived from the **real** parting
> loop. The Boolean **split** is still performed with a **flat plane**. Those
> are two different geometries:
>
> ```
>     face colouring   ←── derived from the REAL 3-D parting loop  (§9, H3)
>     exported solids  ←── cut by a FLAT PLANE                     (§11, §10.2)
> ```
>
> **The UI must never place them side by side in a way that implies a common
> source.** Concretely:
> - The two must not share a legend, a colour, or a panel heading.
> - Any view showing both carries the deviation
>   (`max_deviation_from_loop_mm` — 16.16 mm on Part1) as visible text, not in
>   a tooltip.
> - The export panel keeps `split_tool_kind="planar_approximation"` adjacent to
>   the download control, not in a collapsed expander.
>
> This is the largest remaining place where a viewer could reasonably infer
> something untrue, and improving §9 makes it *more* tempting, not less —
> better classification makes the whole page look more exact than the export
> actually is.

**Exit gate**
- A mold engineer looking at Part3 can tell, **without reading a number**,
  that the silhouette is fragmented and why the selected loop is small.
- **No consumer reads `readiness` or `confidence` any more.** Verified by
  grepping `frontend/` and `backend/report/` — zero hits. Both render the
  §12.9 replacements against a live v2 backend on Part1 and Part3, no
  exceptions (the existing Streamlit `AppTest` pattern).
- Both consumers still work unchanged against a **v1** response — the flag
  stays a genuine A/B until P6.

---

### P6 — Cutover

- A/B v1 vs v2 across the full corpus; publish the comparison table.
- Flip `dfm.parting_line.engine` default to `v2` **only if** v2 wins or ties
  on every corpus part on the §8 measures, with no runtime regression beyond
  an agreed budget.
- v1 stays available behind the flag for one milestone.
- Update `CHANGELOG.md`, `STATUS.md`, `TODO.md`,
  `.claude/rules/honesty-and-scope.md`, and **rewrite the stale
  `.claude/memory/known-gaps.md`** (audit Part 0).

---

## 12.5 Runtime instrumentation policy (cross-phase)

**No Bosch runtime SLA has been provided. Do not invent one.** An arbitrary
ceiling would trade correctness for a number nobody asked for, in direct
conflict with the locked priority order.

Instead, from **P0 onward**, instrument every stage:

```
        load → TrackA → TrackB → weld → reduce → enumerate
             → H1..H7 → rank → core/cavity → surface
```

Each stage emits `elapsed_ms`, and the result carries a `stage_timings` dict.

**Reported per corpus run:** p50 and p95 per stage, plus total. Not the mean —
p95 is where the pathological parts live, and the mean hides them.

**Optimization policy** (your point 17, and the locked priority order):

1. Correctness and geometric validity first. Always.
2. Never optimize a stage that P3a's profile did not identify as a bottleneck.
3. When a bottleneck *is* identified, record the before/after measurement in
   `CHANGELOG.md` — the project's existing standard.
4. A runtime regression is acceptable if it buys correctness, **provided it is
   measured and stated**. An unmeasured regression is not.

If Bosch later supplies an SLA, it becomes a gate at that point — not before.

---

## 12.6 Post-Level-2 validation roadmap (not this milestone)

Named here so it is not forgotten, and explicitly **not** blocking P0–P6.

### Sensitivity analysis to pull direction ⭐

The audit flags this as entirely missing, and it matters more than it first
appears. The parting line is computed *relative to* `d̂`, which is itself an
optimizer output with its own uncertainty. So:

```
        d̂           → Loop A
        d̂ + 1°      → Loop B
```

If a 1° perturbation changes the answer, that is **critical engineering
information** — it means the solution sits on a knife edge and the reported
precision is fake (your point 15).

**Method.** Perturb `d̂` over a small cone (±1°, ±2°, ±5°; 8 azimuths each),
re-run the pipeline, and measure:

| Measure | Meaning |
|---|---|
| Loop **stability** — Hausdorff distance between selected loops, normalized by `bbox_diag` | does the curve move? |
| **Rank stability** — does the T1 winner stay the winner? | is the *decision* stable? |
| **Feasibility stability** — does the feasible-set size change? | do candidates appear/vanish? |
| **Coverage variance** across the cone | is the metric itself stable? |

**Output** — a classification the agent can state plainly:

- `stable` — loop moves < 1% of `bbox_diag`, winner unchanged across the cone.
- `sensitive` — winner changes within ±2°. **Report it.** *"The selected
  parting solution is sensitive to small changes in pull direction; the
  direction should be confirmed before tooling."*
- `degenerate` — multiple equivalent optima (F1, F2, F14 by construction).

This is cheap to build once the pipeline is deterministic, and it converts a
single-point answer into an engineering statement with a stated robustness.

---

## 12.7 Confidence ≠ correctness

> **Rule: the pipeline must never emit a bare confidence percentage.**

v1 emits `confidence = 0.9 if is_closed else 0.72`, adjusted by hardcoded
decrements (`parting_line.py:3556-3563`), and a `readiness` score of 0.806 on
a loop covering 18.1% of the part. Those numbers look like calibrated
probabilities. **They are not.** Nothing was ever fitted to outcome data, so
`0.806` means only "this arithmetic produced 0.806".

v2 replaces the single number with four **separately reported** things:

```
    FEASIBILITY      PASS                     ← binary, from H0–H7. Not a score.
    RANKING          won at tier T1           ← WHY it beat the alternatives
                     (coverage 0.948 vs 0.910)
    VALIDATION       6/6 invariants PASS      ← V1–V6, independently recomputed
    EVIDENCE         on-surface PASS          ← measured quantities, with units
                     max surface deviation 0.000004 mm
                     coverage 94.8%
                     pull-axis span 16.16 mm
                     excess turning 0.08
                     split deviation 16.16 mm
```

Rules:

1. **No probability-shaped output** unless it was fitted to labelled outcomes.
   We have no labelled outcomes (Bosch has not disclosed expected solutions),
   so we have no calibrated probabilities. Say the measurement, not a belief.
2. A **qualitative** band (`stable` / `sensitive` / `degenerate` from §12.6,
   or `feasible` / `referred` / `rejected`) is allowed — it is a
   classification with a stated rule, not a fake probability.
3. Every number shown carries its **unit and its definition**. `0.948` alone
   is not reportable; `coverage 94.8% (projected loop area ÷ Cauchy upper
   bound on projected outline area)` is.
4. The agent narrates the **scorecard**, never a score. *"Selected on
   coverage; the runner-up was smoother but partitioned the part into three
   regions."*

---

## 12.8 Side-action referrals — emit only, do not route (P0–P6)

**Decision:** H5 emits `SideActionReferral`. **`side_core.py` is never called
from v2 in this milestone.**

```
        H5 disqualifies a candidate
                  ↓
        SideActionReferral emitted        ✅ P0–P6
                  ↓
        displayed in the UI / API / report ✅ P0–P6
                  ↓
        ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
                  ↓
        side_core.generate_*()             ⛔ NOT in this milestone
```

**Why emit-only:** auto-routing is the better end product, but calling Stage 4
couples v2's candidate filter to a module with its own Boolean failure modes,
its own tolerances, and its own honesty constraints — and would widen P4 well
past "make the parting line correct". The locked priority order puts
correctness ahead of integration completeness.

**What "preserve the interface" means concretely:**

1. `SideActionReferral` carries **everything Stage 4 would need** —
   `feature_ids`, `conflicting_segment_ids`, `conflict_length_mm`, and
   `release_direction_hint` — so enabling the call later adds a call site,
   not a data model change.
2. The referral list is a **first-class field on the result**, not a warning
   string, so a future caller can consume it programmatically.
3. **No import of `side_core` from the v2 package.** Enforced by the same
   module-dependency test that guards §10.2 rule 1.
4. A follow-up milestone adds `route_referrals: bool` (default `false`) and
   the call site. Nothing in H5, §7, or §8 changes when it does.

**Do not claim** the pipeline "handles undercuts via side cores" during
P0–P6. It *identifies and reports* that a side action is required. That is
the honest claim, and it is already a useful one.

---

## 12.9 Deprecation lifecycle for `readiness` / `confidence`

§12.7 bans confidence-shaped output from v2, but the fields exist today and
both `frontend/app.py` and `backend/report/pdf_export.py` read them. Breaking
them at cutover would make the flag non-reversible, which defeats the flag.

**Three-stage lifecycle:**

| Stage | v2 behaviour | Consumers |
|---|---|---|
| **P0–P4** | Emit `readiness: null`, `confidence: null`, plus `"deprecated": ["readiness", "confidence"]` | Unchanged — they already handle missing/empty payloads |
| **P5** | Same | **Updated** to read feasibility / validation / ranking / evidence (§12.7). Frontend panels and PDF sections rewritten |
| **Later breaking API version** | **Fields removed entirely** | Already migrated |

**Rules:**

1. **v2 never computes these fields.** Not a recalculated value, not a
   relabelled one, not a best-effort mapping from the scorecard. `null` —
   because any number we put there would be exactly the uncalibrated,
   confidence-shaped output §12.7 exists to eliminate.
2. **v1 keeps computing them unchanged.** It is frozen (§12 P6); the flag
   must stay a genuine A/B, so v1's payload shape does not move.
3. A consumer reading `readiness` from a v2 response gets `null` and must
   handle it. The `deprecated` array makes that explicit rather than leaving
   it to be discovered.
4. Removal is a **breaking API version**, not a silent drop.

**P5 replacement mapping** — what each consumer shows instead:

| Was | Becomes |
|---|---|
| `readiness.status` ("ready"/"weak"/"failed") | **Feasibility**: `PASS` / `REFERRED_TO_SIDE_ACTION` / `REJECTED (failed H<n>: reason)` |
| `readiness.score` (0.806) | **Ranking**: winning tier + the margin that won it |
| `refinement.confidence` (0.9 / 0.72) | **Validation**: `V1–V6 n/6 PASS` |
| the single headline number | **Evidence**: on-surface deviation, coverage, pull-axis span, excess turning, split deviation — each with units and a definition |

---

## 13. Config keys — all new thresholds

Under `dfm.parting_line_v2:` in `config.yaml`. Nothing hardcoded (invariant #4).

```yaml
dfm:
  parting_line_v2:
    # --- visibility band ---
    silhouette_epsilon: 0.02          # |g| <= eps => zero-draft band (~1.15 deg)
    orientation_epsilon: 0.05         # H4 slack
    orientation_violation_max: 0.02   # H4 rho_max (area fraction)

    # --- tolerances (scale-aware; * = multiplied by bbox_diag) ---
    weld_tolerance_rel: 1.0e-6        # *  floor 1e-7 mm; max'd with BRep vertex tol
    closure_tolerance_rel: 1.0e-5     # *  H1
    sag_tolerance_rel: 1.0e-3         # *  marching-squares grid + edge sampling

    # --- H0 ON-SURFACE INVARIANT (definitional; see 7.0 and H0) ---
    # Both are max'd at runtime with the KERNEL's own declared tolerance for
    # the specific face/edge (BRep_Tool.Tolerance), never used bare.
    surface_tolerance_rel: 1.0e-6     # *  tau_surface, floor 1e-7 mm
    edge_tolerance_rel: 1.0e-6        # *  tau_edge,    floor 1e-7 mm
    # tau_silhouette = silhouette_epsilon * this (10x tighter than the band)
    silhouette_error_factor: 0.1
    # Smoothed curves are display_only unless they pass H0 themselves (9.5).
    allow_smoothed_as_geometry: false

    # --- Track A ---
    edge_samples_min: 5
    edge_samples_max: 33

    # --- Track B ---
    uv_grid_min: 8
    uv_grid_max: 256
    newton_max_iterations: 8
    newton_tolerance: 1.0e-9

    # --- enumeration bounds (v1 hardcoded these; do not repeat that) ---
    mu_max_for_johnson: 12
    max_candidates: 200
    beam_width: 3
    enumeration_time_budget_s: 5.0

    # --- hard filter ---
    # H7. PROVISIONAL -- a configuration decision, NOT an engineering truth.
    # Calibrated from the corpus in P3a. Never quote this as a manufacturing
    # rule; H3 is the real validity test (see 7.0).
    min_coverage_ratio: 0.50
    min_length_rel: 0.05              # *  H6
    min_projected_area_rel: 1.0e-4    # *  H6 (of bbox_diag^2)

    # --- ranking ---
    tier_epsilon:
      coverage: 0.01
      undercut_proximity: 0.02
      pull_axis_span_mm: 0.10
      ambiguous_area_fraction: 0.01
      excess_turning: 0.02
      length_3d_mm: 0.50

    # --- core/cavity ---
    face_sample_grid: 5               # M x M multi-sample validation
```

---

## 14. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| RC-1 is **not** the dominant cause of Part3's fragmentation | Medium | High — P2 delivers nothing | P2's exit gate makes the component-count drop the explicit falsifiable test. If it does not drop, **stop and re-diagnose.** Committed to in writing, above. |
| Marching squares is slow on spline-heavy industrial parts | Medium | Medium | Sag-derived adaptive grid; per-face caching; closed forms cover most area; measure in P2 before optimizing (your point 17) |
| H3 face-splitting is fiddly in UV space | High | Medium | Level-0 cheap variant (face-adjacency) is exact for edge-only loops and ships in P1; full form deferred to P3 where Track B makes it necessary |
| Johnson explodes on a pathological part | Low | Medium | Hard `K_max` + wall-clock budget, **both reported**; basis+beam fallback |
| v2 never beats v1 on Part1 | Low | High | v1 stays behind the flag; P6 cutover is conditional on measured wins |
| Corpus parts crash the loader | Medium | Low | P3 gate counts crashes explicitly; loader hardening is in scope, algorithm changes are not |
| Two divergent codepaths drift | Medium | Medium | v1 is frozen — bug fixes only, no features — and removed one milestone after cutover |
| Scope creep into Level 3/4 | Medium | High | Locked: not until every Level 2 test passes, then re-decide |
| **Track B points drift off the trimmed face** (marching squares escapes the wire boundary, or Newton converges to a point on the *extended* surface outside the face) | Medium | **High** — the levitating-line failure returns | H0.3's `FClass2d` containment test plus `off_face_point_count == 0` as a P2 exit gate; V6 recomputes it independently of the filter |
| **Someone backfills `readiness`/`confidence` in v2** "so the UI keeps working" | **High** — it is the path of least resistance | High — reintroduces exactly the uncalibrated output §12.7 removed | `null` is mandated, not a default (§12.9 rule 1); P5's exit gate greps `frontend/` and `backend/report/` for zero hits; the claim is banned in §15 |
| **The emit-only boundary is crossed early** (a call into `side_core.py` "while we're here") | Medium | Medium — widens P4 past its purpose | Module-dependency test forbids the import outright, same mechanism as §10.2 rule 1 |
| **A smoothed curve leaks into a downstream consumer** | Medium | High | `allow_smoothed_as_geometry: false` by default; `display_only` tag; §9.5 rule 1 makes the raw representation the only thing consumers read; §15 bans the claim |
| **H7's provisional `κ_min` rejects genuinely valid loops** | Medium | Medium | Set conservatively low (0.50); rejected candidates **retained in the scorecard** with their measured coverage so a reviewer can overrule; H3 remains the real validity test; calibrated from data in P3a |
| **H5 referrals are mistaken for part-level infeasibility** | Medium | High | Reason string is literally `"requires_side_action"`; referrals returned even when *all* candidates are disqualified; explicit claim banned in §15 |
| **Better core/cavity colouring makes the planar-split export look more exact than it is** | High | High | P5 honesty-boundary callout: no shared legend/colour/panel, deviation shown as visible text, `split_tool_kind` adjacent to the download control |
| Enumeration machinery built for a case that never occurs | Medium | Low | §6.1 build-order gate — P3a measures the `μ` distribution before P3b writes any search code |

---

## 15. What we will explicitly NOT claim

Extending `.claude/rules/honesty-and-scope.md`. Add these on merge:

- ❌ "The parting line is globally optimal." — It is the best candidate in a
  **bounded** enumeration under a **lexicographic** rule. Say that.
- ❌ "We implement Hou's global optimization." — Explicitly out of scope
  (Level 4, deferred).
- ❌ "Coverage is exact." — The default denominator is `A_cauchy`, an **upper
  bound** on the projected outline for non-convex parts (§8.1), so coverage is
  a conservative under-estimate unless the exact tessellation-union path was
  used. Report which.
- ❌ "The mold split follows the parting line." — Unchanged from today: the
  split tool is a labelled planar approximation. v2 additionally reports
  **how far off it is** (`max_deviation_from_loop_mm`), which is more than v1
  ever did.
- ❌ "Validated on industry models." — Until P3's corpus run is done and its
  outcome distribution published, with the rejection rate stated.
- ❌ **"The parting line lies on the part."** — Only claimable for a specific
  result that **passed H0**, and always with the measured deviation attached.
  v1 cannot claim it at all: its displayed curve is unconstrained Chaikin
  output whose drift from the B-Rep is measured nowhere (RC-7).
- ❌ **"The smoothed curve is the parting line."** — A smoothed
  representation is `display_only` unless it passes H0 in its own right
  (§9.5 rule 5). Never let it reach the surface provider, the exporter, or a
  reported metric.
- ❌ **"The pipeline handles undercuts via side cores."** — During P0–P6 it
  *identifies and reports* that a side action is required (`SideActionReferral`)
  and **does not call `side_core.py`** (§12.8). "Identifies and reports" is
  the honest claim, and it is already useful.
- ❌ **"A parting line touching an undercut is impossible."** — It is
  disqualified as a **main-split** candidate and referred to side-action
  analysis (H5). Undercuts are resolved by side cores, lifters, inserts, or
  local mold actions — which is exactly what `side_core.py` exists for. Never
  phrase an H5 rejection as part-level infeasibility.
- ❌ **"A valid parting line covers ≥ 50% of projected area."** — `κ_min` is a
  **provisional configuration value**, not a manufacturing law (§7.0, H7).
  Until P3a calibrates it, describe an H7 rejection as *"below our provisional
  coverage gate — probably a local feature loop"*, never as invalid geometry.
- ❌ **"Confidence is N%."** — No calibrated probabilities exist; we have no
  labelled outcomes. Report feasibility, the winning tier, validation
  invariants, and measured evidence separately (§12.7).
- ❌ **"The face colouring and the exported mold halves come from the same
  geometry."** — Classification follows the real loop; the split follows a
  flat plane (§P5 boundary callout). They must never be presented as one
  result.
- ❌ **"v2 found the correct parting line on Part3."** — Bosch has not
  disclosed an expected solution and no mold engineer has supplied one. F16
  can only be scored on feasibility, fragmentation, and honesty — **not
  correctness**. Higher coverage than 18.1% is not evidence of a right answer.
- ✅ Claimable once P3 is green: *"a deterministic, reproducible parting-line
  candidate pipeline that generates silhouette curves on face interiors as
  well as B-Rep edges, proves every point lies on the B-Rep within a measured tolerance, rejects
  infeasible loops against seven further named geometric
  and manufacturability constraints, and ranks the survivors by an ordered
  engineering criterion — reporting a full scorecard and every rejection
  reason."*

---

## 16. Decision log

### Resolved — 2026-08-08 review

| # | Question | Decision |
|---|---|---|
| 0 | **Must the parting line provably lie on the B-Rep?** The plan stated it as C3 but had **no gate enforcing it** — and RC-7 shows v1 violates it via unconstrained Chaikin smoothing, which is the levitating-line defect | ⭐ **Added H0**, running before every other test, with four sub-tests, scale-aware `τ_surface`/`τ_edge`/`τ_silhouette` max'd with the kernel's own tolerances, an automated `OnSurfaceReport`, and validator **V6** recomputing it independently. Promoted "show the deviation" from a P5 display metric to a **gate live from P1**. Added §9.5: geometry is the source of truth, the renderer tessellates it, no unconstrained 3-D smoothing, surface-constrained smoothing only, and smoothed curves are `display_only` unless they pass H0 themselves. H0, §9.5, §13, P1/P2 gates, §15 |
| 1 | `κ_min` (H7) value — the plan contradicted itself (0.60 in config, 0.50 in the open questions) | **0.50 everywhere, explicitly provisional.** A configuration decision, not a mathematical discovery. Calibrated from corpus data in P3a. §7.0, H7, §13 |
| 2 | Is H7 a validity criterion? | **No.** H3 (topological separation) is the primary validity test. H7 is a conservative sanity gate + strong ranking signal. **If they disagree, H3 is right.** §7.0 |
| 3 | H5 semantics — reject on undercut intersection? | **Corrected.** Disqualified as a *main-split* candidate and **routed to side-action analysis** via `SideActionReferral`. An undercut is not part-level infeasibility — Bosch's criteria include side cores and lifters, and `side_core.py` already exists to handle them. H5 |
| 4 | Core/cavity from H3 vs. the planar Boolean split | Approach kept; **UI honesty boundary added and made explicit.** Classification follows the real loop, the split follows a flat plane — never presented as one result. P5 callout, §15 |
| 5 | Build Johnson + beam search in P2? | **No.** P3a measures the `μ` distribution across the corpus *first*; P3b builds only the branches the data justifies. If `μ = 1` dominates, neither is written. §6.1 build-order gate |
| 6 | Sensitivity analysis | **Post-Level-2 roadmap**, not blocking P0–P6. Full method specified. §12.6 |
| 7 | Synthetic fixture location and design | **Approved:** `data/fixtures/synthetic/`, `data/parts/` untouched. Corpus rebuilt around failure modes — **added F6 (fillets), F7 (spline/free-form), F10 (branches), F11 (disconnected candidates)**, which the first draft was missing entirely. §12 P0 |
| 8 | Confidence output | **Banned.** No probability-shaped number without labelled outcomes, and we have none. Feasibility / ranking tier / validation invariants / measured evidence, reported separately. §12.7 |
| 9 | Runtime ceiling | **No SLA provided; none invented.** Instrument per stage, publish p50/p95, optimize only identified bottlenecks. §12.5 |
| 10 | Part3 ground truth | **None exists.** Bosch has not disclosed an expected solution. F16 is scored on feasibility, fragmentation, and honesty — **never on correctness**. §12 P0, §15 |

| 11 | Do H5 referrals invoke `side_core.py` automatically in this milestone? | **No — emit only.** P0–P6 emit `SideActionReferral` and display it; **`side_core.py` is never called.** The interface is preserved so automatic routing can be switched on in a subsequent milestone without redesign. H5, §12.8 |
| 12 | What happens to v1's `readiness` / `confidence` API fields? | **Preserve temporarily as `null` + `deprecated` for backward compatibility.** v2 does **not** compute or relabel them. Frontend and PDF consumers updated in **P5**; confidence-shaped output replaced by explicit feasibility / validation / ranking / diagnostic evidence. Fields **removed entirely in a later breaking API version.** §12.7, §12.9, P5 |

### Open items

**None.** Every question raised by this plan and by the 2026-08-08 review is
resolved above. New questions get appended to this table with their decision
and the section they changed.
