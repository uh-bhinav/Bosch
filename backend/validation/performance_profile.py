"""
backend/validation/performance_profile.py
-----------------------------------------
Performance profiling harness for the current Level 1 DfM pipeline.

The profiler measures the same operations used by the demo UI and reports
structured timings.  It is intentionally runnable as a CLI so Docker/conda can
profile real pythonOCC workloads without adding runtime overhead to the API.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from backend.validation.part_validation import (
    DEFAULT_PARTS_DIR,
    _parting_line_metrics,
    _undercut_context_metrics,
    discover_step_files,
    missing_expected_files,
)


DEFAULT_EXPECTED_FILES = ("Part1.stp", "Part2.stp")

DEFAULT_BUDGETS_S = {
    "load_step": 30.0,
    "display_mesh": 20.0,
    "draft_default_z": 10.0,
    "undercut_detection_z": 60.0,
    "direction_search": 180.0,
    "parting_line": 45.0,
}


@dataclass(frozen=True)
class PerformanceStepProfile:
    """Timing result for one pipeline operation."""

    name: str
    status: str
    elapsed_s: float
    budget_s: float | None = None
    message: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def budget_status(self) -> str:
        if self.status != "passed":
            return "not_applicable"
        if self.budget_s is None:
            return "unbudgeted"
        return "within_budget" if self.elapsed_s <= self.budget_s else "over_budget"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "elapsed_s": round(self.elapsed_s, 4),
            "budget_s": self.budget_s,
            "budget_status": self.budget_status,
            "message": self.message,
            "metrics": self.metrics,
        }


@dataclass(frozen=True)
class PartPerformanceProfile:
    """Performance profile for one STEP file."""

    filename: str
    path: str
    steps: list[PerformanceStepProfile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def total_elapsed_s(self) -> float:
        return sum(step.elapsed_s for step in self.steps)

    @property
    def status(self) -> str:
        if any(step.status == "failed" for step in self.steps):
            return "failed"
        if any(step.status == "skipped" for step in self.steps):
            return "warning"
        if any(step.budget_status == "over_budget" for step in self.steps):
            return "warning"
        if not self.steps:
            return "warning"
        return "passed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "path": self.path,
            "status": self.status,
            "total_elapsed_s": round(self.total_elapsed_s, 4),
            "steps": [step.to_dict() for step in self.steps],
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class PerformanceSuiteProfile:
    """Performance profile for all discovered demo STEP files."""

    parts_dir: str
    expected_files: list[str]
    discovered_files: list[str]
    missing_expected_files: list[str]
    part_profiles: list[PartPerformanceProfile]
    budgets_s: dict[str, float]

    @property
    def status(self) -> str:
        if any(profile.status == "failed" for profile in self.part_profiles):
            return "failed"
        if self.missing_expected_files:
            return "warning"
        if any(profile.status == "warning" for profile in self.part_profiles):
            return "warning"
        if not self.part_profiles:
            return "warning"
        return "passed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "parts_dir": self.parts_dir,
            "expected_files": self.expected_files,
            "discovered_files": self.discovered_files,
            "missing_expected_files": self.missing_expected_files,
            "budgets_s": self.budgets_s,
            "part_profiles": [profile.to_dict() for profile in self.part_profiles],
        }


def _profile_step(
    name: str,
    fn: Callable[[], dict[str, Any] | None],
    *,
    budgets_s: dict[str, float],
) -> PerformanceStepProfile:
    start_s = time.perf_counter()
    try:
        metrics = fn() or {}
    except ImportError as exc:
        return PerformanceStepProfile(
            name=name,
            status="skipped",
            elapsed_s=time.perf_counter() - start_s,
            budget_s=budgets_s.get(name),
            message=f"Runtime dependency unavailable: {exc}",
        )
    except Exception as exc:  # noqa: BLE001 - profiler must report failures.
        return PerformanceStepProfile(
            name=name,
            status="failed",
            elapsed_s=time.perf_counter() - start_s,
            budget_s=budgets_s.get(name),
            message=str(exc) or exc.__class__.__name__,
        )
    return PerformanceStepProfile(
        name=name,
        status="passed",
        elapsed_s=time.perf_counter() - start_s,
        budget_s=budgets_s.get(name),
        metrics=metrics,
    )


def _part_metrics(part: Any) -> dict[str, Any]:
    return {
        "solid_count": part.solid_count,
        "face_count": part.face_count,
        "edge_count": part.edge_count,
        "vertex_count": part.vertex_count,
        "bbox_diagonal_mm": round(float(part.bounding_box.diagonal), 4),
    }


def profile_part(
    path: Path,
    *,
    include_mesh: bool = True,
    run_direction: bool = False,
    boolean_refine: bool = False,
    include_parting_line: bool = True,
    mesh_deflection: float = 0.5,
    budgets_s: dict[str, float] | None = None,
) -> PartPerformanceProfile:
    """Profile the current Level 1 pipeline on one STEP file."""
    budgets = budgets_s or DEFAULT_BUDGETS_S
    loaded_part: Any | None = None
    undercut_result: Any | None = None
    direction_result: Any | None = None
    warnings: list[str] = []
    steps: list[PerformanceStepProfile] = []

    def load_step_file() -> dict[str, Any]:
        nonlocal loaded_part
        from backend.geometry.step_loader import load_step

        loaded_part = load_step(path)
        warnings.extend(list(getattr(loaded_part, "warnings", []) or []))
        return _part_metrics(loaded_part)

    steps.append(_profile_step("load_step", load_step_file, budgets_s=budgets))
    if loaded_part is None or steps[-1].status != "passed":
        return PartPerformanceProfile(
            filename=path.name,
            path=str(path),
            steps=steps,
            warnings=warnings,
        )

    if include_mesh:
        def display_mesh() -> dict[str, Any]:
            from backend.geometry.visualize_raw import build_display_mesh

            mesh = build_display_mesh(loaded_part, linear_deflection=mesh_deflection)
            return {
                "point_count": mesh.point_count,
                "triangle_count": mesh.triangle_count,
                "face_id_count": len(mesh.face_ids),
                "mesh_deflection": mesh_deflection,
            }

        steps.append(_profile_step("display_mesh", display_mesh, budgets_s=budgets))

    def draft_default() -> dict[str, Any]:
        from backend.geometry.draft_analyzer import analyze_draft_default

        result = analyze_draft_default(loaded_part, mutate=False)
        return {
            "severity": result.severity,
            "analysed_faces": result.face_count_analysed,
            "bad_pct": result.bad_pct,
            "suggestion_count": len(result.suggestions),
        }

    steps.append(_profile_step("draft_default_z", draft_default, budgets_s=budgets))

    def undercuts_default() -> dict[str, Any]:
        nonlocal undercut_result
        from backend.geometry.undercut_detector import detect_undercuts

        undercut_result = detect_undercuts(
            loaded_part,
            (0.0, 0.0, 1.0),
            mutate=False,
            boolean_refine=boolean_refine,
            max_boolean_faces=20,
        )
        performance = (
            undercut_result.boolean_performance.to_dict()
            if undercut_result.boolean_performance is not None
            else None
        )
        return {
            "method": undercut_result.method,
            "boolean_refined": undercut_result.boolean_refined,
            "undercut_face_count": len(undercut_result.undercut_face_ids),
            "feature_count": len(undercut_result.features),
            "undercut_area_pct": undercut_result.undercut_area_pct,
            "boolean_performance": performance,
        }

    steps.append(_profile_step("undercut_detection_z", undercuts_default, budgets_s=budgets))

    if run_direction:
        def direction_search() -> dict[str, Any]:
            nonlocal direction_result
            from backend.geometry.direction_optimizer import optimize_mold_direction

            direction_result = optimize_mold_direction(loaded_part)
            return {
                "best_label": direction_result.best_label,
                "candidate_count": len(direction_result.candidates),
                "best_score": direction_result.best_score,
                "boolean_refined_candidate_count": (
                    direction_result.boolean_refined_candidate_count
                ),
                "boolean_pruned_candidate_count": (
                    direction_result.boolean_pruned_candidate_count
                ),
                "direction_cache_entries": direction_result.direction_cache_entries,
                "direction_cache_hits": direction_result.direction_cache_hits,
            }

        steps.append(_profile_step("direction_search", direction_search, budgets_s=budgets))

    if include_parting_line:
        def parting_line() -> dict[str, Any]:
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
            return metrics

        steps.append(_profile_step("parting_line", parting_line, budgets_s=budgets))

    return PartPerformanceProfile(
        filename=path.name,
        path=str(path),
        steps=steps,
        warnings=warnings,
    )


def profile_available_parts(
    *,
    parts_dir: Path = DEFAULT_PARTS_DIR,
    expected_files: tuple[str, ...] = DEFAULT_EXPECTED_FILES,
    include_mesh: bool = True,
    run_direction: bool = False,
    boolean_refine: bool = False,
    include_parting_line: bool = True,
    mesh_deflection: float = 0.5,
    budgets_s: dict[str, float] | None = None,
) -> PerformanceSuiteProfile:
    """Profile every discovered STEP file and report missing expected inputs."""
    budgets = budgets_s or DEFAULT_BUDGETS_S
    discovered = discover_step_files(parts_dir)
    profiles = [
        profile_part(
            path,
            include_mesh=include_mesh,
            run_direction=run_direction,
            boolean_refine=boolean_refine,
            include_parting_line=include_parting_line,
            mesh_deflection=mesh_deflection,
            budgets_s=budgets,
        )
        for path in discovered
    ]
    return PerformanceSuiteProfile(
        parts_dir=str(parts_dir),
        expected_files=list(expected_files),
        discovered_files=[path.name for path in discovered],
        missing_expected_files=missing_expected_files(parts_dir, expected_files),
        part_profiles=profiles,
        budgets_s=dict(budgets),
    )


def _parse_budget(values: list[str] | None) -> dict[str, float]:
    budgets = dict(DEFAULT_BUDGETS_S)
    for item in values or []:
        if "=" not in item:
            raise ValueError(f"Invalid budget '{item}'. Expected name=seconds.")
        name, raw_value = item.split("=", 1)
        budgets[name.strip()] = float(raw_value)
    return budgets


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Profile Bosch STEP demo performance.")
    parser.add_argument("--parts-dir", type=Path, default=DEFAULT_PARTS_DIR)
    parser.add_argument("--expect", action="append", default=None)
    parser.add_argument("--no-mesh", action="store_true", help="Skip display mesh profiling.")
    parser.add_argument("--direction", action="store_true", help="Profile direction optimization.")
    parser.add_argument("--boolean-refine", action="store_true", help="Enable Boolean undercut refinement.")
    parser.add_argument(
        "--no-parting-line",
        action="store_true",
        help="Skip parting-line profiling.",
    )
    parser.add_argument("--mesh-deflection", type=float, default=0.5)
    parser.add_argument(
        "--budget",
        action="append",
        default=None,
        help="Override a budget as step_name=seconds. Can be passed multiple times.",
    )
    parser.add_argument("--fail-on-warning", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    expected = tuple(args.expect) if args.expect else DEFAULT_EXPECTED_FILES
    try:
        budgets = _parse_budget(args.budget)
    except ValueError as exc:
        parser.error(str(exc))

    result = profile_available_parts(
        parts_dir=args.parts_dir,
        expected_files=expected,
        include_mesh=not args.no_mesh,
        run_direction=args.direction,
        boolean_refine=args.boolean_refine,
        include_parting_line=not args.no_parting_line,
        mesh_deflection=args.mesh_deflection,
        budgets_s=budgets,
    )
    payload = result.to_dict()

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Performance status: {payload['status']}")
        print(f"Discovered: {', '.join(payload['discovered_files']) or 'none'}")
        if payload["missing_expected_files"]:
            print(f"Missing expected: {', '.join(payload['missing_expected_files'])}")
        for profile in result.part_profiles:
            print(f"- {profile.filename}: {profile.status} ({profile.total_elapsed_s:.2f}s)")
            for step in profile.steps:
                print(
                    f"  - {step.name}: {step.status}, {step.elapsed_s:.2f}s, "
                    f"{step.budget_status}"
                )
                if step.message:
                    print(f"    {step.message}")

    if result.status == "failed":
        return 1
    if args.fail_on_warning and result.status == "warning":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
