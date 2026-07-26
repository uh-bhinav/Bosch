---
name: research-paper-fidelity
description: Maps the 4 research papers to exactly what is and isn't implemented in the code. Use when writing reports, checking claims, or deciding what paper features to implement next.
---

# Research Paper Fidelity — What's Implemented vs. What's Not

## Paper 1: Bassi et al. (2010) — Optimal Mold Direction

**Full title**: "Undercut-Free Parting Direction Determination for Injection Molded Parts Using Surface-Based Accessibility Analysis"

### What the paper describes
- For every candidate direction, sweep every face along the direction by >2× part diagonal.
- Perform regularized Boolean subtraction against the original solid.
- If interference exists, face is inaccessible (undercut).
- Score direction by inaccessible face count + undercut volume.
- Pick direction with minimum score.

### What the code actually does (direction_optimizer.py + undercut_detector.py)
- ✅ Candidate direction generation (principal axes + spherical sampling)
- ✅ Fast prefilter using surface normal accessibility (n·d scoring)
- ✅ Swept-face Boolean interference check — but SELECTIVE, not every face
- ✅ Boolean retry with offset multipliers and fuzzy tolerance
- ✅ Smart pruning to limit expensive Boolean checks to top candidates
- ✅ Interference volume measurement
- ❌ NOT exhaustive Boolean for every face of every direction
- ❌ NOT full regularized Boolean (BRepAlgoAPI_Common, not BRepAlgoAPI_Cut)

### Honest label: "Candidate search + selective swept Boolean refinement"

---

## Paper 2: Sangolli et al. (2021) — Undercut Feature Recognition

**Full title**: "Algorithms for sorting and recognizing of undercut features in plastic products"

### What the paper describes
- Parse STEP → B-Rep or CSG.
- Volumetric decomposition into convex sub-volumes.
- For each sub-volume, apply geometric rules (normals, edge convexity, directionality).
- Radix sort features by release direction and type (internal/external).
- Output: location, depth, type, suggested mold feature per undercut.

### What the code actually does (undercut_detector.py)
- ✅ STEP-native face-level undercut detection from normals/draft
- ✅ Feature grouping by face adjacency + Boolean-region proximity
- ✅ Internal/external/interacting classification (heuristic rules)
- ✅ Release direction estimate from face normals
- ✅ Depth proxy from centroid projection and Boolean bounding box
- ✅ Action recommendation with confidence scoring
- ❌ NO volumetric decomposition of the solid
- ❌ NO radix sort over decomposed volumes
- ❌ NO edge convexity computation
- ❌ Depth is an estimate, not exact geometric measurement

### Honest label: "Feature-level grouping and typing on detected undercut regions"

---

## Paper 3: Nee et al. (1998) — Parting Line Detection

**Full title**: "Automatic Determination of 3-D Parting Lines and Surfaces in Plastic Injection Mould Design"

### What the paper describes
- Project part onto plane perpendicular to pull direction.
- Find silhouette edges (visibility changes across edge).
- Build graph of silhouette edges.
- Extract all closed edge-loops.
- Select optimal loop by: largest projected area, minimum sharp turns, flatness.
- Generate parting surface by extending the line.

### What the code actually does (parting_line.py)
- ✅ Silhouette edge detection from adjacent face normal sign change
- ✅ Near-parting edge candidate retention
- ✅ Boundary/rim edge support
- ✅ Connected-component grouping
- ✅ First-pass wire ordering (open chains and closed loops)
- ✅ Projection-aware component selection
- ✅ Undercut-conflict scoring
- ✅ Readiness scoring (ready/review/weak/failed)
- ❌ NO parting surface generation
- ❌ Wire ordering is first-pass, not fully optimized

### Honest label: "Silhouette candidate detection with projection-aware selection"

---

## Paper 4: Hou et al. (2018) — Parting Curve Refinement

**Full title**: "A hybrid approach for automatic parting curve generation in injection mold design"

### What the paper describes
- Build weighted graph of candidate edges (length + curvature + flatness + critical-region distance).
- Find minimum-cost closed loop via graph optimization.
- B-spline smooth the result.

### What the code actually does (parting_line.py)
- ✅ Graph cleanup for branched/gapped candidate components
- ✅ Bounded weighted path search for small/medium candidate graphs
- ✅ Greedy fallback for large graphs
- ✅ Chaikin display smoothing (8 iterations)
- ❌ NO global graph optimization for minimum-cost closed loop
- ❌ Smoothing is display-only (Chaikin), not geometric B-spline fitting

### Honest label: "Graph-weighted cleanup and display smoothing"
