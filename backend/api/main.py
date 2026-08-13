import base64
import logging
import math
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from backend.geometry.core_cavity import classify_core_cavity, export_mold_halves, split_core_cavity_solids
from backend.geometry.side_core import (
    combine_side_cores_per_half,
    generate_primary_side_core,
    generate_side_cores_for_features,
)
from backend.geometry.draft_analyzer import analyze_draft
from backend.geometry.direction_optimizer import optimize_mold_direction
from backend.geometry.parting_line import detect_parting_line_candidates
from backend.geometry.parting_line_v2 import PullDirectionInput, UndercutInput
from backend.geometry.parting_line_v2.engine import analyse_parting_line
from backend.geometry.step_loader import STEPLoadError, load_step_cached
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
        "rgb": [1.0, 0.65, 0.0],
        "hex": "#ffa500",
        "width": 1,
    },
    "refined": {
        "label": "Parting Line (Refined)",
        "rgb": [0.0, 0.75, 1.0],
        "hex": "#00BFFF",
        "width": 4,
    },
}


def _rgb_byte_triplet(red: int, green: int, blue: int) -> list[float]:
    return [red / 255.0, green / 255.0, blue / 255.0]


UNDERCUT_FACE_VISUAL_STYLES = {
    "critical_boolean_confirmed": {
        "label": "Critical Boolean-confirmed undercut",
        "rgb": _rgb_byte_triplet(255, 50, 50),
        "priority": 100,
    },
    "high_boolean_confirmed": {
        "label": "High Boolean-confirmed undercut",
        "rgb": _rgb_byte_triplet(255, 50, 50),
        "priority": 95,
    },
    "medium_boolean_confirmed": {
        "label": "Medium Boolean-confirmed undercut",
        "rgb": _rgb_byte_triplet(255, 120, 50),
        "priority": 70,
    },
    "moderate_boolean_confirmed": {
        "label": "Moderate Boolean-confirmed undercut",
        "rgb": _rgb_byte_triplet(255, 120, 50),
        "priority": 68,
    },
    "low_boolean_confirmed": {
        "label": "Low Boolean-confirmed undercut",
        "rgb": _rgb_byte_triplet(255, 165, 50),
        "priority": 45,
    },
    "minor_boolean_confirmed": {
        "label": "Minor Boolean-confirmed undercut",
        "rgb": _rgb_byte_triplet(255, 165, 50),
        "priority": 43,
    },
    "proxy_undercut": {
        "label": "Proxy undercut evidence",
        "rgb": _rgb_byte_triplet(255, 230, 150),
        "priority": 25,
    },
    "parting": {
        "label": "Parting/silhouette face",
        "rgb": _rgb_byte_triplet(180, 180, 180),
        "priority": 10,
    },
    "accessible": {
        "label": "Accessible / no undercut evidence",
        "rgb": _rgb_byte_triplet(180, 180, 180),
        "priority": 5,
    },
    "neutral": {
        "label": "Neutral base face",
        "rgb": _rgb_byte_triplet(210, 210, 210),
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
    "agent_configuration_error": "Check the requested provider name and backend/config.py's agent settings.",
    "agent_dependency_missing": "Install the SDK for the configured provider (google-genai, anthropic, or openai).",
    "agent_provider_error": "The configured LLM provider call failed; check its API key and quota, then retry.",
    "invalid_screenshot": "screenshot_png_base64 must be valid base64-encoded PNG data.",
    "report_export_failed": "Retry with include_agent_narrative=false or include_side_core=false. If it repeats, inspect the backend logs.",
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


def _undercut_result_value(result: object, name: str, default: Any = None) -> Any:
    if isinstance(result, dict):
        return result.get(name, default)
    return getattr(result, name, default)


def _undercut_confirmed_face_ids(result: object) -> set[int]:
    refinement = _undercut_result_value(result, "boolean_refinement", {}) or {}
    if isinstance(refinement, dict):
        confirmed = refinement.get("confirmed_face_ids", [])
    else:
        confirmed = getattr(result, "boolean_confirmed_face_ids", [])
    confirmed_ids = _as_int_set(confirmed)
    if confirmed_ids:
        return confirmed_ids

    fallback_ids: set[int] = set()
    for feature in list(_undercut_result_value(result, "features", []) or []):
        evidence_source = _normalised_token(_feature_value(feature, "evidence_source", "proxy"))
        action_confidence = _safe_float(_feature_value(feature, "action_confidence", 0.0))
        if evidence_source != "proxy" or action_confidence > 0.5:
            fallback_ids.update(_as_int_set(_feature_value(feature, "face_ids", [])))
            fallback_ids.update(_as_int_set(_feature_value(feature, "boolean_confirmed_face_ids", [])))
    return fallback_ids


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _confirmed_undercut_style_key(feature: object | None) -> str:
    severity = _normalised_token(_feature_value(feature, "severity", "low"), "low")
    if severity in {"critical", "high"}:
        return "critical_boolean_confirmed" if severity == "critical" else "high_boolean_confirmed"
    if severity in {"medium", "moderate"}:
        return "medium_boolean_confirmed" if severity == "medium" else "moderate_boolean_confirmed"
    return "low_boolean_confirmed" if severity == "low" else "minor_boolean_confirmed"


def _undercut_mesh_visual_payload(result: object, mesh: object) -> dict[str, list]:
    """
    Build feature-aware visualization arrays for undercut meshes.

    Boolean-confirmed faces use severity-based red/orange coloring. Proxy-only
    faces use light yellow so the whole body is not painted critical red.
    """
    undercut_ids = _as_int_set(_undercut_result_value(result, "undercut_face_ids", []))
    parting_ids = _as_int_set(_undercut_result_value(result, "parting_face_ids", []))
    accessible_ids = _as_int_set(_undercut_result_value(result, "accessible_face_ids", []))
    confirmed_ids = _undercut_confirmed_face_ids(result)
    feature_by_face: dict[int, object] = {}
    feature_ids_by_face: dict[int, list[int]] = {}

    for feature in list(_undercut_result_value(result, "features", []) or []):
        feature_id = int(_feature_value(feature, "feature_id", -1) or -1)
        feature_face_ids = _as_int_set(_feature_value(feature, "face_ids", []))
        feature_face_ids.update(_as_int_set(_feature_value(feature, "boolean_confirmed_face_ids", [])))
        for face_id in feature_face_ids:
            existing = feature_by_face.get(face_id)
            if existing is None:
                feature_by_face[face_id] = feature
            else:
                existing_severity = _normalised_token(_feature_value(existing, "severity", "low"))
                candidate_severity = _normalised_token(_feature_value(feature, "severity", "low"))
                severity_rank = {"critical": 4, "high": 3, "medium": 2, "moderate": 2, "low": 1, "minor": 1}
                if severity_rank.get(candidate_severity, 0) >= severity_rank.get(existing_severity, 0):
                    feature_by_face[face_id] = feature
            feature_ids_by_face.setdefault(face_id, [])
            if feature_id >= 0 and feature_id not in feature_ids_by_face[face_id]:
                feature_ids_by_face[face_id].append(feature_id)

    classifications: list[str] = []
    rgb_values: list[list[float]] = []
    visual_priorities: list[int] = []
    feature_ids: list[list[int]] = []
    for face_id in mesh.face_ids:
        if face_id in confirmed_ids:
            feature = feature_by_face.get(face_id)
            style_key = _confirmed_undercut_style_key(feature)
        elif face_id in undercut_ids:
            style_key = "proxy_undercut"
        elif face_id in parting_ids or face_id in accessible_ids:
            style_key = "parting" if face_id in parting_ids else "accessible"
        else:
            style_key = "neutral"
        style = UNDERCUT_FACE_VISUAL_STYLES.get(style_key, UNDERCUT_FACE_VISUAL_STYLES["neutral"])
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
            "confirmed_face_count": len(confirmed_ids),
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

    effective_refined = refined_points if len(refined_points) >= 3 else raw_points
    return {
        "raw_wire_points": raw_points,
        "refined_points": effective_refined,
        "raw": {
            "label": PARTING_LINE_STYLES["raw"]["label"],
            "points": raw_points,
            "point_count": len(raw_points),
            "rgb": raw_color,
            "hex": PARTING_LINE_STYLES["raw"]["hex"],
            "width": PARTING_LINE_STYLES["raw"]["width"],
            "opacity": 0.4,
            "visible_by_default": True,
        },
        "refined": {
            "label": PARTING_LINE_STYLES["refined"]["label"],
            "points": effective_refined,
            "point_count": len(effective_refined),
            "rgb": refined_color,
            "hex": PARTING_LINE_STYLES["refined"]["hex"],
            "width": PARTING_LINE_STYLES["refined"]["width"],
            "visible_by_default": True,
            "smoothing_iterations": int(refinement.get("smoothing_iterations", 0) or 0),
            "quality": refinement.get("quality", "unknown"),
            "display_metrics": display_metrics,
            "fallback_to_raw": len(refined_points) < 3,
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
        part = load_step_cached(path)
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
    include_mesh_geometry: bool = Query(default=True),
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
        part = load_step_cached(path)
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
            mesh_payload = mesh.to_payload(include_geometry=include_mesh_geometry)
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
    include_mesh_geometry: bool = Query(default=True),
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
        part = load_step_cached(path)
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
            mesh_payload = mesh.to_payload(include_geometry=include_mesh_geometry)
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
    include_mesh_geometry: bool = Query(default=True),
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
        part = load_step_cached(path)
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
            mesh_payload = mesh.to_payload(include_geometry=include_mesh_geometry)
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
    include_mesh_geometry: bool = Query(default=True),
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
        part = load_step_cached(path)
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
            mesh_payload = mesh.to_payload(include_geometry=include_mesh_geometry)
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


@app.get("/parts/{filename}/parting-line-v2")
def part_parting_line_v2(
    filename: str,
    dx: float = Query(default=0.0),
    dy: float = Query(default=0.0),
    dz: float = Query(default=1.0),
    include_mesh: bool = Query(default=True),
    include_mesh_geometry: bool = Query(default=True),
    mesh_deflection: float = Query(default=0.5, gt=0.0),
):
    """
    Run the EXPERIMENTAL, in-development v2 parting-line engine (Track A/B ->
    stitching -> graph -> 2-core -> candidate generation -> H0-H7 -> ranking)
    on a manually supplied direction.

    Direction is ALWAYS "manual" here -- this endpoint never calls
    `optimize_mold_direction()`. `parting_line_v2` must never depend on the
    direction optimizer (enforced by
    `test_no_module_imports_the_direction_optimizer`); this endpoint
    preserves that at the API boundary too, so a caller wanting to inspect
    the optimizer's suggested vector must copy the numbers in manually, the
    same way they would for any other externally-supplied direction.

    Level 0-2 only: no parting-surface generation, no core/cavity SOLID
    split at this level (see docs/IMPLEMENTATION_STATUS.md). When a
    candidate is selected, `regions` is graph-connectivity-based
    (RegionClassification, derived from H3's face-adjacency cut), not v1's
    per-face normal-sign test -- see `docs/DECISIONS_AND_ALGORITHMS.md` for
    why that distinction matters on parts with local features.
    """
    operation = "parting-line v2 detection (experimental)"
    _, path = _part_path_or_raise(filename, operation)

    try:
        magnitude = math.sqrt(dx * dx + dy * dy + dz * dz)
        if magnitude < 1e-9:
            raise ValueError("Pull direction vector must be nonzero.")
        direction = (dx / magnitude, dy / magnitude, dz / magnitude)

        part = load_step_cached(path)
        pull = PullDirectionInput(direction, "manual")
        cfg = settings.dfm.parting_line_v2
        result = analyse_parting_line(part, pull, undercuts=UndercutInput.empty(), cfg=cfg)

        payload: dict[str, Any] = result.to_dict()
        payload["engine"] = "parting_line_v2"
        payload["status_note"] = (
            "Experimental Level 0-2 engine, not yet the default. No parting-surface "
            "generation or core/cavity SOLID split at this level -- see "
            "docs/IMPLEMENTATION_STATUS.md for the authoritative capability list."
        )

        if result.selected is not None:
            payload["parting_line_path"] = {
                "label": "Parting Line v2 (selected candidate)",
                "points": [[round(c, 6) for c in p] for p in result.selected.points],
                "hex": "#22c55e",
                "width": 6,
            }

        if include_mesh:
            mesh = build_display_mesh(part, linear_deflection=mesh_deflection)
            payload["display_mesh"] = mesh.to_payload(include_geometry=include_mesh_geometry)

        return payload
    except ImportError as exc:
        _raise_dependency_error(exc, operation)
    except ValueError as exc:
        _raise_value_error(exc, operation)
    except STEPLoadError as exc:
        _raise_step_error(exc, operation)


@app.get("/parts/{filename}/core-cavity")
def part_core_cavity(
    filename: str,
    use_optimal_direction: bool = Query(default=True),
    dx: float = Query(default=0.0),
    dy: float = Query(default=0.0),
    dz: float = Query(default=1.0),
    threshold: float | None = Query(default=None, ge=0.0, le=1.0),
    solid_split: bool = Query(default=False),
    generate_side_core: bool = Query(default=False),
    multi_feature_side_cores: bool = Query(default=False),
    side_core_severities: str = Query(default="critical"),
    side_core_max_features: int | None = Query(default=None),
    include_faces: bool = Query(default=False),
    include_mesh: bool = Query(default=True),
    include_mesh_geometry: bool = Query(default=True),
    mesh_deflection: float = Query(default=0.5, gt=0.0),
):
    """
    Classify faces as cavity, core, or parting relative to the pull direction.

    Level 1: face classification (always returned).
    Milestone 1.10: set ``solid_split=true`` to also run the Boolean mold-half split
    using the parting surface from the parting-line endpoint.

    Set ``use_optimal_direction=false`` and pass ``dx``/``dy``/``dz`` to
    classify against a manually supplied direction (Stage 3 S3.6 — direction
    override, Bosch criterion #2). Previously this always silently fell back
    to a hardcoded +Z regardless of dx/dy/dz whenever use_optimal_direction
    was false, with no way to classify against a genuinely custom direction.

    Stage 4 (Bosch criterion #5): set ``solid_split=true`` AND
    ``generate_side_core=true`` to also generate one side-core solid for the
    single highest-confidence critical undercut feature at this pull
    direction (see ``backend.geometry.side_core``). Note the OPTIMAL pull
    direction specifically searches for undercut-free directions, so
    ``generate_side_core`` will typically report ``"no_feature"`` there —
    pass ``use_optimal_direction=false`` with a manual direction to
    demonstrate it against a real undercut.

    S4.3 (2026-07-29): set ``multi_feature_side_cores=true`` instead of
    ``generate_side_core`` to generate one side core per QUALIFYING
    feature rather than only the single highest-confidence one.
    ``side_core_severities`` (comma-separated, default ``"critical"``) picks
    which severities qualify; ``side_core_max_features`` caps the count.
    Returns both per-feature diagnostics (``side_cores``) and, per mold
    half, a combined/fused/deduplicated result (``side_core_combined``) —
    see ``backend.geometry.side_core.combine_side_cores_per_half``'s
    docstring for why individual per-feature volumes must never be summed
    across features sharing a half (their local sweep footprints can
    physically overlap).
    """
    operation = "core/cavity classification"
    _, path = _part_path_or_raise(filename, operation)

    try:
        part = load_step_cached(path)
        pull_direction = (dx, dy, dz)
        pull_direction_source = "manual_query_direction"

        if use_optimal_direction:
            direction = optimize_mold_direction(part)
            pull_direction = direction.best_direction
            pull_direction_source = "optimal_mold_direction"
            part.optimal_pull_direction = pull_direction

        result = classify_core_cavity(
            part,
            pull_direction=pull_direction,
            threshold=threshold,
            mutate=True,
        )
        payload: dict[str, Any] = {
            "part": part.to_dict(include_faces=include_faces),
            "core_cavity": result.to_dict(),
            "pull_direction_source": pull_direction_source,
        }

        # Milestone 1.10: optional Boolean solid split.
        if solid_split:
            from backend.geometry.parting_line import detect_parting_line_candidates
            parting_result = detect_parting_line_candidates(
                part,
                pull_direction=pull_direction,
                mutate=False,
            )
            parting_sheet = (
                parting_result.parting_surface.occ_shape
                if parting_result.parting_surface.status.startswith("generated")
                else None
            )
            solid_result = split_core_cavity_solids(
                part,
                parting_sheet,
                pull_direction=pull_direction,
                loop_points=parting_result.wire_points,
            )
            payload["solid_split"] = solid_result.to_dict()

            # Stage 4 (Bosch criterion #5): first-increment side core, gated
            # behind solid_split since it needs cavity_solid/core_solid.
            if generate_side_core:
                undercut_result = detect_undercuts(
                    part,
                    pull_direction,
                    mutate=False,
                    boolean_refine=True,
                )
                side_core_result = generate_primary_side_core(
                    part, undercut_result, solid_result,
                )
                payload["side_core"] = side_core_result.to_dict()

            # S4.3 (2026-07-29): multi-feature generalization, independent
            # of (and mutually usable alongside) the single-feature path
            # above.
            if multi_feature_side_cores:
                severities = tuple(
                    s.strip() for s in side_core_severities.split(",") if s.strip()
                )
                undercut_result = detect_undercuts(
                    part,
                    pull_direction,
                    mutate=False,
                    boolean_refine=True,
                )
                multi_result = generate_side_cores_for_features(
                    part,
                    undercut_result,
                    solid_result,
                    severities=severities,
                    max_features=side_core_max_features,
                )
                combined = combine_side_cores_per_half(solid_result, multi_result)
                payload["side_cores"] = multi_result.to_dict()
                payload["side_core_combined"] = {
                    half: result.to_dict() for half, result in combined.items()
                }

        if include_mesh:
            mesh = build_display_mesh(part, linear_deflection=mesh_deflection)
            mesh_payload = mesh.to_payload(include_geometry=include_mesh_geometry)
            cavity_ids = set(result.cavity_face_ids)
            core_ids = set(result.core_face_ids)
            parting_ids = set(result.parting_face_ids)
            skipped_ids = set(result.skipped_face_ids)
            class_to_color = {
                "cavity": _rgb_byte_triplet(50, 200, 100),
                "core": _rgb_byte_triplet(50, 100, 200),
                "parting": _rgb_byte_triplet(220, 200, 50),
                "skipped": _rgb_byte_triplet(160, 160, 160),
                "neutral": _rgb_byte_triplet(210, 210, 210),
            }
            classifications: list[str] = []
            rgb_values: list[list[float]] = []
            for face_id in mesh.face_ids:
                if face_id in cavity_ids:
                    classification = "cavity"
                elif face_id in core_ids:
                    classification = "core"
                elif face_id in parting_ids:
                    classification = "parting"
                elif face_id in skipped_ids:
                    classification = "skipped"
                else:
                    classification = "neutral"
                classifications.append(classification)
                rgb_values.append(class_to_color[classification])
            mesh_payload["core_cavity_classification"] = classifications
            mesh_payload["core_cavity_rgb"] = rgb_values
            payload["display_mesh"] = mesh_payload

        return payload
    except ImportError as exc:
        _raise_dependency_error(exc, operation)
    except ValueError as exc:
        _raise_value_error(exc, operation)
    except STEPLoadError as exc:
        _raise_step_error(exc, operation)


@app.post("/parts/{filename}/export/mold-halves")
def export_mold_halves_endpoint(
    filename: str,
    output_dir: str | None = Query(default=None),
    use_optimal_direction: bool = Query(default=True),
    dx: float = Query(default=0.0),
    dy: float = Query(default=0.0),
    dz: float = Query(default=1.0),
    generate_side_core: bool = Query(default=False),
    multi_feature_side_cores: bool = Query(default=False),
    side_core_severities: str = Query(default="critical"),
    side_core_max_features: int | None = Query(default=None),
):
    """
    Export cavity and core mold-half solids as a multi-body AP214 STEP file (Milestone 1.11).

    Runs the full pipeline: load → direction → parting line → parting surface →
    solid split → export. Writes to ``output/mold_halves/`` by default (never to
    ``data/parts/``). Returns the output file path and status.

    Set ``use_optimal_direction=false`` with ``dx``/``dy``/``dz`` to export
    against a manually supplied direction, matching ``/core-cavity``'s
    override support (Stage 3 S3.6). Set ``generate_side_core=true`` to also
    generate and export a third solid — the Stage 4 (Bosch criterion #5)
    side core for the single highest-confidence critical undercut feature at
    this pull direction — replacing whichever main half contained it with
    its post-Cut reduced volume. The optimal pull direction specifically
    searches for undercut-free directions, so demonstrating this requires a
    manual, non-optimal direction (see ``/core-cavity``'s docstring).

    S4.3 (2026-07-29): set ``multi_feature_side_cores=true`` instead of
    ``generate_side_core`` to generate side cores for every qualifying
    feature (``side_core_severities``/``side_core_max_features``, same as
    ``/core-cavity``). The exported STEP file gets AT MOST one extra solid
    PER HALF (a combined/fused/deduplicated body — never one body per
    feature): exporting each feature's raw side-core solid as a separate
    body would double-count volume where nearby features' local sweep
    footprints physically overlap (see
    ``backend.geometry.side_core.combine_side_cores_per_half``'s
    docstring — measured on Part1: ~128mm3 of real overlap across 4
    feature pairs). Per-feature diagnostics are still returned in the
    JSON response (``side_cores``) even though only the combined body is
    exported to STEP.
    """
    operation = "mold-half STEP export"
    _, path = _part_path_or_raise(filename, operation)

    try:
        from backend.geometry.parting_line import detect_parting_line_candidates

        part = load_step_cached(path)
        pull_direction = (dx, dy, dz)
        if use_optimal_direction:
            direction = optimize_mold_direction(part)
            pull_direction = direction.best_direction
        part.optimal_pull_direction = pull_direction

        parting_result = detect_parting_line_candidates(
            part,
            pull_direction=pull_direction,
            mutate=False,
        )
        parting_sheet = (
            parting_result.parting_surface.occ_shape
            if parting_result.parting_surface.status.startswith("generated")
            else None
        )
        solid_result = split_core_cavity_solids(
            part,
            parting_sheet,
            pull_direction=pull_direction,
            loop_points=parting_result.wire_points,
        )
        prefix = filename.replace(".stp", "").replace(".step", "")

        side_core_result = None
        multi_side_core_result = None
        combined_side_cores: dict[str, object] = {}
        solid_overrides: dict[str, object] | None = None
        extra_solids: list[tuple[object, str]] | None = None
        if generate_side_core and solid_result.solid_split_status == "split_ok":
            undercut_result = detect_undercuts(
                part, pull_direction, mutate=False, boolean_refine=True,
            )
            side_core_result = generate_primary_side_core(
                part, undercut_result, solid_result,
            )
            if side_core_result.status == "generated":
                solid_overrides = {
                    side_core_result.containing_half: side_core_result.reduced_half_solid,
                }
                extra_solids = [
                    (side_core_result.side_core_solid, f"side_core_{side_core_result.feature_id}"),
                ]
        elif multi_feature_side_cores and solid_result.solid_split_status == "split_ok":
            severities = tuple(
                s.strip() for s in side_core_severities.split(",") if s.strip()
            )
            undercut_result = detect_undercuts(
                part, pull_direction, mutate=False, boolean_refine=True,
            )
            multi_side_core_result = generate_side_cores_for_features(
                part, undercut_result, solid_result,
                severities=severities, max_features=side_core_max_features,
            )
            combined_side_cores = combine_side_cores_per_half(solid_result, multi_side_core_result)
            solid_overrides = {}
            extra_solids = []
            for half, combined in combined_side_cores.items():
                if combined.status != "generated":
                    continue
                solid_overrides[half] = combined.reduced_half_solid
                extra_solids.append((combined.side_core_solid, f"side_core_combined_{half}"))
            if not solid_overrides:
                solid_overrides = None
            if not extra_solids:
                extra_solids = None

        export_result = export_mold_halves(
            solid_result,
            output_dir=output_dir,
            filename_prefix=f"{prefix}_mold_halves",
            solid_overrides=solid_overrides,
            extra_solids=extra_solids,
        )
        response: dict[str, Any] = {
            "filename": filename,
            "pull_direction": list(pull_direction),
            "parting_surface_status": parting_result.parting_surface.status,
            "solid_split": solid_result.to_dict(),
            "export": export_result,
        }
        if side_core_result is not None:
            response["side_core"] = side_core_result.to_dict()
        if multi_side_core_result is not None:
            response["side_cores"] = multi_side_core_result.to_dict()
            response["side_core_combined"] = {
                half: result.to_dict() for half, result in combined_side_cores.items()
            }
        return response
    except ImportError as exc:
        _raise_dependency_error(exc, operation)
    except ValueError as exc:
        _raise_value_error(exc, operation)
    except STEPLoadError as exc:
        _raise_step_error(exc, operation)


# ---------------------------------------------------------------------------
# Stage 5 — AI agent orchestration layer (roadmap §4.7)
# ---------------------------------------------------------------------------

@app.post("/parts/{filename}/agent/analyze")
def agent_analyze(
    filename: str,
    query: str | None = Query(default=None),
    provider: str | None = Query(default=None),
):
    """
    Run the full DfM tool-calling sweep (pull direction, draft, undercuts,
    parting line, core/cavity) via the configured LLM provider and return a
    structured `DfMReport`.

    `provider` overrides `settings.agent.provider` for this request only
    (gemini | anthropic | openai | grok) without touching the persisted
    config. `query` narrows the review to a specific engineer concern.
    """
    operation = "agent DfM analysis"
    _part_path_or_raise(filename, operation)

    from dataclasses import replace as dc_replace

    agent_settings = settings.agent
    if provider:
        agent_settings = dc_replace(agent_settings, provider=provider)

    try:
        from backend.agent.dfm_agent import run_dfm_analysis
        from backend.agent.providers import build_provider

        llm_provider = build_provider(agent_settings)
        report = run_dfm_analysis(filename, user_query=query, provider=llm_provider)
        return {"status": "ok", "report": report.model_dump(mode="json")}
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=_error_detail(
                code="agent_dependency_missing",
                message=str(exc),
                operation=operation,
                details={"provider": agent_settings.provider},
            ),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=_error_detail(
                code="agent_configuration_error",
                message=str(exc),
                operation=operation,
                details={"provider": agent_settings.provider},
            ),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=_error_detail(
                code="agent_provider_error",
                message=str(exc),
                operation=operation,
                details={"provider": agent_settings.provider, "exception_type": type(exc).__name__},
            ),
        ) from exc


@app.get("/agent/providers")
def agent_providers():
    """List which agent providers are importable in this environment, and which is configured."""
    availability: dict[str, bool] = {}
    for name, module_name in (
        ("gemini", "google.genai"), ("anthropic", "anthropic"), ("openai", "openai"),
    ):
        try:
            __import__(module_name)
            availability[name] = True
        except ImportError:
            availability[name] = False
    availability["grok"] = availability["openai"]  # same SDK, OpenAI-compatible endpoint

    return {
        "configured_provider": settings.agent.provider,
        "available": availability,
        "models": {
            "gemini": settings.agent.models.gemini,
            "anthropic": settings.agent.models.anthropic,
            "openai": settings.agent.models.openai,
            "grok": settings.agent.models.grok,
        },
    }


# ---------------------------------------------------------------------------
# Stage 6 — PDF report export (roadmap §5)
# ---------------------------------------------------------------------------

class ReportScreenshotPayload(BaseModel):
    """
    Optional request body for /export/report. The backend has no renderer
    and must not gain one (CLAUDE.md invariant #3 keeps OCC/rendering out of
    anything client-facing; the reverse holds too — the backend should not
    attempt to rasterize a viewport itself), so a screenshot can only ever
    arrive as frontend-supplied base64 PNG data. All-optional / has a
    default so a caller can omit the body entirely — the report must be
    generatable without a screenshot (roadmap §5.2).
    """
    screenshot_png_base64: Optional[str] = None


@app.post("/parts/{filename}/export/report")
def export_pdf_report(
    filename: str,
    use_optimal_direction: bool = Query(default=True),
    dx: float = Query(default=0.0),
    dy: float = Query(default=0.0),
    dz: float = Query(default=1.0),
    include_solid_split: bool = Query(default=True),
    include_side_core: bool = Query(default=False),
    include_agent_narrative: bool = Query(default=False),
    agent_provider: str | None = Query(default=None),
    screenshot: ReportScreenshotPayload = ReportScreenshotPayload(),
):
    """
    Generate a PDF DfM report (Stage 6) and return it as `application/pdf`.

    Runs the same pipeline as the analysis endpoints (draft, undercuts,
    direction, parting line, core/cavity) and hands the resulting
    `.to_dict()` payloads straight to `backend.report.pdf_export` — no new
    computation happens in the report layer (roadmap §5.5's honesty
    constraint). `include_solid_split`/`include_side_core`/
    `include_agent_narrative` are opt-in and each degrades gracefully: the
    report is always generatable with none of them. Set
    `use_optimal_direction=false` with `dx`/`dy`/`dz` for a manually
    supplied direction, matching every other endpoint's S3.6 pattern.
    """
    operation = "PDF report export"
    _, path = _part_path_or_raise(filename, operation)

    screenshot_png_bytes: bytes | None = None
    if screenshot.screenshot_png_base64:
        try:
            screenshot_png_bytes = base64.b64decode(screenshot.screenshot_png_base64, validate=True)
        except (base64.binascii.Error, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail=_error_detail(
                    code="invalid_screenshot", message=str(exc), operation=operation,
                ),
            ) from exc

    try:
        from backend.report.pdf_export import build_dfm_report_pdf

        part = load_step_cached(path)
        pull_direction = (dx, dy, dz)
        direction_result = None
        if use_optimal_direction:
            direction_result = optimize_mold_direction(part)
            pull_direction = direction_result.best_direction
            part.optimal_pull_direction = pull_direction

        draft_result = analyze_draft(part, pull_direction, mutate=False)
        undercut_result = detect_undercuts(part, pull_direction, mutate=False, boolean_refine=True)
        parting_result = detect_parting_line_candidates(
            part, pull_direction, undercut_context=undercut_result, mutate=False,
        )
        core_cavity_result = classify_core_cavity(part, pull_direction=pull_direction, mutate=False)

        solid_split_dict = None
        side_core_dict = None
        if include_solid_split:
            parting_sheet = (
                parting_result.parting_surface.occ_shape
                if parting_result.parting_surface.status.startswith("generated")
                else None
            )
            solid_result = split_core_cavity_solids(
                part, parting_sheet, pull_direction, loop_points=parting_result.wire_points,
            )
            solid_split_dict = solid_result.to_dict()
            if include_side_core and solid_result.solid_split_status == "split_ok":
                side_result = generate_primary_side_core(part, undercut_result, solid_result)
                side_core_dict = side_result.to_dict()

        agent_report_dict = None
        if include_agent_narrative:
            # Degrades gracefully: an unavailable/failed agent call must
            # never block the rest of the report from generating.
            try:
                from dataclasses import replace as dc_replace

                from backend.agent.dfm_agent import run_dfm_analysis
                from backend.agent.providers import build_provider

                agent_settings = settings.agent
                if agent_provider:
                    agent_settings = dc_replace(agent_settings, provider=agent_provider)
                llm_provider = build_provider(agent_settings)
                agent_report = run_dfm_analysis(filename, provider=llm_provider)
                agent_report_dict = agent_report.model_dump(mode="json")
            except Exception as exc:
                logger.warning("PDF export: AI agent narrative unavailable (%s): %s", operation, exc)

        pdf_bytes = build_dfm_report_pdf(
            filename=filename,
            part_summary=part.to_dict(include_faces=False),
            draft=draft_result.to_dict(),
            undercuts=undercut_result.to_dict(),
            parting_line=parting_result.to_dict(),
            core_cavity=core_cavity_result.to_dict(),
            direction=direction_result.to_dict(include_all_candidates=False) if direction_result else None,
            solid_split=solid_split_dict,
            side_core=side_core_dict,
            agent_report=agent_report_dict,
            screenshot_png=screenshot_png_bytes,
        )
        prefix = filename.replace(".stp", "").replace(".step", "")
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{prefix}_dfm_report.pdf"'},
        )
    except ImportError as exc:
        _raise_dependency_error(exc, operation)
    except ValueError as exc:
        _raise_value_error(exc, operation)
    except STEPLoadError as exc:
        _raise_step_error(exc, operation)
