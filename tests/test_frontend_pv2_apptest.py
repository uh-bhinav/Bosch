"""
tests/test_frontend_pv2_apptest.py
------------------------------------
Automated Streamlit interaction tests (streamlit.testing.v1.AppTest) for
the Phase 4 core/cavity visualization work (docs/DECISIONS_AND_ALGORITHMS.md
D-045).

These seed `st.session_state["parting_line_v2_result"]` directly with a
compact, structurally-representative fixture (tests/fixtures/
pv2_candidate110_shaped.json) rather than driving the full guided-flow UI
or requiring a live backend -- the fixture's shape was verified against a
real backend response for Part3 +Z candidate 110 before being trimmed for
size (see the fixture file's header comment). This exercises the exact
rendering code in `frontend.app`'s Parting Line v2 tab end-to-end through
Streamlit's real script-execution engine, without needing pythonOCC, STEP
files, or a running FastAPI server.

IMPORTANT LIMITATION (see also the final Phase 4 report): AppTest can
assert that the correct text/elements are present in the rendered script
output, and that no exception was raised. It cannot verify actual pixel
colors, 3-D viewport rendering (PyVista/Plotly), or that two colors are
*visually* distinguishable to a human. Real browser/viewport inspection is
still required to confirm the visual result -- these tests only prove the
data-to-legend-text wiring is correct.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

streamlit_testing = pytest.importorskip("streamlit.testing.v1")
AppTest = streamlit_testing.AppTest

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_PATH = REPO_ROOT / "frontend" / "app.py"
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "pv2_candidate110_shaped.json"


def _load_fixture() -> dict:
    with open(FIXTURE_PATH) as f:
        return json.load(f)


def _rendered_text(at) -> str:
    markdowns = "\n".join(m.value for m in at.markdown)
    captions = "\n".join(c.value for c in at.caption)
    return markdowns + "\n" + captions


def test_app_boots_with_no_session_state():
    """Baseline smoke test: the app must load without exception before any
    part is selected or any analysis has run (the default, empty state)."""
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.run()
    assert len(at.exception) == 0


def test_v2_tab_renders_all_five_region_states_without_exception():
    fixture = _load_fixture()
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.session_state["selected_part"] = "Part3.stp"
    at.session_state["parting_line_v2_result"] = fixture
    at.run()
    assert len(at.exception) == 0, [e.value for e in at.exception]


def test_v2_legend_labels_all_five_states():
    fixture = _load_fixture()
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.session_state["selected_part"] = "Part3.stp"
    at.session_state["parting_line_v2_result"] = fixture
    at.run()
    text = _rendered_text(at)

    assert "Cavity" in text
    assert "Core" in text
    assert "Split (crosses parting boundary)" in text
    # Phase 4 (D-055): "Ambiguous (side not confidently...)" replaced by
    # "Zero-draft / review" -- the fixture's ambiguous face (id 40) now
    # carries a known topological_side ("cavity"), matching real Part1/
    # Part3 behavior (every measured ambiguous face has a known side), so
    # the legend must show the new wording, not the old "side unknown"
    # phrasing, and must NOT show the separate genuinely-unknown-side
    # legend entry.
    assert "Zero-draft / review" in text
    assert "Ambiguous (side not confidently" not in text
    assert "genuinely unknown" not in text
    # This fixture's regions.faces deliberately omits face_ids 50 and 60
    # (present in display_mesh) to exercise the dormant no-record state.
    assert "No classification data" in text


def test_ambiguous_caption_no_longer_says_split_inconsistent():
    """Regression guard for the terminology fix: the old caption text
    ('Genuinely split/inconsistent faces') conflated ambiguous with split
    and must never reappear."""
    fixture = _load_fixture()
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.session_state["selected_part"] = "Part3.stp"
    at.session_state["parting_line_v2_result"] = fixture
    at.run()
    text = _rendered_text(at)

    assert "split/inconsistent" not in text.lower()
    assert "not confidently assigned to either primary side" in text


def test_gate_area_vs_reported_area_explanation_present():
    fixture = _load_fixture()
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.session_state["selected_part"] = "Part3.stp"
    at.session_state["parting_line_v2_result"] = fixture
    at.run()
    text = _rendered_text(at)

    assert "gate-specific area" in text
    assert "reported area" in text.lower()


def test_no_data_legend_absent_when_every_face_is_classified():
    """The 'No classification data' legend entry must only appear when it
    is actually true -- not unconditionally."""
    fixture = _load_fixture()
    # Add classifications for the two faces this fixture deliberately
    # leaves out, so nothing is unclassified.
    fixture["regions"]["faces"].append(
        {"face_id": 50, "label": "cavity", "cavity_area_mm2": 1.0, "core_area_mm2": 0.0,
         "mean_g": 0.5, "min_g": 0.5, "max_g": 0.5, "sample_count": 11,
         "straddles_zero": False, "is_inconsistent": False}
    )
    fixture["regions"]["faces"].append(
        {"face_id": 60, "label": "core", "cavity_area_mm2": 0.0, "core_area_mm2": 1.0,
         "mean_g": -0.5, "min_g": -0.5, "max_g": -0.5, "sample_count": 11,
         "straddles_zero": False, "is_inconsistent": False}
    )

    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.session_state["selected_part"] = "Part3.stp"
    at.session_state["parting_line_v2_result"] = fixture
    at.run()
    assert len(at.exception) == 0
    text = _rendered_text(at)
    assert "No classification data" not in text
