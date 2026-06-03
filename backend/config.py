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
class DraftSettings:
    good_threshold_deg: float = 1.5
    marginal_threshold_deg: float = 0.5


@dataclass(frozen=True)
class DirectionSearchSettings:
    angular_step_deg: float = 15.0
    max_candidates: int = 54


@dataclass(frozen=True)
class CoreCavitySettings:
    cavity_color: tuple[float, float, float] = (0.2, 0.8, 0.3)
    core_color: tuple[float, float, float] = (0.2, 0.45, 0.9)


@dataclass(frozen=True)
class DFMSettings:
    draft: DraftSettings = DraftSettings()
    direction_search: DirectionSearchSettings = DirectionSearchSettings()
    core_cavity: CoreCavitySettings = CoreCavitySettings()


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
    agent_raw = raw.get("agent", {}) if isinstance(raw.get("agent", {}), dict) else {}

    draft = replace(
        base.dfm.draft,
        good_threshold_deg=float(
            draft_raw.get("good_threshold_deg", base.dfm.draft.good_threshold_deg)
        ),
        marginal_threshold_deg=float(
            draft_raw.get("marginal_threshold_deg", base.dfm.draft.marginal_threshold_deg)
        ),
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
    )
    core_cavity = replace(
        base.dfm.core_cavity,
        cavity_color=_tuple3(
            core_raw.get("cavity_color", base.dfm.core_cavity.cavity_color),
            base.dfm.core_cavity.cavity_color,
        ),
        core_color=_tuple3(
            core_raw.get("core_color", base.dfm.core_cavity.core_color),
            base.dfm.core_cavity.core_color,
        ),
    )
    dfm = replace(
        base.dfm,
        draft=draft,
        direction_search=direction,
        core_cavity=core_cavity,
    )
    agent = replace(
        base.agent,
        model=str(agent_raw.get("model", base.agent.model)),
        temperature=float(agent_raw.get("temperature", base.agent.temperature)),
    )
    return replace(base, dfm=dfm, agent=agent)


settings = load_settings()
