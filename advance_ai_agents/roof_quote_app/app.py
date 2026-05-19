import os
import uuid
import io
from datetime import datetime

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import property_store as db
from agents import (
    analyse_multiple_images, estimate_from_address,
    manual_to_measurement, generate_quote,
)
from address_lookup import lookup_property
from measurement_report import generate_measurement_report
from pdf_generator import generate_quote_pdf
from pricing_data import MATERIAL_OPTIONS, REGIONAL_LABOR_MULTIPLIERS, PITCH_MULTIPLIERS
from models import Property, RoofMeasurement

load_dotenv()
db.init_db()

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _secret(key: str, default: str = "") -> str:
    try:
        return st.secrets.get(key, os.getenv(key, default))
    except Exception:
        return os.getenv(key, default)


STATUS_COLORS = {
    "Measured": "#2980B9",
    "Quoted": "#F39C12",
    "Contracted": "#27AE60",
    "Completed": "#7F8C8D",
}


def _badge(status: str) -> str:
    color = STATUS_COLORS.get(status, "#999")
    return (
        f'<span style="background:{color};color:white;padding:2px 10px;'
        f'border-radius:12px;font-size:0.75rem;font-weight:600;">{status}</span>'
    )


def _now() -> str:
    return datetime.now().isoformat()


def _set_view(view: str, property_id: str = None):
    st.session_state.view = view
    st.session_state.selected_pid = property_id
    st.session_state.edit_mode = view in ("new_property", "edit_property")
    st.session_state.ai_measurements = None
    st.session_state.uploaded_images = []
    for k in ("_lookup_result", "_lookup_images", "_pf_street",
              "_pf_city", "_pf_state", "_pf_zip"):
        st.session_state.pop(k, None)


# ------------------------------------------------------------------
# Session state bootstrap
# ------------------------------------------------------------------
defaults = {
    "view": "list",
    "selected_pid": None,
    "edit_mode": False,
    "ai_measurements": None,
    "uploaded_images": [],
    "quote_preview": None,
    "quote_pdf": None,
    "meas_pdf": None,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ------------------------------------------------------------------
# Page config
# ------------------------------------------------------------------
st.set_page_config(page_title="Roof Measurement CRM", page_icon="🏠", layout="wide")

st.markdown("""
<style>
.prop-card {
    background:#fff; border:1px solid #e0e0e0; border-radius:10px;
    padding:14px 18px; margin-bottom:10px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}
.prop-address { font-size:1.05rem; font-weight:700; color:#1A2332; }
.prop-meta { font-size:0.82rem; color:#666; margin-top:2px; }
.section-header {
    font-size:1.1rem; font-weight:700; color:#2C3E50;
    border-left:4px solid #2980B9; padding-left:10px; margin:18px 0 8px 0;
}
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------
# Sidebar
# ------------------------------------------------------------------
with st.sidebar:
    st.markdown("## 🏠 Roof Measurement CRM")
    st.divider()

    if st.button("➕  New Property", use_container_width=True, type="primary"):
        _set_view("new_property")

    if st.button("📋  All Properties", use_container_width=True):
        _set_view("list")

    st.divider()
    with st.expander("⚙️ Settings", expanded=False):
        anthropic_key = st.text_input(
            "Anthropic API Key",
            value=_secret("ANTHROPIC_API_KEY"),
            type="password",
            help="Powers all three AI agents",
        )
        if anthropic_key:
            os.environ["ANTHROPIC_API_KEY"] = anthropic_key

        st.caption("Optional — improves satellite image quality")
        google_maps_key = st.text_input(
            "Google Maps API Key",
            value=_secret("GOOGLE_MAPS_API_KEY"),
            type="password",
            help="Enables high-res Google satellite + Street View. Without this, free ESRI imagery is used.",
        )
        if google_maps_key:
            os.environ["GOOGLE_MAPS_API_KEY"] = google_maps_key

        mapbox_token = st.text_input(
            "Mapbox Token (optional)",
            value=_secret("MAPBOX_TOKEN"),
            type="password",
            help="Alternative to Google Maps for satellite imagery.",
        )
        if mapbox_token:
            os.environ["MAPBOX_TOKEN"] = mapbox_token

        st.divider()
        company_name = st.text_input("Company Name", value=_secret("COMPANY_NAME", "Your Roofing Co."))
        company_phone = st.text_input("Phone", value=_secret("COMPANY_PHONE", "(555) 000-0000"))
        company_license = st.text_input("License #", value=_secret("COMPANY_LICENSE", "ROC-XXXXXX"))
        _dtax = float(_secret("TAX_RATE", "0.0"))
        tax_rate = st.number_input("Tax Rate (%)", min_value=0.0, max_value=20.0,
                                    value=_dtax, step=0.5) / 100

    st.divider()
    # Quick property search
    search_q = st.text_input("🔍 Search properties", placeholder="Name or address...")

# ------------------------------------------------------------------
# Measurement editor widget (reused in new + edit views)
# ------------------------------------------------------------------

def _measurement_form(prefix: str, init: RoofMeasurement = None) -> dict:
    """Render editable measurement fields. Returns form dict."""
    m = init or RoofMeasurement()

    st.markdown('<div class="section-header">Roof Measurements</div>', unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)
    with col1:
        area_sqft = st.number_input("Footprint Area (sq ft)", min_value=0.0,
                                     value=float(m.total_area_sqft or 0), step=50.0, key=f"{prefix}_area")
        pitch = st.selectbox("Pitch", options=list(PITCH_MULTIPLIERS.keys()),
                              index=list(PITCH_MULTIPLIERS.keys()).index(m.pitch)
                              if m.pitch in PITCH_MULTIPLIERS else 5,
                              key=f"{prefix}_pitch")
        complexity = st.selectbox("Complexity",
                                   options=["Simple", "Moderate", "Complex", "Very Complex"],
                                   index=["Simple", "Moderate", "Complex", "Very Complex"].index(m.complexity)
                                   if m.complexity in ["Simple", "Moderate", "Complex", "Very Complex"] else 1,
                                   key=f"{prefix}_complexity")
    with col2:
        stories = st.number_input("Stories", min_value=1, max_value=4,
                                   value=int(m.number_of_stories or 1), key=f"{prefix}_stories")
        layers = st.number_input("Existing Layers (tearoff)", min_value=0, max_value=3,
                                  value=int(m.layers_existing or 1), key=f"{prefix}_layers",
                                  help="0 = new construction")
        perimeter = st.number_input("Perimeter (LF)", min_value=0.0,
                                     value=float(m.perimeter_lf or 0), step=5.0, key=f"{prefix}_perim")
    with col3:
        ridges = st.number_input("Ridge Length (LF)", min_value=0.0,
                                  value=float(m.ridges_lf or 0), step=5.0, key=f"{prefix}_ridges")
        valleys = st.number_input("Valley Length (LF)", min_value=0.0,
                                   value=float(m.valleys_lf or 0), step=5.0, key=f"{prefix}_valleys")
        hips = st.number_input("Hip Length (LF)", min_value=0.0,
                                value=float(m.hips_lf or 0), step=5.0, key=f"{prefix}_hips")
        eaves = st.number_input("Eave Length (LF)", min_value=0.0,
                                 value=float(m.eaves_lf or 0), step=5.0, key=f"{prefix}_eaves")

    notes = st.text_area("Measurement Notes / Conditions", value=m.notes or "",
                          key=f"{prefix}_notes", height=70)

    from pricing_data import COMPLEXITY_FACTORS, WASTE_FACTORS
    pm = PITCH_MULTIPLIERS.get(pitch, 1.118)
    total_sq = round((area_sqft / 100) * pm, 2) if area_sqft else 0
    cf = COMPLEXITY_FACTORS.get(complexity, 1.15)
    wf = WASTE_FACTORS.get(complexity, 0.13)
    adj_sq = round(total_sq * pm * (1 + wf), 2)

    if area_sqft:
        mc1, mc2, mc3 = st.columns(3)
        mc1.metric("Slope-Adjusted Squares", f"{total_sq:.2f} sq")
        mc2.metric("Waste Factor", f"{wf * 100:.0f}%")
        mc3.metric("Adjusted Squares (order qty)", f"{adj_sq:.2f} sq")

    return {
        "total_area_sqft": area_sqft,
        "total_squares": total_sq,
        "pitch": pitch,
        "pitch_multiplier": pm,
        "complexity": complexity,
        "complexity_factor": cf,
        "waste_factor_pct": wf,
        "perimeter_lf": perimeter,
        "ridges_lf": ridges,
        "valleys_lf": valleys,
        "hips_lf": hips,
        "eaves_lf": eaves,
        "number_of_stories": stories,
        "layers_existing": layers,
        "analysis_source": m.analysis_source or "manual_input",
        "ai_confidence": m.ai_confidence or "",
        "notes": notes,
    }


# ==================================================================
# VIEW: Property List
# ==================================================================

def view_list():
    st.markdown("## Properties")

    all_props = db.list_properties()
    if search_q:
        all_props = [p for p in all_props
                     if search_q.lower() in (p.full_address + p.owner_name).lower()]

    if not all_props:
        st.info("No properties yet. Click **➕ New Property** in the sidebar to add one.")
        return

    for prop in all_props:
        m = prop.roof_measurement
        sq_label = f"{m.total_squares:.1f} sq" if m else "Not measured"

        with st.container():
            st.markdown(f"""
            <div class="prop-card">
                <div class="prop-address">{prop.full_address or "—"}</div>
                <div class="prop-meta">
                    Owner: {prop.owner_name or "—"} &nbsp;|&nbsp;
                    {prop.property_type} &nbsp;|&nbsp;
                    {sq_label} &nbsp;|&nbsp;
                    Added: {prop.created_at[:10]}
                    &nbsp;&nbsp;{_badge(prop.status)}
                </div>
            </div>
            """, unsafe_allow_html=True)

            btn_col1, btn_col2, btn_col3, _ = st.columns([1, 1, 1, 5])
            with btn_col1:
                if st.button("View", key=f"view_{prop.property_id}"):
                    _set_view("property_detail", prop.property_id)
                    st.rerun()
            with btn_col2:
                if st.button("Edit", key=f"edit_{prop.property_id}"):
                    _set_view("edit_property", prop.property_id)
                    st.rerun()
            with btn_col3:
                if st.button("Delete", key=f"del_{prop.property_id}"):
                    db.delete_property(prop.property_id)
                    st.success("Property deleted.")
                    st.rerun()


# ==================================================================
# VIEW: New / Edit Property
# ==================================================================

def view_new_or_edit():
    is_edit = st.session_state.view == "edit_property"
    pid = st.session_state.selected_pid

    existing: Property = db.get_property(pid) if is_edit else None
    existing_images = db.get_images(pid) if is_edit else []

    st.markdown(f"## {'✏️ Edit' if is_edit else '➕ New'} Property")
    if is_edit and existing and existing.full_address:
        st.markdown(f"*{existing.full_address}*")

    # ---- Owner & Property Info ----
    st.markdown('<div class="section-header">Property & Owner Information</div>', unsafe_allow_html=True)
    pi1, pi2 = st.columns(2)
    with pi1:
        owner_name = st.text_input("Owner Name", value=existing.owner_name if existing else "")
        owner_phone = st.text_input("Phone", value=existing.owner_phone if existing else "")
        owner_email = st.text_input("Email", value=existing.owner_email if existing else "")
    with pi2:
        prop_type = st.selectbox("Property Type",
                                  ["Residential", "Commercial", "Multi-Family", "Industrial"],
                                  index=["Residential", "Commercial", "Multi-Family", "Industrial"]
                                  .index(existing.property_type if existing else "Residential"))
        year_built = st.number_input("Year Built", min_value=1800, max_value=2030,
                                      value=existing.year_built if existing and existing.year_built else 1990)
        status = st.selectbox("Status", ["Measured", "Quoted", "Contracted", "Completed"],
                               index=["Measured", "Quoted", "Contracted", "Completed"]
                               .index(existing.status if existing else "Measured"))

    st.markdown('<div class="section-header">Property Address</div>', unsafe_allow_html=True)

    # ---- Auto-lookup ----
    lookup_col, _ = st.columns([2, 3])
    with lookup_col:
        lookup_address = st.text_input(
            "🔍 Enter address to auto-lookup",
            placeholder="123 Main St, Austin, TX 78701",
            help="Fetches satellite imagery, building footprint, and pre-fills address fields.",
            key="lookup_addr_input",
        )

    lu1, lu2, lu3 = st.columns([1, 1, 4])
    with lu1:
        run_lookup = st.button("🛰️ Auto-Lookup Property", type="primary", use_container_width=True,
                                disabled=not lookup_address)
    with lu2:
        st.caption("Free satellite imagery — no extra API key needed.\nGoogle Maps key = higher resolution.")

    if run_lookup and lookup_address:
        with st.spinner("Geocoding address and fetching satellite imagery..."):
            lresult = lookup_property(
                lookup_address,
                google_api_key=os.getenv("GOOGLE_MAPS_API_KEY") or None,
                mapbox_token=os.getenv("MAPBOX_TOKEN") or None,
            )
        st.session_state["_lookup_result"] = lresult

        if lresult["errors"]:
            for err in lresult["errors"]:
                st.warning(err)

        geo = lresult.get("geo")
        building = lresult.get("building") or {}

        if geo:
            # Auto-fill address fields into session state so they pre-populate below
            st.session_state["_pf_street"] = (
                f"{geo.get('house_number','')} {geo.get('road','')}".strip()
            )
            st.session_state["_pf_city"] = geo.get("city", "")
            st.session_state["_pf_state"] = geo.get("state", "")
            st.session_state["_pf_zip"] = geo.get("zip", "")

            info_parts = [f"📍 **{geo['display_name']}**"]
            if building.get("area_sqft"):
                info_parts.append(f"  Footprint: **{building['area_sqft']:,.0f} sq ft**")
            if building.get("levels"):
                info_parts.append(f"  Stories: **{building['levels']}**")
            if building.get("building_type"):
                info_parts.append(f"  Type: **{building['building_type'].title()}**")
            if building.get("year_built"):
                info_parts.append(f"  Built: **{building['year_built']}**")
            st.success("  |  ".join(info_parts))

            # Pre-fill AI measurements from building data
            if building.get("area_sqft") and building["area_sqft"] > 0:
                if not st.session_state.ai_measurements:
                    from pricing_data import COMPLEXITY_FACTORS, WASTE_FACTORS
                    pm = 1.118
                    sqft = float(building["area_sqft"])
                    meas = RoofMeasurement(
                        total_area_sqft=sqft,
                        total_squares=round(sqft / 100 * pm, 2),
                        pitch="6/12", pitch_multiplier=pm,
                        complexity="Moderate", complexity_factor=1.15,
                        waste_factor_pct=0.13,
                        number_of_stories=building.get("levels") or 1,
                        analysis_source="address_lookup",
                        ai_confidence="Low",
                        notes="Pre-filled from OpenStreetMap building data. Run AI analysis on satellite image for accuracy.",
                    )
                    st.session_state.ai_measurements = meas

        if lresult.get("satellite"):
            st.image(lresult["satellite"], caption="Satellite view (auto-fetched)", use_container_width=True)
        if lresult.get("street_view"):
            st.image(lresult["street_view"], caption="Street view", use_container_width=True)

        # Auto-store fetched images
        if lresult.get("images"):
            st.session_state["_lookup_images"] = lresult["images"]
            st.info(f"✅ {len(lresult['images'])} image(s) fetched — will be saved with the property. "
                    "Click **Analyse Images with AI** below to extract measurements.")
        st.rerun()

    # Show previously fetched lookup images
    _lookup_images = st.session_state.get("_lookup_images", [])
    if _lookup_images:
        with st.expander(f"🛰️ {len(_lookup_images)} auto-fetched image(s)", expanded=False):
            img_cols = st.columns(min(len(_lookup_images), 3))
            for i, (lbl, raw) in enumerate(_lookup_images):
                img_cols[i % 3].image(raw, caption=lbl, use_container_width=True)

    st.divider()

    ad1, ad2, ad3, ad4 = st.columns([3, 2, 1, 1])
    street = ad1.text_input("Street Address",
                             value=st.session_state.get("_pf_street", existing.street_address if existing else ""),
                             key="pf_street")
    city = ad2.text_input("City",
                           value=st.session_state.get("_pf_city", existing.city if existing else ""),
                           key="pf_city")
    state = ad3.text_input("State",
                            value=st.session_state.get("_pf_state", existing.state if existing else ""),
                            key="pf_state")
    zip_code = ad4.text_input("ZIP",
                               value=st.session_state.get("_pf_zip", existing.zip_code if existing else ""),
                               key="pf_zip")

    # ---- Images ----
    st.markdown('<div class="section-header">Property Images</div>', unsafe_allow_html=True)
    st.caption("Upload aerial, satellite, or on-site roof photos. More images = better AI analysis accuracy.")

    uploaded_files = st.file_uploader(
        "Upload additional roof images (JPG/PNG) — optional if auto-lookup already fetched images",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True,
        key="img_uploader",
    )
    new_image_bytes = [(f.name, f.read()) for f in (uploaded_files or [])]

    # Merge: existing DB images + auto-fetched lookup images + manually uploaded
    _lookup_images = st.session_state.get("_lookup_images", [])
    combined_new = _lookup_images + new_image_bytes

    # Show existing images (edit mode)
    if existing_images:
        st.caption(f"{len(existing_images)} existing image(s) on file:")
        img_cols = st.columns(min(len(existing_images), 4))
        for i, (label, raw) in enumerate(existing_images):
            img_cols[i % 4].image(raw, caption=label, use_container_width=True)

    if combined_new:
        st.caption(f"{len(combined_new)} new image(s) ready (auto-fetched + uploaded):")
        img_cols2 = st.columns(min(len(combined_new), 4))
        for i, (name, raw) in enumerate(combined_new):
            img_cols2[i % 4].image(raw, caption=name, use_container_width=True)

    # ---- AI Analysis ----
    st.markdown('<div class="section-header">AI Roof Analysis</div>', unsafe_allow_html=True)
    all_raw_images = [raw for _, raw in (existing_images + combined_new)]
    full_address = f"{street}, {city}, {state} {zip_code}".strip(", ")

    ai_col1, ai_col2 = st.columns(2)
    with ai_col1:
        if all_raw_images:
            if st.button("🔍 Analyse Images with AI", use_container_width=True, type="secondary"):
                if not os.getenv("ANTHROPIC_API_KEY"):
                    st.error("Add your Anthropic API key in Settings first.")
                else:
                    with st.spinner("Claude is analysing your roof images..."):
                        meas = analyse_multiple_images(all_raw_images)
                        meas.analysis_source = "image_upload"
                    st.session_state.ai_measurements = meas
                    st.success(f"Analysis complete! Confidence: **{meas.ai_confidence}** — review and edit below.")
                    st.rerun()
        else:
            st.info("Upload images above to enable AI analysis.", icon="📷")

    with ai_col2:
        if full_address.strip(", "):
            if st.button("📍 Estimate from Address", use_container_width=True, type="secondary"):
                if not os.getenv("ANTHROPIC_API_KEY"):
                    st.error("Add your Anthropic API key in Settings first.")
                else:
                    with st.spinner("Estimating from address (low accuracy without imagery)..."):
                        meas = estimate_from_address(full_address)
                    st.session_state.ai_measurements = meas
                    st.warning("Address-based estimate — confidence is Low. Review and edit all fields below.")
                    st.rerun()

    if st.session_state.ai_measurements:
        m = st.session_state.ai_measurements
        st.success(
            f"✅ AI results imported below — source: **{m.analysis_source}**, "
            f"confidence: **{m.ai_confidence}**. Edit any field before saving."
        )

    # ---- Measurement Form ----
    init_meas = st.session_state.ai_measurements or (existing.roof_measurement if existing else None)
    meas_dict = _measurement_form("prop", init_meas)

    # ---- Notes ----
    prop_notes = st.text_area(
        "Property Notes",
        value=existing.property_notes if existing else "",
        height=80,
    )

    # ---- Save / Actions ----
    st.divider()
    save_col, back_col = st.columns([1, 4])

    with save_col:
        if st.button("💾 Save Property", type="primary", use_container_width=True):
            now = _now()
            prop_id = existing.property_id if existing else str(uuid.uuid4())[:8].upper()
            created = existing.created_at if existing else now

            prop = Property(
                property_id=prop_id,
                created_at=created,
                updated_at=now,
                status=status,
                owner_name=owner_name,
                owner_phone=owner_phone,
                owner_email=owner_email,
                street_address=street,
                city=city,
                state=state,
                zip_code=zip_code,
                property_type=prop_type,
                year_built=year_built if year_built else None,
                roof_measurement=RoofMeasurement(**meas_dict) if meas_dict["total_area_sqft"] else None,
                image_count=len(all_raw_images),
                property_notes=prop_notes,
            )
            db.save_property(prop)

            # Save images (existing + auto-fetched + manually uploaded)
            all_to_store = existing_images + combined_new
            if all_to_store:
                db.save_images(prop_id, all_to_store)
            # Clear lookup state after saving
            for k in ("_lookup_result", "_lookup_images", "_pf_street",
                      "_pf_city", "_pf_state", "_pf_zip"):
                st.session_state.pop(k, None)

            st.success(f"Property saved! ID: {prop_id}")
            _set_view("property_detail", prop_id)
            st.rerun()

    with back_col:
        if st.button("← Back to list"):
            _set_view("list")
            st.rerun()


# ==================================================================
# VIEW: Property Detail
# ==================================================================

def view_property_detail():
    pid = st.session_state.selected_pid
    prop = db.get_property(pid)
    if not prop:
        st.error("Property not found.")
        _set_view("list")
        return

    images = db.get_images(pid)
    m = prop.roof_measurement

    # Header
    st.markdown(
        f"## {prop.full_address or prop.owner_name}  "
        f"{_badge(prop.status)}",
        unsafe_allow_html=True,
    )
    st.caption(
        f"Owner: {prop.owner_name or '—'}  |  "
        f"{prop.property_type}  |  "
        f"Added: {prop.created_at[:10]}"
    )

    # Action bar
    ac1, ac2, ac3, ac4, ac5 = st.columns(5)
    with ac1:
        if st.button("✏️ Edit Property", use_container_width=True):
            _set_view("edit_property", pid)
            st.rerun()
    with ac2:
        if st.button("📄 Measurement Report", use_container_width=True):
            with st.spinner("Generating report..."):
                pdf = generate_measurement_report(
                    prop, images,
                    company_name=company_name,
                    company_phone=company_phone,
                    company_license=company_license,
                )
                st.session_state.meas_pdf = pdf
            st.rerun()
    with ac3:
        if st.button("💼 Create Quote", use_container_width=True, type="primary"):
            if not m:
                st.error("Save measurements first before creating a quote.")
            else:
                st.session_state.view = "create_quote"
                st.rerun()
    with ac4:
        if st.button("← All Properties", use_container_width=True):
            _set_view("list")
            st.rerun()
    with ac5:
        if st.button("🗑️ Delete", use_container_width=True):
            db.delete_property(pid)
            _set_view("list")
            st.rerun()

    if st.session_state.meas_pdf:
        st.download_button(
            "⬇️ Download Measurement Report PDF",
            data=st.session_state.meas_pdf,
            file_name=f"measurement_report_{pid}.pdf",
            mime="application/pdf",
        )

    st.divider()

    tab_meas, tab_images, tab_info = st.tabs(["📐 Measurements", "🖼️ Images", "ℹ️ Property Info"])

    # ------ Measurements tab ------
    with tab_meas:
        if not m:
            st.info("No measurements yet. Click **✏️ Edit Property** to add them.")
        else:
            adj_sq = round(m.total_squares * m.pitch_multiplier * (1 + m.waste_factor_pct), 2)
            src_map = {
                "image_upload": "🔍 AI — Image Upload",
                "address_lookup": "📍 AI — Address Estimate",
                "manual_input": "✋ Manual Entry",
            }
            st.caption(
                f"Source: {src_map.get(m.analysis_source, m.analysis_source)}  |  "
                f"Confidence: {m.ai_confidence or '—'}"
            )

            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.metric("Footprint Area", f"{m.total_area_sqft:,.0f} sq ft")
            mc2.metric("Total Squares", f"{m.total_squares:.2f} sq")
            mc3.metric("Adjusted Squares", f"{adj_sq:.2f} sq")
            mc4.metric("Pitch", m.pitch)

            mc5, mc6, mc7, mc8 = st.columns(4)
            mc5.metric("Complexity", m.complexity)
            mc6.metric("Stories", m.number_of_stories)
            mc7.metric("Existing Layers", m.layers_existing)
            mc8.metric("Waste Factor", f"{m.waste_factor_pct * 100:.0f}%")

            st.markdown("**Linear Footage**")
            lf_data = {
                "Feature": ["Perimeter", "Ridges", "Valleys", "Hips", "Eaves"],
                "Length (LF)": [
                    f"{m.perimeter_lf:.1f}",
                    f"{m.ridges_lf:.1f}",
                    f"{m.valleys_lf:.1f}",
                    f"{m.hips_lf:.1f}",
                    f"{m.eaves_lf:.1f}",
                ],
            }
            st.dataframe(pd.DataFrame(lf_data), use_container_width=False, hide_index=True)

            if m.notes:
                st.markdown(f"**Notes:** {m.notes}")

    # ------ Images tab ------
    with tab_images:
        if not images:
            st.info("No images on file. Edit the property to upload images.")
        else:
            cols = st.columns(min(len(images), 3))
            for i, (label, raw) in enumerate(images):
                cols[i % 3].image(raw, caption=label, use_container_width=True)

    # ------ Info tab ------
    with tab_info:
        info_data = {
            "Field": ["Property ID", "Owner", "Phone", "Email",
                       "Type", "Year Built", "Status", "Created", "Updated"],
            "Value": [
                prop.property_id, prop.owner_name or "—", prop.owner_phone or "—",
                prop.owner_email or "—", prop.property_type,
                str(prop.year_built) if prop.year_built else "—",
                prop.status, prop.created_at[:10], prop.updated_at[:10],
            ],
        }
        st.dataframe(pd.DataFrame(info_data), use_container_width=False, hide_index=True)
        if prop.property_notes:
            st.markdown(f"**Notes:** {prop.property_notes}")


# ==================================================================
# VIEW: Create Quote (from saved property)
# ==================================================================

def view_create_quote():
    pid = st.session_state.selected_pid
    prop = db.get_property(pid)
    if not prop or not prop.roof_measurement:
        st.error("No measurements found. Save measurements first.")
        _set_view("list")
        return

    st.markdown(f"## 💼 Create Quote — {prop.full_address}")

    if st.button("← Back to Property"):
        st.session_state.view = "property_detail"
        st.rerun()

    st.divider()

    # Material + region
    mat_display = {mat.name: slug for slug, mat in MATERIAL_OPTIONS.items()}
    selected_mat_name = st.radio("Select Material", list(mat_display.keys()),
                                  index=1, horizontal=True)
    selected_slug = mat_display[selected_mat_name]
    mat = MATERIAL_OPTIONS[selected_slug]

    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("Material / sq", f"${mat.material_cost_per_square:,.0f}")
    mc2.metric("Labor / sq", f"${mat.labor_cost_per_square:,.0f}")
    mc3.metric("Warranty", f"{mat.warranty_years} yrs")
    mc4.metric("Lifespan", f"{mat.lifespan_years} yrs")
    st.caption(mat.description)

    region = st.selectbox("Region / Market", list(REGIONAL_LABOR_MULTIPLIERS.keys()), index=3)

    if st.button("⚡ Generate Quote", type="primary"):
        with st.spinner("Generating quote..."):
            quote = generate_quote(
                prop=prop,
                material_slug=selected_slug,
                region=region,
                company_info={"name": company_name, "phone": company_phone, "license": company_license},
                tax_rate=tax_rate,
            )
            st.session_state.quote_preview = quote
            st.session_state.quote_pdf = None
        st.rerun()

    if st.session_state.quote_preview:
        q = st.session_state.quote_preview
        m = q.roof_measurement
        st.divider()
        st.success(f"Quote #{q.quote_id}  —  Valid until {q.validity_date}")

        if q.scope_of_work:
            st.markdown(f"*{q.scope_of_work}*")

        df = pd.DataFrame([
            {"Category": i.category, "Description": i.description,
             "Qty": f"{i.quantity:.2f}", "Unit": i.unit,
             "Unit Price": f"${i.unit_price:,.2f}", "Total": f"${i.total:,.2f}"}
            for i in q.line_items
        ])
        st.dataframe(df, use_container_width=True, hide_index=True)

        tc1, tc2, tc3 = st.columns(3)
        tc1.metric("Subtotal", f"${q.subtotal:,.2f}")
        tc2.metric(f"Tax ({q.tax_rate*100:.1f}%)", f"${q.tax_amount:,.2f}")
        tc3.metric("TOTAL", f"${q.total:,.2f}")

        qp1, qp2 = st.columns(2)
        with qp1:
            if st.button("📄 Build Quote PDF", use_container_width=True):
                with st.spinner("Rendering PDF..."):
                    st.session_state.quote_pdf = generate_quote_pdf(
                        q, company_name, company_phone, company_license
                    )
                st.rerun()
        if st.session_state.quote_pdf:
            with qp2:
                st.download_button(
                    "⬇️ Download Quote PDF",
                    data=st.session_state.quote_pdf,
                    file_name=f"quote_{q.quote_id}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )


# ==================================================================
# Router
# ==================================================================

view = st.session_state.view

if view == "list":
    view_list()
elif view in ("new_property", "edit_property"):
    view_new_or_edit()
elif view == "property_detail":
    view_property_detail()
elif view == "create_quote":
    view_create_quote()
else:
    view_list()
