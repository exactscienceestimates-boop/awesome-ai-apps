import io
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether, Image as RLImage,
)
from PIL import Image as PILImage
import base64

from models import Property, RoofMeasurement

DARK = colors.HexColor("#1A2332")
ACCENT = colors.HexColor("#2980B9")
LIGHT_GRAY = colors.HexColor("#F2F3F4")
MED_GRAY = colors.HexColor("#BDC3C7")
WHITE = colors.white
MID = colors.HexColor("#2C3E50")


def _s():
    base = getSampleStyleSheet()
    return {
        "company": ParagraphStyle("company", parent=base["Normal"],
            fontSize=16, fontName="Helvetica-Bold", textColor=WHITE),
        "report_title": ParagraphStyle("rt", parent=base["Normal"],
            fontSize=11, fontName="Helvetica-Bold", textColor=WHITE, alignment=TA_RIGHT),
        "report_meta": ParagraphStyle("rm", parent=base["Normal"],
            fontSize=8, fontName="Helvetica", textColor=MED_GRAY, alignment=TA_RIGHT),
        "section": ParagraphStyle("section", parent=base["Normal"],
            fontSize=10, fontName="Helvetica-Bold", textColor=MID, spaceAfter=4),
        "label": ParagraphStyle("label", parent=base["Normal"],
            fontSize=9, fontName="Helvetica-Bold", textColor=MID),
        "value": ParagraphStyle("value", parent=base["Normal"],
            fontSize=9, fontName="Helvetica"),
        "small": ParagraphStyle("small", parent=base["Normal"],
            fontSize=7.5, fontName="Helvetica", textColor=colors.HexColor("#666666")),
        "centered": ParagraphStyle("centered", parent=base["Normal"],
            fontSize=9, fontName="Helvetica", alignment=TA_CENTER),
        "badge": ParagraphStyle("badge", parent=base["Normal"],
            fontSize=8, fontName="Helvetica-Bold", textColor=WHITE, alignment=TA_CENTER),
    }


def _meas_row(label, value, s, highlight=False):
    bg = colors.HexColor("#EBF5FB") if highlight else WHITE
    return ([Paragraph(label, s["label"]), Paragraph(str(value), s["value"])], bg)


def generate_measurement_report(
    prop: Property,
    images: list[tuple[str, bytes]] = None,
    company_name: str = "Your Roofing Co.",
    company_phone: str = "",
    company_license: str = "",
    report_id: str = None,
) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        rightMargin=0.65 * inch, leftMargin=0.65 * inch,
        topMargin=0.65 * inch, bottomMargin=0.65 * inch,
        title=f"Measurement Report — {prop.full_address}",
    )
    W = doc.width
    s = _s()
    story = []

    report_num = report_id or f"RM-{prop.property_id[-6:].upper()}"
    report_date = datetime.now().strftime("%B %d, %Y")

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------
    header_right = Table(
        [[Paragraph("ROOF MEASUREMENT REPORT", s["report_title"])],
         [Paragraph(f"#{report_num}", s["report_meta"])],
         [Paragraph(f"Date: {report_date}", s["report_meta"])]],
        colWidths=[W * 0.4],
    )
    header_data = [[
        Paragraph(company_name, s["company"]),
        header_right,
    ]]
    header_table = Table(header_data, colWidths=[W * 0.6, W * 0.4])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), DARK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 14),
        ("RIGHTPADDING", (-1, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(header_table)

    sub_parts = []
    if company_phone:
        sub_parts.append(f"Tel: {company_phone}")
    if company_license:
        sub_parts.append(f"Lic: {company_license}")
    if sub_parts:
        story.append(Paragraph("  |  ".join(sub_parts), s["small"]))
    story.append(Spacer(1, 10))

    # ------------------------------------------------------------------
    # Property info
    # ------------------------------------------------------------------
    story.append(Paragraph("PROPERTY INFORMATION", s["section"]))
    prop_data = [
        [Paragraph("Address", s["label"]),
         Paragraph(prop.full_address or "—", s["value"]),
         Paragraph("Owner", s["label"]),
         Paragraph(prop.owner_name or "—", s["value"])],
        [Paragraph("Property Type", s["label"]),
         Paragraph(prop.property_type, s["value"]),
         Paragraph("Phone", s["label"]),
         Paragraph(prop.owner_phone or "—", s["value"])],
        [Paragraph("Year Built", s["label"]),
         Paragraph(str(prop.year_built) if prop.year_built else "—", s["value"]),
         Paragraph("Email", s["label"]),
         Paragraph(prop.owner_email or "—", s["value"])],
    ]
    pt = Table(prop_data, colWidths=[W * 0.17, W * 0.33, W * 0.15, W * 0.35])
    pt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), LIGHT_GRAY),
        ("BACKGROUND", (2, 0), (2, -1), LIGHT_GRAY),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("BOX", (0, 0), (-1, -1), 0.5, MED_GRAY),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, MED_GRAY),
    ]))
    story.append(pt)
    story.append(Spacer(1, 10))

    # ------------------------------------------------------------------
    # Measurements
    # ------------------------------------------------------------------
    m = prop.roof_measurement
    story.append(Paragraph("ROOF MEASUREMENTS", s["section"]))

    if not m:
        story.append(Paragraph("No measurements recorded for this property.", s["value"]))
    else:
        adjusted_sq = round(m.total_squares * m.pitch_multiplier * (1 + m.waste_factor_pct), 2)

        rows_raw = [
            ("Total Area (footprint)", f"{m.total_area_sqft:,.0f} sq ft", True),
            ("Total Squares (slope-adjusted)", f"{m.total_squares:.2f} sq", True),
            ("Adjusted Squares (with waste)", f"{adjusted_sq:.2f} sq", True),
            ("Roof Pitch", f"{m.pitch}  (multiplier: {m.pitch_multiplier:.3f})", False),
            ("Complexity", f"{m.complexity}  (factor: {m.complexity_factor:.2f})", False),
            ("Waste Factor", f"{m.waste_factor_pct * 100:.0f}%", False),
            ("Number of Stories", str(m.number_of_stories), False),
            ("Existing Layers (tearoff)", str(m.layers_existing), False),
        ]
        linear_rows = [
            ("Perimeter", f"{m.perimeter_lf:.1f} LF"),
            ("Ridge Length", f"{m.ridges_lf:.1f} LF"),
            ("Valley Length", f"{m.valleys_lf:.1f} LF"),
            ("Hip Length", f"{m.hips_lf:.1f} LF"),
            ("Eave Length", f"{m.eaves_lf:.1f} LF"),
        ]

        # Main measurements table
        meas_rows = []
        for label, val, highlight in rows_raw:
            bg = colors.HexColor("#EBF5FB") if highlight else WHITE
            meas_rows.append(
                ([Paragraph(label, s["label"]), Paragraph(val, s["value"])], bg)
            )

        mt_data = [row for row, _ in meas_rows]
        mt = Table(mt_data, colWidths=[W * 0.45, W * 0.55])
        style_cmds = [
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("BOX", (0, 0), (-1, -1), 0.5, MED_GRAY),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, MED_GRAY),
        ]
        for i, (_, bg) in enumerate(meas_rows):
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), bg))
        mt.setStyle(TableStyle(style_cmds))
        story.append(mt)
        story.append(Spacer(1, 6))

        # Linear footage sub-table
        story.append(Paragraph("Linear Footage Details", s["section"]))
        lf_data = [[Paragraph(lbl, s["label"]), Paragraph(val, s["value"])]
                   for lbl, val in linear_rows]
        lft = Table(lf_data, colWidths=[W * 0.45, W * 0.55])
        lft.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), LIGHT_GRAY),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("BOX", (0, 0), (-1, -1), 0.5, MED_GRAY),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, MED_GRAY),
        ]))
        story.append(lft)
        story.append(Spacer(1, 6))

        # Source + confidence + notes
        src_map = {
            "image_upload": "Image Upload (AI Vision)",
            "address_lookup": "Address Lookup (AI Estimate)",
            "manual_input": "Manual Entry",
        }
        src_display = src_map.get(m.analysis_source, m.analysis_source)
        meta_data = [
            [Paragraph("Measurement Source", s["label"]),
             Paragraph(src_display, s["value"]),
             Paragraph("AI Confidence", s["label"]),
             Paragraph(m.ai_confidence or "—", s["value"])],
        ]
        if m.notes:
            meta_data.append([
                Paragraph("Notes / Conditions", s["label"]),
                Paragraph(m.notes, s["value"]),
                Paragraph("", s["value"]),
                Paragraph("", s["value"]),
            ])
        meta_t = Table(meta_data, colWidths=[W * 0.20, W * 0.30, W * 0.20, W * 0.30])
        meta_t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), LIGHT_GRAY),
            ("BACKGROUND", (2, 0), (2, -1), LIGHT_GRAY),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("BOX", (0, 0), (-1, -1), 0.5, MED_GRAY),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, MED_GRAY),
        ]))
        story.append(meta_t)

    if prop.property_notes:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Property Notes", s["section"]))
        story.append(Paragraph(prop.property_notes, s["value"]))

    # ------------------------------------------------------------------
    # Images (up to 2 per row)
    # ------------------------------------------------------------------
    if images:
        story.append(Spacer(1, 10))
        story.append(Paragraph("PROPERTY IMAGES", s["section"]))
        img_pairs = [images[i:i+2] for i in range(0, len(images), 2)]
        for pair in img_pairs:
            row_cells = []
            for label, raw in pair:
                try:
                    pil = PILImage.open(io.BytesIO(raw))
                    pil.thumbnail((320, 240))
                    buf = io.BytesIO()
                    pil.convert("RGB").save(buf, format="JPEG", quality=80)
                    buf.seek(0)
                    img_obj = RLImage(buf, width=W * 0.44, height=W * 0.44 * (pil.height / pil.width))
                    row_cells.append(
                        Table([[img_obj], [Paragraph(label, s["small"])]],
                              colWidths=[W * 0.46])
                    )
                except Exception:
                    row_cells.append(Paragraph(f"[{label}]", s["small"]))
            while len(row_cells) < 2:
                row_cells.append(Paragraph("", s["value"]))
            img_row = Table([row_cells], colWidths=[W * 0.5, W * 0.5])
            story.append(img_row)
            story.append(Spacer(1, 6))

    # ------------------------------------------------------------------
    # Signature block
    # ------------------------------------------------------------------
    story.append(Spacer(1, 14))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MED_GRAY))
    story.append(Spacer(1, 8))
    sig_data = [
        [Paragraph("Measured By", s["centered"]),
         Paragraph("Date", s["centered"]),
         Paragraph("Verified By", s["centered"]),
         Paragraph("Date", s["centered"])],
        [HRFlowable(width="100%", thickness=0.75, color=DARK),
         HRFlowable(width="100%", thickness=0.75, color=DARK),
         HRFlowable(width="100%", thickness=0.75, color=DARK),
         HRFlowable(width="100%", thickness=0.75, color=DARK)],
        [Paragraph(" ", s["value"]), Paragraph(" ", s["value"]),
         Paragraph(" ", s["value"]), Paragraph(" ", s["value"])],
    ]
    sig_table = Table(sig_data, colWidths=[W * 0.32, W * 0.16, W * 0.32, W * 0.16],
                      rowHeights=[14, 8, 14])
    sig_table.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
    ]))
    story.append(KeepTogether(sig_table))

    doc.build(story)
    return buffer.getvalue()
