"""
tests/test_viewer_key_stability.py
-----------------------------------
Static-analysis guard against dynamic viewer_key regressions.

Viewer keys passed to st.plotly_chart(key=...) must encode only the
*logical identity* of the chart (e.g. tab name + selected part), NOT
visual configuration (opacity, edge toggles, undercut filters).

When visual parameters leak into the key, every sidebar interaction
unmounts and remounts the Plotly component, serializing the full ~1-2 MB
mesh figure over the WebSocket.  Rapid slider drags then flood Tornado
with write tasks, producing cascading WebSocketClosedError /
StreamClosedError / "Task exception was never retrieved" messages.

See: plan buzzing-launching-rabbit.md for the full root-cause analysis.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

APP_PATH = Path(__file__).resolve().parent.parent / "frontend" / "app.py"

# Parameters that must NEVER appear inside a viewer_key value.
# These are visual-configuration controls whose changes should update
# the chart in-place, not cause a component remount.
FORBIDDEN_KEY_PARAMS = [
    "region_opacity",
    "show_region_edges",
    "show_proxy_undercut_faces",
    "important_undercuts_only",
    "high_confidence_only",
]

# Regex: captures the string content of viewer_key=f"..." or viewer_key=(...) assignments.
# Handles both single-line  viewer_key=f"..."  and multi-line  viewer_key=(\n  f"..."\n)
_VIEWER_KEY_RE = re.compile(
    r'viewer_key\s*=\s*(?:'
    r'f"([^"]+)"'            # single-line f-string
    r'|'
    r'\(\s*((?:f"[^"]*"\s*)+)\s*\)'  # multi-line parenthesised f-strings
    r')',
    re.MULTILINE,
)


def _extract_viewer_keys(source: str) -> list[tuple[int, str]]:
    """Return (approx_line, key_text) for every viewer_key assignment."""
    results = []
    for m in _VIEWER_KEY_RE.finditer(source):
        key_text = m.group(1) or m.group(2) or ""
        line_no = source[: m.start()].count("\n") + 1
        results.append((line_no, key_text))
    return results


@pytest.mark.unit
def test_viewer_keys_do_not_encode_visual_controls():
    """Viewer keys must encode logical identity, not visual configuration.

    Dynamic parameters in viewer_keys cause Streamlit to unmount/remount
    Plotly chart components on every control interaction, flooding the
    WebSocket with large serialized figures and producing Tornado
    WebSocketClosedError cascades.
    """
    assert APP_PATH.exists(), f"Frontend app not found at {APP_PATH}"
    source = APP_PATH.read_text()
    keys = _extract_viewer_keys(source)

    assert len(keys) > 0, "No viewer_key assignments found — regex may need updating"

    violations: list[str] = []
    for line_no, key_text in keys:
        for param in FORBIDDEN_KEY_PARAMS:
            if param in key_text:
                violations.append(
                    f"  line ~{line_no}: viewer_key contains '{param}': {key_text!r}"
                )

    assert not violations, (
        "Viewer keys must not encode visual-configuration parameters.\n"
        "These cause Plotly component remounts and WebSocket floods:\n"
        + "\n".join(violations)
    )


@pytest.mark.unit
def test_plotly_layout_has_uirevision():
    """Plotly figures should set uirevision to preserve camera across updates.

    With stable viewer_keys, Streamlit updates charts in-place. Without
    uirevision, Plotly.js resets the camera on each update.
    """
    assert APP_PATH.exists(), f"Frontend app not found at {APP_PATH}"
    source = APP_PATH.read_text()
    assert "uirevision" in source, (
        "_show_mesh_plotly() should include uirevision in fig.update_layout() "
        "to preserve camera position across in-place chart updates"
    )
