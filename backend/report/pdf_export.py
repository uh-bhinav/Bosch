"""
backend/report/pdf_export.py
-------------------------------
PDF DfM report export (Stage 6, roadmap §5).

Pure presentation layer: takes the already-computed result dicts -- the same
`.to_dict()` payloads `backend/api/main.py`'s endpoints already return as
JSON -- and lays them out as a PDF via reportlab's Platypus document
builder. Recomputes NOTHING. Every numeric claim in the PDF traces to a
field on one of these dicts (roadmap §5.5's honesty constraint). If a
section's source data carries a warning or a degraded-confidence flag, this
module surfaces it in the report; it never omits one for a cleaner-looking
page.

`reportlab` has been pinned in `requirements.txt` since the initial scaffold
and was imported nowhere before this module.
"""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from typing import Optional

from reportlab.lib.units import inch
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer

from backend.report.templates import (
    PAGE_SIZE,
    SUBTITLE_STYLE,
    TITLE_STYLE,
    body,
    caption,
    data_table,
    heading,
    key_value_table,
    subheading,
    warning_box,
)


def _direction_text(direction) -> str:
    if not direction or len(direction) != 3:
        return "n/a"
    return f"({direction[0]:+.3f}, {direction[1]:+.3f}, {direction[2]:+.3f})"


def _direction_label_display(direction: dict, *, label_key: str = "best_label", vector_key: str = "best_direction") -> str:
    """
    Mirrors frontend/app.py's `_direction_label_display`: `best_label`
    falls back to the raw vector string for non-axis-aligned directions
    (`direction_optimizer.py`'s `_direction_label()`), which would otherwise
    print the same vector twice in a row.
    """
    label = str(direction.get(label_key, "") or "")
    vector_text = _direction_text(direction.get(vector_key))
    is_axis_label = len(label) == 2 and label[0] in "+-" and label[1] in "XYZ"
    return f"{label} {vector_text}" if is_axis_label else vector_text


def _collect_warnings(
    *,
    undercuts: dict,
    parting_line: dict,
    core_cavity: dict,
    solid_split: Optional[dict],
    side_core: Optional[dict],
    agent_report: Optional[dict],
) -> list[str]:
    """
    Aggregate every warning / degraded-confidence flag across sections
    (roadmap §5.5's honesty constraint) so nothing gets silently dropped for
    a cleaner-looking page.
    """
    warnings: list[str] = []

    for w in parting_line.get("warnings", []) or []:
        warnings.append(f"Parting line: {w}")
    for blocker in (parting_line.get("readiness", {}) or {}).get("blockers", []) or []:
        warnings.append(f"Parting-line readiness blocker: {blocker}")

    for w in core_cavity.get("warnings", []) or []:
        warnings.append(f"Core/cavity: {w}")

    reliability = (undercuts.get("boolean_refinement") or {}).get("reliability")
    if reliability and reliability.get("reliability_level") not in (None, "high"):
        warnings.append(
            f"Undercut Boolean reliability is '{reliability.get('reliability_label')}': "
            f"{reliability.get('summary', '')}"
        )

    if solid_split and solid_split.get("solid_split_status") not in (None, "split_ok"):
        reason = solid_split.get("failure_reason")
        msg = f"Core/cavity Boolean solid split status is '{solid_split.get('solid_split_status')}'"
        warnings.append(f"{msg}: {reason}" if reason else msg)
    if solid_split and solid_split.get("split_tool_kind") == "planar_approximation":
        warnings.append(
            "Core/cavity solid split uses a planar-approximation Boolean tool, not the "
            "exact 3-D parting surface shown in the parting-line section."
        )

    if side_core and side_core.get("status") not in (None, "generated", "no_feature", "not_attempted"):
        reason = side_core.get("failure_reason")
        msg = f"Side-core generation status is '{side_core.get('status')}'"
        warnings.append(f"{msg}: {reason}" if reason else msg)

    if agent_report:
        for w in agent_report.get("analysis_warnings", []) or []:
            warnings.append(f"AI agent: {w}")

    return warnings


def build_dfm_report_pdf(
    *,
    filename: str,
    part_summary: dict,
    draft: dict,
    undercuts: dict,
    parting_line: dict,
    core_cavity: dict,
    direction: Optional[dict] = None,
    solid_split: Optional[dict] = None,
    side_core: Optional[dict] = None,
    agent_report: Optional[dict] = None,
    screenshot_png: Optional[bytes] = None,
) -> bytes:
    """
    Build the full PDF DfM report and return its raw bytes.

    Every argument is a JSON-safe dict already produced by this project's
    own `.to_dict()` methods -- see `backend/api/main.py`'s endpoints for
    the exact shapes each one has. `direction`/`solid_split`/`side_core`/
    `agent_report`/`screenshot_png` are optional: the report must be
    generatable without any of them (roadmap §5.2's explicit requirement for
    the agent narrative, applied here to every optional section).
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=PAGE_SIZE,
        title=f"DfM Report - {filename}",
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    story: list = []

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    pull_direction = draft.get("pull_direction") or (direction or {}).get("best_direction")

    story.append(Paragraph("Design for Manufacturability Report", TITLE_STYLE))
    story.append(Paragraph(f"{filename} &nbsp;&middot;&nbsp; generated {generated_at}", SUBTITLE_STYLE))

    warnings = _collect_warnings(
        undercuts=undercuts,
        parting_line=parting_line,
        core_cavity=core_cavity,
        solid_split=solid_split,
        side_core=side_core,
        agent_report=agent_report,
    )
    story.append(subheading("Warnings"))
    if warnings:
        for w in warnings:
            story.append(warning_box(w))
    else:
        story.append(body("No warnings were raised by any analysis stage."))
    story.append(Spacer(1, 10))

    # --- Part summary ---
    story.append(heading("Part Summary"))
    bbox = part_summary.get("bounding_box", {}) or {}
    dims = bbox.get("dimensions_mm", [])
    dims_text = f"{dims[0]:.1f} x {dims[1]:.1f} x {dims[2]:.1f} mm" if len(dims) == 3 else "n/a"
    story.append(key_value_table([
        ("Source file", part_summary.get("source_file", filename)),
        ("Faces / Edges / Vertices", f"{part_summary.get('face_count', 0)} / "
                                     f"{part_summary.get('edge_count', 0)} / "
                                     f"{part_summary.get('vertex_count', 0)}"),
        ("Solids / Shells", f"{part_summary.get('solid_count', 0)} / {part_summary.get('shell_count', 0)}"),
        ("Bounding box", dims_text),
        ("Pull direction used", _direction_text(pull_direction)),
    ]))
    story.append(Spacer(1, 10))

    # --- Direction ---
    if direction:
        story.append(heading("Pull Direction Optimization"))
        story.append(key_value_table([
            ("Best direction", _direction_label_display(direction)),
            ("Best score", f"{direction.get('best_score', 0):.4f} (lower is better)"),
            ("Candidates evaluated", str(direction.get("candidate_count", "n/a"))),
        ]))
        story.append(Spacer(1, 10))

    # --- Draft ---
    story.append(heading("Draft Analysis"))
    pct = draft.get("percentages", {}) or {}
    counts = draft.get("face_counts", {}) or {}
    story.append(key_value_table([
        ("Manufacturable", str(draft.get("is_manufacturable", "n/a"))),
        ("Severity", str(draft.get("severity", "n/a"))),
        (
            "Good / Marginal / Bad",
            f"{pct.get('good_pct', 0)}% / {pct.get('marginal_pct', 0)}% / {pct.get('bad_pct', 0)}%",
        ),
        ("Bad face count", str(counts.get("bad", 0))),
    ]))
    story.append(Spacer(1, 10))

    # --- Undercuts ---
    story.append(heading("Undercut Detection"))
    u_counts = undercuts.get("face_counts", {}) or {}
    boolean_refinement = undercuts.get("boolean_refinement") or {}
    story.append(key_value_table([
        ("Has undercuts", str(undercuts.get("has_undercuts", "n/a"))),
        ("Has critical undercut", str(undercuts.get("has_critical_undercut", "n/a"))),
        ("Feature count", str(undercuts.get("feature_count", 0))),
        ("Undercut faces", str(u_counts.get("undercut", 0))),
        ("Boolean refinement", "enabled" if boolean_refinement.get("enabled") else "disabled"),
    ]))
    features = undercuts.get("features", []) or []
    if features:
        rows = [
            [
                str(f.get("feature_id")),
                str(f.get("severity")),
                str(f.get("undercut_type")),
                str(f.get("evidence_source")),
                str(f.get("recommended_mold_action")),
                f"{f.get('depth_proxy_mm', 0):.2f}",
            ]
            for f in features
        ]
        story.append(Spacer(1, 6))
        story.append(data_table(
            ["ID", "Severity", "Type", "Evidence", "Recommended action", "Depth (mm)"], rows,
        ))
    story.append(Spacer(1, 10))

    # --- Parting line ---
    story.append(heading("Parting Line"))
    readiness = parting_line.get("readiness", {}) or {}
    parting_surface = parting_line.get("parting_surface", {}) or {}
    story.append(key_value_table([
        ("Readiness", f"{readiness.get('status', 'n/a')} ({readiness.get('score', 0):.3f})"),
        ("Closure error (mm)", f"{parting_line.get('closure_error_mm', 0):.6f}"),
        ("Closure guaranteed", str(parting_line.get("closure_guaranteed", "n/a"))),
        ("Silhouette coverage", f"{parting_line.get('silhouette_coverage_ratio', 0) * 100:.1f}%"),
        ("Bridging status", str(parting_line.get("bridging_status", "n/a"))),
        ("Parting surface status", str(parting_surface.get("status", "n/a"))),
    ]))
    story.append(caption(
        "Candidate/foundation parting line overlay -- not a final, fully-optimized "
        "parting line (full Hou global optimization is not implemented)."
    ))
    story.append(Spacer(1, 10))

    # --- Core / cavity ---
    story.append(heading("Core / Cavity Classification"))
    cc_counts = core_cavity.get("face_counts", {}) or {}
    cc_pct = core_cavity.get("percentages", {}) or {}
    story.append(key_value_table([
        (
            "Cavity / Core / Parting faces",
            f"{cc_counts.get('cavity', 0)} / {cc_counts.get('core', 0)} / {cc_counts.get('parting', 0)}",
        ),
        ("Cavity / Core area %", f"{cc_pct.get('cavity_pct', 0)}% / {cc_pct.get('core_pct', 0)}%"),
    ]))

    if solid_split:
        story.append(Spacer(1, 6))
        story.append(subheading("Boolean Solid Split (Level 2)"))
        story.append(key_value_table([
            ("Status", str(solid_split.get("solid_split_status", "n/a"))),
            ("Solid count", str(solid_split.get("split_solid_count", 0))),
            (
                "Cavity / Core volume (mm³)",
                f"{solid_split.get('cavity_solid_volume_mm3', 0):.1f} / "
                f"{solid_split.get('core_solid_volume_mm3', 0):.1f}",
            ),
            ("Splitting tool", str(solid_split.get("split_tool_kind", "n/a"))),
        ]))
        if solid_split.get("split_tool_kind") == "planar_approximation":
            story.append(caption(
                "The exported solids are bisected with a flat plane through the parting "
                "loop's centroid, not the exact 3-D parting surface shown above."
            ))

    if side_core:
        story.append(Spacer(1, 6))
        story.append(subheading("Side Core / Lifter (Bosch criterion #5)"))
        side_core_status = side_core.get("status", "n/a")
        if side_core_status == "generated":
            # conservation_error/side_core_volume_mm3 only carry a real
            # measurement when a side core was actually generated -- for
            # every other status they hold the dataclass's unset default
            # (conservation_error=1.0), which would read as "100% error"
            # if shown unconditionally. Same guard the frontend uses.
            story.append(key_value_table([
                ("Status", side_core_status),
                ("Containing half", str(side_core.get("containing_half", "n/a"))),
                ("Side core volume (mm³)", f"{side_core.get('side_core_volume_mm3', 0):.1f}"),
                ("Conservation error", f"{side_core.get('conservation_error', 0) * 100:.4f}%"),
            ]))
        elif side_core_status == "no_feature":
            story.append(body(
                "No undercut features were detected at this pull direction -- nothing "
                "for a side core to act on. This is expected at the optimizer's "
                "recommended direction, which specifically searches for undercut-free "
                "directions."
            ))
        else:
            story.append(key_value_table([("Status", side_core_status)]))
            if side_core.get("failure_reason"):
                story.append(body(str(side_core["failure_reason"])))
        story.append(caption(
            "Side-core generation identifies the volume of steel that must retract and "
            "along which direction; it does not select a lifter/slide/collapsible-core "
            "actuation mechanism. First increment only: one side core for the single "
            "highest-confidence critical feature."
        ))
    story.append(Spacer(1, 10))

    # --- AI agent narrative (optional -- report must generate without it) ---
    if agent_report:
        story.append(PageBreak())
        story.append(heading("AI Agent DfM Review"))
        story.append(body(str(agent_report.get("summary", ""))))
        story.append(Spacer(1, 6))
        story.append(key_value_table([
            ("Overall manufacturability", str(agent_report.get("overall_manufacturability", "n/a"))),
            ("Tools called", ", ".join(agent_report.get("tools_called", []) or []) or "none"),
            ("Pull direction source", str(agent_report.get("pull_direction_source", "n/a"))),
        ]))
        findings = agent_report.get("findings", []) or []
        if findings:
            rows = [
                [
                    str(f.get("severity")),
                    str(f.get("category")),
                    str(f.get("title")),
                    str(f.get("evidence_source")),
                    f"{f.get('confidence', 0):.0%}",
                ]
                for f in findings
            ]
            story.append(Spacer(1, 6))
            story.append(data_table(["Severity", "Category", "Title", "Evidence", "Confidence"], rows))
        story.append(caption(
            "Narrative generated by the tool-calling AI agent (backend/agent/); every "
            "number above traces to a real tool call result, never model invention."
        ))
        story.append(Spacer(1, 10))

    # --- Screenshot (optional -- report must generate without it) ---
    if screenshot_png:
        story.append(PageBreak())
        story.append(heading("Viewport Screenshot"))
        story.append(Image(BytesIO(screenshot_png), width=6.5 * inch, height=4.5 * inch, kind="proportional"))

    doc.build(story)
    return buf.getvalue()
