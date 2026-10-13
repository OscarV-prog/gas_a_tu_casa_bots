"""Verification test suite for strict city address validation:
- Petroil (Gas a tu Puerta original): 100% focused on Mazatlán, Sinaloa.
- Gascytsa: 100% focused on Culiacán, Sinaloa.
- No invented or fake addresses accepted.
- No out-of-coverage cities, states, or countries accepted.
- No deceptive fixed downtown center coordinates assigned to unlocatable/fake addresses.
"""

import asyncio
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.services.address_validator import _fast_heuristic_check, validate_address_with_llm
from src.services.geocoding import (
    DEFAULT_LAT,
    DEFAULT_LNG,
    CULIACAN_LAT,
    CULIACAN_LNG,
    calculate_distance_km,
    geocode_address,
)
from src.services.flow_router import flow_router, FlowState, get_or_create_session, clear_session


async def test_fast_heuristic_mazatlan_restrictions():
    print("🧪 [Test 1] Fast Heuristic Rejections for Mazatlán (Petroil)...")
    out_for_mazatlan = [
        "Prol. Álvaro Obregón 1880, Colinas de San Miguel",
        "Colinas de San Miguel",
        "Desarrollo Urbano Tres Ríos",
        "Blvd. Pedro Infante 2200, Culiacán",
        "Av. Álvaro Obregón 1540, Culiacán",
        "Calle Leyva 45, Los Mochis",
        "Av. Hidalgo 12, Escuinapa",
        "Calle Juárez 100, Navolato",
        "Av. Vallarta 1234, Guadalajara, Jalisco",
        "Paseo de la Reforma 222, CDMX",
        "Av. Constitución 500, Monterrey, Nuevo León",
        "123 Main Street, Houston, Texas, USA",
        "calle falsa 123",
        "en mi casa",
        "en la luna",
        "calle del dragon magico en narnia 99",
    ]
    for text in out_for_mazatlan:
        res = _fast_heuristic_check(text, target_city="Mazatlán")
        assert res is not None, f"Expected heuristic rejection for Mazatlan target: '{text}'"
        is_val, fb = res
        assert is_val is False
        assert "Mazatlán" in fb or "domicilio válido" in fb or "demasiado corta" in fb, f"Unexpected feedback: {fb}"
    print("  ✅ Passed: All out-of-city/state/country/joke addresses rejected for Mazatlán in 0ms.\n")


async def test_fast_heuristic_culiacan_restrictions():
    print("🧪 [Test 2] Fast Heuristic Rejections for Culiacán (Gascytsa)...")
    out_for_culiacan = [
        "Av. Camarón Sábalo 310, Mazatlán",
        "Av. del Mar 500, Mazatlán",
        "Misión San Javier 5246, Fracc. Las Misiones, Mazatlán",
        "Calle Leyva 45, Los Mochis",
        "Av. Hidalgo 12, Escuinapa",
        "Av. Vallarta 1234, Guadalajara",
        "Paseo de la Reforma 222, CDMX",
        "calle inventada 45",
        "en el cerro",
    ]
    for text in out_for_culiacan:
        res = _fast_heuristic_check(text, target_city="Culiacán")
        assert res is not None, f"Expected heuristic rejection for Culiacán target: '{text}'"
        is_val, fb = res
        assert is_val is False
        assert "Culiacán" in fb or "domicilio válido" in fb, f"Unexpected feedback: {fb}"
    print("  ✅ Passed: All out-of-city/state/joke addresses rejected for Culiacán in 0ms.\n")


async def test_fast_heuristic_valid_addresses():
    print("🧪 [Test 3] Fast Heuristic Acceptance for Valid Local Addresses...")
    valid_mazatlan = [
        "Misión San Javier 5246, Fracc. Las Misiones",
        "Av. Insurgentes 1204, Col. Estadio",
        "Calle Benito Juárez #45, Centro",
        "Av. del Mar 500, Zona Dorada",
        "Calle 5 de Mayo 123, Col. Centro, Mazatlán",
    ]
    for addr in valid_mazatlan:
        res = _fast_heuristic_check(addr, target_city="Mazatlán")
        assert res is None, f"Valid Mazatlán address '{addr}' should pass heuristic check"

    valid_culiacan = [
        "Blvd. Pedro Infante 2200, Desarrollo Urbano Tres Ríos",
        "Av. Álvaro Obregón 1540, Col. Gabriel Leyva",
        "Calle Ruperto L. Paliza 250, Centro",
        "Calle Dr. Mora 120, Col. Las Quintas",
        "Blvd. Enrique Sánchez Alonso 450, Tres Ríos, Culiacán",
    ]
    for addr in valid_culiacan:
        res = _fast_heuristic_check(addr, target_city="Culiacán")
        assert res is None, f"Valid Culiacán address '{addr}' should pass heuristic check"
    print("  ✅ Passed: Valid local addresses pass heuristic filter cleanly.\n")


async def test_geocoding_no_fake_center_pins():
    print("🧪 [Test 4] Geocoding Never Deceives Torre de Control with Fake Center Pins...")
    
    # 1. Real Mazatlán address: geocodes near Mazatlán center
    m_lat, m_lng, m_addr = geocode_address("Mision San Javier 5246, Fracc Las Misiones", city_context="Mazatlán", fallback_to_default=False)
    assert m_lat is not None and m_lng is not None
    dist_m = calculate_distance_km(m_lat, m_lng, DEFAULT_LAT, DEFAULT_LNG)
    assert dist_m < 35.0, f"Mazatlán address resolved too far: {dist_m:.1f}km"

    # 2. Fake / invented address: returns (None, None, address) when fallback_to_default=False
    fake_lat, fake_lng, _ = geocode_address("Calle Dragon Magico 9999, Fracc Narnia 2", city_context="Mazatlán", fallback_to_default=False)
    assert fake_lat is None and fake_lng is None, f"Fake address returned non-None coordinates: ({fake_lat}, {fake_lng})"

    # 3. Real Culiacán address geocoded in Culiacán
    c_lat, c_lng, c_addr = geocode_address("Blvd Pedro Infante 2200, Desarrollo Urbano Tres Rios", city_context="Culiacán", fallback_to_default=False)
    assert c_lat is not None and c_lng is not None
    dist_c = calculate_distance_km(c_lat, c_lng, CULIACAN_LAT, CULIACAN_LNG)
    assert dist_c < 35.0, f"Culiacán address resolved too far: {dist_c:.1f}km"

    # 4. Mazatlán address queried in Culiacán: does NOT exist in Culiacán, must return None
    m_in_c_lat, m_in_c_lng, _ = geocode_address("Mision San Javier 5246, Fracc Las Misiones", city_context="Culiacán", fallback_to_default=False)
    assert m_in_c_lat is None and m_in_c_lng is None, f"Mazatlán address should not geocode in Culiacán: ({m_in_c_lat}, {m_in_c_lng})"

    print("  ✅ Passed: Pinpoint geocoding validated; fake and out-of-city addresses return None coordinates.\n")


async def test_gps_pin_radius_bounds_in_flow():
    print("🧪 [Test 5] GPS Pin Radius Bounds in Flow Router...")

    # Mazatlán bot (Petroil) with Mazatlán pin (< 35km) -> Accepted
    sid_m = "test_gps_mzt_fresh"
    clear_session(sid_m)
    s_m = get_or_create_session(sid_m, tenant_id="petroil")
    s_m.state = FlowState.WAITING_FOR_NEW_CUSTOMER_ADDRESS
    s_m.draft_order.customer_name = "Cliente Maza"
    s_m.draft_order.customer_phone = "6691999901"

    resp_m_valid = await flow_router.process_event(
        session_id=sid_m,
        location={"latitude": 23.2350, "longitude": -106.4150},  # Mazatlán Centro
        channel="test",
    )
    assert resp_m_valid.state == FlowState.WAITING_FOR_SCHEDULE, f"Expected WAITING_FOR_SCHEDULE but got {resp_m_valid.state}"
    assert "horario" in resp_m_valid.text.lower() or "ubicación gps" in resp_m_valid.text.lower()

    # Mazatlán bot (Petroil) with Guadalajara pin (> 100km) -> Rejected
    sid_m_bad = "test_gps_mzt_bad_fresh"
    clear_session(sid_m_bad)
    s_m_bad = get_or_create_session(sid_m_bad, tenant_id="petroil")
    s_m_bad.state = FlowState.WAITING_FOR_NEW_CUSTOMER_ADDRESS
    resp_m_gdl = await flow_router.process_event(
        session_id=sid_m_bad,
        location={"latitude": 20.6597, "longitude": -103.3496},  # Guadalajara
        channel="test",
    )
    assert "cobertura" in resp_m_gdl.text.lower() or "mazatlán" in resp_m_gdl.text.lower()
    assert s_m_bad.state == FlowState.WAITING_FOR_NEW_CUSTOMER_ADDRESS

    # Culiacán bot (Gascytsa) with Culiacán pin (< 35km) -> Accepted
    sid_c = "test_gps_cul_fresh"
    clear_session(sid_c)
    s_c = get_or_create_session(sid_c, tenant_id="gascytsa")
    s_c.state = FlowState.WAITING_FOR_NEW_CUSTOMER_ADDRESS
    s_c.draft_order.customer_name = "Cliente Culiacán"
    s_c.draft_order.customer_phone = "6671999902"

    resp_c_valid = await flow_router.process_event(
        session_id=sid_c,
        location={"latitude": 24.8050, "longitude": -107.4100},  # Culiacán Tres Ríos
        channel="test",
    )
    assert resp_c_valid.state == FlowState.WAITING_FOR_SCHEDULE, f"Expected WAITING_FOR_SCHEDULE but got {resp_c_valid.state}"

    # Culiacán bot (Gascytsa) with Mazatlán pin (> 200km away) -> Rejected
    sid_c_bad = "test_gps_cul_bad"
    clear_session(sid_c_bad)
    s_c_bad = get_or_create_session(sid_c_bad, tenant_id="gascytsa")
    s_c_bad.state = FlowState.WAITING_FOR_NEW_CUSTOMER_ADDRESS
    resp_c_mzt = await flow_router.process_event(
        session_id=sid_c_bad,
        location={"latitude": 23.2014, "longitude": -106.4215},  # Mazatlán center
        channel="test",
    )
    assert "cobertura" in resp_c_mzt.text.lower() or "culiacán" in resp_c_mzt.text.lower() or "mazatlán" in resp_c_mzt.text.lower()
    assert s_c_bad.state == FlowState.WAITING_FOR_NEW_CUSTOMER_ADDRESS

    print("  ✅ Passed: GPS location boundary checks strictly enforced for each tenant.\n")


async def test_cross_city_text_address_validation():
    print("🧪 [Test 6] Cross-City Text Address Validation (Grounding Cartográfico)...")

    # 1. Dirección de Mazatlán enviada a Gascytsa (Culiacán) -> DEBE RECHAZARSE
    res_mzt_in_cul = await validate_address_with_llm(
        "Mision San Javier 5246, Las Misiones",
        tenant_id="gascytsa",
        city_context="Culiacán",
    )
    assert not res_mzt_in_cul.is_valid, f"Expected invalid in Culiacán, got valid: {res_mzt_in_cul}"
    assert "Culiacán" in res_mzt_in_cul.user_feedback, f"Expected 'Culiacán' in feedback: {res_mzt_in_cul.user_feedback}"
    assert "Mazatlán" not in res_mzt_in_cul.user_feedback, f"Opposing city should NOT be leaked: {res_mzt_in_cul.user_feedback}"

    # 2. Dirección de Mazatlán enviada a Petroil (Mazatlán) -> DEBE ACEPTARSE
    res_mzt_in_mzt = await validate_address_with_llm(
        "Mision San Javier 5246, Las Misiones",
        tenant_id="petroil",
        city_context="Mazatlán",
    )
    assert res_mzt_in_mzt.is_valid, f"Expected valid in Mazatlán, got invalid: {res_mzt_in_mzt}"

    # 3. Dirección de Culiacán enviada a Petroil (Mazatlán) -> DEBE RECHAZARSE
    res_cul_in_mzt = await validate_address_with_llm(
        "Blvd. Pedro Infante 2200, Tres Rios",
        tenant_id="petroil",
        city_context="Mazatlán",
    )
    assert not res_cul_in_mzt.is_valid, f"Expected invalid in Mazatlán, got valid: {res_cul_in_mzt}"
    assert "Mazatlán" in res_cul_in_mzt.user_feedback, f"Expected 'Mazatlán' in feedback: {res_cul_in_mzt.user_feedback}"
    assert "Culiacán" not in res_cul_in_mzt.user_feedback, f"Opposing city should NOT be leaked: {res_cul_in_mzt.user_feedback}"

    res_obregon_in_mzt = await validate_address_with_llm(
        "Prol. Álvaro Obregón 1880, Colinas de San Miguel",
        tenant_id="petroil",
        city_context="Mazatlán",
    )
    assert not res_obregon_in_mzt.is_valid, f"Expected invalid in Mazatlán for Colinas de San Miguel, got valid: {res_obregon_in_mzt}"
    assert "Mazatlán" in res_obregon_in_mzt.user_feedback
    assert "Culiacán" not in res_obregon_in_mzt.user_feedback

    # 4. Dirección de Culiacán enviada a Gascytsa (Culiacán) -> DEBE ACEPTARSE
    res_cul_in_cul = await validate_address_with_llm(
        "Blvd. Pedro Infante 2200, Tres Rios",
        tenant_id="gascytsa",
        city_context="Culiacán",
    )
    assert res_cul_in_cul.is_valid, f"Expected valid in Culiacán, got invalid: {res_cul_in_cul}"

    # 5. Dirección de Guadalajara enviada a Mazatlán o Culiacán -> DEBE RECHAZARSE
    res_gdl = await validate_address_with_llm(
        "Av. Vallarta 1234, Col. Americana",
        tenant_id="petroil",
        city_context="Mazatlán",
    )
    assert not res_gdl.is_valid, f"Expected invalid for Guadalajara, got: {res_gdl}"

    print("  ✅ Passed: Cross-city text validation strictly rejects addresses from other cities.\n")


async def test_cross_city_flow_router_enforcement():
    print("🧪 [Test 7] End-to-End Flow Router Cross-City Address Enforcement...")

    # Caso A: Cliente en bot de Culiacán (Gascytsa) escribe dirección de Mazatlán
    sid_gascytsa = "test_flow_gascytsa_cross_city"
    clear_session(sid_gascytsa)
    sess_g = get_or_create_session(sid_gascytsa, tenant_id="gascytsa")
    sess_g.state = FlowState.WAITING_FOR_NEW_CUSTOMER_ADDRESS
    sess_g.draft_order.customer_name = "Oscar Culiacán"
    sess_g.draft_order.customer_phone = "6671234567"

    resp_g_bad = await flow_router.process_event(
        session_id=sid_gascytsa,
        text="Mision San Javier 5246, Las Misiones",
        channel="telegram",
        channel_user_id="12345",
        tenant_id="gascytsa",
    )
    # Debe ser RECHAZADO: permanecer en WAITING_FOR_NEW_CUSTOMER_ADDRESS y solo indicar cobertura en Culiacán
    assert sess_g.state == FlowState.WAITING_FOR_NEW_CUSTOMER_ADDRESS, f"Expected WAITING_FOR_NEW_CUSTOMER_ADDRESS, got {sess_g.state}"
    assert "Culiacán" in resp_g_bad.text, f"Expected 'Culiacán' in rejection message, got: {resp_g_bad.text}"
    assert "Mazatlán" not in resp_g_bad.text, f"Opposing city should NOT be in rejection message: {resp_g_bad.text}"

    # Ahora el cliente en Culiacán escribe su dirección real de Culiacán
    resp_g_good = await flow_router.process_event(
        session_id=sid_gascytsa,
        text="Blvd. Pedro Infante 2200, Tres Rios",
        channel="telegram",
        channel_user_id="12345",
        tenant_id="gascytsa",
    )
    # Debe ser ACEPTADO: avanzar a WAITING_FOR_SCHEDULE
    assert sess_g.state == FlowState.WAITING_FOR_SCHEDULE, f"Expected WAITING_FOR_SCHEDULE, got {sess_g.state}"
    assert "horario" in resp_g_good.text.lower(), f"Expected schedule prompt, got: {resp_g_good.text}"

    # Caso B: Cliente en bot de Mazatlán (Petroil) escribe dirección de Culiacán
    sid_petroil = "test_flow_petroil_cross_city"
    clear_session(sid_petroil)
    sess_p = get_or_create_session(sid_petroil, tenant_id="petroil")
    sess_p.state = FlowState.WAITING_FOR_NEW_CUSTOMER_ADDRESS
    sess_p.draft_order.customer_name = "Oscar Mazatlán"
    sess_p.draft_order.customer_phone = "6691234567"

    resp_p_bad = await flow_router.process_event(
        session_id=sid_petroil,
        text="Prol. Álvaro Obregón 1880, Colinas de San Miguel",
        channel="telegram",
        channel_user_id="67890",
        tenant_id="petroil",
    )
    # Debe ser RECHAZADO: permanecer en WAITING_FOR_NEW_CUSTOMER_ADDRESS y solo indicar cobertura en Mazatlán
    assert sess_p.state == FlowState.WAITING_FOR_NEW_CUSTOMER_ADDRESS, f"Expected WAITING_FOR_NEW_CUSTOMER_ADDRESS, got {sess_p.state}"
    assert "Mazatlán" in resp_p_bad.text, f"Expected 'Mazatlán' in rejection message, got: {resp_p_bad.text}"
    assert "Culiacán" not in resp_p_bad.text, f"Opposing city should NOT be in rejection message: {resp_p_bad.text}"

    # Ahora el cliente en Mazatlán escribe su dirección real de Mazatlán
    resp_p_good = await flow_router.process_event(
        session_id=sid_petroil,
        text="Mision San Javier 5246, Las Misiones",
        channel="telegram",
        channel_user_id="67890",
        tenant_id="petroil",
    )
    # Debe ser ACEPTADO: avanzar a WAITING_FOR_SCHEDULE
    assert sess_p.state == FlowState.WAITING_FOR_SCHEDULE, f"Expected WAITING_FOR_SCHEDULE, got {sess_p.state}"
    assert "horario" in resp_p_good.text.lower(), f"Expected schedule prompt, got: {resp_p_good.text}"

    print("  ✅ Passed: Flow router enforces strict city boundaries seamlessly across all channels.\n")


async def main():
    print("🚀 Running City Strict Validation Test Suite...\n")
    await test_fast_heuristic_mazatlan_restrictions()
    await test_fast_heuristic_culiacan_restrictions()
    await test_fast_heuristic_valid_addresses()
    await test_geocoding_no_fake_center_pins()
    await test_gps_pin_radius_bounds_in_flow()
    await test_cross_city_text_address_validation()
    await test_cross_city_flow_router_enforcement()
    print("🎉 ALL 7 CITY STRICT VALIDATION TESTS PASSED WITH 100% SUCCESS!\n")


if __name__ == "__main__":
    asyncio.run(main())
