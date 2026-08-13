"""
backend/report/templates.py
------------------------------
Section layout, styles, and Bosch-neutral branding placeholders for the PDF
DfM report (Stage 6, roadmap §5.3).

Pure layout helpers -- no analysis logic lives here. `pdf_export.py` is the
only caller.
"""
from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, Table, TableStyle

PAGE_SIZE = letter

# Bosch-neutral palette -- a dark slate header/accent, no third-party branding.
_ACCENT = colors.HexColor("#1a2b4c")
_WARNING_BG = colors.HexColor("#fff3e0")
_WARNING_TEXT = colors.HexColor("#8a4b00")
_ROW_ALT_BG = colors.HexColor("#f5f6f8")
_GRID_LINE = colors.HexColor("#cfd3da")

_BASE = getSampleStyleSheet()

TITLE_STYLE = ParagraphStyle(
    "DfMTitle", parent=_BASE["Title"], fontSize=22, textColor=_ACCENT, spaceAfter=4,
)
SUBTITLE_STYLE = ParagraphStyle(
    "DfMSubtitle", parent=_BASE["Normal"], fontSize=10.5, textColor=colors.grey, spaceAfter=16,
)
H1_STYLE = ParagraphStyle(
    "DfMH1", parent=_BASE["Heading1"], fontSize=14.5, textColor=_ACCENT,
    spaceBefore=16, spaceAfter=8,
)
H2_STYLE = ParagraphStyle(
    "DfMH2", parent=_BASE["Heading2"], fontSize=11.5, textColor=colors.black,
    spaceBefore=10, spaceAfter=5,
)
BODY_STYLE = ParagraphStyle("DfMBody", parent=_BASE["BodyText"], fontSize=9.5, leading=13)
CAPTION_STYLE = ParagraphStyle(
    "DfMCaption", parent=_BASE["Normal"], fontSize=8, textColor=colors.grey,
    spaceBefore=2, spaceAfter=6,
)
WARNING_STYLE = ParagraphStyle(
    "DfMWarning", parent=_BASE["Normal"], fontSize=9.5, textColor=_WARNING_TEXT,
    backColor=_WARNING_BG, borderPadding=6, spaceAfter=6, leading=13,
)


def heading(text: str) -> Paragraph:
    return Paragraph(text, H1_STYLE)


def subheading(text: str) -> Paragraph:
    return Paragraph(text, H2_STYLE)


def body(text: str) -> Paragraph:
    return Paragraph(text, BODY_STYLE)


def caption(text: str) -> Paragraph:
    return Paragraph(text, CAPTION_STYLE)


def warning_box(text: str) -> Paragraph:
    return Paragraph(f"⚠️ {text}", WARNING_STYLE)


def key_value_table(rows: list[tuple[str, str]]) -> Table:
    data = [[Paragraph(f"<b>{key}</b>", BODY_STYLE), Paragraph(str(value), BODY_STYLE)] for key, value in rows]
    table = Table(data, colWidths=[2.1 * inch, 4.2 * inch])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, _GRID_LINE),
        ("BACKGROUND", (0, 0), (0, -1), _ROW_ALT_BG),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def data_table(header: list[str], rows: list[list[str]]) -> Table:
    data = [header] + rows
    table = Table(data, repeatRows=1)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.4, _GRID_LINE),
        ("BACKGROUND", (0, 0), (-1, 0), _ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for row_index in range(1, len(data)):
        if row_index % 2 == 0:
            style.append(("BACKGROUND", (0, row_index), (-1, row_index), _ROW_ALT_BG))
    table.setStyle(TableStyle(style))
    return table
