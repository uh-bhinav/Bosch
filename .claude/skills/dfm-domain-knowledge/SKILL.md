---
name: dfm-domain-knowledge
description: Injection molding DfM domain concepts — draft angles, undercuts, parting lines, core/cavity, mold actions. Use when answering domain questions or writing explanations for engineers.
---

# DfM Domain Knowledge for Injection-Molded Automotive Plastics

## What Is DfM (Design for Manufacturability)?

DfM is the engineering process of analyzing a 3D part design to ensure it can be manufactured trouble-free in a steel injection mold. A mold engineer reviews the part CAD (.stp file) and identifies:
- Draft angle problems
- Undercut features requiring expensive side-actions
- Optimal pull direction for the mold halves
- Where the parting line should go
- How to split core vs. cavity

## Pull Direction (Mold Opening Direction)

The direction the two mold halves separate to eject the part. This single vector determines everything else:
- Which faces are "cavity side" (upper mold half) vs. "core side" (lower mold half)
- Which faces have sufficient taper (draft) for clean release
- Where undercuts exist (geometry that locks the part in the mold)
- Where the parting line falls (the boundary between mold halves)

## Draft Angle

The taper of a wall face relative to the pull direction. Without draft, the part cannot slide out of the mold.

```
draft_angle = asin(|face_normal · pull_direction|)
```

| Range | Classification | Meaning |
|---|---|---|
| ≥ 1.5° | Good (green) | Clean ejection |
| 0.5° – 1.5° | Marginal (yellow) | Risky — may stick |
| < 0.5° | Bad (red) | Will stick — correction needed |

Textured surfaces need MORE draft (2–3°). Minimum acceptable for smooth automotive plastics: ~0.5–2°.

## Undercuts

Any geometry that prevents straight ejection along the pull direction. Types:
- **Internal undercut**: inside the part (holes, internal bosses) — needs lifter/core pin
- **External undercut**: outside surface (snaps, hooks, flanges) — needs side core/slide
- **Interacting undercut**: two features that interact geometrically

Undercuts force expensive side-actions (slides, lifters, collapsible cores) in the mold, increasing tooling cost and cycle time.

## Parting Line

The 3D curve where the two mold halves meet. Properties of a good parting line:
- Follows the silhouette of the part relative to pull direction
- Is as flat and simple as possible
- Avoids cosmetic surfaces (flash/witness line will be visible here)
- Does not cross undercut features

Detection approach (Nee 1998): find edges where adjacent faces change visibility — one face normal points with the pull, the other against it. These are silhouette edges.

## Core vs. Cavity

- **Cavity** = upper mold half. Faces whose normal aligns WITH the pull direction (n·d > 0). Forms the "outside" surface of the part.
- **Core** = lower mold half. Faces whose normal opposes the pull direction (n·d < 0). Forms the "inside" surface.
- **Parting** = faces near-perpendicular to pull (|n·d| ≈ 0). These sit at the boundary.

## Mold Actions (What Engineers Recommend)

| Finding | Typical Fix |
|---|---|
| Bad draft on wall faces | Add draft angle using parting line as neutral plane |
| External undercut | Add side core / slide mechanism |
| Internal undercut | Add lifter / collapsible core |
| Poor pull direction | Change pull direction to reduce undercuts |
| Complex parting line | Redesign part to simplify mold split |

## STEP File Format

ISO 10303 AP203/AP214. Stores exact B-Rep (Boundary Representation) geometry:
- Analytic surfaces: Plane, Cylinder, Cone, Sphere, Torus
- Freeform surfaces: BSpline/NURBS, Bezier
- Topology: Solids → Shells → Faces → Wires → Edges → Vertices

This is NOT a triangle mesh (like STL). STEP preserves exact geometric accuracy — critical for mold design where parting line placement requires sub-millimeter precision.
