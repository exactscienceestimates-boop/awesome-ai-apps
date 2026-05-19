"""
Address-based property lookup — no paid API key required for core functionality.

Services used:
  - Nominatim (OpenStreetMap) — geocoding, free, no key
  - ESRI World Imagery tiles   — satellite imagery, free, no key
  - OSM Overpass API           — building footprint + metadata, free, no key
  - Nearmap Tiles + AI         — highest-res aerial + AI roof measurements (NEARMAP_API_KEY)
  - Google Maps Static API     — optional high-res satellite (GOOGLE_MAPS_API_KEY)
  - Mapbox Static Images       — optional alternative satellite (MAPBOX_TOKEN)
"""

import io
import math
import time
import requests
from PIL import Image as PILImage

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
CENSUS_GEOCODE_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
ESRI_TILE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
NEARMAP_TILE_URL = "https://api.nearmap.com/tiles/v3/Vert/{z}/{x}/{y}.img"
NEARMAP_AI_URL = "https://api.nearmap.com/ai/features/v4/features.json"
HEADERS = {"User-Agent": "RoofMeasurementCRM/1.0 contact@roofer.app"}


# ------------------------------------------------------------------
# Geocoding
# ------------------------------------------------------------------

def geocode_address(address: str) -> dict:
    """
    Geocode an address. Tries Nominatim first, falls back to US Census Geocoder.
    Returns dict with lat, lng, and parsed address components.
    Raises ValueError if the address cannot be found.
    """
    # Try Nominatim (global, works for any country)
    try:
        return _geocode_nominatim(address)
    except Exception:
        pass

    # Fallback: US Census Geocoder (US addresses only, very permissive on servers)
    try:
        return _geocode_census(address)
    except Exception as e:
        raise ValueError(
            f"Could not geocode '{address}'. "
            "Try a more complete address including city and state. "
            f"Detail: {e}"
        )


def _geocode_nominatim(address: str) -> dict:
    params = {"q": address, "format": "json", "limit": 1, "addressdetails": 1}
    resp = requests.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=12)
    resp.raise_for_status()
    results = resp.json()
    if not results:
        raise ValueError("Not found")
    r = results[0]
    addr = r.get("address", {})
    return {
        "lat": float(r["lat"]),
        "lng": float(r["lon"]),
        "display_name": r.get("display_name", ""),
        "house_number": addr.get("house_number", ""),
        "road": addr.get("road", ""),
        "city": (addr.get("city") or addr.get("town") or addr.get("village")
                 or addr.get("municipality") or ""),
        "county": addr.get("county", ""),
        "state": addr.get("state", ""),
        "zip": addr.get("postcode", ""),
        "country": addr.get("country", ""),
        "country_code": addr.get("country_code", "").upper(),
    }


def _geocode_census(address: str) -> dict:
    """US Census Bureau geocoder — no API key, permissive, US only."""
    params = {
        "address": address,
        "benchmark": "Public_AR_Current",
        "format": "json",
    }
    resp = requests.get(CENSUS_GEOCODE_URL, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    matches = data.get("result", {}).get("addressMatches", [])
    if not matches:
        raise ValueError("Not found in Census geocoder")
    m = matches[0]
    coords = m.get("coordinates", {})
    addr = m.get("addressComponents", {})
    city = addr.get("city", "") or addr.get("unincorporatedPlace", "")
    return {
        "lat": float(coords.get("y", 0)),
        "lng": float(coords.get("x", 0)),
        "display_name": m.get("matchedAddress", address),
        "house_number": addr.get("fromAddress", "").split("-")[0],
        "road": addr.get("streetName", ""),
        "city": city,
        "county": "",
        "state": addr.get("state", ""),
        "zip": addr.get("zip", ""),
        "country": "United States",
        "country_code": "US",
    }


# ------------------------------------------------------------------
# Satellite imagery
# ------------------------------------------------------------------

def _latlng_to_tile(lat: float, lng: float, zoom: int) -> tuple[int, int]:
    """Convert WGS-84 coordinates to XYZ tile indices."""
    x = int((lng + 180) / 360 * (2 ** zoom))
    lat_r = math.radians(lat)
    y = int((1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * (2 ** zoom))
    return x, y


def _fetch_esri_tile(z: int, x: int, y: int) -> PILImage.Image | None:
    url = ESRI_TILE_URL.format(z=z, x=x, y=y)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            return PILImage.open(io.BytesIO(resp.content)).convert("RGB")
    except Exception:
        pass
    return None


def fetch_satellite_image_esri(lat: float, lng: float, zoom: int = 19, grid: int = 3) -> bytes:
    """
    Compose a satellite image from ESRI World Imagery tiles.
    Fetches a grid×grid tile grid, crops to the area around the target point.
    No API key required.
    """
    cx, cy = _latlng_to_tile(lat, lng, zoom)
    tile_px = 256
    half = grid // 2

    canvas = PILImage.new("RGB", (tile_px * grid, tile_px * grid), (40, 40, 40))

    for row in range(grid):
        for col in range(grid):
            tx = cx + (col - half)
            ty = cy + (row - half)
            tile = _fetch_esri_tile(zoom, tx, ty)
            if tile:
                canvas.paste(tile, (col * tile_px, row * tile_px))
            time.sleep(0.05)  # polite pacing

    # Crop to a tighter centre window (the exact target tile + a little context)
    target_col = half
    target_row = half
    pad = tile_px // 4
    left = target_col * tile_px - pad
    top = target_row * tile_px - pad
    right = left + tile_px + pad * 2
    bottom = top + tile_px + pad * 2
    cropped = canvas.crop((
        max(left, 0), max(top, 0),
        min(right, canvas.width), min(bottom, canvas.height),
    ))
    # Scale up so Claude vision has enough pixels
    final = cropped.resize((640, 640), PILImage.LANCZOS)

    buf = io.BytesIO()
    final.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def fetch_satellite_image_google(lat: float, lng: float, api_key: str,
                                  zoom: int = 20, size: str = "640x640") -> bytes:
    """Google Maps Static API — higher resolution, requires GOOGLE_MAPS_API_KEY."""
    url = "https://maps.googleapis.com/maps/api/staticmap"
    params = {
        "center": f"{lat},{lng}",
        "zoom": zoom,
        "size": size,
        "maptype": "satellite",
        "key": api_key,
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.content


def fetch_street_view_google(lat: float, lng: float, api_key: str) -> bytes | None:
    """Google Street View Static API — front-elevation photo."""
    url = "https://maps.googleapis.com/maps/api/streetview"
    params = {
        "size": "640x480",
        "location": f"{lat},{lng}",
        "pitch": "5",
        "fov": "90",
        "key": api_key,
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200 and "image" in resp.headers.get("content-type", ""):
            return resp.content
    except Exception:
        pass
    return None


def fetch_satellite_image_mapbox(lat: float, lng: float, token: str, zoom: int = 19) -> bytes:
    """Mapbox Static Images — free tier, requires MAPBOX_TOKEN."""
    url = (
        f"https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/"
        f"{lng},{lat},{zoom}/640x640@2x"
    )
    resp = requests.get(url, params={"access_token": token}, timeout=15)
    resp.raise_for_status()
    return resp.content


def fetch_satellite_image_nearmap(lat: float, lng: float, api_key: str,
                                   zoom: int = 20, grid: int = 3) -> bytes:
    """
    Nearmap vertical aerial imagery — highest resolution (5–7.5 cm/px).
    Uses the same XYZ tile compositing approach as ESRI.
    Requires a Nearmap API key.
    """
    cx, cy = _latlng_to_tile(lat, lng, zoom)
    tile_px = 256
    half = grid // 2

    canvas = PILImage.new("RGB", (tile_px * grid, tile_px * grid), (40, 40, 40))

    for row in range(grid):
        for col in range(grid):
            tx = cx + (col - half)
            ty = cy + (row - half)
            url = NEARMAP_TILE_URL.format(z=zoom, x=tx, y=ty)
            try:
                resp = requests.get(url, params={"apikey": api_key},
                                    headers=HEADERS, timeout=10)
                if resp.status_code == 200:
                    tile = PILImage.open(io.BytesIO(resp.content)).convert("RGB")
                    canvas.paste(tile, (col * tile_px, row * tile_px))
            except Exception:
                pass
            time.sleep(0.05)

    target_col = half
    target_row = half
    pad = tile_px // 4
    left = target_col * tile_px - pad
    top = target_row * tile_px - pad
    right = left + tile_px + pad * 2
    bottom = top + tile_px + pad * 2
    cropped = canvas.crop((
        max(left, 0), max(top, 0),
        min(right, canvas.width), min(bottom, canvas.height),
    ))
    final = cropped.resize((640, 640), PILImage.LANCZOS)

    buf = io.BytesIO()
    final.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _bounding_box_wkt(lat: float, lng: float, radius_m: float = 70) -> str:
    """WKT polygon bounding box around a coordinate point."""
    dlat = radius_m / 111_320.0
    dlng = radius_m / (111_320.0 * math.cos(math.radians(lat)))
    min_lat, max_lat = lat - dlat, lat + dlat
    min_lng, max_lng = lng - dlng, lng + dlng
    return (
        f"POLYGON(({min_lng:.7f} {min_lat:.7f},"
        f"{max_lng:.7f} {min_lat:.7f},"
        f"{max_lng:.7f} {max_lat:.7f},"
        f"{min_lng:.7f} {max_lat:.7f},"
        f"{min_lng:.7f} {min_lat:.7f}))"
    )


def _pitch_degrees_to_fraction(degrees: float) -> str:
    """Convert pitch angle in degrees to the nearest 'rise/12' string."""
    rise = math.tan(math.radians(float(degrees))) * 12
    nearest = max(2, min(12, round(rise)))
    return f"{nearest}/12"


def fetch_nearmap_ai_features(lat: float, lng: float, api_key: str) -> dict:
    """
    Query Nearmap AI Features API for roof measurements.
    Returns a measurement-compatible dict on success, or {"error": "..."} on failure.
    Requires the 'roofdetection' pack in your Nearmap subscription.
    """
    polygon = _bounding_box_wkt(lat, lng, radius_m=70)
    params = {
        "polygon": polygon,
        "packs": "roofdetection",
        "apikey": api_key,
    }
    try:
        resp = requests.get(NEARMAP_AI_URL, params=params, headers=HEADERS, timeout=25)
        if resp.status_code in (402, 403):
            return {
                "error": (
                    f"Nearmap AI unavailable (HTTP {resp.status_code}). "
                    "Your plan may not include the roofdetection pack — "
                    "aerial imagery will still be used for Claude vision analysis."
                )
            }
        if resp.status_code == 404:
            return {"error": "No Nearmap AI coverage at this location."}
        resp.raise_for_status()
        return _parse_nearmap_ai_features(resp.json())
    except Exception as exc:
        return {"error": f"Nearmap AI request failed: {str(exc)[:200]}"}


def _parse_nearmap_ai_features(data: dict) -> dict:
    """Parse Nearmap AI GeoJSON FeatureCollection into a measurement-compatible dict."""
    features = data.get("features", [])
    if not features:
        return {"error": "No AI features returned for this location."}

    total_slope_sqft = 0.0
    ridges_lf = 0.0
    valleys_lf = 0.0
    hips_lf = 0.0
    eaves_lf = 0.0
    rakes_lf = 0.0
    perimeter_lf = 0.0
    pitch_degrees: list[float] = []
    num_facets = 0

    for feat in features:
        props = feat.get("properties", {})
        ftype = (props.get("type") or props.get("featureType") or "").lower()

        if "rooffacet" in ftype or "roof_facet" in ftype or "roofsurface" in ftype:
            area_sqm = float(props.get("areaSqm") or props.get("area_sqm") or 0)
            total_slope_sqft += area_sqm * 10.7639
            num_facets += 1
            p = props.get("pitch") or props.get("pitchDeg") or props.get("pitch_degrees")
            if p:
                pitch_degrees.append(float(p))

        elif "roofoutline" in ftype or "roof_outline" in ftype:
            p_m = float(props.get("perimeterM") or props.get("perimeter_m") or 0)
            if p_m:
                perimeter_lf = p_m * 3.28084
            # Use outline area only if facets gave us nothing
            if total_slope_sqft == 0:
                area_sqm = float(props.get("areaSqm") or props.get("area_sqm") or 0)
                total_slope_sqft = area_sqm * 10.7639

        elif "ridge" in ftype:
            ridges_lf += float(props.get("lengthM") or props.get("length_m") or 0) * 3.28084
        elif "valley" in ftype:
            valleys_lf += float(props.get("lengthM") or props.get("length_m") or 0) * 3.28084
        elif "hip" in ftype:
            hips_lf += float(props.get("lengthM") or props.get("length_m") or 0) * 3.28084
        elif "eave" in ftype:
            eaves_lf += float(props.get("lengthM") or props.get("length_m") or 0) * 3.28084
        elif "rake" in ftype:
            rakes_lf += float(props.get("lengthM") or props.get("length_m") or 0) * 3.28084

    if total_slope_sqft < 50:
        return {"error": "Insufficient roof area data from Nearmap AI."}

    avg_pitch_deg = sum(pitch_degrees) / len(pitch_degrees) if pitch_degrees else 26.57
    pitch_str = _pitch_degrees_to_fraction(avg_pitch_deg)

    if perimeter_lf == 0:
        perimeter_lf = eaves_lf + rakes_lf

    if num_facets <= 2:
        complexity = "Simple"
    elif num_facets <= 5:
        complexity = "Moderate"
    elif num_facets <= 9:
        complexity = "Complex"
    else:
        complexity = "Very Complex"

    notes = (
        f"Nearmap AI: {num_facets} roof facet(s), "
        f"avg pitch {avg_pitch_deg:.1f}° ≈ {pitch_str}."
    )

    return {
        "total_slope_sqft": round(total_slope_sqft, 0),
        "pitch": pitch_str,
        "complexity": complexity,
        "ridges_lf": round(ridges_lf, 1),
        "valleys_lf": round(valleys_lf, 1),
        "hips_lf": round(hips_lf, 1),
        "eaves_lf": round(eaves_lf, 1),
        "perimeter_lf": round(perimeter_lf, 1),
        "analysis_source": "nearmap_ai",
        "ai_confidence": "High",
        "notes": notes,
    }


# ------------------------------------------------------------------
# Building footprint from OpenStreetMap
# ------------------------------------------------------------------

def fetch_building_data(lat: float, lng: float, radius: int = 40) -> dict:
    """
    Query OSM Overpass for the nearest building and return footprint + metadata.
    All free, no API key required.
    """
    query = f"""
[out:json][timeout:12];
(
  way["building"](around:{radius},{lat},{lng});
  relation["building"](around:{radius},{lat},{lng});
);
out body;
>;
out skel qt;
"""
    result = {
        "area_sqft": None,
        "area_sqm": None,
        "building_type": None,
        "levels": None,
        "height_m": None,
        "year_built": None,
        "name": None,
    }
    try:
        resp = requests.post(OVERPASS_URL, data={"data": query},
                              headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        elements = data.get("elements", [])

        nodes = {e["id"]: (float(e["lat"]), float(e["lon"]))
                 for e in elements if e["type"] == "node"}
        ways = [e for e in elements
                if e["type"] == "way" and "building" in e.get("tags", {})]

        if not ways:
            return result

        # Pick the way whose centroid is closest to the query point
        def _way_distance(way):
            pts = [nodes[n] for n in way.get("nodes", []) if n in nodes]
            if not pts:
                return float("inf")
            clat = sum(p[0] for p in pts) / len(pts)
            clng = sum(p[1] for p in pts) / len(pts)
            return (clat - lat) ** 2 + (clng - lng) ** 2

        way = min(ways, key=_way_distance)
        tags = way.get("tags", {})
        node_refs = way.get("nodes", [])
        coords = [nodes[n] for n in node_refs if n in nodes]

        if len(coords) >= 3:
            area_sqm = _polygon_area_sqm(coords)
            result["area_sqm"] = round(area_sqm, 1)
            result["area_sqft"] = round(area_sqm * 10.7639, 0)

        levels_raw = tags.get("building:levels") or tags.get("levels")
        if levels_raw:
            try:
                result["levels"] = int(float(levels_raw))
            except ValueError:
                pass

        height_raw = tags.get("height") or tags.get("building:height")
        if height_raw:
            try:
                result["height_m"] = float(str(height_raw).replace("m", "").strip())
            except ValueError:
                pass

        result["building_type"] = (
            tags.get("building:use") or tags.get("building") or "residential"
        )
        result["year_built"] = tags.get("start_date") or tags.get("year_built")
        result["name"] = tags.get("name") or tags.get("addr:housename")

    except Exception:
        pass

    return result


def _polygon_area_sqm(coords: list[tuple[float, float]]) -> float:
    """Shoelace formula on lat/lng coords projected to approximate metres."""
    if len(coords) < 3:
        return 0.0
    lat0 = math.radians(sum(c[0] for c in coords) / len(coords))
    m_per_deg_lat = 111_320.0
    m_per_deg_lng = 111_320.0 * math.cos(lat0)
    pts = [(c[1] * m_per_deg_lng, c[0] * m_per_deg_lat) for c in coords]
    n = len(pts)
    area = abs(sum(
        pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1]
        for i in range(n)
    )) / 2.0
    return area


# ------------------------------------------------------------------
# One-shot property lookup (called from the UI)
# ------------------------------------------------------------------

def lookup_property(
    address: str,
    google_api_key: str = None,
    mapbox_token: str = None,
    nearmap_api_key: str = None,
    satellite_zoom: int = 19,
) -> dict:
    """
    Full property lookup from a single address string.

    Returns:
        geo        : dict with lat, lng, parsed address components
        building   : dict with area_sqft, levels, building_type, year_built
        satellite  : bytes (JPEG) of the satellite image, or None
        street_view: bytes (JPEG) street-level photo, or None
        images     : list of (label, bytes) ready for DB storage
        nearmap_ai : dict with AI roof measurements, or None (requires Nearmap key + roofdetection pack)
        errors     : list of error strings
    """
    errors = []
    result = {
        "geo": None,
        "building": None,
        "satellite": None,
        "street_view": None,
        "images": [],
        "nearmap_ai": None,
        "errors": errors,
    }

    # 1. Geocode
    try:
        geo = geocode_address(address)
        result["geo"] = geo
    except Exception as e:
        errors.append(f"Geocoding failed: {e}")
        return result

    lat, lng = geo["lat"], geo["lng"]

    # 2. Building footprint
    try:
        result["building"] = fetch_building_data(lat, lng)
    except Exception as e:
        errors.append(f"Building data unavailable: {e}")
        result["building"] = {}

    # 3. Satellite image — prefer Nearmap > Google > Mapbox > ESRI
    satellite_bytes = None
    if nearmap_api_key:
        try:
            satellite_bytes = fetch_satellite_image_nearmap(
                lat, lng, nearmap_api_key, zoom=max(satellite_zoom, 20)
            )
            result["images"].append(("Satellite (Nearmap)", satellite_bytes))
        except Exception as e:
            errors.append(f"Nearmap satellite failed: {e}")

    if satellite_bytes is None and google_api_key:
        try:
            satellite_bytes = fetch_satellite_image_google(lat, lng, google_api_key, zoom=satellite_zoom)
            result["images"].append(("Satellite (Google)", satellite_bytes))
        except Exception as e:
            errors.append(f"Google satellite failed: {e}")

    if satellite_bytes is None and mapbox_token:
        try:
            satellite_bytes = fetch_satellite_image_mapbox(lat, lng, mapbox_token, zoom=satellite_zoom)
            result["images"].append(("Satellite (Mapbox)", satellite_bytes))
        except Exception as e:
            errors.append(f"Mapbox satellite failed: {e}")

    if satellite_bytes is None:
        try:
            satellite_bytes = fetch_satellite_image_esri(lat, lng, zoom=satellite_zoom)
            result["images"].append(("Satellite (ESRI)", satellite_bytes))
        except Exception as e:
            errors.append(f"ESRI satellite failed: {e}")

    result["satellite"] = satellite_bytes

    # 4. Street view (Google only)
    if google_api_key:
        try:
            sv = fetch_street_view_google(lat, lng, google_api_key)
            if sv:
                result["street_view"] = sv
                result["images"].append(("Street View", sv))
        except Exception as e:
            errors.append(f"Street view failed: {e}")

    # 5. Nearmap AI roof measurements (separate from imagery)
    if nearmap_api_key:
        nm_ai = fetch_nearmap_ai_features(lat, lng, nearmap_api_key)
        result["nearmap_ai"] = nm_ai
        if nm_ai.get("error"):
            errors.append(f"Nearmap AI: {nm_ai['error']}")

    return result
