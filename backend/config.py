"""
backend/config.py
-----------------
Frozen configuration for the DfM Agent.

All thresholds and visualization constants used by geometry modules live here
so Bosch-specific tuning can happen without touching algorithm code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DraftConditionSettings:
    """
    Named draft-condition thresholds (Roadmap Phase 1e).

    STEP AP203/AP214 carries no surface-finish/texture information — these
    conditions are never auto-detected from geometry. They exist so a
    caller (the frontend, once a face is user-marked as textured) can
    override the global threshold for specific faces via `analyze_draft`'s
    `face_conditions` parameter. "smooth" duplicates the global default so
    a caller can explicitly reset a face to it.
    """
    smooth_good_deg: float = 1.5
    smooth_marginal_deg: float = 0.5
    light_texture_good_deg: float = 3.0
    light_texture_marginal_deg: float = 2.0
    heavy_texture_good_deg: float = 5.0
    heavy_texture_marginal_deg: float = 3.5
    deep_rib_good_deg: float = 2.0
    deep_rib_marginal_deg: float = 1.0


@dataclass(frozen=True)
class DraftSettings:
    good_threshold_deg: float = 1.5
    marginal_threshold_deg: float = 0.5
    conditions: DraftConditionSettings = DraftConditionSettings()


@dataclass(frozen=True)
class DirectionSearchSettings:
    angular_step_deg: float = 15.0
    max_candidates: int = 54
    prefilter_skip_score_factor: float = 2.0
    prefilter_survivor_top_count: int = 8
    prefilter_min_boolean_candidates: int = 1
    prefilter_zero_score_margin: float = 1.0
    prefilter_low_undercut_area_pct: float = 5.0
    prefilter_low_bad_area_pct: float = 5.0
    prefilter_principal_axis_keep_count: int = 2
    prefilter_uncertainty_score_margin: float = 0.10
    boolean_refine_top_candidates: int = 5
    boolean_refine_max_faces: int = 80
    boolean_refine_score_margin: float = 0.25
    boolean_interference_weight: float = 4000.0
    boolean_offset_factor: float = 1e-5
    boolean_min_offset_mm: float = 1e-4
    boolean_max_offset_mm: float = 0.25
    boolean_retry_offset_multipliers: tuple[float, ...] = (1.0, 5.0, 25.0)
    boolean_sweep_distance_factor: float = 2.0
    boolean_min_sweep_distance_mm: float = 1.0
    boolean_fuzzy_factor: float = 0.1
    boolean_max_fuzzy_value_mm: float = 0.05
    boolean_volume_tolerance_factor: float = 1e-9
    boolean_min_volume_tolerance_mm3: float = 1e-6
    boolean_min_face_area_mm2: float = 1e-5
    boolean_min_face_area_factor: float = 1e-10
    boolean_feature_seed_faces_per_group: int = 1
    boolean_grouping_proximity_factor: float = 0.15
    boolean_grouping_min_proximity_mm: float = 0.25
    flash_risk_weight: float = 200.0
    flash_angle_threshold_deg: float = 5.0
    flash_thin_area_factor: float = 0.02
    fine_search_enabled: bool = True
    fine_search_top_k: int = 3
    fine_angular_step_deg: float = 5.0
    fine_search_cone_half_angle_deg: float = 15.0
    fine_search_max_candidates: int = 60


@dataclass(frozen=True)
class CoreCavitySettings:
    threshold: float = 0.05
    cavity_color: tuple[float, float, float] = (0.2, 0.8, 0.3)
    core_color: tuple[float, float, float] = (0.2, 0.45, 0.9)


@dataclass(frozen=True)
class UndercutSettings:
    convexity_tangent_tolerance: float = 0.01
    convexity_suppression_enabled: bool = True


@dataclass(frozen=True)
class PartingLineSettings:
    dot_tolerance: float = 0.01
    boundary_dot_tolerance: float = 0.15
    point_tolerance: float = 1e-4
    smoothing_iterations: int = 8
    display_resample_min_points: int = 96
    max_refined_display_points: int = 32_000
    refined_curve_color: tuple[float, float, float] = (0.0, 0.72, 1.0)
    raw_curve_color: tuple[float, float, float] = (1.0, 0.72, 0.0)


@dataclass(frozen=True)
class DFMSettings:
    draft: DraftSettings = DraftSettings()
    direction_search: DirectionSearchSettings = DirectionSearchSettings()
    parting_line: PartingLineSettings = PartingLineSettings()
    core_cavity: CoreCavitySettings = CoreCavitySettings()
    undercut: UndercutSettings = UndercutSettings()


@dataclass(frozen=True)
class AgentSettings:
    model: str = "gpt-4o-mini"
    temperature: float = 0.1


@dataclass(frozen=True)
class Settings:
    dfm: DFMSettings = DFMSettings()
    agent: AgentSettings = AgentSettings()


def _read_yaml(path: Path) -> dict[str, Any]:
    """
    Read a YAML config file if PyYAML is available.

    The project can still run with defaults when PyYAML is not installed; this
    keeps low-level geometry tests independent from optional app dependencies.
    """
    if not path.exists():
        return {}

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return {}

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _tuple3(value: Any, default: tuple[float, float, float]) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return default
    return (float(value[0]), float(value[1]), float(value[2]))


def _condition_pair(
    conditions_raw: dict[str, Any],
    name: str,
    default_good: float,
    default_marginal: float,
) -> tuple[float, float]:
    """Parse one `conditions.<name>: {good, marginal}` entry from config.yaml."""
    entry = conditions_raw.get(name, {})
    if not isinstance(entry, dict):
        return default_good, default_marginal
    return (
        float(entry.get("good", default_good)),
        float(entry.get("marginal", default_marginal)),
    )


def _float_tuple(value: Any, default: tuple[float, ...]) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)):
        return default
    parsed_values: list[float] = []
    for item in value:
        try:
            parsed = float(item)
        except (TypeError, ValueError):
            continue
        if parsed > 0.0:
            parsed_values.append(parsed)
    parsed = tuple(parsed_values)
    return parsed or default


def load_settings(config_path: str | os.PathLike[str] | None = None) -> Settings:
    """
    Load frozen settings from config.yaml, falling back to production defaults.

    Precedence:
      1. Explicit ``config_path`` argument.
      2. ``DFM_CONFIG`` environment variable.
      3. Repository-level ``config.yaml``.
      4. Dataclass defaults.
    """
    default_path = Path(__file__).resolve().parent.parent / "config.yaml"
    path = Path(config_path or os.environ.get("DFM_CONFIG", default_path))
    raw = _read_yaml(path)

    base = Settings()
    dfm_raw = raw.get("dfm", {}) if isinstance(raw.get("dfm", {}), dict) else {}
    draft_raw = dfm_raw.get("draft", {}) if isinstance(dfm_raw.get("draft", {}), dict) else {}
    direction_raw = (
        dfm_raw.get("direction_search", {})
        if isinstance(dfm_raw.get("direction_search", {}), dict)
        else {}
    )
    core_raw = (
        dfm_raw.get("core_cavity", {})
        if isinstance(dfm_raw.get("core_cavity", {}), dict)
        else {}
    )
    parting_raw = (
        dfm_raw.get("parting_line", {})
        if isinstance(dfm_raw.get("parting_line", {}), dict)
        else {}
    )
    undercut_raw = (
        dfm_raw.get("undercut", {})
        if isinstance(dfm_raw.get("undercut", {}), dict)
        else {}
    )
    agent_raw = raw.get("agent", {}) if isinstance(raw.get("agent", {}), dict) else {}

    conditions_raw = (
        draft_raw.get("conditions", {})
        if isinstance(draft_raw.get("conditions", {}), dict)
        else {}
    )
    base_conditions = base.dfm.draft.conditions
    smooth_good, smooth_marginal = _condition_pair(
        conditions_raw, "smooth", base_conditions.smooth_good_deg, base_conditions.smooth_marginal_deg
    )
    light_texture_good, light_texture_marginal = _condition_pair(
        conditions_raw,
        "light_texture",
        base_conditions.light_texture_good_deg,
        base_conditions.light_texture_marginal_deg,
    )
    heavy_texture_good, heavy_texture_marginal = _condition_pair(
        conditions_raw,
        "heavy_texture",
        base_conditions.heavy_texture_good_deg,
        base_conditions.heavy_texture_marginal_deg,
    )
    deep_rib_good, deep_rib_marginal = _condition_pair(
        conditions_raw, "deep_rib", base_conditions.deep_rib_good_deg, base_conditions.deep_rib_marginal_deg
    )
    conditions = replace(
        base_conditions,
        smooth_good_deg=smooth_good,
        smooth_marginal_deg=smooth_marginal,
        light_texture_good_deg=light_texture_good,
        light_texture_marginal_deg=light_texture_marginal,
        heavy_texture_good_deg=heavy_texture_good,
        heavy_texture_marginal_deg=heavy_texture_marginal,
        deep_rib_good_deg=deep_rib_good,
        deep_rib_marginal_deg=deep_rib_marginal,
    )
    draft = replace(
        base.dfm.draft,
        good_threshold_deg=float(
            draft_raw.get("good_threshold_deg", base.dfm.draft.good_threshold_deg)
        ),
        marginal_threshold_deg=float(
            draft_raw.get("marginal_threshold_deg", base.dfm.draft.marginal_threshold_deg)
        ),
        conditions=conditions,
    )
    direction = replace(
        base.dfm.direction_search,
        angular_step_deg=float(
            direction_raw.get(
                "angular_step_deg", base.dfm.direction_search.angular_step_deg
            )
        ),
        max_candidates=int(
            direction_raw.get("max_candidates", base.dfm.direction_search.max_candidates)
        ),
        prefilter_skip_score_factor=float(
            direction_raw.get(
                "prefilter_skip_score_factor",
                base.dfm.direction_search.prefilter_skip_score_factor,
            )
        ),
        prefilter_survivor_top_count=int(
            direction_raw.get(
                "prefilter_survivor_top_count",
                base.dfm.direction_search.prefilter_survivor_top_count,
            )
        ),
        prefilter_min_boolean_candidates=int(
            direction_raw.get(
                "prefilter_min_boolean_candidates",
                base.dfm.direction_search.prefilter_min_boolean_candidates,
            )
        ),
        prefilter_zero_score_margin=float(
            direction_raw.get(
                "prefilter_zero_score_margin",
                base.dfm.direction_search.prefilter_zero_score_margin,
            )
        ),
        prefilter_low_undercut_area_pct=float(
            direction_raw.get(
                "prefilter_low_undercut_area_pct",
                base.dfm.direction_search.prefilter_low_undercut_area_pct,
            )
        ),
        prefilter_low_bad_area_pct=float(
            direction_raw.get(
                "prefilter_low_bad_area_pct",
                base.dfm.direction_search.prefilter_low_bad_area_pct,
            )
        ),
        prefilter_principal_axis_keep_count=int(
            direction_raw.get(
                "prefilter_principal_axis_keep_count",
                base.dfm.direction_search.prefilter_principal_axis_keep_count,
            )
        ),
        prefilter_uncertainty_score_margin=float(
            direction_raw.get(
                "prefilter_uncertainty_score_margin",
                base.dfm.direction_search.prefilter_uncertainty_score_margin,
            )
        ),
        boolean_refine_top_candidates=int(
            direction_raw.get(
                "boolean_refine_top_candidates",
                base.dfm.direction_search.boolean_refine_top_candidates,
            )
        ),
        boolean_refine_max_faces=int(
            direction_raw.get(
                "boolean_refine_max_faces",
                base.dfm.direction_search.boolean_refine_max_faces,
            )
        ),
        boolean_refine_score_margin=float(
            direction_raw.get(
                "boolean_refine_score_margin",
                base.dfm.direction_search.boolean_refine_score_margin,
            )
        ),
        boolean_interference_weight=float(
            direction_raw.get(
                "boolean_interference_weight",
                base.dfm.direction_search.boolean_interference_weight,
            )
        ),
        boolean_offset_factor=float(
            direction_raw.get(
                "boolean_offset_factor",
                base.dfm.direction_search.boolean_offset_factor,
            )
        ),
        boolean_min_offset_mm=float(
            direction_raw.get(
                "boolean_min_offset_mm",
                base.dfm.direction_search.boolean_min_offset_mm,
            )
        ),
        boolean_max_offset_mm=float(
            direction_raw.get(
                "boolean_max_offset_mm",
                base.dfm.direction_search.boolean_max_offset_mm,
            )
        ),
        boolean_retry_offset_multipliers=_float_tuple(
            direction_raw.get(
                "boolean_retry_offset_multipliers",
                base.dfm.direction_search.boolean_retry_offset_multipliers,
            ),
            base.dfm.direction_search.boolean_retry_offset_multipliers,
        ),
        boolean_sweep_distance_factor=float(
            direction_raw.get(
                "boolean_sweep_distance_factor",
                base.dfm.direction_search.boolean_sweep_distance_factor,
            )
        ),
        boolean_min_sweep_distance_mm=float(
            direction_raw.get(
                "boolean_min_sweep_distance_mm",
                base.dfm.direction_search.boolean_min_sweep_distance_mm,
            )
        ),
        boolean_fuzzy_factor=float(
            direction_raw.get(
                "boolean_fuzzy_factor",
                base.dfm.direction_search.boolean_fuzzy_factor,
            )
        ),
        boolean_max_fuzzy_value_mm=float(
            direction_raw.get(
                "boolean_max_fuzzy_value_mm",
                base.dfm.direction_search.boolean_max_fuzzy_value_mm,
            )
        ),
        boolean_volume_tolerance_factor=float(
            direction_raw.get(
                "boolean_volume_tolerance_factor",
                base.dfm.direction_search.boolean_volume_tolerance_factor,
            )
        ),
        boolean_min_volume_tolerance_mm3=float(
            direction_raw.get(
                "boolean_min_volume_tolerance_mm3",
                base.dfm.direction_search.boolean_min_volume_tolerance_mm3,
            )
        ),
        boolean_min_face_area_mm2=float(
            direction_raw.get(
                "boolean_min_face_area_mm2",
                base.dfm.direction_search.boolean_min_face_area_mm2,
            )
        ),
        boolean_min_face_area_factor=float(
            direction_raw.get(
                "boolean_min_face_area_factor",
                base.dfm.direction_search.boolean_min_face_area_factor,
            )
        ),
        boolean_feature_seed_faces_per_group=int(
            direction_raw.get(
                "boolean_feature_seed_faces_per_group",
                base.dfm.direction_search.boolean_feature_seed_faces_per_group,
            )
        ),
        boolean_grouping_proximity_factor=float(
            direction_raw.get(
                "boolean_grouping_proximity_factor",
                base.dfm.direction_search.boolean_grouping_proximity_factor,
            )
        ),
        boolean_grouping_min_proximity_mm=float(
            direction_raw.get(
                "boolean_grouping_min_proximity_mm",
                base.dfm.direction_search.boolean_grouping_min_proximity_mm,
            )
        ),
        flash_risk_weight=float(
            direction_raw.get(
                "flash_risk_weight", base.dfm.direction_search.flash_risk_weight
            )
        ),
        flash_angle_threshold_deg=float(
            direction_raw.get(
                "flash_angle_threshold_deg",
                base.dfm.direction_search.flash_angle_threshold_deg,
            )
        ),
        flash_thin_area_factor=float(
            direction_raw.get(
                "flash_thin_area_factor",
                base.dfm.direction_search.flash_thin_area_factor,
            )
        ),
        fine_search_enabled=bool(
            direction_raw.get(
                "fine_search_enabled", base.dfm.direction_search.fine_search_enabled
            )
        ),
        fine_search_top_k=int(
            direction_raw.get(
                "fine_search_top_k", base.dfm.direction_search.fine_search_top_k
            )
        ),
        fine_angular_step_deg=float(
            direction_raw.get(
                "fine_angular_step_deg",
                base.dfm.direction_search.fine_angular_step_deg,
            )
        ),
        fine_search_cone_half_angle_deg=float(
            direction_raw.get(
                "fine_search_cone_half_angle_deg",
                base.dfm.direction_search.fine_search_cone_half_angle_deg,
            )
        ),
        fine_search_max_candidates=int(
            direction_raw.get(
                "fine_search_max_candidates",
                base.dfm.direction_search.fine_search_max_candidates,
            )
        ),
    )
    core_cavity = replace(
        base.dfm.core_cavity,
        threshold=float(
            core_raw.get("threshold", base.dfm.core_cavity.threshold)
        ),
        cavity_color=_tuple3(
            core_raw.get("cavity_color", base.dfm.core_cavity.cavity_color),
            base.dfm.core_cavity.cavity_color,
        ),
        core_color=_tuple3(
            core_raw.get("core_color", base.dfm.core_cavity.core_color),
            base.dfm.core_cavity.core_color,
        ),
    )
    parting_line = replace(
        base.dfm.parting_line,
        dot_tolerance=float(
            parting_raw.get("dot_tolerance", base.dfm.parting_line.dot_tolerance)
        ),
        boundary_dot_tolerance=float(
            parting_raw.get(
                "boundary_dot_tolerance",
                base.dfm.parting_line.boundary_dot_tolerance,
            )
        ),
        point_tolerance=float(
            parting_raw.get("point_tolerance", base.dfm.parting_line.point_tolerance)
        ),
        smoothing_iterations=int(
            parting_raw.get(
                "smoothing_iterations",
                base.dfm.parting_line.smoothing_iterations,
            )
        ),
        display_resample_min_points=int(
            parting_raw.get(
                "display_resample_min_points",
                base.dfm.parting_line.display_resample_min_points,
            )
        ),
        max_refined_display_points=int(
            parting_raw.get(
                "max_refined_display_points",
                base.dfm.parting_line.max_refined_display_points,
            )
        ),
        refined_curve_color=_tuple3(
            parting_raw.get(
                "refined_curve_color",
                base.dfm.parting_line.refined_curve_color,
            ),
            base.dfm.parting_line.refined_curve_color,
        ),
        raw_curve_color=_tuple3(
            parting_raw.get("raw_curve_color", base.dfm.parting_line.raw_curve_color),
            base.dfm.parting_line.raw_curve_color,
        ),
    )
    undercut = replace(
        base.dfm.undercut,
        convexity_tangent_tolerance=float(
            undercut_raw.get(
                "convexity_tangent_tolerance",
                base.dfm.undercut.convexity_tangent_tolerance,
            )
        ),
        convexity_suppression_enabled=bool(
            undercut_raw.get(
                "convexity_suppression_enabled",
                base.dfm.undercut.convexity_suppression_enabled,
            )
        ),
    )
    dfm = replace(
        base.dfm,
        draft=draft,
        direction_search=direction,
        parting_line=parting_line,
        core_cavity=core_cavity,
        undercut=undercut,
    )
    agent = replace(
        base.agent,
        model=str(agent_raw.get("model", base.agent.model)),
        temperature=float(agent_raw.get("temperature", base.agent.temperature)),
    )
    return replace(base, dfm=dfm, agent=agent)


settings = load_settings()
