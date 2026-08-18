"""
tests/test_frontend_pv2_region_colors.py
------------------------------------------
Pure-function tests for the Parting Line v2 core/cavity region coloring
introduced by Phase 4 (docs/DECISIONS_AND_ALGORITHMS.md D-045):
``frontend.app._pv2_build_face_label_map`` and
``frontend.app._pv2_region_color``.

No Streamlit runtime, no OCC, no STEP files required -- these two functions
are plain data transforms over already-computed API response dicts.
"""

from __future__ import annotations

import frontend.app as app


def _regions(faces):
    return {"faces": faces}


def test_build_face_label_map_reads_label_per_face_id():
    regions = _regions([
        {"face_id": 1, "label": "cavity"},
        {"face_id": 2, "label": "core"},
        {"face_id": 3, "label": "split"},
        {"face_id": 4, "label": "ambiguous"},
    ])
    mapping = app._pv2_build_face_label_map(regions)
    assert mapping == {1: "cavity", 2: "core", 3: "split", 4: "ambiguous"}


def test_build_face_label_map_empty_when_regions_is_none():
    assert app._pv2_build_face_label_map(None) == {}


def test_build_face_label_map_empty_when_regions_has_no_faces_key():
    assert app._pv2_build_face_label_map({}) == {}


def test_all_four_labels_produce_distinct_colors():
    mapping = {1: "cavity", 2: "core", 3: "split", 4: "ambiguous"}
    colors = {
        label: tuple(app._pv2_region_color(fid, mapping, True))
        for fid, label in mapping.items()
    }
    assert len(set(colors.values())) == 4, f"expected 4 distinct colors, got {colors}"


def test_missing_face_id_with_regions_present_gets_no_data_color():
    mapping = {1: "cavity"}
    color = app._pv2_region_color(999, mapping, True)
    assert color == app.PV2_NO_DATA_RGB
    # And it must be visually distinct from every labeled state and from
    # the "nothing computed at all" neutral color.
    other_colors = {
        tuple(app.PV2_CAVITY_RGB), tuple(app.PV2_CORE_RGB),
        tuple(app.PV2_SPLIT_RGB), tuple(app.PV2_AMBIGUOUS_RGB),
        tuple(app.PV2_NEUTRAL_RGB),
    }
    assert tuple(color) not in other_colors


def test_missing_face_id_with_no_regions_at_all_gets_neutral_not_no_data():
    """When regions is None entirely (no candidate selected), an
    unclassified face_id must fall back to the pre-Phase-4 neutral color,
    not the new no-classification-data color -- those are different
    situations (see _pv2_region_color's regions_present argument)."""
    color = app._pv2_region_color(999, {}, False)
    assert color == app.PV2_NEUTRAL_RGB
    assert color != app.PV2_NO_DATA_RGB


def test_cavity_and_core_colors_are_unchanged_from_pre_phase_4_values():
    # These exact RGB triples were the hardcoded CAVITY_RGB/CORE_RGB values
    # in the v2 tab's composite-color loop before Phase 4 -- Phase 4 must
    # not alter them.
    assert app.PV2_CAVITY_RGB == [0.35, 0.65, 0.95]
    assert app.PV2_CORE_RGB == [0.95, 0.55, 0.20]
    assert app._pv2_region_color(1, {1: "cavity"}, True) == [0.35, 0.65, 0.95]
    assert app._pv2_region_color(1, {1: "core"}, True) == [0.95, 0.55, 0.20]


def test_ambiguous_face_with_known_topological_side_gets_blended_color():
    """Phase 4 (D-055): an ambiguous face with a known topological_side
    ('cavity' or 'core') must render as that side's color subtly blended
    toward a dark accent -- NOT the old flat PV2_AMBIGUOUS_RGB, and NOT
    the plain unblended cavity/core color either (must remain visually
    distinct/secondary, per the explicit "subtle, not dominant"
    instruction)."""
    label_map = {1: "ambiguous"}
    cavity_side_color = app._pv2_region_color(1, label_map, True, {1: "cavity"})
    core_side_color = app._pv2_region_color(1, label_map, True, {1: "core"})

    assert cavity_side_color != app.PV2_AMBIGUOUS_RGB
    assert cavity_side_color != app.PV2_CAVITY_RGB
    assert cavity_side_color == app._pv2_blend_zero_draft(app.PV2_CAVITY_RGB)

    assert core_side_color != app.PV2_AMBIGUOUS_RGB
    assert core_side_color != app.PV2_CORE_RGB
    assert core_side_color == app._pv2_blend_zero_draft(app.PV2_CORE_RGB)

    assert cavity_side_color != core_side_color, (
        "the blended color must still distinguish cavity-side from "
        "core-side -- the side information must not be lost"
    )


def test_ambiguous_face_without_known_topological_side_falls_back_to_flat_ambiguous():
    """No topological_side_map passed (backward compatibility) or an
    explicitly 'unknown' side must reproduce the pre-D-055 flat
    PV2_AMBIGUOUS_RGB exactly -- never silently guessed as cavity or core."""
    label_map = {1: "ambiguous"}
    assert app._pv2_region_color(1, label_map, True) == app.PV2_AMBIGUOUS_RGB
    assert app._pv2_region_color(1, label_map, True, {}) == app.PV2_AMBIGUOUS_RGB
    assert app._pv2_region_color(1, label_map, True, {1: "unknown"}) == app.PV2_AMBIGUOUS_RGB


def test_blend_zero_draft_keeps_the_base_hue_dominant():
    """The blend must be subtle: the dominant color channel of the base
    cavity/core color must remain dominant after blending, not overpowered
    by the accent -- 'the normal cavity/core colors should remain
    dominant' per the explicit instruction."""
    blended = app._pv2_blend_zero_draft(app.PV2_CAVITY_RGB)
    # PV2_CAVITY_RGB's blue channel (index 2) is its largest component.
    assert blended[2] == max(blended), (
        "blending should darken the color, not shift which channel dominates"
    )
    # Must actually be darker (a review marking), not identical to the base.
    assert sum(blended) < sum(app.PV2_CAVITY_RGB)


def test_new_colors_do_not_collide_with_other_v2_overlay_colors():
    # Colors already used elsewhere in the same viewport for other,
    # simultaneously-toggleable overlays (undercuts, core-pin, delegation
    # groups, primary PL). Split/ambiguous/no-data must not match any of
    # them.
    other_overlay_colors = {
        (0.90, 0.15, 0.15),  # UNDERCUT_RGB
        (0.85, 0.15, 0.85),  # CORE_PIN_RGB
        (0.95, 0.75, 0.10), (0.10, 0.75, 0.95),  # GROUP_PALETTE[0:2]
        (0.75, 0.10, 0.95), (0.10, 0.95, 0.45),  # GROUP_PALETTE[2:4]
    }
    new_colors = {
        tuple(app.PV2_SPLIT_RGB), tuple(app.PV2_AMBIGUOUS_RGB),
        tuple(app.PV2_NO_DATA_RGB),
    }
    assert new_colors.isdisjoint(other_overlay_colors)
