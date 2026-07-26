---
paths:
  - "backend/api/**"
---

# API Layer Rules

## Endpoint List

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Health check |
| `/parts` | GET | List available STEP files in `data/parts/` |
| `/parts/{filename}/summary` | GET | Topology + geometry summary |
| `/parts/{filename}/draft` | GET | Draft analysis (configurable direction) |
| `/parts/{filename}/undercuts` | GET | Undercut detection + Boolean refinement |
| `/parts/{filename}/direction` | GET | Full direction optimization |
| `/parts/{filename}/parting-line` | GET | Parting line candidates |
| `/parts/{filename}/core-cavity` | GET | Core/cavity face classification |
| `/parts/{filename}/display-mesh` | GET | PyVista mesh data for visualization |
| `/parts/{filename}/boolean-regions` | GET | Boolean interference region meshes |

## Stateless Design

The API re-parses the STEP file on every request. There is no shared in-memory `PartGeometry` between calls. Each handler:
1. Loads the STEP file → `PartGeometry`
2. Runs analysis
3. Calls `.to_dict()` on the result
4. Returns JSON
5. Discards everything

This is by design for hackathon simplicity. It means `/direction` takes the longest (~30-60s) because it runs the entire pipeline from scratch.

## Structured Error Schema

Every error response MUST include:
```json
{
  "code": "STEP_LOAD_FAILED",
  "message": "Human-readable explanation",
  "operation": "load_step",
  "recovery_hint": "Check that the .stp file is valid AP203/AP214",
  "details": {}
}
```

Never return bare HTTP 500s or unstructured error strings.

## Path Traversal Guard

The `{filename}` parameter is validated against `data/parts/` contents. Never allow `..` or absolute paths. The file must exist in the parts directory.

## Visual Styles

Boolean region, undercut face, and parting line visual styles (colors, opacities) are defined at the top of `main.py` as constants (`BOOLEAN_REGION_STYLES`, `PARTING_LINE_STYLES`, `UNDERCUT_FACE_VISUAL_STYLES`). Keep these here, not in config.yaml — they are API/frontend presentation concerns.
