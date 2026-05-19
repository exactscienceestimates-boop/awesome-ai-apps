from models import MaterialOption

# ---------------------------------------------------------------------------
# Material options (costs per square = 100 sq ft, US 2024-2025 baseline)
# ---------------------------------------------------------------------------
MATERIAL_OPTIONS: dict[str, MaterialOption] = {
    "3tab_shingle": MaterialOption(
        name="3-Tab Shingle (20-Year)",
        slug="3tab_shingle",
        material_cost_per_square=85.0,
        labor_cost_per_square=65.0,
        tearoff_cost_per_square=45.0,
        warranty_years=20,
        lifespan_years=15,
        description="Economy asphalt shingle. Best for budget-conscious projects on low-slope roofs.",
    ),
    "architectural_shingle": MaterialOption(
        name="Architectural Shingle (30-Year)",
        slug="architectural_shingle",
        material_cost_per_square=125.0,
        labor_cost_per_square=75.0,
        tearoff_cost_per_square=45.0,
        warranty_years=30,
        lifespan_years=25,
        description="Dimensional laminate shingle. Most popular choice — great aesthetics and durability.",
    ),
    "premium_shingle": MaterialOption(
        name="Premium Architectural Shingle (50-Year)",
        slug="premium_shingle",
        material_cost_per_square=175.0,
        labor_cost_per_square=85.0,
        tearoff_cost_per_square=45.0,
        warranty_years=50,
        lifespan_years=40,
        description="Class 4 impact-resistant shingle. Top-tier protection with transferable warranty.",
    ),
    "metal_exposed_fastener": MaterialOption(
        name="Metal Roofing — Exposed Fastener",
        slug="metal_exposed_fastener",
        material_cost_per_square=220.0,
        labor_cost_per_square=150.0,
        tearoff_cost_per_square=55.0,
        warranty_years=40,
        lifespan_years=40,
        description="Corrugated or ribbed metal panels. Durable and cost-effective metal option.",
    ),
    "metal_standing_seam": MaterialOption(
        name="Metal Roofing — Standing Seam",
        slug="metal_standing_seam",
        material_cost_per_square=350.0,
        labor_cost_per_square=200.0,
        tearoff_cost_per_square=55.0,
        warranty_years=50,
        lifespan_years=50,
        description="Concealed fastener metal panels. Premium look, minimal maintenance, 50-year lifespan.",
    ),
    "concrete_tile": MaterialOption(
        name="Concrete Tile",
        slug="concrete_tile",
        material_cost_per_square=280.0,
        labor_cost_per_square=180.0,
        tearoff_cost_per_square=70.0,
        warranty_years=50,
        lifespan_years=50,
        description="Heavy-duty concrete tile. Excellent fire resistance, ideal for Mediterranean or Spanish styles.",
    ),
    "clay_tile": MaterialOption(
        name="Clay Tile",
        slug="clay_tile",
        material_cost_per_square=400.0,
        labor_cost_per_square=220.0,
        tearoff_cost_per_square=70.0,
        warranty_years=50,
        lifespan_years=100,
        description="Traditional clay tile. Extremely durable, premium aesthetic, last a century with proper care.",
    ),
}

# ---------------------------------------------------------------------------
# Pitch multipliers — exact trig values √(1 + (rise/12)²)
# ---------------------------------------------------------------------------
PITCH_MULTIPLIERS: dict[str, float] = {
    "2/12": 1.014,
    "3/12": 1.031,
    "4/12": 1.054,
    "5/12": 1.083,
    "6/12": 1.118,
    "7/12": 1.158,
    "8/12": 1.202,
    "9/12": 1.250,
    "10/12": 1.302,
    "11/12": 1.357,
    "12/12": 1.414,
    "Flat (1/12)": 1.003,
}

# ---------------------------------------------------------------------------
# Complexity factors and waste factors
# ---------------------------------------------------------------------------
COMPLEXITY_FACTORS: dict[str, float] = {
    "Simple": 1.00,       # Single gable or shed
    "Moderate": 1.15,     # Hip roof or L-shape
    "Complex": 1.30,      # Multiple planes, dormers
    "Very Complex": 1.50, # Many hips/valleys, skylights, penetrations
}

WASTE_FACTORS: dict[str, float] = {
    "Simple": 0.10,
    "Moderate": 0.13,
    "Complex": 0.17,
    "Very Complex": 0.20,
}

# ---------------------------------------------------------------------------
# Regional labor multipliers (applied to labor line items only)
# ---------------------------------------------------------------------------
REGIONAL_LABOR_MULTIPLIERS: dict[str, float] = {
    "Northeast": 1.25,
    "Mid-Atlantic": 1.18,
    "Southeast": 0.95,
    "Midwest": 1.00,
    "South Central": 0.93,
    "Mountain West": 1.05,
    "Pacific Northwest": 1.22,
    "California": 1.35,
    "Southwest": 0.98,
    "Hawaii / Alaska": 1.50,
}

# ---------------------------------------------------------------------------
# Accessory pricing (per unit or per LF)
# ---------------------------------------------------------------------------
ACCESSORIES = {
    "starter_strip_per_lf": 1.50,
    "ridge_cap_per_lf": 4.00,
    "drip_edge_per_lf": 1.25,
    "ice_water_shield_per_sq": 65.0,   # first 2 squares at eaves
    "synthetic_underlayment_per_sq": 18.0,
    "permit_flat_fee": 350.0,
    "debris_disposal_per_sq": 12.0,
}

STANDARD_TERMS = (
    "1. This quote is valid for 30 days from the date of issue.\n"
    "2. A 50% deposit is required upon signing; the balance is due upon completion.\n"
    "3. All work will be performed in accordance with local building codes and manufacturer specifications.\n"
    "4. Contractor carries general liability insurance and workers' compensation coverage.\n"
    "5. Any unforeseen structural damage (decking, fascia, rafters) discovered during work will be quoted separately before proceeding.\n"
    "6. Customer is responsible for moving vehicles, furniture, and breakable items from the work area.\n"
    "7. Warranty on workmanship is 5 years; material warranty per manufacturer specifications stated above.\n"
    "8. Contractor is not responsible for satellite dishes, solar panels, gutters, or other roof-mounted equipment unless explicitly included in this quote.\n"
    "9. Payment is due within 14 days of project completion. A 1.5% monthly finance charge applies to overdue balances.\n"
    "10. Disputes shall be resolved by binding arbitration in the jurisdiction where the property is located."
)
