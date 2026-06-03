from pathlib import Path

from fastapi import FastAPI, HTTPException, Query

from backend.geometry.draft_analyzer import analyze_draft
from backend.geometry.step_loader import STEPLoadError, load_step
from backend.geometry.visualize_raw import build_display_mesh

app = FastAPI(
    title="DfM Agent API"
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PARTS_DIR = PROJECT_ROOT / "data" / "parts"


@app.get("/")
def root():
    return {
        "message": "DfM backend running"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }


@app.get("/parts")
def list_parts():
    """List STEP files available for analysis."""
    files = sorted(
        p.name for p in PARTS_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in {".stp", ".step"}
    )
    return {
        "parts_dir": str(PARTS_DIR),
        "files": files,
    }


@app.get("/parts/{filename}/summary")
def part_summary(
    filename: str,
    include_faces: bool = Query(default=False),
    include_mesh: bool = Query(default=False),
    mesh_deflection: float = Query(default=0.5, gt=0.0),
):
    """
    Load a STEP file and return geometry summary data for frontend/agent use.

    `include_mesh=true` returns raw display mesh counts and face labels.  The
    full point/triangle arrays are intentionally not returned here yet; the
    Streamlit viewer will request/render them through a dedicated endpoint once
    we finish the visualization pipeline.
    """
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail="filename must not contain path separators")

    path = PARTS_DIR / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"STEP file not found: {safe_name}")

    try:
        part = load_step(path)
        payload = part.to_dict(include_faces=include_faces)
        if include_mesh:
            mesh = build_display_mesh(part, linear_deflection=mesh_deflection)
            payload["display_mesh"] = mesh.to_payload(include_geometry=False)
        return payload
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "CAD runtime dependency missing. Use the locked conda/Docker "
                f"environment. Details: {exc}"
            ),
        ) from exc
    except STEPLoadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/parts/{filename}/draft")
def part_draft(
    filename: str,
    dx: float = Query(default=0.0),
    dy: float = Query(default=0.0),
    dz: float = Query(default=1.0),
    include_faces: bool = Query(default=False),
    include_mesh: bool = Query(default=True),
    mesh_deflection: float = Query(default=0.5, gt=0.0),
):
    """
    Run draft analysis for a selected pull direction.

    Default direction is +Z.  The endpoint returns a self-contained draft
    result and, optionally, a display mesh with one RGB color per triangle.
    """
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail="filename must not contain path separators")

    path = PARTS_DIR / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"STEP file not found: {safe_name}")

    try:
        part = load_step(path)
        result = analyze_draft(
            part=part,
            pull_direction=(dx, dy, dz),
            pull_direction_label=f"user direction ({dx:+.3f}, {dy:+.3f}, {dz:+.3f})",
            analysis_pass="override" if (dx, dy, dz) != (0.0, 0.0, 1.0) else "initial",
            mutate=True,
        )

        payload = {
            "part": part.to_dict(include_faces=include_faces),
            "draft": result.to_dict(),
        }

        if include_mesh:
            mesh = build_display_mesh(part, linear_deflection=mesh_deflection)
            mesh_payload = mesh.to_payload(include_geometry=True)
            face_results = result.face_results
            class_to_color = {
                "good": [0.0, 0.85, 0.3],
                "marginal": [1.0, 0.85, 0.0],
                "bad": [0.95, 0.15, 0.1],
            }
            mesh_payload["draft_classification"] = [
                str(face_results.get(face_id, {}).get("draft_classification", "skipped"))
                for face_id in mesh.face_ids
            ]
            mesh_payload["draft_rgb"] = [
                class_to_color.get(
                    str(face_results.get(face_id, {}).get("draft_classification", "skipped")),
                    [0.55, 0.55, 0.55],
                )
                for face_id in mesh.face_ids
            ]
            payload["display_mesh"] = mesh_payload

        return payload
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "CAD runtime dependency missing. Use the locked conda/Docker "
                f"environment. Details: {exc}"
            ),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except STEPLoadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
