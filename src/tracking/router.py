"""Interactive real-time GPS live tracking page for customers (Messenger, Web, WhatsApp)."""

import json
import math
from typing import Any
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from src.config.settings import get_settings
from src.repositories import get_repository

router = APIRouter(tags=["Tracking"])


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in kilometers between two GPS coordinates."""
    r = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


@router.get("/api/tracking/{order_id}")
async def get_tracking_data(order_id: str, tenant_id: str = "petroil") -> dict[str, Any]:
    """Return JSON with real-time driver coordinates, destination, and order progress."""
    repo = get_repository()
    order = repo.get_order_by_id(tenant_id, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    driver = repo.get_driver(order.driver_id) if order.driver_id else None

    # Resolve driver coordinates
    driver_lat = None
    driver_lng = None
    if driver:
        driver_lat = getattr(driver, "current_lat", None)
        driver_lng = getattr(driver, "current_lng", None)
        if driver_lat is None and hasattr(repo, "_driver_locations"):
            cached_loc = repo._driver_locations.get(str(driver.id)) or repo._driver_locations.get(str(driver.telegram_user_id))
            if cached_loc:
                driver_lat, driver_lng = cached_loc

    # Fallback coordinates if driver not yet geolocated: center of Mazatlán
    if driver_lat is None or driver_lng is None:
        driver_lat = 23.2339
        driver_lng = -106.4236

    dest_lat = order.delivery_lat or 23.2435
    dest_lng = order.delivery_lng or -106.4123

    distance_km = _haversine_km(driver_lat, driver_lng, dest_lat, dest_lng)
    # Estimate time at 25 km/h urban speed
    eta_mins = max(1, int(round((distance_km / 25.0) * 60)))

    # Google Maps navigation URL
    gmaps_nav_url = (
        f"https://www.google.com/maps/dir/?api=1"
        f"&origin={driver_lat:.6f},{driver_lng:.6f}"
        f"&destination={dest_lat:.6f},{dest_lng:.6f}"
        f"&travelmode=driving"
    )

    return {
        "ok": True,
        "order_id": order.id,
        "status": order.status,
        "customer_name": order.customer_name,
        "delivery_address": order.delivery_address,
        "total_amount": order.total_amount,
        "payment_method": order.payment_method,
        "destination": {
            "lat": dest_lat,
            "lng": dest_lng,
        },
        "driver": {
            "name": driver.name if driver else "Repartidor Petroil",
            "phone": driver.phone if driver else "",
            "vehicle_plate": getattr(driver, "vehicle_plate", None) or "Unidad de Reparto",
            "lat": driver_lat,
            "lng": driver_lng,
        },
        "distance_km": round(distance_km, 2),
        "eta_minutes": eta_mins,
        "google_maps_url": gmaps_nav_url,
    }


@router.get("/tracking/{order_id}", response_class=HTMLResponse)
async def live_tracking_page(order_id: str, tenant_id: str = "petroil") -> HTMLResponse:
    """Render a mobile-first, real-time animated tracking map with live updating driver point.
    If the order is already delivered, renders a dedicated completion receipt card.
    """
    repo = get_repository()
    order = repo.get_order_by_id(tenant_id, order_id)
    if not order:
        return HTMLResponse(
            """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Pedido no encontrado • Petroil Gas</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; text-align: center; padding: 40px 20px; }
    .card { max-width: 420px; margin: 40px auto; background: #1e293b; border-radius: 20px; padding: 32px 24px; border: 1px solid rgba(255,255,255,0.08); }
    h2 { margin: 16px 0 8px; font-size: 20px; }
    p { color: #94a3b8; font-size: 14px; line-height: 1.5; }
  </style>
</head>
<body>
  <div class="card">
    <div style="font-size:48px;">⚠️</div>
    <h2>Pedido no encontrado</h2>
    <p>El folio indicado no existe o ha expirado. Por favor verifica tu enlace desde el chat.</p>
  </div>
</body>
</html>""",
            status_code=404,
            media_type="text/html; charset=utf-8",
        )

    driver = repo.get_driver(order.driver_id) if order.driver_id else None
    driver_name = driver.name if driver else "Repartidor Petroil"
    vehicle_plate = getattr(driver, "vehicle_plate", None) or "Unidad Gas LP"
    driver_phone = getattr(driver, "phone", "") or ""
    clean_status = str(order.status or "").lower()

    # 1. Si el pedido YA FUE ENTREGADO, mostrar pantalla de servicio concluido (sin mapa activo del chofer)
    if clean_status in ("delivered", "entregado", "completed"):
        delivered_html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>✅ Pedido #{order.id} Entregado • Petroil Gas</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@600;700;800&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Plus Jakarta Sans', sans-serif;
      background: #090d16;
      color: #f1f5f9;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 24px 16px;
    }}
    .card {{
      width: 100%;
      max-width: 440px;
      background: rgba(15, 23, 42, 0.95);
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 24px;
      padding: 32px 24px;
      text-align: center;
      box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7);
    }}
    .badge-icon {{
      width: 68px;
      height: 68px;
      border-radius: 50%;
      background: rgba(34, 197, 94, 0.15);
      border: 2px solid #22c55e;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 34px;
      margin: 0 auto 20px;
      box-shadow: 0 0 25px rgba(34, 197, 94, 0.35);
    }}
    h1 {{
      font-family: 'Outfit', sans-serif;
      font-size: 24px;
      font-weight: 800;
      color: #ffffff;
      margin-bottom: 8px;
    }}
    .subtitle {{
      color: #94a3b8;
      font-size: 14px;
      margin-bottom: 24px;
      line-height: 1.5;
    }}
    .info-list {{
      background: rgba(255, 255, 255, 0.04);
      border-radius: 16px;
      padding: 16px;
      text-align: left;
      margin-bottom: 24px;
      font-size: 14px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}
    .info-item {{
      display: flex;
      justify-content: space-between;
      color: #cbd5e1;
    }}
    .info-item span:first-child {{ color: #94a3b8; }}
    .info-item span:last-child {{ font-weight: 600; color: #ffffff; }}
    .status-tag {{
      display: inline-block;
      padding: 6px 16px;
      border-radius: 20px;
      background: rgba(34, 197, 94, 0.2);
      border: 1px solid #22c55e;
      color: #4ade80;
      font-weight: 700;
      font-size: 13px;
      margin-bottom: 20px;
    }}
    .footer-note {{
      font-size: 13px;
      color: #64748b;
      line-height: 1.4;
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="badge-icon">✅</div>
    <div class="status-tag">Servicio Finalizado</div>
    <h1>¡Pedido Entregado con Éxito!</h1>
    <p class="subtitle">Tu cilindro de gas ha sido entregado en tu domicilio. La ruta del chofer ha concluido exitosamente.</p>

    <div class="info-list">
      <div class="info-item">
        <span>Folio:</span>
        <span>#{order.id}</span>
      </div>
      <div class="info-item">
        <span>Dirección:</span>
        <span style="text-align:right;max-width:65%;">{order.delivery_address}</span>
      </div>
      <div class="info-item">
        <span>Total Pagado:</span>
        <span style="color:#4ade80;">${order.total_amount:,.2f} {order.currency}</span>
      </div>
      <div class="info-item">
        <span>Repartidor:</span>
        <span>{driver_name}</span>
      </div>
    </div>

    <p class="footer-note">¡Muchas gracias por tu compra con Petroil Gas! Si requieres un nuevo cilindro, escríbenos directamente en tu chat.</p>
  </div>
</body>
</html>"""
        return HTMLResponse(content=delivered_html, media_type="text/html; charset=utf-8")

    # 2. Pedido activo: Renderizar Mapa interactivo en tiempo real con Leaflet
    try:
        dest_lat = float(order.delivery_lat) if order.delivery_lat is not None else 23.2435
    except Exception:
        dest_lat = 23.2435

    try:
        dest_lng = float(order.delivery_lng) if order.delivery_lng is not None else -106.4123
    except Exception:
        dest_lng = -106.4123

    driver_lat_raw = getattr(driver, "current_lat", None) if driver else None
    driver_lng_raw = getattr(driver, "current_lng", None) if driver else None
    try:
        driver_lat = float(driver_lat_raw) if driver_lat_raw is not None else 23.2339
    except Exception:
        driver_lat = 23.2339

    try:
        driver_lng = float(driver_lng_raw) if driver_lng_raw is not None else -106.4236
    except Exception:
        driver_lng = -106.4236

    gmaps_nav_url = (
        f"https://www.google.com/maps/dir/?api=1"
        f"&origin={driver_lat:.6f},{driver_lng:.6f}"
        f"&destination={dest_lat:.6f},{dest_lng:.6f}"
        f"&travelmode=driving"
    )

    address_escaped = json.dumps(order.delivery_address or "Tu Domicilio")
    driver_name_escaped = json.dumps(driver_name)
    vehicle_plate_escaped = json.dumps(vehicle_plate)

    html_content = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Rastreo en Vivo • Pedido #{order.id} • Petroil Gas</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700;800&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      -webkit-tap-highlight-color: transparent;
    }}
    html, body {{
      width: 100%;
      height: 100%;
      margin: 0;
      padding: 0;
      overflow: hidden;
      background: #090d16;
      color: #f1f5f9;
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      position: relative;
    }}
    header {{
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 60px;
      background: rgba(15, 23, 42, 0.96);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid rgba(255, 255, 255, 0.1);
      padding: 0 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      z-index: 1000;
    }}
    .brand {{
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .logo-badge {{
      width: 38px;
      height: 38px;
      border-radius: 10px;
      background: linear-gradient(135deg, #ef4444, #f97316);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 20px;
      box-shadow: 0 4px 12px rgba(239, 68, 68, 0.35);
    }}
    .brand-title {{
      font-family: 'Outfit', sans-serif;
      font-weight: 800;
      font-size: 16px;
      letter-spacing: -0.02em;
      color: #ffffff;
    }}
    .brand-sub {{
      font-size: 11px;
      color: #94a3b8;
    }}
    .status-badge {{
      padding: 6px 12px;
      border-radius: 20px;
      font-size: 12px;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 6px;
      background: rgba(34, 197, 94, 0.15);
      border: 1px solid rgba(34, 197, 94, 0.4);
      color: #4ade80;
    }}
    .status-dot {{
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #22c55e;
      box-shadow: 0 0 10px #22c55e;
      animation: pulse-dot 1.8s infinite;
    }}
    @keyframes pulse-dot {{
      0%, 100% {{ transform: scale(1); opacity: 1; }}
      50% {{ transform: scale(1.4); opacity: 0.6; }}
    }}
    #map {{
      position: absolute;
      top: 60px;
      bottom: 0;
      left: 0;
      right: 0;
      width: 100%;
      height: calc(100% - 60px);
      min-height: 350px;
      z-index: 1;
      background: #0b1120;
    }}
    /* Card flotante inferior de información */
    .tracking-card {{
      position: absolute;
      bottom: 16px;
      left: 14px;
      right: 14px;
      z-index: 1000;
      background: rgba(15, 23, 42, 0.95);
      backdrop-filter: blur(16px);
      border: 1px solid rgba(255, 255, 255, 0.14);
      border-radius: 20px;
      padding: 16px;
      box-shadow: 0 20px 45px -10px rgba(0, 0, 0, 0.8);
      max-width: 480px;
      margin: 0 auto;
    }}
    .eta-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 12px;
      padding-bottom: 10px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    }}
    .eta-box {{
      display: flex;
      align-items: baseline;
      gap: 6px;
    }}
    .eta-val {{
      font-family: 'Outfit', sans-serif;
      font-weight: 800;
      font-size: 26px;
      color: #f97316;
    }}
    .eta-unit {{
      font-size: 13px;
      font-weight: 600;
      color: #94a3b8;
    }}
    .dist-box {{
      font-size: 13px;
      color: #cbd5e1;
      background: rgba(255, 255, 255, 0.06);
      padding: 6px 12px;
      border-radius: 12px;
      font-weight: 600;
    }}
    .driver-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 12px;
    }}
    .driver-info {{
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .driver-avatar {{
      width: 40px;
      height: 40px;
      border-radius: 50%;
      background: linear-gradient(135deg, #3b82f6, #1d4ed8);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 20px;
      box-shadow: 0 2px 8px rgba(59, 130, 246, 0.3);
    }}
    .driver-name {{
      font-weight: 700;
      font-size: 14px;
      color: #ffffff;
    }}
    .driver_unit {{
      font-size: 12px;
      color: #94a3b8;
    }}
    .btn-call {{
      background: rgba(34, 197, 94, 0.2);
      border: 1px solid rgba(34, 197, 94, 0.4);
      color: #4ade80;
      padding: 8px 14px;
      border-radius: 12px;
      font-size: 13px;
      font-weight: 600;
      text-decoration: none;
      display: flex;
      align-items: center;
      gap: 4px;
    }}
    .btn-gmaps {{
      display: block;
      width: 100%;
      text-align: center;
      background: linear-gradient(135deg, #2563eb, #1d4ed8);
      color: #ffffff;
      padding: 12px;
      border-radius: 14px;
      font-size: 14px;
      font-weight: 700;
      text-decoration: none;
      box-shadow: 0 4px 15px rgba(37, 99, 235, 0.4);
      margin-bottom: 8px;
    }}
    .btn-gmaps:active {{
      transform: scale(0.98);
    }}
    .address-line {{
      font-size: 11px;
      color: #94a3b8;
      text-align: center;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    /* Marcadores personalizados */
    .truck-marker-wrap {{
      position: relative;
      width: 48px;
      height: 48px;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .truck-radar {{
      position: absolute;
      width: 48px;
      height: 48px;
      border-radius: 50%;
      background: rgba(239, 68, 68, 0.3);
      animation: radar-pulse 2s infinite ease-out;
    }}
    @keyframes radar-pulse {{
      0% {{ transform: scale(0.4); opacity: 1; }}
      100% {{ transform: scale(1.5); opacity: 0; }}
    }}
    .truck-icon-badge {{
      position: relative;
      z-index: 2;
      width: 36px;
      height: 36px;
      background: #ef4444;
      border: 2px solid #ffffff;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 18px;
      box-shadow: 0 4px 12px rgba(0,0,0,0.5);
    }}
    .house-marker-badge {{
      width: 34px;
      height: 34px;
      background: #3b82f6;
      border: 2px solid #ffffff;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 18px;
      box-shadow: 0 4px 12px rgba(0,0,0,0.5);
    }}
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <div class="logo-badge">⛽</div>
      <div>
        <div class="brand-title">Petroil Gas</div>
        <div class="brand-sub">Rastreo en Tiempo Real • Pedido #{order.id}</div>
      </div>
    </div>
    <div id="statusBadge" class="status-badge">
      <div class="status-dot"></div>
      <span id="statusText">En Camino</span>
    </div>
  </header>

  <div id="map"></div>

  <div class="tracking-card">
    <div class="eta-row">
      <div class="eta-box">
        <span class="eta-val" id="etaMinutes">~8</span>
        <span class="eta-unit">min aprox</span>
      </div>
      <div class="dist-box" id="distanceKm">Distancia: ~2.4 km</div>
    </div>

    <div class="driver-row">
      <div class="driver-info">
        <div class="driver-avatar">👨‍✈️</div>
        <div>
          <div class="driver-name" id="driverName">{driver_name}</div>
          <div class="driver_unit" id="vehiclePlate">🚘 {vehicle_plate}</div>
        </div>
      </div>
      {"<a href='tel:" + driver_phone + "' class='btn-call'>📞 Llamar</a>" if driver_phone else ""}
    </div>

    <a id="gmapsLink" href="{gmaps_nav_url}" target="_blank" class="btn-gmaps">
      🗺️ Seguir en Google Maps (Navegación en vivo)
    </a>

    <div class="address-line">
      📍 Destino: <b>{order.delivery_address}</b>
    </div>
  </div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    const orderId = "{order.id}";
    const destAddress = {address_escaped};
    let destLat = {dest_lat:.6f};
    let destLng = {dest_lng:.6f};
    let driverLat = {driver_lat:.6f};
    let driverLng = {driver_lng:.6f};

    // Inicializar mapa Leaflet
    const map = L.map('map', {{
      zoomControl: false,
      attributionControl: false
    }}).setView([driverLat, driverLng], 14);

    L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
      maxZoom: 19
    }}).addTo(map);

    // Forzar actualización de tamaño para webviews móviles
    setTimeout(() => {{ map.invalidateSize(); }}, 250);
    setTimeout(() => {{ map.invalidateSize(); }}, 750);
    window.addEventListener('resize', () => {{ map.invalidateSize(); }});

    // Marcador Casa
    const houseIcon = L.divIcon({{
      className: 'custom-house',
      html: '<div class="house-marker-badge">🏠</div>',
      iconSize: [34, 34],
      iconAnchor: [17, 17]
    }});
    const destMarker = L.marker([destLat, destLng], {{ icon: houseIcon }}).addTo(map);
    destMarker.bindPopup("<b>Tu Domicilio</b><br>" + destAddress);

    // Marcador Chofer / Pipa con Radar
    const truckIcon = L.divIcon({{
      className: 'custom-truck',
      html: '<div class="truck-marker-wrap"><div class="truck-radar"></div><div class="truck-icon-badge">🛻</div></div>',
      iconSize: [48, 48],
      iconAnchor: [24, 24]
    }});
    const driverMarker = L.marker([driverLat, driverLng], {{ icon: truckIcon }}).addTo(map);

    // Línea de ruta dinámica
    const routeLine = L.polyline([[driverLat, driverLng], [destLat, destLng]], {{
      color: '#ef4444',
      weight: 4,
      dashArray: '8, 8',
      opacity: 0.8
    }}).addTo(map);

    // Ajustar límites iniciales para ver ambos puntos
    try {{
      const bounds = L.latLngBounds([[driverLat, driverLng], [destLat, destLng]]);
      map.fitBounds(bounds, {{ padding: [70, 70] }});
    }} catch(e) {{}}

    // Actualización periódica en vivo (polling cada 4 segundos)
    async function updateLiveLocation() {{
      try {{
        const resp = await fetch(`/api/tracking/${{orderId}}`);
        if (!resp.ok) return;
        const data = await resp.json();

        if (data.status === 'delivered') {{
          // Si el pedido ya fue entregado, recargar para mostrar la vista de entrega finalizada
          window.location.reload();
          return;
        }}

        if (data.driver && data.driver.lat && data.driver.lng) {{
          const newLat = data.driver.lat;
          const newLng = data.driver.lng;

          // Mover suavemente el marcador del chofer
          driverMarker.setLatLng([newLat, newLng]);
          routeLine.setLatLngs([[newLat, newLng], [destLat, destLng]]);

          // Actualizar ETA y distancia
          document.getElementById('etaMinutes').textContent = `~${{data.eta_minutes}}`;
          document.getElementById('distanceKm').textContent = `Distancia: ~${{data.distance_km}} km`;
          document.getElementById('gmapsLink').href = data.google_maps_url;

          if (data.driver.name) {{
            document.getElementById('driverName').textContent = data.driver.name;
          }}
          if (data.driver.vehicle_plate) {{
            document.getElementById('vehiclePlate').textContent = `🚘 ${{data.driver.vehicle_plate}}`;
          }}
        }}
      }} catch (err) {{
        console.debug("Tracking fetch err:", err);
      }}
    }}

    setInterval(updateLiveLocation, 4000);
  </script>
</body>
</html>
"""
    return HTMLResponse(content=html_content, media_type="text/html; charset=utf-8")
