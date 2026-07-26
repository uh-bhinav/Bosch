---
paths:
  - "backend/geometry/**"
  - "backend/models/**"
---

# Geometry Engine Rules

## PartGeometry Is The Single Shared Object

Every geometry module receives `PartGeometry` as input and returns a typed result dataclass. `PartGeometry` carries:
- Live OCC handles (`occ_face`, `occ_edge`, `occ_shape`) — NEVER serialize these.
- Scalar fields that ARE JSON-safe — use `.to_dict()` to serialize.
- Progressive enrichment: downstream modules ADD fields (e.g., `draft_angle_deg`, `is_undercut`), never remove them.

## face_id Stability

`face_id` is a sequential 0-based integer assigned by `step_loader.py` in `TopExp_Explorer` traversal order. It is STABLE across reloads of the same STEP file. All downstream modules reference faces by `face_id`. Never reassign or reorder face IDs.

## Adjacency Invariants

Three maps on `PartGeometry`:
- `face_adjacency: dict[face_id → list[face_id]]` — bidirectional face graph
- `face_to_edges: dict[face_id → list[edge_id]]` — face → its edges
- `edge_to_faces: dict[edge_id → list[face_id]]` — edge → its 1 or 2 faces

Seam edges (`is_seam=True`) have only 1 adjacent face and are NOT in the face adjacency graph. Boundary edges also have 1 face. Only manifold edges (exactly 2 faces) create face-to-face adjacency.

## Draft Angle Formula

```
draft_angle_deg = asin(|n · d|)
```
Where `n` = outward unit normal, `d` = unit pull direction.
- 0° = wall perfectly vertical (zero taper) — mold sticks
- 1.5° = minimum acceptable (green)
- 90° = horizontal cap — no issue

## Boolean Pruning Rationale

OCC Booleans are expensive and brittle. The architecture uses staged refinement:
1. **Fast prefilter**: draft angle + signed normal classify ALL faces cheaply.
2. **Boolean refinement**: swept-face intersection only for selected suspect faces on promising candidate directions.
3. **Retry with offsets**: if Boolean fails, retry with increasing fuzzy tolerances.

This is intentionally NOT the full Bassi exhaustive analysis. The honest label is "selective Boolean refinement."

## The `mutate` Flag

- `mutate=False` for ALL scoring/comparison loops (direction candidates, before/after).
- `mutate=True` ONLY for the final chosen direction's result.
- Violating this corrupts the part's face-level display overlay.

## Module Dependencies

```
step_loader → draft_analyzer → direction_optimizer (uses undercut_detector internally)
                             → parting_line
                             → core_cavity
```

`undercut_detector.py` is called by `direction_optimizer.py` for each candidate. It should NOT be called independently unless you explicitly want standalone undercut analysis for a single direction.

## Config-Driven Thresholds

All numbers are in `config.yaml` under `dfm:`. Never hardcode:
- `draft.good_threshold_deg` (default 1.5)
- `draft.marginal_threshold_deg` (default 0.5)
- `direction_search.angular_step_deg` (default 15.0)
- `direction_search.boolean_refine_top_candidates` (default 5)
- `parting_line.smoothing_iterations` (default 8)

Access via: `from backend.config import settings; settings.dfm.draft.good_threshold_deg`
