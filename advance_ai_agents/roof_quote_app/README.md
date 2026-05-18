# AI Roof Quote Generator

An AI-powered roofing estimator that auto-generates professional web and PDF quotes in under 60 seconds. Powered by a three-agent Agno workflow: Claude claude-sonnet-4-6 for vision analysis, Llama-3.3-70B for material estimation and quote composition.

## Features

- **Three input paths** — upload a roof image, enter an address, or input manual measurements
- **AI vision analysis** — Claude claude-sonnet-4-6 extracts squares, pitch, complexity, and linear footage from aerial/overhead images
- **7 material types** — 3-tab shingle through clay tile, with regional labor multipliers
- **Itemised line items** — materials, underlayment, accessories, tearoff, labor, permit
- **Live web quote** — metrics, line-item table, and totals rendered in Streamlit
- **Branded PDF export** — professional ReportLab layout with company header, measurement summary, line items, signature block, and terms
- **Quote history** — session-based history in the sidebar for side-by-side comparison

## Tech Stack

- **Python 3.10+**
- **Agno** — multi-agent Workflow orchestration
- **Claude claude-sonnet-4-6** (Anthropic) — vision-based roof analysis
- **Llama-3.3-70B-Instruct** (Nebius) — material estimation and quote composition
- **Streamlit** — web interface
- **ReportLab** — PDF generation
- **Pydantic** — structured data models throughout

## Workflow

```
Input (image / address / manual)
    └─► RoofAnalysisAgent (Claude vision)   →  RoofMeasurement
          └─► MaterialEstimatorAgent (Llama) →  List[QuoteLineItem]
                └─► QuoteComposerAgent (Llama) →  RoofQuote
                      └─► PDF Generator (ReportLab) →  .pdf bytes
```

## Getting Started

### Prerequisites

- Python 3.10+
- An Anthropic API key (for image analysis — free tier works)
- A Nebius API key (for estimation agents)

### Installation

```bash
cd advance_ai_agents/roof_quote_app

# Recommended: use uv
uv pip install -e .

# Or pip
pip install -r pyproject.toml
```

### Environment Variables

```bash
cp .env.example .env
# Edit .env with your API keys
```

Required:
- `ANTHROPIC_API_KEY` — Claude claude-sonnet-4-6 (vision)
- `NEBIUS_API_KEY` — Llama-3.3-70B (estimation + composition)

### Run

```bash
streamlit run app.py
```

## Usage

1. **Roof Details** — pick a tab:
   - *Upload Image* — drag in an aerial/overhead roof photo
   - *Manual Measurements* — enter footprint sq ft, pitch, complexity
   - *Address Lookup* — enter the property address for an AI estimate

2. **Material Selection** — choose from 7 material types; see cost, warranty, and lifespan at a glance

3. **Customer & Region** — fill in customer info and select the pricing region

4. **Generate Quote** — click the button; watch the 3-agent pipeline run

5. **Export** — click *Build PDF* then *Download PDF Quote*

## Example Quote Output

```
Quote #RQ-20260518-A3F7
Customer: Jane Smith — 123 Main St, Austin TX 78701
Roof: 22.4 squares | 6/12 pitch | Moderate complexity
Material: Architectural Shingle (30-Year)

Line Items:
  Architectural Shingle (30-Year)     25.5 sq  @ $125.00  = $3,187.50
  Synthetic Underlayment              25.5 sq  @  $18.00  =   $459.00
  Ice & Water Shield (eaves)           2.0 sq  @  $65.00  =   $130.00
  Starter Strip                      180.0 LF  @   $1.50  =   $270.00
  Drip Edge                          180.0 LF  @   $1.25  =   $225.00
  Ridge Cap                           70.0 LF  @   $4.00  =   $280.00
  Tear-Off & Disposal                 20.0 sq  @  $45.00  =   $900.00
  Labor — Installation                25.5 sq  @  $86.25  = $2,199.38
  Permit & Debris Removal              1.0 job @  $350.00  =   $350.00

  TOTAL: $7,500.88
```
