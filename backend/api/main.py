import base64
import json
import logging
import math
import os
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
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
from backend.geometry.parting_line_v2.contracts import (
    CorePinFaceRef,
    DelegatedSecondaryAction,
    DelegationEvidence,
)
from backend.geometry.parting_line_v2.engine import analyse_parting_line
from backend.geometry.mold_orchestration import (
    prepare_manual_direction,
    resolve_authoritative_parting_line,
    resolve_manual_direction_mold,
    resolve_winning_direction_mold,
)
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
# F2: user-uploaded STEP files live here, never in data/parts/ -- CLAUDE.md's
# "never modify files in data/parts/" invariant is about that directory's
# curated, read-only fixtures; uploads are a separate, generated-content
# directory (same pattern as the existing gitignored output/mold_halves/).
UPLOADS_DIR = PROJECT_ROOT / "data" / "uploads"
# API/infra constant, not a DFM algorithm threshold -- lives here rather
# than config.yaml/Settings, matching this file's own existing convention
# for presentation/API-layer constants (BOOLEAN_REGION_STYLES, ERROR_HINTS)
# per .claude/rules/api-layer.md.
MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB


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
    "manual_review_undercut": {
        "label": "Manual review / possible undercut (Boolean inconclusive, risk evidence present)",
        "rgb": _rgb_byte_triplet(255, 180, 60),
        "priority": 30,
    },
    "zero_draft_not_applicable": {
        "label": "Zero-draft / not Boolean-testable (no risk evidence)",
        "rgb": _rgb_byte_triplet(200, 210, 225),
        "priority": 8,
    },
    "ray_verified_clear": {
        "label": "Ray-verified clear (geometric clearance check, not Boolean proof)",
        "rgb": _rgb_byte_triplet(150, 215, 180),
        "priority": 7,
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
    "no_file_provided": "Attach a .stp or .step file to the upload request.",
    "invalid_upload_extension": "Only .stp and .step files can be uploaded.",
    "empty_upload": "The uploaded file has no content.",
    "upload_too_large": f"Uploaded files must be {MAX_UPLOAD_BYTES // (1024 * 1024)} MB or smaller.",
    "export_file_not_found": "The exported STEP file was not found on the server -- it may have been cleaned up, or export never completed. Re-run the export.",
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

    # F2: an uploaded part's filename never collides with a curated
    # data/parts/ fixture (see part_upload's uuid-prefixing) -- checking
    # data/parts/ first preserves the exact pre-F2 resolution order for
    # every existing fixture-based test and call site.
    path = PARTS_DIR / safe_name
    if not path.exists():
        path = UPLOADS_DIR / safe_name
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=_error_detail(
                code="part_not_found",
                message=f"STEP file not found: {safe_name}",
                operation=operation,
                details={
                    "parts_dir": str(PARTS_DIR),
                    "uploads_dir": str(UPLOADS_DIR),
                    "filename": safe_name,
                },
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
    """
    Discovered during Stage 1 validation (2026-08-16): this previously always
    fell through to the feature-based fallback below for a raw
    ``UndercutDetectionResult`` dataclass (every real call site in this
    file), because ``boolean_refinement`` only exists as a key in
    ``.to_dict()``'s JSON output, never as a dataclass attribute --
    ``getattr(result, "boolean_refinement", {})`` always returned the `{}`
    default, which is itself a dict, so the ``isinstance(refinement, dict)``
    branch always ran and always returned ``[]`` from the empty placeholder,
    never reaching the correct ``getattr(result, "boolean_confirmed_face_ids",
    [])`` branch. The fallback's own ``evidence_source != "proxy"`` check is
    stale relative to the current evidence-source vocabulary (D-046/D-053:
    "proxy-only", "proxy-retained-after-boolean-failure", etc. -- none of
    which literally equal "proxy"), so it fired for every feature
    unconditionally, painting proxy-only and Boolean-failed faces as if
    Boolean-CONFIRMED. Fixed by checking the real field directly first, and
    only using the fallback when that field is genuinely absent (not merely
    empty) -- an empty ``boolean_confirmed_face_ids=[]`` must mean "nothing
    confirmed," never "field missing, guess from features."
    """
    direct = _undercut_result_value(result, "boolean_confirmed_face_ids", None)
    if direct is not None:
        return _as_int_set(direct)

    refinement = _undercut_result_value(result, "boolean_refinement", {}) or {}
    if isinstance(refinement, dict):
        nested = refinement.get("confirmed_face_ids", None)
        if nested is not None:
            return _as_int_set(nested)

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

    Boolean-confirmed faces use severity-based red/orange coloring.

    The legacy ``undercut_face_ids`` union (confirmed | failed | skipped |
    not_applicable, D-042's deliberately conservative "still flagged,
    uncertain" bucket) is NOT painted as one undifferentiated category here
    -- it remains available on the API response for compatibility/
    diagnostics, but the primary visualization instead distinguishes:

      1. CONFIRMED               -- boolean_confirmed_face_ids (unchanged)
      2. MANUAL_REVIEW            -- boolean_failed_face_ids that ALSO carry
                                      accessibility-risk evidence (a real
                                      signed g + concave edge): Boolean was
                                      attempted and could not resolve it, but
                                      there IS a positive reason to suspect
                                      this face, not just "couldn't test."
      3. ZERO_DRAFT_NOT_APPLICABLE -- boolean_not_applicable_face_ids with NO
                                      accessibility-risk evidence: exactly
                                      tangent to the pull direction (g=0 to
                                      float precision), structurally
                                      untestable, and nothing else about the
                                      face suggests it's suspicious. This was
                                      previously painted identically to (2),
                                      which is exactly the "large ordinary
                                      wall panels painted as undercut"
                                      problem this fixes.
      4. RAY_VERIFIED_CLEAR        -- ray_verified_clear_face_ids (D-061):
                                      an adaptive ray-based geometric
                                      clearance check converged to "no
                                      material found" BEFORE any Boolean was
                                      attempted. A positive, bounded-
                                      confidence geometric result -- NOT
                                      Boolean proof -- kept visually and
                                      semantically distinct from both
                                      CONFIRMED (real physical evidence) and
                                      ZERO_DRAFT_NOT_APPLICABLE (never
                                      independently verified at all).
      5. UNVERIFIED/OTHER          -- anything else left in the legacy union
                                      (e.g. boolean_skipped_face_ids, or the
                                      rare not_applicable-AND-risk overlap).

    Conflating (2) and (3) was the actual bug: both fell into a single
    "proxy_undercut" bucket regardless of whether the face carried any
    positive risk signal at all.
    """
    undercut_ids = _as_int_set(_undercut_result_value(result, "undercut_face_ids", []))
    parting_ids = _as_int_set(_undercut_result_value(result, "parting_face_ids", []))
    accessible_ids = _as_int_set(_undercut_result_value(result, "accessible_face_ids", []))
    confirmed_ids = _undercut_confirmed_face_ids(result)
    failed_ids = _as_int_set(_undercut_result_value(result, "boolean_failed_face_ids", []))
    not_applicable_ids = _as_int_set(_undercut_result_value(result, "boolean_not_applicable_face_ids", []))
    risk_ids = _as_int_set(_undercut_result_value(result, "accessibility_risk_face_ids", []))
    ray_verified_clear_ids = _as_int_set(_undercut_result_value(result, "ray_verified_clear_face_ids", []))
    manual_review_ids = failed_ids & risk_ids
    zero_draft_ids = not_applicable_ids - risk_ids
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
        elif face_id in manual_review_ids:
            style_key = "manual_review_undercut"
        elif face_id in zero_draft_ids:
            style_key = "zero_draft_not_applicable"
        elif face_id in ray_verified_clear_ids:
            style_key = "ray_verified_clear"
        elif face_id in undercut_ids:
            # Remaining legacy-union members not covered above (e.g.
            # boolean_skipped_face_ids, or a not_applicable face that also
            # carries risk evidence -- rare, but not silently dropped).
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


def _step_files(directory: Path) -> list[str]:
    if not directory.exists():
        return []
    return [
        p.name for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in {".stp", ".step"}
    ]


@app.get("/parts")
def list_parts():
    """
    List STEP files available for analysis -- the curated data/parts/
    fixtures plus any user-uploaded files (F2, data/uploads/), merged into
    one flat, sorted list. Upload filenames are uuid-prefixed (see
    part_upload) so a name collision between the two directories cannot
    happen; the merge is a plain union, not a dedupe.
    """
    if not PARTS_DIR.exists():
        return {
            "parts_dir": str(PARTS_DIR),
            "files": sorted(_step_files(UPLOADS_DIR)),
            "warnings": ["Parts directory does not exist."],
        }

    files = sorted(_step_files(PARTS_DIR) + _step_files(UPLOADS_DIR))
    return {
        "parts_dir": str(PARTS_DIR),
        "files": files,
    }


@app.post("/parts/upload")
async def part_upload(file: UploadFile = File(...)):
    """
    F2: accept a user-supplied STEP file and store it so every existing
    `/parts/{filename}/...` endpoint (summary, draft, direction, core-
    cavity, ...) can operate on it immediately via the SAME `filename`
    contract those endpoints already use -- no parallel upload-specific API
    surface. Stored in `data/uploads/`, never `data/parts/` (CLAUDE.md:
    that directory's fixtures are read-only).

    Validation is deliberately shallow here (extension, non-empty, size
    cap) -- deep STEP/geometry validation already exists and is NOT
    duplicated: the caller's very next request, `GET /parts/{filename}/
    summary`, runs `load_step()` and returns the existing structured
    `step_load_failed` error if the content isn't a valid STEP file.
    """
    operation = "STEP file upload"
    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail=_error_detail(code="no_file_provided", message="No file was attached.", operation=operation),
        )

    original_name = Path(file.filename).name
    if Path(original_name).suffix.lower() not in {".stp", ".step"}:
        raise HTTPException(
            status_code=400,
            detail=_error_detail(
                code="invalid_upload_extension",
                message=f"'{original_name}' is not a .stp/.step file.",
                operation=operation,
                details={"filename": original_name},
            ),
        )

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(
            status_code=400,
            detail=_error_detail(code="empty_upload", message=f"'{original_name}' is empty.", operation=operation),
        )
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=_error_detail(
                code="upload_too_large",
                message=f"'{original_name}' is {len(content)} bytes, over the {MAX_UPLOAD_BYTES} byte limit.",
                operation=operation,
                details={"size_bytes": len(content), "max_bytes": MAX_UPLOAD_BYTES},
            ),
        )

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    # uuid-prefixed so two uploads of the same original filename (or an
    # upload that happens to share a name with a data/parts/ fixture) never
    # collide -- this stored name is the `filename` every subsequent
    # /parts/{filename}/... call must use.
    stored_name = f"{uuid.uuid4().hex[:8]}_{original_name}"
    final_path = UPLOADS_DIR / stored_name
    tmp_path = UPLOADS_DIR / f".{stored_name}.part"
    tmp_path.write_bytes(content)
    os.replace(tmp_path, final_path)  # atomic on the same filesystem

    return {
        "filename": stored_name,
        "original_filename": original_name,
        "size_bytes": len(content),
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


def _parse_core_pin_face_refs(raw: str | None) -> tuple[CorePinFaceRef, ...]:
    """
    Parse the optional ``core_pin_face_refs`` JSON query parameter (plan
    D-043). ``None``/omitted -> ``()`` -- byte-identical to every call site
    before this parameter existed, since Round 1.5 never engages on an
    empty tuple. Raises ``ValueError`` on malformed input, caught by the
    caller's existing structured-error handling.
    """
    if raw is None:
        return ()
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"core_pin_face_refs is not valid JSON: {exc}") from exc
    if not isinstance(items, list):
        raise ValueError("core_pin_face_refs must be a JSON array.")

    refs = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"core_pin_face_refs[{i}] must be an object.")
        try:
            face_id = int(item["face_id"])
            axis = item["axis_direction"]
            reason = str(item["reason"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"core_pin_face_refs[{i}] must have face_id (int), "
                f"axis_direction ([x,y,z]), and reason (str): {exc}"
            ) from exc
        if not (isinstance(axis, list) and len(axis) == 3):
            raise ValueError(f"core_pin_face_refs[{i}].axis_direction must be a 3-element array.")
        refs.append(CorePinFaceRef(face_id, (float(axis[0]), float(axis[1]), float(axis[2])), reason))
    return tuple(refs)


def _parse_delegations(raw: str | None) -> tuple[DelegatedSecondaryAction, ...]:
    """
    Parse the optional ``delegations`` JSON query parameter (plan D-044).
    ``None``/omitted -> ``()`` -- byte-identical to every call site before
    this parameter existed, since H4 never excludes any face on an empty
    tuple. ``geometric_verification`` is deliberately NOT an accepted input
    field: every record is constructed through ``DelegationEvidence``'s own
    default, so the API has no way to report anything other than
    ``"unverified"`` regardless of what the caller sends. Raises
    ``ValueError`` on malformed input, caught by the caller's existing
    structured-error handling.
    """
    if raw is None:
        return ()
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"delegations is not valid JSON: {exc}") from exc
    if not isinstance(items, list):
        raise ValueError("delegations must be a JSON array.")

    delegations = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"delegations[{i}] must be an object.")
        try:
            face_ids = frozenset(int(f) for f in item["face_ids"])
            direction = item["movement_direction"]
            movement_type = str(item["movement_type"])
            source = str(item["source"])
            note = str(item["note"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"delegations[{i}] must have face_ids ([int,...]), "
                f"movement_direction ([x,y,z]), movement_type (str), "
                f"source (str), and note (str): {exc}"
            ) from exc
        if not (isinstance(direction, list) and len(direction) == 3):
            raise ValueError(f"delegations[{i}].movement_direction must be a 3-element array.")
        if not face_ids:
            raise ValueError(f"delegations[{i}].face_ids must not be empty.")
        delegations.append(DelegatedSecondaryAction(
            face_ids=face_ids,
            movement_direction=(float(direction[0]), float(direction[1]), float(direction[2])),
            movement_type=movement_type,
            evidence=DelegationEvidence(source=source, note=note),
        ))
    return tuple(delegations)


#: C18A: _resolve_v2_parting_line (C1, 2026-08-17) was removed here -- its
#: two remaining callers (/core-cavity, /export/report's unconditional
#: face-classification section) were both replaced by
#: resolve_authoritative_parting_line, fed by real undercut evidence
#: (direction.optimal_undercuts / prepare_manual_direction), eliminating
#: the undercuts=UndercutInput.empty() staleness C13/C17 identified. It had
#: zero remaining callers after that change (/parting-line-v2 has always
#: called analyse_parting_line directly, independently, with its own
#: deliberate undercuts=UndercutInput.empty() -- untouched, out of scope).


@app.get("/parts/{filename}/parting-line-v2")
def part_parting_line_v2(
    filename: str,
    dx: float = Query(default=0.0),
    dy: float = Query(default=0.0),
    dz: float = Query(default=1.0),
    include_mesh: bool = Query(default=True),
    include_mesh_geometry: bool = Query(default=True),
    mesh_deflection: float = Query(default=0.5, gt=0.0),
    core_pin_face_refs: str | None = Query(
        default=None,
        description='Optional JSON array (plan D-043): [{"face_id": int, '
                     '"axis_direction": [x,y,z], "reason": str}]. Omit for '
                     "today's default behaviour (Round 1.5 never engages).",
    ),
    delegations: str | None = Query(
        default=None,
        description='Optional JSON array (plan D-044): [{"face_ids": [int,...], '
                     '"movement_direction": [x,y,z], "movement_type": str, '
                     '"source": str, "note": str}]. Omit for today\'s default '
                     "behaviour (H4 never excludes any face). "
                     '"geometric_verification" is never accepted -- it always '
                     'reports "unverified".',
    ),
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

    `core_pin_face_refs`/`delegations` are optional, explicitly-authorized
    inputs threaded straight through to `analyse_parting_line` (plan
    D-043/D-044) -- this endpoint performs no discovery or inference of its
    own. Omitting either preserves this endpoint's exact pre-existing
    behaviour, since both default to `()` at the engine layer too.

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

        parsed_core_pin_face_refs = _parse_core_pin_face_refs(core_pin_face_refs)
        parsed_delegations = _parse_delegations(delegations)

        part = load_step_cached(path)
        pull = PullDirectionInput(direction, "manual")
        cfg = settings.dfm.parting_line_v2
        result = analyse_parting_line(
            part, pull, undercuts=UndercutInput.empty(), cfg=cfg,
            core_pin_face_refs=parsed_core_pin_face_refs,
            delegations=parsed_delegations,
        )

        payload: dict[str, Any] = result.to_dict()
        payload["engine"] = "parting_line_v2"
        payload["status_note"] = (
            "Experimental Level 0-2 engine, not yet the default. No parting-surface "
            "generation or core/cavity SOLID split at this level -- see "
            "docs/IMPLEMENTATION_STATUS.md for the authoritative capability list."
        )

        # Independent, read-only undercut detection for DISPLAY only -- this
        # is never passed into analyse_parting_line above (which still gets
        # UndercutInput.empty(), preserving the exact H4/H5 behaviour already
        # verified for candidate 110). Matches D-044's own frozen invariant
        # that undercut detection stays independent of everything else.
        undercut_result = detect_undercuts(part, direction, mutate=False, boolean_refine=False)
        payload["undercuts"] = undercut_result.to_dict()

        if result.selected is not None:
            payload["parting_line_path"] = {
                "label": "Parting Line v2 (selected candidate)",
                "points": [[round(c, 6) for c in p] for p in result.selected.points],
                "hex": "#22c55e",
                "width": 6,
            }

        if include_mesh:
            mesh = build_display_mesh(part, linear_deflection=mesh_deflection)
            mesh_payload = mesh.to_payload(include_geometry=include_mesh_geometry)

            mesh_payload.update(_undercut_mesh_visual_payload(undercut_result, mesh))

            # Core/cavity tint: retired server-side "pv2_region_rgb" here
            # (Phase 4, docs/DECISIONS_AND_ALGORITHMS.md D-045) -- it only
            # distinguished cavity/core by raw H3 component membership, never
            # the split/ambiguous labels, and a repo-wide search found zero
            # consumers of this key. The frontend already owns core/cavity
            # compositing for this tab (it independently overlays undercuts,
            # core-pin, and delegation groups on top), and builds its own
            # label-aware coloring directly from `payload["regions"]["faces"]`
            # (RegionClassification.to_dict(), unaffected by this removal).

            # Core-pin interface highlight (D-043) -- metadata annotation
            # only; never a curve, never mixed into the Γ overlay itself.
            if result.selected is not None and result.selected.core_pin_interfaces:
                core_pin_ids = {i.face_id for i in result.selected.core_pin_interfaces}
                mesh_payload["pv2_core_pin_rgb"] = [
                    [0.85, 0.15, 0.85] if fid in core_pin_ids else [0.55, 0.55, 0.55]
                    for fid in mesh.face_ids
                ]

            # Validated delegation groups (D-044) -- each authorized,
            # structurally-validated group gets its own colour so mirror
            # groups stay visually distinct, never merged.
            if result.selected is not None and result.selected.feasibility is not None:
                validated = result.selected.feasibility.validated_delegations
                if validated:
                    palette = [
                        [0.95, 0.75, 0.10], [0.10, 0.75, 0.95],
                        [0.75, 0.10, 0.95], [0.10, 0.95, 0.45],
                    ]
                    face_to_group: dict[int, int] = {}
                    for group_index, delegation in enumerate(validated):
                        for fid in delegation.face_ids:
                            face_to_group[fid] = group_index
                    mesh_payload["pv2_delegation_rgb"] = [
                        palette[face_to_group[fid] % len(palette)]
                        if fid in face_to_group else [0.55, 0.55, 0.55]
                        for fid in mesh.face_ids
                    ]

            payload["display_mesh"] = mesh_payload

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
    core_pin_face_refs: str | None = Query(
        default=None,
        description='Optional JSON array (plan D-043), threaded straight through '
                     "to parting_line_v2 -- see /parting-line-v2's description. "
                     "Omit for today's default behaviour.",
    ),
    delegations: str | None = Query(
        default=None,
        description='Optional JSON array (plan D-044), threaded straight through '
                     "to parting_line_v2 -- see /parting-line-v2's description. "
                     "Omit for today's default behaviour.",
    ),
):
    """
    Classify faces as cavity, core, or parting relative to the pull direction.

    Level 1: face classification (always returned).
    Milestone 1.10: set ``solid_split=true`` to also run the Boolean mold-half split.

    C1 (2026-08-17): both Level 1 classification and the solid split are now
    sourced from the AUTHORITATIVE ``parting_line_v2`` pipeline
    (``analyse_parting_line``), never the legacy ``parting_line.py`` module.
    Face classification uses ``RegionClassification`` (graph-connectivity-
    based, straddle-aware) whenever v2 finds a feasible candidate for this
    direction; it falls back to the pre-existing single-normal test only
    when v2 does not (e.g. an infeasible/unauthorized direction). The
    Boolean solid split additionally REQUIRES a v2-feasible candidate --
    core/cavity does not decide feasibility itself (that stays
    ``direction_optimizer`` -> ``parting_line_v2`` -> H0-H7's job); an
    infeasible/unauthorized direction reports
    ``solid_split_status="blocked_by_parting_line"`` and the Boolean split
    never runs, with no fallback to the legacy module. ``core_pin_face_refs``/
    ``delegations`` are optional, explicitly-authorized inputs threaded
    straight through to both ``optimize_mold_direction`` and
    ``analyse_parting_line`` -- this endpoint performs no discovery or
    inference of its own.

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
        parsed_core_pin_face_refs = _parse_core_pin_face_refs(core_pin_face_refs)
        parsed_delegations = _parse_delegations(delegations)

        part = load_step_cached(path)
        pull_direction = (dx, dy, dz)
        pull_direction_source = "manual_query_direction"

        # C18A: eliminates the stale _resolve_v2_parting_line(undercuts=
        # UndercutInput.empty()) duplication (C13/C17 finding) -- face
        # classification below now uses the SAME real-undercut-aware
        # parting-line result the solid-split orchestration uses, computed
        # via the SAME resolve_authoritative_parting_line/
        # prepare_manual_direction helpers, and threaded into the
        # orchestration call further down as precomputed_pl_result so it is
        # never derived twice.
        undercuts_for_pl = None
        manual_invalid: object = None
        if use_optimal_direction:
            direction = optimize_mold_direction(
                part,
                core_pin_face_refs=parsed_core_pin_face_refs,
                delegations=parsed_delegations,
            )
            pull_direction = direction.best_direction
            pull_direction_source = "optimal_mold_direction"
            part.optimal_pull_direction = pull_direction
            undercuts_for_pl = direction.optimal_undercuts
        else:
            normalized, undercuts_for_pl, manual_invalid = prepare_manual_direction(part, pull_direction)
            if manual_invalid is None:
                pull_direction = normalized
                part.optimal_pull_direction = pull_direction

        pl_result = None
        if manual_invalid is None:
            pl_result = resolve_authoritative_parting_line(
                part, pull_direction, undercuts_for_pl,
                core_pin_face_refs=parsed_core_pin_face_refs, delegations=parsed_delegations,
                source_label="optimizer" if use_optimal_direction else "manual",
            )

        result = classify_core_cavity(
            part,
            pull_direction=pull_direction,
            threshold=threshold,
            mutate=True,
            region_classification=pl_result.regions if pl_result is not None else None,
        )
        payload: dict[str, Any] = {
            "part": part.to_dict(include_faces=include_faces),
            "core_cavity": result.to_dict(),
            "pull_direction_source": pull_direction_source,
            "parting_line_v2_outcome": pl_result.outcome if pl_result is not None else None,
        }
        if manual_invalid is not None:
            payload["orchestration"] = manual_invalid.to_dict()

        # Milestone 1.10: optional Boolean solid split.
        if solid_split and use_optimal_direction:
            # C14: the ONE winning-direction orchestration chain -- requires
            # optimal_found=True (never proceeds on best_unverified_
            # candidate), re-derives the parting-line result with the SAME
            # real undercut evidence the optimizer's own search used
            # (fixing the undercuts=UndercutInput.empty() gap C13 found),
            # and threads validated delegations into side-core feature
            # selection before generation. Replaces the ad hoc
            # detect_undercuts()+generate_*_side_core() calls previously
            # inlined here.
            severities = tuple(
                s.strip() for s in side_core_severities.split(",") if s.strip()
            ) or ("critical",)
            if generate_side_core:
                orchestration = resolve_winning_direction_mold(
                    part, direction,
                    core_pin_face_refs=parsed_core_pin_face_refs,
                    delegations=parsed_delegations,
                    primary_only=True,
                    generate_side_cores=True,
                    precomputed_pl_result=pl_result,
                )
                payload["solid_split"] = (
                    orchestration.split_result.to_dict() if orchestration.split_result else None
                )
                payload["orchestration"] = orchestration.to_dict()
                if orchestration.multi_side_core_result is not None:
                    generated = orchestration.multi_side_core_result.generated_results
                    payload["side_core"] = (
                        generated[0].to_dict() if generated
                        else orchestration.multi_side_core_result.to_dict()
                    )
            if multi_feature_side_cores:
                orchestration = resolve_winning_direction_mold(
                    part, direction,
                    core_pin_face_refs=parsed_core_pin_face_refs,
                    delegations=parsed_delegations,
                    severities=severities, max_features=side_core_max_features,
                    primary_only=False,
                    generate_side_cores=True,
                    precomputed_pl_result=pl_result,
                )
                payload["solid_split"] = (
                    orchestration.split_result.to_dict() if orchestration.split_result else None
                )
                payload["orchestration"] = orchestration.to_dict()
                if orchestration.multi_side_core_result is not None:
                    payload["side_cores"] = orchestration.multi_side_core_result.to_dict()
                payload["side_core_combined"] = {
                    half: r.to_dict() for half, r in orchestration.combined_side_cores.items()
                }
            if not generate_side_core and not multi_feature_side_cores:
                orchestration = resolve_winning_direction_mold(
                    part, direction,
                    core_pin_face_refs=parsed_core_pin_face_refs,
                    delegations=parsed_delegations,
                    generate_side_cores=False,
                    precomputed_pl_result=pl_result,
                )
                payload["solid_split"] = (
                    orchestration.split_result.to_dict() if orchestration.split_result else None
                )
                payload["orchestration"] = orchestration.to_dict()
        elif solid_split and manual_invalid is None:
            # C16/C18A: manual/override direction (Stage 3 S3.6) now runs
            # through the EXACT SAME orchestration core as the automatic
            # path -- resolve_manual_direction_mold's validation/
            # normalization/undercut-detection was already done above
            # (prepare_manual_direction) and its result reused here via
            # precomputed_undercuts/precomputed_pl_result, so neither
            # detect_undercuts nor analyse_parting_line runs a second time
            # for this direction. Never fabricates a
            # DirectionOptimizationResult/optimal_found -- see
            # resolve_manual_direction_mold's own docstring.
            severities = tuple(
                s.strip() for s in side_core_severities.split(",") if s.strip()
            ) or ("critical",)
            if generate_side_core:
                orchestration = resolve_manual_direction_mold(
                    part, pull_direction,
                    core_pin_face_refs=parsed_core_pin_face_refs,
                    delegations=parsed_delegations,
                    primary_only=True,
                    generate_side_cores=True,
                    precomputed_undercuts=undercuts_for_pl,
                    precomputed_pl_result=pl_result,
                )
                payload["solid_split"] = (
                    orchestration.split_result.to_dict() if orchestration.split_result else None
                )
                payload["orchestration"] = orchestration.to_dict()
                if orchestration.multi_side_core_result is not None:
                    generated = orchestration.multi_side_core_result.generated_results
                    payload["side_core"] = (
                        generated[0].to_dict() if generated
                        else orchestration.multi_side_core_result.to_dict()
                    )
            if multi_feature_side_cores:
                orchestration = resolve_manual_direction_mold(
                    part, pull_direction,
                    core_pin_face_refs=parsed_core_pin_face_refs,
                    delegations=parsed_delegations,
                    severities=severities, max_features=side_core_max_features,
                    primary_only=False,
                    generate_side_cores=True,
                    precomputed_undercuts=undercuts_for_pl,
                    precomputed_pl_result=pl_result,
                )
                payload["solid_split"] = (
                    orchestration.split_result.to_dict() if orchestration.split_result else None
                )
                payload["orchestration"] = orchestration.to_dict()
                if orchestration.multi_side_core_result is not None:
                    payload["side_cores"] = orchestration.multi_side_core_result.to_dict()
                payload["side_core_combined"] = {
                    half: r.to_dict() for half, r in orchestration.combined_side_cores.items()
                }
            if not generate_side_core and not multi_feature_side_cores:
                orchestration = resolve_manual_direction_mold(
                    part, pull_direction,
                    core_pin_face_refs=parsed_core_pin_face_refs,
                    delegations=parsed_delegations,
                    generate_side_cores=False,
                    precomputed_undercuts=undercuts_for_pl,
                    precomputed_pl_result=pl_result,
                )
                payload["solid_split"] = (
                    orchestration.split_result.to_dict() if orchestration.split_result else None
                )
                payload["orchestration"] = orchestration.to_dict()

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
    core_pin_face_refs: str | None = Query(
        default=None,
        description='Optional JSON array (plan D-043), threaded straight through '
                     "to parting_line_v2 -- see /parting-line-v2's description. "
                     "Omit for today's default behaviour.",
    ),
    delegations: str | None = Query(
        default=None,
        description='Optional JSON array (plan D-044), threaded straight through '
                     "to parting_line_v2 -- see /parting-line-v2's description. "
                     "Omit for today's default behaviour.",
    ),
):
    """
    Export cavity and core mold-half solids as a multi-body AP214 STEP file (Milestone 1.11).

    C1 (2026-08-17): the parting-line loop now comes from the AUTHORITATIVE
    ``parting_line_v2`` pipeline, never the legacy ``parting_line.py``
    module. If v2 finds no feasible candidate for this exact direction/
    authorization, the export reports ``solid_split_status=
    "blocked_by_parting_line"`` and no Boolean split runs -- there is no
    fallback to the legacy module. ``core_pin_face_refs``/``delegations``
    are optional, explicitly-authorized inputs threaded straight through to
    both ``optimize_mold_direction`` and ``analyse_parting_line``.

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
        parsed_core_pin_face_refs = _parse_core_pin_face_refs(core_pin_face_refs)
        parsed_delegations = _parse_delegations(delegations)

        part = load_step_cached(path)
        pull_direction = (dx, dy, dz)
        prefix = filename.replace(".stp", "").replace(".step", "")

        side_core_result = None
        multi_side_core_result = None
        combined_side_cores: dict[str, object] = {}
        solid_overrides: dict[str, object] | None = None
        extra_solids: list[tuple[object, str]] | None = None
        orchestration = None

        if use_optimal_direction:
            direction = optimize_mold_direction(
                part,
                core_pin_face_refs=parsed_core_pin_face_refs,
                delegations=parsed_delegations,
            )
            pull_direction = direction.best_direction
            part.optimal_pull_direction = pull_direction

            # C14: the ONE winning-direction orchestration chain -- requires
            # optimal_found=True, re-derives the parting-line result with
            # the SAME real undercut evidence the optimizer's own search
            # used (fixing the undercuts=UndercutInput.empty() gap C13
            # found), and threads validated delegations into side-core
            # feature selection before generation.
            severities = tuple(
                s.strip() for s in side_core_severities.split(",") if s.strip()
            ) or ("critical",)
            orchestration = resolve_winning_direction_mold(
                part, direction,
                core_pin_face_refs=parsed_core_pin_face_refs,
                delegations=parsed_delegations,
                severities=severities, max_features=side_core_max_features,
                primary_only=(generate_side_core and not multi_feature_side_cores),
                generate_side_cores=(generate_side_core or multi_feature_side_cores),
            )
            solid_result = orchestration.split_result
            if solid_result is None:
                response = {
                    "filename": filename,
                    "pull_direction": list(pull_direction),
                    "orchestration": orchestration.to_dict(),
                    "export": None,
                }
                return response

            if orchestration.multi_side_core_result is not None:
                generated = orchestration.multi_side_core_result.generated_results
                if generate_side_core and not multi_feature_side_cores:
                    if generated:
                        side_core_result = generated[0]
                        solid_overrides = {
                            side_core_result.containing_half: side_core_result.reduced_half_solid,
                        }
                        extra_solids = [
                            (side_core_result.side_core_solid, f"side_core_{side_core_result.feature_id}"),
                        ]
                else:
                    multi_side_core_result = orchestration.multi_side_core_result
                    combined_side_cores = orchestration.combined_side_cores
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
        else:
            # C16: manual/override direction (Stage 3 S3.6) now runs through
            # the EXACT SAME orchestration core as the automatic path above
            # -- resolve_manual_direction_mold normalizes/validates
            # pull_direction, computes real undercut evidence for it, and
            # calls the shared _resolve_mold_for_direction chain. Never
            # fabricates a DirectionOptimizationResult/optimal_found.
            part.optimal_pull_direction = pull_direction
            severities = tuple(
                s.strip() for s in side_core_severities.split(",") if s.strip()
            ) or ("critical",)
            orchestration = resolve_manual_direction_mold(
                part, pull_direction,
                core_pin_face_refs=parsed_core_pin_face_refs,
                delegations=parsed_delegations,
                severities=severities, max_features=side_core_max_features,
                primary_only=(generate_side_core and not multi_feature_side_cores),
                generate_side_cores=(generate_side_core or multi_feature_side_cores),
            )
            solid_result = orchestration.split_result
            if solid_result is None:
                response = {
                    "filename": filename,
                    "pull_direction": list(pull_direction),
                    "orchestration": orchestration.to_dict(),
                    "export": None,
                }
                return response

            if orchestration.multi_side_core_result is not None:
                generated = orchestration.multi_side_core_result.generated_results
                if generate_side_core and not multi_feature_side_cores:
                    if generated:
                        side_core_result = generated[0]
                        solid_overrides = {
                            side_core_result.containing_half: side_core_result.reduced_half_solid,
                        }
                        extra_solids = [
                            (side_core_result.side_core_solid, f"side_core_{side_core_result.feature_id}"),
                        ]
                else:
                    multi_side_core_result = orchestration.multi_side_core_result
                    combined_side_cores = orchestration.combined_side_cores
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
            "solid_split": solid_result.to_dict(),
            "export": export_result,
        }
        if orchestration is not None:
            response["orchestration"] = orchestration.to_dict()
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


@app.get("/export/download/{filename}")
def export_download(filename: str):
    """
    F6: retrieve the bytes of a STEP file `POST /parts/{filename}/export/
    mold-halves` already wrote to disk (`export.download_filename` in that
    endpoint's response). `/export/mold-halves` itself only ever returns a
    server-side filesystem path -- there was previously no way for a
    browser client to actually download the file it names; this is the
    minimal endpoint that closes that gap. Scoped strictly to
    `settings.dfm.core_cavity.export_dir` (never an arbitrary path) via the
    same basename-only guard `_part_path_or_raise` already uses.
    """
    operation = "STEP export download"
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(
            status_code=400,
            detail=_error_detail(code="invalid_filename", message="filename must not contain path separators", operation=operation, details={"filename": filename}),
        )
    export_dir = Path(settings.dfm.core_cavity.export_dir).resolve()
    path = export_dir / safe_name
    if not path.exists() or not path.is_file():
        raise HTTPException(
            status_code=404,
            detail=_error_detail(code="export_file_not_found", message=f"Exported file not found: {safe_name}", operation=operation, details={"export_dir": str(export_dir), "filename": safe_name}),
        )
    return FileResponse(path, media_type="application/octet-stream", filename=safe_name)


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
    include_executive_summary: bool = Query(default=True),
    agent_provider: str | None = Query(default=None),
    screenshot: ReportScreenshotPayload = ReportScreenshotPayload(),
    core_pin_face_refs: str | None = Query(
        default=None,
        description='Optional JSON array (plan D-043), threaded straight through '
                     "to parting_line_v2 -- see /parting-line-v2's description. "
                     "Omit for today's default behaviour.",
    ),
    delegations: str | None = Query(
        default=None,
        description='Optional JSON array (plan D-044), threaded straight through '
                     "to parting_line_v2 -- see /parting-line-v2's description. "
                     "Omit for today's default behaviour.",
    ),
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

    C1 (2026-08-17): the report's own "parting line" section still reports
    the legacy `parting_line.py` candidate (unrelated to core/cavity —
    that section's own display data, unchanged this phase). The Boolean
    SOLID SPLIT (`include_solid_split=true`), however, now sources its
    loop from the AUTHORITATIVE `parting_line_v2` pipeline, never the
    legacy module -- an infeasible/unauthorized direction reports
    `solid_split_status="blocked_by_parting_line"` with no split attempted
    and no fallback to the legacy module. `core_pin_face_refs`/
    `delegations` are threaded through to both `optimize_mold_direction`
    and `analyse_parting_line`.

    F6 (2026-08-17): `include_executive_summary` (default true) prepends a
    one-block "read this first" verdict/summary -- see
    `build_dfm_report_pdf`'s own docstring; it is derived entirely from
    the same dicts every other section already renders from, never a new
    computation, and every other section's inclusion logic is unchanged.
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

        parsed_core_pin_face_refs = _parse_core_pin_face_refs(core_pin_face_refs)
        parsed_delegations = _parse_delegations(delegations)

        part = load_step_cached(path)
        pull_direction = (dx, dy, dz)
        direction_result = None
        # C18A: eliminates the stale _resolve_v2_parting_line(undercuts=
        # UndercutInput.empty()) duplication AND the separate detect_
        # undercuts() call this endpoint previously ran unconditionally
        # (C13/C17 finding). undercuts_for_pl is now the SAME real evidence
        # reused for the PDF's own "undercuts" section, the authoritative
        # parting-line derivation below, AND (when include_solid_split is
        # requested) the orchestration -- computed exactly once.
        if use_optimal_direction:
            direction_result = optimize_mold_direction(
                part,
                core_pin_face_refs=parsed_core_pin_face_refs,
                delegations=parsed_delegations,
            )
            pull_direction = direction_result.best_direction
            part.optimal_pull_direction = pull_direction
            undercuts_for_pl = direction_result.optimal_undercuts
        else:
            normalized, undercuts_for_pl, invalid = prepare_manual_direction(part, pull_direction)
            if invalid is not None:
                raise ValueError(invalid.failure_reason)
            pull_direction = normalized
            part.optimal_pull_direction = pull_direction

        draft_result = analyze_draft(part, pull_direction, mutate=False)
        undercut_result = undercuts_for_pl
        # Legacy parting_line.py is kept HERE only for the report's own
        # separate "parting line" display section -- unrelated to
        # core/cavity, unchanged this phase (see docstring above).
        parting_result = detect_parting_line_candidates(
            part, pull_direction, undercut_context=undercut_result, mutate=False,
        )

        # C18A: the ONE authoritative, real-undercut-aware parting_line_v2
        # call for this direction -- feeds BOTH core/cavity classification
        # and (reused via precomputed_pl_result below) the solid split.
        pl_result = resolve_authoritative_parting_line(
            part, pull_direction, undercuts_for_pl,
            core_pin_face_refs=parsed_core_pin_face_refs, delegations=parsed_delegations,
            source_label="optimizer" if use_optimal_direction else "manual",
        )
        core_cavity_result = classify_core_cavity(
            part, pull_direction=pull_direction, mutate=False,
            region_classification=pl_result.regions,
        )

        solid_split_dict = None
        side_core_dict = None
        if include_solid_split and use_optimal_direction:
            # C14: the ONE winning-direction orchestration chain -- requires
            # optimal_found=True (never proceeds on best_unverified_
            # candidate), re-derives the parting-line result with the SAME
            # real undercut evidence the optimizer's own search used
            # (fixing the undercuts=UndercutInput.empty() gap C13 found),
            # and threads validated delegations into side-core feature
            # selection before generation.
            orchestration = resolve_winning_direction_mold(
                part, direction_result,
                core_pin_face_refs=parsed_core_pin_face_refs,
                delegations=parsed_delegations,
                primary_only=True,
                generate_side_cores=include_side_core,
                precomputed_pl_result=pl_result,
            )
            solid_split_dict = (
                orchestration.split_result.to_dict() if orchestration.split_result else None
            )
            if include_side_core and orchestration.multi_side_core_result is not None:
                generated = orchestration.multi_side_core_result.generated_results
                side_core_dict = (
                    generated[0].to_dict() if generated
                    else orchestration.multi_side_core_result.to_dict()
                )
        elif include_solid_split:
            # C16/C18A: manual/override direction (Stage 3 S3.6) now runs
            # through the EXACT SAME orchestration core as the automatic
            # path above -- validation/normalization/undercut-detection was
            # already done above (prepare_manual_direction) and reused here
            # via precomputed_undercuts/precomputed_pl_result, so neither
            # detect_undercuts nor analyse_parting_line runs a second time.
            # Never fabricates a DirectionOptimizationResult/optimal_found.
            orchestration = resolve_manual_direction_mold(
                part, pull_direction,
                core_pin_face_refs=parsed_core_pin_face_refs,
                delegations=parsed_delegations,
                primary_only=True,
                generate_side_cores=include_side_core,
                precomputed_undercuts=undercuts_for_pl,
                precomputed_pl_result=pl_result,
            )
            solid_split_dict = (
                orchestration.split_result.to_dict() if orchestration.split_result else None
            )
            if include_side_core and orchestration.multi_side_core_result is not None:
                generated = orchestration.multi_side_core_result.generated_results
                side_core_dict = (
                    generated[0].to_dict() if generated
                    else orchestration.multi_side_core_result.to_dict()
                )

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
            include_executive_summary=include_executive_summary,
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
