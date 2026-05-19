from pydantic import BaseModel, Field
from typing import List, Optional


class RoofMeasurement(BaseModel):
    total_area_sqft: float = Field(default=0.0, description="Flat footprint area in sq ft")
    total_squares: float = Field(default=0.0, description="Slope-adjusted squares (1 sq = 100 sq ft)")
    pitch: str = Field(default="6/12")
    pitch_multiplier: float = Field(default=1.118)
    complexity: str = Field(default="Moderate")
    complexity_factor: float = Field(default=1.15)
    waste_factor_pct: float = Field(default=0.13)
    perimeter_lf: float = Field(default=0.0)
    ridges_lf: float = Field(default=0.0)
    valleys_lf: float = Field(default=0.0)
    hips_lf: float = Field(default=0.0)
    eaves_lf: float = Field(default=0.0)
    number_of_stories: int = Field(default=1)
    layers_existing: int = Field(default=1)
    analysis_source: str = Field(default="manual_input")
    ai_confidence: str = Field(default="")
    notes: str = Field(default="")


class Property(BaseModel):
    property_id: str
    created_at: str
    updated_at: str
    status: str = Field(default="Measured")  # Measured | Quoted | Contracted | Completed
    # Owner info
    owner_name: str = Field(default="")
    owner_phone: str = Field(default="")
    owner_email: str = Field(default="")
    # Address
    street_address: str = Field(default="")
    city: str = Field(default="")
    state: str = Field(default="")
    zip_code: str = Field(default="")
    # Property details
    property_type: str = Field(default="Residential")
    year_built: Optional[int] = None
    # Measurements (None until analysed/entered)
    roof_measurement: Optional[RoofMeasurement] = None
    # Images stored as list of base64 strings
    image_count: int = Field(default=0)
    # Notes
    property_notes: str = Field(default="")

    @property
    def full_address(self) -> str:
        parts = [self.street_address]
        if self.city:
            parts.append(self.city)
        if self.state:
            parts.append(self.state)
        if self.zip_code:
            parts.append(self.zip_code)
        return ", ".join(p for p in parts if p)

    @property
    def display_name(self) -> str:
        return self.street_address or self.owner_name or self.property_id


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
    property_id: str = ""
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
