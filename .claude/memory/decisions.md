# Architecture Decisions Log

> Append-only. Record decisions that affect how Claude Code or team members should work with this codebase.

---

### 2026-07-26 — Stateless Backend Design
**Decision**: The FastAPI backend re-parses the STEP file on every API call. No shared in-memory part state.
**Rationale**: Simplicity for hackathon. Avoids session management, cache invalidation, and stale state bugs.
**Trade-off**: `/direction` endpoint takes 30-60s because it runs the full pipeline from scratch every time.

### 2026-07-26 — Mutate Flag Contract
**Decision**: All geometry analysis functions accept `mutate: bool`. Default is `True` for direct calls, but `False` must be used in any scoring/comparison loop.
**Rationale**: Direction optimizer tests 50+ candidate directions. If each one mutates FaceData, the display overlay gets corrupted. Only the final winner should mutate.
**Enforcement**: Tests explicitly verify mutate=False doesn't change face fields.

### 2026-07-26 — Display Mesh Separation
**Decision**: PyVista mesh is display-only. All analysis uses exact B-Rep faces via OCC. The mesh preserves face_id mapping so colored overlays can map back to exact geometry.
**Rationale**: Triangulated meshes lose sub-millimeter accuracy needed for parting line placement and undercut depth measurement.

### 2026-07-26 — Selective Boolean Refinement
**Decision**: Boolean interference checks run only on top undercut candidates, not exhaustively on every face.
**Rationale**: OCC Booleans are expensive (~0.5-2s per face) and brittle (crash on thin/degenerate geometry). Exhaustive analysis on a 200-face part with 54 candidate directions would take hours. Smart pruning reduces this to seconds.

### 2026-07-26 — Hash-Based Edge Deduplication
**Decision**: Use `TopoDS_Shape.HashCode(2^31-1)` instead of `topexp.MapShapesAndAncestors` or O(n²) `IsSame()` loops.
**Rationale**: `topexp` module-level singleton is inconsistently available across pythonOCC builds. Hash approach works on all OCC ≥ 7.4. Collision probability ≈ 6×10⁻⁶ for ≤5000 shapes.

### 2026-07-26 — Conda-Only OCC Installation
**Decision**: pythonocc-core must be installed via conda-forge, never pip.
**Rationale**: C++ extension modules compiled for specific OpenCASCADE versions. Pip builds exist but fail on many platforms. step_loader.py itself warns about this.
