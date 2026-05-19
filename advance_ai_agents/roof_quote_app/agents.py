import os
import json
import re
import uuid
import base64
import math
from datetime import date, timedelta
from typing import Optional

from agno.agent import Agent
from agno.models.anthropic import Claude
from dotenv import load_dotenv
from pydantic import ValidationError

from models import (
    CustomerInfo, MaterialOption, QuoteLineItem,
    RoofMeasurement, RoofQuote, Property,
)
from pricing_data import (
    ACCESSORIES, COMPLEXITY_FACTORS, MATERIAL_OPTIONS,
    PITCH_MULTIPLIERS, REGIONAL_LABOR_MULTIPLIERS,
    STANDARD_TERMS, WASTE_FACTORS,
)

load_dotenv()


def _extract_json(text: str) -> dict:
    """Pull the first JSON object or array from an LLM response string."""
    match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\}|\[[\s\S]*?\])\s*```", text)
    if match:
        return json.loads(match.group(1))
    match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
    if match:
        return json.loads(match.group(1))
    raise ValueError(f"No JSON found in response:\n{text[:500]}")


def _make_measurement_agent() -> Agent:
    return Agent(
        name="Roof Measurement Agent",
        model=Claude(id="claude-sonnet-4-6", api_key=os.getenv("ANTHROPIC_API_KEY")),
        markdown=False,
        description=(
            "You are a professional roofing estimator with 20 years of experience. "
            "You extract precise roof measurements from aerial/overhead images."
        ),
        instructions=(
            "Analyse this aerial or overhead roof image carefully and extract detailed measurements.\n\n"
            "Step 1 — Identify roof features:\n"
            "- Count all distinct roof planes/facets\n"
            "- Identify ridge lines, hip lines, valley lines, eave lines\n"
            "- Note any penetrations (chimneys, skylights, vents, dormers)\n"
            "- Determine number of stories from image context\n\n"
            "Step 2 — Estimate dimensions:\n"
            "- Estimate total footprint area in sq ft (use visible scale cues: windows ~3x5ft, "
            "doors ~3x7ft, cars ~6x15ft, standard rooms ~10-15ft wide)\n"
            "- Determine pitch from shadow angles and vertical rise vs horizontal span\n"
            "- Compute slope-adjusted total squares = (footprint sq ft / 100) × pitch_multiplier\n"
            "- Estimate linear footage of each feature type\n\n"
            "Step 3 — Assess complexity:\n"
            "- Simple: 1-2 planes, basic gable or shed (waste 10%)\n"
            "- Moderate: 3-5 planes, hip or L-shape (waste 13%)\n"
            "- Complex: 6+ planes, dormers, multiple valleys (waste 17%)\n"
            "- Very Complex: many intersections, skylights, steep pitch (waste 20%)\n\n"
            "Return ONLY a JSON object with these exact keys (no other text):\n"
            "{\n"
            '  "total_area_sqft": <number>,\n'
            '  "total_squares": <number — slope adjusted>,\n'
            '  "pitch": <string like "6/12">,\n'
            '  "pitch_multiplier": <number>,\n'
            '  "complexity": <"Simple"|"Moderate"|"Complex"|"Very Complex">,\n'
            '  "complexity_factor": <number>,\n'
            '  "waste_factor_pct": <decimal like 0.13>,\n'
            '  "perimeter_lf": <number>,\n'
            '  "ridges_lf": <number>,\n'
            '  "valleys_lf": <number>,\n'
            '  "hips_lf": <number>,\n'
            '  "eaves_lf": <number>,\n'
            '  "number_of_stories": <integer>,\n'
            '  "layers_existing": <integer, default 1>,\n'
            '  "ai_confidence": <"High"|"Medium"|"Low">,\n'
            '  "notes": <string — describe what you see and any uncertainties>\n'
            "}"
        ),
    )


def _make_estimator_agent() -> Agent:
    return Agent(
        name="Material Estimator Agent",
        model=Claude(id="claude-haiku-4-5-20251001", api_key=os.getenv("ANTHROPIC_API_KEY")),
        markdown=False,
        description="Roofing materials calculator that produces itemised quote line items.",
        instructions=(
            "Given JSON inputs for roof_measurement, material, accessories, and regional_labor_multiplier:\n"
            "1. Compute adjusted_squares = total_squares × pitch_multiplier × (1 + waste_factor_pct).\n"
            "2. Apply complexity_factor × regional_labor_multiplier to ALL labor unit prices.\n"
            "3. Generate line items in order:\n"
            "   a. Primary roofing material (category: Materials)\n"
            "   b. Synthetic underlayment (category: Materials)\n"
            "   c. Ice & water shield — 2 squares at eaves (category: Materials)\n"
            "   d. Starter strip — perimeter_lf (category: Materials)\n"
            "   e. Drip edge — perimeter_lf (category: Materials)\n"
            "   f. Ridge cap — ridges_lf + hips_lf (category: Materials)\n"
            "   g. Tear-off & disposal — only if layers_existing > 0, "
            "qty = total_squares × layers_existing (category: Disposal)\n"
            "   h. Labor — installation (category: Labor)\n"
            "   i. Permit & cleanup flat fee (category: Other)\n"
            "4. Return ONLY a JSON array of objects with keys: "
            "category, description, quantity, unit, unit_price, total.\n"
            "5. Round all monetary values to 2 decimal places."
        ),
    )


def _make_scope_agent() -> Agent:
    return Agent(
        name="Quote Composer Agent",
        model=Claude(id="claude-haiku-4-5-20251001", api_key=os.getenv("ANTHROPIC_API_KEY")),
        markdown=False,
        description="Writes professional scope-of-work paragraphs for roofing quotes.",
        instructions=(
            "Write a 2–3 sentence professional scope-of-work paragraph for a roofing project. "
            "Be specific: mention the square footage, material type, tearoff layers if applicable, "
            "pitch, complexity, and notable features (valleys, hips, dormers). "
            "Return only the plain text paragraph."
        ),
    )


# ------------------------------------------------------------------
# Public API: measurement extraction from image
# ------------------------------------------------------------------

def analyse_roof_image(image_bytes: bytes) -> RoofMeasurement:
    """Run Claude vision analysis on a roof image and return structured measurements."""
    from agno.media import Image as AgnoImage
    import io as _io
    from PIL import Image as PILImage

    img = PILImage.open(_io.BytesIO(image_bytes))
    if img.width > 1200:
        ratio = 1200 / img.width
        img = img.resize((1200, int(img.height * ratio)))
    buf = _io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=88)
    b64 = base64.b64encode(buf.getvalue()).decode()

    agent = _make_measurement_agent()
    agno_img = AgnoImage(base64_data=b64, media_type="image/jpeg")
    resp = agent.run(
        "Analyse this roof image and return measurements as a JSON object.",
        images=[agno_img],
    )
    return _parse_measurement(resp.content, "image_upload")


def analyse_multiple_images(images: list[bytes]) -> RoofMeasurement:
    """Analyse multiple roof images and return a consolidated measurement."""
    if not images:
        return _default_measurement("manual_input")
    if len(images) == 1:
        return analyse_roof_image(images[0])

    # Analyse the largest/best image — pick the one with most pixels
    best = max(images, key=lambda b: len(b))
    return analyse_roof_image(best)


def estimate_from_address(address: str) -> RoofMeasurement:
    """Use LLM to estimate roof dimensions from address (no satellite data)."""
    agent = _make_measurement_agent()
    prompt = (
        f"Estimate roof measurements for a typical single-family residential home at: {address}. "
        "Without satellite imagery, use conservative residential defaults: "
        "assume a moderate complexity hip/gable roof, 6/12 pitch, approximately 1,800–2,200 sq ft footprint. "
        "Set ai_confidence to 'Low' and note in the 'notes' field that these are estimates without imagery."
    )
    resp = agent.run(prompt)
    return _parse_measurement(resp.content, "address_lookup")


def manual_to_measurement(m: dict) -> RoofMeasurement:
    """Convert a form dict (from manual entry or UI) to a RoofMeasurement."""
    pitch = m.get("pitch", "6/12")
    pitch_multiplier = PITCH_MULTIPLIERS.get(pitch, 1.118)
    complexity = m.get("complexity", "Moderate")
    area_sqft = float(m.get("total_area_sqft", 0) or m.get("area_sqft", 2000))
    total_squares = round((area_sqft / 100) * pitch_multiplier, 2)
    return RoofMeasurement(
        total_area_sqft=area_sqft,
        total_squares=total_squares,
        pitch=pitch,
        pitch_multiplier=pitch_multiplier,
        complexity=complexity,
        complexity_factor=COMPLEXITY_FACTORS.get(complexity, 1.15),
        waste_factor_pct=WASTE_FACTORS.get(complexity, 0.13),
        perimeter_lf=float(m.get("perimeter_lf", 0)),
        ridges_lf=float(m.get("ridges_lf", 0)),
        valleys_lf=float(m.get("valleys_lf", 0)),
        hips_lf=float(m.get("hips_lf", 0)),
        eaves_lf=float(m.get("eaves_lf", 0)),
        number_of_stories=int(m.get("number_of_stories", 1)),
        layers_existing=int(m.get("layers_existing", 1)),
        analysis_source=m.get("analysis_source", "manual_input"),
        ai_confidence=m.get("ai_confidence", ""),
        notes=m.get("notes", ""),
    )


# ------------------------------------------------------------------
# Quote generation (used after property + measurements are saved)
# ------------------------------------------------------------------

def generate_quote(
    prop: Property,
    material_slug: str,
    region: str,
    company_info: dict,
    tax_rate: float = 0.0,
) -> RoofQuote:
    m = prop.roof_measurement
    material = MATERIAL_OPTIONS[material_slug]
    regional_multiplier = REGIONAL_LABOR_MULTIPLIERS.get(region, 1.0)

    line_items = _estimate_materials(m, material, regional_multiplier)
    scope = _compose_scope(m, material)

    subtotal = round(sum(i.total for i in line_items), 2)
    tax_amount = round(subtotal * tax_rate, 2)
    total = round(subtotal + tax_amount, 2)

    today = date.today()
    return RoofQuote(
        quote_id=f"RQ-{today.strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}",
        property_id=prop.property_id,
        quote_date=today.strftime("%B %d, %Y"),
        validity_date=(today + timedelta(days=30)).strftime("%B %d, %Y"),
        customer=CustomerInfo(
            name=prop.owner_name,
            address=prop.street_address,
            city_state_zip=f"{prop.city}, {prop.state} {prop.zip_code}".strip(", "),
            phone=prop.owner_phone,
            email=prop.owner_email,
        ),
        roof_measurement=m,
        selected_material=material,
        region=region,
        regional_labor_multiplier=regional_multiplier,
        line_items=line_items,
        subtotal=subtotal,
        tax_rate=tax_rate,
        tax_amount=tax_amount,
        total=total,
        scope_of_work=scope,
        terms_and_conditions=STANDARD_TERMS,
        company_name=company_info.get("name", ""),
        company_phone=company_info.get("phone", ""),
        company_license=company_info.get("license", ""),
    )


# ------------------------------------------------------------------
# Private helpers
# ------------------------------------------------------------------

def _parse_measurement(content: str, source: str) -> RoofMeasurement:
    try:
        data = _extract_json(content)
        data.setdefault("analysis_source", source)
        pitch = data.get("pitch", "6/12")
        if not data.get("pitch_multiplier"):
            data["pitch_multiplier"] = PITCH_MULTIPLIERS.get(pitch, 1.118)
        complexity = data.get("complexity", "Moderate")
        if not data.get("complexity_factor"):
            data["complexity_factor"] = COMPLEXITY_FACTORS.get(complexity, 1.15)
        if not data.get("waste_factor_pct"):
            data["waste_factor_pct"] = WASTE_FACTORS.get(complexity, 0.13)
        # Derive total_squares from area if not provided
        if not data.get("total_squares") and data.get("total_area_sqft"):
            pm = data.get("pitch_multiplier", 1.118)
            data["total_squares"] = round(data["total_area_sqft"] / 100 * pm, 2)
        # Derive area from squares if not provided
        if not data.get("total_area_sqft") and data.get("total_squares"):
            pm = data.get("pitch_multiplier", 1.118)
            data["total_area_sqft"] = round(data["total_squares"] * 100 / pm, 0)
        return RoofMeasurement(**data)
    except Exception as exc:
        return _default_measurement(source, note=f"AI parse error: {str(exc)[:120]}")


def _default_measurement(source: str, note: str = "") -> RoofMeasurement:
    return RoofMeasurement(
        total_area_sqft=2000.0,
        total_squares=22.36,
        pitch="6/12", pitch_multiplier=1.118,
        complexity="Moderate", complexity_factor=1.15,
        waste_factor_pct=0.13,
        analysis_source=source,
        ai_confidence="Low",
        notes=note or "Default values — please review and edit.",
    )


def _estimate_materials(
    m: RoofMeasurement, material: MaterialOption, regional_multiplier: float
) -> list[QuoteLineItem]:
    adjusted_sq = round(m.total_squares * m.pitch_multiplier * (1 + m.waste_factor_pct), 2)
    labor_mult = m.complexity_factor * regional_multiplier

    prompt = json.dumps({
        "roof_measurement": m.model_dump(),
        "material": material.model_dump(),
        "adjusted_squares": adjusted_sq,
        "labor_multiplier": round(labor_mult, 4),
        "accessories": ACCESSORIES,
    })
    try:
        agent = _make_estimator_agent()
        resp = agent.run(prompt)
        raw = _extract_json(resp.content)
        items_data = raw if isinstance(raw, list) else raw.get("line_items", [])
        return [QuoteLineItem(**item) for item in items_data]
    except Exception:
        return _fallback_line_items(m, material, adjusted_sq, labor_mult)


def _fallback_line_items(m, material, adjusted_sq, labor_mult) -> list[QuoteLineItem]:
    items = []

    def add(cat, desc, qty, unit, unit_price):
        items.append(QuoteLineItem(
            category=cat, description=desc,
            quantity=round(qty, 2), unit=unit,
            unit_price=round(unit_price, 2),
            total=round(qty * unit_price, 2),
        ))

    add("Materials", material.name, adjusted_sq, "sq", material.material_cost_per_square)
    add("Materials", "Synthetic Underlayment", adjusted_sq, "sq", ACCESSORIES["synthetic_underlayment_per_sq"])
    add("Materials", "Ice & Water Shield (eaves)", 2.0, "sq", ACCESSORIES["ice_water_shield_per_sq"])
    perim = m.perimeter_lf or adjusted_sq * 4
    add("Materials", "Starter Strip", perim, "LF", ACCESSORIES["starter_strip_per_lf"])
    add("Materials", "Drip Edge", perim, "LF", ACCESSORIES["drip_edge_per_lf"])
    ridge_hip = (m.ridges_lf or 0) + (m.hips_lf or 0) or adjusted_sq * 1.5
    add("Materials", "Ridge Cap", ridge_hip, "LF", ACCESSORIES["ridge_cap_per_lf"])
    if m.layers_existing > 0:
        add("Disposal", "Tear-Off & Disposal", m.total_squares * m.layers_existing, "sq",
            material.tearoff_cost_per_square)
    add("Labor", "Labor — Roofing Installation", adjusted_sq, "sq",
        round(material.labor_cost_per_square * labor_mult, 2))
    add("Other", "Permit & Debris Removal", 1.0, "job", ACCESSORIES["permit_flat_fee"])
    return items


def _compose_scope(m: RoofMeasurement, material: MaterialOption) -> str:
    try:
        agent = _make_scope_agent()
        prompt = (
            f"Roof: {m.total_squares:.1f} squares ({m.total_area_sqft:,.0f} sq ft footprint), "
            f"{m.pitch} pitch, {m.complexity} complexity. "
            f"Material: {material.name}. Tearoff: {m.layers_existing} layers. "
            f"Ridges: {m.ridges_lf:.0f} LF, Valleys: {m.valleys_lf:.0f} LF."
        )
        resp = agent.run(prompt)
        return resp.content.strip() if resp.content else ""
    except Exception:
        return ""
