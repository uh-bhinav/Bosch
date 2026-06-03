## understand 

## Problem statement broken down 

“Develop an AI-driven solution that analyzes 3D CAD model of an injection-molded automotive component and automatically provides the corrections needed in the part design to ensure trouble free manufacturing.” 

## Ai driven and 3d cad model: 

1. They want something intelligent (geometric algorithms + potential ML later) that mimics what a senior mold designer does in minutes instead of hours. 

2. Specifically .stp (STEP) files — the ISO 10303 B-Rep (Boundary Representation) standard. This is exact geometry (faces, surfaces, edges, topology) used in automotive/CATIA/Siemens NX workflows 

3. not a triangle mesh like STL. 

4. We must parse true NURBS/analytic surfaces. 

## Injection-molded automotive component: 

1. Plastic part made by shooting molten polymer into a steel mold at high pressure/temperature. Automotive parts are high-volume, safetycritical, tight-tolerance (e.g., dashboards, brackets, housings). 

2. They have ribs, bosses, snaps, undercuts, textures — all of which create DfM headaches. 

## Automatically provide corrections: 

1. The tool should flag issues (bad draft, undercuts, poor parting line) 

2. suggest fixes (change pull direction, add draft, reposition features, or split differently). Not just detection — actionable output agentic form. 

## Trouble free manufacturing: 

1. Zero flash, easy ejection, no mold damage, minimal side-actions (expensive), good cosmetics, repeatable cycle times. 

## _Functional Capabilities to deliver:_ 

## _1._ Automatic Parting Line Detection from 3D CAD model. 

## 2.Automatically determine the optimal mold opening direction (the “pull 

direction” / line-of-draw). 

3.Parse STEP geometry → extract faces, edges, topology. 

4.Evaluate surface normal and draft angles → normals tell which way a face points; draft angle = taper relative to pull direction (industry minimum ~0.5–2°; textured parts need more). 

5.Detect undercuts → any geometry that “locks” the part in the mold (negative draft or overhang relative to pull direction). These force expensive slides/lifters/ side cores. 

6.Propose a manufacturable core-cavity split with clear visualization on the model. 

## Open-source feasibility (confirmed): 

1.pythonOCC (OpenCascade Python bindings) + CadQuery is the gold standard for exact STEP B-Rep parsing, face normals, draft calculation, edge extraction. 2.FreeCAD API, VTK/PyVista for visualization, Trimesh as fallback. 

3.Research papers exist on algorithmic undercut detection and automatic parting line generation (slicing, visibility, graph-based methods). 

Mold designers are specialized mechanical/design engineers (often with 5–15+ years experience) who translate a product designer's 3D part model into a complete, manufacturable injection mold (the steel tool that will produce thousands/millions of plastic parts). 

Daily responsibilities (this is the pain our tool solves): 

- Receive a part CAD (.stp from designers) → perform DfM (Design for Manufacturability) analysis: draft angles, parting line location, undercut detection, wall thickness, flow simulation, ejection feasibility. 

- Design the full mold assembly: core + cavity halves, cooling channels, ejector pins, slides/lifters (if needed), gating, venting. 

- Run mold-flow simulations (e.g., Autodesk Moldflow) to predict fill, warpage, sink marks. 

- Collaborate with part designers to suggest (or force) changes: "add draft here," "move this rib," "change pull direction." 

- Prepare detailed 2D manufacturing drawings for the tool shop (CNC, EDM, polishing). 

- Iterate 3–4+ hours per part on manual verification (exactly what the PDF shows in the "Without DfM Agent" workflow). 

## Flagging & Suggesting Corrections: Most UX-Friendly, IndustryStandard Way 

Industry standard (SolidWorks Mold Tools, Moldflow, Protolabs DFM reports): 

- Interactive 3D viewer with color-coded overlays on the model. 

- Clickable highlights + callouts (e.g., "Face X needs +1.5° draft"). 

- Side panel: prioritized issue list + one-click "Apply suggestion" preview. 

- Export: annotated STEP or PDF report with screenshots 

Repositioning Features & Adding New Drafts: How They Do It 

## Now 

Current manual process (what takes hours): 

- Open native CAD (CATIA/NX/SolidWorks). 

- Use Draft tool: select faces → choose neutral plane (often parting line) → input angle → apply. 

- For repositioning: drag/move features, add fillets/chamfers, or use "Move Face." 

- Re-run draft/undercut analysis → iterate. 

Our agent should propose these changes automatically (e.g., "Rotate this boss 2°" or "Add 1.5° draft to these 12 faces") with visual preview. 

## Why Two .STP Files as Inputs? 

Per the hackathon PDF ("Inputs: Two Design Files(.stp) will be provided"): 

- One simple (Level 1) → tests basic optimal mold direction + main parting line + visualization. 

- One complex (Level 2) → adds core/cavity extraction. 

## Core Algorithms & Methodologies We Will Use (Direct from Papers) 

We build a hybrid geometric pipeline (not reinventing anything — productizing the best 25+ years of research). 

## A. Optimal Mold Direction (Pull Direction) — Level 1 Primary paper: Bassi et al. (2010) – “Undercut-Free Parting Direction Determination... using Surface-Based Accessibility Analysis” (CAD Journal). 

Why we use it: Most accurate B-Rep-native method; no mesh approximation errors. 

Key steps (exact adaptation for pythonOCC): 

1. Load STEP → extract all faces + surface normals + topology (pythonOCC TopoDS_Face, BRepTools). 

2. For candidate directions (discrete sampling: ±X, ±Y, ±Z + 15° increments around principal axes). 

3. Surface classification via sweeping + Boolean: 

   - For each face, sweep it along the candidate direction by >2× part bounding box. 

   - Perform regularized Boolean subtraction (OCC BRepAlgoAPI_Cut / BOPAlgo). 

   - Classify face: 

      - Fully accessible (positive draft, no undercut). 

      - Partially accessible or inaccessible (undercut). 

4. Score direction: Minimize inaccessible faces + undercut volume. 

5. Pick best direction (undercut-free if possible). 

This is Level 1 core (matches evaluation matrix). 

## B. Undercut Feature Recognition (supports Direction + Core/Cavity) Primary paper: Sangolli et al. (2021) – “Algorithms for sorting and recognizing of undercut features...” (Materials Today: Proceedings). 

Why we use it: Directly uses STEP AP203 translator + volumetric decomposition — perfect for our inputs. 

## Key steps: 

1. Parse STEP → B-Rep or CSG. 

2. Volumetric decomposition: Split part into convex sub-volumes (OCC Boolean + convex-hull). 

3. Radix sort on features by directionality (internal/external undercut). 

4. Compute undercut location, depth, and release direction per feature. 

5. Flag for side-actions if needed (future Level 3). 

This gives us quantitative undercut metrics (volume, depth) for scoring 

directions and suggesting corrections. 

## C. Main Parting Line Creation & Highlighting 

## Primary papers: 

- Nee et al. (1998): Projected-area + silhouette edge-loops. 

- Hou et al. (2018): Hybrid visibility + graph-based parting curve generation. 

## `●` 

## Exact steps (combined): 

1. With optimal direction fixed, project all edges onto plane perpendicular to pull direction. 

2. Find maximum projected contour (silhouette loop) using visibility map (face normals). 

3. Build graph of silhouette edges (adjacency via topology). 

4. Traverse graph to generate smooth, manufacturable parting curve (minimize sharp turns, avoid critical features). 

5. Highlight as thick colored curve in 3D viewer. 

## Visualization output: Parting line rendered as red/blue curve on the model. 

## D. Core & Cavity Extraction (Level 2) 

## From Bassi + Yusof et al. (2018) + industry Mold Tools: 

1. After parting line + direction: 

2. Classify every face: 

   - Cavity side: normal aligns with pull direction (positive). 

   - Core side: opposite. 

3. Use Boolean split along parting surface to extract two solids. 

4. Assign colors (green = cavity, blue = core) + export separate STEP bodies. 

## E. Draft Analysis & Suggestions (flagging corrections) 

Built-in OCC + SolidWorks-style: 

- For each face: draft angle = acos(dot(normal, pull_dir)). 

- Color-code: green (>1.5°), yellow (0.5–1.5°), red (negative/undercut). 

- Suggest: “Add 1.5° draft to these N faces using neutral plane = parting line.” 

## Full pipeline flowchart (we’ll include this exact diagram in the report): 

1. Load STEP → Parse B-Rep 

2. Undercut detection + optimal direction (Bassi 2010) 

3. Draft analysis 

4. Parting line (Nee/Hou) 

5. Core/Cavity split & extraction 

6. Visualization + suggestions → Export annotated model + repor 

This hybrid is more accurate than any single paper or basic CAD wizard 

because it combines accessibility (Bassi), STEP-native features (Sangolli), and graph-based cleanliness (Hou). 

The hackathon title is literally **“DfM Agent Hackathon”** and the problem statement opens with **“Develop an AI-driven solution”**. So far we have been laser-focused on the **precise geometric engine** (pythonOCC + Bassi/Nee/ Sangolli papers) because that is the **hardest and most critical part** — without accurate STEP parsing, undercut detection, parting line, and corecavity split, nothing else matters. 

But you are 100% right: that engine by itself is still “just” a smart CAD script. 

### Where the Main AI Agent Lives (The Brain of the DfM Agent) 

The **main AI Agent part** is the **intelligent orchestration layer** we build **on top of** the geometric engine. This is what turns the whole system into a real **DfM Agent** that feels intelligent, conversational, and helpful — exactly what Bosch expects from an “AI-driven” tool. 

#### How the AI Agent Works (Simple & Powerful Hybrid Architecture) 

1. **Geometric Engine (Tools)** ← Backend owns this 

- All the algorithms we planned (optimal mold direction, draft analysis, parting 

line, core/cavity extraction, undercut detection). 

- Exposed as clean, callable tools/functions (e.g. `detect_undercuts(part, direction)`, `generate_parting_line(...)`, `extract_core_cavity(...)`). 

2. **AI Agent Layer (The Brain)** ← This is the “main AI agent part” 

- Powered by an LLM (Grok API, Claude, or even a local open-source model — all allowed and easy to integrate). 

- Uses a lightweight agent framework (LangChain, LlamaIndex, or even a simple custom loop — we can keep it very light for the hackathon). 

- The agent: 

- Receives the raw geometric results. 

- **Reasons** step-by-step (“This direction has 3 undercuts… the best alternative reduces it to 0…”). 

- **Generates human-friendly explanations and suggestions** (“Add 1.5° draft to these 8 faces using the parting line as neutral plane”). 

- **Decides next actions** autonomously (e.g., “Let me try 3 more pull directions and pick the best”). 

- **Handles edge cases** intelligently (“This parting line crosses a cosmetic surface — recommend override?”). 

- Talks to the designer in natural language. 

3. **Frontend** consumes both the geometric output **and** the agent’s reasoning to show beautiful interactive results. 

This hybrid (precise geometry + intelligent LLM agent) is **exactly** what differentiates us from every other team. Most teams will either: 

- Do only basic geometry (no real AI), or 

- Try to do everything with pure ML (which fails on exact STEP B-Rep accuracy). 

We get the best of both worlds — **industrial-grade accuracy + true AI intelligence**. 

### How It Fits Into Our 4 Roles (No Extra Complexity) 

- **Backend Engineer**: Owns the geometric tools + exposes them cleanly so the Agent can call them. 

- **Frontend Engineer**: Displays the Agent’s output (explanations, suggestions, confidence scores) in the 3D GUI. 

- **Tester**: Validates both the geometry **and** the Agent’s suggestions/ accuracy. 

- **Presenter/Reporter/Documenter**: Highlights this hybrid architecture in the report and demo as our key innovation. 

We can implement the Agent layer in **< 2 days** once the geometric tools are ready (it’s mostly prompt engineering + tool calling). 

## What Exactly Are We Building? 

We are building a professional-grade, production-ready starter DfM Agent 

— not a small gimmicky prototype. 

## It is a complete, working digital solution that: 

- Automatically analyzes real automotive .STEP files (exact B-Rep geometry). 

- Detects optimal mold opening direction. 

- Generates and highlights the main parting line. 

- Distinguishes and extracts Core vs Cavity surfaces (Level 2). 

- Provides clear 3D visualization + intelligent suggestions/corrections. 

- Includes a lightweight AI Agent layer on top that reasons, explains, and suggests design fixes in natural language. 

This directly fulfills (and exceeds) every word of the hackathon problem statement and scope. 

## Bosch Can Directly Use & Build On Top of It 

## Yes — this is intentional design, not an afterthought. 

The hackathon PDF explicitly says: 

“Code should be easy to update for future revisions or correction.” 

We have treated this as the north star requirement from the beginning. Our entire architecture, code structure, and documentation are built so that Bosch’s internal engineers (or the winning team during a 4-month internship) can: 

- Fork the repo and continue development immediately. 

- Add new features (side cores/lifters, flash constraints, override logic — Level 3). 

- Integrate with their existing CATIA / NX / Moldflow workflow. 

- Swap or upgrade the AI model, add company-specific rules, or connect to internal databases. 

- Maintain and extend it long-term without pain. 

This is exactly the kind of code Bosch would feel comfortable putting in front of their mold designers on Day 1 after the hackathon. We are not building a “demo that works once on the judge’s laptop.” We are building the first version of the actual internal DfM Agent that Bosch can adopt, productize, and scale — and that positions the winning team perfectly for the 4-month internship (Level 3) and beyond. We have considered this at every step — from role definitions, to repo structure, to choosing pythonOCC (industry-standard open-source), to the hybrid geometry + AI Agent design. 

This is why the team structure (Backend, Frontend, Tester, Presenter/Reporter) is set up the way it is — so we deliver something solid, maintainable, and impressive. 

we are 100% aligned on vision. 

