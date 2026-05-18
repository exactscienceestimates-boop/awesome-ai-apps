from pydantic import BaseModel, Field
from typing import List


class RoofMeasurement(BaseModel):
    total_squares: float = Field(..., description="Total roof area in squares (1 square = 100 sq ft)")
    pitch: str = Field(..., description="Roof pitch, e.g. '6/12'")
    pitch_multiplier: float = Field(..., description="Slope correction factor, e.g. 1.118 for 6/12")
    complexity: str = Field(..., description="Simple | Moderate | Complex | Very Complex")
    complexity_factor: float = Field(..., description="Cost multiplier: 1.0 to 1.5")
    waste_factor_pct: float = Field(..., description="Decimal waste percentage, e.g. 0.12 for 12%")
    perimeter_lf: float = Field(default=0.0, description="Perimeter in linear feet")
    ridges_lf: float = Field(default=0.0)
    valleys_lf: float = Field(default=0.0)
    hips_lf: float = Field(default=0.0)
    eaves_lf: float = Field(default=0.0)
    number_of_stories: int = Field(default=1)
    layers_existing: int = Field(default=1, description="Number of existing shingle layers to tear off")
    analysis_source: str = Field(..., description="image_upload | address_lookup | manual_input")
    analysis_notes: str = Field(default="")


class MaterialOption(BaseModel):
    name: str
    slug: str
    material_cost_per_square: float
    labor_cost_per_square: float
    tearoff_cost_per_square: float = 50.0
    warranty_years: int
    lifespan_years: int
    description: str


class QuoteLineItem(BaseModel):
    category: str
    description: str
    quantity: float
    unit: str
    unit_price: float
    total: float


class CustomerInfo(BaseModel):
    name: str = ""
    address: str = ""
    city_state_zip: str = ""
    phone: str = ""
    email: str = ""


class RoofQuote(BaseModel):
    quote_id: str
    quote_date: str
    validity_date: str
    customer: CustomerInfo
    roof_measurement: RoofMeasurement
    selected_material: MaterialOption
    region: str
    regional_labor_multiplier: float
    line_items: List[QuoteLineItem]
    subtotal: float
    tax_rate: float
    tax_amount: float
    total: float
    scope_of_work: str = ""
    notes: str = ""
    terms_and_conditions: str
    company_name: str = ""
    company_phone: str = ""
    company_license: str = ""
