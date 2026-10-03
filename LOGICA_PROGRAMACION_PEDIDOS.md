# 📅 Lógica de Programación y Despacho de Pedidos
> **Guía Técnica de Integración para el Desarrollador del Dashboard de Pedidos**  
> **Proyecto:** Agente de Ventas y Despacho Logístico (Gas a Tu Puerta / Petroil)  
> **Fecha:** Septiembre 2026  
> **Versión:** 2.4 Enterprise  

---

## 📌 1. Resumen Ejecutivo

En este sistema, los pedidos se dividen en dos grandes categorías operativas:
1. **Pedidos Inmediatos ("Lo antes posible" / ASAP):** Entran directo al flujo de despacho activo (`confirmed` / `PENDIENTE` ➔ `assigned`).
2. **Pedidos Programados a Futuro (`scheduled` / `PROGRAMADO`):** Pedidos pactados para una fecha u hora posterior (ej. *"Hoy a las 5:00 PM"*, *"Mañana a las 11:00 AM"*).

Para no saturar a los choferes ni enviarles alertas con horas o días de anticipación, **los pedidos programados se retienen en una "Mesa de Agenda"** y **se activan automáticamente 30 minutos antes de la hora pactada (`T - 30 min`)**.

Este documento detalla cómo se gestionan los estados, la capacidad de choferes por horario, los campos de la base de datos y los endpoints REST que el Dashboard debe consumir.

---

## 🔄 2. Estados del Pedido y Mapeo de Nombres

El sistema cuenta con soporte dual: base de datos local SQLite y API centralizada (NestJS + PostgreSQL). A continuación se muestra la equivalencia de estados:

| Estado Interno (Dashboard / SQLite) | Estado API NestJS / Postgres | Descripción Operativa | ¿Debe mostrarse en Dashboard Activo? |
| :--- | :--- | :--- | :--- |
| `pending` | `PENDIENTE` | Pedido recién creado por el cliente, en validación o sin asignar. | ✅ Sí (Mesa de Envíos Activos) |
| `confirmed` | `CONFIRMADO` | Pedido confirmado listo para despacho o asignación de unidad. | ✅ Sí (Mesa de Envíos Activos) |
| `scheduled` | `PROGRAMADO` | **Pedido agendado a futuro.** Falta más de 30 min para su entrega. | 🗓️ **En pestaña "Agenda Programada"** |
| `assigned` | `ASIGNADO` | Se le asignó chofer/unidad pero el chofer aún no inicia el recorrido. | ✅ Sí (Mesa de Envíos Activos) |
| `in_route` | `EN_RUTA` | El chofer aceptó el viaje y va navegando hacia el cliente con GPS. | ✅ Sí (En Camino / Monitoreo) |
| `delivered` | `ENTREGADO` | Entrega y cobro confirmados por el chofer o el administrador. | 📦 Historial / Entregados |
| `cancelled` | `CANCELADO` | Pedido cancelado (por cliente, chofer o administrador). | ❌ Cancelados |
| `rejected_by_driver` | `RECHAZADO_POR_CHOFER` | El chofer declinó el viaje por alguna incidencia reportada. | ⚠️ Alerta de Reasignación Urgente |

---

## 🧠 3. Lógica del Motor de Horarios (`ScheduleManager`)

El servicio [`schedule_manager.py`](file:///c:/Users/Prestamo%20ASKE/Desktop/prueba-2-lapp/langgraph-sales-agent/src/services/schedule_manager.py) administra la capacidad de reparto en tiempo real para evitar sobreventa de servicios.

### A. Bloques de Tiempo (Slots de 30 Minutos)
Todo horario capturado en texto natural o fecha seleccionada se normaliza a intervalos fijos de media hora:
* `17:05` ➔ Normaliza a `17:00`
* `17:20` ➔ Normaliza a `17:30`
* `17:48` ➔ Normaliza a `18:00`

### B. Capacidad Dinámica por Choferes Disponibles
* **Regla de Capacidad:** `Capacidad máxima por franja de 30 min = Total de choferes registrados/activos`.
* *Ejemplo:* Si hay **4 choferes** dados de alta en el sistema, cada ventana de 30 minutos puede aceptar un máximo de **4 pedidos simultáneos**.
* Si la consulta de choferes no responde, el sistema toma un valor de respaldo por defecto de **3 pedidos**.

### C. Ventana de Ocupación
Un pedido se considera dentro de un bloque `slot_dt` si su hora programada cae en el rango:
$$\text{Ventana} = [\text{slot\_dt} - 14\text{ minutos}, \; \text{slot\_dt} + 15\text{ minutos}]$$

### D. Algoritmo de Sobrecupo y Reagendación Inteligente
1. El cliente o la Torre de Control solicita un horario (ej. *"Hoy a las 4:00 PM"*).
2. Se cuenta cuántos pedidos ya están registrados en ese bloque.
3. **Si hay cupo:** Se acepta y se confirma el horario.
4. **Si el cupo está lleno:** El sistema recorre secuencialmente los siguientes bloques de 30 minutos en horario laboral (08:00 a 21:00) y propone el primer horario libre disponible:
   > *"El cupo para Hoy a las 4:00 PM está completo (4/4 pedidos asignados). El siguiente horario libre más cercano es Hoy a las 4:30 PM."*

---

## ⏰ 4. La Regla de Activación Automática: Ventana T-30 Minutos

Para evitar que los choferes reciban notificaciones de pedidos que son para dentro de 6 horas o para el día siguiente:

```
[ Cliente pide para las 5:00 PM ] 
                 │
                 ▼
[ Pedido nace en estado "scheduled" ] ──► Se almacena en la tabla 'orders' con:
                                          scheduled_for = "2026-10-01T17:00:00"
                                          delivery_schedule = "Hoy a las 5:00 PM"
                 │
                 ▼ (Permanece visible en la pestaña "Agenda" del Dashboard)
                 │
[ Llega la hora T - 30 min (4:30 PM) ]
                 │
                 ▼
[ Activación Automática ] ──────────────► check_and_activate_scheduled_orders()
                                          1. Cambia estado: "scheduled" ➔ "confirmed"
                                          2. Detona dispatch_order()
                                          3. Asigna la unidad más cercana o disponible
                                          4. Envía tarjeta interactiva al Telegram del Chofer
                                          5. Pasa a la lista activa del Dashboard
```

### ¿Cuándo se evalúa la activación?
1. Cada vez que el Dashboard consulta las métricas (`GET /api/admin/metrics`).
2. Cada vez que el Dashboard solicita la agenda (`GET /api/admin/agenda`).
3. Al consultar o listar pedidos activos (`GET /api/admin/orders`).
4. Mediante el ciclo en segundo plano de despacho de turnos matutinos.

---

## 🗄️ 5. Estructura de Campos en la Base de Datos (`orders`)

Al consultar o recibir pedidos en el Dashboard, los campos clave relacionados con la programación son:

```json
{
  "id": 142,
  "customer_name": "María González",
  "customer_phone": "6691234567",
  "delivery_address": "Av. Insurgentes 402, Playa Sur, Mazatlán",
  "delivery_schedule": "Hoy a las 5:00 PM",
  "scheduled_for": "2026-10-01T17:00:00",
  "status": "scheduled",
  "total_amount": 670.00,
  "currency": "MXN",
  "payment_method": "Efectivo",
  "notes": "Casa blanca de dos pisos, portón negro",
  "driver_id": null,
  "driver_name": null,
  "delivery_lat": 23.21234,
  "delivery_lng": -106.42156,
  "created_at": "2026-10-01T11:15:00",
  "items": [
    {
      "product_id": "cilindro-30kg",
      "product_name": "Cilindro de Gas LP 30 kg",
      "quantity": 1,
      "unit_price": 670.00,
      "subtotal": 670.00
    }
  ]
}
```

* **`delivery_schedule` (string):** Texto legible en español para mostrar en la interfaz (ej. *"Hoy a las 5:00 PM"*, *"Mañana 10:00 AM"*, *"Lo antes posible"*).
* **`scheduled_for` (ISO 8601 string o null):** Fecha y hora formal del compromiso de entrega. Si el pedido es inmediato, viene como `null`.
* **`status` (string):** Si es un pedido futuro y faltan más de 30 minutos, su estado inicial es **`scheduled`**.

---

## 🔌 6. Endpoints REST para el Dashboard

El servidor expone en el puerto local `3000` (o en la URL pública correspondiente) los siguientes endpoints:

### 1. Obtener la Agenda Programada
* **Ruta:** `GET /api/admin/agenda`
* **Parámetros:** `tenant_id=petroil` (opcional)
* **Propósito:** Devuelve únicamente los pedidos programados no entregados ni cancelados, calculando automáticamente los minutos restantes para su activación y su deadline.
* **Ejemplo de Respuesta:**
```json
[
  {
    "id": 142,
    "customer_name": "María González",
    "customer_phone": "6691234567",
    "delivery_address": "Av. Insurgentes 402",
    "delivery_schedule": "Hoy a las 5:00 PM",
    "scheduled_for": "2026-10-01T17:00:00",
    "deadline_display": "Hoy a las 05:00 PM",
    "activation_at": "2026-10-01T16:30:00",
    "activation_display": "Hoy a las 04:30 PM",
    "is_activated": false,
    "minutes_until_deadline": 145,
    "minutes_until_activation": 115,
    "status": "scheduled",
    "total_amount": 670.0,
    "payment_method": "Efectivo",
    "driver_name": null,
    "items": [
      {
        "product_name": "Cilindro de Gas LP 30 kg",
        "quantity": 1,
        "unit_price": 670.0,
        "subtotal": 670.0
      }
    ]
  }
]
```

---

### 2. Forzar Activación Inmediata de un Pedido Agendado
Si el supervisor en el Dashboard decide despachar de una vez un pedido programado sin esperar a que el reloj llegue a $T - 30$:
* **Ruta:** `POST /api/admin/orders/{order_id}/activate-now`
* **Efecto:**
  1. Cambia el estado del pedido de `scheduled` a `confirmed` (o `assigned`).
  2. Ejecuta inmediatamente el algoritmo de despacho para asignarle chofer en campo.
  3. Desaparece de la mesa de espera de la agenda y entra al tablero de pedidos en ruta/activos.

---

### 3. Reprogramar Fecha u Horario
Si el cliente llama o escribe para cambiar la hora de entrega:
* **Ruta:** `POST /api/admin/orders/{order_id}/reschedule`
* **Body:**
```json
{
  "delivery_schedule": "Hoy a las 7:30 PM",
  "scheduled_for": "2026-10-01T19:30:00"
}
```
* **Efecto:** Actualiza el deadline en la base de datos y recalcula si debe continuar en estado `scheduled` o activarse de inmediato.

---

### 4. Crear un Pedido Programado Manualmente (Call Center / Mostrador)
* **Ruta:** `POST /api/admin/orders`
* **Body:**
```json
{
  "customer_name": "Carlos Mendoza",
  "customer_phone": "6699876543",
  "delivery_address": "Calle Bahía 110, Zona Dorada",
  "delivery_schedule": "Mañana a las 10:00 AM",
  "scheduled_for": "2026-10-02T10:00:00",
  "payment_method": "Efectivo",
  "notes": "Timbre descompuesto, tocar portón",
  "dispatch_mode": "none",
  "items": [
    {
      "product_id": "cilindro-30kg",
      "product_name": "Cilindro de Gas LP 30 kg",
      "quantity": 2,
      "unit_price": 670.00
    }
  ]
}
```
* **Nota sobre `dispatch_mode`:**
  * `"none"`: Queda guardado esperando su hora de activación o asignación manual.
  * `"auto"`: El sistema busca chofer automáticamente.
  * `"driver"`: Requiere enviar el campo `"driver_id": 3` para asignarlo directamente a una unidad.

---

## 🎨 7. Recomendaciones de Diseño de UI para el Dashboard

Para que la experiencia visual sea intuitiva y eficiente para el operador del Dashboard:

1. **Separar en 2 Secciones Principales:**
   * **Tablero de Envíos Activos:** Muestra los pedidos que están atendiéndose ahorita (`confirmed`, `assigned`, `in_route`, `rejected_by_driver`).
   * **Mesa de Agenda Programada:** Muestra los pedidos con estatus `scheduled`.
2. **Badges Visuales de Tiempo:**
   * Utilizar badges con cuenta regresiva basada en `minutes_until_deadline`:
     * 🟢 **Verde (> 60 min):** En tiempo, holgado.
     * 🟡 **Amarillo (30 a 60 min):** Próximo a ventana de activación.
     * 🔴 **Rojo (< 30 min):** Dentro de ventana de entrega prioritaria o en activación.
3. **Acciones Rápidas por Fila en la Tabla de Agenda:**
   * ⚡ **Botón "Despachar Ahora" (`activate-now`):** Para adelantar el pedido si un camión va pasando cerca.
   * ✏️ **Botón "Reprogramar" (`reschedule`):** Abre un modal para cambiar fecha/hora pactada.
   * ❌ **Botón "Cancelar Pedido":** Si el cliente desiste del servicio.
4. **Filtros Sugeridos en la Vista de Agenda:**
   * `[ Hoy ]` (pedidos programados para el resto del día de hoy).
   * `[ Mañana ]` (pedidos pactados para el día siguiente).
   * `[ Todos / Futuros ]` (semana completa).

---

## 📞 Soporte y Dudas de Integración
Si necesitas validar un payload en específico o agregar un evento en tiempo real (WebSockets / Server-Sent Events) cuando se active un pedido en la agenda, puedes consultar con el equipo de desarrollo del backend.
