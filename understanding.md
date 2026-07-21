# The Complete Zero-to-Presenter Guide to the Bosch DfM Agent

> Read this top to bottom. Nothing assumes prior knowledge. Every acronym is expanded the first time it appears. Analogies are used deliberately — memorize the analogy, not the jargon, and the jargon will make sense on its own.
>
> **Important honesty note before we start:** I read every markdown file you attached (`README.md`, `onboarding.md`, `understand.md`, `working.md`, `Engine.md`, and the `docs/` folder) AND the actual Python source code, because code is ground truth and docs go stale. I found one real discrepancy worth knowing before you present: the docs say `core_cavity.py` and the "Core/Cavity" feature are "not implemented." That is **out of date**. The code shows a working `classify_core_cavity()` function, a live API endpoint (`GET /parts/{filename}/core-cavity`), and a full Streamlit tab with 3D color visualization. It is a **face-classification-only** version of core/cavity (each face is labeled cavity/core/parting — no actual splitting of the solid into two separate 3D bodies yet). I flag exactly how to phrase this honestly in Part 9 and Part 10. Everything else in this document has been cross-checked against the code.

---

# PART 1 — THE HACKATHON PROBLEM: WHAT, WHY, AND WHERE WE FIT

## 1.1 The exact ask, decoded word by word

Bosch's problem statement:

> "Develop an AI-driven solution that analyzes a 3D CAD model of an injection-molded automotive component and automatically provides the corrections needed in the part design to ensure trouble-free manufacturing."

Break every phrase apart, because the codebase is a direct, literal translation of this sentence:

- **"AI-driven solution"** — Bosch does not want a dumb script that prints numbers. They want something that *reasons* and *explains itself* in plain English, the way a senior engineer would talk to a junior one. This is why the architecture has a planned "brain" layer (an LLM — Large Language Model, explained in Part 4) sitting on top of the math. Today that brain layer is not built yet (the files exist but are empty) — the math/geometry layer is what's real, and it's genuinely the hard 90% of the problem.
- **"3D CAD model"** — specifically a **STEP file** (`.stp`). Not a photo, not a 3D-printable mesh, not a scan. An exact mathematical blueprint of every curved surface on the part. Explained fully in Part 2 and Part 4.
- **"Injection-molded automotive component"** — the physical part is manufactured by injecting molten plastic into a steel mold under huge pressure. This manufacturing method imposes hard geometric constraints on the part's shape — you cannot design a part in CAD without also, in effect, designing a mold. That is the entire discipline this software works in. Explained fully in Part 2.
- **"Automatically provides the corrections"** — not just "detect problems," but "propose the fix." Example: not "Face 47 is bad" but "Face 47 has 0.2° draft; add 1.5° draft using the parting line as the neutral plane." The codebase's `DraftSuggestion` and `UndercutFeature.recommended_mold_action` objects are literally this requirement made into code.
- **"Trouble-free manufacturing"** — no part sticking in the mold, no mold damage, no need for expensive extra mold mechanisms if avoidable, and the ability to run millions of identical parts reliably (automotive volumes are enormous — think hundreds of thousands to millions of units of a single bracket).

## 1.2 Who actually uses this tool, and what their day looks like today

The user is a **mold designer** (also called a mold engineer / tooling engineer). This is a mechanical engineer, usually with 5–15+ years of experience, whose entire job is to take a plastic part design and figure out how to build the steel mold that will manufacture it.

**Today, without any tool like ours, their workflow for one part is:**

1. Product designer finishes a part in CATIA/SolidWorks/NX and exports/sends a `.stp` file.
2. Mold engineer opens the file in expensive CAD software (5+ minutes just to load).
3. Runs a built-in "Draft Analysis" tool, picks an initial direction (almost always straight up, `+Z`, first) and looks at a color-coded 3D preview.
4. Manually scans the model for red (bad) zones, writes them down.
5. Manually looks for undercuts — geometry that would physically block the part from sliding out — by eye, sometimes assisted by another built-in tool.
6. Tries 3–5 other candidate directions by hand, re-running the analysis each time, comparing results mentally.
7. Picks the best direction they found.
8. Manually traces where the mold should split (the parting line) by eye, checking it looks sensible.
9. Writes up a report (often in Word/PowerPoint) listing every problem and the suggested fix.
10. Sends it to the product designer.
11. Product designer updates the model.
12. Repeat from step 3 — this iterates **3 to 4 times** typically.

**Each single pass through steps 3–9 takes an experienced engineer 3–4 hours.** For a complex automotive part (ribs, bosses, snap features, cosmetic surfaces), a single pass can eat an entire day. Multiply by 3–4 iterations and you can see why this is a real bottleneck in getting a part into production. Our software's entire reason to exist is to compress that 3–4 hour manual loop into something that runs in under two minutes and needs zero manual searching.

## 1.3 What exists before our software touches anything, and what happens after

**Before our software (upstream):**

- A product/industrial designer designs the physical shape of the part in a full CAD system: CATIA, Siemens NX, or SolidWorks. This is a totally separate, much bigger piece of software that our project does not touch or reimplement.
- That designer exports the finished 3D shape as a `.stp` (STEP) file — this is the universal hand-off format between different CAD vendors' software, the same way a `.pdf` is a universal hand-off format between different word processors.
- That `.stp` file is dropped into our system's input folder (`data/parts/`).

**Our software's job (the entire scope of this codebase):**

- Read that exact geometry.
- Figure out the best direction to open the mold.
- Find where the wall angles are too steep (bad draft).
- Find any geometry that would physically trap the part in the mold (undercuts).
- Find where the mold should physically split (the parting line).
- Classify which faces belong to which mold half (core vs. cavity — foundation level today).
- Show all of this visually in a browser, and (eventually, not yet built) explain it in plain English and generate a PDF report.

**After our software (downstream, not built by us):**

- A human mold engineer reads our output and uses it as a fast starting point instead of starting from zero.
- They still do the full mechanical mold design in CATIA/NX (cooling channels, ejector pins, steel block dimensions, etc.) — our tool never replaces the entire mold design job, only the *analysis and recommendation* phase that currently eats hours per iteration.
- The product designer receives our (or the mold engineer's) recommendations and edits the part CAD model, and the file is fed back through the loop again.

So: **we are a fast, automated analysis layer that sits between "part is designed" and "mold is designed," replacing the slowest, most repetitive 3–4 hours of manual trial-and-error with an automated pass that a human then reviews.** We do not replace CATIA/NX/SolidWorks. We do not replace the mold engineer. We remove the manual grind from the *first* pass of their job.

---

# PART 2 — INJECTION MOLDING FROM ABSOLUTE ZERO

Forget CAD and code for a moment. This section is pure physical, mechanical intuition. Once this clicks, every geometric rule in the code will feel obvious instead of arbitrary.

## 2.1 What a mold physically is

**Analogy: an ice cube tray, but steel, and for plastic.**

Picture a solid block of steel with a hollow shape carved into it — exactly the shape of the part you want, but hollow (like a mold for a cake, or a chocolate bar, or an ice cube). You inject molten plastic (150–350°C) at very high pressure (up to ~1500 bar — for comparison, a car tire is about 2 bar) into that hollow cavity. It fills up, cools, hardens into the shape of the part, and then you have to get the solid part back out.

A real automotive injection mold is a precision-machined steel tool costing **$50,000 to $500,000** and takes months to manufacture. Every single design rule in this entire field — draft angle, undercuts, parting lines — exists purely to answer one question: **"How do we get the solidified part out of this expensive steel block without breaking the block or the part?"**

## 2.2 Core and cavity — the two halves

A basic mold ("two-plate mold," the cheapest, simplest kind) is made of exactly two steel blocks that clamp together, injection happens, then they pull apart.

```
     ┌───────────────────────┐
     │    CAVITY (top half)  │   ← the part's outward/upward-facing surfaces are carved here
     │   ┌───────────────┐   │
     │   │   PART SHAPE  │   │   ← the plastic fills this hollow shape
     │   └───────────────┘   │
     │    CORE (bottom half) │   ← the part's downward-facing surfaces are carved here
     └───────────────────────┘
```

**Analogy:** think of a waffle iron. It has a top plate and a bottom plate, each carved with half the pattern. Close them, pour batter, cook, open them, the waffle (with a seam line around its edge where the two plates met) pops out. The **cavity** is like the top plate (usually shapes what you see "from above"), the **core** is like the bottom plate (shapes what you see "from below"). The visible seam line running around your waffle is exactly analogous to the **parting line** — more on that in 2.5.

## 2.3 The pull direction (a.k.a. mold opening direction, line of draw)

When the mold finishes cooling, the two halves physically separate by sliding apart in one single straight direction — like pulling two Lego bricks apart. That single direction is the **pull direction**.

Everything else in this whole domain is defined *relative to* the pull direction. It is the single most foundational decision, and it is exactly why, in the codebase, `direction_optimizer.py` runs before almost everything else — every other module needs a pull direction as an input.

In the code this is just a 3D unit vector — a direction with length exactly 1, like `(0, 0, 1)` meaning "straight up." Obvious first guess: point it straight up (`+Z`). But for a complex real automotive part, straight up is very often *not* the best choice — some other tilted direction might avoid far more problems. Finding that better direction automatically, instead of a human guessing and checking 5 directions by hand, is one of the two core deliverables of "Level 1" of this hackathon.

## 2.4 Draft angle — the single most important number in this whole field

**Physical reason draft angle exists at all:** as plastic cools inside the mold, it shrinks very slightly and grips the steel walls (a bit like how a rubber band grips your wrist). If a wall of the part is perfectly parallel to the pull direction (i.e., perfectly vertical relative to how the mold opens), there is zero angle helping it slide free — it will drag, scratch, deform, or outright get stuck as the mold tries to open. You need every wall to be very slightly tapered — angled outward, like a bucket is wider at the top than the bottom — so that as the mold pulls away, the wall immediately separates from the steel instead of scraping along it.

**Analogy:** think about pulling a muffin out of a muffin tin. Muffin tins are always tapered — wider at the top, narrower at the bottom. That taper is draft. If muffin tins were perfectly cylindrical (zero draft), muffins would tear apart or get stuck every single time. The manufacturer's whole tin design exists to guarantee that taper.

**The formula used everywhere in this codebase (the SolidWorks/industry-standard definition):**

```
draft_angle = arcsin( | n · d | )
```

- `n` = the face's outward normal vector — imagine an arrow sticking straight out of the surface, perpendicular to it, pointing away from the solid material.
- `d` = the pull direction (unit vector).
- `·` = the **dot product** — a way of multiplying two vectors that produces one number describing how aligned they are. If two vectors point the exact same way, the dot product of their unit versions is `1`. If perpendicular, it's `0`. If opposite, it's `-1`.
- `arcsin` = "inverse sine" — given a ratio, tells you the angle that produces that ratio. It converts the dot-product number back into a real angle in degrees.
- `| |` = absolute value — we don't care whether the face leans one way or the other, only how far it is from vertical.

**Intuition without the formula:** a horizontal, flat face (like the flat lid of a box) has its normal pointing straight up, exactly parallel to a straight-up pull direction — that's the best possible case, 90° draft, completely safe. A perfectly vertical wall has its normal pointing sideways, exactly perpendicular to the pull direction — that's the worst case, 0° draft, guaranteed to stick.

**Industry thresholds used in this project (and encoded in `config.yaml`):**

| Draft angle | Classification | Color in the UI | Meaning |
|---|---|---|---|
| ≥ 1.5° | Good | Green | Safe, ejects cleanly |
| 0.5°–1.5° | Marginal | Yellow | Risky, may drag or scuff, needs review |
| < 0.5° | Bad | Red | Will almost certainly stick or damage the part/mold |

## 2.5 Undercuts

**Analogy: a doorknob through a mail slot.** A round doorknob is physically bigger than a keyhole-shaped mail slot cut for it — you can't pull the knob straight through the slot no matter how hard you try, because part of the knob is "hidden" behind material that's in its way. That is exactly what an undercut is.

**Formal definition:** any part of the geometry that is "shadowed" from the pull direction — meaning if the mold tried to pull straight away in the chosen direction, some solid material would be in the way and block that face from ever separating cleanly.

```
          Pull direction ↑

    No undercut:          Undercut (overhang):
       /\                   /\
      /  \                 /  \
     /    \               /    \___  ← this overhang blocks straight-line release
    /______\             /______/
```

**Real automotive example:** a plastic snap-clip on the underside of a dashboard panel. The clip has a little hook that curls back inward so it can grab onto another part. From directly above, you literally cannot "see" the underside of that hook — it's blocked by its own geometry. That hook is an undercut.

**Why undercuts are expensive, not just "wrong":** to still manufacture a part that has an undercut, the mold needs an extra moving mechanical piece — a **slider** or **lifter** (explained in 2.7) — that physically moves out of the way *before* the main mold opens. Every one of these extra moving pieces adds **$5,000–$50,000** to the mold's cost, adds a moving part that can wear out or jam over years of production, and adds complexity to every maintenance cycle. This is why undercut detection is treated as seriously as draft angle in this project — it's a direct cost driver, not just a cosmetic issue.

## 2.6 The parting line

**Analogy: the seam on a chocolate Easter egg, or the equator line on a globe held up to the light.** Hold a ball in one hand and look at it from directly above. There's an invisible line running around the "widest" part of the ball as seen from that angle — everything above that line is visible from above, everything below is hidden. That line is the parting line's geometric definition: it's the boundary between "faces visible from the pull direction" and "faces hidden from the pull direction."

**Physical reality:** it is the actual 3D curve, running all the way around the part, where the two mold halves physically touch and seal against each other. Molten plastic must never leak across this line (that leak defect is literally called "flash"). This line also always leaves a faint visible seam on the finished plastic part — go check any plastic bottle cap or car interior trim piece and you'll see a thin line running around it. That's a real parting line, visible with your own eyes.

**What makes a good parting line:** it should form one single closed loop around the whole part, it should be as flat/simple as possible (a wavy, complicated parting line means a more expensive, harder-to-machine mold), and it should avoid cutting across cosmetic show-surfaces where a visible seam would look bad.

**How the code finds candidates for it:** an edge (the line where two surface patches meet) is a parting-line candidate if one of its two neighboring faces is on the "cavity side" (its normal points roughly along the pull direction) and the other neighboring face is on the "core side" (its normal points roughly against the pull direction). This is called a **silhouette edge** — literally the edge where the visible side flips to the hidden side, same as the outline you'd draw if you traced around a photo's silhouette.

## 2.7 Sliders and lifters — the expensive fix for undercuts

**Slider (a.k.a. side core):** a block of steel inside the mold that sits sideways relative to the main pull direction. Right before the main mold opens, a slider retracts sideways first, pulling itself out of an undercut pocket, and only *then* does the main mold open normally. Think of a kitchen drawer that has to slide out sideways before you can lift the whole cabinet's lid off.

**Lifter:** similar idea but usually a smaller pin or block that moves at an angle (not purely sideways) as the mold ejects the part, freeing an internal undercut as it goes.

Both mechanisms work, but they are exactly the "expensive modification" mentioned back in Part 1 — the mold engineer's report to the product designer usually starts with "can we avoid needing a slider here by adding draft / removing this hook / rotating this boss?" before accepting the extra cost. This is precisely why the code's `UndercutFeature.recommended_mold_action` field can say `"redesign"` (fix the part, cheapest), `"lifter"` (medium cost), or `"side_core"` (most expensive) — it's mirroring exactly this real engineering triage.

## 2.8 The dependency chain — why the pipeline is ordered the way it is

```
STEP file loaded
      │
      ▼
Pull direction chosen ← EVERYTHING below depends on this one choice
      │
      ├──► Draft analysis (angle is measured relative to pull direction)
      │
      ├──► Undercut detection (blocked/not-blocked is relative to pull direction)
      │
      └──► Parting line (silhouette edges only exist relative to pull direction)
                │
                ▼
          Core/cavity face split (needs the parting line's "which side" logic)
                │
                ▼
          (Planned) AI agent explains everything in English
                │
                ▼
          (Planned) PDF report
```

You cannot compute a draft angle without first knowing which direction the mold opens. You cannot decide if a face is an undercut without knowing the pull direction. You cannot find the parting line without knowing the pull direction. This single fact is *why* `direction_optimizer.py` is treated as the highest-priority module in the whole codebase, and it's the single most important sentence you can say if a judge asks "why is your pipeline ordered this way?"

## 2.9 How commercial CAD software (SolidWorks, CATIA, Siemens NX) does this today

Understanding what the "gold standard" commercial tools do helps you explain exactly what we're replicating (and what we're not).

- **SolidWorks "Draft Analysis" tool:** you pick a pull direction, and SolidWorks colors every face of the model green/yellow/red using the *exact same* `arcsin(|n·d|)` formula this codebase uses — this isn't a coincidence, we deliberately matched the industry-standard convention so our numbers mean the same thing a mold engineer already expects. SolidWorks does this on the internal exact math surfaces (it's a full CAD authoring tool, so it has the exact geometry natively, no import needed).
- **CATIA "Mold Tooling Design" workbench / "Core & Cavity" tools:** CATIA has semi-automated wizards where an engineer manually selects candidate parting-line edges, and the software helps extend them into a full parting surface, then Booleans (a geometric operation explained in Part 4) the solid into two separate core/cavity bodies. This is largely human-guided, click-by-click — the human is still the one recognizing the undercuts and choosing the parting surface path; CATIA mostly automates the *drawing/surfacing/Boolean* mechanics once a human has made the calls.
- **Siemens NX "Mold Wizard":** similar to CATIA — strong manual/semi-automated tooling for splitting a part into mold components, again relying on an experienced human to identify problem areas first.
- **Autodesk Moldflow:** a completely different tool focused on *simulating the physics* of molten plastic flowing and cooling inside a candidate mold design (fill patterns, warpage, weld lines) — this is downstream of everything we do; we never simulate plastic flow, only pure geometry accessibility.

**What none of these commercial tools do out of the box:** *fully automatically* search dozens of candidate pull directions and score them by draft+undercut quality, *and* automatically propose the actual correction text, *and* do it via an open, scriptable, free pipeline that a company can embed into their own internal tools. That gap — full automation of the direction search plus natural-language correction suggestions — is exactly the opportunity Bosch is pointing at with "AI-driven solution," and it's exactly what this codebase's `direction_optimizer.py` + (planned) LLM agent layer targets.

---

# PART 3 — THE COMPLETE ARCHITECTURE, LAYER BY LAYER

## 3.1 The layers, top to bottom

```
┌───────────────────────────────────────────────────────────────────┐
│  YOUR BROWSER (Chrome/Safari) — http://localhost:8501             │
│  Just renders HTML/JS that Streamlit generates. No CAD math here. │
└──────────────────────────────┬──────────────────────────────────────┘
                                │  HTTP requests (browser ↔ Streamlit's built-in web server)
                                ▼
┌───────────────────────────────────────────────────────────────────┐
│  FRONTEND — frontend/app.py, run by Streamlit                     │
│  Python code that builds the web page. Calls the backend over     │
│  plain HTTP+JSON, using the `requests` library. Contains ZERO      │
│  geometry/CAD imports. Just a client + a 3D viewer widget.         │
└──────────────────────────────┬──────────────────────────────────────┘
                                │  HTTP requests: GET http://backend:8000/parts/...
                                ▼
┌───────────────────────────────────────────────────────────────────┐
│  BACKEND — backend/api/main.py, run by FastAPI + uvicorn           │
│  Receives HTTP requests, calls the geometry engine functions,      │
│  converts Python objects to JSON, sends the response back.         │
└──────────────────────────────┬──────────────────────────────────────┘
                                │  plain Python function calls (same process, no network)
                                ▼
┌───────────────────────────────────────────────────────────────────┐
│  GEOMETRY ENGINE — backend/geometry/*.py                          │
│  step_loader → draft_analyzer → undercut_detector                  │
│              → direction_optimizer → parting_line → core_cavity    │
│  Pure Python + calls into pythonOCC. This is "the brain" today.    │
└──────────────────────────────┬──────────────────────────────────────┘
                                │  pythonOCC function calls (Python → C++ bridge)
                                ▼
┌───────────────────────────────────────────────────────────────────┐
│  pythonOCC — Python bindings/wrapper around OpenCASCADE            │
│  Translates Python calls into the C++ OpenCASCADE library calls.   │
└──────────────────────────────┬──────────────────────────────────────┘
                                │  in-process C++ function calls
                                ▼
┌───────────────────────────────────────────────────────────────────┐
│  OpenCASCADE (OCC) — the CAD kernel, written in C++                │
│  Actually parses the STEP file text and does all real geometry     │
│  math: normals, areas, Boolean operations, meshing for display.    │
└──────────────────────────────┬──────────────────────────────────────┘
                                │  reads bytes from disk
                                ▼
┌───────────────────────────────────────────────────────────────────┐
│  Part1.stp — a plain text file on disk in data/parts/              │
│  ISO 10303 STEP format. Exact mathematical surface descriptions.   │
└───────────────────────────────────────────────────────────────────┘
```

## 3.2 Why the architecture is split this way (the actual engineering reasons)

**Frontend and backend are two separate processes (and two separate Docker containers) instead of one combined app.** Reasons:
1. **Different dependency weight.** The backend needs the entire pythonOCC/CAD stack — a multi-gigabyte, hard-to-install dependency chain. The frontend only needs a web UI library and an HTTP client. Keeping them separate means the frontend's Docker image builds in seconds and stays small; only the backend needs the heavy CAD toolchain.
2. **Independent scaling and iteration.** A frontend developer can restart/edit `frontend/app.py` without ever touching or rebuilding the heavy backend image, and vice versa.
3. **A stable contract.** They only ever talk through plain HTTP + JSON. This means, in principle, you could swap the whole Streamlit frontend for a React app later, or swap FastAPI for another backend framework, without touching the other side, as long as the JSON contract stays the same.
4. **Mirrors how Bosch would want to integrate this.** A real company would want the analysis "engine" (the backend/geometry API) available as a standalone service that other internal tools could call — not welded permanently to one specific UI.

**Why the geometry engine is a chain of small modules instead of one giant function.** Each module (`step_loader`, `draft_analyzer`, `undercut_detector`, `direction_optimizer`, `parting_line`, `core_cavity`) does exactly one job and can be tested, understood, and swapped independently. `draft_analyzer.py` has zero knowledge of Boolean operations; `parting_line.py` has zero knowledge of OCC's C++ classes at all — it just walks abstract Python graphs. This means you can unit-test 90% of the logic without ever touching the slow, heavy OCC layer, which is exactly what the `pytest.mark.unit` vs `pytest.mark.integration` split in the test suite is designed to exploit.

**Why there's a single shared object (`PartGeometry`) instead of passing dozens of separate arguments between functions.** Every module reads from and writes new fields onto the *same* `PartGeometry` object as the pipeline runs. It's a progressive accumulator — load_step creates it with faces/edges/topology, draft_analyzer adds a draft angle to every face, undercut_detector adds an undercut flag to every face, direction_optimizer adds the best pull direction, and so on. This avoids "argument explosion" (imagine `parting_line()` needing 15 separate parameters) and gives every module a single, well-documented object to both read prior results from and write its own results into.

**Why triangulation (turning exact curved surfaces into flat triangles) only happens in one place (`visualize_raw.py`), never inside the analysis code.** All of the actual DfM math — draft angles, undercuts, parting lines — is computed on the *exact* mathematical surfaces, because approximating with triangles first would introduce small errors that compound into wrong answers (explained fully in 4.20, STEP vs. mesh). Triangulation is created *only* as a final, separate step whose only purpose is "give the 3D viewer something it knows how to draw on a screen." The critical trick that makes this safe: every triangle remembers which original exact face it came from (a `face_id` tag on every triangle), so the color you see in the browser (green/yellow/red draft, red undercut, etc.) is always traceable back to the exact analysis result for that exact face — the mesh is just a "skin," never a source of truth.

## 3.3 A single request traced end to end (in extreme detail)

Say the user clicks "Run Draft Analysis" for `Part1.stp` in the browser.

1. **Browser → Streamlit server.** Your browser is just displaying a webpage that Streamlit's built-in web server is generating and serving on port `8501`. Clicking the button causes Streamlit's Python code (running on your machine or inside a Docker container) to re-run the relevant part of `frontend/app.py`.
2. **Streamlit → FastAPI, over HTTP.** Inside `frontend/app.py`, a function calls Python's `requests` library, which sends a plain `GET` request to `http://localhost:8000/parts/Part1.stp/draft?dx=0&dy=0&dz=1&include_mesh=true` (or `http://backend:8000/...` inside Docker — see 4.6 for why the hostname changes). This is a real network request, even if both processes happen to be running on the same laptop — HTTP doesn't care whether "the network" is your own loopback interface or the real internet.
3. **FastAPI receives it.** `uvicorn` (explained in Part 4) is the actual program listening on port 8000 for incoming HTTP connections. It hands the request to the FastAPI Python app object defined in `backend/api/main.py`, which has a Python function registered as the handler for exactly that URL pattern.
4. **The handler calls the geometry engine — plain Python, no network involved anymore.** It calls `load_step("data/parts/Part1.stp")`, which triggers pythonOCC to read the file off disk and build an in-memory C++ representation of the geometry, wrapped and returned to Python as a `PartGeometry` object. It then calls `analyze_draft(part, pull_direction)`, which is pure Python math (dot products, `arcsin`) run once per face.
5. **Result objects get converted to JSON.** Every result class in this codebase has a `.to_dict()` method whose entire job is: "take this Python object (which might be holding a live C++ OCC handle internally) and produce a plain dictionary of numbers/strings/lists that has zero C++ references in it," because only plain data can be sent as JSON text over HTTP.
6. **FastAPI sends the JSON back over HTTP** to the waiting `requests.get(...)` call inside the Streamlit process.
7. **Streamlit parses the JSON and redraws the page** — coloring the 3D mesh viewer according to each triangle's `face_id` → draft classification, updating tables, updating the sidebar status.
8. **Your browser receives the updated HTML/JS from Streamlit's web server** and repaints the screen.

Notice: at no point does the browser talk directly to pythonOCC or to the backend. The browser only ever talks to Streamlit's web server; Streamlit's Python code is the only thing that talks to FastAPI; FastAPI's Python code is the only thing that talks to pythonOCC/OpenCASCADE. Each arrow in the diagram in 3.1 is a real, enforced boundary.

---

# PART 4 — EVERY TECHNOLOGY, EXPLAINED FROM ZERO, WITH ALTERNATIVES

For each item: what it is, why it exists at all (the general problem it solves), why *this* project specifically needed it, and what else could have been used instead with the tradeoffs.

## 4.1 Python

**What it is:** a general-purpose programming language, known for readable syntax and a gigantic ecosystem of pre-built libraries (which is exactly why it dominates scientific/engineering computing).

**Why this project needed it specifically:** pythonOCC (the CAD engine wrapper, 4.10) only has official, well-supported bindings for Python. NumPy, SciPy, PyVista, FastAPI, Streamlit — essentially the entire scientific/AI Python ecosystem — plugs together almost for free once you're in Python. There was never really a competing choice here for this kind of project.

**Alternatives and why not:** C++ (what OpenCASCADE itself is written in) — much faster, but far slower to write correct code in, no interactive prototyping, and you'd lose the entire Python data-science/web ecosystem. JavaScript/Node — has some CAD kernels (e.g., OpenCascade.js, a WebAssembly compile of OCC) but the Python CAD ecosystem (pythonOCC, CadQuery) is dramatically more mature for this kind of B-Rep analysis work.

## 4.2 REST APIs (and HTTP)

**What a REST API is, from zero:** "API" (Application Programming Interface) just means "a defined way for one piece of software to ask another piece of software to do something." "REST" is a very common *style* of API where you talk over the same protocol web browsers use (HTTP), and each "thing" you can ask about has its own URL, like `/parts/Part1.stp/draft`. You "ask" using verbs like `GET` (give me data) or `POST` (create/do something), and you get back structured data, in this project's case JSON (JavaScript Object Notation — plain text that looks like nested Python dictionaries/lists, e.g. `{"good_face_ids": [1,2,3]}`).

**Why this project needs an API at all instead of the frontend just importing the geometry code directly:** because the frontend and backend are two separate processes (see 3.2) — possibly on two separate machines, and definitely in two separate Docker containers. An API over HTTP is the standard, language-agnostic way for separate processes to talk to each other reliably.

**Alternatives:** gRPC (a faster, binary alternative to JSON-over-HTTP, common in high-performance microservices, but heavier to set up and less human-debuggable — you can't just `curl` it easily), GraphQL (lets the client ask for exactly the fields it wants in one request, but adds real complexity that this project's fairly small, fixed set of endpoints doesn't need). Plain REST/JSON was chosen because it's simple, debuggable with a browser or `curl`, and every language can consume it.

## 4.3 FastAPI

**What it is:** a Python library/framework specifically for building REST APIs quickly. You write normal Python functions, decorate them (`@app.get("/parts")`), and FastAPI automatically: turns HTTP requests into Python function calls, validates and converts incoming query parameters to the right Python types, converts your Python return values to JSON, and — for free — generates an interactive web page (`/docs`, Swagger UI) where anyone can browse and test every endpoint live in a browser.

**Why this project chose it:** it's async-friendly (can handle multiple requests efficiently), has excellent automatic input validation (catches a malformed request before your business logic even runs), and the free auto-generated `/docs` page is genuinely useful during a hackathon demo — you can point a judge at `http://localhost:8000/docs` and let them try the API themselves.

**Alternatives:** Flask (older, simpler, extremely popular, but you must add extra libraries yourself for input validation and auto-docs — FastAPI essentially bundles "Flask + validation + docs" together out of the box), Django (a much bigger, more opinionated full-website framework with a built-in database ORM and admin panel — massive overkill for a project with no database and no user accounts).

## 4.4 uvicorn

**What it is:** an **ASGI server** — the actual running program that listens on a network port (e.g., 8000), accepts raw incoming TCP connections, parses the raw bytes into an HTTP request, and only then hands it to your FastAPI application code to decide what to do.

**Why you need it at all, separate from FastAPI:** FastAPI is just a Python library of *functions and decorators* — it has no idea how to open a network socket, listen for connections, or speak the raw HTTP protocol. FastAPI describes *what* should happen for a given request; uvicorn is *the actual program* doing the low-level networking that makes those requests arrive in the first place. This is exactly the same relationship as "a recipe" (FastAPI code) vs. "a working kitchen" (uvicorn) — you need both.

**Command from the README:** `uvicorn backend.api.main:app --host 0.0.0.0 --port 8000` — "look inside the Python module `backend.api.main`, find the variable named `app` (which is the FastAPI application object), and serve it on all network interfaces (`0.0.0.0` means "accept connections from anywhere," not just from this same machine) on port 8000."

**Alternatives:** Gunicorn (an older, still very popular server, but historically for the older WSGI standard rather than the newer async ASGI standard — often used together with uvicorn "worker" processes in big production deployments), Hypercorn (another ASGI server, less commonly used).

## 4.5 Streamlit

**What it is:** a Python library for building interactive web apps *without writing any HTML, CSS, or JavaScript*. You write a normal, top-to-bottom Python script; every time a user interacts with a widget (a button, a dropdown), Streamlit quietly re-runs your whole script from top to bottom and redraws the page with the new state.

**Why this project chose it over building a "real" website:** for a hackathon (and honestly for most internal engineering tools), writing a data-heavy interactive tool as a pure Python script is dramatically faster than hiring a frontend engineer to write React/HTML/CSS/JS. Streamlit specifically has first-class support for embedding 3D viewers (via `stpyvista`, 4.15) and Plotly charts (4.14), which is exactly what this project's 3D visualization needs.

**Alternatives:** React/Vue/plain HTML+JS with a proper design — far more flexible and professional-looking, but requires an entirely separate frontend skillset and much more development time. Gradio (Streamlit's closest competitor, more common in pure ML demo tools, weaker at general dashboards). Dash (Plotly's own dashboard framework — more configurable than Streamlit but noticeably more verbose to write).

## 4.6 Docker and containers

**The core problem Docker solves, explained with zero assumptions:** normally, if you write software that depends on 30 different libraries at very specific versions, and you send your code to a teammate, "it works on my machine but not theirs" happens constantly — different OS, different pre-installed library versions, missing system tools. A **container** solves this by packaging your code *together with* a complete, private mini-filesystem containing the exact operating system libraries, the exact Python version, and the exact dependency versions it needs — and then running that whole bundle in an isolated sandbox on the host machine. Every teammate (and every Bosch judge's laptop) runs the *exact identical bytes*, so it either works everywhere or fails everywhere — no more "well it works for me."

**Image vs. container — the one distinction people always confuse:** an **image** is the frozen, saved, read-only blueprint/template — like a `.zip` file of an entire pre-configured mini-computer. A **container** is a *running instance* of that image — like actually double-clicking that zip's contents and running it as a live program. You can start (and stop, and delete) many separate running containers from the exact same single image, the same way you can run several separate instances/windows of the same installed application.

**What a `Dockerfile` is:** a plain text recipe, read top to bottom, describing exactly how to build one image — "start from this base image, run this install command, copy these files in, set this as the default command to run when a container starts." Looking at `Dockerfile.backend` in this project: it starts from a pre-built `miniconda3` base image (already has conda installed), installs some Linux system libraries OpenCASCADE needs (`libgl1`, etc.), creates the whole conda environment from `environment.yml` (pulling in pythonOCC, VTK, CadQuery), copies the project's code in, installs the remaining pip packages from `requirements.txt`, and finally sets the default startup command. `Dockerfile.frontend` is a separate, much lighter recipe with no CAD dependencies at all — proof, in the actual file, of the frontend/backend dependency-weight split discussed in 3.2.

**Why this project's Dockerfile is "multi-stage" (has a `FROM ... AS builder` and then a second `FROM ...` later):** the *builder* stage does all the heavy, messy work of installing conda packages (which leaves behind lots of temporary cache files and build tools you don't want in your final shipped image). The final stage starts from a clean base image again and only *copies* the finished, already-built conda environment and app code across — leaving all that build junk behind. This keeps the final image smaller and cleaner without changing what actually runs.

**Alternatives to Docker:** plain virtual machines (much heavier — a full separate operating system per app, not just a lightweight sandboxed process), Podman (a nearly drop-in-compatible alternative container engine, popular where Docker's licensing/daemon model is a concern), or simply "everyone installs everything manually and hopes for the best" (what this project explicitly does *not* want to rely on, hence README's heavy emphasis on Docker as the recommended path).

## 4.7 Docker Compose

**The problem it solves:** this project needs *two* containers running together (backend + frontend) that can find and talk to each other, share some folders from your actual laptop (so `.stp` files you drop on disk are visible inside the container), and start/stop together as one unit. Doing this by hand would mean typing several long `docker run ...` commands with matching network/volume flags every single time.

**What Docker Compose actually is:** a tool that reads one YAML file (`docker-compose.yml`, YAML explained in 4.19) describing *all* the containers ("services") your app needs, how they're networked together, what folders on your laptop should be mirrored ("mounted") inside each container, and what environment variables each needs — then a single command (`docker compose up`) builds and starts every one of them together, wired up correctly.

**How the backend/frontend actually find each other inside Docker, concretely, from this project's real file:** inside `docker-compose.yml`, the frontend container is given the environment variable `DFM_BACKEND_URL=http://backend:8000` — note it says `backend`, not `localhost`. Docker Compose automatically creates an internal private network where each service can be reached by its *service name* as if it were a hostname (like a private DNS). This is exactly why the README tells you, when running things manually outside Docker (locally), to instead use `http://localhost:8000` — because outside Docker's private network, there is no `backend` hostname; you're just talking to a normal process on your own machine's `localhost` loopback address.

**Difference between Docker and Docker Compose, stated plainly:** Docker is the underlying engine that can build and run one container. Docker Compose is the orchestration layer on top that describes and manages *multiple* containers together as one coordinated system, using one config file instead of many manual commands. You use plain Docker when you have one simple container; you use Compose the moment you have more than one container that need to be started together and talk to each other (exactly this project's situation).

**Alternatives:** Kubernetes ("k8s") — the industry-standard tool for orchestrating containers *at massive scale across many machines*, with vastly more features (auto-healing, auto-scaling, rolling updates) — total overkill for a two-service hackathon demo running on one laptop, but it's exactly what a company like Bosch would eventually use if this became a real production service used by many mold engineers simultaneously.

## 4.8 Conda and environments in general

**The problem "environments" solve, from zero:** if you install a Python library directly onto your computer's single global Python installation, and two different projects need two different, incompatible versions of the same library, you get conflicts — installing one breaks the other. A **virtual environment** solves this by giving each project its own private, isolated folder of installed packages, so different projects can each have exactly the package versions they need without interfering with each other or with your system Python.

**Why `python -m venv` (what you already know) is *not* sufficient for this specific project — the actual technical reason, not just "because the README says so":** `venv` only manages *pure Python* packages downloaded from PyPI via `pip`. But `pythonocc-core` (the pythonOCC package, 4.10) is not a pure Python package — it is a thin Python wrapper around a **huge pre-compiled C++ library** (OpenCASCADE itself, plus VTK for 3D graphics). Building that C++ code correctly requires an exactly matching set of C++ compiler toolchains, low-level graphics/X11 libraries, and dozens of other native (non-Python) system dependencies, correctly matched to your specific operating system and CPU architecture (e.g., Apple Silicon `arm64` vs Intel `x86_64`). `pip` (and therefore `venv`, which only manages what `pip` installs) has no mechanism at all for managing or matching these *non-Python, native, compiled* dependencies — it can only fetch and unpack Python-level packages. Attempting `pip install pythonocc-core` frequently just fails outright with cryptic native compiler errors, especially on macOS.

**What Conda actually is, and why it fixes exactly this gap:** Conda is a package manager (a tool that finds, downloads, and installs software) that is explicitly designed to also manage *non-Python, compiled, native* dependencies — not just Python packages. The **conda-forge** community channel maintains pre-built, tested binary packages of `pythonocc-core` for every major OS/CPU combination, so instead of your machine trying (and often failing) to compile OpenCASCADE's C++ code from scratch, Conda just downloads an already-compiled binary that's known to work.

**Why the environment is specifically named `dfm_agent`:** that's just the name chosen in `environment.yml`'s first line (`name: dfm_agent`) — an arbitrary label so you and your teammates can refer to "the project's environment" by a memorable, consistent name (`conda activate dfm_agent`) instead of a path.

## 4.9 Micromamba

**What it is:** a tiny, single self-contained executable file (no separate installer, no system-wide changes) that implements the *same* Conda environment format and can read the exact same `environment.yml` files — but it is dramatically faster at resolving and installing packages, and installs in seconds instead of requiring you to install the full (much heavier) Miniconda/Anaconda distribution first.

**Why this project offers Micromamba as "Option A, recommended" instead of requiring full Conda:** it needs zero system-wide installation — the README literally has you download one binary file straight into a `.micromamba/` folder *inside the project repo itself* (see the `curl | tar -xj -C .micromamba` command). This means it never touches or conflicts with anything else already on your laptop, is trivially removable (`rm -rf .micromamba`), and is faster to set up for a hackathon where several teammates need to get running on totally different laptops quickly.

**What each confusing-looking part of the setup command actually does, spelled out completely:**
```bash
export MAMBA_ROOT_PREFIX="$PWD/.micromamba/root"
```
`export` sets an **environment variable** — a named piece of configuration that any program you launch afterward, from this same terminal, can read. `MAMBA_ROOT_PREFIX` tells micromamba "store all environments you create inside this specific folder" (rather than some default system location) — this is the mechanism that keeps everything self-contained inside the project folder. `$PWD` is a shell shortcut meaning "the current directory's full path" (Print Working Directory).
```bash
./.micromamba/bin/micromamba create -y -f environment.yml -n dfm_agent -r "$MAMBA_ROOT_PREFIX"
```
Run the micromamba program you just downloaded; `-y` means "don't ask for confirmation, just proceed"; `-f environment.yml` means "read the list of required packages from this file"; `-n dfm_agent` means "name the new environment `dfm_agent`"; `-r "$MAMBA_ROOT_PREFIX"` means "store it at this root location."
```bash
export PYTHONPATH="$PWD"
```
Tells Python's import system "also look for importable modules starting from this folder" — this is *why* `import backend.geometry.step_loader` works from anywhere: Python needs to know the repo root is a valid place to start looking for the `backend` package.
```bash
./.micromamba/bin/micromamba run -r "$MAMBA_ROOT_PREFIX" -n dfm_agent python -c "..."
```
`micromamba run` means "temporarily activate environment `dfm_agent` just for the duration of this one command, then run the given command inside it" — functionally the same end result as `conda activate dfm_agent` followed by running the command directly, just packaged as one call instead of two steps.

## 4.10 pythonOCC (`pythonocc-core`)

**What it is:** the official Python binding (wrapper) for the OpenCASCADE C++ library. "Binding" here means: a thin translation layer that lets Python code call functions that are actually implemented in C++, by automatically converting Python-style calls into the equivalent C++ calls and converting the C++ results back into Python objects.

**Why this project needs it (not "a nice-to-have," a hard requirement):** it is essentially the only mature, open-source way to read a `.stp` file's *exact* geometry into Python and query things like "what is this surface's exact normal vector at this point," "what is this face's exact area," or "compute the exact intersection volume of these two solids." Nothing in the pure-Python data-science ecosystem (NumPy, SciPy) can parse ISO 10303 STEP geometry or do exact B-Rep Boolean operations — that's specialized CAD-kernel territory.

**Why it must be installed from conda-forge, not pip, in one sentence recap of 4.8:** `pythonocc-core` wraps a huge pre-compiled C++ library (OpenCASCADE), and conda-forge is the channel that reliably provides that pre-built binary for your specific OS/CPU, whereas pip has no good mechanism to build or fetch it.

**Alternatives:** FreeCAD's Python API (FreeCAD is itself built on top of OpenCASCADE, so under the hood you'd be relying on the same kernel through a different, heavier application wrapper), Open Cascade's raw C++ API directly (far more control, but you'd lose all of Python's ergonomics and the entire rest of this project's stack), commercial kernels like ACIS or Parasolid (used inside SolidWorks/CATIA/NX themselves — extremely capable, but proprietary, expensive, and licensed — completely unsuitable for an open hackathon submission Bosch can freely inspect, fork, and run).

## 4.11 OpenCASCADE (OCC)

**What it is:** an open-source **CAD kernel** — the foundational, low-level C++ library that actually implements exact-geometry mathematics: parsing STEP/IGES files, representing curved surfaces (planes, cylinders, NURBS — see 4.21), computing exact areas/normals/volumes, performing Boolean operations (union/intersection/subtraction of solids), and triangulating exact surfaces into meshes for display.

**Analogy:** if NumPy is "the foundational math library that everything in Python's scientific stack quietly builds on top of for arrays and linear algebra," OCC is the exact same kind of foundational layer, just specifically for exact 3D CAD geometry instead of arrays. FreeCAD (a full open-source CAD *application*, comparable in spirit to a free SolidWorks) is built directly on top of OCC. Salome (a major open-source simulation platform) is also built on OCC. It is genuinely production-grade, battle-tested software used across aerospace and industrial CAD tooling, not a toy library.

**Why OCC specifically, and not building our own geometry math:** exact B-Rep geometry (especially NURBS surface math and robust Boolean operations) is an enormously deep, decades-of-research field — implementing even a basic, correct version from scratch would be an entire multi-year research project by itself, completely out of scope for any hackathon. Using a mature, free, open-source kernel is the only realistic option, and OCC is the dominant one in the open-source world.

## 4.12 CadQuery

**What it is:** a higher-level Python scripting library, itself built on top of pythonOCC/OCC, that provides a friendlier, more "Pythonic" API for building and inspecting CAD models — closer in spirit to programmatically *scripting* a part the way you might script a 3D model in code, rather than clicking through a GUI.

**Why this project has it as an optional companion to raw pythonOCC:** the codebase primarily uses raw pythonOCC directly for the core analysis (`step_loader.py` etc.), because it needs precise, low-level control of exact topology traversal (explicit `TopExp_Explorer` iteration, exact `BRepAdaptor_Surface` queries). CadQuery is kept around as an optional convenience wrapper (`PartGeometry.cadquery_shape`) for any future higher-level scripting or export tasks, and the loader is written to gracefully continue even if CadQuery is missing — it is not a hard requirement the way raw pythonOCC is.

## 4.13 VTK

**What it is:** "Visualization Toolkit" — a mature, open-source C++ library (with Python bindings) purpose-built for rendering and interacting with 3D scientific/engineering data: meshes, point clouds, volumetric data, scalar-colored surfaces.

**Why this project needs it:** once OCC has triangulated the exact B-Rep geometry into a mesh (in `visualize_raw.py`), *something* has to actually draw that mesh on screen with rotation, zoom, and per-triangle coloring (for the draft/undercut overlays) — that "something" is VTK. PyVista (4.15) is the friendly Python layer on top of raw VTK that this project actually calls directly.

## 4.14 Plotly

**What it is:** a Python (and JavaScript) charting/graphing library capable of both standard 2D charts (bar, line) *and* interactive 3D mesh rendering directly inside a normal web page, using pure JavaScript/WebGL under the hood rather than a native desktop rendering window.

**Why this project specifically uses Plotly on macOS (per the README's platform table):** PyVista/VTK's typical rendering path in Streamlit (via `stpyvista`) relies on some Linux-specific windowing infrastructure (explained in 4.16, Xvfb) that is prone to crashing specifically on macOS due to threading conflicts with macOS's native Cocoa windowing system. Plotly avoids that entire problem because it renders through the browser's own JavaScript/WebGL engine instead of trying to open a native graphics window on the host OS — so the project's frontend code detects "am I on macOS?" and switches to Plotly there, while using PyVista+VTK on Linux/Docker where that crash risk doesn't apply.

## 4.15 PyVista (and stpyvista)

**What it is:** a friendly, "Pythonic" wrapper around raw VTK (4.13) — instead of VTK's fairly verbose, C++-flavored API, PyVista lets you build and color a 3D mesh viewer in a few clean lines of Python. `stpyvista` is a small bridge library specifically written to let a PyVista 3D viewer be embedded inside a Streamlit page (since Streamlit and a native VTK render window don't normally know how to talk to each other).

**Why this project uses it (on Linux/Docker):** it's the standard, well-supported way to get an interactive, rotatable 3D mesh view with custom per-face coloring inside a Python web app, without writing any raw WebGL/JavaScript by hand.

## 4.16 Xvfb (mentioned in the Docker Compose command, worth knowing)

**What it is:** "X Virtual FrameBuffer" — a program that pretends to be a real graphics display (a monitor) on a Linux machine that has no actual physical monitor attached, which is exactly the situation inside a headless Docker container. Many 3D rendering libraries (like VTK) expect *some* display to exist to render into, even if nothing is ever actually shown on a physical screen — Xvfb satisfies that expectation invisibly.

**Why the frontend Docker command wraps Streamlit with `xvfb-run -a streamlit run ...`:** it's saying "first start a fake virtual display, then run Streamlit inside that fake display's context," so that PyVista/VTK's rendering calls succeed inside the Docker container instead of crashing with "no display found."

## 4.17 NumPy and SciPy

**What they are:** NumPy is the foundational Python library for fast numerical arrays and linear algebra (vectors, matrices, dot products at speed). SciPy builds on NumPy with more advanced scientific algorithms (optimization, spatial data structures, statistics).

**Why this project needs them:** even though a huge amount of the vector math here (`dot3`, `normalize3`, `cross3` in `geometry_models.py`) is written as simple hand-rolled Python tuple math rather than NumPy arrays (a deliberate choice — see below), NumPy/SciPy are still present as dependencies for supporting numerical work throughout the visualization and geometry-adjacent code, and they're the universal baseline expected by nearly every other library in this stack (PyVista, SciPy itself, etc.).

**Why the core vector math uses plain Python tuples instead of NumPy arrays:** for single 3D vectors (just 3 numbers), NumPy's overhead (creating an array object, etc.) is actually *slower* than plain Python math for such a tiny fixed size, and using plain tuples keeps `geometry_models.py` completely dependency-free (it can be imported and unit-tested with zero external libraries at all, not even NumPy) — reinforcing the "foundation layer has zero dependencies" architecture decision from Part 3.

## 4.18 NetworkX

**What it is:** a pure-Python library for building and analyzing **graphs** — here "graph" means the mathematical structure of nodes connected by edges (e.g., a road map, a social network, or — in this project — faces connected to their neighboring faces), *not* a bar chart. It has built-in algorithms for things like "find the shortest path between two nodes" or "find connected groups of nodes."

**Why this project needs it:** the parting-line module's Hou-2018-inspired refinement step (Part 8.5) needs to find a good "closed loop" path through a weighted graph of candidate parting-line edges — exactly the kind of shortest-path/graph-search problem NetworkX is built for, instead of reinventing graph algorithms by hand.

## 4.19 YAML and `config.yaml`

**What YAML is:** a human-friendly plain-text format for storing structured, nested settings (numbers, strings, lists, nested groups), designed to be much easier for a human to read and hand-edit than JSON (no need for the constant commas/brackets/quotes JSON requires) — it uses indentation to show nesting, similar in spirit to how Python itself uses indentation.

**Why this project centralizes every threshold in `config.yaml` instead of hardcoding numbers inside the Python files:** every DfM (Design for Manufacturability) rule this tool enforces — "1.5° is good draft," "15° is the direction search step size" — is fundamentally a *business/engineering policy decision*, not a fixed law of physics. A real user (a Bosch engineer) might want stricter or looser thresholds for a different plastic material, or a finer/coarser direction search for a more complex part. Putting every tunable number in one plain-text file means anyone can adjust the tool's behavior *without touching or even understanding a single line of Python code* — a direct, deliberate response to the hackathon PDF's explicit requirement that "code should be easy to update for future revisions."

## 4.20 Dataclasses

**What a Python "dataclass" is:** a built-in Python feature (`@dataclass` decorator) that auto-generates the repetitive boilerplate code for a simple class whose main job is just to hold a bundle of named fields — you'd otherwise have to hand-write an `__init__` method, a printable representation, and comparison logic yourself.

**Why this project uses dataclasses (not plain dictionaries, not Pydantic) for the core geometry objects (`PartGeometry`, `FaceData`, `EdgeData`, etc.):** these objects need to hold *live C++ OpenCASCADE handles* (`occ_face`, `occ_shape`) as fields — raw references into OCC's own compiled memory. Pydantic (4.21) performs active data *validation* on every field, which requires understanding and validating the field's type — but there is no way (and no need) for Pydantic to "validate" an opaque C++ object handle; trying to run OCC objects through Pydantic's validation layer would be both meaningless and fragile. Dataclasses simply hold whatever you put in them, with no validation overhead, which is exactly right for this internal, trusted, code-generated data.

## 4.21 Pydantic

**What it is:** a Python library for defining data models that *automatically validate* incoming data against declared types (e.g., "this field must be a `float` between 0 and 1") and raise a clear error immediately if the data doesn't match, rather than letting a bad value silently cause a confusing crash somewhere deep in your code later.

**Why this project uses it specifically at the FastAPI boundary, not inside the geometry engine:** FastAPI uses Pydantic internally to validate incoming HTTP query parameters (e.g., `threshold: float = Query(default=0.05, ge=0.0, le=1.0)` on the core-cavity endpoint literally means "this must be a float, default 0.05, must be ≥ 0.0 and ≤ 1.0" — and FastAPI/Pydantic enforces that automatically before your function body even runs). This is precisely the "public boundary talking to untrusted external input (a web request)" scenario Pydantic is built for — as opposed to the internal geometry engine's objects, which never come from untrusted external input and instead need to hold non-validatable C++ handles (4.20).

## 4.22 pytest

**What it is:** the dominant Python testing framework — you write functions starting with `test_`, each one calls some code and asserts the result is what you expect; running `pytest` discovers and runs every such function across your project and reports pass/fail with a clear summary.

**Why this project needs automated tests at all, beyond "it's good practice":** the geometry engine has genuinely subtle math (draft-angle formulas, silhouette-edge sign logic, Boolean pruning heuristics) where a small sign error or off-by-one in a threshold could silently produce *plausible-looking but wrong* engineering recommendations — exactly the kind of bug that would be embarrassing to discover live in front of a Bosch judge instead of caught automatically beforehand.

**The `unit` vs. `integration` vs. `slow` markers, explained:** a **unit test** tests one small piece of pure logic in isolation (e.g., "does `_classify_draft(1.6, 1.5, 0.5)` return `'good'`?") — these need no STEP files and no OCC installed, so they run in milliseconds and can even run without the conda environment. An **integration test** exercises the *real* pipeline against a *real* STEP file with the *real* pythonOCC installed (e.g., "does loading `Part1.stp` actually produce 47 faces?") — slower, and only runnable once the conda/Docker environment is set up. A **slow** test is one that's correct but takes a while to run (e.g., anything invoking expensive Boolean operations) — kept separately markable so you can skip them for a quick sanity check.

## 4.23 STEP files and B-Rep (Boundary Representation)

**What "STEP" stands for and why it exists:** "Standard for the Exchange of Product model data" — an ISO standard (ISO 10303) whose entire purpose is to be a vendor-neutral file format so that a part designed in one company's CAD software (say CATIA) can be opened, with zero loss of exact geometric accuracy, inside a *completely different* company's CAD software (say SolidWorks or our own pythonOCC-based tool). Before standards like STEP existed, every CAD vendor had a proprietary, closed file format, and exchanging exact designs between companies using different software was extremely painful.

**What "B-Rep" (Boundary Representation) means, from zero:** rather than storing a solid 3D shape as, say, a giant 3D grid of filled/empty voxels, B-Rep stores a solid by exactly describing all of the *surfaces that bound it* — its outer "skin," described with exact mathematical equations, not approximations. A STEP file is one common, standardized way to *write down* a B-Rep model as a text file on disk.

**Concrete example that makes this click:** a cylindrical hole of radius 5mm is stored in a STEP file, roughly, as text meaning "this is a cylindrical surface, centered at this exact point, pointing in this exact direction, with this exact radius, from this exact height to that exact height." That's it — an exact, tiny amount of information describing infinitely precise geometry. Compare that to how a `.stl` file (used for 3D printing) would store the same hole: as roughly 200 flat little triangles arranged in a rough circle, only *approximating* a true circle — meaning the "hole" in an `.stl` file is never actually perfectly round, just close enough for a 3D printer's resolution.

**Why this distinction is the single most important technical fact in the whole project (STEP vs. STL/mesh):**

| | STEP (`.stp`) | STL (`.stl`) / any triangle mesh |
|---|---|---|
| Stores | Exact mathematical surfaces (planes, cylinders, NURBS) | Approximated flat triangles |
| A cylinder is | One exact equation | Hundreds of flat triangle facets |
| Accuracy | Machine-precision exact | Approximate, bounded by mesh resolution |
| Normals | Computed exactly from the true surface equation at any point | Only approximate, derived from triangle vertices |
| Typical accuracy loss | None | Can be 0.1mm–1mm+ depending on mesh density |
| Fine for | Mold design, machining, exact tolerancing | 3D printing, games, general visualization |

A mold is machined to tolerances around ±0.01mm. If our tool worked off a triangle-mesh approximation instead of exact STEP surfaces, our draft-angle and parting-line calculations could easily be off by an amount 10–100× larger than the actual manufacturing tolerance — silently producing wrong, misleading recommendations. This single fact — "we work on exact B-Rep, not approximated meshes" — is the correct one-sentence answer to almost any judge question of the form "why STEP and not just any 3D file?"

## 4.24 NURBS

**What it stands for and means:** Non-Uniform Rational B-Splines — the standard mathematical way industrial CAD software represents smooth, freeform curved surfaces (think of the sculpted curve of a car's dashboard or hood) that are too complex to describe as a simple plane, cylinder, or cone.

**Intuition, no equations needed:** imagine you have a grid of "control points" floating in 3D space, each pulling the surface toward it with some adjustable "weight" (how strongly it pulls) — a NURBS surface is the smooth, continuous surface that results from blending all those pulls together, and by moving the control points or adjusting weights, a designer can sculpt essentially any smooth freeform shape.

**Why this matters for the code specifically:** a STEP file's faces can be *any* mix of simple surface types (plane, cylinder, cone, sphere, torus) *and* fully freeform NURBS surfaces, all in the same file. The code never needs to know or care which specific type a given face is when computing something generic like "give me the normal vector here," because it always asks through OCC's `BRepAdaptor_Surface`/`GeomLProp_SLProps` abstraction (explained fully in Part 8.1), which uniformly handles every surface type, NURBS included, behind one consistent API. `FaceData.surface_type` (e.g., `"Plane"`, `"Cylinder"`, `"BSpline/NURBS"`) is stored purely as descriptive metadata for reporting, never as a branch in the actual math.

---

---

# PART 5 — HOW TO ACTUALLY RUN THE PROJECT, COMMAND BY COMMAND

## 5.1 The two supported paths, and when to use which

There are two ways to run this project: **Docker** (recommended, most reliable, what you should use if you're presenting in the next hour) and **Micromamba/Conda locally** (what a developer uses day to day while writing code, with hot-reload). Given your time constraint, **use Docker.** It sidesteps every "pythonOCC won't install on my machine" problem, because the whole point of a container is that it ships a pre-tested, working environment.

## 5.2 Running with Docker — the fastest path, command by command

```bash
cd Bosch                       # move into the git repo root
cp Part1.stp data/parts/       # only needed if the file isn't already there — check first
docker compose up              # build (if needed) and start both containers
```

**What happens internally, in order, when you run `docker compose up`:**
1. Docker Compose reads `docker-compose.yml` and sees two services defined: `backend` and `frontend`.
2. For `backend`: since no `dfm-agent-backend` image already exists (or if you changed the Dockerfile), Docker builds one by executing `Dockerfile.backend` top to bottom — pulling the `miniconda3` base image, installing system libraries, creating the `dfm_agent` conda environment from `environment.yml`, installing the pip extras from `requirements.txt`, copying your code in.
3. Same for `frontend`, using the separate lightweight `Dockerfile.frontend`.
4. Docker creates a private internal network so the two containers can reach each other by service name (`backend`, `frontend` — see 4.7).
5. Docker starts the `backend` container, running the command specified in `docker-compose.yml`: `uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload`. The `--reload` flag means uvicorn watches the mounted `./backend` folder on your laptop for file changes and automatically restarts itself — useful during development, harmless during a demo.
6. Docker starts the `frontend` container (`depends_on: backend` in the YAML means Compose starts backend first), running `xvfb-run -a streamlit run frontend/app.py --server.port=8501 ...` (see 4.16 for `xvfb-run`).
7. Both containers also have `volumes:` entries mounting real folders from your laptop (`./data`, `./reports`, `./config.yaml`) *into* the container's filesystem — meaning any `.stp` file you drop into your laptop's `data/parts/` folder is instantly visible inside the running container too, with no rebuild needed.
8. Once both are up, port `8000` (backend) and `8501` (frontend) on your actual laptop are "forwarded" into the matching ports inside the containers (`ports: "8000:8000"` in the YAML — format is `host_port:container_port`), which is exactly why `http://localhost:8000` and `http://localhost:8501` work in your normal browser even though the code is technically running inside an isolated container.

```bash
open http://localhost:8501     # the Streamlit UI
open http://localhost:8000/docs  # FastAPI's auto-generated interactive API docs
```

To stop everything cleanly: `Ctrl+C` in the terminal running `docker compose up`, or from another terminal, `docker compose down`.

**Repeatable validation evidence (useful before a demo to prove it works):**
```bash
bash scripts/run_level1_docker_validation.sh 3
```
This runs the pipeline validation and performance-profiling scripts inside Docker three times in a row and saves the JSON results into `reports/level1_validation/` — good, concrete evidence to screenshot for a report or to reference if a judge asks "does this actually work reliably, or did it just work once?"

## 5.3 Running locally with Micromamba — the developer path

```bash
cd Bosch
mkdir -p .micromamba
curl -Ls https://micro.mamba.pm/api/micromamba/osx-arm64/latest | tar -xj -C .micromamba bin/micromamba
```
Downloads the micromamba program itself as one binary file, extracted directly into `.micromamba/bin/` inside the repo (nothing is installed system-wide). Use `linux-64` instead of `osx-arm64` if on Linux; check your CPU architecture if unsure (`osx-arm64` = Apple Silicon Mac, `osx-64` = Intel Mac).

```bash
export MAMBA_ROOT_PREFIX="$PWD/.micromamba/root"
./.micromamba/bin/micromamba create -y -f environment.yml -n dfm_agent -r "$MAMBA_ROOT_PREFIX"
```
Creates the actual `dfm_agent` environment, reading the exact package list from `environment.yml`, and installs pythonOCC, CadQuery, VTK, NumPy/SciPy via conda-forge, plus Streamlit/FastAPI/PyVista/etc. via pip inside that environment. **This step takes 5–15 minutes and 2–5GB of disk** the first time — this is the single slowest step in this entire project's setup, budget for it.

```bash
export PYTHONPATH="$PWD"
./.micromamba/bin/micromamba run -r "$MAMBA_ROOT_PREFIX" -n dfm_agent \
  python -c "from OCC.Core.STEPControl import STEPControl_Reader; print('OCC OK')"
```
A sanity check: activates the environment just for this one command and tries to import the actual OpenCASCADE STEP reader class. If it prints `OCC OK`, pythonOCC is correctly installed and importable. If it errors, the conda environment creation step above did not succeed and needs to be redone.

**Two terminals, running the backend and frontend as two separate live processes on your laptop directly (no Docker):**

Terminal 1:
```bash
cd Bosch
export MAMBA_ROOT_PREFIX="$PWD/.micromamba/root"
export PYTHONPATH="$PWD"
./.micromamba/bin/micromamba run -r "$MAMBA_ROOT_PREFIX" -n dfm_agent \
  uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
```
Terminal 2:
```bash
cd Bosch
export MAMBA_ROOT_PREFIX="$PWD/.micromamba/root"
export PYTHONPATH="$PWD"
./.micromamba/bin/micromamba run -r "$MAMBA_ROOT_PREFIX" -n dfm_agent \
  streamlit run frontend/app.py --server.port 8501
```
Note: outside Docker, the frontend defaults to talking to `http://localhost:8000` (not `http://backend:8000` — see 4.7's explanation of why that hostname only exists inside Docker's private network).

## 5.4 Running with plain Miniconda/Miniforge (Option B) instead of Micromamba

If you (or a teammate) already has full Conda installed system-wide, the equivalent commands are simpler because `conda activate` persists for your whole terminal session instead of needing `micromamba run` on every single command:
```bash
conda env create -f environment.yml
conda activate dfm_agent
export PYTHONPATH="$PWD"
uvicorn backend.api.main:app --reload --port 8000     # terminal 1
streamlit run frontend/app.py                          # terminal 2
```

## 5.5 Every other command mentioned in the README, explained

```bash
pytest tests/ -v
```
Runs the entire automated test suite (pytest, 4.22). `-v` means "verbose" — print every individual test's name and pass/fail status, not just a final summary count.

```bash
python -m backend.validation.part_validation --json
```
`python -m package.module` runs a Python file as a script while still treating it as part of the `backend` package (so its internal `from backend.models... import ...` statements resolve correctly — a subtlety of Python's module system that's different from just running `python backend/validation/part_validation.py` directly). This specific script smoke-tests the whole pipeline against every `.stp` file it finds in `data/parts/`, and `--json` makes it print/save a structured JSON result instead of only human-readable text — useful evidence for a report.

```bash
python -m backend.validation.performance_profile --json
```
Times every single pipeline stage (load, draft, undercuts, direction search, parting line) against configured time budgets (Part 8 has the exact budget table) and reports pass/warn/fail per stage — useful to prove "this actually runs fast enough to be useful," a direct claim a judge might challenge.

```bash
python -m backend.geometry.visualize_raw data/parts/Part1.stp
```
Opens a native desktop PyVista window (a real separate application window, not inside the browser) showing the raw triangulated mesh — a quick local sanity check that STEP loading and meshing work, without needing the full FastAPI+Streamlit stack running.

## 5.6 Troubleshooting table (from the README, explained in plain language)

| Symptom | What's actually happening | Fix |
|---|---|---|
| `ModuleNotFoundError: OCC` | Python is running from your normal system Python, not from inside the `dfm_agent` conda/micromamba environment where pythonOCC actually lives | Re-activate/re-run inside the environment; recreate it from `environment.yml` if it was never created |
| "Backend unavailable" in the UI | The Streamlit frontend process is running, but nothing is listening on port 8000 yet, so its HTTP requests fail | Start the FastAPI/uvicorn backend first, confirm `http://localhost:8000/health` responds |
| Micromamba lock error | Two micromamba processes tried to write to the same internal lock file at once (e.g., ran the setup twice too fast) | Wait a few seconds and retry, or delete the stale lock file mentioned in the error |
| Empty parts list in the UI | `/parts` endpoint scanned `data/parts/` and found zero `.stp`/`.step` files | Add a real STEP file there |
| `PYTHONPATH` errors (`ModuleNotFoundError: backend`) | Python doesn't know the repo root is an importable location | Always `export PYTHONPATH="$PWD"` from inside the `Bosch` folder before running anything |

---

# PART 6 — WALKING THE REPOSITORY AS IF WE JUST OPENED IT IN VS CODE

Imagine you just opened the `Bosch/` folder in VS Code's file explorer, top to bottom, and I'm sitting next to you explaining every single item as your eyes land on it.

```
Bosch/                              ← this whole folder IS the git repo root
```

**Top-level files you'd see first:**

- **`README.md`** — the front door of the project. First thing any new engineer, judge, or you-in-a-hurry should open. Contains the quick-start commands and a summary architecture diagram.
- **`Engine.md`** — the four academic research papers this project's algorithms are modeled on (Bassi 2010, Sangolli 2021, Nee 1998, Hou 2018), each with the paper's exact pseudocode. This is your evidence, if a judge asks "is this just made up, or is it grounded in real research?", that every algorithm has a named, dated academic source.
- **`understand.md`** — your team's own working notes decoding the hackathon problem statement and initial algorithm planning. More of a "how we thought about this" scratchpad than a polished spec.
- **`working.md`** — the most complete, most technically precise onboarding document in the repo (the one this guide draws most heavily from for exact module details). If you only have 10 minutes before presenting and need one more file to skim, skim this one.
- **`config.yaml`** — every tunable number in the whole system (draft thresholds, direction search resolution, Boolean tolerances, parting-line smoothing) in one plain YAML file (4.19). Change a number here, restart the backend, behavior changes — zero code edits needed.
- **`environment.yml`** — the exact conda dependency list (4.8, 4.9).
- **`requirements.txt`** — the pip-only dependency list, plus a comment explicitly warning that `pythonocc-core` must come from conda, not from this file.
- **`docker-compose.yml`, `Dockerfile.backend`, `Dockerfile.frontend`** — the container definitions (4.6, 4.7).
- **`.gitignore`** — tells git which files/folders to never track (e.g., `.micromamba/`, `__pycache__/`) — not code, just repo hygiene.
- **`.micromamba/`** — the actual downloaded micromamba binary and environment, if you set it up locally. Explicitly gitignored — every machine recreates its own copy, it's never committed.

**`backend/`** — everything that runs server-side, no browser code at all here.

- **`backend/config.py`** — the one file that reads `config.yaml` off disk at startup and turns it into typed, importable Python settings objects. Everything else that needs a threshold imports `settings` from here rather than reading the YAML file itself.
- **`backend/models/geometry_models.py`** — the foundation. Defines `PartGeometry`, `FaceData`, `EdgeData`, `VertexData`, `BoundingBox`, and the basic vector math helpers (`dot3`, `normalize3`, `cross3`). This file imports *nothing* from the rest of the backend — everything else imports *from* it. If you only read one Python file before presenting, read this one; you cannot understand any other module without knowing what a `FaceData` object looks like.
- **`backend/geometry/step_loader.py`** — Module 1. The only file in the whole project that directly calls OCC's STEP file reader. Turns a `.stp` file on disk into a fully populated `PartGeometry` object.
- **`backend/geometry/draft_analyzer.py`** — Module 2. Pure math (no OCC Boolean operations): computes `arcsin(|n·d|)` per face, classifies green/yellow/red.
- **`backend/geometry/undercut_detector.py`** — Module 3, and by far the largest file in the codebase (~3,400 lines). Fast heuristic prefilter plus optional expensive OCC Boolean confirmation, feature grouping, and mold-action recommendation.
- **`backend/geometry/direction_optimizer.py`** — Module 4. Generates ~30–54 candidate pull directions, scores them cheaply first, then spends the expensive Boolean checks only on the most promising few, and picks the winner.
- **`backend/geometry/parting_line.py`** — Module 5, the second-largest file (~2,870 lines). Finds silhouette edges, groups them, orders them into a wire, scores/smooths the result.
- **`backend/geometry/core_cavity.py`** — Module 6. **Actually implemented** (contrary to what some of the attached docs say) as a lightweight per-face classification step: labels every face `"cavity"`, `"core"`, or `"parting"` based on the sign of `dot3(normal, pull_direction)`. Does **not** yet perform an actual Boolean split of the solid into two separate 3D bodies — that heavier step is the real remaining Level 2 work.
- **`backend/geometry/visualize_raw.py`** — the display-only adapter. The only file that triangulates exact B-Rep surfaces into triangles, purely for the 3D viewer. Never used for analysis math.
- **`backend/agent/dfm_agent.py`** and **`backend/agent/tools.py`** — **both files are completely empty (0 bytes) right now.** This is the planned LLM "brain" layer from Part 1 — it is 100% not started. Be ready to say this plainly and confidently rather than being caught overstating it (Part 9 has the exact phrasing).
- **`backend/api/main.py`** — the FastAPI app: every `@app.get(...)` endpoint the frontend (or you, via `curl`, or a judge, via `/docs`) can call.
- **`backend/validation/part_validation.py`, `performance_profile.py`** — CLI (command-line) scripts, not pytest tests, that run the whole pipeline end-to-end against real STEP files and report pass/fail evidence and timing.

**`frontend/app.py`** — the entire Streamlit UI (~3,400+ lines) in one file. It imports `requests` (an HTTP client library) and PyVista/Plotly for rendering — it does **not** import anything from `backend.geometry` or pythonOCC at all. That absence of import is itself the proof, readable directly in the file, of the frontend/backend separation described in Part 3.

**`tests/`** — the pytest suite (4.22), one file per geometry module, plus API-error-handling and boolean-region-payload tests. `pytest.ini` configures test markers and coverage reporting.

**`data/parts/`** — where you drop `.stp` files. Currently holds `Part1.stp`. `Part2.stp` (the more complex "Level 2" hackathon input) is not present in this workspace and hasn't been validated yet — an honest gap to know about before Q&A.

**`docs/`** — presentation and status-tracking materials, not source code: `IMPLEMENTATION_STATUS.md` (truth source for what's built), `DEMO_SCRIPT.md` (a live demo walkthrough with exact talking points and "claims to avoid"), `SLIDE_STORYBOARD.md`, `DFM_REPORT_OUTLINE.md`, `EVIDENCE_CHECKLIST.md`.

**`reports/`** — generated output only (JSON validation results, HTML coverage reports) — not something you write by hand, it's produced by running the validation/test scripts.

**`scripts/run_level1_docker_validation.sh`** — the one repeatable evidence-generation script mentioned in 5.2.

---

# PART 7 — THE COMPLETE LIFECYCLE OF A STEP FILE, OBJECT BY OBJECT

Tracing `Part1.stp` from raw bytes on disk to pixels in your browser, stage by stage, always stating exactly what enters, what leaves, and what new information got added.

**Stage 0 — Input.** `data/parts/Part1.stp` sits on disk as plain ASCII text following the ISO 10303 STEP grammar — lines of text describing surfaces, curves, and how they connect, in a standardized but genuinely dense, low-level notation not meant for humans to read directly.

**Stage 1 — `step_loader.load_step()`.**
- *Enters:* a file path string.
- *Internally:* `STEPControl_Reader` parses the text and builds OCC's own in-memory C++ representation (a `TopoDS_Shape`). The bounding box is computed exactly (no meshing). Every face is visited once via `TopExp_Explorer`, and for each one: its surface type is read (`BRepAdaptor_Surface.GetType()`), its outward normal and centroid are evaluated at its parametric midpoint (`GeomLProp_SLProps`), and its exact area is integrated (`brepgprop.SurfaceProperties`). Every edge is visited, hashed for deduplication (the same edge is naturally seen once per adjacent face, so a face with 47 faces might see far more than 47 raw edge visits before deduplication), and classified (seam vs. real boundary vs. shared interior edge). Adjacency maps are built: which faces touch which other faces, which edges bound which faces, and which faces share each edge.
- *Leaves:* one `PartGeometry` object — holding a list of `FaceData` objects (each with `face_id`, `normal`, `centroid`, `area`, `surface_type`, a live `occ_face` handle, and `normal_valid`), a list of `EdgeData` objects (`edge_id`, `edge_type`, `length`, `adjacent_face_ids`), a list of `VertexData` objects, the bounding box, and the three adjacency dictionaries.
- *New information added:* everything — this is where raw text becomes structured, queryable Python objects for the first time.

**Stage 2 — `visualize_raw.build_display_mesh()`** (runs alongside, for the UI only).
- *Enters:* the `PartGeometry` from stage 1.
- *Internally:* `BRepMesh_IncrementalMesh` triangulates every exact face into flat triangles, tagging each triangle with the `face_id` of the exact face it approximates.
- *Leaves:* a `RawMeshData` object — flat lists of 3D points and triangle indices, plus a parallel `face_ids` list mapping each triangle back to its source face.
- *New information added:* a renderable approximation, purely for pixels on screen — the exact `PartGeometry` from stage 1 is completely untouched and remains the single source of truth for every further calculation.

**Stage 3 — `draft_analyzer.analyze_draft(part, pull_direction)`.**
- *Enters:* the `PartGeometry`, plus a chosen pull direction (initially usually `(0,0,1)`).
- *Internally:* for every valid face, `arcsin(|dot3(face.normal, pull_direction)|)` is computed, then thresholded into `"good"`/`"marginal"`/`"bad"` using `config.yaml`'s values.
- *Leaves (if `mutate=True`):* the *same* `PartGeometry` object, now with every `FaceData.draft_angle_deg` and `FaceData.draft_classification` filled in. Also returns a separate `DraftAnalysisResult` snapshot object (face-id lists per classification, area percentages, severity, human-readable suggestions) so the UI can later show "before" numbers even after the part gets mutated again for the "after"/optimal pass.
- *New information added:* a draft angle and a color classification, per face.

**Stage 4 — `undercut_detector.detect_undercuts(part, pull_direction)`.**
- *Enters:* the `PartGeometry` (already draft-analyzed) and the pull direction.
- *Internally:* a cheap prefilter flags faces whose normal points against the pull direction as *candidate* undercuts; candidate faces get grouped by adjacency into connected feature groups; optionally (`boolean_refine=True`), the most suspicious candidates get an expensive OCC Boolean sweep-and-intersect check (`BRepPrimAPI_MakePrism` + `BRepAlgoAPI_Common`) to *confirm* they're truly blocked by real material, not just facing the "wrong" way.
- *Leaves:* `FaceData.is_undercut`, `undercut_depth_mm`, `undercut_type` filled in on the mutated `PartGeometry`, plus a returned `UndercutDetectionResult` containing a list of `UndercutFeature` objects (grouped regions with severity, release direction, and a recommended mold action).
- *New information added:* per-face undercut flags, and feature-level grouped undercut objects with recommended fixes.

**Stage 5 — `direction_optimizer.optimize_mold_direction(part)`.**
- *Enters:* the `PartGeometry` (already has an initial draft/undercut pass for comparison purposes).
- *Internally:* generates ~30–54 candidate directions on a sphere grid; scores every one cheaply (draft + proxy undercuts, no Boolean); keeps only the most promising handful for expensive Boolean refinement; re-scores those; declares a winner; re-runs draft analysis and undercut detection *again*, this time with `mutate=True`, using the winning direction, overwriting the earlier +Z-based values.
- *Leaves:* `PartGeometry.optimal_pull_direction` and `direction_score` set; every `FaceData`'s draft/undercut fields now reflect the *optimal* direction, not the initial guess; a `DirectionOptimizationResult` capturing the full candidate ranking and before/after comparison.
- *New information added:* the single most important number in the whole pipeline — the chosen pull direction — plus a fully refreshed draft/undercut picture based on it.

**Stage 6 — `parting_line.detect_parting_line_candidates(part, optimal_direction)`.**
- *Enters:* the `PartGeometry`, now carrying the optimal direction and refreshed undercut data.
- *Internally:* every manifold edge (shared by exactly 2 faces) is checked — if its two neighboring faces' `dot3(normal, pull_direction)` values have opposite signs, it's a silhouette edge. Silhouette (plus some near-parting and boundary) candidates are grouped into connected components, ordered into wires, scored by projected area/closure quality, penalized if they run through known undercut regions, and the best one gets a Hou-inspired graph cleanup and smoothing pass for display.
- *Leaves:* `EdgeData.is_silhouette`/`is_parting_edge` flags set; `PartGeometry.parting_edge_ids` and `parting_wire_points` filled in; a `PartingLineResult` with a readiness verdict (`"ready"`/`"review"`/`"weak"`/`"failed"`).
- *New information added:* the actual candidate parting-line curve, plus a self-reported confidence/readiness verdict about how trustworthy that curve is.

**Stage 7 — `core_cavity.classify_core_cavity(part, optimal_direction)`.**
- *Enters:* the `PartGeometry` with the optimal direction set.
- *Internally:* one dot product per face — positive → cavity, negative → core, near-zero → parting — using the same `dot3` helper every earlier stage already used.
- *Leaves:* `FaceData.cavity_or_core` filled in; a `CoreCavityResult` with area percentages per side.
- *New information added:* a per-face mold-half label. (Not yet: an actual second solid body — see Part 10 for the exact honest boundary of what's done here.)

**Stage 8 — API serialization (`backend/api/main.py`).**
- *Enters:* the fully enriched `PartGeometry` plus whichever stage's result object the requested endpoint needs.
- *Internally:* every dataclass's `.to_dict()` method strips out any live OCC C++ handle (`occ_face`, `occ_shape`, etc. are never serialized — they'd crash JSON encoding) and returns plain nested dictionaries/lists/numbers.
- *Leaves:* a JSON HTTP response body.

**Stage 9 — Frontend rendering (`frontend/app.py`).**
- *Enters:* the JSON response.
- *Internally:* the mesh's per-triangle `face_id` list is matched up against the JSON's per-face classification fields to build a per-triangle color array; PyVista (Linux/Docker) or Plotly (macOS) renders the colored 3D mesh; tables and metrics are rendered directly from the JSON.
- *Leaves:* pixels in your browser.

---

# PART 8 — EVERY GEOMETRY MODULE, INDIVIDUALLY, IN DEPTH

For each module: purpose, exact inputs/outputs, the algorithm, the key classes/functions, which research paper it's based on, why it exists, and what depends on it next.

## 8.1 `step_loader.py` — Module 1: STEP → PartGeometry

**Purpose:** the single, only entry point for turning a `.stp` file into everything downstream needs. **Paper origin:** none — this is standard OCC engineering practice, not from an academic paper.

**Inputs:** a file path string. **Outputs:** a `PartGeometry` object (or raises `STEPLoadError`/`FileNotFoundError`/`ImportError`).

**Algorithm, in order:**
1. `STEPControl_Reader().ReadFile(path)` then `.TransferRoots()` then `.OneShape()` — parses the STEP text and returns one top-level `TopoDS_Shape` (OCC's universal "some geometry" handle).
2. Compute the exact bounding box with `Bnd_Box` + `brepbndlib.Add` (used later by the Bassi sweep-distance calculation, since you need to sweep further than the part's own diagonal to guarantee you've swept clean through it).
3. Count raw topology (`TopExp_Explorer` over SOLID/SHELL/FACE/EDGE/VERTEX) — this is a duplicate-inclusive raw count, used only for warnings/diagnostics, not the final deduplicated counts.
4. For every face: get a `BRepAdaptor_Surface` (a uniform adapter over *any* surface type — plane, cylinder, NURBS, all handled identically), clamp its UV parameter bounds (some surfaces report ±1e100 as "infinite" bounds, which would overflow the next step if not clamped), evaluate `GeomLProp_SLProps` at the midpoint to get the exact normal and 3D point, flip the normal if the face's OCC orientation flag says `REVERSED`, and integrate the exact area with `brepgprop.SurfaceProperties`.
5. For every face's boundary edges: hash each edge's underlying OCC pointer for O(1) deduplication (instead of an O(n²) geometric comparison of every edge against every other edge); detect seam edges (an edge appearing twice in the same face's own boundary loop — the tell-tale sign of a periodic surface's seam line, like the longitude line running down a cylinder); build the three adjacency dictionaries (`face_adjacency`, `face_to_edges`, `edge_to_faces`).
6. Deduplicate and extract every vertex's exact 3D coordinates via `BRep_Tool.Pnt`.
7. Assemble and return one `PartGeometry`.

**Key classes/functions:** `load_step()`, `load_step_with_fallback()`, and internal helpers `_compute_bounding_box`, `_extract_all_faces`, `_compute_face_normal_and_centroid`, `_extract_edges_and_build_adjacency`, `_extract_vertices`.

**Why it exists as its own isolated module:** it is deliberately the *only* file in the entire project allowed to call OCC's STEP reader directly — every other module receives geometry exclusively through the already-built `PartGeometry` object, never by reading a file itself. This means if the STEP-reading approach ever needs to change (a newer OCC version, a different reader), exactly one file needs to change.

**What depends on it:** literally every other module — it's the root of the whole dependency tree.

## 8.2 `draft_analyzer.py` — Module 2: Draft Angle

**Purpose:** classify every face's manufacturability risk relative to a chosen pull direction. **Paper origin:** the industry-standard SolidWorks convention, explicitly referenced inside Bassi (2010) as the accepted way to define draft.

**Inputs:** a `PartGeometry` and a pull direction (`Vec3`), plus a `mutate: bool` flag. **Outputs:** a `DraftAnalysisResult`, and (if `mutate=True`) updated `FaceData.draft_angle_deg`/`draft_classification` fields.

**Algorithm:** for every face with a valid normal, `angle = arcsin(|dot3(normal, pull_dir)|)`, then classify via the two thresholds from `config.yaml` (`good_threshold_deg: 1.5`, `marginal_threshold_deg: 0.5`). Also computes a **signed** dot product separately (`signed_dot`, no absolute value) to decide `"cavity"` vs `"core"` vs `"parting"` mold-side membership for grouping suggestions. Bad and marginal faces get grouped by `(surface_type, mold_side)` into `DraftSuggestion` objects with human-readable text (e.g., "Add 1.5° draft to 8 Plane faces on the cavity side").

**Why the `mutate` flag exists as a deliberate design decision (worth quoting to a judge as a specific engineering choice you understand):** the *exact same function* needs to be called in two very different situations — once to actually set the "official" displayed draft results for the UI (`mutate=True`, writes into `FaceData`), and dozens of times inside `direction_optimizer`'s candidate-scoring loop, where you need a throwaway draft score for a candidate direction *without* corrupting the part's real, currently-displayed classification (`mutate=False`, computes and returns the same numbers but writes nothing back onto the shared object). Without this flag, scoring 30+ candidate directions would require either 30+ separate copies of the whole part, or accept that the last-tested candidate's numbers permanently (and wrongly) overwrite the real result.

**What depends on it:** `undercut_detector.py` (uses draft angle as a cheap prefilter before running expensive Booleans), `direction_optimizer.py` (calls it, non-mutating, for every candidate).

## 8.3 `undercut_detector.py` — Module 3: Undercut Detection

**Purpose:** find geometry that would physically block mold release, and turn raw blocked-face lists into grouped, actionable "features." **Paper origin:** Bassi (2010) for the accessibility-checking mechanism (sweep + Boolean), Sangolli (2021) for the feature-level grouping/typing/recommendation layer.

**Inputs:** `PartGeometry`, pull direction, `mutate`/`boolean_refine` flags. **Outputs:** `UndercutDetectionResult` (face-id lists, a list of `UndercutFeature` objects, Boolean reliability metrics).

**Algorithm, two-stage:**
1. **Fast proxy stage (always runs):** any face whose signed `dot3(normal, pull_dir)` is clearly negative (pointing against the pull direction) is a *candidate* undercut. This alone is a *necessary but not sufficient* signal — a face can point "the wrong way" and still not actually be physically blocked by anything.
2. **Optional expensive Boolean confirmation stage (`boolean_refine=True`):** for the candidate faces, sweep the face forward along the pull direction by `2 × bounding_box_diagonal` (`BRepPrimAPI_MakePrism`) to build a "path the mold would have to travel through," then intersect that swept volume against the part's own solid (`BRepAlgoAPI_Common`). If that intersection has non-zero volume, real material is genuinely in the way — a *confirmed* undercut, not just a suspicious-looking face.
3. Confirmed/candidate undercut faces are grouped by adjacency (breadth-first search over `face_adjacency`) into `UndercutFeature` objects, each classified `"internal"`/`"external"`, given a severity, an estimated depth, a release direction, and — critically — a recommended mold action (`"redesign"`, `"lifter"`, `"side_core"`, `"review"`) with a numeric confidence score.

**Why not run the expensive Boolean check on every single face every single time (this is the single most important performance decision in the whole undercut module):** OCC's Boolean operations are computationally expensive (0.1–1 second *each*, sometimes more) and can be numerically brittle on real-world geometry (near-tangent or near-degenerate surfaces can make a Boolean operation fail outright). Running it unconditionally on every face for every one of ~30–54 candidate directions during optimization would mean thousands of expensive, occasionally-failing operations — impractically slow and unreliable. The fast, cheap normal-based prefilter first narrows the field down to only the faces actually worth spending Boolean time on.

**What depends on it:** `direction_optimizer.py` (calls it for every candidate direction, first without and then with Boolean refinement for the top candidates); `parting_line.py` (checks candidate parting wires for conflicts against confirmed undercut feature locations).

## 8.4 `direction_optimizer.py` — Module 4: Pull-Direction Search

**Purpose:** replace a human's manual "try Z, then try 4 other directions by hand" with an automatic search. **Paper origin:** Bassi et al. (2010).

**Inputs:** `PartGeometry`. **Outputs:** `DirectionOptimizationResult` (best direction, its score, the full ranked candidate table, before/after draft and undercut comparisons).

**Algorithm:**
1. `generate_candidate_directions(angular_step_deg=15)` builds a sphere-sampled grid of candidate unit vectors (roughly 30–54 of them, including the six principal axes `±X, ±Y, ±Z` explicitly, since axis-aligned directions are simpler and cheaper for real mold manufacturing).
2. Every candidate gets scored cheaply (non-mutating draft analysis + non-Boolean-refined undercut proxy) using a weighted score: `1500 × undercut_area_pct + 1000 × bad_draft_area_pct + 100 × marginal_area_pct + smaller terms`, where **lower is better**.
3. `_select_boolean_refinement_candidates()` applies several guard conditions (score-ratio-to-best threshold, "keep some principal axes regardless," "keep more candidates if scores are suspiciously close together," "always refine at least N candidates minimum") to select only the most promising handful for the expensive Boolean pass — this pruning gate is exactly what makes the whole optimizer practical to run inside a two-minute demo instead of five to ten minutes.
4. The promising candidates get re-scored with real Boolean-confirmed undercut evidence.
5. The single best-scoring direction wins; draft analysis and undercut detection are re-run one final time with `mutate=True` using that winning direction, overwriting the earlier +Z-based face data.

**Why this is architecturally the "conductor" module that calls almost everything else:** it is the only module that calls *both* `draft_analyzer` and `undercut_detector` repeatedly, in a loop, across many candidate directions — every other module calls each of those at most once per pull direction.

**What depends on it:** `parting_line.py` (needs the winning `optimal_pull_direction`); `core_cavity.py` (same); the frontend's "Direction" tab and before/after comparison view.

## 8.5 `parting_line.py` — Module 5: Parting Line

**Purpose:** find where the mold should physically split. **Paper origin:** Nee et al. (1998) for silhouette-edge detection and loop selection; Hou et al. (2018) for the graph-based cleanup/smoothing refinement layer.

**Inputs:** `PartGeometry`, the pull direction, the undercut detection result (for conflict scoring). **Outputs:** `PartingLineResult` (selected wire, quality/readiness assessment, refined+raw curve points for display).

**Algorithm:**
1. **Nee-style silhouette detection:** for every manifold edge (exactly 2 adjacent faces), compute both neighboring faces' signed `dot3(normal, pull_dir)`. If the two signs are opposite (one positive/cavity-side, one negative/core-side), the edge is a "silhouette edge" — a parting-line candidate. Near-vertical faces close to zero and open boundary/rim edges near the parting plane are also retained as softer candidates (`"near_parting"`, `"boundary"`).
2. Candidate edges are grouped into connected components (edges sharing a vertex belong to the same component) — a part can have several disconnected candidate loops, and only one is the "real" parting line.
3. Each component is scored using projection metrics (`PartingLineProjection`) — project the candidate wire onto the plane perpendicular to the pull direction and measure enclosed area, perimeter, and how well it forms a single *closed* loop (Nee's "maximum projected contour" rule: a bigger, cleaner closed loop is a better parting-line candidate than a small or open one).
4. Each component is also penalized if it geometrically overlaps or runs suspiciously close to already-detected undercut feature locations (`PartingLineUndercutConflict`) — a parting line that cuts straight through an undercut pocket is a bad, impractical candidate.
5. **Hou-style refinement:** for components that are branched or have gaps (cannot be trivially ordered into one simple wire), a weighted graph is built (edge weights combine length, curvature penalty, and distance from undercut regions) and a bounded shortest-path/minimum-cost search finds a cleaner loop through it; Chaikin smoothing (a standard curve subdivision/smoothing technique) is applied purely for a nicer-looking *display* curve, while the underlying selected exact B-Rep edge IDs are preserved separately for correctness.
6. A final readiness gate (`"ready"`/`"review"`/`"weak"`/`"failed"`) is computed and explicitly reported, along with whether it currently blocks downstream core/cavity work.

**Why this is honestly labeled a "foundation," not "fully done," in the project's own docs:** the full Hou (2018) vision is a *complete global* graph optimization across the whole candidate space; the current code implements a bounded, practical version of that idea for the common branched/gapped cases, with an explicit deterministic fallback for very large graphs — genuinely useful and demoable, but not the fully generalized optimization the paper describes for every possible edge case.

**What depends on it:** `core_cavity.py` conceptually (a *complete* core/cavity Boolean split would need a fully validated parting line as its cutting curve — this is exactly why full core/cavity extraction is gated behind parting-line completion in the roadmap).

## 8.6 `core_cavity.py` — Module 6: Core/Cavity Face Classification

**Purpose:** label every face as belonging to the cavity mold half, the core mold half, or sitting right on the parting boundary. **Paper origin:** not tied to one specific paper — it's the natural, direct geometric consequence of already having a pull direction (same `dot3` sign logic used everywhere else in this project).

**Inputs:** `PartGeometry`, optionally an explicit pull direction (otherwise falls back to `part.optimal_pull_direction`, or to plain `+Z` with a warning if neither is available). **Outputs:** a `CoreCavityResult` (face-id lists per class, area and percentage breakdowns), and if `mutate=True`, `FaceData.cavity_or_core` filled in on every face.

**Algorithm:** for every valid face, `signed_dot = dot3(normal, pull_direction)`; if it's above a small positive threshold (default `0.05`, roughly 2.9° from perpendicular) → `"cavity"`; below the negative threshold → `"core"`; otherwise → `"parting"`.

**The honest, precise boundary of what this module does and doesn't do (important for Q&A):** this is real, working, per-face *classification* — you genuinely get back "these 32 faces are cavity-side, these 41 are core-side," with a live API endpoint (`GET /parts/{filename}/core-cavity`) and a real Streamlit tab that colors the 3D model green/blue accordingly. What it does **not** yet do is the heavier "Level 2" deliverable of actually performing a Boolean *split* of the single solid body into two genuinely separate solid volumes (one representing the cavity insert, one representing the core insert) that could, say, be exported as two separate STEP files for a tool shop. That would require extending the parting line into a full-height parting *surface* and running an OCC solid-splitting Boolean operation against it — a meaningfully bigger next step, correctly still listed as upcoming work.

## 8.7 `visualize_raw.py` — Display Adapter (not a DfM algorithm)

**Purpose:** the one and only bridge between exact B-Rep math and pixels. **Inputs:** `PartGeometry` or a raw `TopoDS_Shape`. **Outputs:** `RawMeshData` (flat triangle arrays with a `face_id` per triangle) and a `to_pyvista()` conversion helper. **Algorithm:** `BRepMesh_IncrementalMesh(shape, linear_deflection, ..., angular_deflection, ...)` triangulates every face, then the code walks each face's resulting triangulation and tags every triangle with its source `face_id`. **Why this file exists at all as a hard separation from the analysis modules:** so that a future bug or change in the visualization/meshing code can *never* silently affect a DfM analysis number — the exact math and the pretty picture are architecturally guaranteed to never share code paths.

## 8.8 The planned AI agent — `backend/agent/dfm_agent.py` and `backend/agent/tools.py`

**Current state, plainly:** both files are completely empty (0 bytes). Nothing has been written yet. **The intended design (from `Engine.md`/`understand.md`), for when it is built:** wrap each geometry module's function as a callable "tool" the LLM can invoke (e.g., a `detect_undercuts_tool(part_file, direction)` LangChain tool), feed the LLM the deterministic geometry results as context, and let it reason step by step and produce natural-language explanations/corrections and (eventually) a PDF report — while the actual geometric truth (face lists, angles, volumes) always still comes from the exact, deterministic modules in Parts 8.1–8.6, never invented by the language model. This "LLM narrates, geometry decides" split is the intended safeguard against an LLM hallucinating a wrong technical fact.

---

# PART 9 — HOW TO PRESENT THIS

## 9.1 The 30-second version (use for an opening line or if cut off)

> "Mold engineers currently spend three to four hours per part manually testing mold-opening directions and checking for draft and undercut problems in CATIA or SolidWorks. We built a tool that loads the exact STEP CAD geometry with an open-source CAD kernel called OpenCASCADE, automatically searches dozens of candidate directions, flags every risky face, detects undercuts with real geometric Boolean checks — not guesses — and shows all of it as a color-coded 3D model in a browser in under two minutes."

## 9.2 The 5-minute version (structure, not a script to memorize word for word)

1. **(30s) The problem.** State the manual workflow and the hours it costs, exactly as in Part 1.2.
2. **(45s) What a mold actually is and why draft/undercuts matter.** Use the muffin-tin analogy (draft) and the doorknob-through-mail-slot analogy (undercut) — these two analogies alone make the whole domain click for a non-mechanical-engineer judge.
3. **(90s) Live demo.** `docker compose up`, open `localhost:8501`, select `Part1.stp`, click through the five/six guided steps (Load STEP → Draft → Undercuts → Direction → Parting Line → Core/Cavity), narrating what each screen shows using the exact "Say:" lines from `docs/DEMO_SCRIPT.md` if you want word-for-word safety.
4. **(60s) Architecture in one breath.** "Browser talks to a Streamlit frontend, which talks over a REST API to a FastAPI backend, which calls our geometry engine, which calls pythonOCC, which calls the open-source OpenCASCADE CAD kernel that actually parses the exact STEP geometry — the frontend never touches CAD code directly, so we can swap either side independently."
5. **(45s) The research grounding.** "Our direction search is based on Bassi 2010's sweep-and-Boolean accessibility method; our undercut feature grouping follows Sangolli 2021; our parting-line detection follows Nee 1998 for the silhouette-edge logic and Hou 2018 for the graph-based cleanup — we didn't invent this from scratch, we productized 25+ years of published mold-design research into one open pipeline."
6. **(30s) Honest status + what's next.** "Level 1 — direction search, draft, undercuts, and an initial parting line — is working end to end today. Core/cavity currently classifies faces to each mold half; splitting into two physical solid bodies and the natural-language AI reasoning layer are our next milestones."

## 9.3 The 10-minute version (add these on top of the 5-minute structure)

- Spend an extra 60–90 seconds on STEP vs. mesh (Part 4.23's table) — this is the single fact that most impresses a technical judge, because it shows you understand *why* the accuracy requirement forced every downstream architectural decision (exact B-Rep everywhere, triangulation only at the very last display step).
- Walk through one concrete face on the actual model in the UI and manually narrate the math out loud: "this face's normal is roughly pointing sideways relative to our chosen pull direction, so `arcsin` of that dot product gives us a small angle — that's why it's colored red." Doing real math live, even approximately, signals genuine understanding far more than reciting the pipeline diagram.
- Show `http://localhost:8000/docs` for 30 seconds and mention "every one of these REST endpoints returns structured JSON with an error code, a human message, and a recovery hint if something goes wrong — we designed the API to fail informatively, not silently."
- Explicitly mention the Boolean pruning gate in `direction_optimizer.py` as a specific, named performance engineering decision: "checking every face against every candidate direction with expensive OCC Boolean operations would take minutes; we score cheaply first and only run the expensive geometric confirmation on the five or so most promising candidates."
- Close with the roadmap table from Part 10, stated confidently rather than defensively — a clear "here is exactly what's next and why" is a strength, not a weakness, in a hackathon judged partly on architecture and extensibility.

## 9.4 Realistic technical questions judges may ask, with detailed answers

**Q: "Why STEP files and not just any 3D model format?"**
A: STEP stores exact mathematical surfaces (B-Rep), not approximated triangles. A mold is machined to roughly ±0.01mm tolerance; a triangle-mesh format like STL can be off by 0.1–1mm depending on resolution — 10 to 100 times too imprecise for draft-angle and parting-line placement, where that error could hide or invent a real manufacturing problem.

**Q: "Why pythonOCC/OpenCASCADE instead of writing your own geometry code?"**
A: Exact B-Rep math — especially NURBS surface evaluation and robust Boolean solid operations — is a multi-decade research field. OpenCASCADE is a mature, open-source, production-grade CAD kernel (the same kernel FreeCAD is built on) that already solves this correctly; reimplementing it would be its own multi-year project, completely out of scope, and strictly worse than using a battle-tested library.

**Q: "Why does pythonOCC need Conda/Micromamba instead of just `pip install`?"**
A: `pythonocc-core` is a Python wrapper around a large pre-compiled C++ library. Pip only reliably manages pure-Python packages; it has no good mechanism for the native, compiled, OS-specific binary dependencies OCC needs. Conda-forge provides pre-built, tested binaries for exactly this kind of package, which is why the whole toolchain (and Docker's backend image) is built around Conda/Micromamba specifically for this one dependency.

**Q: "How do you find the best mold-opening direction, concretely?"**
A: We sample roughly 30–54 candidate directions across a sphere (every 15°, plus the six principal axes explicitly). Each candidate is scored cheaply using draft angles and a fast undercut proxy. The best-scoring handful then get an expensive, geometrically rigorous confirmation step: we sweep each suspect face along the candidate direction and perform a real Boolean intersection against the part's solid body — if material is actually in the way, it's a confirmed undercut, not a guess. The single lowest-scoring (best) direction after that refinement is selected.

**Q: "How exactly do you detect undercuts, and how sure are you they're real?"**
A: Two stages. First, a cheap directional prefilter (does this face's normal point against the pull direction?) — necessary but not sufficient. Second, an optional but implemented Boolean confirmation: sweep the face forward through space along the pull direction and check if it actually intersects solid material — if the intersection volume is non-zero, the undercut is geometrically confirmed, not just suspected. We run this expensive confirmation selectively on the most likely candidates rather than exhaustively on every face of every direction, for performance reasons, and our result objects explicitly report whether a given undercut was proxy-only or Boolean-confirmed, so we're never overstating certainty.

**Q: "What's the parting line, and is it fully solved?"**
A: It's the curve where the two mold halves meet — geometrically, the edges where one neighboring face is on the "cavity" side of the pull direction and the other is on the "core" side (a silhouette edge). We detect these candidates, group them into connected loops, score loops by projected area/closure quality (following Nee 1998), and apply a graph-based cleanup and smoothing pass for branchy or gappy cases (inspired by Hou 2018). It is a genuine, working foundation with an honest self-reported readiness score (ready/review/weak/failed) — the fully generalized global optimization described in the original Hou paper for every possible edge case is still planned, and we say so explicitly rather than overclaiming.

**Q: "Is core/cavity extraction done?"**
A: Face-level classification is done and demoable today — every face gets labeled cavity, core, or parting based on the pull direction, with a live color-coded 3D view. What's not yet built is the heavier step of actually Boolean-splitting the single solid body into two separate physical solids (e.g., to export as two STEP files for a tool shop) — that requires extending the parting line into a full parting surface first, which is why it's sequenced after full parting-line completion in our roadmap.

**Q: "Where's the 'AI' in this AI-driven solution? Isn't this just geometry?"**
A: Fair challenge, and we answer it directly: the geometry engine is deliberately the hard, correctness-critical 90% we built first, because without accurate STEP parsing, undercut detection, and direction search, nothing an LLM said on top of it would be trustworthy. The natural-language reasoning/explanation layer (an LLM agent calling these geometry functions as tools, then explaining results and suggesting fixes conversationally) is architected for — you can see the empty `backend/agent/` module structure and the `agent:` section already reserved in `config.yaml` — but it is not implemented yet. We chose to make the deterministic engine solid and honestly reported rather than bolt on a flashy but unreliable LLM layer with shaky geometric grounding underneath it.

**Q: "How do you know your numbers are correct? Any testing?"**
A: Yes — a pytest suite with unit tests (pure logic, e.g., is 1.6° correctly classified as "good") that need no CAD engine at all, plus integration tests that run the real pipeline against the real `Part1.stp` file with pythonOCC installed. We also have separate CLI validation and performance-profiling scripts that smoke-test the full pipeline and check pipeline stage timings against configured budgets, producing JSON evidence files.

**Q: "What happens with a more complex part, like your Level 2 file?"**
A: Honestly: `Part2.stp` was not present in our workspace and hasn't been run through the pipeline yet, so we don't have empirical results for a more complex geometry to share right now. Our performance-pruning design (the Boolean refinement gate) was specifically built anticipating that a bigger, more complex part would otherwise make exhaustive Boolean checking too slow, so the architecture is designed with that scaling concern in mind even without Part2-specific numbers yet.

**Q: "Why Docker/Conda instead of something simpler?"**
A: Because `pythonocc-core` genuinely cannot be reliably installed with plain `pip`/`venv` across different laptops and operating systems — it wraps a large compiled C++ library. Docker guarantees every judge or teammate runs the exact same pre-tested environment regardless of their own machine; Conda/Micromamba is the correct tool specifically because it (unlike pip) manages non-Python compiled dependencies.

**Q: "Why is the frontend separate from the backend instead of one app?"**
A: Different dependency weight (the CAD toolchain is huge; the UI doesn't need it), independent development/restart cycles, and a clean, stable JSON-over-HTTP contract that would let Bosch swap in a different frontend (or a different backend framework) later without touching the other side — exactly matching the hackathon's explicit requirement that the code be easy for Bosch to extend after the hackathon ends.

---

# PART 10 — WHAT IS ACTUALLY DONE, WHAT IS PARTIAL, WHAT IS PLANNED (Level 1 / 2 / 3)

## 10.1 Honest status table (cross-checked directly against the source code, not just the docs)

| Capability | Status | Where |
|---|---|---|
| STEP B-Rep parsing, exact normals/areas/topology, adjacency graphs | **Done** | `step_loader.py` |
| Display mesh with `face_id` traceability | **Done** | `visualize_raw.py` |
| Draft angle analysis (initial and optimal-direction passes) | **Done** | `draft_analyzer.py` |
| Undercut proxy detection | **Done** | `undercut_detector.py` |
| Undercut Boolean confirmation | **Done, selective** (not exhaustive across every face/direction) | `undercut_detector.py` |
| Undercut feature grouping, typing, mold-action recommendation with confidence | **Done** | `undercut_detector.py` |
| Optimal pull-direction search with smart Boolean pruning | **Done** | `direction_optimizer.py` |
| Parting-line candidate detection, wire ordering, undercut-conflict scoring | **Done (foundation)** | `parting_line.py` |
| Parting-line Hou-style global optimization for every edge case | **Partial** | `parting_line.py` |
| Core/cavity **face classification** (cavity/core/parting labels + live API + UI tab) | **Done** — corrects the stale claim in some attached docs | `core_cavity.py`, `/parts/{filename}/core-cavity` |
| Core/cavity **Boolean solid split** into two separate physical bodies | **Not implemented** | planned, needs a complete parting surface first |
| FastAPI REST layer (parts, summary, draft, undercuts, direction, parting-line, core-cavity, error handling) | **Done** | `backend/api/main.py` |
| Streamlit guided UI with 3D viewer, before/after views, diagnostics | **Done** | `frontend/app.py` |
| pytest test suite (unit + integration) | **Done** | `tests/` |
| CLI validation + performance profiling harnesses | **Done** | `backend/validation/` |
| LangChain/LLM agent orchestration | **Not started at all — files are empty** | `backend/agent/dfm_agent.py`, `tools.py` |
| PDF report export | **Not implemented** | planned (ReportLab is already a listed dependency) |
| `Part2.stp` validated end to end | **Not done** | file not present in this workspace |

## 10.2 Mapping to the hackathon's own Level 1 / Level 2 / Level 3 framing

**Level 1 (what the hackathon's simple input file is meant to test):** STEP parsing, draft analysis, undercut detection, optimal pull-direction search, an initial parting-line candidate with visualization. **This is genuinely complete and demoable end to end today**, including a self-reported readiness/quality score rather than a silent guess.

**Level 2 (what the hackathon's more complex input file is meant to test):** core/cavity extraction on more complex geometry. **Partially there:** face-level cavity/core/parting classification is implemented, tested informally through the UI (though it has no dedicated pytest file yet — worth knowing if asked directly "is core_cavity unit tested?" — the honest answer is "not yet, unlike every other geometry module"), with a working API endpoint and 3D color visualization. The remaining Level 2 work is the actual Boolean split into two separate solid bodies, plus validating the whole pipeline against a genuinely more complex second part, which has not been done in this workspace yet.

**Level 3 (the longer-term vision described in `understand.md`/`Engine.md`, e.g., a follow-on internship phase):** side-core/lifter geometric design (not just recommending that one is needed, but actually designing its shape), a fully conversational LLM agent layer that reasons over the deterministic geometry outputs and answers free-form questions, and automated PDF report generation. **None of this is started** — it is a genuine, clearly scoped future roadmap, not a current claim.

## 10.3 The one sentence to say if you're ever unsure how to phrase the status

> "Our geometric analysis engine — the hard, correctness-critical part — is complete and working end to end for Level 1, with an honest foundation for Level 2 face classification. What's still ahead is the full Boolean core/cavity solid split, validating on more complex geometry, and the natural-language AI reasoning layer we've architected space for but haven't built yet."

That sentence is accurate against the actual code, defensible under follow-up questions, and — because it's honest about the gap instead of overselling — it will hold up far better under a technical judge's follow-up questions than a claim that oversells what's implemented.

---

*End of document. You now have: the business problem and why it matters, the entire injection-molding domain with analogies, the full system architecture and why every layer exists, every technology explained from zero with real alternatives, exact run commands with what each one does internally, a full repo walkthrough, the complete object-by-object STEP file lifecycle, every geometry module's algorithm and research grounding, presentation scripts at three lengths, a full bank of judge Q&A with answers, and an honest, code-verified implementation status. Good luck.*

