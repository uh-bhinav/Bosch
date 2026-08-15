import math
import os
import sys

# VTK/PyVista must render off-screen on macOS when embedded in Streamlit.
os.environ.setdefault("PYVISTA_OFF_SCREEN", "true")
os.environ.setdefault("VTK_DEFAULT_RENDER_WINDOW_OFFSCREEN", "1")

# pyarrow's bundled mimalloc (3.3.x) segfaults (SIGSEGV) the very first time a
# Streamlit ScriptRunner thread performs an Arrow allocation (st.dataframe /
# Table.from_pandas) after the thread that first touched libarrow has exited.
# This is upstream mimalloc bug microsoft/mimalloc#1287 / apache/arrow#50471.
# Forcing the system allocator instead of mimalloc avoids the crash entirely.
os.environ.setdefault("ARROW_DEFAULT_MEMORY_POOL", "system")

import streamlit as st
import requests
import time
import json
from typing import Any


st.set_page_config(
    page_title="DfM Agent",
    layout="wide"
)

BACKEND_URL = os.environ.get("DFM_BACKEND_URL", "http://localhost:8000")
_USE_PLOTLY_VIEWER = sys.platform == "darwin" or os.environ.get("DFM_FORCE_PLOTLY") == "1"


def _inject_app_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 1.1rem;
            padding-bottom: 2rem;
        }
        [data-testid="stSidebar"] {
            background: #f7f8fa;
        }
        div.stButton > button {
            border-radius: 6px;
            font-weight: 600;
        }
        .dfm-status-row {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin: 0.35rem 0 0.85rem 0;
        }
        .dfm-chip {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            border-radius: 999px;
            padding: 5px 9px;
            border: 1px solid rgba(25, 32, 44, 0.14);
            background: #ffffff;
            color: #1f2937;
            font-size: 0.82rem;
            font-weight: 600;
            line-height: 1.1;
        }
        .dfm-chip-dot {
            width: 9px;
            height: 9px;
            border-radius: 50%;
            display: inline-block;
            box-shadow: 0 0 0 1px rgba(0,0,0,0.16);
        }
        .dfm-chip-muted {
            color: #667085;
            background: #f2f4f7;
        }
        .dfm-chip-current {
            color: #155eef;
            background: #eff4ff;
            border-color: #b2ccff;
        }
        .dfm-chip-complete {
            color: #067647;
            background: #ecfdf3;
            border-color: #abefc6;
        }
        .dfm-chip-failed {
            color: #b42318;
            background: #fef3f2;
            border-color: #fecdca;
        }
        .dfm-summary-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 10px;
            margin: 0.25rem 0 0.85rem 0;
        }
        .dfm-summary-tile {
            border: 1px solid #d7dce3;
            border-radius: 6px;
            padding: 10px 12px;
            background: #ffffff;
            min-height: 70px;
        }
        .dfm-summary-label {
            font-size: 0.74rem;
            color: #667085;
            margin-bottom: 5px;
            text-transform: uppercase;
            letter-spacing: 0;
        }
        .dfm-summary-value {
            font-size: 1.08rem;
            font-weight: 700;
            color: #111827;
            overflow-wrap: anywhere;
        }
        .dfm-summary-subtle {
            font-size: 0.78rem;
            color: #667085;
            margin-top: 3px;
        }
        .dfm-story-band {
            border: 1px solid #d7dce3;
            border-radius: 6px;
            padding: 12px 14px;
            background: #ffffff;
            margin: 0.35rem 0 0.9rem 0;
        }
        .dfm-story-kicker {
            font-size: 0.76rem;
            color: #667085;
            text-transform: uppercase;
            letter-spacing: 0;
            margin-bottom: 4px;
        }
        .dfm-story-title {
            font-size: 1.04rem;
            font-weight: 700;
            color: #111827;
            margin-bottom: 4px;
        }
        .dfm-story-body {
            color: #344054;
            font-size: 0.9rem;
            line-height: 1.35;
        }
        .dfm-legend {
            display: flex;
            flex-wrap: wrap;
            gap: 8px 14px;
            margin: 0.25rem 0 0.85rem 0;
        }
        .dfm-legend-item {
            display: inline-flex;
            align-items: center;
            gap: 7px;
            color: #344054;
            font-size: 0.84rem;
        }
        .dfm-swatch {
            width: 14px;
            height: 14px;
            border-radius: 3px;
            border: 1px solid rgba(0,0,0,0.22);
            display: inline-block;
        }
        @media (max-width: 900px) {
            .dfm-summary-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


_inject_app_styles()

DEFAULT_BOOLEAN_LEGEND = {
    "critical": {
        "label": "Critical Boolean interference",
        "rgb": [1.0, 0.10, 0.04],
    },
    "moderate": {
        "label": "Moderate Boolean interference",
        "rgb": [1.0, 0.48, 0.04],
    },
    "minor": {
        "label": "Minor Boolean interference",
        "rgb": [1.0, 0.76, 0.18],
    },
}

QUALITY_TONES = {
    "good": ("complete", "#12b76a"),
    "info": ("current", "#2e90fa"),
    "warning": ("muted", "#f79009"),
    "bad": ("failed", "#f04438"),
    "neutral": ("muted", "#98a2b3"),
}


def _html_escape(value: object) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )



# ---------------------------------------------------------------------------
# Metric glossary (roadmap Stage 3 §3.2/§3.3) — each entry answers three
# questions: what it means · what good looks like · what to do if it's bad.
# Surfaced two ways: (1) as a hover tooltip on the indicator chip that shows
# the metric, via help_key= below, and (2) as a full reference list in the
# "Metric Glossary" expander rendered near the top of the page.
# ---------------------------------------------------------------------------
METRIC_GLOSSARY: dict[str, str] = {
    "readiness": (
        "What the parting-line candidate is safe to use for. ready = usable "
        "as-is; review = usable, but a mold engineer should look at it; "
        "weak/failed = do not trust yet, and core/cavity may be blocked. "
        "Backed by graph_cleanup.strategy, closure_error_mm, and "
        "silhouette_coverage_ratio together, not any single number."
    ),
    "closure_error_mm": (
        "The MEASURED gap (mm) between the parting loop's first and last "
        "point, checked after closure — never just the reported flag. Near "
        "0 with closure_guaranteed=True means the loop is genuinely closed. "
        "A nonzero gap despite a 'closed' report is the exact failure mode "
        "Bug A introduced — always check this number, not just the flag."
    ),
    "graph_cleanup_strategy": (
        "Whether the exact/contracted path search found the selected wire, "
        "or the search fell back to a non-backtracking greedy heuristic "
        "('greedy-fallback'). Fallback means the selected wire is not "
        "guaranteed to be the best one available. Exposing this number "
        "alone would have caught Bug B immediately — it is the single "
        "highest-value metric on this page."
    ),
    "silhouette_coverage_ratio": (
        "Fraction of the part's projected outline the selected parting "
        "loop actually spans. Low (roughly under 35%) usually means a "
        "local feature — a hole rim, a boss — was selected instead of the "
        "main parting line, not that the part itself lacks a good one."
    ),
    "undercut_area_pct": (
        "Fraction of total part surface area flagged as undercut for the "
        "current pull direction. Higher means more tooling complexity "
        "(side actions, lifters); 0% means the direction is fully "
        "undercut-free by area."
    ),
    "direction_score": (
        "A relative, unitless ranking score for one candidate mold-opening "
        "direction. Only meaningful compared against OTHER candidates for "
        "the same part — never compare this number across different parts."
    ),
    "depth_proxy_mm": (
        "A conservative, upper-bound ESTIMATE of undercut depth, not a "
        "precise measurement. Deliberately errs toward over-estimating "
        "risk rather than under-estimating it (a locked project decision — "
        "see TODO.md)."
    ),
    "pull_alignment": (
        "How aligned a face's undercut direction is with the pull "
        "direction: 0.0 = fully transverse (a side action is likely "
        "needed); 1.0 = aligned with the pull axis."
    ),
    "bridging_status": (
        "Whether component bridging ran to close a fragmented silhouette: "
        "not_needed (already closed), applied (ran and was kept), "
        "discarded_not_an_improvement (ran, made things worse, reverted), "
        "unavailable/disabled (did not run at all)."
    ),
    "split_tool_kind": (
        "What geometry actually bisected the tooling into cavity/core "
        "solids. 'planar_approximation' means a flat plane was used, NOT "
        "the exact 3-D parting surface shown elsewhere on this page — the "
        "exported solids approximate that curve, they don't follow it "
        "exactly."
    ),
}


def _metric_help(key: str) -> str:
    """Return glossary text for a metric key, or '' if not in the glossary."""
    return METRIC_GLOSSARY.get(key, "")


def _render_metric_glossary() -> None:
    """Reference-page form of the glossary (roadmap Stage 3 §3.2)."""
    with st.expander("📖 Metric Glossary — what these numbers mean"):
        for key, text in METRIC_GLOSSARY.items():
            st.markdown(f"**`{key}`** — {text}")


def _color_dot(color: str) -> str:
    return f"<span class='dfm-chip-dot' style='background:{_html_escape(color)}'></span>"


def _status_chip(
    label: str, *, state: str = "muted", color: str = "#98a2b3", help_text: str = ""
) -> str:
    css_class = {
        "complete": "dfm-chip-complete",
        "current": "dfm-chip-current",
        "failed": "dfm-chip-failed",
        "muted": "dfm-chip-muted",
    }.get(state, "dfm-chip-muted")
    title_attr = f" title='{_html_escape(help_text)}'" if help_text else ""
    return (
        f"<span class='dfm-chip {css_class}'{title_attr}>"
        f"{_color_dot(color)}{_html_escape(label)}</span>"
    )


def _render_chip_row(chips: list[str]) -> None:
    st.markdown(
        f"<div class='dfm-status-row'>{''.join(chips)}</div>",
        unsafe_allow_html=True,
    )


def _indicator_chip(
    label: str, value: object, *, tone: str = "neutral", help_key: str = ""
) -> str:
    state, color = QUALITY_TONES.get(tone, QUALITY_TONES["neutral"])
    return _status_chip(
        f"{label}: {value}", state=state, color=color, help_text=_metric_help(help_key)
    )


def _render_quality_indicators(
    items: list[tuple[str, object, str] | tuple[str, object, str, str]],
) -> None:
    chips = []
    for item in items:
        label, value, tone, *rest = item
        if value in (None, ""):
            continue
        help_key = rest[0] if rest else ""
        chips.append(_indicator_chip(label, value, tone=tone, help_key=help_key))
    if chips:
        _render_chip_row(chips)


def _tone_for_draft_severity(severity: object) -> str:
    value = str(severity or "unknown").lower()
    if value in {"none", "ok", "good"}:
        return "good"
    if value == "minor":
        return "info"
    if value == "moderate":
        return "warning"
    if value == "critical":
        return "bad"
    return "neutral"


def _tone_for_count(count: int, *, warning_at: int = 1, bad_at: int | None = None) -> str:
    if count <= 0:
        return "good"
    if bad_at is not None and count >= bad_at:
        return "bad"
    if count >= warning_at:
        return "warning"
    return "info"


def _tone_for_quality_level(level: object) -> str:
    value = str(level or "unknown").lower()
    if value in {"high", "ready", "passed", "ok"}:
        return "good"
    if value in {"medium", "review", "accepted"}:
        return "info"
    if value in {"low", "weak", "warning", "fallback", "disabled"}:
        return "warning"
    if value in {"empty", "failed", "error", "high_conflict"}:
        return "bad"
    return "neutral"


def _tone_for_boolean_reliability(level: object) -> str:
    value = str(level or "unknown").lower()
    if value == "high":
        return "good"
    if value == "medium":
        return "info"
    if value == "low":
        return "warning"
    return "neutral"


def _tone_for_conflict(level: object) -> str:
    value = str(level or "unknown").lower()
    if value in {"none", "not_checked"}:
        return "good" if value == "none" else "neutral"
    if value == "low":
        return "info"
    if value == "medium":
        return "warning"
    if value == "high":
        return "bad"
    return "neutral"


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _table_cell(value: object) -> str:
    """Return an Arrow-safe display string for Streamlit dataframes."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, (list, tuple, dict)):
        try:
            return json.dumps(value, ensure_ascii=True, default=str)
        except TypeError:
            return str(value)
    return str(value)


def _safe_table_rows(rows: object) -> object:
    if isinstance(rows, list) and all(isinstance(row, dict) for row in rows):
        return [
            {str(key): _table_cell(value) for key, value in row.items()}
            for row in rows
        ]
    return rows


def _prepare_safe_dataframe(data: list[dict[str, Any]]) -> Any:
    import pandas as pd

    df = pd.DataFrame(data)
    for col in df.columns:
        df[col] = df[col].replace(["-", "—", "N/A", "n/a", ""], None)
        try:
            numeric = pd.to_numeric(df[col], errors="coerce")
            if numeric.notna().sum() > len(df) * 0.5:
                df[col] = numeric
        except Exception:
            pass
        if df[col].dtype == object:
            df[col] = df[col].astype(str).replace("None", "—")
    return df


def _safe_dataframe(rows: object, **kwargs: Any) -> None:
    if isinstance(rows, list) and rows and all(isinstance(row, dict) for row in rows):
        st.dataframe(_prepare_safe_dataframe(rows), **kwargs)
    else:
        st.dataframe(_safe_table_rows(rows), **kwargs)


def _feature_list(undercuts: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(undercuts, dict):
        return []
    features = undercuts.get("features", []) or []
    return [feature for feature in features if isinstance(feature, dict)]


def _normalised_token(value: object) -> str:
    return str(value or "").strip().lower().replace("_", "-").replace(" ", "-")


def _is_major_undercut_feature(feature: dict[str, Any]) -> bool:
    """Return True when a feature should be called out as a major mold risk."""
    severity = _normalised_token(feature.get("severity"))
    action = _normalised_token(feature.get("recommended_mold_action"))
    confidence = _normalised_token(feature.get("action_confidence_label"))
    depth_mm = _safe_float(
        feature.get("depth_proxy_mm", feature.get("depth_mm", 0.0))
    )
    return (
        severity == "critical"
        or action == "side-action"
        or (confidence == "high" and depth_mm >= 2.0)
    )


def _undercut_counts(undercuts: dict[str, Any] | None) -> dict[str, Any]:
    features = _feature_list(undercuts)
    total = (
        _safe_int(undercuts.get("feature_count"), len(features))
        if isinstance(undercuts, dict)
        else 0
    )
    total = max(total, len(features))
    percentages = undercuts.get("percentages", {}) if isinstance(undercuts, dict) else {}
    counts = {
        "total": total,
        "major": 0,
        "critical": 0,
        "moderate": 0,
        "minor": 0,
        "side_action": 0,
        "high_confidence": 0,
        "area_pct": _safe_float(percentages.get("undercut_area_pct", 0.0)),
        "max_depth_mm": 0.0,
    }
    for feature in features:
        severity = _normalised_token(feature.get("severity"))
        action = _normalised_token(feature.get("recommended_mold_action"))
        confidence = _normalised_token(feature.get("action_confidence_label"))
        depth_mm = _safe_float(
            feature.get("depth_proxy_mm", feature.get("depth_mm", 0.0))
        )
        if severity in {"critical", "moderate", "minor"}:
            counts[severity] += 1
        if action == "side-action":
            counts["side_action"] += 1
        if confidence == "high":
            counts["high_confidence"] += 1
        if _is_major_undercut_feature(feature):
            counts["major"] += 1
        counts["max_depth_mm"] = max(counts["max_depth_mm"], depth_mm)
    return counts


def _format_undercut_count(count: int) -> str:
    label = "feature" if count == 1 else "features"
    return f"{count} undercut {label}"


def _format_undercut_evidence(counts: dict[str, Any]) -> str:
    parts: list[str] = []
    if counts.get("major", 0):
        parts.append(f"{counts['major']} major")
    if counts.get("critical", 0):
        parts.append(f"{counts['critical']} critical")
    if counts.get("side_action", 0):
        parts.append(f"{counts['side_action']} side-action")
    if counts.get("high_confidence", 0):
        parts.append(f"{counts['high_confidence']} high-confidence")
    if parts:
        return " | ".join(parts)
    return f"{counts.get('area_pct', 0.0)}% area"


def _tone_for_undercut_counts(counts: dict[str, Any]) -> str:
    if counts.get("major", 0) or counts.get("critical", 0):
        return "bad"
    if counts.get("total", 0):
        return "warning"
    return "good"


def _mold_action_result(counts: dict[str, Any]) -> tuple[str, str, str]:
    if counts.get("side_action", 0):
        return (
            "Side-action review",
            f"{counts['side_action']} side-action feature(s)",
            "Review",
        )
    if counts.get("major", 0):
        return (
            "Mold-action review",
            f"{counts['major']} major feature(s)",
            "Review",
        )
    if counts.get("total", 0):
        return (
            "Manual review",
            f"{counts['total']} retained feature(s)",
            "Review",
        )
    return ("No side-action trigger", "No detected undercut features", "OK")


def _vector_text(vector: object) -> str:
    if not isinstance(vector, (list, tuple)) or len(vector) != 3:
        return "(unknown)"
    try:
        x, y, z = (float(vector[0]), float(vector[1]), float(vector[2]))
    except (TypeError, ValueError):
        return "(unknown)"
    return f"({x:+.3f}, {y:+.3f}, {z:+.3f})"


def _direction_axis_tilt_text(vector: object) -> str:
    """
    Format a pull-direction unit vector the way a mold engineer actually
    reasons about it: the raw components, plus its closest axis and tilt
    angle off that axis (roadmap Stage 3 §3.5), e.g.
    "(+0.232, +0.357, +0.905) ≈ +Z, tilted 25°". The vector itself is never
    snapped to an axis — this is a display-only annotation.
    """
    if not isinstance(vector, (list, tuple)) or len(vector) != 3:
        return _vector_text(vector)
    try:
        vx, vy, vz = (float(vector[0]), float(vector[1]), float(vector[2]))
    except (TypeError, ValueError):
        return _vector_text(vector)
    magnitude = (vx * vx + vy * vy + vz * vz) ** 0.5
    if magnitude < 1e-9:
        return _vector_text(vector)
    ux, uy, uz = vx / magnitude, vy / magnitude, vz / magnitude
    axis_label, component = max(
        (("X", ux), ("Y", uy), ("Z", uz)), key=lambda item: abs(item[1])
    )
    sign = "+" if component >= 0 else "-"
    cos_tilt = max(-1.0, min(1.0, abs(component)))
    tilt_deg = math.degrees(math.acos(cos_tilt))
    return (
        f"({vx:+.3f}, {vy:+.3f}, {vz:+.3f}) ≈ {sign}{axis_label}, "
        f"tilted {tilt_deg:.0f}°"
    )


def _angular_separation_deg(a: object, b: object) -> float:
    """Angle in degrees between two direction vectors (need not be unit)."""
    try:
        ax, ay, az = (float(a[0]), float(a[1]), float(a[2]))
        bx, by, bz = (float(b[0]), float(b[1]), float(b[2]))
    except (TypeError, ValueError, IndexError):
        return 180.0
    mag_a = (ax * ax + ay * ay + az * az) ** 0.5
    mag_b = (bx * bx + by * by + bz * bz) ** 0.5
    if mag_a < 1e-9 or mag_b < 1e-9:
        return 180.0
    cos_angle = (ax * bx + ay * by + az * bz) / (mag_a * mag_b)
    cos_angle = max(-1.0, min(1.0, cos_angle))
    return math.degrees(math.acos(cos_angle))


def _cluster_diverse_candidates(
    candidates: list[dict[str, Any]], *, min_separation_deg: float = 15.0
) -> list[dict[str, Any]]:
    """
    Roadmap Stage 3 §3.7: the raw candidate list's top entries are often all
    within a few degrees of each other (an artefact of the Milestone 1.4
    fine-search cone) — the same answer repeated six times, not six distinct
    options. Greedily picks the best-scoring candidate, then the best
    remaining candidate that is at least `min_separation_deg` from every
    already-picked one, and so on — the standard "diverse top-k" selection
    (closely related to non-max suppression). Assumes `candidates` is
    already sorted best-first (lower score = better, matching the
    optimizer's own ranking).
    """
    diverse: list[dict[str, Any]] = []
    for candidate in candidates:
        direction = candidate.get("direction")
        if not isinstance(direction, (list, tuple)) or len(direction) != 3:
            continue
        if all(
            _angular_separation_deg(direction, chosen.get("direction"))
            >= min_separation_deg
            for chosen in diverse
        ):
            diverse.append(candidate)
    return diverse


def _render_candidate_diversity(direction: dict[str, Any]) -> None:
    """
    Layer 1/2 view of genuinely distinct direction options, replacing "top 6
    near-duplicates" with "here are your real choices and why the best one
    ranks first" (roadmap §3.7's reframing away from claiming *the* answer).
    """
    candidates = direction.get("candidates") or []
    if not isinstance(candidates, list) or not candidates:
        return

    best_direction = direction.get("best_direction")
    diverse = _cluster_diverse_candidates(candidates, min_separation_deg=15.0)

    st.markdown("#### Diverse Candidate Directions")
    st.caption(
        f"{len(candidates)} candidates were scored; clustering by ≥15° "
        f"angular separation finds {len(diverse)} genuinely distinct "
        "option(s) — not just the same direction repeated with tiny "
        "perturbations. Validity (undercut-free?), ranking transparency "
        "(why this beat the others), and stability (do nearby directions "
        "score similarly?) are the defensible claims here — not that this "
        "is uniquely *the* answer."
    )

    rows = []
    for candidate in diverse:
        candidate_direction = candidate.get("direction")
        separation = (
            _angular_separation_deg(candidate_direction, best_direction)
            if best_direction else 0.0
        )
        percentages = candidate.get("percentages", {}) or {}
        undercuts = candidate.get("undercuts", {}) or {}
        rows.append({
            "Direction": _direction_axis_tilt_text(candidate_direction),
            "Score": candidate.get("score"),
            "From best": f"{separation:.1f}°",
            "Bad draft area": f"{percentages.get('bad_area_pct', 0)}%",
            "Undercut features": undercuts.get("feature_count", 0),
            "Boolean-refined": "Yes" if candidate.get("boolean_refined") else "No",
        })
    _safe_dataframe(rows, use_container_width=True)

    if len(diverse) <= 1:
        st.info(
            "Every scored candidate is within 15° of the best direction — "
            "this part's real option space is narrow, not an artefact of "
            "under-searching."
        )


def _direction_label_display(
    direction: dict[str, Any],
    *,
    label_key: str = "best_label",
    vector_key: str = "best_direction",
) -> str:
    """
    Show the direction's axis label (e.g. "+Z") plus vector+tilt — but
    without duplicating the vector when the label itself already fell back
    to raw vector text (`_direction_label` in direction_optimizer.py returns
    the vector string, not a real axis label, for any non-axis-aligned
    direction).
    """
    label = str(direction.get(label_key, "") or "")
    vector_text = _direction_axis_tilt_text(direction.get(vector_key))
    is_axis_label = len(label) == 2 and label[0] in "+-" and label[1] in "XYZ"
    return f"{label} {vector_text}" if is_axis_label else vector_text


def _draft_bad_area_pct(draft: dict[str, Any] | None) -> float:
    if not isinstance(draft, dict):
        return 0.0
    return _safe_float(draft.get("percentages", {}).get("bad_pct", 0.0))


def _draft_bad_faces(draft: dict[str, Any] | None) -> int:
    if not isinstance(draft, dict):
        return 0
    return _safe_int(draft.get("face_counts", {}).get("bad", 0))


def _delta_text(before: float | int, after: float | int, suffix: str = "") -> str:
    delta = float(after) - float(before)
    sign = "+" if delta > 0.0 else ""
    if isinstance(before, int) and isinstance(after, int):
        return f"{sign}{int(delta)}{suffix}"
    return f"{sign}{delta:.2f}{suffix}"


def _comparison_status(before: float | int, after: float | int, *, lower_is_better: bool = True) -> str:
    before_value = float(before)
    after_value = float(after)
    if abs(after_value - before_value) <= 1e-9:
        return "Unchanged"
    improved = after_value < before_value if lower_is_better else after_value > before_value
    return "Improved" if improved else "Worse"


def _initial_undercuts_for_direction(
    direction: dict[str, Any],
    fallback_undercuts: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    return (
        fallback_undercuts
        or direction.get("initial_undercuts")
        or direction.get("undercuts_initial_direction")
    )


def _before_after_rows(
    direction: dict[str, Any],
    initial_undercuts: dict[str, Any],
    optimal_undercuts: dict[str, Any],
) -> list[dict[str, Any]]:
    initial_draft = direction.get("initial_draft", {}) or {}
    optimal_draft = direction.get("optimal_draft", {}) or {}
    initial_counts = _undercut_counts(initial_undercuts)
    optimal_counts = _undercut_counts(optimal_undercuts)
    before_bad_area = _draft_bad_area_pct(initial_draft)
    after_bad_area = _draft_bad_area_pct(optimal_draft)
    before_bad_faces = _draft_bad_faces(initial_draft)
    after_bad_faces = _draft_bad_faces(optimal_draft)
    return [
        {
            "Metric": "Pull direction",
            "Before": _direction_axis_tilt_text(direction.get("initial_pull_direction")),
            "After": _direction_axis_tilt_text(direction.get("best_direction")),
            "Change": direction.get("best_label", "best candidate"),
            "Status": "Computed",
        },
        {
            "Metric": "Bad draft area",
            "Before": f"{before_bad_area:.2f}%",
            "After": f"{after_bad_area:.2f}%",
            "Change": _delta_text(before_bad_area, after_bad_area, "%"),
            "Status": _comparison_status(before_bad_area, after_bad_area),
        },
        {
            "Metric": "Bad draft faces",
            "Before": before_bad_faces,
            "After": after_bad_faces,
            "Change": _delta_text(before_bad_faces, after_bad_faces),
            "Status": _comparison_status(before_bad_faces, after_bad_faces),
        },
        {
            "Metric": "Undercut features",
            "Before": initial_counts["total"],
            "After": optimal_counts["total"],
            "Change": _delta_text(initial_counts["total"], optimal_counts["total"]),
            "Status": _comparison_status(initial_counts["total"], optimal_counts["total"]),
        },
        {
            "Metric": "Major undercut features",
            "Before": initial_counts["major"],
            "After": optimal_counts["major"],
            "Change": _delta_text(initial_counts["major"], optimal_counts["major"]),
            "Status": _comparison_status(initial_counts["major"], optimal_counts["major"]),
        },
        {
            "Metric": "Side-action triggers",
            "Before": initial_counts["side_action"],
            "After": optimal_counts["side_action"],
            "Change": _delta_text(initial_counts["side_action"], optimal_counts["side_action"]),
            "Status": _comparison_status(initial_counts["side_action"], optimal_counts["side_action"]),
        },
    ]


def _before_after_story_text(
    direction: dict[str, Any],
    initial_undercuts: dict[str, Any],
    optimal_undercuts: dict[str, Any],
) -> tuple[str, str, str]:
    initial_counts = _undercut_counts(initial_undercuts)
    optimal_counts = _undercut_counts(optimal_undercuts)
    before_bad_area = _draft_bad_area_pct(direction.get("initial_draft", {}))
    after_bad_area = _draft_bad_area_pct(direction.get("optimal_draft", {}))
    major_delta = initial_counts["major"] - optimal_counts["major"]
    feature_delta = initial_counts["total"] - optimal_counts["total"]
    bad_area_delta = before_bad_area - after_bad_area

    if major_delta > 0:
        tone = "success"
        title = f"Best direction removes {major_delta} major undercut feature(s)"
    elif feature_delta > 0 or bad_area_delta > 0.0:
        tone = "info"
        title = "Best direction reduces manufacturing risk"
    elif optimal_counts["major"] or optimal_counts["critical"]:
        tone = "warning"
        title = "Residual major undercut risk remains after optimization"
    else:
        tone = "success"
        title = "Best direction keeps the residual Level 1 risk clear"

    body = (
        f"Before uses the selected initial pull vector {_direction_axis_tilt_text(direction.get('initial_pull_direction'))}; "
        f"after uses {_direction_label_display(direction)}. "
        f"Bad draft area changes from {before_bad_area:.2f}% to {after_bad_area:.2f}%, "
        f"and undercut features change from {initial_counts['total']} to {optimal_counts['total']}."
    )
    return tone, title, body


def _render_before_after_story(
    direction: dict[str, Any] | None,
    initial_undercuts: dict[str, Any] | None,
    optimal_undercuts: dict[str, Any] | None,
    *,
    compact: bool = False,
) -> None:
    if not isinstance(direction, dict):
        return
    initial = _initial_undercuts_for_direction(direction, initial_undercuts)
    optimal = optimal_undercuts or direction.get("optimal_undercuts") or direction.get("undercuts_optimal_direction")
    if not isinstance(initial, dict) or not isinstance(optimal, dict):
        return

    tone, title, body = _before_after_story_text(direction, initial, optimal)
    st.markdown(
        "<div class='dfm-story-band'>"
        "<div class='dfm-story-kicker'>Before vs After</div>"
        f"<div class='dfm-story-title'>{_html_escape(title)}</div>"
        f"<div class='dfm-story-body'>{_html_escape(body)}</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    if tone == "success":
        st.success(title)
    elif tone == "warning":
        st.warning(title)
    else:
        st.info(title)

    initial_counts = _undercut_counts(initial)
    optimal_counts = _undercut_counts(optimal)
    _render_summary_grid([
        (
            "Before Direction",
            direction.get("initial_label", "Selected initial"),
            _direction_axis_tilt_text(direction.get("initial_pull_direction")),
        ),
        (
            "After Direction",
            direction.get("best_label", "Best candidate"),
            _direction_axis_tilt_text(direction.get("best_direction")),
        ),
        (
            "Draft Bad Area",
            f"{_draft_bad_area_pct(direction.get('initial_draft', {})):.2f}% -> "
            f"{_draft_bad_area_pct(direction.get('optimal_draft', {})):.2f}%",
            "selected vector to optimized vector",
        ),
        (
            "Undercuts",
            f"{initial_counts['total']} -> {optimal_counts['total']}",
            f"major {initial_counts['major']} -> {optimal_counts['major']}",
        ),
    ])
    if not compact:
        _safe_dataframe(
            _before_after_rows(direction, initial, optimal),
            use_container_width=True,
        )


def _render_color_legend(items: list[tuple[str, str]]) -> None:
    legend_items = []
    for label, color in items:
        legend_items.append(
            "<span class='dfm-legend-item'>"
            f"<span class='dfm-swatch' style='background:{_html_escape(color)}'></span>"
            f"{_html_escape(label)}</span>"
        )
    st.markdown(
        f"<div class='dfm-legend'>{''.join(legend_items)}</div>",
        unsafe_allow_html=True,
    )


def _summary_tile(label: str, value: object, detail: object = "") -> str:
    detail_html = (
        f"<div class='dfm-summary-subtle'>{_html_escape(detail)}</div>"
        if detail not in ("", None)
        else ""
    )
    return (
        "<div class='dfm-summary-tile'>"
        f"<div class='dfm-summary-label'>{_html_escape(label)}</div>"
        f"<div class='dfm-summary-value'>{_html_escape(value)}</div>"
        f"{detail_html}</div>"
    )


def _render_summary_grid(tiles: list[tuple[str, object, object]]) -> None:
    html = "".join(_summary_tile(label, value, detail) for label, value, detail in tiles)
    st.markdown(f"<div class='dfm-summary-grid'>{html}</div>", unsafe_allow_html=True)


def _draft_legend() -> None:
    _render_color_legend([
        ("Good draft", "#00d94d"),
        ("Marginal draft", "#ffd900"),
        ("Bad / negative draft", "#f2261a"),
        ("Skipped / unknown", "#8c8c8c"),
    ])


def _undercut_legend(*, important_only: bool = False) -> None:
    items = [
        ("Boolean-confirmed critical/high", "#ff3232"),
        ("Boolean-confirmed medium", "#ff7832"),
        ("Boolean-confirmed low/minor", "#ffa532"),
        ("Proxy-only evidence", "#ffe696"),
        ("Parting / accessible", "#b4b4b4"),
        ("Neutral base", "#d2d2d2"),
    ]
    if important_only:
        items.append(("Proxy faces muted in high-confidence view", "#bfc7d1"))
    _render_color_legend(items)


def _is_important_undercut_style(style_key: object) -> bool:
    value = str(style_key or "").lower()
    return value.endswith("boolean_confirmed")


def _filtered_undercut_mesh_payload(
    mesh_payload: dict[str, Any],
    *,
    important_only: bool,
    show_proxy_faces: bool = False,
) -> dict[str, Any]:
    """
    Return a display-only mesh where low-priority proxy evidence is muted.

    The backend result still contains every retained undercut face.  This helper
    only changes the visual RGB/classification arrays used by the PyVista view,
    so tables, counts, and JSON remain complete.
    """
    if show_proxy_faces:
        return mesh_payload
    if not important_only:
        return mesh_payload

    classifications = mesh_payload.get("undercut_classification")
    rgb_values = mesh_payload.get("undercut_rgb")
    if not isinstance(classifications, list) or not isinstance(rgb_values, list):
        return mesh_payload
    if len(classifications) != len(rgb_values):
        return mesh_payload

    filtered = dict(mesh_payload)
    muted_rgb = [0.824, 0.824, 0.824]
    proxy_rgb = [1.0, 0.902, 0.588]
    filtered_classes: list[str] = []
    filtered_rgb: list[list[float]] = []
    hidden_count = 0
    visible_count = 0
    for classification, rgb in zip(classifications, rgb_values):
        value = str(classification or "")
        is_undercut_evidence = (
            "undercut" in value
            or "proxy" in value
            or "fallback" in value
            or "boolean_confirmed" in value
        )
        if is_undercut_evidence and not _is_important_undercut_style(value):
            filtered_classes.append("filtered_proxy_evidence")
            filtered_rgb.append(muted_rgb if important_only else proxy_rgb)
            hidden_count += 1
        else:
            filtered_classes.append(value)
            filtered_rgb.append(rgb)
            if is_undercut_evidence:
                visible_count += 1

    filtered["undercut_classification"] = filtered_classes
    filtered["undercut_rgb"] = filtered_rgb
    filtered["undercut_visual_filter"] = {
        "mode": "important_only",
        "visible_evidence_faces": visible_count,
        "hidden_proxy_faces": hidden_count,
    }
    return filtered


def _is_undercut_overlay_style(style_key: object) -> bool:
    value = str(style_key or "").lower()
    if value in {"accessible", "parting", "filtered_proxy_evidence"}:
        return False
    return (
        "undercut" in value
        or "proxy" in value
        or "fallback" in value
        or "boolean_confirmed" in value
    )


def _undercut_face_overlay_region(
    mesh_payload: dict[str, Any],
    *,
    label: str,
) -> dict[str, Any] | None:
    """
    Build a translucent triangle overlay from undercut-classified mesh cells.

    Draft analysis owns full face coloring.  Undercut visualization uses this
    subset overlay so the exact B-Rep display mesh remains neutral while
    inaccessible regions are drawn as a separate evidence layer.
    """
    points = mesh_payload.get("points") or []
    faces = mesh_payload.get("faces") or []
    classifications = mesh_payload.get("undercut_classification") or []
    colors = mesh_payload.get("undercut_rgb") or []
    face_ids = mesh_payload.get("face_ids") or []

    if not points or not faces or len(classifications) != len(faces):
        return None
    if len(colors) != len(faces):
        return None

    selected_indices = [
        index for index, classification in enumerate(classifications)
        if _is_undercut_overlay_style(classification)
    ]
    if not selected_indices:
        return None

    point_map: dict[int, int] = {}
    overlay_points: list[list[float]] = []
    overlay_faces: list[list[int]] = []
    overlay_colors: list[list[float]] = []
    overlay_face_ids: list[int] = []

    for triangle_index in selected_indices:
        triangle = faces[triangle_index]
        if not isinstance(triangle, list) or len(triangle) != 3:
            continue
        remapped: list[int] = []
        for point_index in triangle:
            try:
                source_index = int(point_index)
            except (TypeError, ValueError):
                remapped = []
                break
            if source_index < 0 or source_index >= len(points):
                remapped = []
                break
            if source_index not in point_map:
                point_map[source_index] = len(overlay_points)
                overlay_points.append(points[source_index])
            remapped.append(point_map[source_index])
        if len(remapped) != 3:
            continue
        overlay_faces.append(remapped)
        overlay_colors.append(colors[triangle_index])
        if triangle_index < len(face_ids):
            try:
                overlay_face_ids.append(int(face_ids[triangle_index]))
            except (TypeError, ValueError):
                overlay_face_ids.append(-1)

    if not overlay_faces:
        return None

    mesh = {
        "point_count": len(overlay_points),
        "triangle_count": len(overlay_faces),
        "points": overlay_points,
        "faces": overlay_faces,
        "region_rgb": overlay_colors,
        "face_ids": overlay_face_ids,
    }
    return {
        "feature_id": "undercut-face-overlay",
        "shape_index": 0,
        "severity": "display-overlay",
        "label": label,
        "visual_style": {
            "edge_color": "#7a1c10",
            "label": label,
            "opacity": 0.46,
        },
        "mesh": mesh,
    }


def _major_feature_face_ids(
    undercuts: dict[str, Any],
    *,
    include_proxy_faces: bool = False,
) -> set[int]:
    face_ids: set[int] = set()
    for feature in _feature_list(undercuts):
        if not _is_major_undercut_feature(feature):
            continue
        evidence_keys = [
            "boolean_intersection_face_ids",
            "boolean_confirmed_face_ids",
        ]
        if include_proxy_faces:
            evidence_keys.extend([
                "boolean_failed_face_ids",
                "boolean_skipped_face_ids",
                "face_ids",
            ])
        for key in evidence_keys:
            for face_id in feature.get(key, []) or []:
                try:
                    face_ids.add(int(face_id))
                except (TypeError, ValueError):
                    continue
    return face_ids


def _major_feature_overlay_region(
    mesh_payload: dict[str, Any],
    undercuts: dict[str, Any],
    *,
    label: str = "Major undercut feature overlay",
    include_proxy_faces: bool = False,
) -> dict[str, Any] | None:
    major_face_ids = _major_feature_face_ids(
        undercuts,
        include_proxy_faces=include_proxy_faces,
    )
    if not major_face_ids:
        return None

    points = mesh_payload.get("points") or []
    faces = mesh_payload.get("faces") or []
    face_ids = mesh_payload.get("face_ids") or []
    if not points or not faces or len(face_ids) != len(faces):
        return None

    selected_indices: list[int] = []
    for index, face_id in enumerate(face_ids):
        try:
            parsed_face_id = int(face_id)
        except (TypeError, ValueError):
            continue
        if parsed_face_id in major_face_ids:
            selected_indices.append(index)
    if not selected_indices:
        return None

    point_map: dict[int, int] = {}
    overlay_points: list[list[float]] = []
    overlay_faces: list[list[int]] = []
    overlay_face_ids: list[int] = []
    for triangle_index in selected_indices:
        triangle = faces[triangle_index]
        if not isinstance(triangle, list) or len(triangle) != 3:
            continue
        remapped: list[int] = []
        for point_index in triangle:
            try:
                source_index = int(point_index)
            except (TypeError, ValueError):
                remapped = []
                break
            if source_index < 0 or source_index >= len(points):
                remapped = []
                break
            if source_index not in point_map:
                point_map[source_index] = len(overlay_points)
                overlay_points.append(points[source_index])
            remapped.append(point_map[source_index])
        if len(remapped) != 3:
            continue
        overlay_faces.append(remapped)
        overlay_face_ids.append(int(face_ids[triangle_index]))

    if not overlay_faces:
        return None

    mesh = {
        "point_count": len(overlay_points),
        "triangle_count": len(overlay_faces),
        "points": overlay_points,
        "faces": overlay_faces,
        "region_rgb": [[1.0, 0.02, 0.0] for _ in overlay_faces],
        "face_ids": overlay_face_ids,
    }
    return {
        "feature_id": "major-undercut-face-overlay",
        "shape_index": 0,
        "severity": "major",
        "label": label,
        "visual_style": {
            "edge_color": "#1f0b08",
            "label": label,
            "opacity": 0.78,
            "line_width": 2.2,
        },
        "mesh": mesh,
    }


def _mesh_to_pyvista(mesh_payload: dict[str, Any], color_key: str = "draft_rgb") -> Any:
    import numpy as np
    import pyvista as pv

    points_payload = mesh_payload.get("points") or []
    faces_payload = mesh_payload.get("faces") or []
    if not points_payload or not faces_payload:
        raise ValueError("mesh payload does not contain renderable points/faces")

    points = np.asarray(points_payload, dtype=float)
    faces = np.asarray(
        [[3, int(a), int(b), int(c)] for a, b, c in faces_payload],
        dtype=int,
    ).ravel()
    poly = pv.PolyData(points, faces)
    color_values = mesh_payload.get(color_key)
    face_ids = mesh_payload.get("face_ids")
    if isinstance(color_values, list) and len(color_values) == len(faces_payload):
        poly.cell_data[color_key] = np.asarray(color_values, dtype=float)
    if isinstance(face_ids, list) and len(face_ids) == len(faces_payload):
        poly.cell_data["face_id"] = np.asarray(face_ids, dtype=int)
    return poly


def _line_path_to_pyvista(points_payload: list[list[float]]) -> Any:
    import numpy as np
    import pyvista as pv

    if len(points_payload) < 2:
        raise ValueError("line path requires at least two points")
    points = np.asarray(points_payload, dtype=float)
    line = np.asarray([len(points), *range(len(points))], dtype=int)
    poly = pv.PolyData(points)
    poly.lines = line
    return poly


def _marker_points_to_pyvista(points_payload: list[list[float]]) -> Any:
    import numpy as np
    import pyvista as pv

    if not points_payload:
        raise ValueError("marker payload requires at least one point")
    return pv.PolyData(np.asarray(points_payload, dtype=float))


def _resolve_mesh_color_values(
    mesh_payload: dict[str, Any],
    color_key: str,
) -> list[list[float]] | None:
    faces_payload = mesh_payload.get("faces") or []
    if not faces_payload:
        return None
    expected = len(faces_payload)
    for key in (
        color_key,
        "draft_rgb",
        "undercut_rgb",
        "parting_rgb",
        "core_cavity_rgb",
    ):
        color_values = mesh_payload.get(key)
        if isinstance(color_values, list) and len(color_values) == expected:
            return color_values
    return None


def _show_mesh_offscreen(plotter: Any, key: str = "mesh") -> None:
    """Render PyVista plotter — Linux/Docker only. Never call on macOS (VTK thread crash)."""
    try:
        from stpyvista import stpyvista as _stpyvista_fn
        _stpyvista_fn(plotter, key=key)
    except Exception:
        try:
            img = plotter.screenshot(return_img=True)
            plotter.close()
            st.image(img, use_container_width=True)
        except Exception as shot_err:
            st.error(f"3D render failed: {shot_err}")
            st.info("Mesh data available but cannot render in this environment.")


def _show_mesh(
    mesh_payload: dict[str, Any],
    color_key: str = "draft_rgb",
    region_meshes: list[dict[str, Any]] | None = None,
    line_paths: list[dict[str, Any]] | None = None,
    region_opacity: float = 0.55,
    show_region_edges: bool = True,
    marker_points: list[dict[str, Any]] | None = None,
    viewer_key: str | None = None,
) -> bool:
    # macOS + Streamlit runs scripts on worker threads; VTK Cocoa crashes if used there.
    if _USE_PLOTLY_VIEWER:
        return _show_mesh_plotly(
            mesh_payload,
            color_key=color_key,
            region_meshes=region_meshes,
            line_paths=line_paths,
            region_opacity=region_opacity,
            marker_points=marker_points,
            viewer_key=viewer_key,
        )

    try:
        import pyvista as pv
    except ImportError as exc:
        st.warning(f"PyVista viewer dependencies are unavailable: {exc}")
        return False

    try:
        try:
            pv.OFF_SCREEN = True
        except Exception:
            pass

        poly = _mesh_to_pyvista(mesh_payload, color_key=color_key)
        plotter = pv.Plotter(window_size=(1100, 720), off_screen=True)
        plotter.set_background("#f6f7f9")
        try:
            plotter.enable_anti_aliasing("fxaa")
        except Exception:
            pass
        if color_key in poly.cell_data:
            plotter.add_mesh(
                poly,
                scalars=color_key,
                rgb=True,
                show_edges=True,
                edge_color="#30343b",
                line_width=0.4,
                ambient=0.35,
                diffuse=0.65,
                specular=0.12,
            )
        else:
            plotter.add_mesh(
                poly,
                color="#b8c0cc",
                show_edges=True,
                edge_color="#30343b",
                line_width=0.4,
                ambient=0.35,
                diffuse=0.65,
                specular=0.12,
            )
        for region in region_meshes or []:
            region_payload = region.get("mesh", {})
            if not region_payload.get("points") or not region_payload.get("faces"):
                continue
            region_poly = _mesh_to_pyvista(region_payload, color_key="region_rgb")
            visual_style = region.get("visual_style", {})
            plotter.add_mesh(
                region_poly,
                scalars="region_rgb" if "region_rgb" in region_poly.cell_data else None,
                rgb="region_rgb" in region_poly.cell_data,
                color=None if "region_rgb" in region_poly.cell_data else "#f97316",
                opacity=float(visual_style.get("opacity", region_opacity)),
                show_edges=show_region_edges,
                edge_color=str(visual_style.get("edge_color", "#7a1c10")),
                line_width=float(visual_style.get("line_width", 0.9)) if show_region_edges else 0.0,
                smooth_shading=True,
                ambient=0.45,
                diffuse=0.75,
                specular=0.18,
            )
        for line_path in line_paths or []:
            points_payload = line_path.get("points", [])
            if len(points_payload) < 2:
                continue
            line_poly = _line_path_to_pyvista(points_payload)
            plotter.add_mesh(
                line_poly,
                color=str(line_path.get("hex", "#00b8ff")),
                line_width=int(line_path.get("width", 6)),
                render_lines_as_tubes=True,
                name=str(line_path.get("label", "parting-line")),
            )
        marker_payloads = marker_points or []
        marker_coords = [
            marker.get("point")
            for marker in marker_payloads
            if isinstance(marker.get("point"), list) and len(marker.get("point")) == 3
        ]
        if marker_coords:
            marker_poly = _marker_points_to_pyvista(marker_coords)
            plotter.add_mesh(
                marker_poly,
                color="#ff3b30",
                point_size=18,
                render_points_as_spheres=True,
                name="undercut-conflict-markers",
            )
        plotter.add_axes()
        plotter.camera_position = "iso"
        plotter.reset_camera()
        # Slight zoom-out so the complete part sits comfortably inside the
        # frame with margin, rather than touching the edges or clipping.
        plotter.camera.zoom(0.85)
        _show_mesh_offscreen(
            plotter,
            key=viewer_key or (
                f"viewer-{color_key}-{len(region_meshes or [])}-"
                f"{len(marker_points or [])}-{region_opacity:.2f}"
            ),
        )
    except Exception as exc:
        st.warning(f"3D viewer failed; showing structured fallback instead. Details: {exc}")
        return False
    return True


def _rgb_to_hex(rgb: list[float]) -> str:
    values = [
        max(0, min(255, int(round(float(component) * 255.0))))
        for component in rgb[:3]
    ]
    return f"#{values[0]:02x}{values[1]:02x}{values[2]:02x}"


def _show_mesh_plotly(
    mesh_payload: dict[str, Any],
    color_key: str = "draft_rgb",
    region_meshes: list[dict[str, Any]] | None = None,
    line_paths: list[dict[str, Any]] | None = None,
    region_opacity: float = 0.55,
    marker_points: list[dict[str, Any]] | None = None,
    viewer_key: str | None = None,
) -> bool:
    """Browser-based 3D viewer for macOS (avoids VTK Cocoa thread crashes)."""
    try:
        import plotly.graph_objects as go
    except ImportError as exc:
        st.warning(f"Plotly viewer is unavailable: {exc}")
        return False

    points_payload = mesh_payload.get("points") or []
    faces_payload = mesh_payload.get("faces") or []
    if not points_payload or not faces_payload:
        return False

    traces: list[Any] = []
    mesh_kwargs: dict[str, Any] = {
        "x": [float(p[0]) for p in points_payload],
        "y": [float(p[1]) for p in points_payload],
        "z": [float(p[2]) for p in points_payload],
        "i": [int(f[0]) for f in faces_payload],
        "j": [int(f[1]) for f in faces_payload],
        "k": [int(f[2]) for f in faces_payload],
        "flatshading": True,
        "name": "part",
    }
    color_values = _resolve_mesh_color_values(mesh_payload, color_key)
    if color_values is not None:
        mesh_kwargs["facecolor"] = [_rgb_to_hex(c) for c in color_values]
        mesh_kwargs["opacity"] = 1.0
    else:
        mesh_kwargs["color"] = "#b8c0cc"
        mesh_kwargs["opacity"] = 1.0
    traces.append(go.Mesh3d(**mesh_kwargs))

    for region in region_meshes or []:
        region_payload = region.get("mesh", {})
        region_points = region_payload.get("points") or []
        region_faces = region_payload.get("faces") or []
        if not region_points or not region_faces:
            continue
        visual_style = region.get("visual_style", {})
        region_kwargs: dict[str, Any] = {
            "x": [float(p[0]) for p in region_points],
            "y": [float(p[1]) for p in region_points],
            "z": [float(p[2]) for p in region_points],
            "i": [int(f[0]) for f in region_faces],
            "j": [int(f[1]) for f in region_faces],
            "k": [int(f[2]) for f in region_faces],
            "opacity": float(visual_style.get("opacity", region_opacity)),
            "flatshading": True,
            "name": str(region.get("label", "region")),
        }
        region_colors = region_payload.get("region_rgb")
        if isinstance(region_colors, list) and len(region_colors) == len(region_faces):
            region_kwargs["facecolor"] = [_rgb_to_hex(c) for c in region_colors]
        else:
            region_kwargs["color"] = "#f97316"
        traces.append(go.Mesh3d(**region_kwargs))

    for line_path in line_paths or []:
        points = line_path.get("points", [])
        if len(points) < 2:
            continue
        line_x = [float(p[0]) for p in points]
        line_y = [float(p[1]) for p in points]
        line_z = [float(p[2]) for p in points]
        line_width = float(line_path.get("width", 6))
        # Dark outline trace drawn first, bright core trace on top -- makes
        # the line read clearly against any mesh/overlay colour underneath,
        # not just a single thin stroke that can blend into the part.
        if line_width > 6:
            traces.append(
                go.Scatter3d(
                    x=line_x, y=line_y, z=line_z,
                    mode="lines",
                    line=dict(color="#ffffff", width=line_width * 1.7),
                    hoverinfo="skip",
                    showlegend=False,
                    name=f"{line_path.get('label', 'parting-line')} (outline)",
                )
            )
        traces.append(
            go.Scatter3d(
                x=line_x, y=line_y, z=line_z,
                mode="lines",
                line=dict(color=str(line_path.get("hex", "#00b8ff")), width=line_width),
                name=str(line_path.get("label", "parting-line")),
            )
        )

    marker_coords = [
        marker.get("point")
        for marker in (marker_points or [])
        if isinstance(marker.get("point"), list) and len(marker.get("point")) == 3
    ]
    if marker_coords:
        traces.append(
            go.Scatter3d(
                x=[float(p[0]) for p in marker_coords],
                y=[float(p[1]) for p in marker_coords],
                z=[float(p[2]) for p in marker_coords],
                mode="markers",
                marker=dict(size=5, color="#ff3b30"),
                name="undercut-conflict-markers",
            )
        )

    fig = go.Figure(data=traces)
    fig.update_layout(
        height=720,
        margin=dict(l=0, r=0, t=0, b=0),
        scene=dict(
            aspectmode="data",
            bgcolor="#f6f7f9",
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            zaxis=dict(visible=False),
            # Pulled back slightly from Plotly's default (1.25,1.25,1.25) so
            # the full part sits comfortably inside the frame with a margin,
            # rather than touching the edges or being auto-clipped.
            camera=dict(eye=dict(x=1.65, y=1.65, z=1.35)),
        ),
        showlegend=True,
        legend=dict(bgcolor="rgba(255,255,255,0.75)"),
    )
    chart_key = viewer_key or f"dfm-mesh-{color_key}-{len(faces_payload)}"
    st.plotly_chart(
        fig,
        use_container_width=True,
        key=chart_key,
    )
    return True


def _show_boolean_region_status(boolean_regions: dict[str, Any], label: str) -> None:
    c1, c2, c3 = st.columns(3)
    c1.metric(label, boolean_regions.get("region_count", 0))
    c2.metric("Region Triangles", boolean_regions.get("triangle_count", 0))
    c3.metric("Mesh Warnings", len(boolean_regions.get("warnings", [])))

    warnings = boolean_regions.get("warnings", [])
    if warnings:
        with st.expander("Boolean region mesh warnings"):
            for warning in warnings:
                st.warning(warning)


def _show_boolean_region_legend(boolean_regions: dict[str, Any]) -> None:
    legend = boolean_regions.get("legend") or DEFAULT_BOOLEAN_LEGEND
    chips = []
    for severity in ("critical", "moderate", "minor"):
        item = legend.get(severity)
        if not item:
            continue
        color = _rgb_to_hex(item.get("rgb", [1.0, 0.48, 0.04]))
        label = item.get("label", severity.title())
        chips.append((label, color))
    if chips:
        _render_color_legend(chips)


def _path_length_mm(points: list[list[float]]) -> float:
    total = 0.0
    for start, end in zip(points, points[1:]):
        try:
            dx = float(end[0]) - float(start[0])
            dy = float(end[1]) - float(start[1])
            dz = float(end[2]) - float(start[2])
        except (TypeError, ValueError, IndexError):
            continue
        total += (dx * dx + dy * dy + dz * dz) ** 0.5
    return total


def _curve_metrics(path_payload: dict[str, Any]) -> dict[str, Any]:
    points = path_payload.get("points", []) or []
    display_metrics = path_payload.get("display_metrics", {}) or {}
    return {
        "label": path_payload.get("label", "Curve"),
        "point_count": len(points),
        "length_mm": round(_path_length_mm(points), 4),
        "visible_by_default": bool(path_payload.get("visible_by_default", False)),
        "color": path_payload.get("hex", "#00b8ff"),
        "width": path_payload.get("width", 0),
        "smoothing_iterations": (
            _safe_int(path_payload.get("smoothing_iterations"))
            if path_payload.get("smoothing_iterations") not in (None, "")
            else None
        ),
        "quality": path_payload.get("quality") or None,
        "raw_length_mm": display_metrics.get("raw_length_mm"),
        "refined_length_mm": display_metrics.get("refined_length_mm"),
        "closure_error_mm": display_metrics.get("closure_error_mm"),
        "max_turn_reduction_pct": display_metrics.get("max_turn_reduction_pct"),
    }


def _render_parting_curve_display_metrics(refinement: dict[str, Any]) -> None:
    metrics = refinement.get("display_metrics", {}) or {}
    if not metrics:
        return

    smoothing = metrics.get(
        "applied_smoothing_iterations",
        refinement.get("smoothing_iterations", 0),
    )
    requested = metrics.get("requested_smoothing_iterations", smoothing)
    point_label = (
        f"{metrics.get('resampled_point_count', 0)} -> "
        f"{metrics.get('refined_point_count', refinement.get('refined_point_count', 0))}"
    )
    _render_quality_indicators([
        (
            "Curve smoothing",
            f"{smoothing}/{requested}",
            "good" if _safe_int(smoothing) >= 5 else "warning",
        ),
        (
            "Display points",
            point_label,
            "info",
        ),
        (
            "Closure error",
            f"{float(metrics.get('closure_error_mm', 0.0) or 0.0):.4f} mm",
            "good" if float(metrics.get("closure_error_mm", 0.0) or 0.0) <= 0.001 else "warning",
        ),
        (
            "Turn cleanup",
            f"{float(metrics.get('max_turn_reduction_pct', 0.0) or 0.0):.1f}%",
            "good" if float(metrics.get("max_turn_reduction_pct", 0.0) or 0.0) >= 0 else "neutral",
        ),
    ])


def _visible_parting_line_paths(
    raw_path: dict[str, Any],
    refined_path: dict[str, Any],
    *,
    show_raw: bool,
    show_refined: bool,
) -> list[dict[str, Any]]:
    line_paths: list[dict[str, Any]] = []
    if show_raw and raw_path.get("points"):
        line_paths.append(raw_path)
    if show_refined and refined_path.get("points"):
        line_paths.append(refined_path)
    return line_paths


def _parting_conflict_rows(conflict: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    direct_faces = conflict.get("conflicting_face_ids", []) or []
    direct_edges = conflict.get("direct_edge_face_conflict_ids", []) or []
    if direct_faces or direct_edges:
        rows.append({
            "Type": "Direct edge-face overlap",
            "Feature": "-",
            "Severity": conflict.get("conflict_level", "unknown"),
            "Distance mm": "-",
            "Axis distance mm": "-",
            "Score": conflict.get("conflict_score", 0.0),
            "Evidence": (
                f"Faces {direct_faces or '-'}; edges {direct_edges or '-'}"
            ),
        })

    for item in conflict.get("near_feature_conflicts", []) or []:
        rows.append({
            "Type": "Projected feature proximity",
            "Feature": item.get("feature_id"),
            "Severity": item.get("severity", "unknown"),
            "Distance mm": item.get("projected_distance_mm"),
            "Axis distance mm": item.get("axis_distance_mm"),
            "Score": item.get("score_contribution"),
            "Evidence": f"Influence radius {item.get('influence_radius_mm')} mm",
        })
    return rows


def _parting_conflict_markers(conflict: dict[str, Any]) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    for item in conflict.get("near_feature_conflicts", []) or []:
        location = item.get("location")
        if isinstance(location, list) and len(location) == 3:
            markers.append({
                "point": location,
                "label": f"Feature {item.get('feature_id')}",
                "severity": item.get("severity", "unknown"),
            })
    return markers


def _graph_cleanup_rows(refinement: dict[str, Any]) -> list[dict[str, Any]]:
    cleanup = refinement.get("graph_cleanup", {}) or {}
    if not cleanup:
        return []
    warnings = cleanup.get("warnings", []) or []
    return [
        {
            "Area": "Status",
            "Result": cleanup.get("status", "unknown"),
            "Evidence": cleanup.get("strategy", "unknown"),
            "Review": "; ".join(warnings) if warnings else "-",
        },
        {
            "Area": "Edges",
            "Result": (
                f"{cleanup.get('retained_edge_count', 0)} retained / "
                f"{cleanup.get('removed_edge_count', 0)} removed"
            ),
            "Evidence": (
                f"{cleanup.get('orderable_edge_count', 0)} orderable of "
                f"{cleanup.get('input_edge_count', 0)} input"
            ),
            "Review": "Removed IDs: " + str(cleanup.get("removed_edge_ids", "-"))
            if cleanup.get("removed_edge_ids")
            else "-",
        },
        {
            "Area": "Undercut-aware cleanup",
            "Result": (
                f"{len(cleanup.get('removed_conflict_edge_ids', []) or [])} conflict edge(s) removed"
            ),
            "Evidence": (
                f"penalized {cleanup.get('conflict_penalized_edge_ids', []) or []}; "
                f"retained {cleanup.get('retained_conflict_edge_ids', []) or []}"
            ),
            "Review": (
                "Cleaned conflict branch"
                if cleanup.get("removed_conflict_edge_ids")
                else "No conflict edge removed"
            ),
        },
        {
            "Area": "Search",
            "Result": cleanup.get("search_state_count", 0),
            "Evidence": f"limit {cleanup.get('search_state_limit', 0)}",
            "Review": f"edge limit {cleanup.get('search_edge_limit', 0)}",
        },
    ]


def _render_feature_outcome_chips(features: list[dict[str, Any]]) -> None:
    if not features:
        return

    severity_counts: dict[str, int] = {}
    confidence_counts: dict[str, int] = {}
    for feature in features:
        severity = str(feature.get("severity", "unknown")).lower()
        confidence = str(feature.get("action_confidence_label", "unknown")).lower()
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        confidence_counts[confidence] = confidence_counts.get(confidence, 0) + 1

    severity_colors = {
        "critical": "#f04438",
        "moderate": "#f79009",
        "minor": "#fdb022",
        "unknown": "#98a2b3",
    }
    confidence_colors = {
        "high": "#12b76a",
        "medium": "#2e90fa",
        "low": "#f79009",
        "unknown": "#98a2b3",
    }

    chips: list[str] = []
    for severity in ("critical", "moderate", "minor", "unknown"):
        count = severity_counts.get(severity, 0)
        if count:
            chips.append(
                _status_chip(
                    f"{count} {severity}",
                    state="muted",
                    color=severity_colors[severity],
                )
            )
    for confidence in ("high", "medium", "low", "unknown"):
        count = confidence_counts.get(confidence, 0)
        if count:
            chips.append(
                _status_chip(
                    f"{count} {confidence} confidence",
                    state="muted",
                    color=confidence_colors[confidence],
                )
            )
    _render_chip_row(chips)


def _action_recommendation_rows(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for feature in features:
        rows.append({
            "Feature": feature.get("feature_id"),
            "Action": feature.get("recommended_mold_action"),
            "Confidence": feature.get("action_confidence_label"),
            "Score": feature.get("action_confidence"),
            "Severity": feature.get("severity"),
            "Type": feature.get("undercut_type"),
            "Depth mm": feature.get("depth_proxy_mm"),
            "Why": feature.get("action_explanation") or feature.get("action_reason"),
        })
    return rows


def _highest_severity_feature(undercuts: dict[str, Any]) -> dict[str, Any] | None:
    severity_rank = {"critical": 5, "high": 4, "medium": 3, "moderate": 2, "low": 1, "minor": 1}
    features = _feature_list(undercuts)
    if not features:
        return None
    return max(
        features,
        key=lambda feature: (
            severity_rank.get(_normalised_token(feature.get("severity")), 0),
            _safe_float(feature.get("interference_volume_mm3", 0.0)),
            _safe_float(feature.get("depth_proxy_mm", 0.0)),
        ),
    )


def _render_prominent_undercut_callout(undercuts: dict[str, Any]) -> None:
    features = _feature_list(undercuts)
    major_count = sum(1 for feature in features if feature.get("is_major_feature"))
    highest = _highest_severity_feature(undercuts)
    if not highest:
        return
    severity = str(highest.get("severity", "unknown")).title()
    volume = _safe_float(highest.get("interference_volume_mm3", 0.0))
    depth = _safe_float(highest.get("depth_proxy_mm", 0.0))
    action = highest.get("recommended_mold_action", "review")
    confidence = _safe_float(highest.get("action_confidence", 0.0))
    feature_type = highest.get("geometric_feature_type", highest.get("undercut_type", "unknown"))
    headline = (
        f"⚠️ {severity} Undercut Detected — "
        f"{str(action).replace('-', ' ').title()} "
        f"({volume:,.0f} mm³ volume, {depth:.1f}mm depth)"
    )
    st.warning(headline)
    st.info(
        f"Major undercut features: {major_count} | "
        f"Highest severity feature ID {highest.get('feature_id')} | "
        f"Type: {feature_type} | "
        f"Recommended action: {action} | "
        f"Confidence: {confidence:.2f} | "
        f"Depth proxy: {depth:.2f} mm | "
        f"Interference volume: {volume:,.0f} mm³"
    )


def _major_undercut_rows(undercuts: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for feature in _feature_list(undercuts):
        if not _is_major_undercut_feature(feature):
            continue
        rows.append({
            "Feature": feature.get("feature_id"),
            "Severity": feature.get("severity"),
            "Action": feature.get("recommended_mold_action"),
            "Confidence": feature.get("action_confidence_label"),
            "Faces": feature.get("face_count", len(feature.get("face_ids", []) or [])),
            "Confirmed": len(feature.get("boolean_confirmed_face_ids", []) or []),
            "Fallback": len(feature.get("boolean_failed_face_ids", []) or []),
            "Depth mm": feature.get("depth_proxy_mm"),
            "Volume mm3": feature.get("interference_volume_mm3"),
            "Why": _short_text(feature.get("action_explanation") or feature.get("action_reason"), 240),
        })
    return rows


def _major_undercut_headline(undercuts: dict[str, Any]) -> str:
    features = [
        feature for feature in _feature_list(undercuts)
        if _is_major_undercut_feature(feature)
    ]
    if not features:
        return ""
    critical_count = sum(
        1 for feature in features
        if _normalised_token(feature.get("severity")) == "critical"
    )
    side_action_count = sum(
        1 for feature in features
        if _normalised_token(feature.get("recommended_mold_action")) == "side-action"
    )
    severity_text = (
        "Critical "
        if critical_count
        else ""
    )
    recommendation = (
        " (Side-action recommended)"
        if side_action_count
        else " (Mold-action review required)"
    )
    return (
        f"{len(features)} Major {severity_text}Undercut Feature"
        f"{'' if len(features) == 1 else 's'} Detected{recommendation}"
    )


def _render_major_undercut_callout(
    undercuts: dict[str, Any],
    *,
    title: str = "Major Undercut Features",
) -> None:
    rows = _major_undercut_rows(undercuts)
    if not rows:
        return
    counts = _undercut_counts(undercuts)
    headline = _major_undercut_headline(undercuts)
    st.warning(
        headline
        or f"{counts['major']} major undercut feature(s) need mold-action review."
    )
    _render_quality_indicators([
        ("Major", counts["major"], "bad"),
        ("Critical", counts["critical"], _tone_for_count(counts["critical"], bad_at=1)),
        ("Side-action", counts["side_action"], _tone_for_count(counts["side_action"], bad_at=1)),
        ("High confidence", counts["high_confidence"], "good" if counts["high_confidence"] else "neutral"),
    ])
    with st.expander(title, expanded=True):
        _safe_dataframe(rows, use_container_width=True)


def _render_undercut_visual_summary(mesh_payload: dict[str, Any]) -> None:
    visual_summary = mesh_payload.get("undercut_visual_summary", {}) or {}
    counts = visual_summary.get("counts", {}) or {}
    if not counts:
        return
    visual_filter = mesh_payload.get("undercut_visual_filter", {}) or {}
    raw_highlight_count = (
        _safe_int(counts.get("critical_boolean_confirmed", 0))
        + _safe_int(counts.get("critical_proxy_fallback", 0))
        + _safe_int(counts.get("critical_proxy", 0))
    )
    visible_evidence = _safe_int(
        visual_filter.get("visible_evidence_faces", raw_highlight_count)
    )
    muted_proxy = _safe_int(visual_filter.get("hidden_proxy_faces", 0))
    fallback_count = sum(
        _safe_int(value)
        for key, value in counts.items()
        if "fallback" in str(key)
    )
    _render_quality_indicators([
        (
            "Visible overlay faces",
            visible_evidence,
            _tone_for_count(visible_evidence, bad_at=1),
        ),
        (
            "Retained fallback faces",
            fallback_count,
            _tone_for_count(fallback_count, warning_at=1, bad_at=50),
        ),
        (
            "Muted proxy faces",
            muted_proxy,
            _tone_for_count(muted_proxy, warning_at=1),
        ),
    ])
    if visible_evidence <= 0 and muted_proxy > 0:
        st.info(
            "Proxy fallback undercut faces are retained in the result but muted in this view. "
            "Enable 'Show proxy fallback faces' in the sidebar to audit them."
        )


def _short_text(value: object, limit: int = 160) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return f"{text[:limit - 3]}..."


def _dict_lookup(mapping: dict[Any, Any], key: object, default: Any = None) -> Any:
    if not isinstance(mapping, dict):
        return default
    if key in mapping:
        return mapping[key]
    text_key = str(key)
    if text_key in mapping:
        return mapping[text_key]
    try:
        int_key = int(key)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return mapping.get(int_key, default)


def _boolean_failure_rows(undercuts: dict[str, Any]) -> list[dict[str, Any]]:
    refinement = undercuts.get("boolean_refinement", {}) or {}
    failed_ids = refinement.get("failed_face_ids", []) or []
    failure_reasons = refinement.get("failure_reasons", {}) or {}
    failure_details = refinement.get("failure_details", {}) or {}
    rows: list[dict[str, Any]] = []
    for face_id in sorted({_safe_int(face_id) for face_id in failed_ids}):
        detail = _dict_lookup(failure_details, face_id, {}) or {}
        reason = _dict_lookup(failure_reasons, face_id, "")
        rows.append({
            "Face": face_id,
            "Failure class": detail.get("failure_class", "unknown"),
            "Attempts": detail.get("attempt_count", 0),
            "Fallback": detail.get("fallback_action", "proxy-retained-after-boolean-failure"),
            "Last error": _short_text(detail.get("last_error") or reason, 220),
        })
    return rows


def _boolean_feature_fallback_rows(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for feature in features:
        failed = feature.get("boolean_failed_face_ids", []) or []
        skipped = feature.get("boolean_skipped_face_ids", []) or []
        evidence_source = str(feature.get("evidence_source", "unknown"))
        if not (failed or skipped or "failure" in evidence_source or "skip" in evidence_source):
            continue
        rows.append({
            "Feature": feature.get("feature_id"),
            "Evidence source": evidence_source,
            "Confirmed faces": len(feature.get("boolean_confirmed_face_ids", []) or []),
            "Failed faces": len(failed),
            "Skipped faces": len(skipped),
            "Action": feature.get("recommended_mold_action"),
            "Confidence": feature.get("action_confidence_label"),
            "Fallback note": _short_text(feature.get("action_explanation") or feature.get("action_reason"), 220),
        })
    return rows


def _boolean_reliability_rows(reliability: dict[str, Any]) -> list[dict[str, Any]]:
    if not reliability:
        return []
    failure_counts = reliability.get("failure_class_counts", {}) or {}
    skip_counts = reliability.get("skip_reason_counts", {}) or {}
    failure_text = ", ".join(
        f"{key}: {value}" for key, value in sorted(failure_counts.items())
    ) or "none"
    skip_text = ", ".join(
        f"{key}: {value}" for key, value in sorted(skip_counts.items())
    ) or "none"
    return [
        {
            "Evidence Area": "Reliability",
            "Value": reliability.get("reliability_label", "unknown"),
            "Detail": f"score {reliability.get('reliability_score', 0.0)}",
        },
        {
            "Evidence Area": "Operation success",
            "Value": f"{100.0 * _safe_float(reliability.get('successful_operation_ratio', 0.0)):.1f}%",
            "Detail": (
                f"checked {reliability.get('checked_count', 0)} | "
                f"failed {reliability.get('failed_count', 0)} | "
                f"skipped {reliability.get('skipped_count', 0)}"
            ),
        },
        {
            "Evidence Area": "Proxy retained",
            "Value": reliability.get("proxy_retained_face_count", 0),
            "Detail": (
                f"failed proxy {reliability.get('proxy_retained_failed_count', 0)} | "
                f"skipped proxy {reliability.get('proxy_retained_skipped_count', 0)}"
            ),
        },
        {
            "Evidence Area": "Failure classes",
            "Value": failure_text,
            "Detail": f"Skip classes: {skip_text}",
        },
    ]


def _render_boolean_refinement_visibility(
    undercuts: dict[str, Any],
    *,
    title: str = "Boolean refinement diagnostics",
) -> None:
    refinement = undercuts.get("boolean_refinement", {}) or {}
    features = _feature_list(undercuts)
    checked_count = _safe_int(refinement.get("checked_count", 0))
    confirmed_count = _safe_int(refinement.get("confirmed_count", 0))
    failed_count = _safe_int(refinement.get("failed_count", 0))
    skipped_count = _safe_int(refinement.get("skipped_count", 0))
    reliability = refinement.get("reliability", {}) or {}
    reliability_level = reliability.get("reliability_level")
    proxy_retained = _safe_int(reliability.get("proxy_retained_face_count", 0))
    failure_rows = _boolean_failure_rows(undercuts)
    fallback_rows = _boolean_feature_fallback_rows(features)

    _render_quality_indicators([
        (
            "Boolean reliability",
            reliability.get("reliability_label", "Not reported"),
            _tone_for_boolean_reliability(reliability_level),
        ),
        (
            "Boolean checked",
            checked_count,
            "good" if checked_count else "neutral",
        ),
        (
            "Boolean confirmed",
            confirmed_count,
            "good" if confirmed_count else "neutral",
        ),
        (
            "Boolean failed",
            failed_count,
            _tone_for_count(failed_count, bad_at=1),
        ),
        (
            "Boolean skipped",
            skipped_count,
            _tone_for_count(skipped_count, warning_at=1),
        ),
        (
            "Proxy retained",
            proxy_retained,
            _tone_for_count(proxy_retained, warning_at=1),
        ),
    ])

    if reliability.get("summary"):
        st.caption(reliability["summary"])
    if failed_count:
        st.warning(
            "Swept Boolean refinement could not confirm every candidate face. "
            "The analysis kept those faces as conservative proxy evidence instead of discarding them."
        )
    elif skipped_count:
        st.info(
            "Some faces were skipped by Boolean refinement, usually because they were too small "
            "or not worth spending the Boolean budget on."
        )
    if reliability.get("recommended_action"):
        st.caption(f"Recommended review action: {reliability['recommended_action']}")

    reliability_rows = _boolean_reliability_rows(reliability)
    if failure_rows or fallback_rows or reliability_rows:
        with st.expander(title, expanded=bool(failure_rows)):
            if reliability_rows:
                st.caption("Boolean reliability summary")
                _safe_dataframe(reliability_rows, use_container_width=True)
            if failure_rows:
                st.caption("Face-level Boolean failures")
                _safe_dataframe(failure_rows, use_container_width=True)
            if fallback_rows:
                st.caption("Feature-level fallback evidence")
                _safe_dataframe(fallback_rows, use_container_width=True)


RESULT_KEYS = (
    "summary_result",
    "draft_result",
    "undercut_result",
    "direction_result",
    "parting_line_result",
    "core_cavity_result",
)

STEP_RESULT_KEYS = {
    "Load STEP": "summary_result",
    "Draft": "draft_result",
    "Undercuts": "undercut_result",
    "Direction": "direction_result",
    "Parting Line": "parting_line_result",
    "Core/Cavity": "core_cavity_result",
}

STEP_ORDER = tuple(STEP_RESULT_KEYS)
STEP_FAILURES_KEY = "analysis_step_failures"
STEP_RUNS_KEY = "analysis_step_runs"


def _reset_analysis_state() -> None:
    for key in RESULT_KEYS:
        st.session_state.pop(key, None)
    st.session_state.pop(STEP_FAILURES_KEY, None)
    st.session_state.pop(STEP_RUNS_KEY, None)
    st.session_state.pop("last_backend_error", None)
    st.session_state.pop("cached_display_mesh", None)
    _clear_direction_override()


# ---------------------------------------------------------------------------
# Direction override (roadmap Stage 3 §3.6 — Bosch criterion #2)
#
# Philosophy: the optimizer recommends, the engineer decides. Overriding the
# mold direction recomputes draft/undercuts/parting-line/core-cavity for the
# chosen direction WITHOUT discarding the recommendation — both stay
# available so the engineer can see exactly what the override costs. Only
# geometry extraction is never rerun (both directions use the same loaded
# part). Stored separately from the normal per-step results
# (`draft_result`, `undercut_result`, ...) rather than overwriting them.
# ---------------------------------------------------------------------------
DIRECTION_OVERRIDE_KEY = "direction_override"
OVERRIDE_RESULT_KEY = "override_result"


def _direction_override_state() -> dict[str, Any]:
    return st.session_state.get(
        DIRECTION_OVERRIDE_KEY, {"active": False, "vector": None, "label": ""}
    )


def _set_direction_override(vector: tuple[float, float, float], label: str) -> None:
    st.session_state[DIRECTION_OVERRIDE_KEY] = {
        "active": True,
        "vector": vector,
        "label": label,
    }


def _clear_direction_override() -> None:
    st.session_state[DIRECTION_OVERRIDE_KEY] = {
        "active": False,
        "vector": None,
        "label": "",
    }
    st.session_state.pop(OVERRIDE_RESULT_KEY, None)


def _run_direction_override_pipeline(
    selected_part: str,
    vector: tuple[float, float, float],
    *,
    include_faces: bool,
    include_mesh: bool,
    include_boolean_regions: bool,
    mesh_deflection: float,
    solid_split: bool = False,
    generate_side_core: bool = False,
) -> dict[str, Any]:
    """
    Recompute the full downstream pipeline (draft, undercuts, parting line,
    core/cavity) for a manually overridden direction. Geometry extraction is
    NOT rerun — every fetch here re-parses the STEP file server-side anyway
    (the API is stateless), but conceptually this is "downstream of pull
    direction" recompute only, matching the roadmap's scope for S3.6.
    """
    ox, oy, oz = vector
    draft = _fetch_draft(
        selected_part, dx=ox, dy=oy, dz=oz,
        include_faces=include_faces, include_mesh=include_mesh,
        mesh_deflection=mesh_deflection,
    )
    undercuts = _fetch_undercuts(
        selected_part, dx=ox, dy=oy, dz=oz,
        include_faces=include_faces, include_mesh=include_mesh,
        include_boolean_regions=include_boolean_regions,
        mesh_deflection=mesh_deflection,
    )
    parting_line = _fetch_parting_line(
        selected_part, dx=ox, dy=oy, dz=oz,
        include_faces=include_faces, include_mesh=include_mesh,
        mesh_deflection=mesh_deflection, use_optimal_direction=False,
    )
    core_cavity = _fetch_core_cavity(
        selected_part,
        include_faces=include_faces, include_mesh=include_mesh,
        mesh_deflection=mesh_deflection,
        use_optimal_direction=False, dx=ox, dy=oy, dz=oz,
        solid_split=solid_split,
        generate_side_core=generate_side_core,
    )
    return {
        "draft": draft,
        "undercuts": undercuts,
        "parting_line": parting_line,
        "core_cavity": core_cavity,
    }


_AXIS_OVERRIDE_PRESETS: list[tuple[str, tuple[float, float, float]]] = [
    ("+X", (1.0, 0.0, 0.0)),
    ("-X", (-1.0, 0.0, 0.0)),
    ("+Y", (0.0, 1.0, 0.0)),
    ("-Y", (0.0, -1.0, 0.0)),
    ("+Z", (0.0, 0.0, 1.0)),
    ("-Z", (0.0, 0.0, -1.0)),
]


def _render_direction_override_controls(
    selected_part: str,
    *,
    include_faces: bool,
    include_mesh: bool,
    include_boolean_regions: bool,
    mesh_deflection: float,
    solid_split: bool = False,
    generate_side_core: bool = False,
) -> None:
    """
    Bosch criterion #2. The optimizer recommends; the engineer decides.
    Applying an override recomputes draft/undercuts/parting-line/core-cavity
    for the chosen direction and stores the result separately from the
    recommended pipeline's results — nothing is overwritten or discarded.
    """
    state = _direction_override_state()
    st.markdown("#### Override Mold Direction")
    st.caption(
        "The optimizer recommends the geometrically best direction. Real "
        "constraints — flash, gate location, ejector layout, existing "
        "tooling — often mean the engineer picks a different one. Applying "
        "an override recomputes every downstream analysis for that "
        "direction; the recommendation stays available for comparison below."
    )

    axis_cols = st.columns(6)
    for col, (label, vector) in zip(axis_cols, _AXIS_OVERRIDE_PRESETS):
        if col.button(label, key=f"override_axis_{label}", use_container_width=True):
            with st.spinner(f"Recomputing draft/undercuts/parting-line/core-cavity for {label}..."):
                result = _run_direction_override_pipeline(
                    selected_part, vector,
                    include_faces=include_faces, include_mesh=include_mesh,
                    include_boolean_regions=include_boolean_regions,
                    mesh_deflection=mesh_deflection,
                    solid_split=solid_split,
                    generate_side_core=generate_side_core,
                )
            _set_direction_override(vector, label)
            st.session_state[OVERRIDE_RESULT_KEY] = result
            # The banner/Findings panel are rendered earlier in the script
            # (before this tab's code runs) and would otherwise show stale
            # state for one rerun — force an immediate clean rerun so every
            # render call sees the just-applied override consistently.
            st.rerun()

    with st.expander("Custom vector"):
        cx = st.number_input("Override X", value=0.0, step=0.1, format="%.3f", key="override_cx")
        cy = st.number_input("Override Y", value=0.0, step=0.1, format="%.3f", key="override_cy")
        cz = st.number_input("Override Z", value=1.0, step=0.1, format="%.3f", key="override_cz")
        if st.button("Apply custom vector", key="override_apply_custom"):
            magnitude = (cx * cx + cy * cy + cz * cz) ** 0.5
            if magnitude < 1e-9:
                st.error("The override vector cannot be zero.")
            else:
                vector = (cx / magnitude, cy / magnitude, cz / magnitude)
                label = f"custom ({vector[0]:+.3f}, {vector[1]:+.3f}, {vector[2]:+.3f})"
                with st.spinner("Recomputing draft/undercuts/parting-line/core-cavity for the custom direction..."):
                    result = _run_direction_override_pipeline(
                        selected_part, vector,
                        include_faces=include_faces, include_mesh=include_mesh,
                        include_boolean_regions=include_boolean_regions,
                        mesh_deflection=mesh_deflection,
                        solid_split=solid_split,
                        generate_side_core=generate_side_core,
                    )
                _set_direction_override(vector, label)
                st.session_state[OVERRIDE_RESULT_KEY] = result
                st.rerun()

    if state["active"]:
        st.warning(f"⚠️ Using manual override: **{state['label']}**")
        if st.button("Clear override — use recommended direction", key="override_clear"):
            _clear_direction_override()
            st.rerun()
    else:
        st.success("🎯 Using recommended direction (no override applied).")


def _render_recommended_vs_override(direction: dict[str, Any]) -> None:
    """Side-by-side comparison so the engineer can see what an override costs."""
    state = _direction_override_state()
    override_result = st.session_state.get(OVERRIDE_RESULT_KEY)
    if not state.get("active") or not isinstance(override_result, dict):
        return

    rec_draft = direction.get("optimal_draft", {}) or {}
    rec_undercuts = direction.get("optimal_undercuts", {}) or {}
    rec_parting = st.session_state.get("parting_line_result", {}).get("parting_line", {}) or {}

    ov_draft = (override_result.get("draft") or {}).get("draft", {}) or {}
    ov_undercuts_payload = override_result.get("undercuts") or {}
    ov_undercuts = ov_undercuts_payload.get("undercuts", {}) or {}
    ov_parting_payload = override_result.get("parting_line") or {}
    ov_parting = ov_parting_payload.get("parting_line", {}) or {}
    ov_core_cavity_payload = override_result.get("core_cavity") or {}
    ov_core_cavity = ov_core_cavity_payload.get("core_cavity", {}) or {}

    rec_counts = _undercut_counts(rec_undercuts)
    ov_counts = _undercut_counts(ov_undercuts)

    st.markdown(f"#### Recommended vs Override ({state['label']})")
    rows = [
        {
            "Metric": "Direction",
            "Recommended": _direction_axis_tilt_text(direction.get("best_direction")),
            "Override": _direction_axis_tilt_text(state.get("vector")),
        },
        {
            "Metric": "Draft severity",
            "Recommended": str(rec_draft.get("severity", "unknown")).title(),
            "Override": str(ov_draft.get("severity", "unknown")).title(),
        },
        {
            "Metric": "Bad draft area",
            "Recommended": f"{_draft_bad_area_pct(rec_draft):.2f}%",
            "Override": f"{_draft_bad_area_pct(ov_draft):.2f}%",
        },
        {
            "Metric": "Undercut features",
            "Recommended": rec_counts["total"],
            "Override": ov_counts["total"],
        },
        {
            "Metric": "Major undercuts",
            "Recommended": rec_counts["major"],
            "Override": ov_counts["major"],
        },
        {
            "Metric": "Parting-line readiness",
            "Recommended": str(rec_parting.get("readiness", {}).get("status", "not run")).title(),
            "Override": str(ov_parting.get("readiness", {}).get("status", "not run")).title(),
        },
        {
            "Metric": "Silhouette coverage",
            "Recommended": f"{_safe_float(rec_parting.get('silhouette_coverage_ratio', 0.0)) * 100:.0f}%",
            "Override": f"{_safe_float(ov_parting.get('silhouette_coverage_ratio', 0.0)) * 100:.0f}%",
        },
        {
            "Metric": "Cavity/Core/Parting faces",
            "Recommended": "n/a — see Core/Cavity tab",
            "Override": (
                f"{ov_core_cavity.get('face_counts', {}).get('cavity', 0)}/"
                f"{ov_core_cavity.get('face_counts', {}).get('core', 0)}/"
                f"{ov_core_cavity.get('face_counts', {}).get('parting', 0)}"
                if ov_core_cavity else "not run"
            ),
        },
    ]
    _safe_dataframe(rows, use_container_width=True)


def _render_active_direction_banner() -> None:
    """Always-visible, tab-independent indicator of which direction is active."""
    state = _direction_override_state()
    if state.get("active"):
        st.warning(f"⚠️ Viewing results for a manual direction override: **{state['label']}** (not the optimizer's recommendation).")


def _cache_and_strip_mesh(result: dict[str, Any]) -> None:
    """
    Cache the base mesh geometry once and strip duplicate point/face arrays.

    The first call stores the full display_mesh (points, faces, face_ids,
    face_centers) in st.session_state["cached_display_mesh"].  Every
    subsequent call strips the large geometry arrays from the result's
    display_mesh, leaving only overlay-specific arrays (draft_rgb,
    undercut_classification, etc.).

    This reduces session-state memory from 6 full mesh copies to 1 cached
    copy + 5 small overlay dicts, eliminating the root cause of the
    Tornado WebSocketClosedError flood on macOS.
    """
    display_mesh = result.get("display_mesh")
    if not isinstance(display_mesh, dict):
        return

    if "cached_display_mesh" not in st.session_state:
        # Prime the cache with the geometry from this result.
        st.session_state["cached_display_mesh"] = {
            "points": display_mesh.get("points", []),
            "faces": display_mesh.get("faces", []),
            "face_ids": display_mesh.get("face_ids", []),
            "face_centers": display_mesh.get("face_centers", {}),
            "point_count": display_mesh.get("point_count", 0),
            "triangle_count": display_mesh.get("triangle_count", 0),
            "face_count": display_mesh.get("face_count", 0),
        }
    else:
        # Geometry is already cached — strip the large arrays from this copy.
        stripped = {
            k: v for k, v in display_mesh.items()
            if k not in ("points", "faces", "face_ids")
        }
        result["display_mesh"] = stripped


def _hydrate_mesh(display_mesh: dict[str, Any] | None) -> dict[str, Any]:
    """
    Return a display_mesh dict that is guaranteed to have full geometry.

    If points/faces were stripped during caching, they are restored from
    the cached base mesh.  The step-specific overlay arrays (draft_rgb, etc.)
    are preserved and take precedence over the cached values.

    Safe to call even when no cache exists (returns the input unchanged).
    """
    if not isinstance(display_mesh, dict):
        return {}
    cached = st.session_state.get("cached_display_mesh")
    if cached is None:
        return display_mesh
    # Merge: cached geometry as base, step overlays on top.
    return {**cached, **display_mesh}


def _step_failures() -> dict[str, dict[str, Any]]:
    failures = st.session_state.setdefault(STEP_FAILURES_KEY, {})
    return failures if isinstance(failures, dict) else {}


def _step_runs() -> dict[str, dict[str, Any]]:
    runs = st.session_state.setdefault(STEP_RUNS_KEY, {})
    return runs if isinstance(runs, dict) else {}


def _format_elapsed(elapsed_s: float | None) -> str:
    if elapsed_s is None:
        return "-"
    if elapsed_s < 10.0:
        return f"{elapsed_s:.2f}s"
    return f"{elapsed_s:.1f}s"


def _record_step_run(step_name: str, *, success: bool, elapsed_s: float) -> None:
    runs = _step_runs()
    runs[step_name] = {
        "status": "passed" if success else "failed",
        "elapsed_s": round(elapsed_s, 4),
    }
    st.session_state[STEP_RUNS_KEY] = runs


def _record_backend_error(
    *,
    failure_label: str,
    message: str,
    endpoint: str,
    hint: str | None = None,
    status_code: int | None = None,
    code: str | None = None,
) -> None:
    st.session_state["last_backend_error"] = {
        "failure_label": failure_label,
        "message": message,
        "endpoint": endpoint,
        "recovery_hint": hint,
        "status_code": status_code,
        "code": code,
    }


def _mark_step_success(step_name: str) -> None:
    failures = _step_failures()
    failures.pop(step_name, None)
    st.session_state[STEP_FAILURES_KEY] = failures
    st.session_state.pop("last_backend_error", None)


def _mark_step_failure(step_name: str) -> None:
    last_error = st.session_state.get("last_backend_error", {})
    if not isinstance(last_error, dict):
        last_error = {}
    failures = _step_failures()
    failures[step_name] = {
        "message": last_error.get("message", "Step failed."),
        "recovery_hint": last_error.get("recovery_hint"),
        "endpoint": last_error.get("endpoint"),
        "status_code": last_error.get("status_code"),
        "code": last_error.get("code"),
    }
    st.session_state[STEP_FAILURES_KEY] = failures


def _store_step_result(step_name: str, result_key: str, result: dict[str, Any] | None) -> bool:
    if result is None:
        _mark_step_failure(step_name)
        return False
    # Cache geometry once; strip duplicate points/faces from subsequent steps.
    _cache_and_strip_mesh(result)
    st.session_state[result_key] = result
    _mark_step_success(step_name)
    return True


def _completed_steps() -> dict[str, bool]:
    return {
        step_name: bool(st.session_state.get(result_key))
        for step_name, result_key in STEP_RESULT_KEYS.items()
    }


def _next_step_name() -> str:
    for name, complete in _completed_steps().items():
        if not complete:
            return name
    return "Level 1 complete"


def _journey_prompt() -> str:
    next_step = _next_step_name()
    failure = _step_failures().get(next_step)
    if failure:
        hint = failure.get("recovery_hint") or "Review the failure details, then retry this step."
        return f"{next_step} failed. {hint}"
    if next_step == "Load STEP":
        return "I will first verify the STEP topology and display mesh."
    if next_step == "Draft":
        return "Topology is loaded. Next I will classify draft quality for the selected pull direction."
    if next_step == "Undercuts":
        return "Draft is ready. Next I will find inaccessible faces and Boolean-confirmed undercut regions."
    if next_step == "Direction":
        return "Undercuts are mapped. Next I will compare mold-opening candidates and select the best direction."
    if next_step == "Parting Line":
        return "Best direction is ready. Next I will detect and refine the main parting-line candidate."
    if next_step == "Core/Cavity":
        return "Parting line is ready. Next I will classify cavity, core, and parting faces for Level 1."
    return "Level 1 checks are complete. Review Direction, Parting Line, and Core/Cavity for the mold-opening recommendation."


def _show_backend_error(
    *,
    response: requests.Response,
    failure_label: str,
    endpoint: str,
) -> None:
    try:
        payload = response.json()
    except ValueError:
        st.error(f"{failure_label}: HTTP {response.status_code}")
        _record_backend_error(
            failure_label=failure_label,
            message=f"HTTP {response.status_code}",
            endpoint=endpoint,
            status_code=response.status_code,
        )
        with st.expander("Failure details"):
            st.write(response.text[:1000])
        return

    raw_error = payload.get("error") if isinstance(payload, dict) else None
    raw_detail = payload.get("detail") if isinstance(payload, dict) else None

    if isinstance(raw_error, dict):
        error = raw_error
    elif isinstance(raw_detail, dict):
        error = raw_detail
    else:
        error = {
            "code": "http_error",
            "message": str(raw_detail or raw_error or payload),
            "operation": endpoint,
            "recovery_hint": "Review the selected file, pull direction, and backend logs.",
            "details": {},
        }

    message = error.get("message") or f"HTTP {response.status_code}"
    hint = error.get("recovery_hint")
    _record_backend_error(
        failure_label=failure_label,
        message=message,
        endpoint=endpoint,
        hint=hint,
        status_code=response.status_code,
        code=error.get("code"),
    )
    st.error(f"{failure_label}: {message}")

    if hint:
        st.info(hint)

    with st.expander("Failure details"):
        st.json({
            "status_code": response.status_code,
            "endpoint": endpoint,
            "code": error.get("code"),
            "operation": error.get("operation"),
            "details": error.get("details", {}),
        })


def _backend_get(
    endpoint: str,
    *,
    params: dict[str, Any] | None,
    timeout: int,
    failure_label: str,
) -> dict[str, Any] | None:
    try:
        response = requests.get(
            f"{BACKEND_URL}{endpoint}",
            params=params,
            timeout=timeout,
        )
        if response.status_code >= 400:
            _show_backend_error(
                response=response,
                failure_label=failure_label,
                endpoint=endpoint,
            )
            return None
        return response.json()
    except requests.RequestException as exc:
        _record_backend_error(
            failure_label=failure_label,
            message=str(exc),
            endpoint=endpoint,
            hint="Check that the backend container is running and reachable from the Streamlit container.",
        )
        st.error(f"{failure_label}: {exc}")
        st.info("Check that the backend container is running and reachable from the Streamlit container.")
        return None


def _backend_post(
    endpoint: str,
    *,
    params: dict[str, Any] | None,
    timeout: int,
    failure_label: str,
) -> dict[str, Any] | None:
    try:
        response = requests.post(
            f"{BACKEND_URL}{endpoint}",
            params=params,
            timeout=timeout,
        )
        if response.status_code >= 400:
            _show_backend_error(
                response=response,
                failure_label=failure_label,
                endpoint=endpoint,
            )
            return None
        return response.json()
    except requests.RequestException as exc:
        _record_backend_error(
            failure_label=failure_label,
            message=str(exc),
            endpoint=endpoint,
            hint="Check that the backend container is running and reachable from the Streamlit container.",
        )
        st.error(f"{failure_label}: {exc}")
        st.info("Check that the backend container is running and reachable from the Streamlit container.")
        return None


def _fetch_agent_analysis(
    selected_part: str,
    *,
    query: str | None,
    provider: str | None,
) -> dict[str, Any] | None:
    params: dict[str, Any] = {}
    if query:
        params["query"] = query
    if provider:
        params["provider"] = provider
    return _backend_post(
        f"/parts/{selected_part}/agent/analyze",
        params=params,
        timeout=120,
        failure_label="AI agent DfM analysis failed",
    )


def _fetch_pdf_report(
    selected_part: str,
    *,
    use_optimal_direction: bool,
    dx: float,
    dy: float,
    dz: float,
    include_solid_split: bool,
    include_side_core: bool,
    include_agent_narrative: bool,
) -> bytes | None:
    """
    Unlike every other `_fetch_*` helper, `/export/report` returns raw
    `application/pdf` bytes, not JSON -- so this bypasses `_backend_post`
    (which always calls `.json()`) and handles the response directly.
    """
    endpoint = f"/parts/{selected_part}/export/report"
    params = {
        "use_optimal_direction": use_optimal_direction,
        "dx": dx, "dy": dy, "dz": dz,
        "include_solid_split": include_solid_split,
        "include_side_core": include_side_core,
        "include_agent_narrative": include_agent_narrative,
    }
    try:
        response = requests.post(f"{BACKEND_URL}{endpoint}", params=params, timeout=150)
        if response.status_code >= 400:
            _show_backend_error(response=response, failure_label="PDF report export failed", endpoint=endpoint)
            return None
        return response.content
    except requests.RequestException as exc:
        _record_backend_error(
            failure_label="PDF report export failed",
            message=str(exc),
            endpoint=endpoint,
            hint="Check that the backend container is running and reachable from the Streamlit container.",
        )
        st.error(f"PDF report export failed: {exc}")
        return None


def _fetch_summary(
    selected_part: str,
    *,
    include_faces: bool,
    include_mesh: bool,
    mesh_deflection: float,
) -> dict[str, Any] | None:
    return _backend_get(
        f"/parts/{selected_part}/summary",
        params={
            "include_faces": include_faces,
            "include_mesh": include_mesh,
            "mesh_deflection": mesh_deflection,
        },
        timeout=120,
        failure_label="STEP load failed",
    )


def _mesh_geometry_already_cached() -> bool:
    """
    Roadmap Stage 3 §3.8 (second item): once the base mesh geometry
    (points/faces) has been cached client-side (`_cache_and_strip_mesh`),
    every subsequent analysis fetch for the same part can ask the backend to
    OMIT points/faces from the response entirely (`include_mesh_geometry=
    false`) -- `_hydrate_mesh` reconstructs the full mesh by merging the
    fresh overlay (draft_rgb, etc.) onto the cached geometry either way, so
    nothing downstream needs to change. This is what actually stops
    re-downloading identical geometry over the network on every overlay
    switch; `_cache_and_strip_mesh` alone only ever stopped re-STORING it
    client-side after it had already been transferred.
    """
    return "cached_display_mesh" in st.session_state


def _fetch_draft(
    selected_part: str,
    *,
    dx: float,
    dy: float,
    dz: float,
    include_faces: bool,
    include_mesh: bool,
    mesh_deflection: float,
) -> dict[str, Any] | None:
    return _backend_get(
        f"/parts/{selected_part}/draft",
        params={
            "dx": dx,
            "dy": dy,
            "dz": dz,
            "include_faces": include_faces,
            "include_mesh": include_mesh,
            "include_mesh_geometry": not _mesh_geometry_already_cached(),
            "mesh_deflection": mesh_deflection,
        },
        timeout=180,
        failure_label="Draft analysis failed",
    )


def _fetch_undercuts(
    selected_part: str,
    *,
    dx: float,
    dy: float,
    dz: float,
    include_faces: bool,
    include_mesh: bool,
    include_boolean_regions: bool,
    mesh_deflection: float,
) -> dict[str, Any] | None:
    return _backend_get(
        f"/parts/{selected_part}/undercuts",
        params={
            "dx": dx,
            "dy": dy,
            "dz": dz,
            "include_faces": include_faces,
            "include_mesh": include_mesh,
            "include_mesh_geometry": not _mesh_geometry_already_cached(),
            "include_boolean_regions": include_boolean_regions,
            "mesh_deflection": mesh_deflection,
        },
        timeout=180,
        failure_label="Undercut detection failed",
    )


def _fetch_direction(
    selected_part: str,
    *,
    dx: float,
    dy: float,
    dz: float,
    include_faces: bool,
    include_mesh: bool,
    include_boolean_regions: bool,
    mesh_deflection: float,
) -> dict[str, Any] | None:
    return _backend_get(
        f"/parts/{selected_part}/direction",
        params={
            "dx": dx,
            "dy": dy,
            "dz": dz,
            "include_faces": include_faces,
            "include_mesh": include_mesh,
            "include_mesh_geometry": not _mesh_geometry_already_cached(),
            "include_boolean_regions": include_boolean_regions,
            "mesh_deflection": mesh_deflection,
            # Roadmap Stage 3 §3.7: the default top-10 candidates are all
            # near-duplicates of the best one (an artefact of the fine-search
            # cone) -- genuine diversity clustering needs the full candidate
            # set to find families the top-10 cutoff would otherwise hide.
            "include_all_candidates": True,
        },
        timeout=240,
        failure_label="Direction optimization failed",
    )


def _fetch_core_cavity(
    selected_part: str,
    *,
    include_faces: bool,
    include_mesh: bool,
    mesh_deflection: float,
    solid_split: bool = False,
    generate_side_core: bool = False,
    use_optimal_direction: bool = True,
    dx: float = 0.0,
    dy: float = 0.0,
    dz: float = 1.0,
) -> dict[str, Any] | None:
    return _backend_get(
        f"/parts/{selected_part}/core-cavity",
        params={
            "use_optimal_direction": use_optimal_direction,
            "dx": dx,
            "dy": dy,
            "dz": dz,
            "threshold": 0.05,
            "include_faces": include_faces,
            "include_mesh": include_mesh,
            "include_mesh_geometry": not _mesh_geometry_already_cached(),
            "mesh_deflection": mesh_deflection,
            "solid_split": solid_split,
            "generate_side_core": generate_side_core and solid_split,
        },
        timeout=240,
        failure_label="Core/cavity classification failed",
    )


def _fetch_parting_line(
    selected_part: str,
    *,
    dx: float,
    dy: float,
    dz: float,
    include_faces: bool,
    include_mesh: bool,
    mesh_deflection: float,
    use_optimal_direction: bool = True,
) -> dict[str, Any] | None:
    return _backend_get(
        f"/parts/{selected_part}/parting-line",
        params={
            "dx": dx,
            "dy": dy,
            "dz": dz,
            "use_optimal_direction": use_optimal_direction,
            "include_faces": include_faces,
            "include_mesh": include_mesh,
            "include_mesh_geometry": not _mesh_geometry_already_cached(),
            "include_direction": False,
            "refine": True,
            "mesh_deflection": mesh_deflection,
        },
        timeout=260,
        failure_label="Parting-line detection failed",
    )


def _render_journey_status() -> None:
    completed = _completed_steps()
    failures = _step_failures()
    runs = _step_runs()
    chips: list[str] = []
    for name, complete in completed.items():
        elapsed = _format_elapsed(runs.get(name, {}).get("elapsed_s"))
        label = f"{name} {elapsed}" if name in runs else name
        if name in failures and not complete:
            chips.append(_status_chip(label, state="failed", color="#f04438"))
        elif complete:
            chips.append(_status_chip(label, state="complete", color="#12b76a"))
        elif name == _next_step_name():
            chips.append(_status_chip(label, state="current", color="#2e90fa"))
        else:
            chips.append(_status_chip(label, state="muted", color="#98a2b3"))
    _render_chip_row(chips)


def _render_step_timings() -> None:
    runs = _step_runs()
    if not runs:
        return
    rows = []
    for step_name in STEP_ORDER:
        run = runs.get(step_name)
        if not run:
            continue
        rows.append({
            "Step": step_name,
            "Status": run.get("status", "unknown"),
            "Elapsed": _format_elapsed(float(run.get("elapsed_s", 0.0))),
        })
    if rows:
        with st.expander("Run timings"):
            _safe_dataframe(rows, use_container_width=True)


def _render_step_failures() -> None:
    failures = _step_failures()
    active_failures = {
        step: failure
        for step, failure in failures.items()
        if not st.session_state.get(STEP_RESULT_KEYS.get(step, ""))
    }
    if not active_failures:
        return
    with st.expander("Failed step diagnostics", expanded=True):
        for step_name, failure in active_failures.items():
            st.warning(f"{step_name}: {failure.get('message', 'Step failed.')}")
            if failure.get("recovery_hint"):
                st.info(failure["recovery_hint"])
            st.json({
                "endpoint": failure.get("endpoint"),
                "status_code": failure.get("status_code"),
                "code": failure.get("code"),
            })


def _render_level1_snapshot() -> None:
    summary = st.session_state.get("summary_result")
    draft = st.session_state.get("draft_result", {}).get("draft")
    undercuts = st.session_state.get("undercut_result", {}).get("undercuts")
    direction = st.session_state.get("direction_result", {}).get("direction")
    failures = _step_failures()

    tiles: list[tuple[str, object, object]] = []
    if summary:
        tiles.append((
            "Topology",
            f"{summary.get('face_count', 0)} faces",
            f"{summary.get('solid_count', 0)} solids | {summary.get('edge_count', 0)} edges",
        ))
    elif "Load STEP" in failures:
        tiles.append(("Topology", "Failed", failures["Load STEP"].get("message", "Retry step")))
    else:
        tiles.append(("Topology", "Pending", selected_part))

    if draft:
        tiles.append((
            "Draft",
            str(draft.get("severity", "unknown")).title(),
            f"{draft.get('percentages', {}).get('bad_pct', 0)}% bad area",
        ))
    elif "Draft" in failures:
        tiles.append(("Draft", "Failed", failures["Draft"].get("message", "Retry step")))
    else:
        tiles.append(("Draft", "Pending", "Selected pull vector"))

    if undercuts:
        undercut_counts = _undercut_counts(undercuts)
        face_count = _safe_int(undercuts.get("face_counts", {}).get("undercut", 0))
        tiles.append((
            "Undercut Features",
            _format_undercut_count(undercut_counts["total"]),
            f"{face_count} faces | {_format_undercut_evidence(undercut_counts)}",
        ))
    elif "Undercuts" in failures:
        tiles.append(("Undercuts", "Failed", failures["Undercuts"].get("message", "Retry step")))
    else:
        tiles.append(("Undercuts", "Pending", "Boolean regions optional"))

    if direction:
        best = direction.get("best_direction", [0.0, 0.0, 0.0])
        tiles.append((
            "Best Direction",
            direction.get("best_label", "Pending"),
            f"({best[0]:+.2f}, {best[1]:+.2f}, {best[2]:+.2f})",
        ))
    elif "Direction" in failures:
        tiles.append(("Best Direction", "Failed", failures["Direction"].get("message", "Retry step")))
    else:
        tiles.append(("Best Direction", "Pending", "Candidate search"))

    parting = st.session_state.get("parting_line_result", {}).get("parting_line")
    if parting:
        refinement = parting.get("refinement", {})
        readiness = parting.get("readiness", {})
        tiles.append((
            "Parting Line",
            str(readiness.get("status", f"{parting.get('edge_counts', {}).get('selected', 0)} edges")).title(),
            f"{refinement.get('quality', 'unknown')} | score {readiness.get('score', 0)}",
        ))
    elif "Parting Line" in failures:
        tiles.append(("Parting Line", "Failed", failures["Parting Line"].get("message", "Retry step")))
    else:
        tiles.append(("Parting Line", "Pending", "Split candidate"))

    core_cavity = st.session_state.get("core_cavity_result", {}).get("core_cavity")
    if core_cavity:
        tiles.append((
            "Core/Cavity",
            f"{core_cavity.get('face_counts', {}).get('cavity', 0)} cavity",
            (
                f"{core_cavity.get('percentages', {}).get('cavity_pct', 0)}% cavity | "
                f"{core_cavity.get('percentages', {}).get('core_pct', 0)}% core"
            ),
        ))
    elif "Core/Cavity" in failures:
        tiles.append(("Core/Cavity", "Failed", failures["Core/Cavity"].get("message", "Retry step")))
    else:
        tiles.append(("Core/Cavity", "Pending", "Face classification"))

    _render_summary_grid(tiles)


def _render_direction_before_after_from_state(*, compact: bool = True) -> None:
    direction = st.session_state.get("direction_result", {}).get("direction")
    if not isinstance(direction, dict):
        return
    initial_undercuts = st.session_state.get("undercut_result", {}).get("undercuts")
    initial_undercuts = _initial_undercuts_for_direction(direction, initial_undercuts)
    optimal_undercuts = (
        direction.get("optimal_undercuts")
        or direction.get("undercuts_optimal_direction")
    )
    _render_before_after_story(
        direction,
        initial_undercuts,
        optimal_undercuts,
        compact=compact,
    )


def _level1_result_rows(
    *,
    draft: dict[str, Any],
    initial_undercuts: dict[str, Any],
    optimal_undercuts: dict[str, Any],
    direction: dict[str, Any],
    parting: dict[str, Any],
) -> list[dict[str, Any]]:
    best = direction.get("best_direction", [0.0, 0.0, 0.0])
    readiness = parting.get("readiness", {})
    gate = parting.get("diagnostic_gate", {})
    conflict = parting.get("undercut_conflict", {})
    initial_counts = _undercut_counts(initial_undercuts)
    optimal_counts = _undercut_counts(optimal_undercuts)
    mold_action_result, mold_action_evidence, mold_action_status = _mold_action_result(initial_counts)
    conflict_level = str(conflict.get("conflict_level", "unknown"))
    conflict_evidence = f"score {conflict.get('conflict_score', 0)}"
    conflict_status = "OK" if conflict_level in {"none", "not_checked"} else "Review"
    if conflict_level == "none" and initial_counts["major"]:
        conflict_evidence = "optimal context clear; initial major feature exists"
        conflict_status = "Review"
    return [
        {
            "Decision Area": "Mold opening",
            "Result": direction.get("best_label", "unknown"),
            "Evidence": f"Vector ({best[0]:+.3f}, {best[1]:+.3f}, {best[2]:+.3f})",
            "Status": "Computed",
        },
        {
            "Decision Area": "Draft",
            "Result": str(draft.get("severity", "unknown")).title(),
            "Evidence": f"{draft.get('percentages', {}).get('bad_pct', 0)}% bad area",
            "Status": "Review" if draft.get("severity") not in {"none", "minor"} else "OK",
        },
        {
            "Decision Area": "Detected undercuts",
            "Result": _format_undercut_count(initial_counts["total"]),
            "Evidence": _format_undercut_evidence(initial_counts),
            "Status": "Review" if initial_counts["total"] else "OK",
        },
        {
            "Decision Area": "Mold action",
            "Result": mold_action_result,
            "Evidence": mold_action_evidence,
            "Status": mold_action_status,
        },
        {
            "Decision Area": "Residual undercuts",
            "Result": _format_undercut_count(optimal_counts["total"]),
            "Evidence": "after best direction",
            "Status": "Review" if optimal_counts["total"] else "OK",
        },
        {
            "Decision Area": "Parting line",
            "Result": str(readiness.get("status", "unknown")).title(),
            "Evidence": f"score {readiness.get('score', 0)}",
            "Status": "Ready" if readiness.get("status") == "ready" else "Review",
        },
        {
            "Decision Area": "Downstream use",
            "Result": "Report-ready" if gate.get("can_use_for_report") else "Not report-ready",
            "Evidence": f"core/cavity block: {gate.get('blocks_core_cavity', False)}",
            "Status": "OK" if gate.get("can_use_for_report") else "Blocked",
        },
        {
            "Decision Area": "Undercut conflict",
            "Result": conflict_level.title(),
            "Evidence": conflict_evidence,
            "Status": conflict_status,
        },
    ]


# ---------------------------------------------------------------------------
# Issue-first summary (roadmap Stage 3 §3.1/§3.4) — three-layer progressive
# disclosure. Layer 1 (verdict, default view) is the ranked issue list built
# here; Layer 2 (evidence) is each issue's "Show evidence" expander; Layer 3
# (provenance/debug) is the existing per-step tabs and their raw-JSON
# expanders further down the page, unchanged. This is also deliberate
# groundwork for Stage 5 (the agent will consume exactly these
# severity/location/reason/recommendation/evidence records).
# ---------------------------------------------------------------------------
_ISSUE_SEVERITY_ORDER = {"critical": 0, "review": 1, "info": 2, "ok": 3}
_ISSUE_SEVERITY_STYLE = {
    "critical": ("🔴", "Critical"),
    "review": ("🟡", "Review"),
    "info": ("ℹ️", "Info"),
    "ok": ("🟢", "OK"),
}
_ISSUE_DEFAULT_VISIBLE = 5


def _collect_issues() -> list[dict[str, Any]]:
    """
    Scan every pipeline stage's result in session_state and return ranked
    {severity, location, title, detail, evidence} issue records — the
    plain-language "what's wrong, why, how serious, what to do" answers a
    mold engineer actually asks for, in that order (roadmap §3.4).
    """
    issues: list[dict[str, Any]] = []

    # Bosch criterion #2 (S3.6): when a direction override is active, the
    # engineer's chosen direction — not the optimizer's recommendation —
    # drives these findings ("the engineering report reflects the chosen
    # direction"). The recommendation itself is never discarded; it stays
    # available via the Recommended-vs-Override comparison in the Direction
    # tab. Every issue built while an override is active gets its location
    # suffixed "(override)" below, so this is never ambiguous.
    override_state = _direction_override_state()
    override_active = bool(override_state.get("active"))
    override_result = st.session_state.get(OVERRIDE_RESULT_KEY) if override_active else None

    direction = st.session_state.get("direction_result", {}).get("direction")
    if override_active and isinstance(override_result, dict):
        draft = (override_result.get("draft") or {}).get("draft")
    else:
        draft = (
            (direction or {}).get("optimal_draft")
            or st.session_state.get("draft_result", {}).get("draft")
        )
    if isinstance(draft, dict):
        # Real vocabulary from draft_analyzer.py: "none" | "minor" | "moderate"
        # | "critical" — matches _tone_for_draft_severity's mapping, not the
        # "bad"/"marginal"/"good" guess this used to check against.
        severity = _normalised_token(draft.get("severity"))
        bad_pct = _draft_bad_area_pct(draft)
        bad_faces = _draft_bad_faces(draft)
        if severity == "critical":
            issues.append({
                "severity": "critical",
                "location": "Draft",
                "title": "Draft correction required",
                "detail": (
                    f"{bad_pct:.1f}% of surface area ({bad_faces} faces) has "
                    "insufficient or negative draft along the mold-opening "
                    "direction — the part will stick in the mold."
                ),
                "evidence": f"Bad draft area: {bad_pct:.2f}% · Bad faces: {bad_faces}",
            })
        elif severity == "moderate":
            issues.append({
                "severity": "review",
                "location": "Draft",
                "title": "Moderate draft issues on some faces",
                "detail": (
                    f"{bad_pct:.1f}% of surface area ({bad_faces} faces) is "
                    "below the recommended draft angle."
                ),
                "evidence": f"Bad draft area: {bad_pct:.2f}% · Faces: {bad_faces}",
            })
        elif severity == "minor":
            issues.append({
                "severity": "info",
                "location": "Draft",
                "title": "Minor draft issues on a few faces",
                "detail": (
                    f"{bad_pct:.1f}% of surface area ({bad_faces} face(s)) is "
                    "slightly below the recommended draft angle."
                ),
                "evidence": f"Bad draft area: {bad_pct:.2f}% · Faces: {bad_faces}",
            })
        elif severity == "none":
            issues.append({
                "severity": "ok",
                "location": "Draft",
                "title": "Draft acceptable",
                "detail": "All analysed faces meet the minimum draft angle.",
                "evidence": f"Bad draft area: {bad_pct:.2f}%",
            })

    # The `/direction` endpoint's optimal_undercuts is a SUMMARY (counts and
    # percentages) with no per-feature "features" list — only the standalone
    # /undercuts endpoint (undercut_result) returns full feature detail. Use
    # whichever is available for per-feature detail, but always judge the
    # residual-risk verdict against the actual chosen (optimal) direction's
    # summary when one exists, not the initial direction's.
    if override_active and isinstance(override_result, dict):
        override_undercuts = (override_result.get("undercuts") or {}).get("undercuts")
        optimal_undercuts = override_undercuts
        detailed_undercuts = (
            override_undercuts
            if isinstance(override_undercuts, dict) and _feature_list(override_undercuts)
            else None
        )
    else:
        optimal_undercuts = (direction or {}).get("optimal_undercuts")
        detailed_undercuts = (
            st.session_state.get("undercut_result", {}).get("undercuts")
            if isinstance(st.session_state.get("undercut_result", {}).get("undercuts"), dict)
            and _feature_list(st.session_state.get("undercut_result", {}).get("undercuts"))
            else None
        )
    if isinstance(optimal_undercuts, dict) and optimal_undercuts:
        major_count = _safe_int(optimal_undercuts.get("major_undercut_features_count", 0))
        has_critical = bool(optimal_undercuts.get("has_critical_undercut", False))
        feature_count = _safe_int(optimal_undercuts.get("feature_count", 0))
        highest = _highest_severity_feature(detailed_undercuts) if detailed_undercuts else None
        if has_critical or major_count > 0:
            depth_text = ""
            if highest:
                depth = _safe_float(highest.get("depth_proxy_mm", 0.0))
                faces = highest.get("face_count", len(highest.get("face_ids", []) or []))
                depth_text = f" (deepest known: {depth:.1f} mm on {faces} face(s), from the initial-direction scan)"
            issues.append({
                "severity": "critical" if has_critical else "review",
                "location": "Undercuts (optimal direction)",
                "title": (
                    "Critical undercut remains at the optimal direction"
                    if has_critical
                    else f"{major_count} major undercut feature(s) remain at the optimal direction"
                ),
                "detail": f"The chosen mold-opening direction still has residual undercut risk{depth_text}.",
                "evidence": (
                    f"feature_count={feature_count} · major={major_count} · "
                    f"has_critical_undercut={has_critical}"
                ),
            })
        elif feature_count == 0:
            issues.append({
                "severity": "ok",
                "location": "Undercuts",
                "title": "No undercuts at the optimal direction",
                "detail": "The chosen mold-opening direction is fully undercut-free by feature count.",
                "evidence": "feature_count=0",
            })
        else:
            issues.append({
                "severity": "info",
                "location": "Undercuts",
                "title": f"{feature_count} minor undercut feature(s) remain",
                "detail": "None are flagged critical or major, but worth a quick look.",
                "evidence": f"feature_count={feature_count} · major=0 · has_critical_undercut=False",
            })
    elif detailed_undercuts:
        highest = _highest_severity_feature(detailed_undercuts)
        counts = _undercut_counts(detailed_undercuts)
        if highest:
            feature_severity = _normalised_token(highest.get("severity"))
            action = _normalised_token(highest.get("recommended_mold_action"))
            depth = _safe_float(highest.get("depth_proxy_mm", 0.0))
            volume = _safe_float(highest.get("interference_volume_mm3", 0.0))
            faces = highest.get("face_count", len(highest.get("face_ids", []) or []))
            if action == "side-action" or feature_severity in ("critical", "high"):
                issues.append({
                    "severity": "critical" if feature_severity == "critical" else "review",
                    "location": f"Undercut feature {highest.get('feature_id')}",
                    "title": (
                        "Side action required"
                        if action == "side-action"
                        else f"{highest.get('severity', 'High').title()} undercut needs review"
                    ),
                    "detail": (
                        f"A {depth:.1f} mm deep undercut on {faces} face(s) cannot "
                        "release along the mold opening direction."
                        if action == "side-action"
                        else f"A {depth:.1f} mm deep undercut on {faces} face(s) is "
                        "flagged for manual mold-action review."
                    ),
                    "evidence": (
                        f"Depth (proxy): {depth:.2f} mm · Interference volume: "
                        f"{volume:,.0f} mm³ · Faces: {faces} · Major features: "
                        f"{counts['major']} · Critical: {counts['critical']}"
                    ),
                })
            elif counts["major"] == 0:
                issues.append({
                    "severity": "ok",
                    "location": "Undercuts",
                    "title": "No major undercuts detected",
                    "detail": "No undercut feature requires a side action or critical review.",
                    "evidence": f"Total undercut features: {counts['total']}",
                })

    if override_active and isinstance(override_result, dict):
        parting = (override_result.get("parting_line") or {}).get("parting_line")
    else:
        parting = st.session_state.get("parting_line_result", {}).get("parting_line")
    if isinstance(parting, dict):
        readiness = parting.get("readiness", {}) or {}
        refinement = parting.get("refinement", {}) or {}
        graph_cleanup = refinement.get("graph_cleanup", {}) or {}
        readiness_status = _normalised_token(readiness.get("status"))
        coverage_ratio = _safe_float(parting.get("silhouette_coverage_ratio", 0.0))
        closure_guaranteed = bool(parting.get("closure_guaranteed", False))
        component_count = len(parting.get("components", []) or [])

        if not closure_guaranteed:
            issues.append({
                "severity": "critical",
                "location": "Parting line",
                "title": "Parting loop is not guaranteed closed",
                "detail": (
                    f"Measured gap: {_safe_float(parting.get('closure_error_mm', 0.0)):.4f} mm. "
                    "Downstream core/cavity split cannot be trusted until this closes."
                ),
                "evidence": f"closure_error_mm={parting.get('closure_error_mm', 0.0)}",
            })
        elif readiness_status in ("weak", "failed"):
            issues.append({
                "severity": "critical" if readiness_status == "failed" else "review",
                "location": "Parting line",
                "title": readiness.get("label") or f"Parting-line readiness: {readiness_status}",
                "detail": "; ".join(readiness.get("blockers") or readiness.get("reasons") or [
                    "The selected parting-line candidate needs manual review before use."
                ]),
                "evidence": f"readiness_score={readiness.get('score', 0.0)}",
            })
        elif coverage_ratio and coverage_ratio < 0.35:
            issues.append({
                "severity": "review",
                "location": "Parting line",
                "title": f"Parting line covers only {coverage_ratio * 100:.0f}% of the part outline",
                "detail": (
                    f"Expected ≥ 35%. The part's silhouette is split across "
                    f"{component_count} separate edge groups, so the tool could "
                    "not assemble one dominant loop."
                ),
                "evidence": f"silhouette_coverage_ratio={coverage_ratio:.4f}",
            })
        else:
            issues.append({
                "severity": "ok",
                "location": "Parting line",
                "title": "Parting-line candidate ready",
                "detail": readiness.get("label", "Readiness and coverage checks passed."),
                "evidence": f"coverage={coverage_ratio * 100:.0f}% · readiness={readiness_status}",
            })

        if _normalised_token(graph_cleanup.get("strategy")) == "greedy-fallback":
            issues.append({
                "severity": "review",
                "location": "Parting line — wire search",
                "title": "Exact path search fell back to greedy",
                "detail": (
                    "The wire-ordering search exceeded its exact/contracted search "
                    "budget and used a non-backtracking greedy heuristic instead — "
                    "the selected wire is not guaranteed to be the best available."
                ),
                "evidence": (
                    f"graph_cleanup.strategy=greedy-fallback · "
                    f"input_edge_count={graph_cleanup.get('input_edge_count', 'n/a')}"
                ),
            })

    if override_active and isinstance(override_result, dict):
        core_cavity_split = (override_result.get("core_cavity") or {}).get("solid_split")
    else:
        core_cavity_split = st.session_state.get("core_cavity_result", {}).get("solid_split")
    if isinstance(core_cavity_split, dict):
        split_status = core_cavity_split.get("solid_split_status")
        if split_status == "split_ok":
            if core_cavity_split.get("split_tool_kind") == "planar_approximation":
                issues.append({
                    "severity": "info",
                    "location": "Core/cavity split",
                    "title": "Solid split uses a planar approximation",
                    "detail": (
                        "The exported cavity/core solids were bisected with a flat "
                        "plane through the parting loop's centroid, not the exact "
                        "3-D parting surface shown above — see split_tool_kind."
                    ),
                    "evidence": (
                        f"cavity={core_cavity_split.get('cavity_solid_volume_mm3', 0):.1f} mm³ · "
                        f"core={core_cavity_split.get('core_solid_volume_mm3', 0):.1f} mm³"
                    ),
                })
        elif split_status not in (None, "not_attempted", "blocked_by_parting_line"):
            issues.append({
                "severity": "review",
                "location": "Core/cavity split",
                "title": f"Solid split status: {split_status}",
                "detail": core_cavity_split.get("failure_reason") or "The Boolean split did not succeed.",
                "evidence": f"split_solid_count={core_cavity_split.get('split_solid_count', 0)}",
            })

    if override_active and isinstance(override_result, dict):
        side_core_result = (override_result.get("core_cavity") or {}).get("side_core")
    else:
        side_core_result = st.session_state.get("core_cavity_result", {}).get("side_core")
    if isinstance(side_core_result, dict):
        sc_status = side_core_result.get("status")
        if sc_status == "generated":
            issues.append({
                "severity": "info",
                "location": "Side core (Stage 4)",
                "title": (
                    f"Side core generated — {side_core_result.get('containing_half', '?')} "
                    "half reduced"
                ),
                "detail": (
                    "First increment only (one feature, no lifter/slide/"
                    "collapsible-core classification) — see roadmap Stage 4 §4.3."
                ),
                "evidence": (
                    f"side_core_volume={side_core_result.get('side_core_volume_mm3', 0):.1f} mm³ · "
                    f"conservation_error="
                    f"{side_core_result.get('conservation_error', 0) * 100:.4f}%"
                ),
            })
        elif sc_status not in (None, "no_feature", "not_attempted", "blocked_by_core_cavity_split"):
            issues.append({
                "severity": "review",
                "location": "Side core (Stage 4)",
                "title": f"Side core status: {sc_status}",
                "detail": side_core_result.get("failure_reason") or "Side-core generation did not succeed.",
                "evidence": (
                    f"containing_half={side_core_result.get('containing_half', 'n/a')}"
                ),
            })

    if override_active:
        for issue in issues:
            issue["location"] = f"{issue['location']} (override)"

    issues.sort(key=lambda issue: _ISSUE_SEVERITY_ORDER.get(issue["severity"], 9))
    return issues


def _render_issue_summary() -> None:
    """Layer 1 verdict view: ranked issues, ≤5 by default, rest collapsed."""
    issues = _collect_issues()
    if not issues:
        return

    st.subheader("Findings")
    visible, hidden = issues[:_ISSUE_DEFAULT_VISIBLE], issues[_ISSUE_DEFAULT_VISIBLE:]

    def _render_issue(issue: dict[str, Any]) -> None:
        icon, label = _ISSUE_SEVERITY_STYLE.get(issue["severity"], ("⚪", "Unknown"))
        st.markdown(f"**{icon} {label} — {issue['location']}: {issue['title']}**")
        st.write(issue["detail"])
        with st.expander("Show evidence"):
            st.write(issue["evidence"])

    for issue in visible:
        _render_issue(issue)

    if hidden:
        with st.expander(f"Show {len(hidden)} more finding(s)"):
            for issue in hidden:
                _render_issue(issue)


def _render_level1_result_summary() -> None:
    draft = st.session_state.get("draft_result", {}).get("draft")
    direction = st.session_state.get("direction_result", {}).get("direction")
    initial_undercuts = st.session_state.get("undercut_result", {}).get("undercuts")
    if initial_undercuts is None and isinstance(direction, dict):
        initial_undercuts = (
            direction.get("initial_undercuts")
            or direction.get("undercuts_initial_direction")
        )
    optimal_undercuts = direction.get("optimal_undercuts") if isinstance(direction, dict) else None
    if initial_undercuts is None:
        initial_undercuts = optimal_undercuts
    if optimal_undercuts is None:
        optimal_undercuts = initial_undercuts
    parting = st.session_state.get("parting_line_result", {}).get("parting_line")

    if not (draft and initial_undercuts and optimal_undercuts and direction and parting):
        return

    best = direction.get("best_direction", [0.0, 0.0, 0.0])
    readiness = parting.get("readiness", {})
    gate = parting.get("diagnostic_gate", {})
    conflict = parting.get("undercut_conflict", {})
    optimal_draft = direction.get("optimal_draft", {})
    display_draft = optimal_draft or draft
    initial_counts = _undercut_counts(initial_undercuts)
    optimal_counts = _undercut_counts(optimal_undercuts)
    mold_action_result, mold_action_evidence, mold_action_status = _mold_action_result(initial_counts)

    st.subheader("Level 1 Result")
    _render_quality_indicators([
        ("Mold direction", direction.get("best_label", "unknown"), "info"),
        (
            "Draft",
            str(display_draft.get("severity", "unknown")).title(),
            _tone_for_draft_severity(display_draft.get("severity")),
        ),
        (
            "Detected undercuts",
            initial_counts["total"],
            _tone_for_undercut_counts(initial_counts),
        ),
        (
            "Major undercuts",
            initial_counts["major"],
            _tone_for_undercut_counts(initial_counts),
        ),
        (
            "Mold action",
            mold_action_status,
            "warning" if mold_action_status == "Review" else "good",
        ),
        (
            "Residual undercuts",
            optimal_counts["total"],
            _tone_for_undercut_counts(optimal_counts),
        ),
        (
            "Parting",
            str(readiness.get("status", "unknown")).title(),
            _tone_for_quality_level(readiness.get("status")),
        ),
        (
            "Conflict",
            str(conflict.get("conflict_level", "unknown")).title(),
            _tone_for_conflict(conflict.get("conflict_level")),
        ),
    ])
    _render_summary_grid([
        (
            "Best Direction",
            direction.get("best_label", "unknown"),
            f"({best[0]:+.3f}, {best[1]:+.3f}, {best[2]:+.3f})",
        ),
        (
            "Optimal Draft",
            str(display_draft.get("severity", "unknown")).title(),
            f"{display_draft.get('percentages', {}).get('bad_pct', 0)}% bad area",
        ),
        (
            "Detected Undercut Features",
            _format_undercut_count(initial_counts["total"]),
            _format_undercut_evidence(initial_counts),
        ),
        (
            "Mold Action",
            mold_action_result,
            mold_action_evidence,
        ),
        (
            "Residual Undercuts",
            _format_undercut_count(optimal_counts["total"]),
            "after best direction",
        ),
        (
            "Parting Line",
            str(readiness.get("status", "unknown")).title(),
            f"score {readiness.get('score', 0)}",
        ),
        (
            "Report Use",
            "Yes" if gate.get("can_use_for_report") else "No",
            gate.get("summary", ""),
        ),
        (
            "Core/Cavity Gate",
            "Blocked" if gate.get("blocks_core_cavity") else "Open",
            "Level 2 dependency",
        ),
    ])
    _safe_dataframe(
        _level1_result_rows(
            draft=display_draft,
            initial_undercuts=initial_undercuts,
            optimal_undercuts=optimal_undercuts,
            direction=direction,
            parting=parting,
        ),
        use_container_width=True,
    )


def _render_dfm_summary_report(selected_part: str) -> None:
    summary = st.session_state.get("summary_result")
    draft_result = st.session_state.get("draft_result", {})
    undercut_result = st.session_state.get("undercut_result", {})
    direction_result = st.session_state.get("direction_result", {})
    parting_result = st.session_state.get("parting_line_result", {})
    core_cavity_result = st.session_state.get("core_cavity_result", {})

    if not (summary and draft_result and undercut_result and direction_result):
        return

    draft = draft_result.get("draft", {})
    undercuts = undercut_result.get("undercuts", {})
    direction = direction_result.get("direction", {})
    parting = parting_result.get("parting_line", {}) if parting_result else {}
    core_cavity = core_cavity_result.get("core_cavity", {}) if core_cavity_result else {}
    optimal_draft = direction.get("optimal_draft", draft)
    initial_draft = direction.get("initial_draft", draft)
    initial_undercuts = undercuts
    optimal_undercuts = direction.get("optimal_undercuts", undercuts)
    bbox = summary.get("bounding_box", {}) or {}
    today = time.strftime("%Y-%m-%d")

    with st.expander("📋 Full DfM Summary Report", expanded=True):
        st.markdown(f"## DfM Analysis Report — {selected_part}")
        st.write(f"**Analysis Date:** {today}")
        st.write("**Analysis Level:** Level 1")

        st.markdown("### Part Geometry")
        st.write(
            f"- File: {selected_part}\n"
            f"- Faces: {summary.get('face_count', 0)} | "
            f"Edges: {summary.get('edge_count', 0)} | "
            f"Solids: {summary.get('solid_count', 0)}\n"
            f"- Bounding box (mm): "
            f"X {bbox.get('x_mm', bbox.get('dx', '—'))}, "
            f"Y {bbox.get('y_mm', bbox.get('dy', '—'))}, "
            f"Z {bbox.get('z_mm', bbox.get('dz', '—'))}\n"
            f"- Surface types: {summary.get('surface_type_counts', {})}"
        )

        st.markdown("### Draft Analysis Results")
        st.write(
            f"- Initial pull: {direction.get('initial_label', '+Z')}\n"
            f"- Optimal pull: {_direction_label_display(direction)}\n"
            f"- Good/Marginal/Bad faces: "
            f"{optimal_draft.get('face_counts', {}).get('good', 0)}/"
            f"{optimal_draft.get('face_counts', {}).get('marginal', 0)}/"
            f"{optimal_draft.get('face_counts', {}).get('bad', 0)}\n"
            f"- Bad area %: {optimal_draft.get('percentages', {}).get('bad_pct', 0)}%\n"
            f"- Severity: {optimal_draft.get('severity', 'unknown')}"
        )
        suggestions = (optimal_draft.get("suggestions") or draft.get("suggestions") or [])[:3]
        if suggestions:
            st.write("**Top suggestions:**")
            for suggestion in suggestions:
                st.write(f"- {suggestion.get('action_text', suggestion)}")

        st.markdown("### Undercut Detection Results")
        st.write(f"- Undercut features: {undercuts.get('feature_count', 0)}")
        for feature in _feature_list(undercuts):
            if not feature.get("is_major_feature"):
                continue
            st.write(
                f"- Feature {feature.get('feature_id')}: "
                f"{feature.get('severity')} | {feature.get('undercut_type')} | "
                f"{feature.get('recommended_mold_action')} | "
                f"depth {feature.get('depth_proxy_mm')} mm | "
                f"volume {feature.get('interference_volume_mm3')} mm³"
            )

        st.markdown("### Mold Direction Optimization")
        before_bad = _safe_float(initial_draft.get("percentages", {}).get("bad_pct", 0.0))
        after_bad = _safe_float(optimal_draft.get("percentages", {}).get("bad_pct", 0.0))
        improvement = before_bad - after_bad
        st.write(
            f"- Initial bad draft %: {before_bad:.2f}%\n"
            f"- Optimal bad draft %: {after_bad:.2f}%\n"
            f"- Improvement: {improvement:.2f}%\n"
            f"- Boolean-refined candidates: {direction.get('boolean_refined_candidate_count', 0)}"
        )

        st.markdown("### Parting Line")
        readiness = parting.get("readiness", {}) if parting else {}
        refinement = parting.get("refinement", {}) if parting else {}
        st.write(
            f"- Readiness: {readiness.get('status', 'not run')}\n"
            f"- Selected edges: {parting.get('edge_counts', {}).get('selected', 0) if parting else 0}\n"
            f"- Wire quality: {refinement.get('quality', 'unknown')}"
        )

        st.markdown("### Core/Cavity Split (Level 1)")
        if core_cavity:
            st.write(
                f"- Cavity faces: {core_cavity.get('face_counts', {}).get('cavity', 0)} "
                f"({core_cavity.get('percentages', {}).get('cavity_pct', 0)}%)\n"
                f"- Core faces: {core_cavity.get('face_counts', {}).get('core', 0)} "
                f"({core_cavity.get('percentages', {}).get('core_pct', 0)}%)\n"
                f"- Pull direction: {_direction_axis_tilt_text(core_cavity.get('pull_direction'))}"
            )
        else:
            st.write("- Core/cavity classification not run yet.")

        st.markdown("### Limitations (Honest)")
        st.write(
            "> Current limitations: Parting line is a candidate-level silhouette detection "
            "(final production optimization planned). Core/cavity is face classification "
            "only — full Boolean solid split is Level 2. LangChain AI agent and automated "
            "PDF export are planned for Level 2. Boolean refinement is selective (top "
            "undercut candidates only)."
        )

        st.markdown("### Action Items")
        action_suggestions = draft.get("suggestions", []) or optimal_draft.get("suggestions", []) or []
        if action_suggestions:
            for index, suggestion in enumerate(action_suggestions, start=1):
                st.write(f"ACTION {index}: {suggestion.get('action_text', suggestion)}")
        else:
            st.write("No draft correction actions required.")


st.title("DfM Agent")

st.caption("Bosch RB-CoC Plastics | STEP-native injection molding DfM")


left, center = st.columns([0.28, 0.72])

with left:
    st.subheader("Part")
    try:
        health = requests.get(f"{BACKEND_URL}/health", timeout=5)
        health.raise_for_status()
        st.success("Backend connected")
    except requests.RequestException as exc:
        st.error(f"Backend unavailable: {exc}")
        st.info("Start the backend service, then refresh this app.")
        st.stop()

    try:
        parts_response = requests.get(f"{BACKEND_URL}/parts", timeout=10)
        parts_response.raise_for_status()
        parts_payload = parts_response.json()
        parts = parts_payload.get("files", [])
    except requests.RequestException as exc:
        st.error(f"Could not list STEP files: {exc}")
        st.info("Confirm the backend can read the data/parts directory.")
        st.stop()

    for warning in parts_payload.get("warnings", []):
        st.warning(warning)

    if not parts:
        st.info("Place a .stp file in data/parts.")
        st.stop()

    selected_part = st.selectbox("STEP file", parts, index=0)
    include_faces = st.checkbox("Include face table", value=False)
    include_mesh = st.checkbox("Build display mesh", value=True)
    include_boolean_regions = st.checkbox("Boolean volumes", value=True)
    important_undercuts_only = st.checkbox(
        "Show only high-confidence undercuts (Boolean-confirmed)",
        value=True,
        help="Default demo view: mute proxy fallback faces so confirmed interference stays readable.",
    )
    show_proxy_undercut_faces = st.checkbox(
        "Show proxy fallback faces",
        value=False,
        help="Turn this on for audit/debug views. It can make large fallback features visually noisy.",
    )
    show_refined_parting_line = st.checkbox("Refined parting curve", value=True)
    show_raw_parting_line = st.checkbox("Raw parting wire", value=True)
    run_solid_split = st.checkbox(
        "Boolean solid split (Level 2)",
        value=False,
        help=(
            "Runs the real cavity/core Boolean split (Stage 2). Uses a "
            "planar-approximation splitting tool, not the exact 3-D parting "
            "surface shown elsewhere — see split_tool_kind. Slower than "
            "Level 1 face classification alone."
        ),
    )
    run_side_core = st.checkbox(
        "Side core / lifter (Stage 4)",
        value=False,
        disabled=not run_solid_split,
        help=(
            "Bosch criterion #5, first increment: generates ONE side-core "
            "solid for the single highest-confidence critical undercut "
            "feature at the current pull direction, and subtracts it from "
            "whichever mold half contains it. Requires Boolean solid split "
            "above. The optimal pull direction is chosen to avoid undercuts, "
            "so this will usually report 'no_feature' there — try a manual "
            "pull direction below to see it act on a real feature."
        ),
    )
    region_opacity = 0.55
    show_region_edges = True
    if include_boolean_regions:
        region_opacity = st.slider("Volume opacity", 0.2, 0.85, 0.55, 0.05)
        show_region_edges = st.checkbox("Volume edges", value=True)
    mesh_deflection = st.slider("Mesh quality", 0.1, 2.0, 0.5, 0.1)

    st.subheader("Pull Direction")
    dx = st.number_input("X", value=0.0, step=0.1, format="%.3f")
    dy = st.number_input("Y", value=0.0, step=0.1, format="%.3f")
    dz = st.number_input("Z", value=1.0, step=0.1, format="%.3f")

    analysis_signature = {
        "selected_part": selected_part,
        "include_mesh": include_mesh,
        "include_boolean_regions": include_boolean_regions,
        "mesh_deflection": mesh_deflection,
        "pull_direction": (dx, dy, dz),
    }
    if st.session_state.get("analysis_signature") != analysis_signature:
        _reset_analysis_state()
        st.session_state["analysis_signature"] = analysis_signature

    st.subheader("AI Mold Engineer")
    st.caption(_journey_prompt())
    run_next_step = st.button("Run Next Step", type="primary", use_container_width=True)
    run_full_flow = st.button("Run Full Level 1 Flow", use_container_width=True)
    reset_journey = st.button("Reset Journey", use_container_width=True)

    st.subheader("Manual Checks")
    run_summary = st.button("Load STEP", use_container_width=True)
    run_draft = st.button("Run Draft", use_container_width=True)
    run_undercuts = st.button("Detect Undercuts", use_container_width=True)
    run_direction = st.button("Find Best Direction", use_container_width=True)
    run_parting_line = st.button("Detect Parting Line", use_container_width=True)
    run_core_cavity = st.button("Classify Core/Cavity", use_container_width=True)

    st.subheader("PDF Report (Stage 6)")
    st.caption(
        "Presentation layer only -- every number in the PDF traces to a "
        "field already computed by an analysis endpoint below. Generating "
        "the PDF re-runs the pipeline server-side; it does not reuse "
        "results from the tabs above."
    )
    report_include_solid_split = st.checkbox("Include Boolean solid split", value=True, key="report_solid_split")
    report_include_side_core = st.checkbox(
        "Include side core (Stage 4)", value=False, key="report_side_core",
        disabled=not report_include_solid_split,
    )
    report_include_agent = st.checkbox(
        "Include AI agent narrative (Stage 5)", value=False, key="report_agent",
        help="Runs a real LLM call via the configured provider -- adds latency and API cost.",
    )
    if st.button("Generate PDF Report", key="generate_pdf_report", use_container_width=True):
        _override_state = _direction_override_state()
        if _override_state["active"] and _override_state["vector"]:
            _report_use_optimal = False
            _rdx, _rdy, _rdz = _override_state["vector"]
        else:
            _report_use_optimal = True
            _rdx, _rdy, _rdz = dx, dy, dz
        with st.spinner("Building PDF report -- re-running the full analysis pipeline..."):
            pdf_bytes = _fetch_pdf_report(
                selected_part,
                use_optimal_direction=_report_use_optimal,
                dx=_rdx, dy=_rdy, dz=_rdz,
                include_solid_split=report_include_solid_split,
                include_side_core=report_include_side_core,
                include_agent_narrative=report_include_agent,
            )
        st.session_state["pdf_report_bytes"] = pdf_bytes

    pdf_report_bytes = st.session_state.get("pdf_report_bytes")
    if pdf_report_bytes:
        st.download_button(
            "Download PDF Report",
            data=pdf_report_bytes,
            file_name=f"{selected_part.replace('.stp', '').replace('.step', '')}_dfm_report.pdf",
            mime="application/pdf",
            use_container_width=True,
        )


if reset_journey:
    _reset_analysis_state()


def _run_summary_step() -> bool:
    result = _fetch_summary(
        selected_part,
        include_faces=include_faces,
        include_mesh=include_mesh,
        mesh_deflection=mesh_deflection,
    )
    return _store_step_result("Load STEP", "summary_result", result)


def _run_draft_step() -> bool:
    result = _fetch_draft(
        selected_part,
        dx=dx,
        dy=dy,
        dz=dz,
        include_faces=include_faces,
        include_mesh=include_mesh,
        mesh_deflection=mesh_deflection,
    )
    return _store_step_result("Draft", "draft_result", result)


def _run_undercut_step() -> bool:
    result = _fetch_undercuts(
        selected_part,
        dx=dx,
        dy=dy,
        dz=dz,
        include_faces=include_faces,
        include_mesh=include_mesh,
        include_boolean_regions=include_boolean_regions,
        mesh_deflection=mesh_deflection,
    )
    return _store_step_result("Undercuts", "undercut_result", result)


def _run_direction_step() -> bool:
    result = _fetch_direction(
        selected_part,
        dx=dx,
        dy=dy,
        dz=dz,
        include_faces=include_faces,
        include_mesh=include_mesh,
        include_boolean_regions=include_boolean_regions,
        mesh_deflection=mesh_deflection,
    )
    return _store_step_result("Direction", "direction_result", result)


def _run_parting_line_step() -> bool:
    result = _fetch_parting_line(
        selected_part,
        dx=dx,
        dy=dy,
        dz=dz,
        include_faces=include_faces,
        include_mesh=include_mesh,
        mesh_deflection=mesh_deflection,
    )
    return _store_step_result("Parting Line", "parting_line_result", result)


def _run_core_cavity_step() -> bool:
    result = _fetch_core_cavity(
        selected_part,
        include_faces=include_faces,
        include_mesh=include_mesh,
        mesh_deflection=mesh_deflection,
        solid_split=run_solid_split,
        generate_side_core=run_side_core,
    )
    return _store_step_result("Core/Cavity", "core_cavity_result", result)


def _run_named_step(step_name: str) -> bool:
    runners = {
        "Load STEP": _run_summary_step,
        "Draft": _run_draft_step,
        "Undercuts": _run_undercut_step,
        "Direction": _run_direction_step,
        "Parting Line": _run_parting_line_step,
        "Core/Cavity": _run_core_cavity_step,
    }
    runner = runners.get(step_name)
    if runner is None:
        st.success("Level 1 flow is already complete.")
        return True

    start_s = time.perf_counter()
    try:
        success = bool(runner())
    except Exception as exc:  # noqa: BLE001 - frontend should show diagnostics, not crash.
        _record_backend_error(
            failure_label=f"{step_name} failed",
            message=str(exc) or exc.__class__.__name__,
            endpoint="frontend",
            hint="Review the frontend traceback and retry the step.",
            code="frontend_step_error",
        )
        _mark_step_failure(step_name)
        st.error(f"{step_name} failed: {exc}")
        success = False
    _record_step_run(
        step_name,
        success=success,
        elapsed_s=time.perf_counter() - start_s,
    )
    return success


def _run_step_sequence(step_names: list[str]) -> bool:
    if not step_names:
        st.success("Level 1 flow is already complete.")
        return True

    progress = st.progress(0.0)
    status_box = st.empty()
    total = len(step_names)
    for index, step_name in enumerate(step_names, start=1):
        status_box.info(f"Running {step_name} ({index}/{total})")
        success = _run_named_step(step_name)
        progress.progress(index / total)
        if not success:
            status_box.error(f"{step_name} failed. Review diagnostics before continuing.")
            return False
    status_box.success("Level 1 flow complete.")
    return True


if run_summary:
    with st.spinner("Loading STEP topology..."):
        _run_named_step("Load STEP")
if run_draft:
    with st.spinner("Running draft analysis..."):
        _run_named_step("Draft")
if run_undercuts:
    with st.spinner("Detecting undercuts..."):
        _run_named_step("Undercuts")
if run_direction:
    with st.spinner("Optimizing mold direction..."):
        _run_named_step("Direction")
if run_parting_line:
    with st.spinner("Detecting parting line..."):
        _run_named_step("Parting Line")
if run_core_cavity:
    with st.spinner("Classifying core/cavity faces..."):
        _run_named_step("Core/Cavity")

if run_next_step:
    next_step = _next_step_name()
    with st.spinner(f"Running {next_step}..."):
        _run_named_step(next_step)

if run_full_flow:
    with st.spinner("Running Level 1 flow..."):
        _run_step_sequence(list(STEP_ORDER))

with center:
    st.subheader("AI Mold Engineer Journey")
    st.caption(_journey_prompt())
    _render_journey_status()
    _render_active_direction_banner()
    _render_metric_glossary()
    _render_issue_summary()
    _render_step_timings()
    _render_step_failures()
    _render_level1_snapshot()
    _render_direction_before_after_from_state(compact=True)
    _render_level1_result_summary()

    raw_tab, draft_tab, undercut_tab, direction_tab, parting_tab, parting_v2_tab, core_cavity_tab, agent_tab = st.tabs([
        "Raw",
        "Draft",
        "Undercuts",
        "Direction",
        "Parting Line",
        "Parting Line v2 (experimental)",
        "Core/Cavity",
        "AI Agent",
    ])

    with raw_tab:
        st.subheader("Raw Geometry")
        summary = st.session_state.get("summary_result")
        if summary is None:
            st.info("Select a STEP file and load it to inspect exact B-Rep topology.")
        else:
            _render_summary_grid([
                ("Solids", summary.get("solid_count", 0), "Loaded B-Rep bodies"),
                ("Faces", summary.get("face_count", 0), "Analysis surfaces"),
                ("Edges", summary.get("edge_count", 0), "Topology graph"),
                ("Vertices", summary.get("vertex_count", 0), "Model points"),
            ])

            st.json({
                "bounding_box": summary.get("bounding_box"),
                "surface_type_counts": summary.get("surface_type_counts"),
                "edge_type_counts": summary.get("edge_type_counts"),
                "adjacency_stats": summary.get("adjacency_stats"),
                "warnings": summary.get("warnings"),
            })

            if include_mesh and "display_mesh" in summary:
                st.subheader("Display Mesh")
                _mesh_payload = _hydrate_mesh(summary.get("display_mesh"))
                shown = _show_mesh(
                    _mesh_payload,
                    color_key="draft_rgb",
                    viewer_key=f"raw-{selected_part}",
                )
                if not shown:
                    st.json({
                        "display_mesh": {
                            "point_count": _mesh_payload.get("point_count"),
                            "triangle_count": _mesh_payload.get("triangle_count"),
                        }
                    })

            if include_faces and "faces" in summary:
                st.subheader("Faces")
                _safe_dataframe(summary["faces"], use_container_width=True)

    with draft_tab:
        st.subheader("Draft Analysis")
        result = st.session_state.get("draft_result")
        if result is None:
            st.info("Run draft analysis to view classifications.")
        else:
            _draft_legend()
            draft = result["draft"]
            face_counts = draft["face_counts"]
            percentages = draft["percentages"]
            _render_quality_indicators([
                (
                    "Draft risk",
                    str(draft.get("severity", "unknown")).title(),
                    _tone_for_draft_severity(draft.get("severity")),
                ),
                (
                    "Bad area",
                    f"{percentages.get('bad_pct', 0)}%",
                    _tone_for_count(face_counts.get("bad", 0), bad_at=5),
                ),
                (
                    "Suggestions",
                    len(draft.get("suggestions", []) or []),
                    _tone_for_count(len(draft.get("suggestions", []) or []), bad_at=5),
                ),
            ])

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Good", face_counts["good"], f"{percentages['good_pct']}% area")
            c2.metric("Marginal", face_counts["marginal"], f"{percentages['marginal_pct']}% area")
            c3.metric("Bad", face_counts["bad"], f"{percentages['bad_pct']}% area")
            c4.metric("Severity", draft["severity"].title())

            if include_mesh and "display_mesh" in result:
                _mesh_payload = _hydrate_mesh(result.get("display_mesh"))
                shown = _show_mesh(
                    _mesh_payload,
                    color_key="draft_rgb",
                    viewer_key=f"draft-{selected_part}",
                )
                if not shown:
                    st.json({
                        "display_mesh": {
                            "point_count": _mesh_payload.get("point_count"),
                            "triangle_count": _mesh_payload.get("triangle_count"),
                        }
                    })

            if draft["suggestions"]:
                st.subheader("Suggestions")
                for suggestion in draft["suggestions"]:
                    st.write(suggestion["action_text"])

            with st.expander("Draft JSON"):
                st.json(draft)

            if include_faces:
                st.subheader("Faces")
                _safe_dataframe(result["part"].get("faces", []), use_container_width=True)

    with undercut_tab:
        st.subheader("Undercut Detection")
        result = st.session_state.get("undercut_result")
        if result is None:
            st.info("Run undercut detection to view likely inaccessible features.")
        else:
            _undercut_legend(important_only=important_undercuts_only)
            undercuts = result["undercuts"]
            high_confidence_only = st.toggle(
                "Show only high-confidence undercuts (Boolean-confirmed)",
                value=important_undercuts_only,
                help="When enabled, proxy-only faces are muted in the 3D overlay.",
            )
            features = undercuts.get("features", []) or []
            critical_features = sum(
                1 for feature in features
                if str(feature.get("severity", "")).lower() == "critical"
            )
            moderate_features = sum(
                1 for feature in features
                if str(feature.get("severity", "")).lower() == "moderate"
            )
            high_confidence_actions = sum(
                1 for feature in features
                if str(feature.get("action_confidence_label", "")).lower() == "high"
            )
            boolean_refinement = undercuts.get("boolean_refinement", {}) or {}
            boolean_enabled = bool(boolean_refinement.get("enabled", False))
            _render_quality_indicators([
                (
                    "Undercut state",
                    "Clear" if not features else f"{len(features)} feature(s)",
                    "good" if not features else "warning",
                ),
                (
                    "Critical",
                    critical_features,
                    _tone_for_count(critical_features, bad_at=1),
                ),
                (
                    "Moderate",
                    moderate_features,
                    _tone_for_count(moderate_features, warning_at=1),
                ),
                (
                    "Boolean refine",
                    "Yes" if boolean_enabled else "No",
                    "good" if boolean_enabled else "neutral",
                ),
                (
                    "High-confidence actions",
                    high_confidence_actions,
                    "good" if high_confidence_actions else "neutral",
                ),
            ])
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Undercut Faces", undercuts["face_counts"]["undercut"])
            c2.metric("Undercut Features", undercuts["feature_count"])
            c3.metric("Undercut Area", f"{undercuts['percentages']['undercut_area_pct']}%")
            c4.metric("Parting Faces", undercuts["face_counts"]["parting"])
            st.caption(undercuts["method"])
            _render_prominent_undercut_callout(undercuts)
            _render_major_undercut_callout(undercuts)
            _render_boolean_refinement_visibility(
                undercuts,
                title="Default-direction Boolean diagnostics",
            )

            boolean_regions = result.get("boolean_region_meshes", {})
            region_meshes = boolean_regions.get("regions", [])
            if include_boolean_regions:
                _show_boolean_region_status(boolean_regions, "Boolean Regions")
                _show_boolean_region_legend(boolean_regions)

            if include_mesh and "display_mesh" in result:
                if high_confidence_only and not show_proxy_undercut_faces:
                    st.caption(
                        "3D overlay is in confirmed-evidence mode: Boolean-confirmed faces are emphasized; "
                        "proxy fallback faces remain in the tables and diagnostics."
                    )
                display_mesh = _filtered_undercut_mesh_payload(
                    _hydrate_mesh(result.get("display_mesh")),
                    important_only=high_confidence_only,
                    show_proxy_faces=show_proxy_undercut_faces,
                )
                face_overlay = _undercut_face_overlay_region(
                    display_mesh,
                    label="Undercut face evidence overlay",
                )
                viewer_regions = []
                if face_overlay is not None:
                    viewer_regions.append(face_overlay)
                if include_boolean_regions:
                    viewer_regions.extend(region_meshes)
                major_overlay = _major_feature_overlay_region(
                    display_mesh,
                    undercuts,
                    label="Major undercut feature overlay",
                    include_proxy_faces=show_proxy_undercut_faces,
                )
                if major_overlay is not None:
                    viewer_regions.append(major_overlay)
                _render_undercut_visual_summary(display_mesh)
                shown = _show_mesh(
                    display_mesh,
                    color_key="neutral_base_rgb",
                    region_meshes=viewer_regions,
                    region_opacity=region_opacity,
                    show_region_edges=show_region_edges,
                    viewer_key=(
                        f"undercuts-{selected_part}-{len(viewer_regions)}-"
                        f"{region_opacity:.2f}-{show_region_edges}-"
                        f"important-{high_confidence_only}-proxy-{show_proxy_undercut_faces}"
                    ),
                )
                if not shown:
                    st.json({
                        "display_mesh": {
                            "point_count": display_mesh.get("point_count"),
                            "triangle_count": display_mesh.get("triangle_count"),
                        }
                    })
                    if include_boolean_regions:
                        st.json({
                            "boolean_region_meshes": {
                                "region_count": boolean_regions.get("region_count", 0),
                                "warnings": boolean_regions.get("warnings", []),
                            }
                        })

            if undercuts["features"]:
                _render_feature_outcome_chips(undercuts["features"])
                st.subheader("Mold Action Rationale")
                _safe_dataframe(
                    _action_recommendation_rows(undercuts["features"]),
                    use_container_width=True,
                )
                st.subheader("Recognized Features")
                _safe_dataframe(undercuts["features"], use_container_width=True)

            with st.expander("Undercut JSON"):
                st.json(undercuts)

    with direction_tab:
        st.subheader("Best Mold Direction")
        result = st.session_state.get("direction_result")
        if result is None:
            st.info("Run direction optimization to compare the selected initial pull vector against the best candidate.")
        else:
            direction = result["direction"]
            best = direction["best_direction"]
            optimal = direction["optimal_draft"]
            undercuts = direction["optimal_undercuts"]
            initial = direction["initial_draft"]
            st.markdown(
                f"### 🎯 Best Mold Opening Direction: {direction.get('best_label', 'unknown')}\n"
                f"**Vector:** `{_direction_axis_tilt_text(best)}`  \n"
                f"**Score:** `{direction.get('best_score', 0):.4f}`"
            )
            initial_undercut_result = st.session_state.get("undercut_result", {})
            initial_undercuts = (
                initial_undercut_result.get("undercuts")
                if isinstance(initial_undercut_result, dict)
                else None
            )
            if initial_undercuts is None:
                initial_undercuts = (
                    direction.get("initial_undercuts")
                    or direction.get("undercuts_initial_direction")
                )
            initial_counts = _undercut_counts(initial_undercuts)
            optimal_counts = _undercut_counts(undercuts)
            _render_quality_indicators([
                ("Best", direction.get("best_label", "unknown"), "info"),
                (
                    "Optimal draft",
                    str(optimal.get("severity", "unknown")).title(),
                    _tone_for_draft_severity(optimal.get("severity")),
                ),
                (
                    "Boolean candidates",
                    direction.get("boolean_refined_candidate_count", 0),
                    "good" if direction.get("boolean_refined_candidate_count", 0) else "neutral",
                ),
                (
                    "Optimal undercuts",
                    optimal_counts["total"],
                    _tone_for_undercut_counts(optimal_counts),
                ),
                (
                    "Initial major",
                    initial_counts["major"],
                    _tone_for_undercut_counts(initial_counts),
                ),
            ])
            st.write(
                f"Best candidate: `{direction['best_label']}` "
                f"= ({best[0]:+.3f}, {best[1]:+.3f}, {best[2]:+.3f})"
            )
            st.caption(direction["method"])
            before_col, after_col = st.columns(2)
            with before_col:
                st.markdown("#### Before (Default +Z Direction)")
                st.metric("Bad Draft Area", f"{initial['percentages']['bad_pct']}%")
                st.metric("Undercut Features", initial_counts["total"])
                st.metric("Severity", str(initial.get("severity", "unknown")).title())
            with after_col:
                st.markdown("#### After (Optimal Direction Found)")
                st.metric("Bad Draft Area", f"{optimal['percentages']['bad_pct']}%")
                st.metric("Undercut Features", optimal_counts["total"])
                st.metric("Severity", str(optimal.get("severity", "unknown")).title())
                bad_delta = _safe_float(optimal["percentages"]["bad_pct"]) - _safe_float(initial["percentages"]["bad_pct"])
                feature_delta = optimal_counts["total"] - initial_counts["total"]
                st.markdown(
                    f"**Improvement:** bad draft `{bad_delta:+.2f}%`, "
                    f"undercut features `{feature_delta:+d}`"
                )
            _render_before_after_story(
                direction,
                initial_undercuts,
                undercuts,
                compact=False,
            )
            if initial_counts["major"] and not optimal_counts["total"]:
                st.info(
                    "Best-direction residual undercuts are clear. "
                    "Switch the overlay to Initial Detected Undercuts to review the original major feature."
                )

            initial = direction["initial_draft"]

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Initial Bad", initial["face_counts"]["bad"], f"{initial['percentages']['bad_pct']}% area")
            c2.metric("Optimal Bad", optimal["face_counts"]["bad"], f"{optimal['percentages']['bad_pct']}% area")
            c3.metric("Candidates", direction["candidate_count"])
            c4.metric("Score", direction["best_score"])

            u1, u2, u3 = st.columns(3)
            u1.metric("Optimal Undercut Faces", undercuts["face_counts"]["undercut"])
            u2.metric("Optimal Undercut Features", undercuts["feature_count"])
            u3.metric("Optimal Undercut Area", f"{undercuts['percentages']['undercut_area_pct']}%")
            if initial_undercuts:
                _render_major_undercut_callout(
                    initial_undercuts,
                    title="Initial Major Undercuts For Before/After Review",
                )
            _render_boolean_refinement_visibility(
                undercuts,
                title="Optimal-direction Boolean diagnostics",
            )

            boolean_regions = result.get("boolean_region_meshes", {})
            region_meshes = boolean_regions.get("regions", [])
            if include_boolean_regions:
                _show_boolean_region_status(boolean_regions, "Optimal Boolean Regions")
                _show_boolean_region_legend(boolean_regions)

            if include_mesh and "display_mesh" in result:
                overlay_options = [
                    "Optimal Draft",
                    "Optimal Residual Undercuts",
                    "Initial Detected Undercuts",
                ]
                overlay_mode = st.radio(
                    "Direction overlay",
                    overlay_options,
                    horizontal=True,
                    key="direction_overlay_mode",
                )
                display_mesh = _hydrate_mesh(result.get("display_mesh"))
                color_key = "draft_rgb"
                viewer_regions = None
                viewer_suffix = "optimal-draft"
                if overlay_mode == "Optimal Residual Undercuts":
                    _undercut_legend(important_only=important_undercuts_only)
                    optimal_counts = _undercut_counts(undercuts)
                    if optimal_counts["total"] <= 0:
                        st.success(
                            "No residual undercut evidence is visible for the optimized pull direction."
                        )
                    elif important_undercuts_only and not show_proxy_undercut_faces:
                        st.caption(
                            "Showing Boolean-confirmed residual undercut faces first; "
                            "proxy fallback faces are muted unless enabled in the sidebar."
                        )
                    display_mesh = _filtered_undercut_mesh_payload(
                        display_mesh,
                        important_only=important_undercuts_only,
                        show_proxy_faces=show_proxy_undercut_faces,
                    )
                    face_overlay = _undercut_face_overlay_region(
                        display_mesh,
                        label="Optimal residual undercut face overlay",
                    )
                    viewer_regions = []
                    if face_overlay is not None:
                        viewer_regions.append(face_overlay)
                    if include_boolean_regions:
                        viewer_regions.extend(region_meshes)
                    major_overlay = _major_feature_overlay_region(
                        display_mesh,
                        undercuts,
                        label="Optimal major undercut feature overlay",
                        include_proxy_faces=show_proxy_undercut_faces,
                    )
                    if major_overlay is not None:
                        viewer_regions.append(major_overlay)
                    color_key = "neutral_base_rgb"
                    _render_undercut_visual_summary(display_mesh)
                    viewer_suffix = "optimal-undercuts"
                elif overlay_mode == "Initial Detected Undercuts":
                    initial_mesh = (
                        _hydrate_mesh(initial_undercut_result.get("display_mesh"))
                        if isinstance(initial_undercut_result, dict)
                        else None
                    )
                    if initial_mesh:
                        _undercut_legend(important_only=important_undercuts_only)
                        st.info(
                            "This overlay shows the before-state undercuts from the initial pull direction. "
                            "Use it to compare against the optimized residual undercut view."
                        )
                        display_mesh = _filtered_undercut_mesh_payload(
                            initial_mesh,
                            important_only=important_undercuts_only,
                            show_proxy_faces=show_proxy_undercut_faces,
                        )
                        color_key = "neutral_base_rgb"
                        initial_regions_payload = initial_undercut_result.get("boolean_region_meshes", {})
                        face_overlay = _undercut_face_overlay_region(
                            display_mesh,
                            label="Initial undercut face evidence overlay",
                        )
                        viewer_regions = []
                        if face_overlay is not None:
                            viewer_regions.append(face_overlay)
                        if include_boolean_regions:
                            viewer_regions.extend(initial_regions_payload.get("regions", []))
                        major_overlay = _major_feature_overlay_region(
                            display_mesh,
                            initial_undercuts or {},
                            label="Initial major undercut feature overlay",
                            include_proxy_faces=show_proxy_undercut_faces,
                        )
                        if major_overlay is not None:
                            viewer_regions.append(major_overlay)
                        _render_undercut_visual_summary(display_mesh)
                        viewer_suffix = "initial-undercuts"
                    else:
                        st.warning(
                            "Run Detect Undercuts first to show the initial undercut overlay."
                        )
                else:
                    _draft_legend()

                shown = _show_mesh(
                    display_mesh,
                    color_key=color_key,
                    region_meshes=viewer_regions,
                    region_opacity=region_opacity,
                    show_region_edges=show_region_edges,
                    viewer_key=(
                        f"direction-{selected_part}-{viewer_suffix}-"
                        f"{len(viewer_regions or [])}-{region_opacity:.2f}-"
                        f"{show_region_edges}-important-{important_undercuts_only}-"
                        f"proxy-{show_proxy_undercut_faces}"
                    ),
                )
                if not shown:
                    st.json({
                        "display_mesh": {
                            "point_count": display_mesh.get("point_count"),
                            "triangle_count": display_mesh.get("triangle_count"),
                        }
                    })
                    if include_boolean_regions:
                        st.json({
                            "boolean_region_meshes": {
                                "region_count": boolean_regions.get("region_count", 0),
                                "warnings": boolean_regions.get("warnings", []),
                            }
                        })

            _render_candidate_diversity(direction)

            with st.expander("Top Candidates (raw, all scored)"):
                _safe_dataframe(direction["candidates"], use_container_width=True)

            if optimal["suggestions"]:
                st.subheader("Suggestions For Best Direction")
                for suggestion in optimal["suggestions"]:
                    st.write(suggestion["action_text"])

            if undercuts["features"]:
                _render_feature_outcome_chips(undercuts["features"])
                st.subheader("Optimal Mold Action Rationale")
                _safe_dataframe(
                    _action_recommendation_rows(undercuts["features"]),
                    use_container_width=True,
                )

            with st.expander("Direction JSON"):
                st.json(direction)

            st.divider()
            _render_direction_override_controls(
                selected_part,
                include_faces=include_faces,
                include_mesh=include_mesh,
                include_boolean_regions=include_boolean_regions,
                mesh_deflection=mesh_deflection,
                solid_split=run_solid_split,
                generate_side_core=run_side_core,
            )
            _render_recommended_vs_override(direction)

    with parting_tab:
        st.subheader("Main Parting Line")
        result = st.session_state.get("parting_line_result")
        if result is None:
            st.info("Run parting-line detection after direction optimization to view the selected split candidate.")
        else:
            parting = result["parting_line"]
            refinement = parting.get("refinement", {})
            selection_quality = parting.get("selection_quality", {})
            undercut_conflict = parting.get("undercut_conflict", {})
            selected_wire_conflict = parting.get("selected_wire_undercut_conflict", {})
            readiness = parting.get("readiness", {})
            diagnostic_gate = parting.get("diagnostic_gate", result.get("analysis_quality", {}))
            diagnostics = parting.get("diagnostics", {})
            paths = result.get("parting_line_paths", {})
            initial_undercut_result = st.session_state.get("undercut_result", {})
            initial_undercuts = (
                initial_undercut_result.get("undercuts")
                if isinstance(initial_undercut_result, dict)
                else None
            )
            if initial_undercuts is None:
                direction_payload = st.session_state.get("direction_result", {}).get("direction", {})
                if isinstance(direction_payload, dict):
                    initial_undercuts = (
                        direction_payload.get("initial_undercuts")
                        or direction_payload.get("undercuts_initial_direction")
                    )
            initial_counts = _undercut_counts(initial_undercuts)
            graph_cleanup_strategy = str(
                refinement.get("graph_cleanup", {}).get("strategy", "unknown")
            )
            coverage_ratio = _safe_float(parting.get("silhouette_coverage_ratio", 0.0))
            # These two chips are the flagship fix from roadmap Stage 3 §3.3:
            # graph_cleanup.strategy was previously visible only inside a
            # conditionally-collapsed "Graph Cleanup Evidence" expander below
            # — exposing this alone would have caught Bug B immediately.
            _render_quality_indicators([
                (
                    "Readiness",
                    str(readiness.get("status", "unknown")).title(),
                    _tone_for_quality_level(readiness.get("status")),
                    "readiness",
                ),
                (
                    "Search strategy",
                    graph_cleanup_strategy,
                    "bad" if graph_cleanup_strategy == "greedy-fallback" else "good",
                    "graph_cleanup_strategy",
                ),
                (
                    "Silhouette coverage",
                    f"{coverage_ratio * 100:.0f}%",
                    "good" if coverage_ratio >= 0.35 else "warning",
                    "silhouette_coverage_ratio",
                ),
                (
                    "Report use",
                    "Yes" if diagnostic_gate.get("can_use_for_report") else "No",
                    "good" if diagnostic_gate.get("can_use_for_report") else "bad",
                ),
                (
                    "Manual review",
                    "Yes" if diagnostic_gate.get("requires_manual_review") else "No",
                    "warning" if diagnostic_gate.get("requires_manual_review") else "good",
                ),
                (
                    "Curve quality",
                    str(selection_quality.get("level", "unknown")).title(),
                    _tone_for_quality_level(selection_quality.get("level")),
                ),
                (
                    "Undercut conflict",
                    str(undercut_conflict.get("conflict_level", "unknown")).title(),
                    _tone_for_conflict(undercut_conflict.get("conflict_level")),
                ),
                (
                    "Raw wire conflict",
                    str(selected_wire_conflict.get("conflict_level", "unknown")).title(),
                    _tone_for_conflict(selected_wire_conflict.get("conflict_level")),
                ),
                (
                    "Initial major",
                    initial_counts["major"],
                    _tone_for_undercut_counts(initial_counts),
                ),
            ])
            legend = paths.get("legend", {})
            legend_items = []
            for key in ("refined", "raw"):
                item = legend.get(key)
                if item:
                    is_visible = (
                        (key == "refined" and show_refined_parting_line)
                        or (key == "raw" and show_raw_parting_line)
                    )
                    label_suffix = "shown" if is_visible else "hidden"
                    legend_items.append((
                        f"{item.get('label', key.title())} ({label_suffix})",
                        item.get("hex", "#00b8ff"),
                    ))
            if legend_items:
                _render_color_legend(legend_items)

            readiness_status = str(readiness.get("status", "unknown"))
            if readiness_status == "ready":
                st.success(readiness.get("label", "Parting-line candidate ready for review."))
            elif readiness_status == "review":
                st.info(readiness.get("label", "Parting-line candidate needs review."))
            elif readiness_status == "weak":
                st.warning(readiness.get("label", "Weak parting-line candidate."))
            elif readiness_status == "failed":
                st.error(readiness.get("label", "No reliable parting-line candidate."))

            gate_summary = diagnostic_gate.get("summary")
            gate_severity = str(diagnostic_gate.get("severity", "info"))
            if gate_summary:
                if gate_severity == "success":
                    st.success(gate_summary)
                elif gate_severity == "warning":
                    st.warning(gate_summary)
                elif gate_severity == "error":
                    st.error(gate_summary)
                else:
                    st.info(gate_summary)

            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Readiness", readiness_status)
            c2.metric("Selected Edges", parting.get("edge_counts", {}).get("selected", 0))
            c3.metric("Refined Points", refinement.get("refined_point_count", 0))
            c4.metric("Quality", selection_quality.get("level", "unknown"))
            c5.metric("Undercut Conflict", undercut_conflict.get("conflict_level", "unknown"))
            g1, g2, g3 = st.columns(3)
            g1.metric(
                "Report Use",
                "Yes" if diagnostic_gate.get("can_use_for_report") else "No",
            )
            g2.metric(
                "Manual Review",
                "Yes" if diagnostic_gate.get("requires_manual_review") else "No",
            )
            g3.metric(
                "Blocks Core/Cavity",
                "Yes" if diagnostic_gate.get("blocks_core_cavity") else "No",
            )
            st.caption(parting.get("method", "Parting-line candidate detection"))

            pull = parting.get("pull_direction", [0.0, 0.0, 1.0])
            st.write(
                f"Pull direction source: `{parting.get('pull_direction_source', 'unknown')}` "
                f"= {_direction_axis_tilt_text(pull)}"
            )
            st.write(
                f"Refinement: `{refinement.get('quality', 'unknown')}` "
                f"({refinement.get('status', 'unknown')})"
            )
            _render_parting_curve_display_metrics(refinement)
            cleanup_rows = _graph_cleanup_rows(refinement)
            cleanup = refinement.get("graph_cleanup", {}) or {}
            removed_conflict_ids = cleanup.get("removed_conflict_edge_ids", []) or []
            retained_conflict_ids = cleanup.get("retained_conflict_edge_ids", []) or []
            if removed_conflict_ids:
                st.success(
                    "Graph cleanup removed undercut-conflict edge(s): "
                    f"{removed_conflict_ids}"
                )
            elif retained_conflict_ids:
                st.warning(
                    "The refined parting path still retains undercut-conflict edge(s): "
                    f"{retained_conflict_ids}"
                )
            if cleanup_rows:
                with st.expander("Graph Cleanup Evidence", expanded=bool(removed_conflict_ids or retained_conflict_ids)):
                    _safe_dataframe(cleanup_rows, use_container_width=True)
            st.write(
                f"Selection quality score: `{selection_quality.get('score', 0.0)}` | "
                f"Undercut conflict score: `{undercut_conflict.get('conflict_score', 0.0)}` | "
                f"Readiness score: `{readiness.get('score', 0.0)}`"
            )

            conflict_rows = _parting_conflict_rows(undercut_conflict)
            conflict_markers = _parting_conflict_markers(undercut_conflict)
            if undercut_conflict.get("checked"):
                conflict_level = str(undercut_conflict.get("conflict_level", "none"))
                if conflict_level == "high":
                    st.warning("Parting-line candidate crosses or closely approaches major undercut evidence.")
                elif conflict_level in {"medium", "low"}:
                    st.info("Parting-line candidate has undercut proximity evidence to review.")
                else:
                    st.success("No refined-path undercut conflict detected.")
                    if initial_counts["major"]:
                        st.warning(
                            "The selected wire is clear in the optimized-direction context, "
                            "but the selected initial-direction undercut analysis still contains a major feature."
                        )
            else:
                st.info("Undercut conflict was not checked for this parting-line result.")

            if conflict_rows:
                st.subheader("Undercut Conflict Evidence")
                _safe_dataframe(conflict_rows, use_container_width=True)
            if initial_undercuts:
                _render_major_undercut_callout(
                    initial_undercuts,
                    title="Initial Major Undercut Context",
                )

            raw_path = paths.get("raw", {})
            refined_path = paths.get("refined", {})
            if refined_path.get("fallback_to_raw"):
                st.warning(
                    "Refined curve had fewer than 3 points; displaying raw wire as fallback."
                )
            readiness_score = _safe_float(readiness.get("score", 0.0))
            wire_closed = refinement.get("display_metrics", {}).get("closed", refinement.get("closed"))
            st.write(
                f"Wire points: raw {raw_path.get('point_count', 0)} | "
                f"refined {refined_path.get('point_count', 0)} | "
                f"closed: {wire_closed if wire_closed is not None else 'unknown'} | "
                f"readiness score: {readiness_score:.3f}"
            )
            line_paths = _visible_parting_line_paths(
                raw_path,
                refined_path,
                show_raw=show_raw_parting_line,
                show_refined=show_refined_parting_line,
            )

            st.subheader("Curve Overlay")
            curve_rows = []
            if refined_path.get("points"):
                curve_rows.append(_curve_metrics(refined_path))
            if raw_path.get("points"):
                curve_rows.append(_curve_metrics(raw_path))
            if curve_rows:
                _safe_dataframe(curve_rows, use_container_width=True)
            if not line_paths:
                st.warning("No parting-line curve is currently visible. Enable raw or refined curve in the sidebar.")

            if include_mesh and "display_mesh" in result:
                _mesh_payload = _hydrate_mesh(result.get("display_mesh"))
                shown = _show_mesh(
                    _mesh_payload,
                    color_key="parting_rgb",
                    line_paths=line_paths,
                    marker_points=conflict_markers,
                    viewer_key=(
                        f"parting-line-{selected_part}-"
                        f"raw-{show_raw_parting_line}-refined-{show_refined_parting_line}-"
                        f"{len(line_paths)}-markers-{len(conflict_markers)}"
                    ),
                )
                if not shown:
                    _render_summary_grid([
                        (
                            "Mesh Points",
                            _mesh_payload.get("point_count", 0),
                            "Fallback display",
                        ),
                        (
                            "Mesh Triangles",
                            _mesh_payload.get("triangle_count", 0),
                            "Fallback display",
                        ),
                        (
                            "Raw Points",
                            raw_path.get("point_count", 0),
                            "Parting wire",
                        ),
                        (
                            "Refined Points",
                            refined_path.get("point_count", 0),
                            "Display curve",
                        ),
                    ])
                    st.json({
                        "visible_curves": [
                            {
                                "label": path.get("label"),
                                "point_count": path.get("point_count"),
                                "color": path.get("hex"),
                            }
                            for path in line_paths
                        ],
                        "conflict_markers": conflict_markers,
                    })

            if parting.get("warnings"):
                with st.expander("Parting-line warnings"):
                    for warning in parting["warnings"]:
                        st.warning(warning)

            if diagnostics:
                with st.expander("Parting-line diagnostics"):
                    if diagnostics.get("failure_code"):
                        st.warning(
                            f"{diagnostics.get('failure_code')}: "
                            f"{diagnostics.get('recovery_hint', '')}"
                        )
                    st.json(diagnostics)

            with st.expander("Parting-line quality and undercut conflict"):
                st.json({
                    "readiness": readiness,
                    "diagnostic_gate": diagnostic_gate,
                    "diagnostics": diagnostics,
                    "selection_quality": selection_quality,
                    "undercut_conflict": undercut_conflict,
                    "selected_wire_undercut_conflict": selected_wire_conflict,
                    "refined_undercut_conflict": parting.get("refined_undercut_conflict", {}),
                })

            st.subheader("Candidate Components")
            _safe_dataframe(parting.get("components", []), use_container_width=True)

            with st.expander("Parting Line JSON"):
                st.json(parting)

    with parting_v2_tab:
        st.subheader("Parting Line v2 (experimental) — engineering / debug view")
        st.info(
            "Clean-room Level 0-2 engine (Track A/B -> stitching -> graph -> "
            "2-core -> candidate generation -> H0-H7 -> ranking). Not the "
            "default engine yet -- see docs/IMPLEMENTATION_STATUS.md. "
            "Direction is always manually supplied here: this engine never "
            "calls the direction optimizer. Every number below comes "
            "directly from the API response -- nothing on this tab is "
            "pre-computed or hardcoded in the frontend."
        )

        PV2_DIRECTION_PRESETS = {
            "+X": (1.0, 0.0, 0.0), "-X": (-1.0, 0.0, 0.0),
            "+Y": (0.0, 1.0, 0.0), "-Y": (0.0, -1.0, 0.0),
            "+Z": (0.0, 0.0, 1.0), "-Z": (0.0, 0.0, -1.0),
        }

        def _pv2_apply_preset() -> None:
            preset = st.session_state.get("pv2_direction_preset")
            if preset in PV2_DIRECTION_PRESETS:
                dx, dy, dz = PV2_DIRECTION_PRESETS[preset]
                st.session_state["pv2_dx"] = dx
                st.session_state["pv2_dy"] = dy
                st.session_state["pv2_dz"] = dz

        st.radio(
            "Pull direction",
            list(PV2_DIRECTION_PRESETS.keys()) + ["Custom / manual override"],
            index=4,  # "+Z", matching the dx/dy/dz defaults below on first load
            key="pv2_direction_preset",
            horizontal=True,
            on_change=_pv2_apply_preset,
        )

        dcol1, dcol2, dcol3 = st.columns(3)
        with dcol1:
            pv2_dx = st.number_input("dx", value=0.0, step=0.1, format="%.4f", key="pv2_dx")
        with dcol2:
            pv2_dy = st.number_input("dy", value=0.0, step=0.1, format="%.4f", key="pv2_dy")
        with dcol3:
            pv2_dz = st.number_input("dz", value=1.0, step=0.1, format="%.4f", key="pv2_dz")

        st.markdown("#### ⚙️ Manually Authorized Engineering Input")
        st.caption(
            "Core-pin interfaces and secondary-action groups are ENGINEER-SUPPLIED "
            "authorizations, never discovered or inferred by the algorithm. Leave "
            "both empty to run with no authorization at all (today's default)."
        )
        mcol1, mcol2 = st.columns([2, 1])
        with mcol1:
            if st.button("Load Part3 +Z reference example (candidate 110)", key="pv2_load_example"):
                st.session_state["pv2_core_pin_json"] = json.dumps([
                    {"face_id": 35, "axis_direction": [0.0, 0.0, 1.0],
                     "reason": "straight coaxial through-bore"},
                ], indent=2)
                st.session_state["pv2_delegations_json"] = json.dumps([
                    {"face_ids": list(range(0, 17)), "movement_direction": [1.0, 0.0, 0.0],
                     "movement_type": "radial_slide", "source": "manual_engineering",
                     "note": "original rib stack, radial outward +X"},
                    {"face_ids": list(range(18, 35)), "movement_direction": [-1.0, 0.0, 0.0],
                     "movement_type": "radial_slide", "source": "manual_engineering",
                     "note": "mirror rib stack, radial outward -X"},
                ], indent=2)
                st.info(
                    "Example filled in (Part3, +Z only). Nothing has run yet -- "
                    "select +Z above, then click \"Run v2 analysis\"."
                )
        with mcol2:
            if st.button("Clear authorization", key="pv2_clear_authorization"):
                st.session_state["pv2_core_pin_json"] = "[]"
                st.session_state["pv2_delegations_json"] = "[]"

        pv2_core_pin_json_text = st.session_state.get("pv2_core_pin_json", "[]")
        pv2_delegations_json_text = st.session_state.get("pv2_delegations_json", "[]")

        def _pv2_count_preview(raw_json: str) -> int | None:
            try:
                parsed = json.loads(raw_json or "[]")
                return len(parsed) if isinstance(parsed, list) else None
            except json.JSONDecodeError:
                return None

        n_core_pin_preview = _pv2_count_preview(pv2_core_pin_json_text)
        n_delegations_preview = _pv2_count_preview(pv2_delegations_json_text)
        if (n_core_pin_preview or 0) > 0 or (n_delegations_preview or 0) > 0:
            st.markdown(
                f"<div class='dfm-status-row'>"
                f"<span class='dfm-chip dfm-chip-current'>⚙ {n_core_pin_preview or 0} core-pin authorization(s)</span>"
                f"<span class='dfm-chip dfm-chip-current'>⚙ {n_delegations_preview or 0} secondary-action group(s) authorized</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.caption("No manual authorization currently set — the pipeline will run with its default (empty) inputs.")

        dev_mode = st.checkbox(
            "Advanced / Developer Mode — edit raw JSON authorization",
            value=False, key="pv2_dev_mode",
        )
        if dev_mode:
            pv2_core_pin_json_text = st.text_area(
                "Core-pin face authorizations (JSON array)",
                value=pv2_core_pin_json_text,
                key="pv2_core_pin_json", height=100,
            )
            pv2_delegations_json_text = st.text_area(
                "Secondary-action delegations (JSON array)",
                value=pv2_delegations_json_text,
                key="pv2_delegations_json", height=140,
            )

        if st.button("Run v2 analysis", key="pv2_run_button"):
            if abs(pv2_dx) + abs(pv2_dy) + abs(pv2_dz) < 1e-9:
                st.error("Direction vector must be nonzero.")
            else:
                parse_ok = True
                core_pin_payload = None
                delegations_payload = None
                try:
                    parsed = json.loads(pv2_core_pin_json_text or "[]")
                    core_pin_payload = json.dumps(parsed) if parsed else None
                except json.JSONDecodeError as exc:
                    st.error(f"Core-pin authorization JSON is invalid: {exc}")
                    parse_ok = False
                try:
                    parsed = json.loads(pv2_delegations_json_text or "[]")
                    delegations_payload = json.dumps(parsed) if parsed else None
                except json.JSONDecodeError as exc:
                    st.error(f"Delegation authorization JSON is invalid: {exc}")
                    parse_ok = False

                if parse_ok:
                    params: dict[str, Any] = {"dx": pv2_dx, "dy": pv2_dy, "dz": pv2_dz}
                    if core_pin_payload:
                        params["core_pin_face_refs"] = core_pin_payload
                    if delegations_payload:
                        params["delegations"] = delegations_payload
                    with st.spinner("Running Track A/B -> graph -> H0-H7 (v2)..."):
                        try:
                            pv2_response = requests.get(
                                f"{BACKEND_URL}/parts/{selected_part}/parting-line-v2",
                                params=params,
                                timeout=180,
                            )
                            pv2_response.raise_for_status()
                            st.session_state["parting_line_v2_result"] = pv2_response.json()
                            st.session_state["parting_line_v2_request"] = {
                                "part": selected_part, "dx": pv2_dx, "dy": pv2_dy, "dz": pv2_dz,
                                "core_pin_face_refs": core_pin_payload, "delegations": delegations_payload,
                            }
                        except requests.RequestException as exc:
                            error_detail = None
                            try:
                                error_detail = pv2_response.json().get("error")
                            except Exception:
                                pass
                            if isinstance(error_detail, dict):
                                st.error(
                                    f"v2 analysis failed ({error_detail.get('code', 'error')}): "
                                    f"{error_detail.get('message', str(exc))}"
                                )
                            else:
                                st.error(f"v2 analysis failed: {exc}")

        pv2_result = st.session_state.get("parting_line_v2_result")
        if pv2_result is None:
            st.caption("Choose a direction above and click \"Run v2 analysis\".")
        else:
            outcome = pv2_result.get("outcome", "unknown")
            selected = pv2_result.get("selected")
            feasibility = (selected or {}).get("feasibility") or {}
            validated_delegations = feasibility.get("validated_delegations") or []
            core_pin_interfaces = (selected or {}).get("core_pin_interfaces") or []
            regions = pv2_result.get("regions")
            candidate_count = pv2_result.get("candidate_count", 0)
            bounds = pv2_result.get("bounds", {}) or {}
            rejection_summary = pv2_result.get("rejection_summary", {}) or {}
            scorecard = pv2_result.get("scorecard", []) or []

            # -----------------------------------------------------------------
            # THREE-STATE CLASSIFICATION (A/B/C) -- derived only from gate
            # outcomes already in the response, never from a new heuristic or
            # hardcoded threshold:
            #   A = no candidate ever reached H3 (no primary split exists)
            #   B = a candidate reached H3 (a valid split exists) but every
            #       one fails H4 without authorization, OR the pipeline
            #       explicitly referred to H5 side-action analysis
            #   C = a candidate passed everything (outcome == "feasible")
            # Note: B does not by itself mean secondary-action authorization
            # WILL resolve it -- only that a genuine two-region split exists
            # and the remaining obstacle is orientation-consistency (H4).
            # Whether that split is a meaningful engineering architecture
            # (core/cavity balance) is not assessed for rejected candidates.
            # -----------------------------------------------------------------
            dir_vec = pv2_result.get("pull_direction", {}).get("direction", [0, 0, 0])
            dir_label = f"({dir_vec[0]:+.2f}, {dir_vec[1]:+.2f}, {dir_vec[2]:+.2f})"
            dir_source = pv2_result.get("pull_direction", {}).get("source", "unknown")

            reached_h3_or_later = candidate_count - sum(
                rejection_summary.get(g, 0) for g in ("H0", "H1", "H2", "H3")
            )
            passed_h4_or_later = candidate_count - sum(
                rejection_summary.get(g, 0) for g in ("H0", "H1", "H2", "H3", "H4")
            )

            if outcome == "feasible":
                state_letter, state_tone = "C", "success"
                state_title = "FEASIBLE WITH VALIDATED SECONDARY-ACTION AUTHORIZATION" if validated_delegations else "FEASIBLE — no secondary action required"
            elif outcome == "referred_to_side_action" or (candidate_count > 0 and reached_h3_or_later > 0 and passed_h4_or_later == 0):
                state_letter, state_tone = "B", "warning"
                state_title = "PRIMARY ARCHITECTURE IDENTIFIED — requires unresolved/unauthorized secondary action"
            else:
                state_letter, state_tone = "A", "error"
                state_title = "NO FEASIBLE PRIMARY ARCHITECTURE"

            state_banner = {"success": st.success, "warning": st.warning, "error": st.error}[state_tone]
            state_banner(f"**{state_letter} · {state_title}**")

            # ---- Engineering Architecture Summary --------------------------
            sel_feas = (selected or {}).get("feasibility") or {}
            sel_meas = sel_feas.get("measurements") or {}
            score = (selected or {}).get("score") or {}

            h4_val = sel_meas.get("h4_orientation_violation_fraction")
            h4_delegated_n = sel_meas.get("h4_delegated_face_count", 0.0)
            h4_display = "n/a" if h4_val is None else (
                f"{h4_val:.2%} (after {int(h4_delegated_n)} delegated face(s) excluded)"
                if validated_delegations else f"{h4_val:.2%}"
            )

            h5_conflict = sel_meas.get("h5_conflicting_face_count")
            if h5_conflict is None:
                h5_display = "Not reached" if selected is None else "n/a"
            elif outcome == "referred_to_side_action":
                h5_display = f"⚠ Referred ({int(h5_conflict)} conflicting face(s))"
            else:
                h5_display = f"✓ Pass ({int(h5_conflict)} conflicts)"

            if validated_delegations:
                verifications = {d.get("evidence", {}).get("geometric_verification", "unknown") for d in validated_delegations}
                gv_display = " / ".join(sorted(verifications))
            else:
                gv_display = "n/a — no secondary action authorized"

            st.markdown("#### Engineering Architecture Summary")
            _render_summary_grid([
                ("Primary pull direction", dir_label, f"source: {dir_source}"),
                ("PL status", state_letter, state_title[:40] + ("…" if len(state_title) > 40 else "")),
                ("Selected candidate", selected.get("candidate_id") if selected else "—", f"of {candidate_count} evaluated"),
                (
                    "Core / Cavity",
                    f"{(regions or {}).get('core_face_count', '—')} / {(regions or {}).get('cavity_face_count', '—')} faces"
                    if regions else "—",
                    "graph-connectivity based" if regions else "not available (no passing candidate)",
                ),
                ("Core pins", len(core_pin_interfaces), "D-043 metadata, not a PL curve"),
                ("Secondary-action groups", len(validated_delegations), "D-044, structurally validated"),
                ("Lifters", "—", "not reported by this engine"),
                ("H4 (orientation)", h4_display, ""),
                ("H5 (undercut conflict)", h5_display, ""),
                ("Geometric verification", gv_display, "never elevated beyond \"unverified\""),
            ])

            if validated_delegations:
                st.caption(
                    "⚙️ The core-pin interface and secondary-action groups above are "
                    "MANUALLY AUTHORIZED ENGINEERING INPUT — supplied by you, not "
                    "discovered by the algorithm. Structural validation confirms only "
                    "that the authorized groups are connected, non-parallel to the "
                    "primary pull, and disjoint from Γ."
                )
                st.warning(
                    "⚠ Secondary action structurally validated, physical release "
                    "**UNVERIFIED**. This is not a sweep, collision, or interference "
                    "check. No physical release has been simulated or proven."
                )

            with st.expander("Candidate-level detail", expanded=False):
                if selected is not None:
                    st.markdown(
                        f"Selected candidate **{selected.get('candidate_id')}** "
                        f"({selected.get('discovered_by')}, {selected.get('segment_count')} segments) · "
                        f"coverage {score.get('coverage', 0):.1%}" if score.get("coverage") is not None else ""
                    )
                    if core_pin_interfaces:
                        for interface in core_pin_interfaces:
                            st.caption(
                                f"Core-pin interface: face {interface.get('face_id')}, split parameter ≈ "
                                f"{interface.get('split_param'):.3f}, \"{interface.get('reason')}\"."
                            )
                    for i, d in enumerate(validated_delegations):
                        ev = d.get("evidence", {})
                        st.markdown(
                            f"- Group {chr(65+i)}: {len(d.get('face_ids', []))} faces "
                            f"(`{sorted(d.get('face_ids', []))[:3]}...`), movement "
                            f"`{tuple(round(c, 2) for c in d.get('movement_direction', []))}`, "
                            f"type `{d.get('movement_type')}` — "
                            f"**geometric_verification: \"{ev.get('geometric_verification', 'unknown')}\"**"
                        )
                else:
                    h3_valid_scored = [
                        c for c in scorecard
                        if (c.get("feasibility") or {}).get("measurements", {}).get("h3_region_count") == 2.0
                    ]
                    if h3_valid_scored:
                        best = min(
                            h3_valid_scored,
                            key=lambda c: (c.get("feasibility") or {}).get("measurements", {}).get(
                                "h4_orientation_violation_fraction", float("inf")
                            ),
                        )
                        best_meas = (best.get("feasibility") or {}).get("measurements", {})
                        st.markdown("**Best candidate found (rejected):**")
                        bcols = st.columns(3)
                        bcols[0].metric("Candidate", best.get("candidate_id"))
                        bcols[1].metric("H4 violation", f"{best_meas.get('h4_orientation_violation_fraction', 0):.2%}")
                        bcols[2].metric("Failed at", (best.get("feasibility") or {}).get("failed_gate", "?"))
                        st.caption(
                            "Core/cavity balance: not available for rejected candidates — "
                            "region classification is only computed for the passing candidate."
                        )
                    elif candidate_count == 0:
                        st.caption(
                            "Candidate generation itself found zero closed loops for this "
                            f"direction (strategy={bounds.get('strategy', 'unknown')}, "
                            f"cyclomatic_number={bounds.get('cyclomatic_number', '?')}). "
                            "This is not a gate rejection; there was nothing to evaluate."
                        )
                    else:
                        st.caption(
                            f"No candidate reached H3=2 (a valid two-region separation) at this "
                            f"direction. All {rejection_summary.get('H3', 0)} H3 rejections were "
                            "either under-separated (1 region) or over-partitioned (3+ regions)."
                        )

            # -----------------------------------------------------------------
            # Candidate ranking / why-selected
            # -----------------------------------------------------------------
            with st.expander(f"Candidate breakdown ({len(scorecard)} total)", expanded=False):
                rows = []
                for c in scorecard:
                    feas = c.get("feasibility") or {}
                    meas = feas.get("measurements") or {}
                    rows.append({
                        "candidate_id": c.get("candidate_id"),
                        "discovered_by": c.get("discovered_by"),
                        "segments": c.get("segment_count"),
                        "h3_region_count": meas.get("h3_region_count"),
                        "h4_violation": meas.get("h4_orientation_violation_fraction"),
                        "failed_gate": feas.get("failed_gate"),
                        "passed": feas.get("passed"),
                        "selected": c.get("candidate_id") == (selected or {}).get("candidate_id"),
                    })
                rows.sort(key=lambda r: (
                    not r["selected"],
                    r["h4_violation"] if r["h4_violation"] is not None else float("inf"),
                ))
                _safe_dataframe(rows[:50], use_container_width=True)
                if len(rows) > 50:
                    st.caption(f"Showing 50 of {len(rows)} candidates (sorted: selected first, then best H4).")

            # -----------------------------------------------------------------
            # 3D visualization with independent overlay toggles
            # -----------------------------------------------------------------
            st.markdown("#### 3D Visualization")
            tcol1, tcol2, tcol3, tcol4, tcol5, tcol6 = st.columns(6)
            show_pl = tcol1.checkbox("✓ Primary PL", value=True, key="pv2_show_pl")
            show_core_cavity = tcol2.checkbox("Core/Cavity", value=selected is not None, key="pv2_show_region")
            show_undercuts = tcol3.checkbox("Undercuts", value=False, key="pv2_show_undercuts")
            show_side_actions = tcol4.checkbox("Side Actions", value=bool(validated_delegations), key="pv2_show_delegations")
            show_core_pin = tcol5.checkbox("Core Pin", value=bool(core_pin_interfaces), key="pv2_show_core_pin")
            show_unclassified = tcol6.checkbox("Neutral (no overlay)", value=False, key="pv2_show_neutral")
            st.caption(
                "Toggles only change what's highlighted in the viewport below — the "
                "underlying result (candidate, gates, authorization) is unaffected."
            )

            # The real Γ, rendered bold and unmistakable -- points come only
            # from the API's own selected-candidate geometry; width/colour
            # are display-only overrides, never a change to what curve is
            # drawn or where it comes from.
            # Near-black core + light halo (set in _show_mesh_plotly) reads
            # clearly against the neutral mesh AND every overlay hue below
            # (blue/orange/red/magenta/gold/cyan/purple/green), unlike a
            # single bright colour that could visually merge with one of them.
            PL_LINE_COLOR = "#111827"
            PL_LINE_WIDTH = 14
            line_paths_v2 = []
            if show_pl and pv2_result.get("parting_line_path"):
                raw_path = pv2_result["parting_line_path"]
                line_paths_v2 = [{
                    **raw_path,
                    "hex": PL_LINE_COLOR,
                    "width": PL_LINE_WIDTH,
                }]

            if "display_mesh" in pv2_result:
                _mesh_payload_v2 = _hydrate_mesh(pv2_result.get("display_mesh"))
                mesh_face_ids = _mesh_payload_v2.get("face_ids", [])

                cavity_ids = {
                    f.get("face_id") for f in (regions or {}).get("faces", [])
                    if f.get("label") == "cavity"
                } if regions else set()
                core_ids = {
                    f.get("face_id") for f in (regions or {}).get("faces", [])
                    if f.get("label") == "core"
                } if regions else set()
                undercut_ids = set((pv2_result.get("undercuts") or {}).get("face_ids", {}).get("undercut", []))
                core_pin_ids = {i.get("face_id") for i in core_pin_interfaces}
                delegation_groups = [set(d.get("face_ids", [])) for d in validated_delegations]

                NEUTRAL = [0.72, 0.72, 0.75]
                CAVITY_RGB = [0.35, 0.65, 0.95]
                CORE_RGB = [0.95, 0.55, 0.20]
                UNDERCUT_RGB = [0.90, 0.15, 0.15]
                CORE_PIN_RGB = [0.85, 0.15, 0.85]
                GROUP_PALETTE = [[0.95, 0.75, 0.10], [0.10, 0.75, 0.95], [0.75, 0.10, 0.95], [0.10, 0.95, 0.45]]

                if show_unclassified or not any([show_core_cavity, show_undercuts, show_side_actions, show_core_pin]):
                    composite_rgb = None
                else:
                    composite_rgb = []
                    for fid in mesh_face_ids:
                        color = NEUTRAL
                        if show_core_cavity:
                            if fid in cavity_ids:
                                color = CAVITY_RGB
                            elif fid in core_ids:
                                color = CORE_RGB
                        if show_side_actions:
                            for gi, group in enumerate(delegation_groups):
                                if fid in group:
                                    color = GROUP_PALETTE[gi % len(GROUP_PALETTE)]
                                    break
                        if show_undercuts and fid in undercut_ids:
                            color = UNDERCUT_RGB
                        if show_core_pin and fid in core_pin_ids:
                            color = CORE_PIN_RGB
                        composite_rgb.append(color)

                if composite_rgb is not None:
                    _mesh_payload_v2 = {**_mesh_payload_v2, "pv2_composite_rgb": composite_rgb}
                    color_key_v2 = "pv2_composite_rgb"
                else:
                    color_key_v2 = "__none__"

                shown_v2 = _show_mesh(
                    _mesh_payload_v2,
                    color_key=color_key_v2,
                    line_paths=line_paths_v2,
                    viewer_key=(
                        f"parting-line-v2-{selected_part}-{outcome}-{len(line_paths_v2)}-"
                        f"{show_core_cavity}-{show_undercuts}-{show_side_actions}-{show_core_pin}"
                    ),
                )
                if not shown_v2:
                    _render_summary_grid([
                        ("Mesh Points", _mesh_payload_v2.get("point_count", 0), "Fallback display"),
                        ("Mesh Triangles", _mesh_payload_v2.get("triangle_count", 0), "Fallback display"),
                    ])

                legend_entries: list[tuple[str, str]] = []
                if show_pl and line_paths_v2:
                    legend_entries.append(("Primary parting line (Γ)", PL_LINE_COLOR))
                if show_core_cavity:
                    legend_entries.append(("Cavity", _rgb_to_hex(CAVITY_RGB)))
                    legend_entries.append(("Core", _rgb_to_hex(CORE_RGB)))
                if show_undercuts:
                    legend_entries.append(("Undercut face", _rgb_to_hex(UNDERCUT_RGB)))
                if show_side_actions:
                    for gi, _ in enumerate(delegation_groups):
                        legend_entries.append((f"Side-action Group {chr(65+gi)}", _rgb_to_hex(GROUP_PALETTE[gi % len(GROUP_PALETTE)])))
                if show_core_pin and core_pin_ids:
                    legend_entries.append(("Core-pin face", _rgb_to_hex(CORE_PIN_RGB)))
                if legend_entries:
                    _render_color_legend(legend_entries)
                else:
                    st.caption("No overlay layers active — toggle one above to see it highlighted.")

            # -----------------------------------------------------------------
            # Technical details -- raw gate measurements + full JSON
            # -----------------------------------------------------------------
            with st.expander("Technical details (raw H0-H7 measurements)", expanded=False):
                last_request = st.session_state.get("parting_line_v2_request")
                if last_request:
                    st.caption(f"Exact request that produced this result: `{last_request}`")
                if selected is not None:
                    sel_meas = ((selected.get("feasibility") or {}).get("measurements")) or {}
                    _safe_dataframe(
                        [{"measurement": k, "value": v} for k, v in sorted(sel_meas.items())],
                        use_container_width=True,
                    )
                track_a = pv2_result.get("track_a", {})
                track_b = pv2_result.get("track_b", {})
                reduction = pv2_result.get("reduction", {})
                _render_summary_grid([
                    ("Track A segments", track_a.get("segment_count", 0), "Sharp-edge silhouette"),
                    ("Track B segments", track_b.get("segment_count", 0), "Face-interior silhouette"),
                    ("Graph nodes (post 2-core)", reduction.get("nodes_after", 0), "Welded points"),
                    ("Graph edges (post 2-core)", reduction.get("edges_after", 0), "Curve segments"),
                    ("Cyclomatic number", reduction.get("cyclomatic_number", 0), "Independent loops available"),
                ])
                if rejection_summary:
                    st.markdown("**Rejection breakdown (why candidates failed)**")
                    _safe_dataframe(
                        [{"gate": gate, "candidates_rejected": count} for gate, count in rejection_summary.items()],
                        use_container_width=True,
                    )
                if regions:
                    _render_summary_grid([
                        ("Cavity area", f"{regions.get('cavity_area_mm2', 0):.1f} mm²", ""),
                        ("Core area", f"{regions.get('core_area_mm2', 0):.1f} mm²", ""),
                        (
                            "Ambiguous area fraction",
                            f"{regions.get('ambiguous_area_fraction', 0):.1%}",
                            "Genuinely split/inconsistent faces",
                        ),
                    ])

            with st.expander("Parting Line v2 JSON (full raw response)"):
                st.json(pv2_result)

    with core_cavity_tab:
        st.subheader("Core/Cavity Classification")
        result = st.session_state.get("core_cavity_result")
        if result is None:
            st.info("Run core/cavity classification after direction optimization to view the Level 1 face split.")
        else:
            core_cavity = result.get("core_cavity", {})
            counts = core_cavity.get("face_counts", {})
            percentages = core_cavity.get("percentages", {})
            pull = core_cavity.get("pull_direction", [0.0, 0.0, 1.0])
            _render_color_legend([
                ("Cavity (upper mold half)", "#32c864"),
                ("Core (lower mold half)", "#3264c8"),
                ("Parting zone", "#dcc832"),
            ])
            c1, c2, c3 = st.columns(3)
            c1.metric(
                "Cavity Faces",
                counts.get("cavity", 0),
                f"{percentages.get('cavity_pct', 0)}%",
            )
            c2.metric(
                "Core Faces",
                counts.get("core", 0),
                f"{percentages.get('core_pct', 0)}%",
            )
            c3.metric("Parting Faces", counts.get("parting", 0))
            st.write(f"Pull direction used: `{_direction_axis_tilt_text(pull)}`")
            st.caption(
                "Core/cavity classification uses the optimal mold direction found in Step 4."
            )

            solid_split = result.get("solid_split")
            if isinstance(solid_split, dict):
                st.subheader("Boolean Solid Split (Level 2)")
                split_status = solid_split.get("solid_split_status", "unknown")
                tool_kind = solid_split.get("split_tool_kind", "none")
                _render_quality_indicators([
                    (
                        "Split status",
                        split_status,
                        "good" if split_status == "split_ok" else "bad",
                    ),
                    ("Solids", solid_split.get("split_solid_count", 0), "neutral"),
                    (
                        "Splitting tool",
                        tool_kind,
                        "info" if tool_kind == "planar_approximation" else "neutral",
                        "split_tool_kind",
                    ),
                ])
                if tool_kind == "planar_approximation":
                    st.info(
                        "The cavity/core solids are bisected with a flat plane "
                        "through the parting loop's centroid, not the exact 3-D "
                        "parting surface shown in the Parting Line tab — a real, "
                        "labeled approximation, not a measurement of that curve."
                    )
                if split_status == "split_ok":
                    sc1, sc2, sc3 = st.columns(3)
                    sc1.metric("Cavity volume", f"{solid_split.get('cavity_solid_volume_mm3', 0):.1f} mm³")
                    sc2.metric("Core volume", f"{solid_split.get('core_solid_volume_mm3', 0):.1f} mm³")
                    sc3.metric("Blank volume", f"{solid_split.get('blank_volume_mm3', 0):.1f} mm³")
                elif solid_split.get("failure_reason"):
                    st.warning(solid_split["failure_reason"])
                with st.expander("Solid Split JSON"):
                    st.json(solid_split)

            side_core_data = result.get("side_core")
            if isinstance(side_core_data, dict):
                st.subheader("Side Core / Lifter (Stage 4 — Bosch criterion #5)")
                st.caption(
                    "First increment only: one side core for the single "
                    "highest-confidence critical undercut feature at this "
                    "pull direction. Does not decide lifter vs. slide vs. "
                    "collapsible-core mechanism — see docs/ARCHITECTURE_"
                    "ROADMAP.md Stage 4 §4.3 Q4."
                )
                sc_status = side_core_data.get("status", "unknown")
                _render_quality_indicators([
                    (
                        "Side core status",
                        sc_status,
                        "good" if sc_status == "generated" else (
                            "neutral" if sc_status == "no_feature" else "bad"
                        ),
                    ),
                ])
                if sc_status == "generated":
                    sd1, sd2, sd3 = st.columns(3)
                    sd1.metric("Containing half", side_core_data.get("containing_half", "—"))
                    sd2.metric(
                        "Side core volume",
                        f"{side_core_data.get('side_core_volume_mm3', 0):.1f} mm³",
                    )
                    sd3.metric(
                        "Reduced half volume",
                        f"{side_core_data.get('reduced_half_volume_mm3', 0):.1f} mm³",
                    )
                    st.caption(
                        f"Volume conservation error: "
                        f"{side_core_data.get('conservation_error', 0) * 100:.4f}%"
                    )
                elif sc_status == "no_feature":
                    st.info(
                        "No undercut features at this pull direction — nothing "
                        "for a side core to act on. This is expected at the "
                        "optimizer's recommended direction, which specifically "
                        "searches for undercut-free directions. Try a manual "
                        "override direction below to see a real side core."
                    )
                elif side_core_data.get("failure_reason"):
                    st.warning(side_core_data["failure_reason"])
                with st.expander("Side Core JSON"):
                    st.json(side_core_data)

            if include_mesh and "display_mesh" in result:
                _mesh_payload = _hydrate_mesh(result.get("display_mesh"))
                shown = _show_mesh(
                    _mesh_payload,
                    color_key="core_cavity_rgb",
                    viewer_key=f"core-cavity-{selected_part}",
                )
                if not shown:
                    st.json({
                        "display_mesh": {
                            "point_count": _mesh_payload.get("point_count"),
                            "triangle_count": _mesh_payload.get("triangle_count"),
                        }
                    })
            with st.expander("Core/Cavity JSON"):
                st.json(core_cavity)

    with agent_tab:
        st.subheader("AI DfM Agent (Stage 5)")
        st.caption(
            "Provider-agnostic tool-calling agent that drives the same "
            "deterministic geometry engine used elsewhere in this app -- it "
            "never invents a measurement, only calls tools and narrates "
            "what they returned. See backend/agent/prompts.py for the exact "
            "honesty constraints given to the model."
        )

        agent_providers_info = st.session_state.get("agent_providers_info")
        if agent_providers_info is None:
            agent_providers_info = _backend_get(
                "/agent/providers", params=None, timeout=15,
                failure_label="Could not list agent providers",
            )
            st.session_state["agent_providers_info"] = agent_providers_info

        available_providers = ["gemini", "anthropic", "openai", "grok"]
        default_provider = "gemini"
        if agent_providers_info:
            available_providers = [
                name for name in ["gemini", "anthropic", "openai", "grok"]
                if agent_providers_info.get("available", {}).get(name)
            ] or available_providers
            default_provider = agent_providers_info.get("configured_provider", "gemini")

        provider_choice = st.selectbox(
            "Provider",
            available_providers,
            index=available_providers.index(default_provider)
            if default_provider in available_providers else 0,
            help="Overrides config.yaml's agent.provider for this run only.",
        )
        agent_query = st.text_input(
            "Specific focus (optional)",
            placeholder="e.g. Focus on undercuts requiring side actions.",
        )

        if st.button("Run AI DfM Review", key="run_agent_review"):
            with st.spinner(f"Running the {provider_choice} agent -- calling geometry tools..."):
                agent_result = _fetch_agent_analysis(
                    selected_part, query=agent_query or None, provider=provider_choice,
                )
            st.session_state["agent_result"] = agent_result

        agent_result = st.session_state.get("agent_result")
        if agent_result is None:
            st.info("Click \"Run AI DfM Review\" to have the agent call the geometry tools and report findings.")
        else:
            report = agent_result.get("report", {})
            manufacturability = report.get("overall_manufacturability", "unknown")
            _manufacturability_tone = {
                "good": "good", "acceptable": "info", "problematic": "review", "not_manufacturable": "bad",
            }.get(manufacturability, "neutral")
            _render_quality_indicators([
                ("Manufacturability", manufacturability, _manufacturability_tone),
                ("Tools called", len(report.get("tools_called", [])), "neutral"),
                ("Findings", len(report.get("findings", [])), "neutral"),
            ])
            st.write(
                f"Pull direction used: `{_direction_axis_tilt_text(report.get('pull_direction', [0, 0, 1]))}` "
                f"({report.get('pull_direction_source', 'unknown')})"
            )
            st.markdown(f"**Summary**: {report.get('summary', '')}")

            for warning in report.get("analysis_warnings", []):
                st.warning(warning)

            _AGENT_SEVERITY_STYLE = {
                "critical": ("🔴", "bad"), "high": ("🟠", "review"),
                "medium": ("🟡", "info"), "low": ("🔵", "neutral"),
            }
            for finding in report.get("findings", []):
                icon, _tone = _AGENT_SEVERITY_STYLE.get(finding.get("severity"), ("⚪", "neutral"))
                with st.expander(f"{icon} [{finding.get('severity', '?')}] {finding.get('title', 'Untitled finding')}"):
                    st.write(finding.get("description", ""))
                    ev_source = finding.get("evidence_source", "unknown")
                    st.caption(
                        f"Category: {finding.get('category', '?')} · "
                        f"Evidence: {ev_source} · "
                        f"Confidence: {finding.get('confidence', 0):.0%}"
                    )
                    if finding.get("affected_face_ids"):
                        st.write(f"Affected faces: {finding['affected_face_ids']}")
                    if finding.get("measured_values"):
                        st.write("Measured values:", finding["measured_values"])
                    st.markdown(f"**Recommendation**: {finding.get('recommendation', '')}")
                    if finding.get("estimated_tooling_impact"):
                        st.caption(f"Tooling impact: {finding['estimated_tooling_impact']}")

            with st.expander("Tools called (audit trail)"):
                st.json(report.get("tools_called", []))
            with st.expander("Full report JSON"):
                st.json(report)

    _render_dfm_summary_report(selected_part)
