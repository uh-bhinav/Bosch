import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from backend.geometry.draft_analyzer import analyze_draft
from backend.geometry.direction_optimizer import optimize_mold_direction
from backend.geometry.parting_line import detect_parting_line_candidates
from backend.geometry.step_loader import STEPLoadError, load_step
from backend.geometry.undercut_detector import detect_undercuts
from backend.geometry.visualize_raw import build_display_mesh, build_shape_display_mesh
from backend.config import settings

app = FastAPI(
    title="DfM Agent API"
)

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PARTS_DIR = PROJECT_ROOT / "data" / "parts"


BOOLEAN_REGION_STYLES = {
    "critical": {
        "label": "Critical Boolean interference",
        "rgb": [1.0, 0.10, 0.04],
        "edge_color": "#6f160b",
        "opacity": 0.62,
    },
    "moderate": {
        "label": "Moderate Boolean interference",
        "rgb": [1.0, 0.48, 0.04],
        "edge_color": "#7a3a05",
        "opacity": 0.56,
    },
    "minor": {
        "label": "Minor Boolean interference",
        "rgb": [1.0, 0.76, 0.18],
        "edge_color": "#7c5a08",
        "opacity": 0.48,
    },
}

PARTING_LINE_STYLES = {
    "raw": {
        "label": "Raw selected parting wire",
        "rgb": [1.0, 0.72, 0.0],
        "hex": "#ffb800",
        "width": 3,
    },
    "refined": {
        "label": "Refined parting curve candidate",
        "rgb": [0.0, 0.72, 1.0],
        "hex": "#00b8ff",
        "width": 11,
    },
}


UNDERCUT_FACE_VISUAL_STYLES = {
    "critical_boolean_confirmed": {
        "label": "Critical Boolean-confirmed undercut",
        "rgb": [1.0, 0.04, 0.02],
        "priority": 100,
    },
    "critical_proxy_fallback": {
        "label": "Critical proxy/fallback undercut",
        "rgb": [1.0, 0.70, 0.25],
        "priority": 85,
    },
    "critical_proxy": {
        "label": "Critical proxy undercut",
        "rgb": [1.0, 0.62, 0.22],
        "priority": 80,
    },
    "moderate_boolean_confirmed": {
        "label": "Moderate Boolean-confirmed undercut",
        "rgb": [1.0, 0.48, 0.04],
        "priority": 70,
    },
    "moderate_proxy_fallback": {
        "label": "Moderate proxy/fallback undercut",
        "rgb": [1.0, 0.82, 0.38],
        "priority": 55,
    },
    "moderate_proxy": {
        "label": "Moderate proxy undercut",
        "rgb": [1.0, 0.78, 0.34],
        "priority": 50,
    },
    "minor_boolean_confirmed": {
        "label": "Minor Boolean-confirmed undercut",
        "rgb": [1.0, 0.76, 0.18],
        "priority": 45,
    },
    "minor_proxy_fallback": {
        "label": "Minor proxy/fallback undercut",
        "rgb": [1.0, 0.88, 0.42],
        "priority": 30,
    },
    "minor_proxy": {
        "label": "Minor proxy undercut",
        "rgb": [1.0, 0.82, 0.30],
        "priority": 28,
    },
    "proxy_undercut": {
        "label": "Proxy undercut evidence",
        "rgb": [0.94, 0.70, 0.24],
        "priority": 25,
    },
    "parting": {
        "label": "Parting/silhouette face",
        "rgb": [0.12, 0.34, 0.88],
        "priority": 10,
    },
    "accessible": {
        "label": "Accessible / no undercut evidence",
        "rgb": [0.74, 0.79, 0.84],
        "priority": 0,
    },
}


ERROR_HINTS = {
    "invalid_filename": "Select a STEP file from the app list instead of typing a path.",
    "part_not_found": "Confirm the file exists in data/parts and refresh the app.",
    "cad_runtime_missing": "Run the locked Docker/conda environment with pythonOCC, CadQuery, VTK, PyVista, and stpyvista installed.",
    "step_load_failed": "Check that the STEP file is valid, readable, and exported as a solid B-Rep.",
    "invalid_input": "Check the selected pull direction and numeric analysis settings.",
    "analysis_failed": "Retry with Boolean volumes disabled or a coarser mesh. If it repeats, inspect the backend logs.",
}


def _error_detail(
    *,
    code: str,
    message: str,
    operation: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "operation": operation,
        "recovery_hint": ERROR_HINTS.get(code, "Review the request settings and backend logs."),
        "details": details or {},
    }


@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict) and {"code", "message", "operation"}.issubset(detail):
        error = detail
    else:
        error = _error_detail(
            code="http_error",
            message=str(detail),
            operation=f"{request.method} {request.url.path}",
            details={"status_code": exc.status_code},
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "error": error},
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled API error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "error": _error_detail(
                code="analysis_failed",
                message="The analysis failed unexpectedly.",
                operation=f"{request.method} {request.url.path}",
                details={"exception_type": exc.__class__.__name__},
            ),
        },
    )


def _part_path_or_raise(filename: str, operation: str) -> tuple[str, Path]:
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(
            status_code=400,
            detail=_error_detail(
                code="invalid_filename",
                message="filename must not contain path separators",
                operation=operation,
                details={"filename": filename},
            ),
        )

    path = PARTS_DIR / safe_name
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=_error_detail(
                code="part_not_found",
                message=f"STEP file not found: {safe_name}",
                operation=operation,
                details={"parts_dir": str(PARTS_DIR), "filename": safe_name},
            ),
        )
    return safe_name, path


def _raise_dependency_error(exc: ImportError, operation: str) -> None:
    raise HTTPException(
        status_code=503,
        detail=_error_detail(
            code="cad_runtime_missing",
            message="CAD runtime dependency missing.",
            operation=operation,
            details={"exception": str(exc)},
        ),
    ) from exc


def _raise_step_error(exc: STEPLoadError, operation: str) -> None:
    raise HTTPException(
        status_code=422,
        detail=_error_detail(
            code="step_load_failed",
            message=str(exc),
            operation=operation,
        ),
    ) from exc


def _raise_value_error(exc: ValueError, operation: str) -> None:
    raise HTTPException(
        status_code=400,
        detail=_error_detail(
            code="invalid_input",
            message=str(exc),
            operation=operation,
        ),
    ) from exc


def _boolean_region_visual_style(feature: object) -> dict:
    severity = str(getattr(feature, "severity", "moderate") or "moderate").lower()
    is_major = bool(getattr(feature, "is_major_feature", False))
    style = BOOLEAN_REGION_STYLES.get(severity, BOOLEAN_REGION_STYLES["moderate"])
    if is_major:
        return {
            "severity": severity,
            "label": f"Major {style['label']}",
            "rgb": [1.0, 0.02, 0.0],
            "edge_color": "#1f0b08",
            "opacity": 0.78,
            "line_width": 2.2,
            "is_major_feature": True,
        }
    return {
        "severity": severity,
        "label": style["label"],
        "rgb": style["rgb"],
        "edge_color": style["edge_color"],
        "opacity": style["opacity"],
        "line_width": 0.9,
        "is_major_feature": False,
    }


def _feature_value(feature: object, name: str, default: Any = None) -> Any:
    if isinstance(feature, dict):
        return feature.get(name, default)
    return getattr(feature, name, default)


def _normalised_token(value: object, default: str = "unknown") -> str:
    text = str(value or default).strip().lower()
    return text.replace("_", "-").replace(" ", "-")


def _as_int_set(value: object) -> set[int]:
    if value is None:
        return set()
    if isinstance(value, set):
        iterable = value
    elif isinstance(value, (list, tuple)):
        iterable = value
    else:
        iterable = [value]
    result: set[int] = set()
    for item in iterable:
        try:
            result.add(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _undercut_style_key(feature: object | None, face_id: int, *, fallback: bool) -> str:
    if feature is None:
        return "proxy_undercut"

    severity = _normalised_token(_feature_value(feature, "severity", "minor"), "minor")
    if severity not in {"critical", "moderate", "minor"}:
        severity = "minor"

    confirmed_ids = _as_int_set(_feature_value(feature, "boolean_confirmed_face_ids", []))
    failed_ids = _as_int_set(_feature_value(feature, "boolean_failed_face_ids", []))
    skipped_ids = _as_int_set(_feature_value(feature, "boolean_skipped_face_ids", []))
    evidence_source = _normalised_token(_feature_value(feature, "evidence_source", ""))
    has_fallback_evidence = (
        face_id in failed_ids
        or face_id in skipped_ids
        or "failure" in evidence_source
        or "skip" in evidence_source
        or fallback
    )

    if face_id in confirmed_ids:
        return f"{severity}_boolean_confirmed"
    if has_fallback_evidence:
        return f"{severity}_proxy_fallback"
    return f"{severity}_proxy" if f"{severity}_proxy" in UNDERCUT_FACE_VISUAL_STYLES else "proxy_undercut"


def _undercut_mesh_visual_payload(result: object, mesh: object) -> dict[str, list]:
    """
    Build feature-aware visualization arrays for undercut meshes.

    The detector intentionally retains proxy faces when OCC Boolean fails, but
    display should not paint every retained proxy face as critical red.  This
    adapter keeps Boolean-confirmed severe evidence visually dominant while
    rendering fallback evidence with less alarming amber/orange colors.
    """
    undercut_ids = _as_int_set(getattr(result, "undercut_face_ids", []))
    parting_ids = _as_int_set(getattr(result, "parting_face_ids", []))
    feature_by_face: dict[int, object] = {}
    feature_ids_by_face: dict[int, list[int]] = {}

    for feature in list(getattr(result, "features", []) or []):
        feature_id = int(_feature_value(feature, "feature_id", -1) or -1)
        feature_face_ids = _as_int_set(_feature_value(feature, "face_ids", []))
        feature_face_ids.update(_as_int_set(_feature_value(feature, "boolean_confirmed_face_ids", [])))
        feature_face_ids.update(_as_int_set(_feature_value(feature, "boolean_failed_face_ids", [])))
        for face_id in feature_face_ids:
            candidate_key = _undercut_style_key(feature, face_id, fallback=False)
            candidate_priority = UNDERCUT_FACE_VISUAL_STYLES.get(candidate_key, {}).get("priority", 0)
            existing = feature_by_face.get(face_id)
            existing_key = _undercut_style_key(existing, face_id, fallback=False) if existing is not None else ""
            existing_priority = UNDERCUT_FACE_VISUAL_STYLES.get(existing_key, {}).get("priority", -1)
            if candidate_priority >= existing_priority:
                feature_by_face[face_id] = feature
            feature_ids_by_face.setdefault(face_id, [])
            if feature_id >= 0 and feature_id not in feature_ids_by_face[face_id]:
                feature_ids_by_face[face_id].append(feature_id)

    classifications: list[str] = []
    rgb_values: list[list[float]] = []
    visual_priorities: list[int] = []
    feature_ids: list[list[int]] = []
    for face_id in mesh.face_ids:
        if face_id in undercut_ids:
            feature = feature_by_face.get(face_id)
            style_key = _undercut_style_key(feature, face_id, fallback=feature is None)
        elif face_id in parting_ids:
            style_key = "parting"
        else:
            style_key = "accessible"
        style = UNDERCUT_FACE_VISUAL_STYLES.get(style_key, UNDERCUT_FACE_VISUAL_STYLES["accessible"])
        classifications.append(style_key)
        rgb_values.append(style["rgb"])
        visual_priorities.append(int(style["priority"]))
        feature_ids.append(sorted(feature_ids_by_face.get(face_id, [])))

    summary_counts: dict[str, int] = {}
    for style_key in classifications:
        summary_counts[style_key] = summary_counts.get(style_key, 0) + 1

    return {
        "undercut_classification": classifications,
        "undercut_rgb": rgb_values,
        "undercut_visual_priority": visual_priorities,
        "undercut_feature_ids": feature_ids,
        "undercut_visual_summary": {
            "counts": summary_counts,
            "legend": UNDERCUT_FACE_VISUAL_STYLES,
        },
    }


def _boolean_region_mesh_payloads(
    features: list[object],
    mesh_deflection: float,
) -> dict:
    """
    Build renderable meshes for Boolean-confirmed undercut regions.

    The analysis layer keeps exact OCC shapes in memory.  This helper converts
    only those confirmed regions into lightweight triangle payloads that the
    frontend can draw as translucent undercut volumes.
    """
    regions: list[dict] = []
    warnings: list[str] = []

    for feature in features:
        feature_id = int(getattr(feature, "feature_id", len(regions)))
        shapes = list(getattr(feature, "boolean_intersection_shapes", []) or [])
        source_face_ids = list(getattr(feature, "boolean_intersection_face_ids", []) or [])

        for shape_index, shape in enumerate(shapes):
            if shape is None:
                continue
            try:
                visual_style = _boolean_region_visual_style(feature)
                region_mesh = build_shape_display_mesh(
                    shape,
                    linear_deflection=mesh_deflection,
                )
                mesh_payload = region_mesh.to_payload(include_geometry=True)
                mesh_payload["feature_ids"] = [feature_id for _ in region_mesh.faces]
                mesh_payload["region_rgb"] = [
                    visual_style["rgb"] for _ in region_mesh.faces
                ]
                regions.append({
                    "feature_id": feature_id,
                    "shape_index": shape_index,
                    "severity": getattr(feature, "severity", "moderate"),
                    "is_major_feature": bool(getattr(feature, "is_major_feature", False)),
                    "source_face_ids": source_face_ids,
                    "geometric_feature_type": getattr(feature, "geometric_feature_type", "unclassified"),
                    "geometric_feature_confidence": float(
                        getattr(feature, "geometric_feature_confidence", 0.0)
                    ),
                    "undercut_type": getattr(feature, "undercut_type", "unknown"),
                    "recommended_mold_action": getattr(feature, "recommended_mold_action", "review"),
                    "action_confidence": float(getattr(feature, "action_confidence", 0.0)),
                    "action_confidence_label": getattr(feature, "action_confidence_label", "unknown"),
                    "action_explanation": getattr(feature, "action_explanation", ""),
                    "release_direction": list(getattr(feature, "release_direction", (0.0, 0.0, 0.0))),
                    "depth_proxy_mm": float(getattr(feature, "depth_proxy_mm", 0.0)),
                    "visual_style": visual_style,
                    "mesh": mesh_payload,
                })
            except Exception as exc:  # pragma: no cover - depends on OCC runtime failure modes.
                warnings.append(
                    f"Feature {feature_id} Boolean region {shape_index} mesh failed: {exc}"
                )

    return {
        "region_count": len(regions),
        "triangle_count": sum(
            int(region.get("mesh", {}).get("triangle_count", 0))
            for region in regions
        ),
        "point_count": sum(
            int(region.get("mesh", {}).get("point_count", 0))
            for region in regions
        ),
        "regions": regions,
        "warnings": warnings,
        "legend": BOOLEAN_REGION_STYLES,
    }


def _rgb_float_to_hex(rgb: list[float]) -> str:
    values = [
        max(0, min(255, int(round(float(component) * 255.0))))
        for component in rgb[:3]
    ]
    return f"#{values[0]:02x}{values[1]:02x}{values[2]:02x}"


def _parting_line_paths_payload(parting_line: dict[str, Any]) -> dict[str, Any]:
    raw_points = parting_line.get("wire_points", []) or []
    refinement = parting_line.get("refinement", {}) or {}
    refined_points = refinement.get("refined_points", []) or []
    display_metrics = refinement.get("display_metrics", {}) or {}
    cfg = settings.dfm.parting_line
    raw_color = [float(value) for value in cfg.raw_curve_color]
    refined_color = [float(value) for value in cfg.refined_curve_color]

    return {
        "raw": {
            "label": PARTING_LINE_STYLES["raw"]["label"],
            "points": raw_points,
            "point_count": len(raw_points),
            "rgb": raw_color,
            "hex": _rgb_float_to_hex(raw_color),
            "width": PARTING_LINE_STYLES["raw"]["width"],
            "visible_by_default": False,
        },
        "refined": {
            "label": PARTING_LINE_STYLES["refined"]["label"],
            "points": refined_points or raw_points,
            "point_count": len(refined_points or raw_points),
            "rgb": refined_color,
            "hex": _rgb_float_to_hex(refined_color),
            "width": PARTING_LINE_STYLES["refined"]["width"],
            "visible_by_default": True,
            "smoothing_iterations": int(refinement.get("smoothing_iterations", 0) or 0),
            "quality": refinement.get("quality", "unknown"),
            "display_metrics": display_metrics,
        },
        "legend": {
            "raw": {
                **PARTING_LINE_STYLES["raw"],
                "rgb": raw_color,
                "hex": _rgb_float_to_hex(raw_color),
            },
            "refined": {
                **PARTING_LINE_STYLES["refined"],
                "rgb": refined_color,
                "hex": _rgb_float_to_hex(refined_color),
            },
        },
    }


@app.get("/")
def root():
    return {
        "message": "DfM backend running"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "parts_dir": str(PARTS_DIR),
        "parts_dir_exists": PARTS_DIR.exists(),
    }


@app.get("/parts")
def list_parts():
    """List STEP files available for analysis."""
    if not PARTS_DIR.exists():
        return {
            "parts_dir": str(PARTS_DIR),
            "files": [],
            "warnings": ["Parts directory does not exist."],
        }

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

    `include_mesh=true` returns a renderable display mesh.  The summary view
    uses the same frontend viewer path as draft/undercut/parting-line overlays,
    so the mesh payload must include point and triangle arrays, not only counts.
    """
    operation = "STEP summary"
    _, path = _part_path_or_raise(filename, operation)

    try:
        part = load_step(path)
        payload = part.to_dict(include_faces=include_faces)
        if include_mesh:
            mesh = build_display_mesh(part, linear_deflection=mesh_deflection)
            payload["display_mesh"] = mesh.to_payload(include_geometry=True)
        return payload
    except ImportError as exc:
        _raise_dependency_error(exc, operation)
    except STEPLoadError as exc:
        _raise_step_error(exc, operation)


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
    operation = "draft analysis"
    _, path = _part_path_or_raise(filename, operation)

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
        _raise_dependency_error(exc, operation)
    except ValueError as exc:
        _raise_value_error(exc, operation)
    except STEPLoadError as exc:
        _raise_step_error(exc, operation)


@app.get("/parts/{filename}/undercuts")
def part_undercuts(
    filename: str,
    dx: float = Query(default=0.0),
    dy: float = Query(default=0.0),
    dz: float = Query(default=1.0),
    include_faces: bool = Query(default=False),
    include_mesh: bool = Query(default=True),
    include_boolean_regions: bool = Query(default=False),
    boolean_refine: bool = Query(default=True),
    boolean_check_all_faces: bool = Query(default=False),
    max_boolean_faces: int = Query(default=120, ge=1),
    mesh_deflection: float = Query(default=0.5, gt=0.0),
):
    """
    Run first-pass undercut/accessibility detection for a pull direction.

    The detector uses a normal/draft/accessibility prefilter plus optional
    swept Boolean refinement. `include_boolean_regions=true` returns
    display-only meshes for confirmed Boolean interference volumes.
    """
    operation = "undercut detection"
    _, path = _part_path_or_raise(filename, operation)

    try:
        part = load_step(path)
        result = detect_undercuts(
            part,
            (dx, dy, dz),
            mutate=True,
            boolean_refine=boolean_refine,
            boolean_check_all_faces=boolean_check_all_faces,
            max_boolean_faces=max_boolean_faces,
        )
        payload = {
            "part": part.to_dict(include_faces=include_faces),
            "undercuts": result.to_dict(),
        }

        if include_mesh:
            mesh = build_display_mesh(part, linear_deflection=mesh_deflection)
            mesh_payload = mesh.to_payload(include_geometry=True)
            mesh_payload.update(_undercut_mesh_visual_payload(result, mesh))
            payload["display_mesh"] = mesh_payload

        if include_boolean_regions:
            payload["boolean_region_meshes"] = _boolean_region_mesh_payloads(
                result.features,
                mesh_deflection=mesh_deflection,
            )

        return payload
    except ImportError as exc:
        _raise_dependency_error(exc, operation)
    except ValueError as exc:
        _raise_value_error(exc, operation)
    except STEPLoadError as exc:
        _raise_step_error(exc, operation)


@app.get("/parts/{filename}/direction")
def part_direction(
    filename: str,
    dx: float = Query(default=0.0),
    dy: float = Query(default=0.0),
    dz: float = Query(default=1.0),
    angular_step_deg: float | None = Query(default=None, gt=0.0),
    max_candidates: int | None = Query(default=None, ge=6),
    include_faces: bool = Query(default=False),
    include_mesh: bool = Query(default=True),
    include_boolean_regions: bool = Query(default=False),
    include_all_candidates: bool = Query(default=False),
    mesh_deflection: float = Query(default=0.5, gt=0.0),
):
    """
    Compute the best mold opening direction from sampled candidates.

    Current method: surface-normal draft/accessibility prefilter plus optional
    Bassi-style swept Boolean refinement on promising candidates.
    """
    operation = "direction optimization"
    _, path = _part_path_or_raise(filename, operation)

    try:
        part = load_step(path)
        initial_direction = (dx, dy, dz)
        direction = optimize_mold_direction(
            part,
            angular_step_deg=angular_step_deg,
            max_candidates=max_candidates,
            initial_pull_direction=initial_direction,
            initial_label=f"initial UI direction ({dx:+.3f}, {dy:+.3f}, {dz:+.3f})",
        )
        payload = {
            "part": part.to_dict(include_faces=include_faces),
            "direction": direction.to_dict(include_all_candidates=include_all_candidates),
        }

        if include_mesh:
            mesh = build_display_mesh(part, linear_deflection=mesh_deflection)
            mesh_payload = mesh.to_payload(include_geometry=True)
            face_results = direction.optimal_draft.face_results
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
            mesh_payload.update(_undercut_mesh_visual_payload(direction.optimal_undercuts, mesh))
            payload["display_mesh"] = mesh_payload

        if include_boolean_regions:
            payload["boolean_region_meshes"] = _boolean_region_mesh_payloads(
                direction.optimal_undercuts.features,
                mesh_deflection=mesh_deflection,
            )

        return payload
    except ImportError as exc:
        _raise_dependency_error(exc, operation)
    except ValueError as exc:
        _raise_value_error(exc, operation)
    except STEPLoadError as exc:
        _raise_step_error(exc, operation)


@app.get("/parts/{filename}/parting-line")
def part_parting_line(
    filename: str,
    dx: float = Query(default=0.0),
    dy: float = Query(default=0.0),
    dz: float = Query(default=1.0),
    use_optimal_direction: bool = Query(default=True),
    include_faces: bool = Query(default=False),
    include_mesh: bool = Query(default=True),
    include_direction: bool = Query(default=False),
    include_undercut_conflicts: bool = Query(default=True),
    refine: bool = Query(default=True),
    smoothing_iterations: int | None = Query(default=None, ge=0),
    mesh_deflection: float = Query(default=0.5, gt=0.0),
):
    """
    Detect the main parting-line candidate for a pull direction.

    By default this endpoint first computes the optimal Level 1 mold opening
    direction, then runs the Nee/Hou-inspired parting-line foundation on that
    direction.  Callers can set `use_optimal_direction=false` to inspect a
    manually supplied vector.
    """
    operation = "parting-line detection"
    _, path = _part_path_or_raise(filename, operation)

    try:
        part = load_step(path)
        direction_payload: dict[str, Any] | None = None
        undercut_context: object | None = None
        if use_optimal_direction:
            direction = optimize_mold_direction(
                part,
                initial_pull_direction=(dx, dy, dz),
                initial_label=f"initial UI direction ({dx:+.3f}, {dy:+.3f}, {dz:+.3f})",
            )
            pull_direction = direction.best_direction
            pull_direction_source = "optimal_mold_direction"
            undercut_context = direction.optimal_undercuts
            if include_direction:
                direction_payload = direction.to_dict(include_all_candidates=False)
        else:
            pull_direction = (dx, dy, dz)
            pull_direction_source = "manual_query_direction"
            if include_undercut_conflicts:
                undercut_context = detect_undercuts(
                    part,
                    pull_direction,
                    mutate=False,
                    boolean_refine=False,
                )

        cfg = settings.dfm.parting_line
        result = detect_parting_line_candidates(
            part,
            pull_direction=pull_direction,
            undercut_context=undercut_context if include_undercut_conflicts else None,
            dot_tolerance=cfg.dot_tolerance,
            boundary_dot_tolerance=cfg.boundary_dot_tolerance,
            point_tolerance=cfg.point_tolerance,
            refine=refine,
            smoothing_iterations=(
                cfg.smoothing_iterations
                if smoothing_iterations is None
                else smoothing_iterations
            ),
            display_resample_min_points=cfg.display_resample_min_points,
            max_refined_display_points=cfg.max_refined_display_points,
            mutate=True,
        )
        parting_line = result.to_dict()
        parting_line["pull_direction_source"] = pull_direction_source

        payload: dict[str, Any] = {
            "part": part.to_dict(include_faces=include_faces),
            "parting_line": parting_line,
            "parting_line_paths": _parting_line_paths_payload(parting_line),
            "analysis_quality": parting_line.get("diagnostic_gate", {}),
        }
        if direction_payload is not None:
            payload["direction"] = direction_payload

        if include_mesh:
            mesh = build_display_mesh(part, linear_deflection=mesh_deflection)
            mesh_payload = mesh.to_payload(include_geometry=True)
            selected_edge_count = len(result.selected_edge_ids)
            mesh_payload["parting_rgb"] = [
                [0.72, 0.76, 0.82]
                for _ in mesh.face_ids
            ]
            mesh_payload["parting_context"] = {
                "selected_edge_count": selected_edge_count,
                "refined_point_count": len(result.refinement.refined_points),
                "raw_point_count": len(result.wire_points),
            }
            payload["display_mesh"] = mesh_payload

        return payload
    except ImportError as exc:
        _raise_dependency_error(exc, operation)
    except ValueError as exc:
        _raise_value_error(exc, operation)
    except STEPLoadError as exc:
        _raise_step_error(exc, operation)
