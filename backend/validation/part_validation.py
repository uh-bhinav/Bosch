"""
backend/validation/part_validation.py
-------------------------------------
Reusable validation harness for Bosch STEP demo files.

This module is intentionally conservative: it validates every available STEP
file in ``data/parts`` and reports missing expected files separately.  That
lets us be honest about Part2 readiness without pretending to test a file that
is not present in the workspace.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PARTS_DIR = PROJECT_ROOT / "data" / "parts"
DEFAULT_EXPECTED_FILES = ("Part1.stp", "Part2.stp")


@dataclass(frozen=True)
class ValidationStepResult:
    """Result for one validation step."""

    name: str
    status: str
    elapsed_s: float
    message: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "elapsed_s": round(self.elapsed_s, 4),
            "message": self.message,
            "metrics": self.metrics,
        }


@dataclass(frozen=True)
class PartValidationResult:
    """Validation result for one STEP file."""

    filename: str
    path: str
    status: str
    steps: list[ValidationStepResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "path": self.path,
            "status": self.status,
            "steps": [step.to_dict() for step in self.steps],
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class ValidationSuiteResult:
    """Validation result for all discovered demo STEP files."""

    parts_dir: str
    expected_files: list[str]
    discovered_files: list[str]
    missing_expected_files: list[str]
    part_results: list[PartValidationResult]

    @property
    def status(self) -> str:
        if any(result.status == "failed" for result in self.part_results):
            return "failed"
        if any(result.status == "skipped" for result in self.part_results):
            return "warning"
        if self.missing_expected_files:
            return "warning"
        if not self.part_results:
            return "warning"
        return "passed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "parts_dir": self.parts_dir,
            "expected_files": self.expected_files,
            "discovered_files": self.discovered_files,
            "missing_expected_files": self.missing_expected_files,
            "part_results": [result.to_dict() for result in self.part_results],
        }


def discover_step_files(parts_dir: Path = DEFAULT_PARTS_DIR) -> list[Path]:
    """Return sorted STEP files in a parts directory."""
    if not parts_dir.exists():
        return []
    return sorted(
        path
        for path in parts_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".stp", ".step"}
    )


def missing_expected_files(
    parts_dir: Path = DEFAULT_PARTS_DIR,
    expected_files: tuple[str, ...] = DEFAULT_EXPECTED_FILES,
) -> list[str]:
    """Return expected demo files that are not present."""
    return [
        filename
        for filename in expected_files
        if not (parts_dir / filename).exists()
    ]


def _step_result(
    name: str,
    status: str,
    start_s: float,
    *,
    message: str = "",
    metrics: dict[str, Any] | None = None,
) -> ValidationStepResult:
    return ValidationStepResult(
        name=name,
        status=status,
        elapsed_s=time.perf_counter() - start_s,
        message=message,
        metrics=metrics or {},
    )


def _run_step(
    name: str,
    fn: Callable[[], dict[str, Any] | None],
) -> ValidationStepResult:
    start_s = time.perf_counter()
    try:
        metrics = fn() or {}
    except ImportError as exc:
        return _step_result(
            name,
            "skipped",
            start_s,
            message=f"Runtime dependency unavailable: {exc}",
        )
    except Exception as exc:  # noqa: BLE001 - validation should report failures, not hide them.
        return _step_result(
            name,
            "failed",
            start_s,
            message=str(exc) or exc.__class__.__name__,
        )
    return _step_result(name, "passed", start_s, metrics=metrics)


def _topology_metrics(part: Any) -> dict[str, Any]:
    valid_normals = sum(1 for face in part.faces if getattr(face, "normal_valid", False))
    valid_normal_ratio = valid_normals / part.face_count if part.face_count else 0.0
    bbox = part.bounding_box
    return {
        "solid_count": part.solid_count,
        "face_count": part.face_count,
        "edge_count": part.edge_count,
        "vertex_count": part.vertex_count,
        "bbox_diagonal_mm": round(float(bbox.diagonal), 4),
        "valid_normal_ratio": round(valid_normal_ratio, 4),
        "warnings": list(getattr(part, "warnings", []) or []),
    }


def _validate_topology(part: Any) -> dict[str, Any]:
    metrics = _topology_metrics(part)
    if part.solid_count < 1:
        raise ValueError("Loaded part has no solids.")
    if part.face_count < 1:
        raise ValueError("Loaded part has no faces.")
    if part.bounding_box.diagonal <= 0.0:
        raise ValueError("Loaded part has a non-positive bounding-box diagonal.")
    if metrics["valid_normal_ratio"] < 0.80:
        raise ValueError(
            f"Only {metrics['valid_normal_ratio']:.1%} faces have valid normals."
        )
    return metrics


def _parting_line_metrics(result: Any) -> dict[str, Any]:
    """Return compact validation/profiling metrics from a parting-line result."""
    readiness = getattr(result, "readiness", None)
    diagnostic_gate = getattr(result, "diagnostic_gate", None)
    diagnostics = getattr(result, "diagnostics", None)
    quality = getattr(result, "selection_quality", None)
    conflict = getattr(result, "undercut_conflict", None)
    refinement = getattr(result, "refinement", None)

    candidate_edge_ids = list(getattr(result, "candidate_edge_ids", []) or [])
    silhouette_edge_ids = list(getattr(result, "silhouette_edge_ids", []) or [])
    selected_edge_ids = list(getattr(result, "selected_edge_ids", []) or [])
    components = list(getattr(result, "components", []) or [])
    warnings = list(getattr(result, "warnings", []) or [])

    readiness_blockers = list(getattr(readiness, "blockers", []) or [])
    readiness_reasons = list(getattr(readiness, "reasons", []) or [])

    return {
        "selected_edge_count": len(selected_edge_ids),
        "candidate_edge_count": len(candidate_edge_ids),
        "silhouette_edge_count": len(silhouette_edge_ids),
        "component_count": len(components),
        "readiness_status": getattr(readiness, "status", "unknown"),
        "readiness_score": round(float(getattr(readiness, "score", 0.0) or 0.0), 4),
        "readiness_reasons": readiness_reasons,
        "readiness_blockers": readiness_blockers,
        "gate_status": getattr(diagnostic_gate, "status", "unknown"),
        "gate_can_display_curve": bool(
            getattr(diagnostic_gate, "can_display_curve", False)
        ),
        "gate_can_use_for_report": bool(
            getattr(diagnostic_gate, "can_use_for_report", False)
        ),
        "gate_blocks_core_cavity": bool(
            getattr(diagnostic_gate, "blocks_core_cavity", False)
        ),
        "gate_requires_manual_review": bool(
            getattr(diagnostic_gate, "requires_manual_review", True)
        ),
        "diagnostics_status": getattr(diagnostics, "status", "unknown"),
        "diagnostics_failure_code": getattr(diagnostics, "failure_code", None),
        "diagnostics_skipped_edge_count": int(
            getattr(diagnostics, "skipped_edge_count", 0) or 0
        ),
        "diagnostics_unorderable_edge_count": int(
            getattr(diagnostics, "unorderable_edge_count", 0) or 0
        ),
        "selection_quality_level": getattr(quality, "level", "unknown"),
        "selection_quality_score": round(float(getattr(quality, "score", 0.0) or 0.0), 4),
        "undercut_conflict_level": getattr(conflict, "conflict_level", "unknown"),
        "undercut_conflict_score": round(
            float(getattr(conflict, "conflict_score", 0.0) or 0.0),
            4,
        ),
        "refinement_status": getattr(refinement, "status", "unknown"),
        "refinement_quality": getattr(refinement, "quality", "unknown"),
        "warning_count": len(warnings),
    }


def _undercut_context_metrics(context: Any | None) -> dict[str, Any]:
    """Return compact metrics for the undercut context passed to parting line."""
    if context is None:
        return {
            "undercut_context_present": False,
            "undercut_context_boolean_refined": False,
            "undercut_context_feature_count": 0,
            "undercut_context_face_count": 0,
            "undercut_context_boolean_feature_count": 0,
        }

    features = list(getattr(context, "features", []) or [])
    undercut_face_ids = list(getattr(context, "undercut_face_ids", []) or [])
    boolean_feature_count = sum(
        1
        for feature in features
        if getattr(feature, "boolean_refined", False)
        or getattr(feature, "interference_volume_mm3", 0.0)
        or getattr(feature, "boolean_intersection_shapes", None)
    )
    return {
        "undercut_context_present": True,
        "undercut_context_boolean_refined": bool(
            getattr(context, "boolean_refined", False)
        ),
        "undercut_context_feature_count": len(features),
        "undercut_context_face_count": len(undercut_face_ids),
        "undercut_context_boolean_feature_count": boolean_feature_count,
    }


def validate_part(
    path: Path,
    *,
    run_direction: bool = False,
    boolean_refine: bool = False,
    run_parting_line: bool = True,
) -> PartValidationResult:
    """
    Validate one STEP file through the current Level 1 pipeline.

    ``boolean_refine`` defaults to false so the harness can run as a fast smoke
    check on new files.  Deeper Boolean validation can be enabled explicitly in
    Docker/conda where OCC is available and stable.
    """
    steps: list[ValidationStepResult] = []
    warnings: list[str] = []
    loaded_part: Any | None = None
    undercut_result: Any | None = None
    direction_result: Any | None = None

    def load_step_file() -> dict[str, Any]:
        nonlocal loaded_part
        from backend.geometry.step_loader import load_step

        loaded_part = load_step(path)
        warnings.extend(list(getattr(loaded_part, "warnings", []) or []))
        return _topology_metrics(loaded_part)

    steps.append(_run_step("load_step", load_step_file))
    if steps[-1].status != "passed" or loaded_part is None:
        return PartValidationResult(
            filename=path.name,
            path=str(path),
            status="failed" if steps[-1].status == "failed" else "skipped",
            steps=steps,
            warnings=warnings,
        )

    steps.append(_run_step("topology_invariants", lambda: _validate_topology(loaded_part)))

    def run_draft() -> dict[str, Any]:
        from backend.geometry.draft_analyzer import analyze_draft_default

        result = analyze_draft_default(loaded_part, mutate=False)
        return {
            "severity": result.severity,
            "analysed_faces": result.face_count_analysed,
            "good_pct": result.good_pct,
            "marginal_pct": result.marginal_pct,
            "bad_pct": result.bad_pct,
        }

    steps.append(_run_step("draft_default_z", run_draft))

    def run_undercuts() -> dict[str, Any]:
        nonlocal undercut_result
        from backend.geometry.undercut_detector import detect_undercuts

        undercut_result = detect_undercuts(
            loaded_part,
            (0.0, 0.0, 1.0),
            mutate=False,
            boolean_refine=boolean_refine,
            max_boolean_faces=20,
        )
        return {
            "method": undercut_result.method,
            "boolean_refined": undercut_result.boolean_refined,
            "undercut_face_count": len(undercut_result.undercut_face_ids),
            "feature_count": len(undercut_result.features),
            "undercut_area_pct": undercut_result.undercut_area_pct,
        }

    steps.append(_run_step("undercut_detection_z", run_undercuts))

    if run_direction:
        def run_direction_search() -> dict[str, Any]:
            nonlocal direction_result
            from backend.geometry.direction_optimizer import optimize_mold_direction

            direction_result = optimize_mold_direction(loaded_part)
            return {
                "best_label": direction_result.best_label,
                "best_direction": [round(v, 6) for v in direction_result.best_direction],
                "candidate_count": len(direction_result.candidates),
                "best_score": direction_result.best_score,
                "boolean_refined_candidate_count": (
                    direction_result.boolean_refined_candidate_count
                ),
            }

        steps.append(_run_step("direction_search", run_direction_search))

    if run_parting_line:
        def run_parting_line_step() -> dict[str, Any]:
            from backend.geometry.parting_line import detect_parting_line_candidates

            if direction_result is not None:
                pull_direction = direction_result.best_direction
                context = direction_result.optimal_undercuts
                context_source = "optimal_direction"
            else:
                pull_direction = (0.0, 0.0, 1.0)
                context = undercut_result
                context_source = "default_z"

            result = detect_parting_line_candidates(
                loaded_part,
                pull_direction,
                undercut_context=context,
                mutate=False,
            )
            metrics = _parting_line_metrics(result)
            metrics.update(_undercut_context_metrics(context))
            metrics["context_source"] = context_source
            if metrics["readiness_status"] == "failed":
                blockers = metrics["readiness_blockers"] or ["no reviewable candidate"]
                raise ValueError(
                    "Parting-line readiness failed: " + "; ".join(blockers)
                )
            return metrics

        steps.append(_run_step("parting_line", run_parting_line_step))

    status = "failed" if any(step.status == "failed" for step in steps) else "passed"
    return PartValidationResult(
        filename=path.name,
        path=str(path),
        status=status,
        steps=steps,
        warnings=warnings,
    )


def validate_available_parts(
    *,
    parts_dir: Path = DEFAULT_PARTS_DIR,
    expected_files: tuple[str, ...] = DEFAULT_EXPECTED_FILES,
    run_direction: bool = False,
    boolean_refine: bool = False,
    run_parting_line: bool = True,
) -> ValidationSuiteResult:
    """Validate every available STEP file and report missing expected inputs."""
    discovered = discover_step_files(parts_dir)
    results = [
        validate_part(
            path,
            run_direction=run_direction,
            boolean_refine=boolean_refine,
            run_parting_line=run_parting_line,
        )
        for path in discovered
    ]
    return ValidationSuiteResult(
        parts_dir=str(parts_dir),
        expected_files=list(expected_files),
        discovered_files=[path.name for path in discovered],
        missing_expected_files=missing_expected_files(parts_dir, expected_files),
        part_results=results,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate available Bosch STEP demo files.")
    parser.add_argument(
        "--parts-dir",
        type=Path,
        default=DEFAULT_PARTS_DIR,
        help="Directory containing .stp/.step files.",
    )
    parser.add_argument(
        "--expect",
        action="append",
        default=None,
        help="Expected filename. Can be passed multiple times.",
    )
    parser.add_argument(
        "--direction",
        action="store_true",
        help="Also run full mold-direction optimization.",
    )
    parser.add_argument(
        "--boolean-refine",
        action="store_true",
        help="Enable swept Boolean refinement in the undercut smoke pass.",
    )
    parser.add_argument(
        "--no-parting-line",
        action="store_true",
        help="Skip parting-line readiness validation.",
    )
    parser.add_argument(
        "--fail-on-missing-expected",
        action="store_true",
        help="Exit non-zero if an expected file such as Part2.stp is missing.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON instead of a compact text summary.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    expected = tuple(args.expect) if args.expect else DEFAULT_EXPECTED_FILES
    result = validate_available_parts(
        parts_dir=args.parts_dir,
        expected_files=expected,
        run_direction=args.direction,
        boolean_refine=args.boolean_refine,
        run_parting_line=not args.no_parting_line,
    )

    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Validation status: {payload['status']}")
        print(f"Parts directory: {payload['parts_dir']}")
        print(f"Discovered: {', '.join(payload['discovered_files']) or 'none'}")
        if payload["missing_expected_files"]:
            print(f"Missing expected: {', '.join(payload['missing_expected_files'])}")
        for part_result in result.part_results:
            print(f"- {part_result.filename}: {part_result.status}")
            for step in part_result.steps:
                print(f"  - {step.name}: {step.status} ({step.elapsed_s:.2f}s)")
                if step.message:
                    print(f"    {step.message}")

    if result.status == "failed":
        return 1
    if result.missing_expected_files and args.fail_on_missing_expected:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
