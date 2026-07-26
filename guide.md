# DfM Agent — Reverse-Engineered Runtime & Presentation Guide

Source of truth: `backend/models/geometry_models.py`, `backend/config.py`, `backend/geometry/{step_loader,draft_analyzer,direction_optimizer,undercut_detector,parting_line,core_cavity,visualize_raw}.py`, `backend/api/main.py`, `frontend/app.py`, `docker-compose.yml`, `Dockerfile.backend`, `environment.yml`, `config.yaml`, `README.md`.

This document reconstructs runtime execution exactly as it happens. Nothing here is assumed — every claim is tied to a specific function, endpoint, or line of code. Where the code does something different from older docs (`README.md`, `onboarding.md`), that discrepancy is called out explicitly. Read this alongside `understanding.md` (the from-zero conceptual teaching doc) — this file is the code-accurate execution/reverse-engineering layer on top of it.

---

## PART A — From `git clone` to a browser tab

This is what a Bosch judge will actually do. Walk through it exactly this way.

### A1. Clone and look at the structure

```bash
git clone <repo-url>
cd Bosch
```

Top-level layout that matters at runtime:

```
Bosch/
├── backend/
│   ├── api/main.py                 FastAPI app — the ONLY HTTP surface
│   ├── geometry/                   7 modules — the "geometry engine"
│   │   ├── step_loader.py          Module 1 — STEP → PartGeometry
│   │   ├── draft_analyzer.py       Module 2 — draft angle / classification
│   │   ├── direction_optimizer.py  Module 3 — candidate direction search
│   │   ├── undercut_detector.py    Module 4 — undercut/accessibility (3431 lines — biggest module)
│   │   ├── parting_line.py         Module 5 — silhouette wire detection (2869 lines)
│   │   ├── core_cavity.py          Module 6 — face-level cavity/core split (140 lines, small)
│   │   └── visualize_raw.py        Visualization adapter — B-Rep → triangles
│   ├── models/geometry_models.py   Shared dataclasses — the "nouns" of the whole system
│   ├── agent/dfm_agent.py, tools.py  EMPTY FILES — 0 bytes. Not built. Aspirational only.
│   └── config.py                   Loads config.yaml into frozen dataclasses
├── frontend/app.py                  Streamlit UI — 3958 lines, single file
├── data/parts/                      Drop .stp files here (Part1.stp ships in the repo)
├── config.yaml                      Every tunable threshold, no code changes needed
├── environment.yml                  Conda/micromamba dependency lock
├── requirements.txt                  Pip deps installed inside the conda env
├── Dockerfile.backend / Dockerfile.frontend / docker-compose.yml
└── tests/                            pytest suite, one file per geometry module
```

**Say this:** "There's exactly one backend process and one frontend process. The backend never touches the UI, and the frontend never touches OpenCascade directly — it only ever calls the backend over HTTP. That separation is what let two people build this in parallel."

### A2. Why can't I just do `python -m venv` + `pip install`?

`pythonocc-core` (the Python binding to the OpenCascade C++ kernel) ships as compiled C++ extensions. The conda-forge build is the reliable one; pip wheels for OCC are inconsistent across OS/Python combinations. This is explicitly documented in `step_loader.py`'s `_require_occ()` error message: *"Install via conda: conda install -c conda-forge pythonocc-core. Pip builds are unreliable — conda is strongly recommended."* This is why the project uses **Conda/Micromamba environments**, not plain `venv`.

- **venv/pip** — pure-Python dependency isolation. Fine for FastAPI/Streamlit/NumPy, not for OCC.
- **Conda/Micromamba** — full binary package manager. Manages Python itself, C/C++ shared libraries (VTK, OCC), not just Python wheels. `environment.yml` pins `python=3.11`, `pythonocc-core=7.7.2`, `cadquery=2.4.0`, `vtk=9.2.*` from `conda-forge` + `cadquery` channels, then installs everything else (`fastapi`, `streamlit`, `pyvista`, `stpyvista`, `plotly`, `langchain`, `pydantic`, `uvicorn`, `PyYAML`, `networkx`, `reportlab`, `pytest`...) via `pip:` inside that same conda env.
- **Micromamba** — a tiny (~5 MB), dependency-free reimplementation of conda's solver. Chosen over requiring a system-wide Miniconda install because it installs into a local `.micromamba/` folder inside the repo (gitignored) — no admin rights, no polluting the judge's machine, no version conflicts with an existing conda install.

### A3. Environment setup (Micromamba path, what README.md prescribes)

```bash
mkdir -p .micromamba
curl -Ls https://micro.mamba.pm/api/micromamba/osx-arm64/latest | tar -xj -C .micromamba bin/micromamba
export MAMBA_ROOT_PREFIX="$PWD/.micromamba/root"
./.micromamba/bin/micromamba create -y -f environment.yml -n dfm_agent -r "$MAMBA_ROOT_PREFIX"
```

What happens internally: `micromamba` downloads its own static binary (no dependencies), then reads `environment.yml`, resolves a dependency graph across `conda-forge` + `cadquery` channels, downloads and unpacks the binary packages (OCC, VTK, Python 3.11 itself) into an isolated env named `dfm_agent`, then runs `pip install` for the packages listed under the `pip:` block. Takes 5–15 minutes and 2–5 GB the first time because pythonOCC + VTK are large binary artifacts.

Verify:
```bash
./.micromamba/bin/micromamba run -r "$MAMBA_ROOT_PREFIX" -n dfm_agent \
  python -c "from OCC.Core.STEPControl import STEPControl_Reader; print('OCC OK')"
```
This import alone proves the C++ kernel bindings loaded — if this fails, nothing else in the app will work.

### A4. Running locally without Docker (two terminals)

```bash
# Terminal 1 — backend
export MAMBA_ROOT_PREFIX="$PWD/.micromamba/root"; export PYTHONPATH="$PWD"
./.micromamba/bin/micromamba run -r "$MAMBA_ROOT_PREFIX" -n dfm_agent \
  uvicorn backend.api.main:app --host 0.0.0.0 --port 8000

# Terminal 2 — frontend
export MAMBA_ROOT_PREFIX="$PWD/.micromamba/root"; export PYTHONPATH="$PWD"
./.micromamba/bin/micromamba run -r "$MAMBA_ROOT_PREFIX" -n dfm_agent \
  streamlit run frontend/app.py --server.port 8501
```

- `PYTHONPATH="$PWD"` — required because `backend/api/main.py` is imported as `backend.api.main:app` (a dotted module path). Without the repo root on `PYTHONPATH`, Python cannot resolve the `backend` package.
- `uvicorn backend.api.main:app` — uvicorn is an ASGI server; it imports the `app` object (a `FastAPI()` instance created at `backend/api/main.py:17`) and starts an async event loop that dispatches incoming HTTP requests to the `@app.get(...)`-decorated route functions.
- `streamlit run frontend/app.py` — Streamlit re-executes `app.py` top-to-bottom on every user interaction (every button click, slider drag, checkbox toggle triggers a full script rerun; `st.session_state` is the only thing that persists across reruns — this is why the code stores every analysis result in `st.session_state[...]`, e.g. `draft_result`, `undercut_result`).

### A5. Running with Docker (`docker compose up`)

```bash
cp Part1.stp data/parts/
docker compose up
open http://localhost:8501     # Streamlit UI
open http://localhost:8000/docs  # FastAPI interactive docs (Swagger UI)
```

What `docker-compose.yml` actually does:
- **`backend` service** — builds `Dockerfile.backend` (multi-stage: builder stage installs the full conda env + pip deps from `environment.yml`/`requirements.txt`, then fails fast with `python -c "import OCC; import cadquery; import pyvista; import stpyvista"` so a broken image never reaches judges silently; final stage copies only the built conda env, not the build tools, to keep the image lean). Runs `uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload`. Bind-mounts `./data`, `./reports`, `./backend`, `./config.yaml` so file edits are live without rebuilding the image. Exposes port 8000. Has a `healthcheck` that curls `/health` every 30s.
- **`frontend` service** — builds `Dockerfile.frontend`, runs Streamlit under `xvfb-run` (a virtual X11 framebuffer — needed because VTK/PyVista expects a display server even in "headless" mode on Linux containers), sets `DFM_BACKEND_URL=http://backend:8000` (Docker's internal DNS resolves the `backend` service name to its container IP — this is why the frontend code reads `BACKEND_URL` from an env var instead of hardcoding `localhost`), and `depends_on: backend`.
- **Docker image vs container**: the image is the frozen, built filesystem (conda env + code baked in); the container is a running instance of that image. `docker compose up` builds two images (or reuses cached layers) and starts two containers that can talk to each other over a private Docker network.
- **Docker vs Docker Compose**: Docker builds/runs one container from one Dockerfile. Compose orchestrates *multiple* containers (backend + frontend here) as one unit — one command starts both, wires their network, and mounts volumes consistently. This project needs Compose specifically because backend and frontend are two independent processes that must discover each other by name.

### A6. Tests, validation, profiling — what "run this" means internally

```bash
pytest tests/ -v                                            # 10 test files, one per geometry module
python -m backend.validation.part_validation --json         # batch-validates every .stp in data/parts
python -m backend.validation.performance_profile --json     # timing/memory profile per module
python -m backend.geometry.visualize_raw data/parts/Part1.stp  # opens a native PyVista desktop window (dev-only, bypasses Streamlit entirely)
```
Each geometry module also has a `if __name__ == "__main__":` CLI block (see `step_loader.py` lines 978-1009, `draft_analyzer.py` lines 743-772) so any module can be run standalone against a `.stp` file and dump a JSON result — this is what lets each module be unit-tested independently of FastAPI/Streamlit.

### A7. Opening the browser — what you actually see first

Streamlit serves `http://localhost:8501`. On load, `frontend/app.py` executes top to bottom: `st.set_page_config(page_title="DfM Agent", layout="wide")` → `st.title("DfM Agent")` → sidebar tries `requests.get(f"{BACKEND_URL}/health")`. If that fails, `st.error(...)`; `st.stop()` halts the entire script — **the UI literally cannot render past this point without a live backend.** This is intentional: it forces the presenter to prove the backend is up before anything else loads.

---

## PART B — Master data flow (every transformation, end to end)

```
Part1.stp (ISO-10303 STEP text file on disk)
   │  STEPControl_Reader().ReadFile() + .TransferRoots() + .OneShape()      [step_loader.load_step]
   ▼
TopoDS_Shape (single in-memory OCC object — exact B-Rep, NURBS/analytic surfaces, no mesh yet)
   │  TopExp_Explorer(shape, TopAbs_FACE) walks every face
   │  BRepAdaptor_Surface + GeomLProp_SLProps → outward normal, centroid, surface type
   │  brepgprop.SurfaceProperties → exact area (surface integration, not mesh approximation)
   ▼
list[FaceData]  (one per B-Rep face; holds occ_face handle + normal + area + surface_type)
   │  TopExp_Explorer(face, TopAbs_EDGE) per face + TopoDS_Shape.HashCode() dedup
   │  BRepAdaptor_Curve → edge type; brepgprop.LinearProperties → arc length
   ▼
list[EdgeData]  (unique edges; adjacent_face_ids links back into FaceData)
   │  hash-based face↔face, face→edges, edge→faces adjacency maps built in the same pass
   ▼
PartGeometry  (occ_shape + faces + edges + vertices + 3 adjacency dicts + bounding box)
   │  ── this ONE object is passed by reference through every module below; each
   │     module mutates FaceData/EdgeData fields on it in place and also returns
   │     its own immutable *Result dataclass for the API to serialise ──
   ▼
draft_analyzer.analyze_draft(part, pull_dir)         → writes face.draft_angle_deg / .draft_classification
   ▼
direction_optimizer.optimize_mold_direction(part)    → generates ~54 candidate directions,
   │                                                      scores each with draft+undercut proxies,
   │                                                      Boolean-refines a pruned survivor subset,
   │                                                      writes part.optimal_pull_direction
   ▼
undercut_detector.detect_undercuts(part, direction)  → proxy pass (draft<marginal) then optional
   │                                                      swept-face BRepAlgoAPI_Common Boolean refinement,
   │                                                      writes face.is_undercut / .undercut_type
   ▼
parting_line.detect_parting_line_candidates(part, direction)  → classifies every edge as
   │                                                      silhouette/near_parting/boundary/skipped,
   │                                                      connected-component grouping, ordered-wire
   │                                                      construction, graph cleanup + Chaikin smoothing,
   │                                                      writes part.parting_edge_ids / .parting_wire_points
   ▼
core_cavity.classify_core_cavity(part, direction)    → per-face sign(n·d) classification only,
   │                                                      writes face.cavity_or_core  (NOT a Boolean solid split)
   ▼
visualize_raw.build_display_mesh(part)               → BRepMesh_IncrementalMesh triangulates occ_shape,
   │                                                      RawMeshData: points[], faces[](triangle indices),
   │                                                      face_ids[] (one STEP face_id per triangle — the
   │                                                      critical link that lets colors map back to B-Rep)
   ▼
FastAPI endpoint (backend/api/main.py)  → part.to_dict() + result.to_dict() + mesh.to_payload(include_geometry=True)
   │  serialised as one JSON blob per endpoint call
   ▼
HTTP response over the Docker network / localhost:8000
   ▼
frontend/app.py  _fetch_*() → requests.get(...) → response.json() → st.session_state[result_key]
   │  _mesh_to_pyvista() rebuilds a pyvista.PolyData from points[]/faces[]/*_rgb[] arrays
   │  (macOS: _show_mesh_plotly() builds a Plotly Mesh3d figure instead — VTK's Cocoa
   │   backend crashes on Streamlit's worker threads on macOS, so the code detects
   │   sys.platform == "darwin" and swaps renderers entirely)
   ▼
Browser (WebGL canvas via Plotly, or a PNG snapshot via PyVista off-screen render + stpyvista)
```

**Key point to say out loud:** nothing downstream of `step_loader.py` ever touches the STEP file again or re-parses OCC topology from scratch. Every module reads and enriches the *same* `PartGeometry` object. This is why `face_id` stays stable across the Draft tab, Undercuts tab, and Core/Cavity tab — it's the same face object, just with more fields filled in each time.

---

## PART C — Screen-by-screen reverse engineering

For each element: what you see → what to say → frontend fn → backend endpoint → backend fn → geometry module → OCC APIs → objects created → algorithm → JSON → render → why.

### C0. Sidebar — "Part" panel

**What you see:** "Backend connected" success banner, a STEP file dropdown, checkboxes (`Include face table`, `Build display mesh`, `Boolean volumes`, `Show only high-confidence undercuts`, `Show proxy fallback faces`, `Refined parting curve`, `Raw parting wire`), sliders (`Volume opacity`, `Mesh quality`), three pull-direction number inputs (X/Y/Z), and two button groups: **AI Mold Engineer** (`Run Next Step`, `Run Full Level 1 Flow`, `Reset Journey`) and **Manual Checks** (`Load STEP`, `Run Draft`, `Detect Undercuts`, `Find Best Direction`, `Detect Parting Line`, `Classify Core/Cavity`).

**Say this:** "Before anything else runs, the app pings the backend's `/health` endpoint. If that fails, the whole UI stops — there's no way to fake a demo without a live geometry engine behind it."

- Frontend code: `frontend/app.py` lines 2851-2930 (module-level script, not a function — Streamlit reruns top-level code every interaction).
- `requests.get(f"{BACKEND_URL}/health")` → backend `@app.get("/health")` (`backend/api/main.py:550`) → returns `{"status": "healthy", "parts_dir": ..., "parts_dir_exists": ...}`. No geometry module runs here — it's a filesystem existence check only.
- `requests.get(f"{BACKEND_URL}/parts")` → `@app.get("/parts")` (`main.py:559`) → lists every `.stp`/`.step` file under `data/parts/`.
- The **pull-direction (X/Y/Z)** number inputs are the single most important control in the whole demo: every downstream endpoint (`/draft`, `/undercuts`, `/direction`, `/parting-line`) accepts `dx/dy/dz` query params seeded from these three widgets. Changing them and re-running is literally how you demonstrate "the mold engineer tries a direction, sees it's bad, tries another."
- Mesh quality slider → `mesh_deflection` param → passed straight into `BRepMesh_IncrementalMesh(shape, linear_deflection, ...)` in `visualize_raw.py`. Lower value = finer triangles = more accurate silhouette but slower/heavier JSON payload.
- **Why Bosch needs this:** a mold engineer never wants to guess the pull direction manually across 3 numbers; that's exactly what "Find Best Direction" automates below. The manual XYZ boxes exist so a user can override the algorithm and compare (e.g. "what if we're forced to use +Z because of an existing tool base").

### C1. "Run Next Step" / "Run Full Level 1 Flow" — the AI Mold Engineer Journey

This is a **state machine**, not an AI/LLM. `STEP_ORDER = ("Load STEP","Draft","Undercuts","Direction","Parting Line","Core/Cavity")` (`app.py:1980-1998`). `_next_step_name()` (`app.py:2095`) returns the first step whose `st.session_state[result_key]` is still empty. `_journey_prompt()` (`app.py:2102`) prints a scripted sentence per step ("Topology is loaded. Next I will classify draft quality...").

**Say this exactly:** "This isn't calling an LLM — there's no agent yet. It's a deterministic checklist that runs the same six backend calls a human would click one by one, in the correct dependency order, and narrates each step with a canned sentence. The actual LLM orchestration layer (`backend/agent/dfm_agent.py`) is an empty file today — that's the honest Level 2/3 roadmap item, not a hidden feature."

`_run_step_sequence()` (`app.py:3047`) loops `STEP_ORDER`, calling `_run_named_step(name)` for each, which dispatches to one of six `_run_*_step()` wrapper functions, each calling one `_fetch_*()` HTTP helper, each hitting exactly one backend endpoint. Every step's success/failure and elapsed time is recorded via `_record_step_run()` into `st.session_state["analysis_step_runs"]`, rendered as colored chips by `_render_journey_status()`.

### C2. Raw tab — "Raw Geometry"

**What you see:** four metric tiles (Solids / Faces / Edges / Vertices), a JSON block (bounding box, surface type counts, edge type counts, adjacency stats, warnings), and — if "Build display mesh" is checked — a rotatable 3D model of the part with no coloring (grey shaded).

**Say this:** "This is the exact B-Rep straight out of OpenCascade before any DfM logic runs. What you're rotating right now is a triangulated *view* of an exact NURBS/analytic solid — the analysis underneath never uses these triangles; it uses the original curved surfaces."

- Button: `Load STEP` → `_run_summary_step()` (`app.py:2937`) → `_fetch_summary()` (`app.py:2217`) → `GET /parts/{filename}/summary` → `@app.get("/parts/{filename}/summary")` (`main.py:579`) → backend function `part_summary()`.
- Backend function calls `step_loader.load_step(path)`. Internally: `STEPControl_Reader().ReadFile(str(path))` parses the STEP text into OCC's internal document model; `.NbRootsForTransfer()` counts top-level entities; `.TransferRoots()` converts STEP entities into native `TopoDS_Shape` topology; `.OneShape()` returns the single merged shape (if the file has multiple root shapes, OCC compounds them). This is the moment a text file becomes a live in-memory geometry object — no mesh, no approximation, exact curves.
- Then `_compute_bounding_box()` (`Bnd_Box` + `brepbndlib.Add`), `_extract_all_faces()` (walks `TopExp_Explorer(shape, TopAbs_FACE)`, for each face builds a `BRepAdaptor_Surface` to get surface type via `GetType()`, evaluates the UV-centroid normal via `GeomLProp_SLProps(surface, umid, vmid, 1, 1e-9)` — the "1,1" means "first derivative order," which OCC needs to compute a normal from cross-product of tangent vectors — and flips the normal if `face.Orientation() == TopAbs_REVERSED`), `_extract_edges_and_build_adjacency()` (hashes every edge's `TShape` pointer via `TopoDS_Shape.HashCode(2**31-1)` to deduplicate; an edge shared by exactly 2 faces becomes an adjacency-graph link; an edge appearing twice for the *same* face is a seam edge of a periodic surface like a cylinder, and is excluded from adjacency), `_extract_vertices()` (same hash-dedup trick).
- Objects created: one `FaceData` per B-Rep face (holds live `occ_face` handle — never JSON-serialised directly), one `EdgeData` per unique edge, one `VertexData` per unique point, three adjacency dicts (`face_adjacency`, `face_to_edges`, `edge_to_faces`), all bundled into one `PartGeometry`. This `PartGeometry` is created fresh on **every single API call** — the backend is stateless; nothing survives between HTTP requests except what's re-derived from the STEP file each time. (This is an important architectural honesty point — see Q&A.)
- If `include_mesh=true`: `visualize_raw.build_display_mesh(part)` calls `BRepMesh_IncrementalMesh(shape, linear_deflection, False, angular_deflection, True)` — OCC's own tessellator, walks each face's `BRep_Tool.Triangulation(face, location)`, flips triangle winding if the face is `TopAbs_REVERSED`, and tags every output triangle with the STEP `face_id` it came from. This is the **only place in the whole codebase where an approximation (triangles) is introduced** — every DfM algorithm upstream works on the exact B-Rep.
- JSON returned: `part.to_dict(include_faces=...)` + `display_mesh: {points, faces, face_ids, face_centers}`.
- Frontend render: `_show_mesh(display_mesh, color_key="draft_rgb")` → `_mesh_to_pyvista()` builds `pv.PolyData(points, faces_flat)` (or, on macOS, `_show_mesh_plotly()` builds a `plotly.graph_objects.Mesh3d`). Since no draft analysis has run yet, there's no `draft_rgb` key in the payload, so it falls back to flat grey.
- **Why this screen exists / why Bosch needs it:** it proves the file loaded correctly and gives the mold engineer an intuitive sanity check ("does this look like the part I expect?") before spending compute on the expensive DfM passes.

### C3. Draft tab — "Draft Analysis"

**What you see:** a color legend (green=Good, yellow=Marginal, red=Bad, grey=Skipped), quality-indicator chips (Draft risk, Bad area %, Suggestions count), four metric tiles (Good/Marginal/Bad face counts + area %, Severity), the colored 3D model, a list of plain-English correction suggestions, and expandable raw JSON.

**Say this:** "Green means this wall already has enough taper to release from the mold. Red means it's within a hair of vertical — that face will drag against the mold wall on ejection and either scratch the part or snap it. This is the exact same visual language SolidWorks' Draft Analysis tool gives a mold designer, except we compute the angle from the exact B-Rep surface math, not a mesh approximation."

- Button: `Run Draft` → `_fetch_draft()` (`app.py:2236`) → `GET /parts/{filename}/draft?dx&dy&dz` → `part_draft()` (`main.py:609`).
- Backend calls `draft_analyzer.analyze_draft(part, pull_direction=(dx,dy,dz), mutate=True)`. For every face with `normal_valid=True`: `angle = asin(|n·d|)` in degrees (`FaceData.draft_angle_for_direction`, `geometry_models.py:348`) where `n` is the face's outward normal and `d` is the normalized pull vector — this is the exact SolidWorks DraftAnalysis convention. `_classify_draft()` buckets it: `≥1.5°` → "good", `≥0.5°` → "marginal" (config: `config.yaml: dfm.draft.good_threshold_deg/marginal_threshold_deg`), else "bad". `_mold_side()` also tags each face "positive" (cavity/upper half, `n·d>0.01`), "negative" (core/lower half, `n·d<-0.01`), or "parting" (near-zero). Area-weighted `_assess_severity()` maps bad-area fraction to none/minor/moderate/critical (0%/0–5%/5–20%/>20%).
- `_build_suggestions()` groups all bad/marginal faces by `(classification, surface_type, mold_side)` and emits Bosch-style text like *"[CRITICAL] Add +1.3° draft to 5 Cylinder faces (core side, ~142 mm²). Min angle: 0.21°. Neutral plane: parting line."* — this is templated text generation from the grouped data, not an LLM call.
- Object created: `DraftAnalysisResult` (immutable dataclass) — holds face-ID lists per bucket, area sums, severity, and a list of `DraftSuggestion` objects. **Side effect:** because `mutate=True` here, every `FaceData.draft_angle_deg` / `.draft_classification` on the live `PartGeometry` is overwritten — this is why later screens that reuse the same `part` object (within one request) see draft results already populated.
- Mesh coloring: backend builds `mesh_payload["draft_rgb"]` by mapping each triangle's `face_id` to its classification color (`main.py:647-662`): good=`[0,0.85,0.3]`, marginal=`[1,0.85,0]`, bad=`[0.95,0.15,0.1]`, skipped=grey. Frontend just plots those RGB triples per-triangle via `plotter.add_mesh(poly, scalars="draft_rgb", rgb=True)`.
- **Why Bosch needs it:** draft is the single highest-frequency mold defect cause (sticking, scuffing, ejector-pin damage) and is the *first* thing every commercial DfM tool checks — this screen is table stakes for credibility with mold engineers.

### C4. Undercuts tab — "Undercut Detection"

**What you see:** legend (Boolean-confirmed critical/high=bright red, medium=orange, low/minor=amber, proxy-only=pale yellow, parting/accessible=grey), a "Show only high-confidence undercuts" toggle, quality chips (Undercut state, Critical count, Moderate count, Boolean refine yes/no, High-confidence actions), 4 metrics (Undercut Faces, Undercut Features, Undercut Area %, Parting Faces), a "Mold Action Rationale" table, a "Recognized Features" table, colored 3D overlay (optionally with translucent Boolean-interference volumes), and raw JSON.

**Say this:** "Draft tells you a wall is too vertical. Undercuts tell you something worse — this face is physically blocked by other material and *cannot* be reached by a straight mold pull in this direction at all, no matter how much draft you add. That distinction is why undercuts get a 'side action' recommendation (a slide or lifter) instead of just 'add more taper.'"

- Button: `Detect Undercuts` → `GET /parts/{filename}/undercuts` → `part_undercuts()` (`main.py:674`) → `undercut_detector.detect_undercuts(part, direction, boolean_refine=True, max_boolean_faces=120)`.
- **Stage 1 — fast proxy filter (always runs):** re-runs `analyze_draft` for the given direction; every valid face with `draft_angle_deg < marginal_threshold_deg (0.5°)` is provisionally flagged `proxy_undercut`. Faces where `|n·d| ≤ 0.01` are separately tagged `parting`. This is a cheap O(faces) pass — no Boolean geometry yet.
- **Stage 2 — swept-face Boolean refinement (optional, on by default, capped at `max_boolean_faces`):** for each candidate face, `_rank_boolean_candidate_faces()` prioritizes which faces are worth the expensive check; `_swept_face_interference_volume()` (`undercut_detector.py:2656`) does the actual OCC work:
  1. `_face_access_direction()` picks whether this face should be swept along `+pull_dir` or `-pull_dir` based on its signed normal side.
  2. Offsets the face slightly outward with `BRepBuilderAPI_Transform(face.occ_face, gp_Trsf(translation), True)` (avoids counting the face's own contact area as "interference").
  3. Sweeps the offset face into a solid prism using `BRepPrimAPI_MakePrism(moved_face, gp_Vec(direction * sweep_distance), True, True)` — `sweep_distance` is the part's bounding-box diagonal × 2 (config: `boolean_sweep_distance_factor`), i.e. "sweep this face all the way past the far end of the part."
  4. Intersects that swept volume with the whole part solid: `BRepAlgoAPI_Common(part.occ_shape, swept)` with a fuzzy tolerance (`SetFuzzyValue`) to survive near-coincident NURBS surfaces.
  5. If the intersection (`common.Shape()`) is non-null and has positive volume (via `brepgprop.VolumeProperties`), that's **material physically in the way** — a confirmed undercut, not just a guess. Retries with 3 increasing offset multipliers (`1.0, 5.0, 25.0`) if OCC throws (common with degenerate NURBS).
  6. This is a literal, conservative first implementation of Bassi et al. (2010)'s "swept accessibility" idea — the code's own docstring says exactly that.
- **Stage 3 — feature grouping:** `_group_undercut_faces_with_boolean_proximity()` groups adjacent undercut faces (plus faces whose Boolean regions are geometrically close/overlapping) into `UndercutFeature` objects — one feature = one physical pocket/protrusion, not one face. Each feature gets: `undercut_type` (internal/core-side vs external, via `_classify_undercut_type`), `severity` (critical/moderate/minor from depth × area), `release_direction` (estimated escape vector, via `_estimate_release_direction` / `_estimate_release_and_depth_from_boolean_geometry`), `geometric_feature_type` (hole/boss/rib-like classification from the Boolean region's bounding-box aspect ratio), and — the actionable output — `recommended_mold_action` (`side-action`, `lifter-or-collapsible-core-review`, `draft-redesign-review`, `manual-review`) computed by `_recommend_mold_action()` (`undercut_detector.py:1408`) with a full `action_confidence` score and human-readable `action_explanation`.
- Objects: `UndercutDetectionResult` (top-level, immutable) containing a list of `UndercutFeature` (immutable), each optionally holding live `boolean_intersection_shapes` (real OCC `TopoDS_Shape` regions, kept in memory only long enough to be triangulated for display).
- Mesh coloring + Boolean volumes: `_undercut_mesh_visual_payload()` (`main.py:341`) colors each triangle by whether its face is Boolean-confirmed (bright red/orange by severity), proxy-only (pale yellow), parting, or neutral. `_boolean_region_mesh_payloads()` (`main.py:410`) calls `visualize_raw.build_shape_display_mesh()` on each confirmed feature's real intersection solid to render it as a translucent extra mesh layer — this is literally showing the judge the exact 3D chunk of plastic that's physically trapped.
- **Why Bosch needs it:** undercuts are the #1 reason a "simple" 2-plate mold becomes an expensive slide/lifter tool. Automatically finding *and geometrically confirming* them (not just guessing from angle) is the highest-value output in the whole demo.

### C5. Direction tab — "Best Mold Direction"

**What you see:** a headline ("🎯 Best Mold Opening Direction: +Z, Vector, Score"), quality chips, a Before/After two-column comparison (bad draft %, undercut features, severity for the initial vs. optimal direction), a radio to switch the 3D overlay between Optimal Draft / Optimal Residual Undercuts / Initial Detected Undercuts, a "Top Candidates" table, and suggestions.

**Say this:** "This is the automation that replaces a mold engineer manually trying six, ten, twenty pull directions in SolidWorks by hand. The algorithm samples ~54 directions around the part, scores each one cheaply first, then spends the expensive Boolean checks only on the handful of directions that are actually close contenders."

- Button: `Find Best Direction` → `GET /parts/{filename}/direction` → `part_direction()` (`main.py:734`) → `direction_optimizer.optimize_mold_direction()`.
- `generate_candidate_directions()` (`direction_optimizer.py:418`) always includes the 6 principal axes (±X, ±Y, ±Z) first, then spherically samples the rest of the sphere at `angular_step_deg=15°` steps (config), capped at `max_candidates=54`.
- For every candidate: `analyze_draft(mutate=False)` + `detect_undercuts(mutate=False, boolean_refine=False)` — the *cheap* pass, no Boolean geometry — then `_score_candidate()` (`direction_optimizer.py:476`) computes a single weighted score: `1500×undercut_pct + 1000×bad_draft_pct + 100×marginal_pct + interference_weight×interference_volume_frac + ... + 0.25×non_principal_axis_penalty` (lower is better). The heavy weight on undercut% and a small tie-break penalty toward principal axes (simpler 2-plate tooling) are deliberate engineering choices baked into this formula.
- `_select_boolean_refinement_candidates()` (`direction_optimizer.py:513`) is the pruning gate — only candidates within a ratio/margin of the best cheap score, plus "low risk" candidates, plus guaranteed principal-axis survivors, plus near-ties, get promoted to expensive Boolean refinement (default cap: 5, config `boolean_refine_top_candidates`). This whole gate is returned to the API as a `BooleanPruningSummary` so the judge can literally see *why* a candidate was or wasn't Boolean-checked.
- The winning direction becomes `part.optimal_pull_direction`; `analyze_draft(mutate=True)` and `detect_undercuts(mutate=True)` are re-run on it so the live `PartGeometry` reflects the final chosen state — this is what Parting Line and Core/Cavity read by default afterward.
- Objects: `DirectionOptimizationResult` (best direction/score, initial vs optimal `DraftAnalysisResult`/`UndercutDetectionResult`, list of `DirectionCandidateResult` per sampled direction, a `BooleanPruningSummary`, plus a same-request `direction_undercut_cache`/`boolean_volume_cache` so a direction's expensive Boolean result is never recomputed twice within one call).
- Before/After UI directly diffs `initial_draft`/`initial_undercuts` (computed on whatever direction the sidebar XYZ boxes held) against `optimal_draft`/`optimal_undercuts` (the winner) — this Before/After framing is the single most persuasive visual in the whole demo for a non-technical judge.
- **Why Bosch needs it:** picking the mold-opening direction is one of the first and most consequential decisions in tool design — get it wrong and every downstream draft/undercut/parting-line decision inherits the mistake. Automating the search directly saves senior mold-design time.

### C6. Parting Line tab — "Main Parting Line"

**What you see:** readiness chips (Readiness, Report use Yes/No, Manual review Yes/No, Curve quality, Undercut conflict, Raw wire conflict, Initial major), a color legend (orange=raw wire, blue=refined curve), status banners (success/info/warning/error depending on readiness), 5 metrics (Readiness, Selected Edges, Refined Points, Quality, Undercut Conflict), graph-cleanup evidence table, undercut-conflict evidence table, curve-overlay metrics, the 3D model with the parting curve drawn on top, and a "Candidate Components" table.

**Say this:** "This is the line where the mold physically splits into two halves. Get this line wrong and the part either can't be ejected cleanly or leaves a visible flash line in the wrong place on a customer-facing surface. What you're seeing is a first-pass, not the final production algorithm — I want to be upfront about that."

- Button: `Detect Parting Line` → `GET /parts/{filename}/parting-line?use_optimal_direction=true` → `part_parting_line()` (`main.py:810`) → by default first re-runs `optimize_mold_direction()` (so this tab implicitly depends on Direction having already found the best pull vector) then `parting_line.detect_parting_line_candidates()`.
- `_classify_edge()` (`parting_line.py:541`) is the Nee (1998)-inspired core rule: for a manifold edge with exactly 2 adjacent faces, compute `signed_dot = n·d` for each adjacent face. If one is `>+0.01` and the other `<-0.01` (config `dot_tolerance`), the edge is a **silhouette** edge — literally the boundary where "the mold pulls away in this direction" flips sign across the edge. Near-zero-on-either-side edges become weaker `near_parting` candidates; boundary (1-face) edges near the parting plane become `boundary` candidates; 3+-face edges are `non_manifold` (flagged for review, geometry error smell).
- `_candidate_components()` groups all candidate edges into connected components (a simple graph-traversal over shared endpoint coordinates, tolerance-snapped). `_build_ordered_wire()` walks each component into a single ordered polyline (handles branches/gaps explicitly and records them). `_apply_wire_assessments()` scores each candidate wire's projected-loop quality (`_wire_projection`/`_projection_quality` — does it look like a closed, non-self-intersecting loop when flattened onto the plane perpendicular to the pull direction?) and undercut conflict (`_wire_undercut_conflict` — does the candidate line pass suspiciously close to a major undercut feature found in Module 4? If so, that's a red flag that this isn't really the parting line). `_select_projected_wire()` picks the single best-scoring component.
- `_refine_selected_wire()` (`parting_line.py:2159`) is the Hou (2018)-inspired step: a weighted graph cleanup (`_trace_best_weighted_path`) that removes branch/noise edges, then `_chaikin_smooth()` (Chaikin's corner-cutting subdivision algorithm, `smoothing_iterations=8` by default) smooths the polyline for display, then resamples it to a target point density (`display_resample_min_points=96`, capped at `max_refined_display_points=32000`).
- `_parting_line_readiness()` / `_parting_line_diagnostic_gate()` turn all of the above into human gates: `can_use_for_report`, `requires_manual_review`, `blocks_core_cavity` — booleans the frontend directly renders as Yes/No metrics, so the tool is explicitly telling the presenter "trust this" or "don't."
- Objects: `PartingLineResult` (top-level), containing `PartingLineEdgeCandidate` (per edge), `PartingLineComponent` (per connected group), `PartingLineWire` (ordered polyline + assessments), `PartingLineRefinement` (the final smoothed curve + `PartingLineGraphCleanup` evidence), `PartingLineReadiness`/`PartingLineDiagnosticGate`. **Side effect:** `part.parting_edge_ids` / `part.parting_wire_points` are written onto the live `PartGeometry`.
- Rendering: `_parting_line_paths_payload()` (`main.py:492`) returns both the raw wire (orange, `#ffa500`) and the refined curve (blue, `#00BFFF`) as separate point-array "line paths"; frontend `_show_mesh(..., line_paths=[...])` draws them as tube-rendered polylines on top of the (now uncolored, `parting_rgb`=flat grey) 3D model.
- **Why Bosch needs it & honesty note:** README/onboarding.md still call this "in progress"/"planned." The code shows a real Nee-style silhouette detector plus a real Hou-style graph-cleanup and smoothing pass — genuinely more built than older docs suggest — but it is candidate-level, not the fully regularized global-optimization parting curve a production tool would ship. Say exactly that.

### C7. Core/Cavity tab — "Core/Cavity Classification"

**What you see:** a 3-item color legend (green=Cavity/upper half, blue=Core/lower half, yellow=Parting zone), 3 metrics (Cavity Faces, Core Faces, Parting Faces with %), the pull direction used, a caption, the colored 3D model, and raw JSON.

**Say this — and be exact about scope here, this is the one screen where being honest matters most:** "This is telling you which faces belong to the upper mold half versus the lower mold half. What it is *not* doing yet is actually cutting the solid into two separate physical bodies with a Boolean split — that's the Level 2 deliverable. Today it's a per-face classification using nothing more than the sign of the dot product between each face's normal and the pull direction."

- Button: `Classify Core/Cavity` → `GET /parts/{filename}/core-cavity?use_optimal_direction=true&threshold=0.05` → `part_core_cavity()` (`main.py:916`) → `core_cavity.classify_core_cavity()` (`core_cavity.py:78`, **139 lines total — the smallest module in the pipeline**).
- Algorithm, in full: for every valid face, `sdot = n·d`. `sdot > 0.05` → `"cavity"` (upper mold half — the outward normal points *with* the pull, i.e. away from where the core retreats). `sdot < -0.05` → `"core"` (lower half). Otherwise → `"parting"` (near-perpendicular — these are the walls that actually run along the parting line). `threshold=0.05` ≈ 2.9° from perpendicular (config: sidebar hardcodes `threshold=0.05` in `_fetch_core_cavity`, `app.py:2315`).
- Object: `CoreCavityResult` (immutable) — three face-ID lists + area sums + the threshold used. `mutate=True` writes `face.cavity_or_core` onto `PartGeometry`.
- **Correction versus older docs:** `README.md`'s architecture diagram and `onboarding.md` both still describe `core_cavity.py` as "Planned: Level 2 core/cavity split" and list it with no working code. The live code is a real, wired, tested, UI-integrated Level 1 face classifier — it is genuinely implemented, just scoped narrower (face labels, not a physically split solid) than the name "core/cavity extraction" implies in the original problem statement. State this distinction explicitly if asked — it is exactly the kind of gap a sharp Bosch reviewer will probe for.

### C8. "📋 Full DfM Summary Report" (bottom of the page)

**What you see:** an expandable report block that only appears once Load STEP, Draft, Undercuts, and Direction have all run — sectioned Markdown text: Part Geometry, Draft Analysis Results, Undercut Detection Results, Mold Direction Optimization, Parting Line, Core/Cavity Split, an explicit **"Limitations (Honest)"** section, and Action Items.

**Say this:** "This is the closest thing to the final PDF DFM report a mold engineer would actually file. It's built entirely from the same JSON payloads you've already seen in the tabs above — no new computation happens here, it's a formatting/aggregation layer, `_render_dfm_summary_report()`." Read the Limitations section out loud if a judge is skeptical — it's baked into the product itself, not something you're improvising: *"Parting line is a candidate-level silhouette detection... Core/cavity is face classification only — full Boolean solid split is Level 2. LangChain AI agent and automated PDF export are planned for Level 2."*

---

## PART D — Object lifecycle reference

| Object | Created where | Why it exists | Owner | Consumed by | Destroyed when |
|---|---|---|---|---|---|
| `TopoDS_Shape` (OCC) | `step_loader.load_step()`, `STEPControl_Reader().OneShape()` | The single exact in-memory B-Rep solid | `PartGeometry.occ_shape` | Every Boolean/sweep/triangulation call in every downstream module | End of the HTTP request (Python GC) — never persisted between requests |
| `FaceData` | `step_loader._extract_all_faces()` | One structured record per B-Rep face; the "row" every algorithm iterates | `PartGeometry.faces` list | draft_analyzer (writes `.draft_angle_deg`), undercut_detector (writes `.is_undercut`), core_cavity (writes `.cavity_or_core`), visualize_raw (reads `.centroid` as triangulation fallback) | Same request lifetime as `PartGeometry` |
| `EdgeData` | `step_loader._extract_edges_and_build_adjacency()` | One record per unique topological edge + which faces touch it | `PartGeometry.edges` | parting_line (`.is_silhouette`, `.is_parting_edge`), undercut/draft indirectly via face adjacency | Same request lifetime |
| `PartGeometry` | `step_loader.load_step()` return value | THE shared pipeline object; every module takes it as first arg and mutates it in place | Local variable inside each FastAPI route function | draft/direction/undercut/parting/core-cavity/visualize modules, then `part.to_dict()` for JSON | Falls out of scope at the end of each route function — **stateless backend, reloaded from disk on every single API call, even within the same "journey"** |
| `DraftAnalysisResult` | `draft_analyzer.analyze_draft()` return value | Immutable snapshot of one draft pass (needed because the pipeline runs draft analysis *multiple times* — initial +Z, per-candidate, final optimal — and needs to keep each snapshot distinct even though `FaceData` itself only holds the *latest* mutation) | Route function locally, then `DirectionOptimizationResult.initial_draft`/`.optimal_draft` | API JSON response, frontend Before/After comparison | End of request |
| `UndercutFeature` / `UndercutDetectionResult` | `undercut_detector.detect_undercuts()` | Feature-level (not face-level) undercut record with mold-action recommendation and, optionally, a live Boolean intersection shape | Route function locally; features referenced by direction_optimizer's cache | `_boolean_region_mesh_payloads()` triangulates `.boolean_intersection_shapes` for the 3D overlay, then the shape is discarded | End of request (OCC shape freed with it) |
| `DirectionOptimizationResult` | `direction_optimizer.optimize_mold_direction()` | Full record of the direction search: candidates, scores, pruning rationale, before/after draft+undercut results | Route function locally | Frontend Direction tab, and re-used inside the same request by the Parting Line / Core-Cavity endpoints (which call `optimize_mold_direction()` again themselves — **note: each endpoint re-runs the direction search independently; results are not cached across endpoints**, only within one `optimize_mold_direction()` call via its internal `direction_undercut_cache`) | End of request |
| `PartingLineResult` | `parting_line.detect_parting_line_candidates()` | Full silhouette/wire/refinement/readiness record | Route function locally | Frontend Parting Line tab | End of request |
| `CoreCavityResult` | `core_cavity.classify_core_cavity()` | Per-face cavity/core/parting classification | Route function locally | Frontend Core/Cavity tab | End of request |
| `RawMeshData` | `visualize_raw.build_display_mesh()` / `build_shape_display_mesh()` | Display-only triangulation, tagged per-triangle with source `face_id` | Route function locally | `to_payload(include_geometry=True)` → JSON → frontend `_mesh_to_pyvista()`/Plotly `Mesh3d` | End of request |
| `pv.PolyData` / Plotly `Mesh3d` | Frontend `_mesh_to_pyvista()` / `_show_mesh_plotly()` | Renderable 3D object in the browser's rendering stack | Streamlit script-local variable | `plotter.add_mesh()` → off-screen PNG (`stpyvista`) or a live WebGL figure (Plotly) | Discarded on next Streamlit rerun |

**The single most important architectural fact to say out loud when asked about performance/scalability:** *the backend is completely stateless — there is no server-side session or cache of a loaded part between HTTP calls.* Every single endpoint call (`/summary`, `/draft`, `/undercuts`, `/direction`, `/parting-line`, `/core-cavity`) independently calls `load_step(path)` from scratch and re-parses the STEP file, re-extracts every face/edge/vertex, and re-runs whatever upstream analysis it depends on (e.g. `/parting-line` internally re-runs the *entire* direction optimization search before it can even start). This is simple and correct but means clicking through all six tabs on a large part re-does STEP parsing six times and re-does direction optimization three times (Direction, Parting Line, Core/Cavity). That is a real, honest performance limitation — have the answer ready.

---

## PART E — Presentation script (natural narration, not documentation-reading)

**Setup line (before you touch anything):** "I'm going to run this exactly the way a mold engineer would use it, in the order the tool itself guides you through — the sidebar literally has an 'AI Mold Engineer Journey' panel that tells you what to run next."

**1. Open browser → point at "Backend connected."**
What appears: green success banner, STEP file dropdown with `Part1.stp`.
Say: "Two containers are running — a FastAPI backend doing all the OpenCascade geometry work, and this Streamlit frontend that never touches the CAD kernel directly. It just talks JSON over HTTP to the backend, the same way any web client would."
Internally: `GET /health` returned `{"status":"healthy",...}`; `GET /parts` listed `data/parts/Part1.stp`.
Why it matters: proves this isn't a scripted screenshot — the backend is alive and the file is real.
Business value: this is the exact separation Bosch would need to eventually swap the frontend for a CATIA/NX plugin without touching the geometry engine at all.

**2. Click "Load STEP."**
What appears: Solids/Faces/Edges/Vertices tiles populate; a grey 3D part appears, rotatable.
Say: "That STEP file just got parsed by the actual OpenCascade kernel — the same C++ geometry engine underneath CATIA and FreeCAD. What you're looking at right now is triangulated only for display; every measurement this tool makes uses the exact curved surfaces, not these triangles."
Internally: `STEPControl_Reader` → `TopoDS_Shape` → face/edge/vertex extraction → adjacency graph → `BRepMesh_IncrementalMesh` triangulation for the viewer.
Why: establishes ground truth topology before any DfM logic runs.
Business value: replaces the "open in CATIA and eyeball it" step mold engineers do today — now it's an API call.

**3. Click "Run Draft."**
What appears: model turns green/yellow/red; metric tiles show face counts and area %; suggestion text appears.
Say: "Red means this wall is basically vertical relative to how the mold opens — it'll drag and scuff on ejection. The tool doesn't just flag it, it tells you which faces, how much area, and exactly how many degrees of taper to add."
Internally: `asin(|normal · pull_direction|)` per face, area-weighted severity, templated correction suggestions.
Why: draft is the #1 most common mold defect cause; every commercial DfM tool leads with this check.
Business value: turns a manual visual inspection into a quantified, prioritized punch-list.

**4. Click "Detect Undercuts."**
What appears: some faces turn bright red/orange with translucent 3D "interference volumes" floating over the model; a Mold Action Rationale table appears.
Say: "This is a level up from draft. These faces aren't just steep — they're physically trapped behind other material. The tool actually swept each suspicious face through the part and ran a real Boolean intersection to *confirm* material is in the way, not just guess from the angle. That orange blob is the literal geometry that would rip if we tried to pull the mold apart right now."
Internally: fast draft-based proxy filter → `BRepPrimAPI_MakePrism` sweep → `BRepAlgoAPI_Common` Boolean intersection → feature grouping → mold-action recommendation (side-action / lifter / redesign).
Why: undercuts, not draft, are what actually force expensive slide/lifter tooling.
Business value: this is the single highest-value automation in the demo — geometrically *proving* a defect, not just flagging an angle.

**5. Click "Find Best Direction."**
What appears: a "Best Mold Opening Direction" headline with a vector and score; a Before/After split showing bad-draft% and undercut-feature-count dropping.
Say: "Instead of me guessing a pull direction, the tool just tried about fifty of them, scored each one cheaply first, and only ran the expensive Boolean checks on the handful that were actually close contenders. This before/after is the same part — same STEP file — just a smarter choice of which way the mold opens."
Internally: candidate generation (principal axes + spherical sampling) → cheap draft/undercut scoring → smart-pruned Boolean refinement on survivors → best-scoring direction selected.
Why: pull direction is decided first and every other DfM decision inherits it.
Business value: replaces hours of manual trial-and-error in SolidWorks/NX with one automated pass.

**6. Click "Detect Parting Line."**
What appears: an orange raw wire and a smoother blue curve traced around the part; readiness/quality chips.
Say: "This is where the mold physically splits into two halves. I want to be upfront — this is a first-pass candidate detector, not the final production-grade algorithm. It finds edges where the part's surface normals flip across the pull direction — that's literally where the silhouette of the part changes — connects them into a loop, and then cleans up the noisy raw result into this smoother curve."
Internally: per-edge silhouette classification via adjacent-face normal sign flip → connected-component grouping → ordered-wire construction → graph-based cleanup → Chaikin curve smoothing.
Why: wrong parting line = visible flash lines on customer-facing surfaces or a part that won't eject cleanly.
Business value: gives a starting candidate a mold designer can review and correct, instead of tracing it by hand.

**7. Click "Classify Core/Cavity."**
What appears: green (cavity/upper), blue (core/lower), and yellow (parting) coloring across the part.
Say: "Green faces belong to the top mold half, blue to the bottom. This is the geometric classification only — I want to be precise about that — it's not yet cutting the solid into two separate physical bodies. That full Boolean split is the next milestone."
Internally: `sign(face_normal · pull_direction)` thresholded at ±0.05.
Why: sets up the tooling split every mold design needs.
Business value: automatically pre-sorts faces for the toolmaker instead of manual face-picking in CAD.

**8. Scroll to the DfM Summary Report.**
Say: "And this pulls everything you just saw into one report, including a section that explicitly lists what's a candidate-level result versus production-ready — because a DfM tool that overstates its own confidence is worse than no tool at all."

---

## PART F — Bosch Judge Q&A

**Project motivation / architecture**

Q: Why does Bosch need this instead of just using SolidWorks/CATIA/NX DfM modules? A: Those tools require a licensed seat and manual operation per part; this is a headless, API-driven engine that could sit in an automated CI-style pipeline (upload STEP → get a DfM report) without a human opening a CAD session, and it's built to be extended with an LLM orchestration layer for natural-language DfM Q&A — that layer isn't built yet (`backend/agent/` is empty), but the geometry engine underneath it is designed with a stable dataclass interface (`PartGeometry`) specifically so that layer can be added without touching geometry code.

Q: Why split into backend (FastAPI) and frontend (Streamlit) instead of one process? A: Separation of concerns and reusability — the geometry engine is a pure Python/OCC library behind a REST API; any client (Streamlit today, a CATIA plugin or CI pipeline tomorrow) can call the same endpoints. It also lets the two be developed, tested, and scaled independently.

Q: Is the backend stateful — does it remember the part between tabs? A: No. Confirmed from the code: every endpoint calls `load_step(path)` from scratch. There is no server-side session, no shared cache of a parsed `PartGeometry` across HTTP requests. This is a genuine simplicity vs. performance trade-off, not an oversight — see Performance below.

**Technology choices**

Q: Why pythonOCC/OpenCascade instead of Trimesh, Open3D, or a mesh-based library? A: STEP files are exact B-Rep (NURBS/analytic surfaces), not triangle meshes. Mesh libraries would force an approximation before any geometry math, which is unacceptable when parting-line placement needs millimeter accuracy. Only a real B-Rep kernel (OpenCascade, Parasolid, ACIS) can parse STEP without lossy conversion — this is stated directly in `step_loader.py`'s module docstring.

Q: Why CadQuery in addition to pythonOCC? A: `step_loader.py` loads the file independently through CadQuery as well (`_load_cadquery_part`), stored as `PartGeometry.cadquery_shape`, purely as a convenience handle for future higher-level CAD operations (CadQuery wraps OCC — actually OCP, a separate binding — with a friendlier scripting API). It is not used by any current analysis module; pythonOCC's `TopoDS_Shape` remains the actual source of truth, because pythonOCC and CadQuery use different underlying OCC Python bindings and their shape objects cannot be safely cross-cast.

Q: Why Streamlit instead of React/Vue? A: Fast to build a data-science-style interactive UI in pure Python, with native support for widgets/dataframes/JSON viewers, at the cost of full-script-rerun-per-interaction and less control over layout than a real frontend framework. Session state (`st.session_state`) is Streamlit's workaround for the rerun model and is used extensively here to persist each analysis step's result across reruns.

Q: Why does the 3D viewer switch between PyVista and Plotly? A: On macOS, VTK's Cocoa windowing backend crashes when driven from Streamlit's non-main worker thread; the code detects `sys.platform == "darwin"` (`_show_mesh`, `app.py:1106`) and renders with Plotly's `Mesh3d` instead (runs in-browser via WebGL, no native windowing at all). On Linux/Docker, PyVista off-screen rendering + `stpyvista` works because the container runs under `xvfb-run` (virtual framebuffer), so the “real” 3D path (edges, lighting, translucent regions, tube-rendered lines) is used there.

Q: Why Micromamba/Conda instead of pip/venv? A: `pythonocc-core` ships as compiled C++ bindings that are only reliably distributed via conda-forge; pip builds are described in the code itself as "unreliable." Micromamba is chosen over full conda specifically because it's a tiny, dependency-free binary that installs locally into the repo (`.micromamba/`), avoiding any need for judges/CI machines to have conda pre-installed or admin rights.

Q: Why YAML config (`config.yaml`) instead of hardcoded constants? A: Every DfM threshold (draft angles, Boolean offset/fuzzy tolerances, direction search sampling density, parting-line smoothing) is loaded once at import time by `backend/config.py::load_settings()` into frozen (`@dataclass(frozen=True)`) settings objects. Frozen means immutable after construction — prevents accidental mutation mid-analysis — while still letting Bosch engineers retune thresholds without a code change or rebuild (the Docker Compose file even mounts `config.yaml` read-only into both containers for live tuning without a rebuild).

**OpenCascade / STEP / B-Rep / Topology**

Q: What is B-Rep and why does it matter here? A: Boundary Representation — a solid is defined by its exact bounding surfaces (planes, cylinders, cones, NURBS, etc.) and the topological graph connecting faces/edges/vertices, rather than a discretized mesh or a voxel grid. It preserves exact curvature and dimension, which matters directly for draft-angle math (`asin` of an exact dot product) and Boolean interference volumes (exact, not mesh-approximated).

Q: What is NURBS and where does it show up? A: Non-Uniform Rational B-Splines — the general free-form curve/surface representation OCC uses for anything that isn't a plane/cylinder/cone/sphere/torus. Reported directly in the Raw tab's `surface_type_counts` as `"BSpline/NURBS"`. `GeomLProp_SLProps` evaluates normals on any of these uniformly, analytic or NURBS, via first-derivative surface evaluation.

Q: How does the loader avoid double-counting shared edges/vertices? A: `TopoDS_Shape.HashCode(2**31-1)` hashes each entity's underlying `TShape` pointer; entities sharing the same hash are the same physical edge/vertex and get one `EdgeData`/`VertexData` record with an accumulated list of adjacent face IDs (see `step_loader._extract_edges_and_build_adjacency`). Collision probability for a typical ~5000-edge part is estimated in the code's own comments at ≈6×10⁻⁶ — not zero, but negligible, and a non-manifold-edge warning is logged if it ever manifests as an unexpected 3+-face edge.

Q: What's a seam edge and why is it handled specially? A: The single vertical seam line on a full cylinder/sphere/torus where OCC's periodic UV parameterization wraps around — it appears twice in one face's wire (forward + reversed orientation) but hashes to the same edge. If not special-cased, it would look like a shared boundary between two different faces and corrupt the adjacency graph; the loader detects a repeated face-id within one face's raw edge list and marks it `is_seam=True`, excluding it from adjacency.

Q: What OCC classes actually do the geometric heavy lifting? A: `STEPControl_Reader` (file parsing), `TopExp_Explorer` (topology traversal), `BRepAdaptor_Surface`/`BRepAdaptor_Curve` (surface/curve type + parametrization), `GeomLProp_SLProps` (normal/derivative evaluation), `BRep_Tool` (raw geometry access — points, triangulation), `Bnd_Box`/`brepbndlib` (bounding box), `GProp_GProps`/`brepgprop` (exact area/length/volume via surface/line/volume integration), `BRepBuilderAPI_Transform` (translation for Boolean offset), `BRepPrimAPI_MakePrism` (sweep-to-solid), `BRepAlgoAPI_Common` (Boolean intersection), `BRepMesh_IncrementalMesh` (display triangulation only).

**DFM concepts**

Q: How exactly is draft angle computed and why `asin`? A: `draft_angle_deg = degrees(asin(|normal · pull_direction|))`. When the face normal is perpendicular to the pull (a vertical wall) the dot product is 0 → `asin(0)=0°` → worst case. When the normal is parallel to the pull (a horizontal top/bottom face) the dot product is ±1 → `asin(1)=90°` → best case, matching the SolidWorks Draft Analysis convention exactly.

Q: How is an undercut different from a bad-draft face, mechanically? A: Bad draft is a *taper* problem — the wall is too close to vertical but nothing physically blocks it; fixable by adding more taper. An undercut is a *reachability* problem — some other part geometry sits in the straight-line path the mold half would need to retract along; no amount of added taper fixes it, only a side-action (slide/lifter) or redesign does. The code encodes this distinction structurally: draft is a per-face angle number; undercuts require an actual swept-Boolean interference check against the whole solid.

Q: How is the parting line actually detected? A: Nee (1998)'s core insight, implemented directly: an edge is a silhouette candidate exactly where its two adjacent faces' normals have opposite-signed dot products against the pull direction — i.e., where the visible outline of the part (as seen looking along the pull direction) actually is. Near-zero-dot edges and boundary edges near the parting plane are retained as weaker secondary candidates because real parts often place the actual parting curve on near-vertical transition faces, not perfect silhouette edges.

Q: How is core vs cavity decided? A: Purely by the sign of `face_normal · pull_direction` against a small threshold (±0.05, ≈2.9° from perpendicular): positive → cavity (upper half, in the direction the top mold plate retreats), negative → core (lower half), near-zero → parting zone. This is face-level labeling only, not a Boolean split into two separate solids.

Q: What algorithm/paper backs each module, and how faithfully? A: Bassi et al. (2010) → direction_optimizer's surface-accessibility scoring + swept-Boolean refinement (implemented as a conservative first pass, not the full regularized volumetric-decomposition algorithm from the paper). Sangolli et al. (2021) → undercut_detector's feature grouping/classification/action recommendation (implemented, STEP-native adaptation). Nee et al. (1998) → parting_line's silhouette-edge detection + loop construction (implemented for the core rule; full automatic parting-*surface* generation is not). Hou et al. (2018) → parting_line's graph-weighted cleanup + curve smoothing (a first-pass, deterministic approximation of the paper's global optimization, explicitly noted as such in the module docstring).

**Boolean operations / mesh / performance**

Q: Why is Boolean refinement only run on a subset of faces/directions, not everything? A: Cost — `BRepAlgoAPI_Common` on a full solid is expensive and can fail/retry on difficult NURBS topology. The pipeline always runs a cheap proxy (draft-angle-based) filter first, then gates expensive Boolean checks behind explicit, tunable thresholds (`max_boolean_faces` per undercut call, `boolean_refine_top_candidates`/pruning-ratio gates per direction-search call) — all visible in the API response as a `BooleanPruningSummary`/`boolean_performance` block so the trade-off is never hidden.

Q: What happens when a Boolean operation fails? A: `_swept_face_interference_volume` retries with 3 increasing offset multipliers (`1.0, 5.0, 25.0` × base epsilon) before giving up; on total failure it raises a structured `BooleanOperationError` carrying a `BooleanFailureInfo` (failure class, attempts, last error). The caller (`detect_undercuts`) conservatively **keeps** the proxy-based undercut classification for that face rather than silently dropping a possible defect — "fail safe toward flagging an issue" is a deliberate design choice, documented directly in the code comments around line 3137-3144.

Q: How is the display mesh different from the analysis geometry, and does mesh quality affect DfM results? A: `BRepMesh_IncrementalMesh` (in `visualize_raw.py`) produces triangles *only* for the 3D viewer; every DfM computation (draft angle, undercut Boolean, parting silhouette, core/cavity) works on the original `TopoDS_Shape` B-Rep surfaces and is completely unaffected by the mesh-quality slider in the sidebar. That slider only changes how smooth the model *looks*, never the underlying numbers.

Q: What's the actual performance/scalability profile? A: Every endpoint reloads and fully re-parses the STEP file from scratch (no caching across requests) — confirmed directly in `backend/api/main.py`, every route calls `load_step(path)` independently. `/parting-line` and `/core-cavity` each additionally re-run the *entire* direction-optimization search internally (`optimize_mold_direction()`) if `use_optimal_direction=true`, meaning a full six-tab click-through on one part re-parses STEP six times and re-runs direction search three times. This is a genuine, known scalability limitation for large assemblies or high-frequency API use — the honest answer, not a deflection.

Q: What about memory? A: `TopoDS_Shape` and any live `TopoDS_Face`/`TopoDS_Edge` handles are kept only as long as one HTTP request's Python call stack is alive; Python's garbage collector reclaims them once the route function returns. Live Boolean-intersection shapes (`UndercutFeature.boolean_intersection_shapes`) are held only long enough to be triangulated into a JSON-safe mesh payload before the request ends — no persistent in-memory geometry cache exists server-side.

**Limitations / future work (say plainly, do not hedge)**

- `backend/agent/dfm_agent.py` and `backend/agent/tools.py` are **empty files (0 bytes)** — the LangChain/LLM orchestration and natural-language DfM report generation described in the original problem statement is not built. The "AI Mold Engineer Journey" in the sidebar is a deterministic, scripted step sequencer, not an LLM agent.
- `core_cavity.py` performs face-level classification only; it does not Boolean-split the solid into two separate manufacturable bodies (that is the actual Level 2 "Core and Cavity Extraction" deliverable per the evaluation matrix in `README.md`).
- `parting_line.py` produces a candidate silhouette curve with graph-cleanup and smoothing, not the fully regularized, globally-optimized production parting curve Hou (2018) describes.
- No PDF export exists; the "DfM Summary Report" is a Markdown block rendered inside the Streamlit page, not a generated file artifact.
- The backend is stateless with no cross-request caching, which caps practical performance for large assemblies or rapid iterative use.
- Direction search, by construction, only samples ~54 discrete directions at a configurable angular step (default 15°) plus the 6 principal axes — it is a sampled search, not a continuous global optimum, and Boolean refinement only touches a pruned subset of those samples.

---

## PART G — Cheat sheet (max density)

**Backend endpoints** (`backend/api/main.py`), all under `GET /parts/{filename}/...`:
- `/summary` → `part_summary()` → `load_step` only. Returns topology counts + optional mesh.
- `/draft?dx&dy&dz` → `part_draft()` → `analyze_draft(mutate=True)`. Returns `DraftAnalysisResult` + `draft_rgb` mesh overlay.
- `/undercuts?dx&dy&dz&boolean_refine&max_boolean_faces` → `part_undercuts()` → `detect_undercuts()`. Returns `UndercutDetectionResult` + optional Boolean-region meshes.
- `/direction?dx&dy&dz&angular_step_deg&max_candidates` → `part_direction()` → `optimize_mold_direction()`. Returns `DirectionOptimizationResult`.
- `/parting-line?use_optimal_direction&refine&smoothing_iterations` → `part_parting_line()` → (optionally) `optimize_mold_direction()` then `detect_parting_line_candidates()`. Returns `PartingLineResult` + raw/refined curve paths.
- `/core-cavity?use_optimal_direction&threshold` → `part_core_cavity()` → (optionally) `optimize_mold_direction()` then `classify_core_cavity()`. Returns `CoreCavityResult`.
- `/health`, `/parts` → filesystem checks only, no geometry.
- Errors: every exception path returns `{"status":"error","error":{code, message, operation, recovery_hint, details}}` via two global handlers (`_http_exception_handler`, `_unhandled_exception_handler`); codes: `invalid_filename`, `part_not_found`, `cad_runtime_missing` (OCC/CadQuery/PyVista import failed), `step_load_failed`, `invalid_input`, `analysis_failed`.

**Module → responsibility → key function → mutates → key OCC calls:**
| Module | Responsibility | Entry fn | Mutates on PartGeometry | Core OCC/algorithm |
|---|---|---|---|---|
| step_loader.py | STEP → PartGeometry | `load_step()` | creates the object | `STEPControl_Reader`, `TopExp_Explorer`, `BRepAdaptor_Surface`, `GeomLProp_SLProps`, `HashCode` dedup |
| draft_analyzer.py | angle + good/marginal/bad | `analyze_draft()` | `face.draft_angle_deg`, `.draft_classification` | `asin(|n·d|)` |
| direction_optimizer.py | best pull direction | `optimize_mold_direction()` | `part.optimal_pull_direction`, `.direction_score` | candidate sampling + weighted scoring + pruned Boolean refine |
| undercut_detector.py | reachability / undercuts | `detect_undercuts()` | `face.is_undercut`, `.undercut_depth_mm`, `.undercut_type` | `BRepPrimAPI_MakePrism` + `BRepAlgoAPI_Common` |
| parting_line.py | mold split curve | `detect_parting_line_candidates()` | `edge.is_silhouette`, `.is_parting_edge`; `part.parting_edge_ids/wire_points` | signed-normal sign-flip across edge + graph cleanup + Chaikin smoothing |
| core_cavity.py | face-level cavity/core label | `classify_core_cavity()` | `face.cavity_or_core` | `sign(n·d)` threshold ±0.05 |
| visualize_raw.py | display triangulation | `build_display_mesh()` | none (read-only adapter) | `BRepMesh_IncrementalMesh` |

**Config knobs (`config.yaml`) that matter in a demo:** `dfm.draft.good_threshold_deg=1.5`, `marginal_threshold_deg=0.5` (draft coloring cutoffs) · `dfm.direction_search.angular_step_deg=15`, `max_candidates=54` (search density/speed trade-off) · `dfm.direction_search.boolean_refine_top_candidates=5` (Boolean refinement cap) · `dfm.parting_line.dot_tolerance=0.01`, `smoothing_iterations=8` · `dfm.core_cavity` colors only (no threshold in yaml — threshold is a query param, default 0.05).

**Frontend session-state keys** (`app.py`): `summary_result`, `draft_result`, `undercut_result`, `direction_result`, `parting_line_result`, `core_cavity_result` — one per pipeline step, gate what each tab can render; `analysis_step_failures`, `analysis_step_runs` — journey diagnostics; resetting any sidebar control that changes `analysis_signature` (part, mesh flags, pull direction) wipes all of the above via `_reset_analysis_state()`.

**Platform branch to remember:** `sys.platform == "darwin"` → Plotly `Mesh3d` renderer (`_show_mesh_plotly`); everything else → PyVista off-screen + `stpyvista` (`_show_mesh`). Both are fed the same JSON mesh payload — only the rendering backend differs.

**One-sentence answer bank:**
- What replaces manual work? → Draft/undercut/direction/parting/core-cavity checks a mold engineer would do by eye in CATIA/SolidWorks/NX.
- What's not built? → The LLM agent layer (`backend/agent/*` empty), a true core/cavity Boolean solid split, full production parting-surface generation, PDF export.
- What's the exactness guarantee? → All DfM math runs on exact B-Rep surfaces via OCC; triangulation exists only at the display layer and never feeds back into analysis.
- What's the biggest honest limitation? → Stateless backend re-parses STEP and re-runs direction search on every relevant endpoint call — no caching across requests.
