# Guía de Integración de Bots con API Central (Gasera X)

Este documento describe la arquitectura actual, el flujo de operaciones y los endpoints clave de la API en `server-nest` para que los bots (Telegram Bot y Driver Bot) puedan integrarse nativamente y reflejar la información correctamente en el Dashboard (`dashboard-nuxt`).

## 1. Arquitectura y Autenticación
- **Base URL:** `http://localhost:4000/api` (o la URL de producción).
- **Tenant ID:** La plataforma es multi-empresa. Todas las peticiones de los bots hacia la API central **DEBEN** incluir el header `x-tenant-id` (por defecto `petroil` o según configuración).

## 2. Flujo del Bot de Clientes (Telegram Bot)

El bot de Telegram atiende a clientes finales, registra clientes, guarda sus ubicaciones y levanta pedidos.

### Identificar o Crear Cliente
Antes de procesar un pedido, asegúrate de que el cliente exista.
- **Endpoint:** `POST /api/customers/identify-or-create`
- **Payload sugerido:**
  ```json
  {
    "tenantId": "petroil",
    "phone": "+526645550101",
    "name": "Juan Pérez",
    "address": "Av. Paseo de los Héroes #1020",
    "latitude": 32.5312,
    "longitude": -117.0223,
    "customerType": "WHATSAPP"
  }
  ```
- **Respuesta:** Retorna el ID del cliente y sus direcciones previas.

### Levantar un Nuevo Pedido
La creación de un pedido inicializará automáticamente su estado en `PENDIENTE` y creará un registro de **Trazabilidad** ("Pedido Registrado") que es visible en el Dashboard.
- **Endpoint:** `POST /api/orders`
- **Payload:**
  ```json
  {
    "tenantId": "petroil",
    "customerPhone": "+526645550101",
    "customerName": "Juan Pérez",
    "deliveryAddress": "Av. Paseo de los Héroes #1020",
    "latitude": 32.5312,
    "longitude": -117.0223,
    "channel": "WHATSAPP",
    "paymentMethod": "EFECTIVO",
    "notes": "Llamar al llegar",
    "items": [
      { "productId": "<ID_DEL_PRODUCTO>", "quantity": 1 }
    ]
  }
  ```

---

## 3. Flujo del Bot de Choferes (Driver Bot)

El bot de choferes ahora maneja turnos (shifts), visualización de pedidos asignados, cambio de estado (ruta, cancelado, entregado) y registro de firmas. Todo esto afecta directamente la **Bitácora de Trazabilidad** (`/traceability` en el Dashboard).

### Autenticación del Chofer
- **Endpoint:** `POST /api/admin/drivers/login`
- **Header:** `x-tenant-id: petroil`
- **Payload:** `{ "phone": "+52...", "password": "..." }`

### Gestión de Turnos (Shifts)
Para que el Dashboard asigne pedidos, **el chofer debe tener un turno activo**.
- **Iniciar Turno:** `POST /api/admin/shifts/start`
  - Payload: `{ "driverId": "ID_CHOFER", "vehicleId": "ID_VEHICULO", "initialReading": 0 }`
  - *Nota: Esto crea un evento en la bitácora global del dashboard indicando que el chofer empezó a trabajar.*
- **Terminar Turno:** `PUT /api/admin/shifts/end`
  - Payload: `{ "driverId": "ID_CHOFER", "finalReading": 100 }`

### Ver Pedidos Asignados
- **Endpoint:** `GET /api/admin/drivers/:driverId/orders`
- Retorna todos los pedidos que el operador central le asignó al chofer desde el Dashboard.

### Actualizar Estado del Pedido (Ruta, Cancelación y Entrega)
Este endpoint es crítico porque ahora **dispara los eventos de Trazabilidad** para el Dashboard.
- **Endpoint:** `PUT /api/admin/drivers/:driverId/orders/:orderId/status`
- **Header:** `x-tenant-id: petroil`

**A. Voy en camino:**
```json
{
  "status": "EN_RUTA"
}
```

**B. Entregar Pedido (Con firma en Base64):**
La PWA y el Dashboard ahora soportan la firma digital del cliente. Si el bot de Telegram/Chofer solicita una foto de comprobante o firma, puedes enviarla como base64.
```json
{
  "status": "ENTREGADO",
  "signature": "data:image/png;base64,iVBORw0KGgoAAAANSU..."
}
```

**C. Cancelar Pedido:**
```json
{
  "status": "CANCELADO",
  "reason": "El cliente no estaba en el domicilio"
}
```
*La cancelación se registrará en la Trazabilidad y también en el submódulo de Rechazos del Dashboard.*

### Actualización de Ubicación GPS
Para que el Dashboard dibuje los camioncitos en el mapa en tiempo real, el bot del chofer debe enviar la ubicación periódicamente.
- **Endpoint:** `POST /api/admin/drivers/:driverId/location`
- **Payload:** `{ "lat": 32.5111, "lng": -117.0312 }`

## 4. Cambios y Mejoras Recientes a Considerar
1. **Trazabilidad Detallada:** Ya no es necesario registrar a mano en otras tablas la trazabilidad. Simplemente con invocar `/orders` (POST) o actualizar estados con el endpoint del Driver, el backend NestJS inserta la trazabilidad con toda la información (nombre del chofer asignado, nombre del cliente, dirección, hora, firma del cliente) para mostrarse en el módulo `/traceability`.
2. **Restricción de Choferes:** Si el bot del chofer no inicia su turno (`/shifts/start`), este no aparecerá "Disponible" en el Dashboard del despachador, imposibilitando que se le asignen pedidos.
3. **Firmas y Evidencias:** La nueva integración con `metadata` de Trazabilidad permite guardar la imagen `signature` cuando el estado pase a `ENTREGADO`. El dashboard de Nuxt lee este metadato y renderiza la foto o firma directamente en el modal de Detalles de Operación.
