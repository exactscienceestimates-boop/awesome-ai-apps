import io
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether,
)
from models import RoofQuote

# Brand colours
DARK = colors.HexColor("#1A2332")
ACCENT = colors.HexColor("#E74C3C")
MID = colors.HexColor("#2C3E50")
LIGHT_GRAY = colors.HexColor("#F2F3F4")
MED_GRAY = colors.HexColor("#BDC3C7")
WHITE = colors.white


def _styles():
    base = getSampleStyleSheet()
    s = {
        "h_company": ParagraphStyle("h_company", parent=base["Normal"],
            fontSize=18, fontName="Helvetica-Bold", textColor=WHITE),
        "h_sub": ParagraphStyle("h_sub", parent=base["Normal"],
            fontSize=9, fontName="Helvetica", textColor=MED_GRAY),
        "section_title": ParagraphStyle("section_title", parent=base["Normal"],
            fontSize=10, fontName="Helvetica-Bold", textColor=MID,
            spaceAfter=4),
        "body": ParagraphStyle("body", parent=base["Normal"],
            fontSize=9, fontName="Helvetica", leading=13),
        "body_bold": ParagraphStyle("body_bold", parent=base["Normal"],
            fontSize=9, fontName="Helvetica-Bold"),
        "small": ParagraphStyle("small", parent=base["Normal"],
            fontSize=7.5, fontName="Helvetica", leading=11, textColor=colors.HexColor("#555555")),
        "total_label": ParagraphStyle("total_label", parent=base["Normal"],
            fontSize=10, fontName="Helvetica-Bold", alignment=TA_RIGHT),
        "total_value": ParagraphStyle("total_value", parent=base["Normal"],
            fontSize=10, fontName="Helvetica-Bold", alignment=TA_RIGHT),
        "grand_total_label": ParagraphStyle("grand_total_label", parent=base["Normal"],
            fontSize=13, fontName="Helvetica-Bold", alignment=TA_RIGHT, textColor=ACCENT),
        "grand_total_value": ParagraphStyle("grand_total_value", parent=base["Normal"],
            fontSize=13, fontName="Helvetica-Bold", alignment=TA_RIGHT, textColor=ACCENT),
        "terms": ParagraphStyle("terms", parent=base["Normal"],
            fontSize=7.5, fontName="Helvetica", leading=11, textColor=colors.HexColor("#555555")),
        "centered": ParagraphStyle("centered", parent=base["Normal"],
            fontSize=9, fontName="Helvetica", alignment=TA_CENTER),
    }
    return s


def generate_quote_pdf(
    quote: RoofQuote,
    company_name: str = "Your Roofing Company",
    company_phone: str = "",
    company_license: str = "",
) -> bytes:
    """Build and return a branded PDF quote as raw bytes."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.65 * inch,
        leftMargin=0.65 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.65 * inch,
        title=f"Roof Quote {quote.quote_id}",
    )

    s = _styles()
    W = doc.width
    story = []

    # ------------------------------------------------------------------
    # Header bar
    # ------------------------------------------------------------------
    company_display = quote.company_name or company_name
    phone_display = quote.company_phone or company_phone
    license_display = quote.company_license or company_license

    header_data = [[
        Paragraph(company_display, s["h_company"]),
        Table(
            [
                [Paragraph(f"ROOFING QUOTE", ParagraphStyle("qh", fontSize=10,
                    fontName="Helvetica-Bold", textColor=WHITE, alignment=TA_RIGHT))],
                [Paragraph(f"#{quote.quote_id}", ParagraphStyle("qid", fontSize=8,
                    fontName="Helvetica", textColor=MED_GRAY, alignment=TA_RIGHT))],
                [Paragraph(f"Date: {quote.quote_date}", ParagraphStyle("qd", fontSize=8,
                    fontName="Helvetica", textColor=MED_GRAY, alignment=TA_RIGHT))],
                [Paragraph(f"Valid Until: {quote.validity_date}", ParagraphStyle("qv", fontSize=8,
                    fontName="Helvetica", textColor=MED_GRAY, alignment=TA_RIGHT))],
            ],
            colWidths=[W * 0.35],
        ),
    ]]
    header_table = Table(header_data, colWidths=[W * 0.65, W * 0.35])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), DARK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 14),
        ("RIGHTPADDING", (-1, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
    ]))
    story.append(header_table)

    if phone_display or license_display:
        contact_parts = []
        if phone_display:
            contact_parts.append(f"Tel: {phone_display}")
        if license_display:
            contact_parts.append(f"Lic: {license_display}")
        story.append(Paragraph("  |  ".join(contact_parts), s["small"]))
    story.append(Spacer(1, 10))

    # ------------------------------------------------------------------
    # Customer + Property info side by side
    # ------------------------------------------------------------------
    c = quote.customer
    customer_block = [
        [Paragraph("PREPARED FOR", s["section_title"]), Paragraph("PROPERTY ADDRESS", s["section_title"])],
        [Paragraph(c.name or "—", s["body_bold"]), Paragraph(c.address or "—", s["body_bold"])],
        [Paragraph(c.phone or "", s["body"]), Paragraph(c.city_state_zip or "", s["body"])],
        [Paragraph(c.email or "", s["body"]), Paragraph("", s["body"])],
    ]
    ct = Table(customer_block, colWidths=[W * 0.5, W * 0.5])
    ct.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT_GRAY),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, MED_GRAY),
        ("BOX", (0, 0), (-1, -1), 0.5, MED_GRAY),
    ]))
    story.append(ct)
    story.append(Spacer(1, 8))

    # ------------------------------------------------------------------
    # Roof Measurement Summary
    # ------------------------------------------------------------------
    story.append(Paragraph("ROOF MEASUREMENTS", s["section_title"]))
    m = quote.roof_measurement
    meas_data = [
        ["Total Squares", f"{m.total_squares:.1f} sq",
         "Pitch", m.pitch,
         "Complexity", m.complexity],
        ["Stories", str(m.number_of_stories),
         "Tearoff Layers", str(m.layers_existing),
         "Waste Factor", f"{m.waste_factor_pct * 100:.0f}%"],
        ["Perimeter", f"{m.perimeter_lf:.0f} LF",
         "Ridges", f"{m.ridges_lf:.0f} LF",
         "Valleys", f"{m.valleys_lf:.0f} LF"],
    ]
    mt = Table(meas_data, colWidths=[W * 0.16, W * 0.16, W * 0.16, W * 0.16, W * 0.18, W * 0.18])
    mt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), LIGHT_GRAY),
        ("BACKGROUND", (2, 0), (2, -1), LIGHT_GRAY),
        ("BACKGROUND", (4, 0), (4, -1), LIGHT_GRAY),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTNAME", (4, 0), (4, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("BOX", (0, 0), (-1, -1), 0.5, MED_GRAY),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, MED_GRAY),
    ]))
    story.append(mt)
    if m.analysis_notes:
        story.append(Spacer(1, 3))
        story.append(Paragraph(f"Analysis note: {m.analysis_notes}", s["small"]))
    story.append(Spacer(1, 10))

    # ------------------------------------------------------------------
    # Line Items Table
    # ------------------------------------------------------------------
    story.append(Paragraph("SCOPE & PRICING", s["section_title"]))
    col_w = [W * 0.38, W * 0.10, W * 0.12, W * 0.16, W * 0.14, W * 0.10]
    li_header = [
        Paragraph("Description", s["body_bold"]),
        Paragraph("Category", s["body_bold"]),
        Paragraph("Qty", s["body_bold"]),
        Paragraph("Unit", s["body_bold"]),
        Paragraph("Unit Price", s["body_bold"]),
        Paragraph("Total", s["body_bold"]),
    ]
    li_rows = [li_header]
    for i, item in enumerate(quote.line_items):
        row_style = LIGHT_GRAY if i % 2 == 0 else WHITE
        li_rows.append([
            Paragraph(item.description, s["body"]),
            Paragraph(item.category, s["small"]),
            Paragraph(f"{item.quantity:.2f}", s["body"]),
            Paragraph(item.unit, s["body"]),
            Paragraph(f"${item.unit_price:,.2f}", s["body"]),
            Paragraph(f"${item.total:,.2f}", s["body"]),
        ])

    li_table = Table(li_rows, colWidths=col_w, repeatRows=1)
    row_backgrounds = [("BACKGROUND", (0, 0), (-1, 0), MID),
                       ("TEXTCOLOR", (0, 0), (-1, 0), WHITE)]
    for i in range(1, len(li_rows)):
        bg = LIGHT_GRAY if (i - 1) % 2 == 0 else WHITE
        row_backgrounds.append(("BACKGROUND", (0, i), (-1, i), bg))

    li_table.setStyle(TableStyle(row_backgrounds + [
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("BOX", (0, 0), (-1, -1), 0.5, MED_GRAY),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, MED_GRAY),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
    ]))
    story.append(li_table)
    story.append(Spacer(1, 10))

    # ------------------------------------------------------------------
    # Totals summary
    # ------------------------------------------------------------------
    totals_data = [
        [Paragraph("Subtotal:", s["total_label"]), Paragraph(f"${quote.subtotal:,.2f}", s["total_value"])],
        [Paragraph(f"Tax ({quote.tax_rate * 100:.1f}%):", s["total_label"]),
         Paragraph(f"${quote.tax_amount:,.2f}", s["total_value"])],
        [Paragraph("TOTAL:", s["grand_total_label"]), Paragraph(f"${quote.total:,.2f}", s["grand_total_value"])],
    ]
    totals_table = Table(totals_data, colWidths=[W * 0.78, W * 0.22])
    totals_table.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEABOVE", (0, 2), (-1, 2), 1.0, ACCENT),
        ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#FDEDEC")),
        ("BOX", (0, 0), (-1, -1), 0.5, MED_GRAY),
    ]))
    story.append(totals_table)
    story.append(Spacer(1, 10))

    # ------------------------------------------------------------------
    # Material details
    # ------------------------------------------------------------------
    mat = quote.selected_material
    story.append(Paragraph("SELECTED MATERIAL", s["section_title"]))
    mat_data = [
        [Paragraph("Product", s["body_bold"]),
         Paragraph("Warranty", s["body_bold"]),
         Paragraph("Est. Lifespan", s["body_bold"]),
         Paragraph("Description", s["body_bold"])],
        [Paragraph(mat.name, s["body"]),
         Paragraph(f"{mat.warranty_years} years", s["body"]),
         Paragraph(f"{mat.lifespan_years} years", s["body"]),
         Paragraph(mat.description, s["small"])],
    ]
    mat_table = Table(mat_data, colWidths=[W * 0.28, W * 0.13, W * 0.13, W * 0.46])
    mat_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT_GRAY),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("BOX", (0, 0), (-1, -1), 0.5, MED_GRAY),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, MED_GRAY),
    ]))
    story.append(mat_table)
    story.append(Spacer(1, 8))

    # ------------------------------------------------------------------
    # Scope of work
    # ------------------------------------------------------------------
    if quote.scope_of_work:
        story.append(Paragraph("SCOPE OF WORK", s["section_title"]))
        story.append(Paragraph(quote.scope_of_work, s["body"]))
        story.append(Spacer(1, 8))

    if quote.notes:
        story.append(Paragraph("NOTES", s["section_title"]))
        story.append(Paragraph(quote.notes, s["body"]))
        story.append(Spacer(1, 8))

    # ------------------------------------------------------------------
    # Terms & Conditions
    # ------------------------------------------------------------------
    story.append(HRFlowable(width="100%", thickness=0.5, color=MED_GRAY))
    story.append(Spacer(1, 6))
    story.append(Paragraph("TERMS & CONDITIONS", s["section_title"]))
    for line in quote.terms_and_conditions.split("\n"):
        if line.strip():
            story.append(Paragraph(line.strip(), s["terms"]))
    story.append(Spacer(1, 14))

    # ------------------------------------------------------------------
    # Signature block
    # ------------------------------------------------------------------
    sig_data = [
        [Paragraph("Customer Signature", s["centered"]),
         Paragraph("Date", s["centered"]),
         Paragraph("Contractor Signature", s["centered"]),
         Paragraph("Date", s["centered"])],
        [HRFlowable(width="100%", thickness=0.75, color=DARK),
         HRFlowable(width="100%", thickness=0.75, color=DARK),
         HRFlowable(width="100%", thickness=0.75, color=DARK),
         HRFlowable(width="100%", thickness=0.75, color=DARK)],
        [Paragraph(" ", s["body"]), Paragraph(" ", s["body"]),
         Paragraph(" ", s["body"]), Paragraph(" ", s["body"])],
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
