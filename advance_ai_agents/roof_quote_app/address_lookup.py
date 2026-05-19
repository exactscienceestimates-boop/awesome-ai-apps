"""
Address-based property lookup — no paid API key required for core functionality.

Services used:
  - Nominatim (OpenStreetMap) — geocoding, free, no key
  - ESRI World Imagery tiles   — satellite imagery, free, no key
  - OSM Overpass API           — building footprint + metadata, free, no key
  - Google Maps Static API     — optional higher-res satellite (GOOGLE_MAPS_API_KEY)
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
        errors     : list of error strings
    """
    errors = []
    result = {
        "geo": None,
        "building": None,
        "satellite": None,
        "street_view": None,
        "images": [],
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

    # 3. Satellite image — prefer Google > Mapbox > ESRI
    satellite_bytes = None
    if google_api_key:
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

    return result
