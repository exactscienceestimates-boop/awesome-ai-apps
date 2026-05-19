# Product Requirements Document: Roof Quote App

**Version:** 1.0  
**Date:** 2026-05-18  
**Location:** `advance_ai_agents/roof_quote_app/`

---

## Overview

A multi-agent AI application that takes roof details (address, manual measurements, or uploaded images) and automatically generates a professional, itemized roofing quote — delivered as both a live web UI and a downloadable branded PDF.

Contractors, estimators, and homeowners get an instant quote in under 60 seconds without manual takeoffs.

---

## Problem Statement

Roof estimating is slow, error-prone, and requires an experienced eye. A typical manual quote takes 30–90 minutes. This app compresses that to under a minute by using AI vision for measurement extraction, a rules-based pricing engine for materials and labor, and automated document generation for the final deliverable.

---

## Goals

1. Accept roof input via **3 paths**: address lookup (satellite), manual dimension entry, or image upload
2. Extract structured roof measurements using AI vision
3. Calculate material quantities with waste factors per roofing type
4. Present a live, editable web-based quote in Streamlit
5. Export a branded, print-ready PDF quote with line items and terms
6. Store quote history within the session for review/comparison

---

## Tech Stack

| Layer | Choice | Reason |
|---|---|---|
| Framework | Agno `Workflow` + `Agent` | Matches repo pattern; handles multi-agent orchestration |
| UI | Streamlit | Standard across all advanced agents in this repo |
| LLM / Vision | `claude-sonnet-4-6` via Anthropic | Best-in-class vision for roof image analysis |
| LLM / Reasoning | Nebius `meta-llama/Llama-3.3-70B-Instruct` | Fast reasoning for estimation & quote composition |
| Structured Output | Pydantic `BaseModel` | Enforces typed quote data throughout pipeline |
| PDF Generation | ReportLab | Pure Python, no browser dependency, fine-grained layout control |
| Satellite Imagery | Google Maps Static API (optional) | Aerial view from address for roof outline |
| Env Management | `python-dotenv` + `.env.example` | Repo standard |
| Packaging | `pyproject.toml` + `uv` | Repo standard for newer projects |

---

## File Structure

```
advance_ai_agents/roof_quote_app/
├── app.py                  # Streamlit UI entry point
├── agents.py               # Agno Workflow + all sub-agents
├── models.py               # Pydantic data models
├── pricing.py              # Material pricing database & formulas
├── pdf_generator.py        # ReportLab PDF builder
├── utils.py                # Image helpers, address geocoding
├── assets/
│   └── logo_placeholder.png
├── .env.example
├── pyproject.toml
└── README.md
```

---

## Pydantic Data Models (`models.py`)

```python
class RoofMeasurement(BaseModel):
    total_squares: float          # 1 square = 100 sq ft
    pitch: str                    # e.g. "6/12"
    pitch_multiplier: float       # flat=1.0, steep=1.19
    complexity: str               # simple | moderate | complex
    waste_factor: float           # 0.10–0.20 based on complexity
    perimeter_lf: float
    ridge_lf: float
    valley_lf: float
    hip_lf: float
    eave_lf: float
    layers_existing: int          # tearoff layers (0 = new construction)
    confidence: float             # 0.0–1.0 AI confidence score
    notes: str

class MaterialOption(BaseModel):
    name: str                     # "Architectural Shingle - Mid Grade"
    sku: str
    price_per_square: float       # material cost
    labor_per_square: float
    warranty_years: int
    description: str

class QuoteLineItem(BaseModel):
    category: str                 # Materials | Labor | Disposal | Accessories
    description: str
    qty: float
    unit: str                     # squares, LF, EA, job
    unit_price: float
    total: float

class RoofQuote(BaseModel):
    quote_id: str
    created_at: str
    valid_until: str              # 30 days from creation
    customer_name: str
    customer_address: str
    customer_phone: str
    customer_email: str
    roof_measurements: RoofMeasurement
    selected_material: MaterialOption
    line_items: list[QuoteLineItem]
    subtotal: float
    tax_rate: float
    tax_amount: float
    total: float
    notes: str
    company_name: str
    company_phone: str
    company_license: str
```

---

## Agent Architecture (`agents.py`)

### Workflow: `RoofQuoteWorkflow`

```
Input
  └─► RoofAnalysisAgent      → RoofMeasurement
        └─► MaterialEstimatorAgent  → list[QuoteLineItem] + totals
              └─► QuoteComposerAgent → RoofQuote (final structured output)
```

### Agent 1 — `RoofAnalysisAgent`
- **Model:** `claude-sonnet-4-6` (Anthropic) — vision capable
- **Input:** base64-encoded roof image OR address string OR manual dict
- **Output:** `RoofMeasurement` JSON
- **Instructions:**
  - Identify roof planes, count facets, estimate pitch from shadow angles
  - Detect hips, valleys, ridges, dormers, skylights, chimneys
  - Estimate total square footage from scale cues or provided dimensions
  - Assign complexity: simple (≤2 planes), moderate (3–5), complex (6+)
  - Return confidence score; flag if image quality is too low
  - If manual dimensions provided, skip vision and compute from inputs

### Agent 2 — `MaterialEstimatorAgent`
- **Model:** Nebius `meta-llama/Llama-3.3-70B-Instruct`
- **Input:** `RoofMeasurement` + selected material type + region
- **Output:** `list[QuoteLineItem]`
- **Instructions:**
  - Apply waste factor to compute ordered squares
  - Add accessory line items: underlayment, ice & water shield, drip edge, ridge cap, nails, starter strip
  - Add labor lines: tearoff (per layer), install, flashing, cleanup
  - Add disposal line if tearoff layers > 0
  - Price from `pricing.py` lookup table; apply complexity surcharge
  - Output itemized line items with quantities and unit prices

### Agent 3 — `QuoteComposerAgent`
- **Model:** Nebius `meta-llama/Llama-3.3-70B-Instruct`
- **Input:** all prior outputs + customer info
- **Output:** complete `RoofQuote` with notes and validity date
- **Instructions:**
  - Assemble final quote from line items
  - Calculate subtotal, tax, total
  - Write a professional 2–3 sentence summary of the scope of work
  - Set validity to 30 days from today
  - Flag any unusual conditions noted by the analysis agent

---

## Pricing Engine (`pricing.py`)

```python
MATERIAL_OPTIONS = {
    "3tab_standard":        MaterialOption(price_per_square=85,  labor_per_square=75,  warranty_years=20),
    "architectural_mid":    MaterialOption(price_per_square=115, labor_per_square=80,  warranty_years=30),
    "architectural_premium":MaterialOption(price_per_square=165, labor_per_square=85,  warranty_years=50),
    "metal_standing_seam":  MaterialOption(price_per_square=350, labor_per_square=200, warranty_years=50),
    "metal_exposed_fastener":MaterialOption(price_per_square=220,labor_per_square=150, warranty_years=40),
    "concrete_tile":        MaterialOption(price_per_square=280, labor_per_square=180, warranty_years=50),
    "clay_tile":            MaterialOption(price_per_square=400, labor_per_square=220, warranty_years=lifetime),
}

COMPLEXITY_SURCHARGE = {"simple": 0.0, "moderate": 0.08, "complex": 0.18}
TEAROFF_COST_PER_SQUARE = 45   # per layer
REGIONAL_MULTIPLIERS = {"northeast": 1.15, "southeast": 0.95, "midwest": 1.0, "west": 1.20, "southwest": 0.98}
```

---

## PDF Generator (`pdf_generator.py`)

Built with **ReportLab**. Page layout (letter size):

```
┌─────────────────────────────────────────────────┐
│  [LOGO]    Company Name          Quote #: XXXXX  │
│            Phone | License       Date: YYYY-MM-DD│
├─────────────────────────────────────────────────┤
│  PREPARED FOR          │  PROPERTY ADDRESS       │
│  Customer Name         │  123 Main St            │
│  Phone / Email         │  City, State ZIP        │
├─────────────────────────────────────────────────┤
│  ROOF MEASUREMENTS                               │
│  Total Squares: XX  │ Pitch: X/12  │ Layers: X   │
│  Complexity: Moderate │ Confidence: 94%           │
├─────────────────────────────────────────────────┤
│  LINE ITEMS TABLE                                │
│  Description      │ Qty │ Unit │ Unit$ │ Total$  │
│  ──────────────────────────────────────────────  │
│  Architectural Shingle (30yr)  │ 24.5 sq │ ...   │
│  Underlayment ...                                │
│  Tearoff & Disposal ...                          │
│  Labor - Installation ...                        │
├─────────────────────────────────────────────────┤
│                        Subtotal:    $X,XXX.XX    │
│                        Tax (X%):    $  XXX.XX    │
│                        TOTAL:       $X,XXX.XX    │
├─────────────────────────────────────────────────┤
│  SCOPE OF WORK (AI-generated paragraph)          │
├─────────────────────────────────────────────────┤
│  TERMS & CONDITIONS (standard 5-point list)      │
├─────────────────────────────────────────────────┤
│  Contractor Signature ___________  Date _______  │
│  Customer Signature  ___________  Date _______   │
└─────────────────────────────────────────────────┘
```

---

## Streamlit UI Flow (`app.py`)

```
Sidebar
  └── Company Settings (name, phone, license, tax rate, region)
  └── Quote History (session_state list)

Main Panel — 4-step wizard:

Step 1: ROOF INPUT
  ├── Tab A: Upload Image (drag & drop, supports JPG/PNG/aerial screenshot)
  ├── Tab B: Enter Address (calls Google Maps Static API for satellite view)
  └── Tab C: Manual Entry (sliders/inputs for dimensions)

Step 2: MATERIAL SELECTION
  └── Radio cards for each material type
      Shows: price/sq, labor/sq, warranty, description
      Optional: tier comparison table

Step 3: CUSTOMER INFO
  └── Name, address, phone, email
  └── "Generate Quote" button → triggers Workflow with spinner

Step 4: QUOTE REVIEW & EXPORT
  ├── Live quote rendered in Streamlit (metrics + styled table)
  ├── Editable notes field
  ├── "Download PDF" button → calls pdf_generator.py → st.download_button
  └── "Save to History" → appends to session_state
```

---

## Environment Variables (`.env.example`)

```env
# Required
ANTHROPIC_API_KEY=your_anthropic_api_key        # For Claude vision (RoofAnalysisAgent)
NEBIUS_API_KEY=your_nebius_api_key              # For estimation & composition agents

# Optional
GOOGLE_MAPS_API_KEY=your_google_maps_api_key    # For address → satellite image lookup

# App Config
TAX_RATE=0.08
DEFAULT_REGION=midwest
COMPANY_NAME=Your Roofing Co
COMPANY_PHONE=(555) 000-0000
COMPANY_LICENSE=ROC-XXXXXX
```

---

## Dependencies (`pyproject.toml`)

```toml
[project]
name = "roof-quote-app"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "agno",
    "anthropic",
    "openai",                 # Agno uses openai-compatible client for Nebius
    "streamlit",
    "pydantic",
    "reportlab",
    "python-dotenv",
    "Pillow",                 # Image preprocessing before vision
    "requests",               # Google Maps Static API call
    "fpdf2",                  # Fallback PDF option
]
```

---

## Implementation Phases

### Phase 1 — Core (MVP)
- [ ] `models.py` — all Pydantic models
- [ ] `pricing.py` — full material + accessory pricing table
- [ ] `agents.py` — RoofAnalysisAgent (manual input path only, no vision yet)
- [ ] `agents.py` — MaterialEstimatorAgent + QuoteComposerAgent
- [ ] `pdf_generator.py` — complete ReportLab layout
- [ ] `app.py` — Tab C (manual entry) + Step 3–4 fully working
- [ ] End-to-end: manual input → quote → PDF download

### Phase 2 — Vision
- [ ] `agents.py` — RoofAnalysisAgent vision path (Claude vision API)
- [ ] `utils.py` — image preprocessing (resize, base64 encode)
- [ ] `app.py` — Tab A (image upload) wired up

### Phase 3 — Address Lookup
- [ ] `utils.py` — Google Maps Static API → satellite image fetch
- [ ] `app.py` — Tab B (address input) wired up

### Phase 4 — Polish
- [ ] Quote history panel in sidebar
- [ ] Multiple material tier comparison view
- [ ] Logo upload for PDF branding
- [ ] Quote validity countdown
- [ ] Export quote to JSON for CRM import

---

## Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Vision model | Claude claude-sonnet-4-6 | Best roof geometry understanding; native vision |
| PDF library | ReportLab | No headless browser needed; precise layout control |
| No external measurement API | Intentional | Keeps app self-contained; Eagleview/Nearmap cost $15–30/report |
| Waste factor in model | Stored in `RoofMeasurement` | Allows AI to tune it per complexity vs. hardcoded |
| Pricing as Python dict | `pricing.py` | Easy to update rates without touching agent logic |
| Streamlit tabs for input | 3-tab wizard | Reduces friction; user picks their comfort level |

---

## Verification / Testing

1. **Manual path end-to-end:** Enter 2000 sq ft, 6/12 pitch, moderate, 1 tearoff layer → select architectural mid → fill customer info → verify PDF downloads with correct line items and total
2. **Vision path:** Upload a real aerial roof photo → confirm `RoofMeasurement.total_squares` is within 15% of known value
3. **PDF integrity:** Open downloaded PDF, verify all sections render, signature lines present, no truncated text
4. **Pricing math:** Manually verify: `(squares × (1 + waste)) × (material_price + labor_price) + accessories + tearoff + tax = total`
5. **Session history:** Generate 3 quotes, verify all appear in sidebar history with correct totals
