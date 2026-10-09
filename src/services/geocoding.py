"""Geocoding, GPS route generation, and smart address cleaning service."""

from __future__ import annotations

import json
import logging
import math
import re
import urllib.parse
import urllib.request
from typing import Tuple

from src.config.settings import get_settings

logger = logging.getLogger(__name__)

# Default center for Mazatlán, Sinaloa, Mexico (Plazuela República / Palacio Municipal)
DEFAULT_LAT = 23.201400
DEFAULT_LNG = -106.421500

# Center for Culiacán, Sinaloa, Mexico (Catedral / Palacio Municipal de Culiacán)
CULIACAN_LAT = 24.809060
CULIACAN_LNG = -107.394020


def clean_address_for_geocoding(address: str) -> list[str]:
    """Generate multiple cleaned variations of an address to maximize geocoding hit rate.

    Strips descriptive landmarks, building colors, references, and landmark notes.
    Yields street+colonia, street without number+colonia, street alone, and colonia alone.
    """
    raw = address.strip()
    if not raw:
        return []

    # 1. Clean common noise separators and reference phrases
    cleaned_main = raw
    noise_patterns = [
        r"\s*-\s*.*$",
        r"\s*\(.*?\)",
        r"\s+ref(?:erencias?|\.)?:?.*$",
        r"\s+frente\s+a\s+.*$",
        r"\s+casi\s+esquina\s+con\s+.*$",
        r"\s+esquina\s+con\s+.*$",
        r"\s+entre\s+.*$",
        r"\s+a\s+espaldas\s+de\s+.*$",
        r"\s+casa\s+(?:de\s+dos\s+pisos|verde|azul|blanca|amarilla|roja|color).*$",
        r"\s+port[oó]n\s+.*$",
        r"\s+reja\s+.*$",
        r"\s+timbre\s+.*$",
    ]
    for pattern in noise_patterns:
        cleaned_main = re.sub(pattern, "", cleaned_main, flags=re.IGNORECASE).strip()

    cleaned_main = re.sub(r"[\(\)\-\,\.]+$", "", cleaned_main).strip()

    variations = []
    if cleaned_main:
        variations.append(cleaned_main)

    # 2. Extract Street + Number and Neighborhood
    parts = [p.strip() for p in cleaned_main.split(",") if p.strip()]
    street_part = parts[0] if parts else cleaned_main
    neigh_part = parts[1] if len(parts) >= 2 else ""

    # Clean 'Col.', 'Fracc.', 'Colonia', 'Fraccionamiento', 'Privada'
    clean_neigh = re.sub(r"\b(?:col\.?|colonia|fracc\.?|fraccionamiento|privada|residencial)\s*", "", neigh_part, flags=re.IGNORECASE).strip()

    # Street without house numbers (e.g. "Misión San Javier 5246" -> "Misión San Javier")
    street_no_num = re.sub(r"\s*#?\s*\d+[\w\-]*", "", street_part).strip()

    # 3. Add clean variations in priority order
    if clean_neigh:
        v1 = f"{street_part}, {clean_neigh}"
        if v1 not in variations:
            variations.append(v1)
        if street_no_num and street_no_num != street_part:
            v2 = f"{street_no_num}, {clean_neigh}"
            if v2 not in variations:
                variations.append(v2)

    if street_part not in variations:
        variations.append(street_part)
    if street_no_num and street_no_num not in variations:
        variations.append(street_no_num)

    if clean_neigh and clean_neigh not in variations:
        variations.append(clean_neigh)

    # 4. Add raw address as fallback
    if raw not in variations:
        variations.append(raw)

    return variations


def calculate_distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate distance in kilometers between two GPS coordinates using Haversine formula."""
    if lat1 is None or lng1 is None or lat2 is None or lng2 is None:
        return 99999.0

    R = 6371.0  # Earth radius in kilometers
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


_geocode_cache: dict[str, Tuple[float, float, str]] = {}


def geocode_address(address: str, city_context: str | None = None) -> Tuple[float, float, str]:
    """Convert an address string into latitude and longitude coordinates.

    Uses smart in-memory caching, multi-candidate Photon Komoot OSM with Nominatim fallback,
    and strict Mexican bounds and city proximity filtering to ensure pinpoint accuracy.
    """
    if not address or not address.strip():
        return DEFAULT_LAT, DEFAULT_LNG, ""

    settings = get_settings()
    city = city_context or settings.default_city or "Mazatlán"
    is_culiacan = "culiac" in city.lower()
    target_lat = CULIACAN_LAT if is_culiacan else DEFAULT_LAT
    target_lng = CULIACAN_LNG if is_culiacan else DEFAULT_LNG
    max_dist_km = 45.0 if is_culiacan else 75.0

    clean_key = f"{address.strip().lower()}::{city.strip().lower()}"
    if clean_key in _geocode_cache:
        return _geocode_cache[clean_key]

    candidates = clean_address_for_geocoding(address)

    # 1. Primary: ESRI ArcGIS World Geocoding (high-precision door / house number resolution in Mexico)
    for cand in candidates[:2]:
        try:
            query = f"{cand}, {city}".strip(", ")
            encoded = urllib.parse.quote(query)
            url = (
                f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
                f"?SingleLine={encoded}&f=json&outFields=Match_addr,Addr_type,Score&location={target_lng:.4f},{target_lat:.4f}&distance=60000&maxLocations=2"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=3.0) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    cands = data.get("candidates", [])
                    if cands:
                        top = cands[0]
                        score = float(top.get("score", 0))
                        loc = top.get("location", {})
                        lat = float(loc.get("y", 0))
                        lng = float(loc.get("x", 0))
                        if lat > 0 and (14.0 <= lat <= 33.0 and -118.0 <= lng <= -86.0):
                            dist_km = calculate_distance_km(lat, lng, target_lat, target_lng)
                            if dist_km < max_dist_km and score >= 60.0:
                                matched_name = top.get("address") or top.get("attributes", {}).get("Match_addr") or address
                                res = (lat, lng, matched_name)
                                _geocode_cache[clean_key] = res
                                addr_type = top.get("attributes", {}).get("Addr_type", "Address")
                                logger.info(f"🎯 Pinpoint High-Precision Geocoded (ArcGIS {addr_type} score={score}) '{cand}' -> ({lat:.5f}, {lng:.5f}) dist={dist_km:.1f}km")
                                return res
        except Exception as e:
            logger.debug(f"ArcGIS geocode attempt failed for candidate '{cand}': {e}")

    # 2. Secondary fallback: Photon Komoot (OSM) with city location bias across all candidates
    for cand in candidates:
        try:
            query = f"{cand}, {city}".strip(", ")
            encoded = urllib.parse.quote(query)
            url = f"https://photon.komoot.io/api/?q={encoded}&lat={target_lat}&lon={target_lng}&limit=3"
            req = urllib.request.Request(url, headers={"User-Agent": "PetroilGasDeliveryAgent/2.0"})
            with urllib.request.urlopen(req, timeout=2.0) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    features = data.get("features", [])
                    for feat in features:
                        coords = feat.get("geometry", {}).get("coordinates", [])
                        props = feat.get("properties", {})
                        if len(coords) >= 2:
                            lng = float(coords[0])
                            lat = float(coords[1])
                            country = str(props.get("country") or "").lower()
                            is_mx = country in ("méxico", "mexico", "mx") or (14.0 <= lat <= 33.0 and -118.0 <= lng <= -86.0)
                            if is_mx and lat > 0:
                                dist_km = calculate_distance_km(lat, lng, target_lat, target_lng)
                                if dist_km < max_dist_km:
                                    res = (lat, lng, address)
                                    _geocode_cache[clean_key] = res
                                    logger.info(f"✅ Pinpoint Geocoded (Photon) '{cand}' -> ({lat:.5f}, {lng:.5f}) dist={dist_km:.1f}km")
                                    return res
        except Exception as e:
            logger.debug(f"Photon geocode attempt failed for candidate '{cand}': {e}")

    # 3. Fallback to OpenStreetMap Nominatim with 2.5s timeout across candidates
    for cand in candidates[:3]:
        try:
            query = f"{cand}, {city}".strip(", ")
            encoded_query = urllib.parse.quote(query)
            url = f"https://nominatim.openstreetmap.org/search?q={encoded_query}&countrycodes=mx&format=json&limit=2"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "PetroilGasDeliveryAgent/2.0 (contact: soporte@petroil.com.mx)"},
            )
            with urllib.request.urlopen(req, timeout=2.5) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    for item in data:
                        lat = float(item["lat"])
                        lng = float(item["lon"])
                        dist_km = calculate_distance_km(lat, lng, target_lat, target_lng)
                        if dist_km < max_dist_km:
                            display_name = item.get("display_name", address)
                            res = (lat, lng, display_name)
                            _geocode_cache[clean_key] = res
                            logger.info(f"✅ Geocoded (Nominatim) '{cand}' -> ({lat:.5f}, {lng:.5f}) dist={dist_km:.1f}km")
                            return res
        except Exception as e:
            logger.debug(f"Nominatim geocode attempt failed for candidate '{cand}': {e}")

    logger.warning(f"⚠️ Geocoding failed for all candidates of '{address}'. Using city default.")
    fallback_res = (target_lat, target_lng, address)
    _geocode_cache[clean_key] = fallback_res
    return fallback_res


def reverse_geocode(lat: float, lng: float) -> str:
    """Convert latitude and longitude coordinates into a human-readable street address.

    Uses high-speed multi-provider reverse geocoding (Photon Komoot OSM, Nominatim OSM, BigDataCloud).
    Always returns a clean, human-readable street and neighborhood string.
    """
    if lat is None or lng is None:
        return ""

    default_city = "Culiacán" if calculate_distance_km(lat, lng, CULIACAN_LAT, CULIACAN_LNG) < 70.0 else "Mazatlán"

    # Provider 1: ESRI ArcGIS World Reverse Geocoder (High-precision house numbers and street addresses in Mexico)
    try:
        url = f"https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/reverseGeocode?location={lng:.6f},{lat:.6f}&f=json"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        with urllib.request.urlopen(req, timeout=3.5) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                addr_info = data.get("address", {})
                match_addr = addr_info.get("Match_addr") or addr_info.get("LongLabel")
                if match_addr:
                    return str(match_addr).strip()
    except Exception as e:
        logger.debug(f"ArcGIS reverse geocode error for ({lat}, {lng}): {e}")

    # Provider 2: Photon by Komoot (OSM-based fallback)
    try:
        url = f"https://photon.komoot.io/reverse?lat={lat:.6f}&lon={lng:.6f}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
        )
        with urllib.request.urlopen(req, timeout=4) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                features = data.get("features", [])
                if features:
                    props = features[0].get("properties", {})
                    street = props.get("street")
                    housenumber = props.get("housenumber")
                    district = (
                        props.get("district")
                        or props.get("suburb")
                        or props.get("quarter")
                        or props.get("locality")
                    )
                    city = (
                        props.get("city")
                        or props.get("town")
                        or props.get("county")
                        or default_city
                    )
                    name = props.get("name")

                    parts = []
                    if street:
                        if housenumber:
                            parts.append(f"{street} #{housenumber}".strip())
                        elif name and name != street and not str(name).isnumeric():
                            parts.append(f"{street} ({name})".strip())
                        else:
                            parts.append(str(street).strip())
                    elif name:
                        parts.append(str(name).strip())

                    if district:
                        dist_clean = str(district).strip()
                        if not dist_clean.lower().startswith("col.") and not dist_clean.lower().startswith("fracc."):
                            dist_clean = f"Col. {dist_clean}"
                        parts.append(dist_clean)

                    if city:
                        parts.append(str(city).strip())

                    if parts:
                        return ", ".join(parts)
    except Exception as e:
        logger.debug(f"Photon reverse geocode error for ({lat}, {lng}): {e}")

    # Provider 2: OpenStreetMap Nominatim
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat:.6f}&lon={lng:.6f}&format=json&zoom=18&addressdetails=1"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "PetroilGasDeliveryAgent/2.0 (contact: soporte@petroil.com.mx)", "Accept-Language": "es"},
        )
        with urllib.request.urlopen(req, timeout=4) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                addr_info = data.get("address", {})
                road = addr_info.get("road", "")
                house_number = addr_info.get("house_number", "")
                neighbourhood = (
                    addr_info.get("neighbourhood")
                    or addr_info.get("suburb")
                    or addr_info.get("quarter")
                    or addr_info.get("residential", "")
                )
                city = (
                    addr_info.get("city")
                    or addr_info.get("town")
                    or addr_info.get("municipality", default_city)
                )

                parts = []
                if road:
                    parts.append(f"{road} {house_number}".strip())
                if neighbourhood:
                    parts.append(f"Col. {neighbourhood}".strip())
                if city:
                    parts.append(city)

                if parts:
                    return ", ".join(parts)
                display_name = data.get("display_name")
                if display_name:
                    return display_name
    except Exception as e:
        logger.debug(f"Nominatim reverse geocode error for ({lat}, {lng}): {e}")

    # Provider 3: BigDataCloud Reverse Geocoding Client
    try:
        url = f"https://api.bigdatacloud.net/data/reverse-geocode-client?latitude={lat:.6f}&longitude={lng:.6f}&localityLanguage=es"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=4) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                locality = data.get("locality") or data.get("city")
                subdiv = data.get("principalSubdivision")
                if locality:
                    return f"{locality}, {subdiv}" if subdiv else locality
    except Exception as e:
        logger.debug(f"BigDataCloud reverse geocode error for ({lat}, {lng}): {e}")

    return f"Ubicación en {default_city} (GPS: {lat:.4f}, {lng:.4f})"


def resolve_gps_address_to_name(address_str: str) -> str:
    """If an address string is formatted as raw coordinates or 'Ubicación GPS (lat, lng)...',
    reverse geocodes it into a human-readable street and neighborhood name while preserving any client notes."""
    if not address_str or not isinstance(address_str, str):
        return address_str or ""

    raw = address_str.strip()

    # Match patterns like:
    # 'Ubicación GPS (23.19957, -106.42363) - Edificio color amarillo'
    # 'Ubicacion GPS: 23.19957, -106.42363'
    # 'GPS (23.19957, -106.42363)'
    # '23.19957, -106.42363'
    pattern = r"^(?:Ubicaci[oó]n(?:\s+GPS)?|GPS)?\s*[\:\(]?\s*(-?\d{1,3}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)\s*[\)]?(.*)$"
    m = re.match(pattern, raw, re.IGNORECASE)
    if m:
        try:
            lat = float(m.group(1))
            lng = float(m.group(2))
            if -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0:
                extra = m.group(3).strip() if m.group(3) else ""
                extra = re.sub(r"^[\s\-\,\:\;]+", "", extra).strip()

                resolved = reverse_geocode(lat, lng)
                if resolved and not resolved.lower().startswith("ubicación en mazatlán (gps:"):
                    if extra:
                        return f"{resolved} - {extra}"
                    return resolved
        except Exception as e:
            logger.warning(f"Error resolving GPS address '{address_str}': {e}")

    return raw


def get_google_maps_url(lat: float | None, lng: float | None, query_fallback: str = "") -> str:
    """Generate Google Maps directions URL for the driver.

    If query_fallback has a structured address, Google Maps text query is used so Google Maps
    pinpoints the exact house number & building on the map.
    If exact GPS was provided via device GPS sharing, coordinates are used.
    """
    cands = clean_address_for_geocoding(query_fallback) if query_fallback else []
    clean_addr = cands[0] if cands else ""
    is_gps_text = clean_addr.lower().startswith("ubicación gps") or clean_addr.lower().startswith("ubicacion gps")

    if clean_addr and not is_gps_text:
        query = clean_addr
        if "mazatl" not in query.lower():
            query = f"{query}, Mazatlán, Sinaloa, México"
        encoded = urllib.parse.quote(query)
        return f"https://www.google.com/maps/dir/?api=1&destination={encoded}&travelmode=driving"

    if lat is not None and lng is not None and lat != 0.0:
        return f"https://www.google.com/maps/dir/?api=1&destination={lat:.6f},{lng:.6f}&travelmode=driving"
    return "https://www.google.com/maps"


def get_waze_url(lat: float | None, lng: float | None, query_fallback: str = "") -> str:
    """Generate Waze navigation URL for the driver."""
    cands = clean_address_for_geocoding(query_fallback) if query_fallback else []
    clean_addr = cands[0] if cands else ""
    is_gps_text = clean_addr.lower().startswith("ubicación gps") or clean_addr.lower().startswith("ubicacion gps")

    if clean_addr and not is_gps_text:
        query = clean_addr
        if "mazatl" not in query.lower():
            query = f"{query}, Mazatlán, Sinaloa"
        encoded = urllib.parse.quote(query)
        return f"https://waze.com/ul?q={encoded}&navigate=yes"

    if lat is not None and lng is not None and lat != 0.0 and lat != DEFAULT_LAT:
        return f"https://waze.com/ul?ll={lat:.6f},{lng:.6f}&navigate=yes"
    return "https://waze.com"


def get_apple_maps_url(lat: float, lng: float) -> str:
    """Generate Apple Maps navigation URL."""
    if lat is not None and lng is not None and lat != 0.0:
        return f"https://maps.apple.com/?daddr={lat:.6f},{lng:.6f}&dirflg=d"
    return "https://maps.apple.com"
