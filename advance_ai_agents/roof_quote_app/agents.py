import os
import json
import re
import uuid
import base64
from datetime import date, timedelta
from typing import Optional

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.nebius import Nebius
from dotenv import load_dotenv
from pydantic import ValidationError

from models import (
    CustomerInfo, MaterialOption, QuoteLineItem,
    RoofMeasurement, RoofQuote,
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


def _make_analysis_agent() -> Agent:
    return Agent(
        name="Roof Analysis Agent",
        model=Claude(id="claude-sonnet-4-6", api_key=os.getenv("ANTHROPIC_API_KEY")),
        markdown=False,
        description=(
            "You are a licensed roofing estimator AI. You analyse roof images or "
            "interpret provided measurements to produce structured roof data."
        ),
        instructions=(
            "When analysing a roof image:\n"
            "1. Identify all roof planes and estimate their dimensions.\n"
            "2. Determine the dominant pitch (rise per 12 inches of run) by examining angles.\n"
            "3. Count and estimate linear footage of ridges, valleys, hips, and eaves.\n"
            "4. Assess complexity: Simple (≤2 planes/gable), Moderate (hip or L-shape), "
            "Complex (dormers, multiple breaks), Very Complex (many hips/valleys/skylights).\n"
            "5. Estimate total squares (1 square = 100 sq ft). A 2,000 sq ft footprint with "
            "moderate pitch is typically ~22–25 squares.\n"
            "6. Return ONLY a JSON object with keys: total_squares, pitch, pitch_multiplier, "
            "complexity, complexity_factor, waste_factor_pct, perimeter_lf, ridges_lf, "
            "valleys_lf, hips_lf, eaves_lf, number_of_stories, layers_existing, "
            "analysis_source, analysis_notes.\n"
            "7. Do not add explanatory text outside the JSON block. Use double quotes."
        ),
    )


def _make_estimator_agent() -> Agent:
    return Agent(
        name="Material Estimator Agent",
        model=Nebius(
            id="meta-llama/Llama-3.3-70B-Instruct",
            api_key=os.getenv("NEBIUS_API_KEY"),
        ),
        markdown=False,
        description=(
            "You are a roofing materials calculator. Given roof measurements and a selected "
            "material, you compute a complete list of itemised quote line items."
        ),
        instructions=(
            "Given JSON inputs for roof_measurement, material, accessories, and regional_labor_multiplier:\n"
            "1. Compute adjusted_squares = total_squares × pitch_multiplier × (1 + waste_factor_pct).\n"
            "2. Apply complexity_factor to ALL labor unit prices.\n"
            "3. Apply regional_labor_multiplier to ALL labor unit prices.\n"
            "4. Generate these line items in order:\n"
            "   a. Primary roofing material (category: Materials)\n"
            "   b. Synthetic underlayment (category: Materials)\n"
            "   c. Ice & water shield — first 2 squares at eaves (category: Materials)\n"
            "   d. Starter strip — use perimeter_lf (category: Materials)\n"
            "   e. Drip edge — use perimeter_lf (category: Materials)\n"
            "   f. Ridge cap — use ridges_lf + hips_lf (category: Materials)\n"
            "   g. Tear-off & disposal — only if layers_existing > 0; "
            "qty = total_squares × layers_existing (category: Disposal)\n"
            "   h. Labor — installation (category: Labor)\n"
            "   i. Permit & cleanup flat fee (category: Other)\n"
            "5. Return ONLY a JSON array of objects each with keys: "
            "category, description, quantity, unit, unit_price, total.\n"
            "6. All monetary values rounded to 2 decimal places. Use double quotes."
        ),
    )


def _make_composer_agent() -> Agent:
    return Agent(
        name="Quote Composer Agent",
        model=Nebius(
            id="meta-llama/Llama-3.3-70B-Instruct",
            api_key=os.getenv("NEBIUS_API_KEY"),
        ),
        markdown=False,
        description=(
            "You are a professional roofing quote specialist. You write a concise, "
            "professional scope-of-work paragraph summarising the job."
        ),
        instructions=(
            "Given the roof measurements and material details, write a 2–3 sentence "
            "professional scope-of-work paragraph describing what the roofing project entails. "
            "Be specific: mention square footage, material type, tearoff if applicable, "
            "and any notable features (valleys, hips, pitch). "
            "Return ONLY the plain text paragraph, no JSON, no headings."
        ),
    )


class RoofQuoteWorkflow:
    """
    Three-stage multi-agent workflow:
    1. roof_analysis_agent  — interprets image / address / manual dims → RoofMeasurement
    2. material_estimator_agent — calculates quantities and line items
    3. quote_composer_agent — scope-of-work prose
    """

    def __init__(self):
        self.roof_analysis_agent = _make_analysis_agent()
        self.material_estimator_agent = _make_estimator_agent()
        self.quote_composer_agent = _make_composer_agent()

    def run(
        self,
        input_mode: str,
        material_slug: str,
        region: str,
        customer_info: dict,
        company_info: dict,
        tax_rate: float = 0.0,
        image_bytes: Optional[bytes] = None,
        address: Optional[str] = None,
        manual_measurements: Optional[dict] = None,
    ) -> RoofQuote:
        # ----------------------------------------------------------------
        # Step 1: Roof Analysis
        # ----------------------------------------------------------------
        measurement = self._analyse_roof(
            input_mode, image_bytes, address, manual_measurements
        )

        # ----------------------------------------------------------------
        # Step 2: Material Estimation
        # ----------------------------------------------------------------
        material = MATERIAL_OPTIONS[material_slug]
        regional_multiplier = REGIONAL_LABOR_MULTIPLIERS.get(region, 1.0)
        line_items = self._estimate_materials(measurement, material, regional_multiplier)

        # ----------------------------------------------------------------
        # Step 3: Scope of Work (quick prose description)
        # ----------------------------------------------------------------
        scope = self._compose_scope(measurement, material)

        # ----------------------------------------------------------------
        # Step 4: Assemble quote
        # ----------------------------------------------------------------
        subtotal = round(sum(i.total for i in line_items), 2)
        tax_amount = round(subtotal * tax_rate, 2)
        total = round(subtotal + tax_amount, 2)

        today = date.today()
        quote = RoofQuote(
            quote_id=f"RQ-{today.strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}",
            quote_date=today.strftime("%B %d, %Y"),
            validity_date=(today + timedelta(days=30)).strftime("%B %d, %Y"),
            customer=CustomerInfo(**customer_info),
            roof_measurement=measurement,
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
        return quote

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _analyse_roof(
        self,
        input_mode: str,
        image_bytes: Optional[bytes],
        address: Optional[str],
        manual_measurements: Optional[dict],
    ) -> RoofMeasurement:
        if input_mode == "manual" and manual_measurements:
            return self._manual_to_measurement(manual_measurements)

        if input_mode == "image" and image_bytes:
            return self._vision_analysis(image_bytes)

        # address fallback — estimate from address string
        prompt = (
            f"Estimate roof measurements for a typical single-family residential home at: {address}. "
            "Assume a moderate complexity hip roof with 6/12 pitch and approximately 20 squares. "
            "Return the JSON with analysis_source set to 'address_lookup' and include a note that "
            "these are estimates without satellite imagery."
        )
        resp = self.roof_analysis_agent.run(prompt)
        return self._parse_measurement(resp.content, "address_lookup")

    def _vision_analysis(self, image_bytes: bytes) -> RoofMeasurement:
        from agno.media import Image as AgnoImage
        import io as _io
        from PIL import Image as PILImage

        # Resize to max 1024px wide to stay within vision token limits
        img = PILImage.open(_io.BytesIO(image_bytes))
        if img.width > 1024:
            ratio = 1024 / img.width
            img = img.resize((1024, int(img.height * ratio)))
        buf = _io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode()

        agno_img = AgnoImage(base64_data=b64, media_type="image/jpeg")
        prompt = (
            "Analyse this aerial or overhead roof image. "
            "Return only a JSON object with the required roof measurement fields."
        )
        resp = self.roof_analysis_agent.run(prompt, images=[agno_img])
        return self._parse_measurement(resp.content, "image_upload")

    def _manual_to_measurement(self, m: dict) -> RoofMeasurement:
        pitch = m.get("pitch", "6/12")
        pitch_multiplier = PITCH_MULTIPLIERS.get(pitch, 1.118)
        complexity = m.get("complexity", "Moderate")
        area_sqft = float(m.get("area_sqft", 2000))
        total_squares = round((area_sqft / 100) * pitch_multiplier, 2)
        return RoofMeasurement(
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
            analysis_source="manual_input",
            analysis_notes="",
        )

    def _parse_measurement(self, content: str, source: str) -> RoofMeasurement:
        try:
            data = _extract_json(content)
            data.setdefault("analysis_source", source)
            # Fill in lookup-table values if model returned raw strings
            pitch = data.get("pitch", "6/12")
            if "pitch_multiplier" not in data or data["pitch_multiplier"] == 0:
                data["pitch_multiplier"] = PITCH_MULTIPLIERS.get(pitch, 1.118)
            complexity = data.get("complexity", "Moderate")
            if "complexity_factor" not in data or data["complexity_factor"] == 0:
                data["complexity_factor"] = COMPLEXITY_FACTORS.get(complexity, 1.15)
            if "waste_factor_pct" not in data or data["waste_factor_pct"] == 0:
                data["waste_factor_pct"] = WASTE_FACTORS.get(complexity, 0.13)
            return RoofMeasurement(**data)
        except (ValueError, ValidationError, json.JSONDecodeError) as exc:
            # Fallback: return sensible defaults with error note
            return RoofMeasurement(
                total_squares=20.0,
                pitch="6/12",
                pitch_multiplier=1.118,
                complexity="Moderate",
                complexity_factor=1.15,
                waste_factor_pct=0.13,
                analysis_source=source,
                analysis_notes=f"AI parse error — using defaults. Detail: {str(exc)[:120]}",
            )

    def _estimate_materials(
        self,
        m: RoofMeasurement,
        material: MaterialOption,
        regional_multiplier: float,
    ) -> list[QuoteLineItem]:
        adjusted_sq = round(m.total_squares * m.pitch_multiplier * (1 + m.waste_factor_pct), 2)
        labor_mult = m.complexity_factor * regional_multiplier

        prompt = json.dumps({
            "roof_measurement": m.model_dump(),
            "material": material.model_dump(),
            "adjusted_squares": adjusted_sq,
            "labor_multiplier": round(labor_mult, 4),
            "accessories": ACCESSORIES,
            "instructions": (
                "Compute line items for this roofing job. "
                "Return a JSON array of line item objects."
            ),
        })
        resp = self.material_estimator_agent.run(prompt)

        try:
            raw = _extract_json(resp.content)
            items_data = raw if isinstance(raw, list) else raw.get("line_items", [])
            return [QuoteLineItem(**item) for item in items_data]
        except (ValueError, ValidationError, json.JSONDecodeError):
            # Build line items directly as fallback
            return self._fallback_line_items(m, material, adjusted_sq, labor_mult)

    def _fallback_line_items(
        self,
        m: RoofMeasurement,
        material: MaterialOption,
        adjusted_sq: float,
        labor_mult: float,
    ) -> list[QuoteLineItem]:
        items = []

        def add(category, desc, qty, unit, unit_price):
            items.append(QuoteLineItem(
                category=category, description=desc,
                quantity=round(qty, 2), unit=unit,
                unit_price=round(unit_price, 2),
                total=round(qty * unit_price, 2),
            ))

        add("Materials", material.name, adjusted_sq, "sq", material.material_cost_per_square)
        add("Materials", "Synthetic Underlayment", adjusted_sq, "sq", ACCESSORIES["synthetic_underlayment_per_sq"])
        add("Materials", "Ice & Water Shield (eaves)", 2.0, "sq", ACCESSORIES["ice_water_shield_per_sq"])
        add("Materials", "Starter Strip", m.perimeter_lf or adjusted_sq * 4, "LF", ACCESSORIES["starter_strip_per_lf"])
        add("Materials", "Drip Edge", m.perimeter_lf or adjusted_sq * 4, "LF", ACCESSORIES["drip_edge_per_lf"])
        ridge_hip_lf = (m.ridges_lf or 0) + (m.hips_lf or 0) or adjusted_sq * 1.5
        add("Materials", "Ridge Cap", ridge_hip_lf, "LF", ACCESSORIES["ridge_cap_per_lf"])
        if m.layers_existing > 0:
            add("Disposal", "Tear-Off & Disposal", m.total_squares * m.layers_existing, "sq",
                material.tearoff_cost_per_square)
        add("Labor", "Labor — Roofing Installation", adjusted_sq, "sq",
            round(material.labor_cost_per_square * labor_mult, 2))
        add("Other", "Permit & Debris Removal", 1.0, "job", ACCESSORIES["permit_flat_fee"])
        return items

    def _compose_scope(self, m: RoofMeasurement, material: MaterialOption) -> str:
        prompt = (
            f"Roof: {m.total_squares:.1f} squares, {m.pitch} pitch, {m.complexity} complexity. "
            f"Material: {material.name} ({material.warranty_years}-year warranty). "
            f"Tearoff layers: {m.layers_existing}. "
            f"Ridges: {m.ridges_lf:.0f} LF, Valleys: {m.valleys_lf:.0f} LF, Hips: {m.hips_lf:.0f} LF."
        )
        resp = self.quote_composer_agent.run(prompt)
        return resp.content.strip() if resp.content else ""
