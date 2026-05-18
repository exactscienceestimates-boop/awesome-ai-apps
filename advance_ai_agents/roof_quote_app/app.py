import os
import io
import streamlit as st
from dotenv import load_dotenv

from agents import RoofQuoteWorkflow
from pdf_generator import generate_quote_pdf
from pricing_data import MATERIAL_OPTIONS, REGIONAL_LABOR_MULTIPLIERS, PITCH_MULTIPLIERS

load_dotenv()

# Pull secrets from Streamlit Cloud secrets manager if available,
# falling back to .env / environment variables.
def _secret(key: str, default: str = "") -> str:
    try:
        return st.secrets.get(key, os.getenv(key, default))
    except Exception:
        return os.getenv(key, default)

st.set_page_config(
    page_title="Roof Quote App",
    page_icon="🏠",
    layout="wide",
)

# ------------------------------------------------------------------
# Session state initialisation
# ------------------------------------------------------------------
if "quote_history" not in st.session_state:
    st.session_state.quote_history = []
if "current_quote" not in st.session_state:
    st.session_state.current_quote = None
if "current_pdf" not in st.session_state:
    st.session_state.current_pdf = None
if "uploaded_image" not in st.session_state:
    st.session_state.uploaded_image = None

# ------------------------------------------------------------------
# Page title
# ------------------------------------------------------------------
st.markdown(
    """
    <div style="text-align:center; padding: 24px 0 8px 0;">
        <h1 style="font-size:2.2rem; font-weight:800; margin:0;">
            🏠 AI Roof Quote Generator
        </h1>
        <p style="color:#666; margin-top:6px;">
            Powered by <strong>Claude claude-sonnet-4-6</strong> vision + <strong>Agno</strong> multi-agent workflow
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ------------------------------------------------------------------
# Sidebar — API keys, company settings, quote history
# ------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Configuration")

    with st.expander("API Keys", expanded=True):
        anthropic_key = st.text_input(
            "Anthropic API Key",
            value=_secret("ANTHROPIC_API_KEY"),
            type="password",
            help="Required for roof image analysis (Claude vision)",
        )
        nebius_key = st.text_input(
            "Nebius API Key",
            value=_secret("NEBIUS_API_KEY"),
            type="password",
            help="Required for estimation & quote composition agents",
        )
        if st.button("Save Keys", use_container_width=True):
            os.environ["ANTHROPIC_API_KEY"] = anthropic_key
            os.environ["NEBIUS_API_KEY"] = nebius_key
            st.success("Keys saved for this session.")

    st.divider()

    with st.expander("Company Settings", expanded=True):
        company_name = st.text_input("Company Name", value=_secret("COMPANY_NAME", "Your Roofing Co."))
        company_phone = st.text_input("Company Phone", value=_secret("COMPANY_PHONE", "(555) 000-0000"))
        company_license = st.text_input("License #", value=_secret("COMPANY_LICENSE", "ROC-XXXXXX"))
        _default_tax = float(_secret("TAX_RATE", "0.0"))
        tax_rate = st.number_input("Tax Rate (%)", min_value=0.0, max_value=20.0,
                                    value=_default_tax, step=0.5) / 100

    st.divider()

    st.header("📋 Quote History")
    if not st.session_state.quote_history:
        st.caption("No quotes yet this session.")
    else:
        for q in reversed(st.session_state.quote_history):
            label = f"{q.quote_id}  —  ${q.total:,.0f}"
            if st.button(label, key=f"hist_{q.quote_id}", use_container_width=True):
                st.session_state.current_quote = q
                st.session_state.current_pdf = None

    st.divider()
    st.markdown(
        "**Agents:**\n"
        "- 🔍 Roof Analysis (Claude vision)\n"
        "- 📐 Material Estimator (Llama-3.3-70B)\n"
        "- ✍️ Quote Composer (Llama-3.3-70B)"
    )

# ------------------------------------------------------------------
# Main content — input wizard
# ------------------------------------------------------------------
st.subheader("Step 1 — Roof Details")
tab_image, tab_manual, tab_address = st.tabs([
    "📷  Upload Image",
    "📏  Manual Measurements",
    "📍  Address Lookup",
])

input_mode = None
image_bytes = None
manual_measurements = None
address_str = None

with tab_image:
    uploaded = st.file_uploader(
        "Upload an aerial or overhead roof photo (JPG/PNG)",
        type=["jpg", "jpeg", "png"],
        key="roof_uploader",
    )
    if uploaded:
        st.session_state.uploaded_image = uploaded.read()
        st.image(st.session_state.uploaded_image, caption="Uploaded roof image", use_container_width=True)

    if st.session_state.uploaded_image:
        input_mode = "image"
        image_bytes = st.session_state.uploaded_image
        st.info(
            "Claude claude-sonnet-4-6 will analyse this image to extract roof measurements. "
            "Best results with clear overhead/aerial shots.",
            icon="ℹ️",
        )

with tab_manual:
    col1, col2 = st.columns(2)
    with col1:
        area_sqft = st.number_input(
            "Roof Footprint Area (sq ft)", min_value=100, max_value=20000,
            value=2000, step=100,
        )
        pitch_choice = st.selectbox(
            "Roof Pitch", options=list(PITCH_MULTIPLIERS.keys()), index=5
        )
        complexity_choice = st.selectbox(
            "Roof Complexity",
            options=["Simple", "Moderate", "Complex", "Very Complex"],
            index=1,
        )
        stories = st.number_input("Number of Stories", min_value=1, max_value=4, value=1)
        layers = st.number_input(
            "Existing Shingle Layers (tearoff)", min_value=0, max_value=3, value=1,
            help="0 = new construction, no tearoff needed",
        )
    with col2:
        st.caption("Optional: Linear Footage Details")
        perimeter = st.number_input("Perimeter (LF)", min_value=0, value=180, step=5)
        ridges = st.number_input("Ridge Length (LF)", min_value=0, value=30, step=5)
        valleys = st.number_input("Valley Length (LF)", min_value=0, value=20, step=5)
        hips = st.number_input("Hip Length (LF)", min_value=0, value=40, step=5)
        eaves = st.number_input("Eave Length (LF)", min_value=0, value=80, step=5)

    if tab_manual:
        input_mode = "manual"
        manual_measurements = {
            "area_sqft": area_sqft,
            "pitch": pitch_choice,
            "complexity": complexity_choice,
            "number_of_stories": stories,
            "layers_existing": layers,
            "perimeter_lf": perimeter,
            "ridges_lf": ridges,
            "valleys_lf": valleys,
            "hips_lf": hips,
            "eaves_lf": eaves,
        }

with tab_address:
    address_input = st.text_input(
        "Property Address",
        placeholder="123 Main St, Austin, TX 78701",
    )
    st.info(
        "Without satellite integration the AI will estimate dimensions for a typical residential "
        "home at this address. For accurate results, use image upload instead.",
        icon="ℹ️",
    )
    if address_input:
        input_mode = "address"
        address_str = address_input

# ------------------------------------------------------------------
# Step 2 — Material Selection
# ------------------------------------------------------------------
st.divider()
st.subheader("Step 2 — Material Selection")

mat_cols = st.columns(len(MATERIAL_OPTIONS))
selected_slug = list(MATERIAL_OPTIONS.keys())[1]  # default: architectural

mat_display = {}
for slug, mat in MATERIAL_OPTIONS.items():
    mat_display[f"{mat.name}"] = slug

selected_mat_name = st.radio(
    "Choose roofing material",
    options=list(mat_display.keys()),
    index=1,
    horizontal=True,
    label_visibility="collapsed",
)
selected_slug = mat_display[selected_mat_name]
selected_mat = MATERIAL_OPTIONS[selected_slug]

mc1, mc2, mc3, mc4 = st.columns(4)
mc1.metric("Material / sq", f"${selected_mat.material_cost_per_square:,.0f}")
mc2.metric("Labor / sq", f"${selected_mat.labor_cost_per_square:,.0f}")
mc3.metric("Warranty", f"{selected_mat.warranty_years} yrs")
mc4.metric("Est. Lifespan", f"{selected_mat.lifespan_years} yrs")
st.caption(selected_mat.description)

# ------------------------------------------------------------------
# Step 3 — Customer Info & Region
# ------------------------------------------------------------------
st.divider()
st.subheader("Step 3 — Customer & Region")

ci_col1, ci_col2 = st.columns(2)
with ci_col1:
    cust_name = st.text_input("Customer Name", placeholder="Jane Smith")
    cust_address = st.text_input("Street Address", placeholder="123 Main Street")
    cust_csz = st.text_input("City, State, ZIP", placeholder="Austin, TX 78701")
with ci_col2:
    cust_phone = st.text_input("Phone", placeholder="(512) 555-0100")
    cust_email = st.text_input("Email", placeholder="jane@example.com")
    region = st.selectbox("Region / Market", options=list(REGIONAL_LABOR_MULTIPLIERS.keys()), index=3)

# ------------------------------------------------------------------
# Generate Quote button
# ------------------------------------------------------------------
st.divider()
generate_col, _ = st.columns([1, 3])
with generate_col:
    generate_btn = st.button("⚡ Generate Quote", type="primary", use_container_width=True)

if generate_btn:
    if not input_mode:
        st.error("Please provide roof details in one of the tabs above.")
    elif input_mode == "image" and not image_bytes:
        st.error("Please upload a roof image first.")
    elif input_mode == "address" and not address_str:
        st.error("Please enter a property address.")
    elif not os.getenv("NEBIUS_API_KEY") and not nebius_key:
        st.error("Nebius API key is required. Add it in the sidebar.")
    else:
        # Ensure env vars are set from sidebar inputs
        if anthropic_key:
            os.environ["ANTHROPIC_API_KEY"] = anthropic_key
        if nebius_key:
            os.environ["NEBIUS_API_KEY"] = nebius_key

        customer_info = {
            "name": cust_name,
            "address": cust_address,
            "city_state_zip": cust_csz,
            "phone": cust_phone,
            "email": cust_email,
        }
        company_info = {
            "name": company_name,
            "phone": company_phone,
            "license": company_license,
        }

        try:
            workflow = RoofQuoteWorkflow()

            with st.status("Generating your roof quote...", expanded=True) as status:
                if input_mode == "image":
                    status.write("🔍 Analysing roof image with Claude vision...")
                elif input_mode == "address":
                    status.write("📍 Estimating dimensions from address...")
                else:
                    status.write("📐 Processing roof measurements...")

                status.write("📐 Calculating material quantities and line items...")
                status.write("✍️ Composing professional quote...")

                quote = workflow.run(
                    input_mode=input_mode,
                    material_slug=selected_slug,
                    region=region,
                    customer_info=customer_info,
                    company_info=company_info,
                    tax_rate=tax_rate,
                    image_bytes=image_bytes,
                    address=address_str,
                    manual_measurements=manual_measurements,
                )
                status.update(label="Quote ready!", state="complete")

            st.session_state.current_quote = quote
            st.session_state.current_pdf = None
            if quote not in st.session_state.quote_history:
                st.session_state.quote_history.append(quote)

        except Exception as exc:
            st.error(f"Quote generation failed: {exc}")
            st.exception(exc)

# ------------------------------------------------------------------
# Step 4 — Results
# ------------------------------------------------------------------
if st.session_state.current_quote:
    q = st.session_state.current_quote
    m = q.roof_measurement

    st.divider()
    st.subheader(f"Step 4 — Quote #{q.quote_id}")
    st.success(f"Quote valid until **{q.validity_date}**")

    # Measurement summary
    st.markdown("#### Roof Measurements")
    rm1, rm2, rm3, rm4, rm5 = st.columns(5)
    rm1.metric("Total Squares", f"{m.total_squares:.1f} sq")
    rm2.metric("Pitch", m.pitch)
    rm3.metric("Complexity", m.complexity)
    rm4.metric("Stories", m.number_of_stories)
    rm5.metric("Tearoff Layers", m.layers_existing)
    if m.analysis_notes:
        st.caption(f"Analysis note: {m.analysis_notes}")

    # Scope of work
    if q.scope_of_work:
        st.markdown("#### Scope of Work")
        st.write(q.scope_of_work)

    # Line items
    st.markdown("#### Line Items")
    import pandas as pd
    df = pd.DataFrame([
        {
            "Category": item.category,
            "Description": item.description,
            "Qty": f"{item.quantity:.2f}",
            "Unit": item.unit,
            "Unit Price": f"${item.unit_price:,.2f}",
            "Total": f"${item.total:,.2f}",
        }
        for item in q.line_items
    ])
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Totals
    t1, t2, t3 = st.columns(3)
    t1.metric("Subtotal", f"${q.subtotal:,.2f}")
    t2.metric(f"Tax ({q.tax_rate * 100:.1f}%)", f"${q.tax_amount:,.2f}")
    t3.metric("**TOTAL**", f"${q.total:,.2f}")

    # PDF export
    st.markdown("#### Export")
    pdf_col1, pdf_col2 = st.columns([1, 3])
    with pdf_col1:
        if st.button("📄 Build PDF", use_container_width=True):
            with st.spinner("Rendering PDF..."):
                st.session_state.current_pdf = generate_quote_pdf(
                    q,
                    company_name=company_name,
                    company_phone=company_phone,
                    company_license=company_license,
                )
            st.success("PDF ready!")

    if st.session_state.current_pdf:
        with pdf_col2:
            st.download_button(
                label="⬇️ Download PDF Quote",
                data=st.session_state.current_pdf,
                file_name=f"quote_{q.quote_id}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )

    with st.expander("Raw Quote JSON"):
        st.json(q.model_dump())
