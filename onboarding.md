# DfM Agent — Complete Engineer Onboarding Document

**For engineers joining mid-project with no prior CAD, injection molding, OpenCascade, or DFM knowledge.**

---

## TABLE OF CONTENTS

1. The Hackathon Problem
2. Injection Molding Domain Knowledge
3. CAD and OpenCascade Fundamentals
4. Project Architecture
5. Complete Data Flow Walkthrough
6. Codebase Deep Dive
7. Geometry Object Model
8. Algorithms
9. Current Implementation Status
10. Engineer Onboarding Guide
11. Future Development Roadmap

---

---

# SECTION 1 — THE HACKATHON PROBLEM

## What Bosch Is Actually Asking For

Bosch (Robert Bosch GmbH) runs what they call the **RB-CoC Plastics Hackathon**. The specific problem statement is:

> "Develop an AI-driven solution that analyzes a 3D CAD model of an injection-molded automotive component and automatically provides the corrections needed in the part design to ensure trouble-free manufacturing."

Let's decode this completely, because every word matters for understanding why the codebase looks the way it does.

**"AI-driven solution"** means they don't want a simple script. They want something that can *reason*, explain decisions, and give suggestions in natural language — not just output raw numbers. This is why the architecture has a planned LLM (large language model) agent layer on top of geometric algorithms.

**"3D CAD model"** means they're giving you `.stp` files (STEP format files, pronounced "step"). These are exact mathematical descriptions of the part's surface geometry. They are NOT photos. They are NOT 3D printed models. They are NOT triangle meshes like `.stl` files. They are exact mathematical definitions of curved surfaces. More on this in Section 3.

**"injection-molded automotive component"** means the physical part is made by a specific industrial process where molten plastic gets forced at high pressure into a steel mold. The part must be designed so it can actually come out of that mold cleanly. This is the manufacturability constraint. More on this in Section 2.

**"automatically provides corrections"** means the tool must not just find problems, it must suggest fixes. "Face 47 has insufficient draft — add 1.5° using the parting line as the neutral plane." Not just "there's a problem."

**"trouble-free manufacturing"** means: no damage to the mold, no part getting stuck, no defects, minimal cost, repeatable production at automotive volumes (millions of parts).

## Who The Users Are

The primary user is a **mold designer** (also called a mold engineer). This is a specialized mechanical engineer with 5–15+ years of experience who receives a `.stp` file from a product designer and must determine:

1. Can this part be made in a two-plate mold? (the simplest, cheapest mold type)
2. If not, what expensive modifications are needed (sliders, lifters, side cores)?
3. Where exactly should the mold split (the "parting line")?
4. Are all the walls tapered enough to allow ejection (draft angles)?
5. Are there any geometry features that would prevent the part from coming out (undercuts)?

Today, this analysis takes 3–4+ hours per part, done manually in CATIA or SolidWorks. Our tool is supposed to reduce this to minutes.

## The Current Manual Workflow (What We Are Replacing)

Here is what a mold engineer does today, step by step, before our tool exists:

```
Step 1: Receive Part1.stp from product designer
Step 2: Open file in CATIA or SolidWorks (takes 5 minutes to load)
Step 3: Try Draft Analysis → pick a pull direction (usually Z first) → look at color map
Step 4: Find all red faces (bad draft) → note them manually
Step 5: Look for undercuts manually (geometry that "locks" the part)
Step 6: Try 3–5 different pull directions manually → compare results
Step 7: Pick the best direction → record it
Step 8: Trace the parting line manually → check it looks clean
Step 9: Write a report with findings and suggestions
Step 10: Send report to product designer
Step 11: Product designer makes changes
Step 12: Process repeats (often 3–4 iterations)
```

Each iteration of Step 3–9 takes an experienced engineer 3–4 hours. If the part is complex (automotive bracket with ribs, holes, bosses), it can take all day.

## What Outputs Bosch Expects

From the hackathon PDF and problem statement, Bosch expects:

| Output | Description |
|--------|-------------|
| Optimal mold opening direction | The best "pull direction" to minimize undercuts and bad draft |
| Draft analysis map | Color-coded 3D model: green = good, yellow = marginal, red = bad |
| Undercut detection | Identified undercut features with location, depth, type, and recommended action |
| Parting line | Highlighted curve on the 3D model showing where mold halves separate |
| Core/cavity classification | Which faces belong to which mold half |
| Natural language corrections | "Add 1.5° draft to faces 12, 47, 93 using the parting line as neutral plane" |
| PDF report | Structured DfM report with screenshots, metrics, and recommendations |

## What Success Looks Like

Success means a mold engineer can:
1. Drop a `Part1.stp` file into the system
2. Get an analysis result in under 2 minutes
3. See a color-coded 3D view in a browser
4. Read a plain English summary of problems and fixes
5. Export a PDF to send to the product designer

The solution must handle **Level 1** (simple parts, basic direction + parting line) and **Level 2** (complex parts, core/cavity extraction).

---

---

# SECTION 2 — INJECTION MOLDING DOMAIN KNOWLEDGE

## What Is a Mold?

Think of a mold like an ice cube tray, but for plastic parts and made of hardened tool steel.

The mold is a steel block (usually two halves) with a cavity shaped exactly like the part you want to produce. You inject molten plastic at high pressure (up to 1500 bar) and temperature (150–350°C) into this cavity. The plastic fills the cavity, cools, and solidifies into the part. Then you open the mold and push the part out.

The mold is expensive — a typical automotive injection mold costs $50,000–$500,000 USD and takes months to machine. Every design decision in this project is ultimately about not breaking that mold and not having to add expensive features to it.

**Real-world analogy:** Think of making a chocolate bar. You pour melted chocolate into a mold, let it cool, and flip it out. The mold splits cleanly because there are no undercuts — the chocolate can slide straight out. An injection mold works the same way, just at industrial pressure and temperature for plastic.

## The Two Halves: Core and Cavity

A standard (two-plate) mold has exactly two halves:

```
     ┌───────────────────────┐
     │    CAVITY (upper)     │  ← faces visible from above when mold opens
     │   ┌───────────────┐   │
     │   │   PART        │   │
     │   └───────────────┘   │
     │    CORE (lower)       │  ← faces visible from below when mold opens
     └───────────────────────┘
```

When the mold opens, the two halves separate. The part must be able to slide out cleanly along the direction the mold opens.

**Cavity half:** The upper mold half. Contains the surfaces of the part that face "upward" (in the direction the mold opens). In code, faces classified as `cavity_or_core = "cavity"`.

**Core half:** The lower mold half. Contains the surfaces that face "downward" (opposite to mold opening). In code, faces classified as `cavity_or_core = "core"`.

In our codebase: `FaceData.cavity_or_core` stores `"cavity"`, `"core"`, or `"parting"`. This field is populated by `core_cavity.py` (not yet implemented).

## The Pull Direction (Mold Opening Direction)

When the mold opens, the two halves move apart in one specific direction. This is called the **pull direction** or **mold opening direction** or **line of draw**.

For example, if the mold opens vertically upward, the pull direction is `+Z = (0, 0, 1)`.

**Why this matters:** Every single other decision — draft analysis, undercut detection, parting line location, core/cavity classification — depends on which direction you choose. It is the foundational choice.

**The problem:** For complex parts, the obvious direction (usually +Z) is often not the best choice. The optimizer's job (Module 3: `direction_optimizer.py`) is to search ~20–30 candidate directions and find the one that minimizes problems.

In code: `Vec3 = tuple[float, float, float]` — the pull direction is always stored as a unit vector in 3D space. `(0.0, 0.0, 1.0)` means "straight up along Z axis."

**Example with Part1.stp:** The optimizer will test directions like `+X, -X, +Y, -Y, +Z, -Z` plus intermediate angles. It might find that `(-0.259, 0.0, 0.966)` gives fewer undercuts than pure `+Z`.

## Draft Angle

Draft angle is the most important basic concept in injection molding DfM.

**Physical meaning:** When plastic solidifies in a mold, it shrinks slightly and grips the mold walls. If a wall is perfectly vertical (parallel to the pull direction), you cannot eject the part — it's stuck. You need to taper the walls slightly so the part can slide out.

This taper is called draft. Draft angle is measured in degrees from vertical (from the pull direction).

```
    Pull direction ↑
                    │
    No draft        │   Has draft (1.5°)
    (vertical wall) │   (slightly tapered)
         │          │
         │         /│
         │        / │
         │       /  │
         │      /   │
         └──────    └──────
```

**Industry standard:** For most automotive plastic parts:
- ≥ 1.5° draft = **good** (green in UI)
- 0.5° – 1.5° draft = **marginal** (yellow) — may stick; needs review
- < 0.5° draft = **bad** (red) — will almost certainly cause problems

**Mathematical definition:**

```
draft_angle = arcsin(|n · d|)
```

Where:
- `n` = outward unit normal vector of the face (which direction the face "points")
- `d` = pull direction unit vector
- `·` = dot product

If the face is horizontal (parallel to the ground, `n = (0,0,1)` and `d = (0,0,1)`): `|n · d| = 1` → `arcsin(1) = 90°`. Perfect — no draft issue.

If the face is perfectly vertical (`n = (1,0,0)` and `d = (0,0,1)`): `|n · d| = 0` → `arcsin(0) = 0°`. Worst case — will stick.

At 1.5° draft: `|n · d| = sin(1.5°) ≈ 0.026`. This tiny taper allows the part to eject cleanly.

In code: `FaceData.draft_angle_for_direction(pull_dir)` implements this exact formula. `FaceData.draft_classification` stores `"good"`, `"marginal"`, or `"bad"`.

## Undercuts

An undercut is any geometry feature that physically prevents the part from being ejected straight out of a two-plate mold.

**Physical analogy:** Imagine trying to pull a doorknob through a door hole. The knob is larger than the hole — it's an undercut. You can't pull it straight through; you'd have to take the knob apart first.

**In injection molding terms:** If any surface of the part is "hidden" from the pull direction — i.e., you cannot see it if you look at the part from above (or below) — it's an undercut.

```
          Pull direction ↑

    No undercut:          Undercut:
    
       /\                   /\
      /  \                 /  \
     /    \               /    \___  ← this overhang is an undercut
    /______\             /______/    the mold cannot come out straight up
```

**Why undercuts are expensive:** To mold a part with undercuts, you must add side cores, sliders, or lifters to the mold — movable steel elements that retract sideways before the mold opens. Each such element adds $5,000–$50,000 to the mold cost and increases the mold's complexity, failure risk, and maintenance cost.

**Detection algorithm:** A face has an undercut (relative to pull direction `d`) if the face normal `n` has `n · d < 0` (the face points "against" the pull direction) AND the face is geometrically blocked by other part geometry when you try to release it in the pull direction.

In code: `FaceData.is_undercut` is `True` or `False`. Set by `undercut_detector.py`.

**Example:** A snap clip on a car door panel. The clip hooks inward — from above, you cannot see the hook face. It's an undercut. The mold would need a slider.

## The Parting Line

The parting line (also called parting curve) is the 3D curve on the part's surface where the two mold halves meet.

**Physical reality:** When you press the two mold halves together, they contact each other along a precise curve that goes all the way around the part. This curve must:
1. Form a closed loop around the part
2. Lie at the "equator" between what's visible from above and what's visible from below
3. Avoid cosmetic surfaces (it always leaves a visible seam line on the part)
4. Be as simple and flat as possible (complex parting lines mean complex, expensive molds)

**Geometric definition:** The parting line consists of **silhouette edges** — edges where one adjacent face has `n · d > 0` (cavity side) and the adjacent face on the other side has `n · d < 0` (core side). The parting line is literally the boundary between "what faces up" and "what faces down."

In code: `EdgeData.is_silhouette` is set to `True` for these edges by `parting_line.py`. The parting line result is stored in `PartGeometry.parting_edge_ids`.

**Example:** Hold a ball in your hand and look at it from above. The equator line (where your hand blocks the view) is the parting line. For a complex bracket, this "equator" follows the geometry of the part's features.

## Sliders and Lifters

These are mechanical components inside the mold that handle undercuts. We detect undercuts precisely to determine whether these components will be needed.

**Slider (side core):** A steel block that moves sideways (perpendicular to the pull direction) before the mold opens. It forms one side of an undercut cavity. When the mold opens, the slider moves out of the way first, releasing the undercut.

**Lifter:** A pin or block that moves at an angle during ejection to release internal undercuts.

Both are expensive to add, increase mold complexity, and require extra maintenance. Every undercut detected by our tool potentially means one of these must be added.

In code: `UndercutFeature.recommended_mold_action` and `UndercutFeature.side_action_candidate` encode whether a slider/lifter is recommended.

## Dependency Chain: What Depends on What

This is critical for understanding why the pipeline is ordered the way it is:

```
STEP file loaded
      │
      ▼
Pull Direction (Mold Opening Direction) ← EVERYTHING ELSE DEPENDS ON THIS
      │
      ├──► Draft Analysis (relative to pull direction)
      │
      ├──► Undercut Detection (which faces are blocked from pull direction)
      │
      ├──► Parting Line (silhouette edges in pull direction)
      │         │
      │         ▼
      └──► Core/Cavity Classification (split part by parting line)
                │
                ▼
          LLM Agent (explain results, suggest corrections)
                │
                ▼
          PDF Report
```

You cannot classify faces as cavity or core until you have the parting line. You cannot find the parting line until you have the pull direction. You cannot do draft analysis without the pull direction. The pull direction is the foundational choice that everything else follows.

This is why `direction_optimizer.py` (Module 3) comes before `parting_line.py` (Module 4) in the pipeline, even though it runs *after* an initial draft analysis pass.

---

---

# SECTION 3 — CAD AND OPENCASCADE FUNDAMENTALS

## What CAD Actually Stores

When a mechanical engineer designs a part in CATIA or SolidWorks, the software stores an **exact mathematical description** of every surface in the part. Not pixels. Not triangles. Exact math.

For a cylindrical hole of radius 5mm, the software stores: "this is a cylindrical surface, center axis at point (10, 20, 0), axis direction (0, 0, 1), radius 5.0mm, from Z=0 to Z=15mm." This is exact. Not an approximation.

This exact format is called **B-Rep (Boundary Representation)** — you represent a solid by describing all of its boundary surfaces.

## Why STEP Files Exist

STEP (Standard for the Exchange of Product model data, ISO 10303) is the ISO standard format for exchanging exact CAD geometry between different software systems.

When Bosch's engineer designs a part in CATIA and gives it to you, they export it as a `.stp` file. This file contains the exact B-Rep geometry in a vendor-neutral format.

**Why .stp and not something simpler?** Because Bosch operates at automotive precision. A mold is machined to tolerances of ±0.01mm. If you approximate the part geometry with triangles (like an `.stl` file), you introduce errors of 0.1–1mm. That's 10–100× too large. For parting line placement and draft analysis, you need exact surfaces.

## STEP vs STL: The Critical Difference

| Property | STEP (.stp) | STL (.stl) |
|----------|-------------|------------|
| Geometry representation | Exact analytic/NURBS surfaces | Triangle mesh approximation |
| Cylinder storage | `Cylinder(r=5, axis=Z, h=15)` | ~200 triangles approximating it |
| Accuracy | Exact (machine precision) | Approximate (±resolution of mesh) |
| Face normals | Exact mathematical normals | Computed from triangle vertices |
| File size | Smaller | Larger for same complexity |
| CAD software compatibility | CATIA, SolidWorks, NX, etc. | Mostly 3D printing |
| Suitability for DfM analysis | Required | Unacceptable for mold work |

Our project uses STEP exclusively. The code comment in `step_loader.py` says it clearly: *"Only OCC can parse them without approximation errors — unacceptable for mold design where parting line placement requires millimetre accuracy."*

## What B-Rep Means

B-Rep (Boundary Representation) is a way to describe a 3D solid by describing all of its surfaces (boundaries).

**Hierarchy of a B-Rep solid:**

```
TopoDS_Shape (the whole thing)
  └── TopoDS_Solid (a connected solid body)
       └── TopoDS_Shell (closed surface forming the boundary)
            └── TopoDS_Face (one parametric surface patch)
                 └── TopoDS_Edge (boundary curve between faces)
                      └── TopoDS_Vertex (endpoint of an edge)
```

**Analogy:** Think of a cardboard box. The box is the Solid. Each flat cardboard panel is a Face. The fold lines where panels meet are Edges. The box corners are Vertices.

A cylinder has: 3 faces (top circle, bottom circle, curved side), 2 edges (top rim circle, bottom rim circle), 0 vertices (the circles are closed curves with no endpoints).

For a real automotive part with ribs and bosses, you might have 50–200 faces and 200–500 edges.

## What NURBS Means

NURBS = Non-Uniform Rational B-Splines. This is the standard mathematical representation for smooth curved surfaces in industrial CAD.

**Intuition:** A straight line between two points has a simple equation. A curved surface through multiple control points needs a more complex equation. NURBS provides a flexible, precise way to define any smooth curved surface using a grid of control points with associated weights.

**Why you need to know this:** Some faces in a STEP file are simple (planes, cylinders, cones). Others are complex freeform NURBS surfaces (the hood of a car, the curved dashboard). Our code handles all of them through OCC's `BRepAdaptor_Surface` which abstracts the surface type — you can ask "what's the normal at UV point (0.3, 0.7)?" for any surface type without knowing if it's a plane or NURBS.

In code: `FaceData.surface_type` is `"Plane"`, `"Cylinder"`, `"BSpline/NURBS"`, etc. The `BRepAdaptor_Surface.GetType()` call returns the type from OCC's `GeomAbs` enum.

## What OpenCascade Is

OpenCASCADE Technology (OCC) is an open-source CAD kernel. A CAD kernel is the low-level library that handles the mathematical representation and manipulation of exact B-Rep geometry.

Think of OCC as the NumPy of CAD — a foundational math library. The same way NumPy handles arrays and linear algebra, OCC handles surfaces, solids, Booleans, and topology.

OCC can:
- Parse STEP and IGES files
- Evaluate surface normals at any UV point
- Compute exact areas and volumes
- Perform Boolean operations on solids (union, intersection, difference)
- Triangulate surfaces into meshes for display
- Extract topology (which faces share which edges)

**Why OCC specifically?** It is the only major open-source CAD kernel that handles exact B-Rep geometry at production quality. FreeCAD is built on it. Salome is built on it. It's battle-tested for automotive and aerospace use.

## What PythonOCC Is

`pythonOCC` (package name `pythonocc-core`) provides Python bindings for OpenCASCADE. It wraps OCC's C++ library so you can call it from Python.

**Important installation note:** The code uses `conda` (not `pip`) to install pythonOCC. The package `pythonocc-core` has C++ extensions that must be compiled against specific OCC headers. Conda-forge provides pre-built binaries. Pip builds often fail on various platforms.

```bash
conda install -c conda-forge pythonocc-core
```

## The Complete OpenCascade Class Glossary

Every OCC class used in this project, explained from scratch:

### Shape and Topology Classes

**`TopoDS_Shape`**
- The base class for all topological entities in OCC.
- Like Python's `object` — everything is a `TopoDS_Shape` at the base level.
- Holds a reference to the underlying topology and geometry.
- Stored in `PartGeometry.occ_shape` — the live handle to the whole part.
- Used in: `step_loader.py`, `undercut_detector.py` (for Boolean operations).

**`TopoDS_Solid`**
- A connected solid body — a watertight volume of material.
- Most injection-molded parts are a single solid. Some complex parts have multiple solids (the code warns if `solid_count > 1`).
- Not stored directly in our data model — we work at the Face level.

**`TopoDS_Shell`**
- A connected set of Faces that form a closed surface (the boundary of a Solid).
- Counted in `PartGeometry.shell_count`.

**`TopoDS_Face`**
- One surface patch, bounded by edges.
- This is the primary entity our algorithms operate on.
- Stored as `FaceData.occ_face` — the live OCC handle kept for downstream operations.
- NEVER serialize this to JSON. Call `face.to_dict()` instead.
- Used by: every module. The face normal, draft angle, and undercut classification all work on `TopoDS_Face` objects.

**`TopoDS_Edge`**
- A curve in 3D space, bounded by two vertices (or closed if it's a circle with no distinct endpoints).
- Shared between two faces (manifold) or owned by one face (boundary edge).
- Stored as `EdgeData.occ_edge`.
- Critical for parting line detection: silhouette edges straddle the pull direction boundary.

**`TopoDS_Vertex`**
- A point in 3D space — the endpoint of an edge.
- Stored as `VertexData.occ_vertex`.

### Explorer Classes

**`TopExp_Explorer`**
- The standard OCC iterator for traversing a shape's sub-elements.
- Usage pattern:
```python
exp = TopExp_Explorer(shape, TopAbs_FACE)  # iterate all faces
while exp.More():
    face = exp.Current()  # get current face as generic TopoDS_Shape
    face = topods.Face(face)  # cast to TopoDS_Face
    # ... process face ...
    exp.Next()
```
- Used extensively in `step_loader.py` for face extraction, edge extraction, vertex extraction.
- The order of traversal is deterministic for the same STEP file — face IDs assigned by this order are stable.

**`topods` module (specifically `topods.Face()`, `topods.Edge()`, `topods.Vertex()`)**
- Type-cast helpers. `TopExp_Explorer.Current()` returns a generic `TopoDS_Shape`. You must cast it to the specific type.
- In newer OCC (7.7+): `topods.Face(shape)`, `topods.Edge(shape)`, `topods.Vertex(shape)`
- In older OCC: `topods_Face(shape)`, `topods_Edge(shape)`, `topods_Vertex(shape)`
- The code handles both via `_as_face()`, `_as_edge()`, `_as_vertex()` helper functions in `step_loader.py`.

### Surface and Geometry Classes

**`BRepAdaptor_Surface`**
- A high-level adapter that wraps a `TopoDS_Face` and gives you a uniform API regardless of whether the underlying surface is a Plane, Cylinder, or NURBS.
- Used to:
  - Get surface type: `adaptor.GetType()` → `GeomAbs_Cylinder`, `GeomAbs_Plane`, etc.
  - Get UV parameter bounds: `adaptor.FirstUParameter()`, `adaptor.LastUParameter()`, etc.
- Used in `step_loader.py` `_extract_all_faces()`.

**`GeomLProp_SLProps`**
- Local surface properties at a UV point.
- Given a surface and a UV coordinate, computes the normal vector and point coordinates.
- Critical for normal computation: `slprops.Normal()` returns the surface normal, `slprops.Value()` returns the 3D point.
- If `slprops.IsNormalDefined()` returns False, the face is degenerate (a singularity like a cone tip). The code handles this by setting `normal_valid = False`.
- Used in `step_loader.py` `_compute_face_normal_and_centroid()`.

**`BRepAdaptor_Curve`**
- Similar adapter for edges. Wraps a `TopoDS_Edge` and provides uniform API.
- Used to get edge type and compute arc length.
- Used in `step_loader.py` `_get_edge_geometry()`.

**`BRep_Tool`**
- A utility class for extracting geometry from topology.
- `BRep_Tool.Surface(face)` → returns the underlying geometric surface (`Geom_Surface`).
- `BRep_Tool.Pnt(vertex)` → returns the 3D coordinates of a vertex.
- `BRep_Tool.Triangulation(face, location)` → returns the triangulation mesh of a face (used in `visualize_raw.py`).
- Used in: `step_loader.py`, `visualize_raw.py`.

### Measurement Classes

**`Bnd_Box`**
- An axis-aligned bounding box.
- Used with `brepbndlib.Add(shape, bbox)` to compute the exact bounding box of the whole part.
- `bbox.Get()` returns `(xmin, ymin, zmin, xmax, ymax, zmax)`.
- Used in `step_loader.py` `_compute_bounding_box()`. The diagonal of this box is used by the Bassi algorithm to determine sweep distance.

**`GProp_GProps`**
- General properties container.
- Used with `brepgprop.SurfaceProperties(face, props)` to compute exact surface area.
- `props.Mass()` returns the area in mm².
- "Mass" is used because OCC treats area like mass in its general properties framework.
- Used in `step_loader.py` `_compute_face_area()`.

### Boolean Operation Classes

**`BRepPrimAPI_MakePrism`**
- Creates a prism (extrusion) by sweeping a shape along a vector.
- In the Bassi algorithm: we sweep a face by `2 × bounding_box_diagonal` in the pull direction to create a "swept volume" representing the path of the mold half.
- Used in `undercut_detector.py`.

**`BRepAlgoAPI_Common`**
- Computes the Boolean intersection (common volume) of two solids.
- In undercut detection: we intersect the swept face volume with the part body. If there's an intersection volume, the face is blocked = undercut.
- Used in `undercut_detector.py`.

**`BRepBuilderAPI_Transform`**
- Applies a geometric transformation (translation, rotation, scaling) to a shape.
- Used to position swept volumes correctly in space.
- Used in `undercut_detector.py`.

### STEP Reading Classes

**`STEPControl_Reader`**
- The main STEP file reader.
- `reader.ReadFile(path)` → reads the file.
- `reader.TransferRoots()` → converts STEP entities to OCC shapes.
- `reader.OneShape()` → returns the whole loaded geometry as a single `TopoDS_Shape`.
- `IFSelect_RetDone` → the status code meaning "success".
- Used in `step_loader.py` `load_step()`.

### Mesh Classes (for Visualization Only)

**`BRepMesh_IncrementalMesh`**
- Triangulates a B-Rep shape for display purposes.
- Parameters: `linear_deflection` (max distance from triangle to exact surface) and `angular_deflection` (max angle between triangle normals and exact normal).
- This is ONLY used in `visualize_raw.py` — the geometry analysis itself never uses triangles.
- After calling `mesher.Perform()`, you can get triangles from `BRep_Tool.Triangulation(face, location)`.

### Point and Direction Classes

**`gp_Pnt`**
- A 3D point. `pnt.X()`, `pnt.Y()`, `pnt.Z()` to get coordinates.
- In our code, we immediately convert to `Vec3 = tuple[float, float, float]` and stop using `gp_Pnt`.

**`gp_Dir`**
- A unit vector (automatically normalized). `dir.X()`, `dir.Y()`, `dir.Z()`.
- Our code uses plain `Vec3` tuples for directions instead, to avoid OCC dependency in non-OCC code.

**`gp_Vec`**
- A non-unit vector. Used for sweeping: `gp_Vec(dx, dy, dz)` where the magnitude is the sweep distance.
- Used in `undercut_detector.py` for the Bassi sweep operation.

**`GeomAbs_*` enums**
- `GeomAbs_Plane`, `GeomAbs_Cylinder`, `GeomAbs_Cone`, `GeomAbs_Sphere`, `GeomAbs_Torus`, `GeomAbs_BSplineSurface`, etc.
- These are the integer constants that `BRepAdaptor_Surface.GetType()` returns.
- Mapped to strings in `step_loader.py`'s `_SURFACE_TYPE_MAP`.

### Hash Operations

**`TopoDS_Shape.HashCode(modulus)`**
- Returns an integer hash of the shape's underlying TShape pointer.
- Used for deduplication: same geometric entity (e.g., a shared edge) will always return the same hash.
- Used throughout `step_loader.py` to deduplicate edges and vertices without O(n²) comparison.

---

---

# SECTION 4 — PROJECT ARCHITECTURE

## Complete Folder Structure

```
dfm_agent/
├── backend/                        ← All Python analysis and API code
│   ├── __init__.py
│   ├── config.py                   ← Settings loader (reads config.yaml)
│   ├── geometry/                   ← The core analysis engine (5 main modules)
│   │   ├── __init__.py
│   │   ├── step_loader.py          ← Module 1: STEP → PartGeometry
│   │   ├── draft_analyzer.py       ← Module 2: Draft angle per face
│   │   ├── direction_optimizer.py  ← Module 3a: Find best pull direction
│   │   ├── undercut_detector.py    ← Module 3b: Find undercut features
│   │   ├── parting_line.py         ← Module 4: Parting line candidates
│   │   ├── visualize_raw.py        ← Companion: STEP → display mesh
│   │   └── core_cavity.py          ← Module 5: NOT YET IMPLEMENTED
│   ├── models/
│   │   ├── __init__.py
│   │   └── geometry_models.py      ← Shared dataclasses (PartGeometry, FaceData…)
│   ├── agent/
│   │   ├── dfm_agent.py            ← NOT YET IMPLEMENTED: LangChain orchestrator
│   │   └── tools.py                ← NOT YET IMPLEMENTED: Tool wrappers
│   ├── api/
│   │   └── main.py                 ← FastAPI REST endpoints
│   └── validation/
│       ├── part_validation.py      ← Smoke tests for STEP files
│       └── performance_profile.py  ← Pipeline timing measurements
├── frontend/
│   └── app.py                      ← Streamlit interactive 3D UI
├── tests/                          ← pytest suite
├── data/
│   └── parts/
│       └── Part1.stp               ← Sample STEP input file
├── config.yaml                     ← ALL thresholds and parameters
├── environment.yml                 ← Conda dependencies
├── requirements.txt                ← Pip fallback
├── Dockerfile.backend
├── Dockerfile.frontend
└── docker-compose.yml
```

## Why Each File Exists

**`geometry_models.py`** — The shared data contract. Every module imports from here. It has zero imports from the rest of the backend. This is intentional — it is the foundation that cannot have circular dependencies.

**`step_loader.py`** — The only file that touches OCC's STEP reader. Every other module gets geometry through `PartGeometry`, not through direct OCC reader calls.

**`draft_analyzer.py`** — Depends only on `geometry_models` and `config`. It's pure math: take normals + pull direction → compute angles → classify. Can be tested without touching OCC.

**`undercut_detector.py`** — Depends on `draft_analyzer` (uses draft angles as a prefilter) and OCC Boolean operations. This is the heaviest computational module.

**`direction_optimizer.py`** — Depends on both `draft_analyzer` and `undercut_detector`. It calls both for each candidate direction to score it.

**`parting_line.py`** — Depends only on `geometry_models`. Pure graph traversal on the extracted edge/face topology.

**`visualize_raw.py`** — Depends on OCC's mesh generator (`BRepMesh`). Converts the exact B-Rep to triangles for PyVista. This is the ONLY place triangulation happens.

**`config.py`** — Reads `config.yaml` and provides typed settings. All DfM thresholds (1.5° good draft threshold, etc.) are here, not hardcoded.

**`api/main.py`** — FastAPI app. Exposes all analysis results over HTTP as JSON. The frontend calls this API; the frontend does not call geometry modules directly.

**`frontend/app.py`** — Streamlit UI. Calls the FastAPI backend. Renders 3D meshes with PyVista. Shows color overlays, tables, and the parting line curve.

## Module Communication Diagram

```
                    config.yaml
                         │
                         ▼
                     config.py
                         │ (settings)
                         │
            ┌────────────┼────────────────────┐
            │            │                    │
            ▼            ▼                    ▼
      step_loader    draft_analyzer     undercut_detector
            │            │                    │
            │            └──────────┬─────────┘
            │                       │
            ▼                       ▼
        [PartGeometry]         [DraftResult]
            │                  [UndercutResult]
            │                       │
            │                       ▼
            │              direction_optimizer
            │                       │
            │                       ▼
            │              [DirectionResult]
            │                       │
            ▼                       ▼
        parting_line           [PartingResult]
                                    │
                                    ▼
                               core_cavity      ← NOT YET IMPLEMENTED
                                    │
                                    ▼
                               dfm_agent        ← NOT YET IMPLEMENTED
                                    │
                                    ▼
                               api/main.py
                                    │
                                    ▼
                               frontend/app.py
```

## Data Flow Diagram

```
Part1.stp (on disk)
      │
      │  step_loader.load_step()
      ▼
  PartGeometry {
    occ_shape: TopoDS_Shape,
    faces: [FaceData × N],
    edges: [EdgeData × M],
    vertices: [VertexData × K],
    face_adjacency: dict,
    face_to_edges: dict,
    edge_to_faces: dict,
    bounding_box: BoundingBox
  }
      │
      │  draft_analyzer.analyze_draft(part, direction=+Z)
      ▼
  DraftAnalysisResult {
    good_face_ids, marginal_face_ids, bad_face_ids,
    good_area_pct, bad_area_pct,
    suggestions: [DraftSuggestion × P],
    severity: "minor" | "moderate" | "critical"
  }
  + part.faces[i].draft_angle_deg mutated
  + part.faces[i].draft_classification mutated
      │
      │  direction_optimizer.optimize_mold_direction(part)
      ▼
  DirectionOptimizationResult {
    best_direction: Vec3,
    best_score: float,
    candidates: [DirectionCandidateResult × C],
    initial_draft, optimal_draft,
    initial_undercuts, optimal_undercuts
  }
  + part.optimal_pull_direction mutated
  + part.inaccessible_face_ids mutated
      │
      │  undercut_detector.detect_undercuts(part, best_direction)
      ▼
  UndercutDetectionResult {
    undercut_face_ids, accessible_face_ids, parting_face_ids,
    features: [UndercutFeature × F],
    boolean_refined: bool,
    interference_volume_mm3: float
  }
  + part.faces[i].is_undercut mutated
      │
      │  parting_line.detect_parting_line_candidates(part, best_direction)
      ▼
  PartingLineResult {
    selected_component: PartingLineComponent,
    candidates: [PartingLineEdgeCandidate],
    wire_points: [Vec3],
    quality: PartingLineQualityAssessment,
    readiness: "ready" | "review" | "weak" | "failed"
  }
      │
      │  API serialization → JSON
      ▼
  frontend/app.py → PyVista 3D viewer with color overlays
```

---

---

# SECTION 5 — COMPLETE DATA FLOW WALKTHROUGH

## From File Upload to Final Visualization

Let's trace exactly what happens when the user selects `Part1.stp` in the Streamlit UI and clicks "Run Full Level 1 Flow."

### Step 1: Frontend — File Selection

**File:** `frontend/app.py`

The Streamlit UI presents a dropdown of available STEP files from `data/parts/`. The user selects `Part1.stp`. The UI calls the FastAPI backend at `GET /parts` to get the list, then `POST /analyze/full` (or sequential step endpoints) when they click Run.

### Step 2: FastAPI — Request Received

**File:** `backend/api/main.py`

FastAPI receives the request. The endpoint handler calls `load_step("data/parts/Part1.stp")`.

### Step 3: STEP Parsing

**File:** `backend/geometry/step_loader.py`
**Function:** `load_step(filepath)`

This is the most important step. Here's what happens:

```python
# 1. OCC reads the file
reader = STEPControl_Reader()
reader.ReadFile("data/parts/Part1.stp")
reader.TransferRoots()
shape = reader.OneShape()  # → TopoDS_Shape (the entire part)
```

The `STEPControl_Reader` parses the ISO 10303 STEP text format and builds an OCC B-Rep model in memory. `shape` is now a live OCC object holding the complete geometry.

```python
# 2. Bounding box (exact, no mesh)
bbox = _compute_bounding_box(shape)
# Result: BoundingBox(xmin=-50, ymin=-30, zmin=0, xmax=50, ymax=30, zmax=40)
# diagonal = sqrt(100² + 60² + 40²) ≈ 121mm
```

```python
# 3. Raw topology counts (before deduplication)
raw = _count_topology_raw(shape)
# Result: {solid_count: 1, shell_count: 1, face_count: 47, edge_count_raw: 180, vertex_count_raw: 240}
```

```python
# 4. Face extraction
faces = _extract_all_faces(shape, warnings)
# For each face:
#   adaptor = BRepAdaptor_Surface(face)
#   stype = "Plane" | "Cylinder" | "BSpline/NURBS" | ...
#   slprops = GeomLProp_SLProps(surface, u_mid, v_mid, 1, 1e-9)
#   normal = slprops.Normal()  → flipped if face.Orientation() == REVERSED
#   centroid = slprops.Value()
#   area = brepgprop.SurfaceProperties(face, props); props.Mass()
# Result: [FaceData(face_id=0, normal=..., centroid=..., area=...), ...]
```

```python
# 5. Edge extraction + adjacency graph
edges, face_adj, face_to_edges, edge_to_faces = _extract_edges_and_build_adjacency(shape, faces, warnings)
# Two-pass algorithm:
#   Pass 1: for each face, iterate its edges, hash each edge, track which faces each edge belongs to
#   Seam detection: if same edge hash appears twice for same face → seam edge
#   Pass 2: build EdgeData objects with geometry (type, length, endpoints)
#   Pass 3: build face_adjacency from non-seam manifold edges
# Result:
#   edges: [EdgeData(edge_id=0, edge_type="Line", length=25.4, adjacent_face_ids=[3,7]), ...]
#   face_adj: {0: [1,2,5], 1: [0,3,8], ...}  ← face graph
#   face_to_edges: {0: [12, 14, 15, 22], ...}  ← which edges bound each face
#   edge_to_faces: {12: [0,1], 14: [0,5], ...}  ← which faces share each edge
```

```python
# 6. Vertex extraction
vertices = _extract_vertices(shape, warnings)
# Hash-deduplicate all vertices, extract 3D coordinates
# Result: [VertexData(vertex_id=0, coordinates=(50.0, 30.0, 0.0)), ...]
```

```python
# 7. Assemble PartGeometry
part = PartGeometry(
    source_file="data/parts/Part1.stp",
    occ_shape=shape,        # ← LIVE OCC HANDLE - required for all downstream Booleans
    faces=faces,            # ← 47 FaceData objects
    edges=edges,            # ← deduplicated EdgeData
    vertices=vertices,      # ← deduplicated VertexData
    bounding_box=bbox,
    face_adjacency=face_adj,
    face_to_edges=face_to_edges,
    edge_to_faces=edge_to_faces,
    ...
)
```

**Data created:** One `PartGeometry` object containing all geometric data for the entire part. This object flows through every subsequent module.

### Step 4: Display Mesh Generation

**File:** `backend/geometry/visualize_raw.py`
**Function:** `build_display_mesh(part)`

```python
mesher = BRepMesh_IncrementalMesh(part.occ_shape, 0.5, False, 0.5, True)
mesher.Perform()
# Result: OCC has now generated triangles for each face
# We then iterate faces, extract triangles, build vertex list
# Result: RawMeshData(points=[...], faces=[...], face_ids=[...])
```

The `face_ids` list is critical: `face_ids[i] = 12` means triangle `i` comes from STEP face #12. This lets the frontend color each triangle based on the draft classification or undercut status of its source face.

**What gets stored:** `RawMeshData` — a flat triangle mesh for rendering. This is the ONLY time we triangulate. All analysis still uses exact B-Rep.

### Step 5: Initial Draft Analysis

**File:** `backend/geometry/draft_analyzer.py`
**Function:** `analyze_draft(part, pull_direction=(0,0,1), ...)`

```python
for face in part.faces:
    if not face.normal_valid:
        continue
    angle = face.draft_angle_for_direction((0.0, 0.0, 1.0))
    # = arcsin(|dot(face.normal, (0,0,1))|)
    # = arcsin(|face.normal[2]|)  (just the Z component of the normal)
    
    classification = _classify_draft(angle, good_thresh=1.5, marginal_thresh=0.5)
    # angle >= 1.5° → "good"
    # 0.5° <= angle < 1.5° → "marginal"  
    # angle < 0.5° → "bad"
    
    if mutate:
        face.draft_angle_deg = angle
        face.draft_classification = classification
```

**What gets stored:**
- `FaceData.draft_angle_deg` — a float in degrees
- `FaceData.draft_classification` — `"good"`, `"marginal"`, or `"bad"`
- Returns `DraftAnalysisResult` with aggregated statistics and suggestions

### Step 6: Direction Optimization

**File:** `backend/geometry/direction_optimizer.py`
**Function:** `optimize_mold_direction(part)`

```python
# 1. Generate candidate directions (15° increments around sphere)
candidates = generate_candidate_directions(angular_step_deg=15)
# → roughly 26–50 candidate Vec3 unit vectors

# 2. Fast prefilter: score each candidate
for direction in candidates:
    draft = analyze_draft(part, direction, mutate=False)  # non-destructive
    undercuts = detect_undercuts(part, direction, boolean_refine=False)
    score = 1500 * undercut_pct + 1000 * bad_pct + 100 * marginal_pct + ...
    # Lower score = better direction

# 3. Sort by score, select top N for expensive Boolean refinement
promising = _select_boolean_refinement_candidates(scored)

# 4. Refine promising candidates with swept Boolean interference
for candidate in promising:
    undercuts = detect_undercuts(part, direction, boolean_refine=True)  # expensive
    score = _score_candidate(draft, undercuts, direction, part)

# 5. Pick best direction, re-run analysis with mutation
best_direction = sorted_candidates[0].direction
analyze_draft(part, best_direction, mutate=True)  # overwrites face.draft_angle_deg
detect_undercuts(part, best_direction, mutate=True)  # overwrites face.is_undercut

# 6. Write to PartGeometry
part.optimal_pull_direction = best_direction
part.direction_score = best_score
part.inaccessible_face_ids = [undercut face ids]
```

**What gets stored:**
- `PartGeometry.optimal_pull_direction` — the best pull direction vector
- `PartGeometry.direction_score` — the score of the best direction
- `PartGeometry.inaccessible_face_ids` — face IDs that are undercuts in the best direction
- All `FaceData.draft_angle_deg` and `FaceData.is_undercut` fields updated to reflect the optimal direction

### Step 7: Parting Line Detection

**File:** `backend/geometry/parting_line.py`

```python
# For each edge:
for edge in part.edges:
    face_ids = edge.adjacent_face_ids
    if len(face_ids) != 2:
        continue
    f1 = part.get_face(face_ids[0])
    f2 = part.get_face(face_ids[1])
    dot1 = dot3(f1.normal, pull_direction)
    dot2 = dot3(f2.normal, pull_direction)
    
    # Silhouette edge: one face points toward pull, other points away
    if dot1 * dot2 < 0:  # opposite signs
        edge.is_silhouette = True  # ← marked for parting line

# Group silhouette edges into connected components
# Order the best component into a wire
# Score by projected area, closure quality, undercut conflict
# Return PartingLineResult with wire_points for visualization
```

**What gets stored:**
- `EdgeData.is_silhouette = True` for edges on the parting line
- `PartGeometry.parting_edge_ids` — list of edge IDs forming the parting line
- `PartGeometry.parting_wire_points` — ordered 3D points for the curve display

### Step 8: API Serialization

**File:** `backend/api/main.py`

All results are collected and serialized to JSON via each object's `.to_dict()` method. The OCC objects (`occ_face`, `occ_edge`, `occ_shape`) are excluded — only Python-native data is sent to the frontend.

### Step 9: Frontend Visualization

**File:** `frontend/app.py`

The Streamlit frontend:
1. Receives the JSON API response
2. Reconstructs the display mesh (or uses a cached `RawMeshData`)
3. Colors each triangle based on `face_id` → `draft_classification` mapping
4. Adds the parting line curve as a separate polyline overlay
5. Renders using PyVista/stpyvista in the browser

---

---

# SECTION 6 — CODEBASE DEEP DIVE

## `geometry_models.py` — The Foundation

This file is the foundation. It has zero imports from the rest of the backend. Everything else imports from it.

### `Vec3 = tuple[float, float, float]`

A type alias for a 3D vector or point in millimeters. Used everywhere. All coordinates in this project are in millimeters (STEP files from automotive CAD are always mm).

### `dot3(a, b) → float`

Dot product of two `Vec3`. Returns a scalar. Used constantly:
- To compute `n · d` for draft angle
- To classify cavity vs core side
- To detect silhouette edges

### `normalize3(v) → Vec3`

Returns a unit vector. Raises `ValueError` if the vector has near-zero magnitude. Used before any direction computation to ensure unit vectors.

### `cross3(a, b) → Vec3`

Cross product. Returns a vector perpendicular to both inputs. Used in parting line projection basis computation.

### `BoundingBox`

Stores the axis-aligned bounding box of the entire part. The `diagonal` property is used by Bassi's algorithm to determine how far to sweep a face (you need to sweep beyond the part boundary, so `2 × diagonal` guarantees the swept shape passes completely through the part).

### `VertexData`

A unique 3D vertex. The `occ_vertex` field holds the live OCC handle for cases where you need to perform further OCC operations on this vertex. The `coordinates` field holds the Python-native `Vec3` for all non-OCC use.

### `EdgeData`

The most informationally rich entity (after `FaceData`). Key fields:

- `adjacent_face_ids`: THE critical field. If this has 2 entries, it's a shared interior edge — these are the candidates for the parting line. If 1 entry, it's a boundary edge (the open rim of the part). If 3+, it's a non-manifold error.
- `convexity`: Set later by `undercut_detector.py`. `"convex"` = outside corner. `"concave"` = inside corner. Inside corners create undercut risk.
- `is_silhouette`: Set by `parting_line.py`. True when adjacent faces straddle the pull direction.
- `is_parting_edge`: Set by `parting_line.py`. True when this edge is selected as part of the final parting line wire.
- `is_seam`: True for the longitudinal line of a cylinder/sphere. NOT a real face-to-face boundary.

### `FaceData`

The primary data carrier for one surface patch. Populated progressively as the pipeline runs.

Fields set by `step_loader.py`:
- `face_id`: 0-based sequential integer. Stable across multiple loads of the same file.
- `occ_face`: Live OCC handle. NEVER serialize. REQUIRED for downstream Boolean operations.
- `surface_type`: `"Plane"`, `"Cylinder"`, `"Cone"`, `"BSpline/NURBS"`, etc.
- `normal`: Outward unit normal at the UV centroid. `"Outward"` means pointing away from the solid interior. THIS IS THE SIGN CONVENTION EVERYTHING DEPENDS ON.
- `centroid`: The 3D point at the parametric midpoint of the face.
- `area`: Exact surface area in mm², computed by OCC surface integration (not triangle approximation).
- `u_range`, `v_range`: Parametric bounds. UV coordinates are abstract parameters — `(u_mid, v_mid)` is the midpoint of the face in parameter space, not necessarily the physical center.
- `is_reversed`: If True, the OCC face orientation is reversed and the normal was flipped during loading.
- `normal_valid`: False if the normal could not be computed (degenerate face, cone tip singularity, etc.). ALL downstream modules check this before using `normal`.

Fields populated progressively:
- `draft_angle_deg`: Set by `draft_analyzer.py` (Module 2).
- `draft_classification`: `"good"`, `"marginal"`, or `"bad"`. Set by Module 2.
- `is_undercut`: `True`/`False`. Set by `undercut_detector.py` (Module 3).
- `undercut_depth_mm`: Estimated undercut depth. Set by Module 3.
- `undercut_type`: `"internal"` or `"external"`. Set by Module 3.
- `cavity_or_core`: `"cavity"`, `"core"`, or `"parting"`. Set by `core_cavity.py` (NOT YET IMPLEMENTED).

Key method `draft_angle_for_direction(pull_dir)`:
```python
def draft_angle_for_direction(self, pull_dir):
    raw = dot3(self.normal, pull_dir)
    clamped = max(-1.0, min(1.0, raw))
    return math.degrees(math.asin(abs(clamped)))
```
This is the industry-standard SolidWorks DraftAnalysis definition. We take the absolute value because draft angle is always positive (we don't care which side of the pull direction the normal is on — only how far from vertical it is).

Key method `signed_dot(pull_dir)`:
```python
def signed_dot(self, pull_dir):
    return dot3(self.normal, pull_dir)
```
This IS signed. Positive = cavity side (face points toward pull). Negative = core side. Near zero = parting/silhouette zone.

### `PartGeometry`

The single object that flows through the entire pipeline. Acts as both an input container and a progressive state accumulator.

**Adjacency maps** (these power the graph-based algorithms):

- `face_adjacency: dict[int, list[int]]` — For each face ID, the list of face IDs that share at least one edge with it. This is the face graph. Used by Nee (parting line loop traversal) and Sangolli (undercut feature grouping).
- `face_to_edges: dict[int, list[int]]` — For each face ID, the list of edge IDs that bound it. Used to find which edges to check for silhouette conditions.
- `edge_to_faces: dict[int, list[int]]` — For each edge ID, the list of face IDs (1 or 2) that share it. Used by parting line and undercut detection.

**Mutable analysis state** (gets written by downstream modules):
- `optimal_pull_direction`: Written by `direction_optimizer.py`.
- `direction_score`: Written by `direction_optimizer.py`.
- `inaccessible_face_ids`: Written by `direction_optimizer.py`.
- `parting_edge_ids`: Written by `parting_line.py`.
- `parting_wire_points`: Written by `parting_line.py`.

---

## `step_loader.py` — Module 1

### `load_step(filepath) → PartGeometry`

**The single entry point for all downstream analysis.**

Internal functions called:

**`_compute_bounding_box(shape)`**: Uses `Bnd_Box` + `brepbndlib.Add`. This is the exact analytical bounding box, computed from the parametric surfaces directly — no meshing needed.

**`_count_topology_raw(shape)`**: Uses `TopExp_Explorer` 5 times (for SOLID, SHELL, FACE, EDGE, VERTEX). These are raw counts with duplicates — edges counted once per face that contains them.

**`_clamp_uv(umin, umax, vmin, vmax)`**: Some surfaces (open cylinders, infinite planes) have UV bounds of ±1e100. We clamp these to ±1.0 before evaluation. Failing to do this would cause numerical overflow in `GeomLProp_SLProps`.

**`_compute_face_normal_and_centroid(face, adaptor)`**: The most critical geometry extraction:
1. Compute UV midpoint from clamped bounds
2. Evaluate `GeomLProp_SLProps` at that UV point
3. Read `slprops.Normal()` and `slprops.Value()`
4. Flip if `face.Orientation() == TopAbs_REVERSED`
5. Renormalize

**`_compute_face_area(face)`**: Uses `brepgprop.SurfaceProperties`. The `props.Mass()` call returns area — OCC uses "mass" as a general term for the integrated quantity.

**`_extract_edges_and_build_adjacency(shape, faces, warnings)`**: Three-pass algorithm. This is architecturally significant:
- Pass 1: Hash-based deduplication. Every edge gets a unique `edge_id` but may appear in multiple faces.
- Seam detection: If the same edge hash appears twice for the same face, it's a seam edge (like the longitude line of a cylinder).
- Pass 2: Build `EdgeData` objects with geometry.
- Pass 3: Build `face_adjacency` from manifold non-seam edges.

**`_get_edge_geometry(edge)`**: Uses `BRepAdaptor_Curve` to get edge type and length. Length is computed by `GCPnts_AbscissaPoint.Length()` (OCC arc length integration).

**`_extract_vertices(shape, warnings)`**: Hash-deduplication of all vertices. `BRep_Tool.Pnt(vertex)` extracts 3D coordinates.

---

## `draft_analyzer.py` — Module 2

### Key Dataclasses

**`DraftSuggestion`**: Groups bad/marginal faces by surface type and mold side. Generates human-readable instructions like: "Add 1.5° draft to 8 Plane faces on the cavity side. Current average: 0.2°. Neutral plane: use parting line."

**`DraftAnalysisResult`**: Complete result of one draft analysis pass. Self-contained — includes per-face snapshots so the UI can compare "initial +Z" vs "optimal" even when the `PartGeometry` has already been mutated by the final pass.

### Key Functions

**`analyze_draft(part, pull_direction, ..., mutate=True)`**: 

The `mutate` parameter is architecturally important. When `mutate=True`, the function writes `draft_angle_deg` and `draft_classification` into each `FaceData` object. When `mutate=False`, it computes the same values but does NOT write them — it just returns them in the result. This allows the direction optimizer to score many candidate directions without corrupting the part's active draft overlay.

**`_classify_draft(angle, good_thresh, marginal_thresh)`**: Simple thresholding. Thresholds come from `config.yaml`:
```yaml
dfm:
  draft:
    good_threshold_deg: 1.5
    marginal_threshold_deg: 0.5
```

**`_mold_side(signed_dot)`**: Returns `"positive"` (cavity), `"negative"` (core), or `"parting"`:
- `signed_dot > 0.05` → positive/cavity
- `signed_dot < -0.05` → negative/core
- between → parting

**`_assess_severity(bad_frac)`**: Area-weighted severity:
- 0% bad area → `"none"`
- 0–5% → `"minor"`
- 5–20% → `"moderate"`
- >20% → `"critical"`

**`_build_suggestions(part, pull_dir, good_thresh, face_results)`**: Groups bad+marginal faces by `(surface_type, mold_side)` tuple, then generates one `DraftSuggestion` per group.

**`analyze_draft_default(part)`**: Convenience wrapper for the initial +Z pass.

**`analyze_draft_optimal(part, optimal_direction)`**: Convenience wrapper for the final pass with the best direction. This MUTATES the face data.

---

## `direction_optimizer.py` — Module 3a

### Key Dataclasses

**`DirectionCandidateResult`**: Scores one candidate direction. Contains both draft metrics (`bad_area_pct`, `marginal_area_pct`) and undercut metrics (`undercut_area_pct`, `interference_volume_mm3`). `boolean_refined` tells you whether this candidate got the expensive swept Boolean treatment.

**`DirectionOptimizationResult`**: Complete result. Contains `initial_draft` (before optimization) and `optimal_draft` (after), enabling before/after comparison. Also contains the full ranked `candidates` list for the UI table.

**`BooleanPruningSummary`**: Explains the pruning gate — which candidates were selected for expensive Boolean refinement and why. Crucial for transparency.

### Scoring Formula

```python
score = (
    1500.0 * undercut_pct      # undercuts are very expensive
  + 1000.0 * bad_pct           # bad draft is expensive
  + 100.0  * marginal_pct      # marginal draft is somewhat expensive
  + weight * interference_frac  # Boolean-confirmed interference volume
  + 25.0   * undercut_count_frac
  + 10.0   * bad_count_frac
  + 2.0    * marginal_count_frac
  + 0.25   * (1 - principal_axis_alignment)  # slight penalty for non-axis directions
)
```

Lower score = better direction. Principal axes (+X, -X, +Y, etc.) get a slight advantage because they're simpler for mold manufacturing.

### Smart Boolean Pruning

The Bassi algorithm calls for Boolean intersection for EVERY face for EVERY candidate direction. On a real 100-face part with 30 candidate directions, that's 3000 OCC Boolean operations — very slow.

The pruning strategy:
1. Score all candidates with fast draft/undercut prefilter (no Booleans)
2. Sort by score
3. Apply multi-criteria gate to select "promising" candidates only
4. Only run Booleans on the promising set
5. Re-score with Boolean evidence

The `_select_boolean_refinement_candidates()` function implements several guard conditions:
- Score within ratio threshold of best
- Low-risk prefilter (very low undercut AND bad area percentages)
- Principal axis guard (keep at least some axis-aligned candidates)
- Near-tie uncertainty guard (if scores are close, keep more candidates)
- Minimum candidate guard (always refine at least N candidates)

### Caching

The direction/undercut cache (`DirectionUndercutCache`) prevents re-running the same computation when the best direction from the first pass is needed again for the final mutation pass. The cache key includes geometry signature (face count, bounding box dimensions, total area) to prevent false hits if a different part is loaded.

---

## `undercut_detector.py` — Module 3b

This is the largest and most complex module (~3400 lines). It implements both the Bassi accessibility check and the Sangolli feature recognition.

### Key Dataclasses

**`BooleanShapeAnalysis`**: Geometry of one Boolean intersection result — bounding box, volume, vertex count, etc. This is the geometric evidence from one swept-face Boolean operation.

**`BooleanRegionGeometry`**: Aggregated Boolean geometry for one undercut feature group (multiple faces).

**`UndercutFeature`**: The primary output — a recognized undercut feature group. Contains:
- `face_ids`: Which faces belong to this undercut
- `undercut_type`: `"internal"` (inside the part, like a pocket) or `"external"` (protrusion)
- `severity`: `"low"`, `"medium"`, `"high"`, `"critical"`
- `release_direction`: Which direction this undercut can be released (for slider design)
- `depth_proxy_mm`: Estimated undercut depth
- `recommended_mold_action`: `"side_core"`, `"lifter"`, `"redesign"`, etc.
- `action_confidence`: 0.0–1.0 confidence in the recommendation

**`UndercutDetectionResult`**: Complete result containing all features, face classifications, and performance/reliability summaries.

### Core Detection Algorithm

```python
def detect_undercuts(part, pull_direction, mutate=True, boolean_refine=True, ...):
    
    # Phase 1: Fast prefilter (normal-based)
    for face in part.valid_faces:
        signed_dot = dot3(face.normal, pull_direction)
        draft_angle = face.draft_angle_for_direction(pull_direction)
        
        if signed_dot < -PARTING_THRESHOLD:
            # Face points away from pull → candidate undercut
            undercut_candidates.add(face.face_id)
        elif abs(signed_dot) <= PARTING_THRESHOLD:
            parting_ids.add(face.face_id)
        else:
            accessible_ids.add(face.face_id)
    
    # Phase 2: Adjacency grouping
    # Group candidate undercut faces by adjacency using BFS
    groups = _group_undercut_faces_by_adjacency(undercut_candidates, part)
    
    # Phase 3: Optional swept Boolean refinement
    if boolean_refine and _OCC_BOOLEAN_AVAILABLE:
        for face_id in undercut_candidates:
            face = part.get_face(face_id)
            # Sweep face along pull direction by 2 × diagonal
            swept = BRepPrimAPI_MakePrism(face.occ_face, gp_Vec(...))
            # Intersect with part body
            intersection = BRepAlgoAPI_Common(swept.Shape(), part.occ_shape)
            # Measure intersection volume
            vol = measure_volume(intersection.Shape())
            if vol > threshold:
                boolean_confirmed.add(face_id)
    
    # Phase 4: Feature-level classification (Sangolli-style)
    for group in groups:
        feature = _build_undercut_feature(group, part, pull_direction, ...)
        features.append(feature)
```

### Boolean Volume Cache

`BooleanVolumeCache = dict[int, ...]` — caches the Boolean result for each face (keyed by `face_id`). Since the direction optimizer calls `detect_undercuts` multiple times for the same faces in different candidate directions, this cache avoids redundant OCC operations. The cache also helps when the best direction is later used for mutation — it's retrieved from cache rather than recomputed.

---

## `parting_line.py` — Module 4

### Algorithm Overview

This implements the first two research papers in the parting line pipeline:

**Nee et al. (1998):** Silhouette edge detection and loop extraction.
**Hou et al. (2018):** Graph-based cleanup and optimization (partial implementation).

### Key Dataclasses

**`PartingLineEdgeCandidate`**: One classified edge. Kinds:
- `"silhouette"`: Adjacent face normals straddle the pull direction (one positive, one negative `n·d`).
- `"near_parting"`: Close to the parting plane but not exactly silhouette. Retained for near-vertical or near-parting faces.
- `"boundary"`: Open rim edge. Retained if the adjacent face is close to the parting plane.
- `"non_manifold"`: 3+ adjacent faces. Unusual but included.
- `"skipped"`: Not a candidate.

**`PartingLineComponent`**: A connected component of candidate edges. The algorithm groups candidates by graph connectivity and selects the "best" component.

**`PartingLineProjection`**: 2D projection metrics of the candidate wire onto the plane perpendicular to the pull direction. Used to score components: larger projected area = better candidate (Nee's "maximum contour" rule).

**`PartingLineUndercutConflict`**: Measures how much the candidate parting line overlaps with known undercut regions. High conflict = the line passes through a problematic area.

**`PartingLineQualityAssessment`**: Final readiness score combining topology quality, projection quality, and undercut conflict. Returns `"ready"`, `"review"`, `"weak"`, or `"failed"`.

### Silhouette Detection

```python
for edge in part.edges:
    if len(edge.adjacent_face_ids) != 2:
        continue  # skip boundary and non-manifold
    
    f1 = part.get_face(edge.adjacent_face_ids[0])
    f2 = part.get_face(edge.adjacent_face_ids[1])
    
    d1 = dot3(f1.normal, pull_direction)
    d2 = dot3(f2.normal, pull_direction)
    
    if d1 * d2 < 0:  # opposite signs = one cavity-side, one core-side
        # This edge is a silhouette edge → parting line candidate
```

### Wire Construction

Once candidate edges are identified, they're grouped into connected components (faces share vertices). The component with the best projection score (largest projected area in the pull-normal plane) is selected. Edge vertices are then ordered into a wire by traversal — each edge is connected to the next by a shared vertex.

### Hou-Style Graph Cleanup

For branched or gapped components (where the simple wire cannot be constructed because edges meet at 3+ vertices), the code applies a weighted graph shortest-path search. Edges are weighted by:
- Length (longer edges preferred for stability)
- Curvature penalty
- Distance from critical regions (undercut features)

---

## `visualize_raw.py` — Display Adapter

### Purpose

This module is **purely a visualization adapter**. It converts the exact B-Rep geometry into triangles for PyVista rendering. It does NOT do any analysis.

### Key Functions

**`build_display_mesh(part) → RawMeshData`**: Triangulates the entire part. Calls `BRepMesh_IncrementalMesh`, then iterates faces to extract triangles and build the flat point/face arrays.

**`build_shape_display_mesh(shape) → RawMeshData`**: Same but for any arbitrary OCC shape (used for Boolean intersection visualization).

**`to_pyvista(mesh) → pyvista.PolyData`**: Converts `RawMeshData` to a PyVista object. The `face_id` scalar array is critical — it's what allows the frontend to color triangles based on their source face's classification.

**Critical architecture decision:** The `face_ids` list maintains the mapping from display triangles back to STEP faces. This is how the 3D color overlay works:
```python
poly.cell_data["face_id"] = mesh.face_ids
# Each triangle cell gets the ID of the STEP face it came from
# The frontend colors cell by face_id → draft_classification
```

---

---

# SECTION 7 — GEOMETRY OBJECT MODEL

## Complete Object Lifecycle

The following shows every field of every major object, when it gets set, and who reads it.

### `PartGeometry` — Complete Field Reference

```
PartGeometry {
    # Set at construction (step_loader.py):
    source_file: str              ← "data/parts/Part1.stp"
    occ_shape: TopoDS_Shape       ← LIVE OCC handle. Never serialize. Never copy.
    faces: list[FaceData]         ← N faces (N typically 20–200 for Level 1 parts)
    bounding_box: BoundingBox
    cadquery_shape: object|None   ← Optional CadQuery handle (may be None if CQ not installed)
    
    # Topology counts (unique, after hash deduplication):
    face_count: int               ← len(faces)
    edge_count: int               ← len(edges) (unique edges, NOT raw count)
    vertex_count: int             ← len(vertices)
    solid_count: int              ← typically 1
    shell_count: int              ← typically 1
    
    # Full geometry data:
    edges: list[EdgeData]         ← M unique edges
    vertices: list[VertexData]    ← K unique vertices
    
    # Adjacency maps (set by step_loader):
    face_adjacency: dict[int→list[int]]   ← face graph
    face_to_edges: dict[int→list[int]]    ← face → its bounding edges
    edge_to_faces: dict[int→list[int]]    ← edge → its 1 or 2 faces
    
    # Load metadata:
    load_time_s: float
    warnings: list[str]
    surface_type_counts: dict[str,int]    ← {"Plane":23, "Cylinder":8, ...}
    edge_type_counts: dict[str,int]       ← {"Line":45, "Circle":12, ...}
    
    # Analysis results (written by downstream modules):
    optimal_pull_direction: Vec3|None     ← written by direction_optimizer
    direction_score: float|None           ← written by direction_optimizer
    inaccessible_face_ids: list[int]      ← written by direction_optimizer
    parting_edge_ids: list[int]           ← written by parting_line
    parting_wire_points: list[Vec3]       ← written by parting_line
}
```

### `FaceData` — Progressive Population

| Field | Set By | Read By |
|-------|--------|---------|
| `face_id` | `step_loader` | Everything |
| `occ_face` | `step_loader` | `draft_analyzer`, `undercut_detector`, `visualize_raw` |
| `surface_type` | `step_loader` | `draft_analyzer` (suggestions), reports |
| `normal` | `step_loader` | `draft_analyzer`, `undercut_detector`, `parting_line`, `direction_optimizer` |
| `centroid` | `step_loader` | `undercut_detector` (feature location), `parting_line` |
| `area` | `step_loader` | `draft_analyzer` (area-weighted stats), `direction_optimizer` |
| `u_range`, `v_range` | `step_loader` | Rarely used downstream |
| `is_reversed` | `step_loader` | Diagnostic only |
| `normal_valid` | `step_loader` | ALL modules (skip if False) |
| `draft_angle_deg` | `draft_analyzer` | `undercut_detector` (prefilter), API, frontend |
| `draft_classification` | `draft_analyzer` | API, frontend (color overlay) |
| `is_undercut` | `undercut_detector` | API, frontend (red highlight) |
| `undercut_depth_mm` | `undercut_detector` | API, reports |
| `undercut_type` | `undercut_detector` | API, recommendations |
| `cavity_or_core` | `core_cavity` (NOT YET) | API, core/cavity visualization |

### `EdgeData` — Progressive Population

| Field | Set By | Read By |
|-------|--------|---------|
| `edge_id` | `step_loader` | `parting_line`, `direction_optimizer` |
| `occ_edge` | `step_loader` | `undercut_detector` (convexity) |
| `edge_type` | `step_loader` | Diagnostics |
| `length` | `step_loader` | `parting_line` (edge weights in Hou graph) |
| `adjacent_face_ids` | `step_loader` | `parting_line` (silhouette check), `undercut_detector` |
| `start_vertex`, `end_vertex` | `step_loader` | `parting_line` (wire construction) |
| `is_seam` | `step_loader` | `parting_line` (skip seam edges) |
| `convexity` | `undercut_detector` | `parting_line` (Sangolli classification) |
| `is_silhouette` | `parting_line` | API, frontend |
| `is_parting_edge` | `parting_line` | API, frontend |

### Adjacency Graph Invariants

These invariants must hold for the adjacency to be correct:

1. Every edge in `face_to_edges[face_id]` must have `face_id` in its `adjacent_face_ids`.
2. Every entry in `face_adjacency[face_id]` must be a face that shares at least one non-seam edge with `face_id`.
3. Seam edges appear in `face_to_edges` but NOT in `face_adjacency`.
4. Boundary edges (1 adjacent face) appear in `face_to_edges` but NOT in `face_adjacency`.
5. Non-manifold edges (3+ adjacent faces) trigger a warning. They should not appear in correctly modeled injection parts.

---

---

# SECTION 8 — ALGORITHMS

## Algorithm 1: STEP Loading (step_loader.py)

**Paper origin:** None — standard OCC usage patterns.

**Mathematical intuition:** None needed. This is parsing.

**Algorithm:**
```
1. STEPControl_Reader.ReadFile(path) → parse ISO 10303 text format
2. TransferRoots() → build OCC B-Rep model from STEP entities
3. OneShape() → get top-level TopoDS_Shape
4. For each face (TopExp_Explorer over shape):
   a. BRepAdaptor_Surface → get UV bounds and surface type
   b. GeomLProp_SLProps → evaluate normal and centroid at UV midpoint
   c. brepgprop.SurfaceProperties → compute exact area
   d. Apply orientation flip if face is REVERSED
5. For each face's edges (second TopExp_Explorer):
   a. Hash edge TShape pointer for deduplication
   b. Track which faces share each edge
   c. Detect seam edges (same hash twice in same face)
6. Build EdgeData for unique edges: BRepAdaptor_Curve for type/length
7. Hash-deduplicate vertices: BRep_Tool.Pnt for coordinates
8. Build adjacency maps from edge-face relationships
```

**Complexity:** O(F × E) in the worst case, where F = face count, E = edges per face. In practice O(F + E) because of hash-based deduplication.

**Current status:** Fully implemented and working.

## Algorithm 2: Draft Analysis (draft_analyzer.py)

**Paper origin:** Industry standard (SolidWorks DraftAnalysis convention). Referenced in Bassi (2010).

**Mathematical intuition:** 

Draft angle is simply the angle between the face normal and the pull direction. A vertical wall has normal perpendicular to pull (angle = 0°). A horizontal face has normal parallel to pull (angle = 90°). Injection molding requires at least 1.5° taper to allow ejection.

**Formula:**
```
draft_angle = arcsin(|n · d|)

where:
  n = outward unit normal of face
  d = pull direction unit vector
  · = dot product
  | · | = absolute value
```

The absolute value is taken because we don't care which side — only the magnitude of the taper.

**Complexity:** O(F) — one dot product per face.

**Current status:** Fully implemented. Runs in both mutating and non-mutating modes.

## Algorithm 3: Pull Direction Optimization (direction_optimizer.py + undercut_detector.py)

**Paper origin:** Bassi et al. (2010) — "Undercut-Free Parting Direction Determination for Injection Molded Parts Using Surface-Based Accessibility Analysis"

**Mathematical intuition:**

For each candidate direction `d`, we want to measure: "how many faces are inaccessible from this direction?" A face is inaccessible if there's material between it and the mold opening. We approximate this with:

1. **Fast prefilter:** `n · d < 0` → face points against pull → undercut candidate. This is a necessary but not sufficient condition for an undercut.

2. **Swept Boolean refinement (Bassi):** For a suspected undercut face, sweep it along direction `d` by `2 × diagonal` (creating a "projection volume" in front of it). Intersect with the part body. If the intersection volume > 0, there IS material blocking this face → confirmed undercut.

**Scoring:**
```
score = 1500 × (undercut_area / total_area)
      + 1000 × (bad_draft_area / total_area)
      + 100 × (marginal_draft_area / total_area)
      + interference_weight × (interference_volume / bbox_volume)
      + ... (smaller terms)
```

Lower score = better direction.

**Candidate generation:** Approximately sphere-sampling with 15° angular step. Tests ~30 candidate directions. Includes all 6 principal axes (+X, -X, +Y, -Y, +Z, -Z) plus intermediate angles.

**Pruning:** Only the top N candidates (by prefilter score) receive expensive Boolean refinement. The gate has multiple conditions to ensure important candidates aren't missed.

**Complexity:**
- Prefilter: O(C × F) where C = candidates (~30), F = faces (~100). Very fast.
- Boolean refinement: O(N × F_undercut × T_boolean) where N = promising candidates (~5), F_undercut = undercut face count, T_boolean = OCC Boolean operation time (~0.1–1s per operation).

**Current status:** Implemented. The fast prefilter is complete. The swept Boolean is implemented selectively (not for every face of every candidate — that would be too slow). Full Bassi regularized Boolean is not implemented.

## Algorithm 4: Undercut Feature Detection (undercut_detector.py)

**Paper origin:** Sangolli et al. (2021) — "Algorithms for sorting and recognizing of undercut features in plastic products"

**Mathematical intuition:**

After identifying which individual faces are undercuts, we group them into "features" — coherent undercut regions. A feature is a connected group of undercut faces that would require the same mold action (one slider, one lifter).

**Feature classification:**
- **Internal undercut:** The undercut is inside the part (e.g., a pocket, a hole from the side). Corresponds to a feature you cannot see from outside.
- **External undercut:** The undercut protrudes outward (e.g., a snap hook, an external flange).

**Depth estimation:** Uses either the centroid projection spread (how far the undercut faces extend in the pull direction) or the volume/area ratio of the Boolean intersection shape as a depth proxy.

**Action recommendation:**
- Deep severe undercut → `"side_core"` (expensive slider)
- Shallow internal → `"lifter"` (simpler mechanism)
- Minimal → `"redesign"` (add draft)
- Small/shallow → `"review"` (may not need action)

**Current status:** Implemented with proxy prefilter + optional swept Boolean refinement. Full Sangolli volumetric decomposition not implemented (would require decomposing the entire part into convex sub-volumes — expensive and brittle on real automotive parts).

## Algorithm 5: Parting Line Generation (parting_line.py)

**Paper origin:** Nee et al. (1998) + Hou et al. (2018)

**Nee (1998) — Silhouette Edge Detection:**

Mathematical intuition: The parting line is the "equator" of the part relative to the pull direction. It's where the face orientation changes from "facing up" to "facing down." An edge on the parting line has one adjacent face with `n · d > 0` and another with `n · d < 0`.

```
For each manifold edge (2 adjacent faces f1, f2):
  d1 = dot(f1.normal, pull_dir)
  d2 = dot(f2.normal, pull_dir)
  if d1 * d2 < 0:  # opposite signs
    edge is a silhouette edge → parting line candidate
```

**Wire construction:** Group silhouette edges by connectivity (shared vertices), then traverse to form an ordered wire. Select the component with largest projected area in the pull-normal plane (Nee's "maximum contour" rule).

**Hou (2018) — Graph-Based Refinement:**

For branched or gapped candidate sets, build a weighted edge graph and find the minimum-cost closed loop using shortest-path algorithms. Edge weights combine length, curvature, flatness, and proximity to critical regions.

**Current status:** Silhouette detection and wire construction are implemented. Hou-style global optimization is partially implemented (Hou-inspired graph cleanup for branched/gapped cases, but not the full optimization with B-spline smoothing).

## Algorithm 6: Core/Cavity Classification (core_cavity.py — NOT YET IMPLEMENTED)

**Mathematical intuition:**

Once the parting line is established:
- Faces with `n · d > 0` (normal pointing in pull direction) → cavity side
- Faces with `n · d < 0` (normal pointing against pull direction) → core side
- Faces on the parting line → parting faces

For core/cavity extraction:
1. Use the parting line as a cutting curve
2. Boolean split the solid along the parting surface
3. Extract two separate solid bodies (core half, cavity half)
4. Color them differently for visualization

This requires the parting line to be complete and geometrically valid. Since the parting line is not fully optimized yet, `core_cavity.py` cannot be completed.

---

---

# SECTION 9 — CURRENT IMPLEMENTATION STATUS

## Status Table

| Feature | Status | Notes |
|---------|--------|-------|
| STEP parsing | ✅ Implemented | Full topology extraction, all surface types |
| Face normal extraction | ✅ Implemented | UV midpoint evaluation, orientation-corrected |
| Face area computation | ✅ Implemented | Exact OCC surface integration |
| Edge extraction + adjacency | ✅ Implemented | Hash deduplication, seam edge handling |
| Vertex extraction | ✅ Implemented | Hash deduplication |
| Bounding box | ✅ Implemented | Exact analytical, no mesh approximation |
| Initial draft analysis (+Z) | ✅ Implemented | With mutate/non-mutate modes |
| Optimal draft analysis | ✅ Implemented | After direction optimization |
| Draft suggestions | ✅ Implemented | Grouped by surface type and mold side |
| Direction candidate generation | ✅ Implemented | 15° sampling, ~30 candidates |
| Direction scoring (prefilter) | ✅ Implemented | Draft + adjacency prefilter |
| Direction Boolean refinement | ✅ Partial | Selective swept Boolean, not exhaustive |
| Undercut detection (prefilter) | ✅ Implemented | Normal + draft prefilter |
| Undercut Boolean confirmation | ✅ Partial | Selective, not full Bassi decomposition |
| Undercut feature grouping | ✅ Implemented | BFS adjacency grouping |
| Undercut type classification | ✅ Partial | Rule-based heuristics, not full Sangolli |
| Undercut action recommendation | ✅ Implemented | With confidence scores |
| Display mesh generation | ✅ Implemented | Preserves face_id mapping |
| Parting line silhouette edges | ✅ Implemented | Adjacent-normal silhouette detection |
| Parting line wire construction | ✅ Implemented | Ordered wire, connected components |
| Parting line projection scoring | ✅ Implemented | Projected area, closure quality |
| Parting line undercut conflict | ✅ Implemented | Heuristic scoring |
| Parting line readiness gate | ✅ Implemented | ready/review/weak/failed |
| Hou graph optimization | ⚠️ Partial | Branched/gapped cleanup; full optimization not done |
| Core/cavity classification | ❌ Not implemented | Planned Level 2 |
| Core/cavity extraction (Boolean split) | ❌ Not implemented | Requires stable parting line first |
| LangChain agent | ❌ Not implemented | Orchestration layer planned |
| LangChain tools | ❌ Not implemented | Planned wrappers around geometry modules |
| PDF report export | ❌ Not implemented | Structure defined in `DFM_REPORT_OUTLINE.md` |
| Part2.stp validation | ❌ Not started | File not present in workspace yet |
| FastAPI endpoints | ✅ Implemented | Parts, summary, draft, undercuts, direction, parting line |
| Streamlit UI | ✅ Implemented | Guided 5-step flow, PyVista 3D viewer |
| Validation harness | ✅ Implemented | `part_validation.py` |
| Performance profiler | ✅ Implemented | `performance_profile.py` |

## What Is Missing for Level 1 Completion

Level 1 is essentially complete for demo purposes. What remains:

1. **Final parting line polish:** The current parting line implementation gives a displayable candidate curve. Full Hou-style optimization (B-spline smoothing, global minimum-cost loop) would make it production-quality.

2. **Part2.stp validation:** The second hackathon input file hasn't been tested yet because it wasn't in the workspace.

## What Is Missing for Level 2

Level 2 requires:

1. `core_cavity.py` — Face classification and Boolean solid split. Depends on a stable, complete parting line.
2. Final parting line optimization — A prerequisite for reliable core/cavity split.
3. API endpoints for core/cavity — Expose the split result.
4. Frontend visualization for core/cavity — Green/blue face color overlay.

## What Is Missing for Full "AI Agent" Vision

1. `backend/agent/dfm_agent.py` — LangChain orchestrator. Receives geometry outputs → sends to LLM → gets natural language reasoning → structures suggestions.
2. `backend/agent/tools.py` — Tool wrappers so the LLM agent can call `detect_undercuts(part, direction)` as a tool and get structured results back.
3. PDF export — Automated report generation from the DFM report outline (`DFM_REPORT_OUTLINE.md`).

---

---

# SECTION 10 — ENGINEER ONBOARDING GUIDE

## Files to Read First (in this order)

1. **`backend/models/geometry_models.py`** — Read this FIRST. It defines all data structures. You cannot understand any other module without knowing `PartGeometry`, `FaceData`, and `EdgeData`.

2. **`backend/geometry/step_loader.py`** — Read `load_step()` and the module docstring. Understand the pipeline entry point.

3. **`backend/geometry/draft_analyzer.py`** — Read the `analyze_draft()` function and the `DraftAnalysisResult` dataclass. This is the simplest module and teaches the pattern.

4. **`config.yaml`** (if available) — Read the DfM configuration section. All thresholds are here.

5. **`backend/api/main.py`** — Understand the REST endpoints. This shows how results flow from the geometry engine to the frontend.

6. **`backend/geometry/direction_optimizer.py`** — Understand the optimization loop: candidates → prefilter → Boolean refinement → select best.

7. **`backend/geometry/undercut_detector.py`** — The most complex module. Read the docstring, `detect_undercuts()`, and `UndercutFeature`. Don't try to read all 3400 lines at once.

8. **`backend/geometry/parting_line.py`** — Read the silhouette detection section and `PartingLineResult`.

## Files to Avoid Initially

- **`frontend/app.py`** — The Streamlit UI is large. You don't need it to understand the geometry engine. Come back when debugging visualization issues.
- **`backend/validation/`** — The harnesses are useful for testing but not for understanding the architecture.
- The long data-processing sections in `undercut_detector.py` — The key algorithmic ideas are in the first 200 lines. The rest is refinement.

## Foundational Modules

These must work correctly for everything else to work:

1. `geometry_models.py` (the data contract)
2. `step_loader.py` (produces all input data)
3. `draft_analyzer.py` (basic geometric operation that everything uses)

## Dependent Modules

These depend on foundational modules:

1. `direction_optimizer.py` depends on `draft_analyzer` + `undercut_detector`
2. `undercut_detector.py` depends on `draft_analyzer` results as prefilter
3. `parting_line.py` depends on `direction_optimizer` output (optimal direction)
4. `core_cavity.py` (not implemented) depends on `parting_line` output

## The Biggest Architectural Decisions

**Decision 1: `mutate` parameter in `analyze_draft()` and `detect_undercuts()`**

This is elegant. The same function can either write results into `FaceData` fields (for final display) or just compute and return (for candidate scoring). This prevents corrupting the active overlay while evaluating dozens of candidate directions.

**Decision 2: Hash-based deduplication for edges and vertices**

Instead of O(n²) comparison (`edge1.IsSame(edge2)` for all pairs), the code uses `edge.HashCode(2^31 - 1)` which is O(n). The collision probability for ≤5000 edges is ~6×10⁻⁶ — effectively zero.

**Decision 3: Visualization mesh is separate from analysis**

`visualize_raw.py` runs OCC's triangulation to create a display mesh. All analysis continues on the exact B-Rep. The `face_id` scalar on the mesh provides the bridge — each triangle knows which exact STEP face it came from.

**Decision 4: `PartGeometry` as the shared pipeline state**

Instead of passing dozens of arguments between functions, one object accumulates state as the pipeline progresses. Each module writes its results into `PartGeometry` fields. The object is a progressive state accumulator.

**Decision 5: Boolean pruning gate**

OCC Boolean operations are expensive and can be numerically brittle on real STEP files. The pruning gate ensures that only promising candidate directions receive expensive Boolean refinement. This is what makes the optimizer practical on real hardware.

## The Biggest Risks

**Risk 1: OCC Boolean operations failing**

OCC's Boolean operations (`BRepAlgoAPI_Common`) can fail on degenerate or near-degenerate geometry. The code has extensive try/catch handling and graceful degradation (proxy evidence if Boolean fails). But if Part2.stp has unusual geometry, you may see new failure modes.

**Risk 2: PyVista/VTK rendering issues**

The Streamlit frontend uses PyVista for 3D rendering, which requires VTK and Xvfb. In headless Docker environments, this can fail. The code has a fallback to show mesh counts without 3D rendering.

**Risk 3: Seam edge misdetection**

The seam edge detection (cylinder longitudinal line appearing twice in one face's wire) depends on hash comparison. If a STEP file has unusual topology, a non-seam edge might appear twice in a face's wire, getting incorrectly flagged as a seam. Check the `is_manifold` flag in adjacency stats.

**Risk 4: UV clamping side effects**

The UV parameter clamping (`_PARAM_LIMIT = 1e6`) means normals are evaluated at the center of the face, not necessarily at the actual centroid. For elongated faces, this can give a slightly wrong normal. The code uses this approximation intentionally for robustness, but it's worth knowing.

## Assumptions the Code Makes

1. **All coordinates are in millimeters.** Automotive STEP files are always mm. If a file is in meters or inches, the diagonal-based sweep distances will be wrong.

2. **The part is a single connected solid.** If `solid_count > 1`, a warning is emitted. Multi-solid parts are analyzed as a compound, which may give incorrect adjacency.

3. **Face normals are consistent outward.** The loader flips `REVERSED` faces. If a STEP file has inconsistent face orientations, core/cavity classification will fail.

4. **Part1.stp is a well-formed B-Rep.** No degenerate faces, no self-intersections, no zero-area faces.

## Mistakes That Could Break the Pipeline

**Mistake 1:** Serializing `occ_face` or `occ_shape` to JSON. These are C++ objects. They will crash. Always call `.to_dict()`.

**Mistake 2:** Running `analyze_draft()` with `mutate=True` during the direction search loop. This would corrupt the face classifications with the last candidate direction's values, not the optimal direction.

**Mistake 3:** Modifying `face_adjacency` or `edge_to_faces` after construction. These maps are built once by `step_loader` and must remain stable.

**Mistake 4:** Assuming face IDs are stable across different STEP files. Face IDs (`face_id`) are sequential within one loaded part. Face #12 in Part1.stp is not the same face as Face #12 in Part2.stp.

**Mistake 5:** Ignoring `normal_valid = False`. Every downstream function must check this flag before using `face.normal`. Degenerate faces (cone tips, zero-area patches) will have garbage normals.

**Mistake 6:** Using absolute Python list indices instead of `get_face(face_id)`. Face IDs might not be perfectly sequential if there were skipped/error faces during loading. Always use the `get_face()` accessor which handles the fallback.

---

---

# SECTION 11 — FUTURE DEVELOPMENT ROADMAP

## Priority 1 (Immediate): Parting Line Polish

**What's needed:** The Hou-style global graph optimization for the parting line. Currently, the code handles simple silhouette cases well and has a graph cleanup layer for branched/gapped cases. What's missing is the full minimum-cost closed-loop optimization with B-spline smoothing.

**Why it's first:** Core/cavity extraction requires a valid, complete parting line. This is the gating dependency for Level 2.

**Technical debt:** The `parting_line.py` file is already 2870+ lines. Consider splitting into:
- `parting_line_candidates.py` — silhouette detection + candidate classification
- `parting_line_wire.py` — wire construction + projection scoring
- `parting_line_optimization.py` — Hou graph optimization

## Priority 2: Core/Cavity Classification

**What's needed:** Implement `core_cavity.py`:
1. Classify each face as cavity/core/parting using `signed_dot(optimal_pull_direction)`
2. Extend the parting line into a parting surface (ruled surface sweep along the parting wire)
3. Boolean split the solid along the parting surface
4. Extract two solid bodies
5. Export them as separate STEP files or visualize as green/blue face overlays

**Complexity:** The face classification step is trivial (one dot product per face). The Boolean split is the hard part — OCC's `BRepAlgoAPI_Splitter` or a series of `BRepAlgoAPI_Section` operations.

## Priority 3: LangChain Agent Integration

**What's needed:**
1. `backend/agent/tools.py` — Wrap each geometry module as a LangChain tool. Example:
```python
@tool
def analyze_draft_tool(part_file: str, direction: list[float]) -> dict:
    """Analyze draft angles for an injection-molded part."""
    part = load_step(part_file)
    result = analyze_draft(part, tuple(direction))
    return result.to_dict()
```

2. `backend/agent/dfm_agent.py` — LangChain orchestrator. The agent receives:
   - The raw geometry results as a JSON context
   - The task: "Generate a DfM report and suggest corrections"
   - It reasons step by step and calls tools as needed

**Recommended LLM:** Use Claude API (via `anthropic` Python SDK) or any OpenAI-compatible endpoint. Config-driven so it can be swapped.

## Priority 4: PDF Report Export

**What's needed:** Automated PDF generation using the structure in `DFM_REPORT_OUTLINE.md`. Recommended approach: generate HTML from a Jinja2 template with embedded screenshots and tables, then convert to PDF using `weasyprint` or `reportlab`.

**Technical debt:** Screenshots of the 3D view need to be generated headlessly (PyVista offscreen rendering).

## Priority 5: Part2.stp Validation

**What's needed:** When Part2.stp is provided (more complex Level 2 part), run the full pipeline and validate that:
1. Loading succeeds
2. Direction optimization finds a good pull direction
3. Undercut detection finds features correctly
4. The parting line generation doesn't fail

**Note:** Part2 is where the current implementation will likely hit its limits first. Expect to encounter new failure modes in the Boolean operations.

## Performance Bottlenecks

| Operation | Typical Time | Notes |
|-----------|-------------|-------|
| STEP loading | 1–5s | Fast for Level 1 parts |
| Display mesh generation | 1–3s | Can be reduced with coarser deflection |
| Draft analysis (per direction) | <0.1s | Fast dot products |
| Direction optimization (prefilter) | 2–5s | O(candidates × faces) |
| Boolean refinement (per face) | 0.1–1s | Highly variable per face complexity |
| Full Boolean optimization | 30–120s | If not pruned — DO NOT run without pruning |
| Parting line detection | 1–5s | Graph traversal |

**Performance risk:** If the Boolean pruning gate is misconfigured (too many candidates pass through), the optimizer can take 5–10 minutes. The config parameters `boolean_refine_top_candidates`, `prefilter_skip_score_factor`, etc., control this.

## Scalability Concerns

1. **Multi-part sessions:** Currently, `PartGeometry` is created per request. If the API needs to handle concurrent users, the OCC shapes (which live in C++ memory) must be properly managed. OCC is not inherently thread-safe for shared shape handles.

2. **Memory:** A loaded `PartGeometry` for a 200-face part may use 50–200MB of memory (mostly the OCC C++ objects). For a web service with many concurrent users, this needs a cache with eviction policy.

3. **Part2 complexity:** Level 2 parts from Bosch may have 200–500 faces. The current boolean-pruned approach should scale, but the parting line graph optimization might become slow for highly connected graphs.

## Refactoring Opportunities

1. **`undercut_detector.py` is too large** — 3400 lines. The feature classification logic (`_classify_undercut_type`, `_recommend_mold_action`, `_classify_boolean_geometric_feature`) could be extracted into `undercut_features.py`.

2. **`direction_optimizer.py` mixes concerns** — The scoring function, pruning gate, and caching logic could each be their own module.

3. **No unified pipeline runner** — Currently, each module must be called explicitly in the right order. A `pipeline.py` module that orchestrates the full flow (load → draft → optimize → undercuts → parting line) would simplify the API layer and make testing easier.

4. **Configuration is stringly typed** — `settings.dfm.direction_search.boolean_refine_max_faces` works but adding new config keys requires updating multiple places. Consider moving to a validated Pydantic settings model.

## Technical Debt Summary (Ranked by Impact)

| Debt Item | Impact | Effort |
|-----------|--------|--------|
| Parting line optimization incomplete | Blocks Level 2 | Medium |
| `core_cavity.py` not implemented | Blocks Level 2 | Medium |
| `dfm_agent.py` not implemented | Missing "AI" part of "AI agent" | Medium |
| `undercut_detector.py` too large | Maintenance burden | Low |
| No unified pipeline runner | Code duplication in API | Low |
| No thread safety for OCC objects | Scaling concern | Low |
| PyVista headless rendering for PDF | Blocks PDF export | Low |
| Part2.stp not tested | Unknown unknowns | Unknown |

---

---

# APPENDIX: QUICK REFERENCE CHEAT SHEET

## Dot Products and Their Meaning

| Computation | Value | Meaning |
|-------------|-------|---------|
| `dot(face.normal, pull_dir) > 0` | Positive | Face is on cavity side (faces "up") |
| `dot(face.normal, pull_dir) < 0` | Negative | Face is on core side OR undercut |
| `dot(face.normal, pull_dir) ≈ 0` | Near-zero | Silhouette/parting region |
| `arcsin(abs(dot(face.normal, pull_dir)))` | 0–90° | Draft angle (0° = vertical = bad) |
| `dot(f1.normal, pull_dir) * dot(f2.normal, pull_dir) < 0` | Opposite signs | Edge is a silhouette edge → parting line |

## Key Code Patterns

**Iterating valid faces:**
```python
for face in part.valid_faces:  # excludes invalid normals
    angle = face.draft_angle_for_direction(pull_direction)
```

**Getting adjacent faces:**
```python
for neighbor_id in part.face_adjacency[face.face_id]:
    neighbor = part.get_face(neighbor_id)
```

**Getting edges of a face:**
```python
for edge in part.get_face_edges(face.face_id):
    if edge.is_silhouette:
        ...
```

**Checking if an edge is on the parting line boundary:**
```python
if len(edge.adjacent_face_ids) == 2:  # manifold interior edge
    f1 = part.get_face(edge.adjacent_face_ids[0])
    f2 = part.get_face(edge.adjacent_face_ids[1])
    d1 = dot3(f1.normal, pull_dir)
    d2 = dot3(f2.normal, pull_dir)
    if d1 * d2 < 0:  # opposite signs = silhouette
        edge.is_silhouette = True
```

## File → Module Mapping

| File | Module # | Responsibility |
|------|----------|---------------|
| `geometry_models.py` | 0 | Data contracts |
| `step_loader.py` | 1 | STEP → PartGeometry |
| `draft_analyzer.py` | 2 | Draft angle classification |
| `direction_optimizer.py` | 3a | Find best pull direction |
| `undercut_detector.py` | 3b | Detect + classify undercuts |
| `parting_line.py` | 4 | Parting line candidates |
| `core_cavity.py` | 5 | Core/cavity split (NOT IMPLEMENTED) |
| `visualize_raw.py` | — | B-Rep → display mesh |
| `dfm_agent.py` | — | LangChain agent (NOT IMPLEMENTED) |

---

*Document version: June 2026. Based on codebase state as shown in uploaded files.*
*Authors: Generated from full codebase analysis for onboarding the second engineer.*