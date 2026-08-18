# Known Gaps — What's Not Implemented

> Update this file whenever a gap is closed or a new one is discovered.
> Last updated: 2026-08-16

## ❌ Not Implemented (Empty / Missing)

| Gap | File(s) | Impact |
|---|---|---|
| AI Agent layer (LangChain tool-calling) | `backend/agent/dfm_agent.py` (0 lines), `backend/agent/tools.py` (0 lines) | Core hackathon deliverable — it's an "AI Agent" hackathon |
| PDF report export | No code anywhere | `reportlab` in requirements but never imported |
| Part2.stp analysis | `data/parts/Part2.stp` does not exist | Cannot validate Level 2 complexity |

## 🐛 Known Defects (not yet fixed — proven, not just suspected)

| Defect | File(s) | Impact | Evidence |
|---|---|---|---|
| `detect_undercuts(boolean_refine=True)` mis-handles near-zero-g ("silhouette") faces: `_face_access_direction`'s strict `signed < 0.0` branch flips sweep direction on floating-point sign noise (measured `-9.9e-32` vs exact `0.0` on two otherwise-identical mirror faces), and independently `_swept_face_interference_volume` returns a degenerate whole-part-sized volume for this face category regardless of sweep direction | `backend/geometry/undercut_detector.py` (`_face_access_direction`, `_swept_face_interference_volume`) | Any Boolean-confirmed "critical" undercut on a face whose normal is ~exactly perpendicular to the pull direction is currently NOT trustworthy evidence — `depth_proxy_mm`, `release_direction`, and `boolean_region_geometry` for such features may be computed from a degenerate whole-part Boolean result. Fast-proxy (`boolean_refine=False`) results are unaffected. | See `docs/DECISIONS_AND_ALGORITHMS.md` D-042 (Part3 faces 325/366 at `+X`) |
| H4/H5 have no mechanism for a region to be exempted from orientation-consistency checking on account of already-confirmed secondary-action (side-core/slide) geometry it contains. H4 (`gates.py`) computes purely from raw per-face `g` and the H3 region a face landed in — it never reads `UndercutInput`. H5 only checks whether the LOOP touches a confirmed undercut face (`undercuts.undercut_face_ids & loop_face_ids`, edge-derived only) — it has no visibility into undercut faces sitting in a region's INTERIOR, and H4 runs before H5 in the gate sequence anyway, so even a matching H5 case could never rescue an H4 failure that already returned. | `backend/geometry/parting_line_v2/gates.py` (H4 block precedes H5 block; H4 never references `undercuts`), `regions.py` (`classify_regions`) | Any candidate whose H3 partition places a whole confirmed side-action feature (e.g. Part3's alternating-radius rib lattice) inside one region will fail H4 on that feature's own internal orientation reversals, with no way to represent "this sub-area is handled by an independent secondary mechanism, exempt it." Measured directly on Part3 +Z: real `detect_undercuts()` output wired into `evaluate_gates` produced a byte-identical H4 result to `UndercutInput.empty()` — confirming the gap is structural, not a wiring oversight. Distinct from D-043's core-pin mechanism, which solves only the C1-C4 representability of a coaxial face and does not touch H4/H5. | Investigated across several turns in the Z-architecture session (2026-08-15); no fix implemented, explicitly deferred as a separate workstream. |

## 🔍 Unproven Observations (flagged, not investigated — do not act on these without a dedicated bounded pass)

| Observation | File(s) | Status |
|---|---|---|
| `build_face_regions`'s boundary-edge sampling loop (`for edge_id in part.face_to_edges...`) draws each edge_id from a DEDUPED list and samples its ONE stored `occ_edge` orientation. For a seam edge (appears twice in a face's own wire with opposite orientation, e.g. real Part3 `face_to_edges[38]` lists edge 123 exactly once), this may sample only one of the two real, geometrically-different boundary lines (verified directly on the Mechanism B fixture: the two oriented occurrences of the same seam edge give DIFFERENT `_sample_edge_uv` results, u=0 vs u=2*pi) — potentially under-counting regions on some seam-adjacent split faces. Observed as a side effect while building the Mechanism B fixture (2026-08-15); NOT investigated, NOT confirmed to affect any real Part3 face beyond the fixture. | `backend/validation/parting_line_face_partition.py` (`build_face_regions`, `_sample_edge_uv`) | Logged only, per explicit instruction not to investigate during the Mechanism A pass. |
| `classify_regions()`'s `"ambiguous"` label uses `abs(mean_g) <= silhouette_epsilon` — a SINGLE-scalar, mean-only test. A genuinely doubly-curved/saddle zero-draft-band face could in principle have `min_g` substantially negative and `max_g` substantially positive (real, opposite-sign draft in different parts of the same face) while `mean_g` happens to average out near zero, causing a real cavity/core-determinate face to be mislabeled ambiguous by an averaging artifact ("CASE B"). Directly investigated (Phase 4B, 2026-08-16, D-050): measured `min_g`/`max_g`/`mean_g` for every ambiguous face on Part1 (70 faces) and Part3 candidate 110 (95 faces) — zero CASE-B faces found on either part; max `max_g-min_g` spread across the whole ambiguous population is `4.56e-15`/`1.41e-16`, floating-point noise 13-14 orders of magnitude below `silhouette_epsilon=0.02`. `inconsistent_face_ids` (the pipeline's own straddle detector, applied to all cavity/core faces) is also empty on both parts. NOT demonstrated on either available real fixture, but NOT ruled out for an unseen part — `FaceClassification` already carries the `min_g`/`max_g` data needed to detect it, no schema change required if one is ever observed. | `backend/geometry/parting_line_v2/regions.py` (`classify_regions`, `_sample_face_g`), `types.py` (`FaceClassification`) | Investigated and found absent on both real parts (Part1, Part3 candidate 110); do not treat as a current defect or build a new criterion against it without a demonstrating fixture. See `docs/DECISIONS_AND_ALGORITHMS.md` D-050. |

## ⚠️ Partially Implemented

| Gap | Current State | What's Missing |
|---|---|---|
| Core/cavity extraction | Face classification only (140 lines in `core_cavity.py`) | Boolean solid split into two separate mold-half bodies |
| Parting line | Candidate silhouette overlay with Chaikin smoothing | Full Hou-style global graph optimization, parting surface generation |
| Bassi 2010 fidelity | Selective swept Boolean on top candidates | Exhaustive Boolean for every face of every direction |
| Sangolli 2021 fidelity | Adjacency + Boolean-region feature grouping; edge convexity computed at load time and used to suppress centroid-normal false positives (2026-07-27) | Volumetric decomposition, radix sort |

## 📋 Infrastructure Gaps

| Gap | Notes |
|---|---|
| No type checking | No mypy, pyright, or ruff config |
| Frontend is monolith | `app.py` is 3,905 lines in one file |
| No `__init__.py` in `backend/geometry/` | Module works via relative imports but isn't a proper package |
| No CI/CD | No GitHub Actions, no automated testing pipeline |
