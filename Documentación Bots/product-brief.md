# Product Brief: Bots de Usuario Omnicanal (Gas a tu Puerta)

**Cliente:** Grupo Petroil — División Gas (Mazatlán, Sinaloa)  
**Versión:** 3.5.0 Enterprise — Enfocada Exclusivamente en Canales de Usuario (Telegram, WhatsApp, Facebook Messenger e Instagram Direct)  
**Estado:** Documento Maestro Aprobado y Operativo  
**Fecha:** Octubre 2026  

---

## 1. Executive Summary

El subsistema de **Bots de Usuario Omnicanal** de la plataforma **Gas a Tu Puerta - Petroil** es la solución tecnológica integral que automatiza, agiliza y unifica la captación de pedidos de Gas LP (cilindros de 10, 20, 30 y 45 kg y recarga en tanque estacionario por litro) para clientes residenciales y comerciales en Mazatlán, Sinaloa.

Históricamente, la atención al cliente enfrentaba fricciones severas: saturación de líneas telefónicas en horas pico, tiempos de espera superiores a 5 minutos, errores humanos en la captura manual de direcciones complejas en fraccionamientos nuevos y falta total de visibilidad sobre el estatus de entrega.

Para erradicar estos cuellos de botella, Grupo Petroil implementó un ecosistema de **4 bots conversacionales orientados 100% al usuario final**, integrados bajo un único motor inteligente y determinista (`FlowRouter` + `LangGraph`):

1. **Bot de Usuario en Telegram (`telegram_bot.py`):** Interfaz ultrarrápida impulsada por `python-telegram-bot` v20+ con teclados interactivos dinámicos (`InlineKeyboardMarkup`), compartición nativa de ubicación GPS y tarjeta de contacto telefónico en un toque (`ReplyKeyboardMarkup`), soporte para notas de voz transcritas por Whisper y visualización de ubicación del repartidor en camino.
2. **Bot de Usuario en WhatsApp Cloud API (`src/channels/whatsapp/`):** Canal de máxima penetración masiva en México operando sobre Meta Graph API v21.0. Combina mensajes de lista interactiva (`type: list`) para catálogos y libretas de direcciones, botones rápidos (`type: button`), carrito interactivo temporal con control de cantidades (`wa_carts`), recepción de ubicaciones GPS nativas de WhatsApp y notas de voz Opus transcritas automáticamente.
3. **Bot de Usuario en Facebook Messenger (`src/channels/messenger/`):** Canal nativo para usuarios de Facebook y visitantes de la FanPage oficial de Petroil Gas. Implementa carruseles enriquecidos (`Generic Template`) con imágenes y fichas técnicas de cilindros, botones de respuesta rápida (`Quick Replies`), validación criptográfica de firmas HMAC-SHA256 (`X-Hub-Signature-256`), deduplicación de eventos por Message ID y vinculación de Page-Scoped ID (PSID) a la identidad telefónica del cliente.
4. **Bot de Usuario en Instagram Direct (`src/channels/instagram/`):** Canal especializado en audiencias jóvenes y comerciales provenientes de la cuenta de Instagram de Grupo Petroil y campañas publicitarias en Meta. Proporciona menús táctiles deslizables de hasta 13 botones rápidos, tarjetas visuales de producto, procesamiento de audios en formato M4A/AAC y enlace directo de Instagram-Scoped ID (IGSID) con el historial de compras en Mazatlán.

Los 4 canales convergen en un modelo de identidad unificada (`IdentityStore`), garantizando que un cliente que inicia su compra en Instagram pueda consultar el estatus en WhatsApp o recibir su factura y encuesta CSAT en Telegram sin fricción ni inconsistencias.

---

## 2. Product Vision

> *"Ofrecer a cada familia y negocio de Mazatlán una experiencia de compra de Gas LP inmediata, transparente y sin esperas, permitiéndoles solicitar su gas en menos de 60 segundos desde su aplicación de mensajería preferida (Telegram, WhatsApp, Messenger o Instagram), con precios reales de catálogo, geolocalización satelital precisa, notificaciones proactivas de entrega y evaluación directa del servicio."*

---

## 3. El Problema de Negocio del Cliente

Antes del despliegue de los bots de usuario omnicanal, el cliente final enfrentaba los siguientes puntos de dolor críticos:

1. **Pérdida de Tiempo en Espera Telefónica:** En horarios de alta demanda (mañanas y fines de semana), las líneas telefónicas tradicionales se saturaban, provocando que hasta un 32% de las llamadas se perdieran o abandonaran hacia gaseras de la competencia.
2. **Fricción al Escribir Direcciones Largas:** Escribir calles sin nomenclatura formal, andadores o fraccionamientos en desarrollo (ej. Real Pacífico, Pradera Dorada, Cerritos) generaba errores recurrentes en el despacho de los repartidores.
3. **Incertidumbre del Pedido ("¿A qué hora llega mi gas?"):** El cliente desconocía si su pedido había sido asignado a una pipa o camioneta, cuál chofer lo atendía y a cuántos minutos se encontraba de su domicilio.
4. **Barrera de Instalación de Nuevas Apps:** Los clientes residenciales rechazan descargar aplicaciones pesadas (APKs o apps dedicadas de tiendas de apps) solo para pedir gas una o dos veces al mes. Requerían un canal nativo que ya tuvieran instalado en su teléfono.
5. **Falta de Claridad en Precios Oficiales:** Dudas constantes sobre el importe exacto a pagar en efectivo o tarjeta al chofer, provocando discusiones y desconfianza en el momento del cobro.

---

## 4. Oportunidad y Propuesta de Valor Omnicanal

La estrategia implementada se fundamenta en llevar la gasera a los canales donde los usuarios ya interactúan a diario:

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                ECOSISTEMA BOTS DE USUARIO PETROIL                                │
├─────────────────┬──────────────────┬─────────────────────────┬───────────────────────────────────┤
│ TELEGRAM BOT    │ WHATSAPP CLOUD   │ FACEBOOK MESSENGER      │ INSTAGRAM DIRECT                  │
├─────────────────┼──────────────────┼─────────────────────────┼───────────────────────────────────┤
│ • Botones Inline│ • Listas Meta    │ • Carruseles visuales   │ • Quick Replies deslizables       │
│ • GPS nativo    │ • Botones de 3   │ • Quick Replies         │ • Fichas visuales en DM           │
│ • Contacto 1-tap│ • Carrito wa_cart│ • Firma HMAC-SHA256     │ • Conexión con Stories / Ads      │
│ • Whisper Audio │ • Audio OGG Opus │ • Mapeo PSID a Teléfono │ • Mapeo IGSID a Teléfono          │
│ • Live Location │ • Ventana 24h    │ • Whisper Audio         │ • Whisper Audio                   │
└─────────────────┴──────────────────┴─────────────────────────┴───────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                   MOTOR CONVERSACIONAL DETERMINISTA + IA (FlowRouter)                            │
│  • Catálogo PostgreSQL en Vivo  • Geocodificación Nominatim  • IdentityStore Cross-Channel       │
│  • Horarios de Atención         • Métodos de Pago           • CSAT 1-5 ⭐ Post-Entrega          │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Propuesta de Valor Específica por Canal

* **Telegram (`telegram_bot.py`):** Máxima fluidez para usuarios avanzados y clientes que valoran la velocidad instantánea, sin límites de botones en pantalla y con capacidad de compartir ubicación y teléfono nativamente sin escribir un solo dígito.
* **WhatsApp (`src/channels/whatsapp/`):** Penetración del 95%+ de los hogares en Mazatlán. Proporciona una experiencia limpia mediante listas desplegables para selección de cilindros (10, 20, 30, 45 kg) o pedidos estacionarios, botones de confirmación y plantillas de notificación de entrega.
* **Facebook Messenger (`src/channels/messenger/`):** Captación natural de clientes desde la FanPage de Petroil Gas y grupos locales de colonias en Facebook. Permite carruseles interactivos con imágenes reales de los cilindros y botones directos de "Comprar Ahora".
* **Instagram Direct (`src/channels/instagram/`):** Atracción de usuarios jóvenes, departamentos y negocios gastronómicos modernos que descubren promociones de Petroil en Instagram y completan su pedido sin abandonar la red social.

---

## 5. Objetivos del Producto y Métricas Clave (KPIs)

| Indicador Clave (KPI) | Definición | Meta Target | Mecanismo de Auditoría |
| :--- | :--- | :---: | :--- |
| **Tiempo de Conversión (Toma de Pedido)** | Tiempo transcurrido desde el primer "Hola" hasta la confirmación formal del pedido con folio | $< 75$ segundos | Timestamps en `flow_router` e `IdentityStore` |
| **Tasa de Finalización de Compra** | Porcentaje de sesiones iniciadas que culminan en un pedido creado exitosamente | $> 82\%$ | Métricas de sesión en `FlowState.COMPLETED` |
| **Tasa de Autoservicio Digital** | Porcentaje de pedidos completados 100% por bot sin requerir llamada a call center | $> 85\%$ | Comparativa pedidos Bot vs Venta Directa en BD |
| **Precisión de Geolocalización** | Porcentaje de pedidos con coordenadas válidas (GPS nativo o geocodificación satelital) | $> 96\%$ | Coordenadas lat/lng registradas en tabla `ORDERS` |
| **Adopción de Notas de Voz** | Tasa de éxito en la transcripción y procesamiento de notas de voz recibidas | $> 98\%$ | Logs del servicio `audio_transcription.py` |
| **Satisfacción del Cliente (CSAT)** | Calificación promedio post-servicio en escala de 1 a 5 estrellas recibida en los bots | $\ge 4.7 / 5.0$ ⭐ | Tabla `ORDER_RATINGS` en PostgreSQL |
| **Retención y Compra Recurrente** | Clientes que vuelven a ordenar usando su libreta de direcciones guardadas | $> 65\%$ | Compras recurrentes por número telefónico |

---

## 6. Stakeholders y Audiencia Clave

* **Clientes Finales Residenciales (Mazatlán):** Usuarios domésticos que requieren suministro de Gas LP de manera recurrente para estufas, calentadores de agua y secadoras.
* **Clientes Comerciales (Restaurantes, Taquerías, Hotelería):** Negocios que necesitan recargas de gas estacionario o baterías de cilindros de 45 kg con confirmación inmediata y comprobante.
* **Equipo de Soporte y Supervisión Digital:** Operadores que monitorean la Torre de Control y asisten a usuarios si ocurre alguna excepción o dirección no reconocida.
* **Dirección Comercial y Marketing de Grupo Petroil:** Interesados en la conversión de campañas en redes sociales (Meta Ads, Instagram Stories, Facebook Posts) a ventas tangibles de gas.

---

## 7. User Personas por Canal

### 7.1. Persona 1: Canal WhatsApp — Doña María (Cliente Residencial Tradicional)
* **Edad:** 48 años.
* **Ubicación:** Fraccionamiento Alarcón, Mazatlán.
* **Comportamiento:** Utiliza WhatsApp para todo: comunicarse con su familia, grupos escolares y compras locales. No sabe instalar APKs ni quiere entrar a sitios web complejos.
* **Interacción con el Bot:** Envía un mensaje *"Ocupo un cilindro de 30 kilos"*. El bot de WhatsApp le muestra la lista interactiva, ella toca `[ 🟢 Cilindro 30 kg — $670.00 ]`, el bot reconoce su teléfono automáticamente, le despliega su dirección guardada *"Av. del Delfín #402"*, selecciona *"Efectivo"* y confirma en 3 toques.

### 7.2. Persona 2: Canal Telegram — Carlos (Profesional Joven / Tech-Savvy)
* **Edad:** 29 años.
* **Ubicación:** Fraccionamiento Marina Mazatlán.
* **Comportamiento:** Prefiere Telegram por velocidad, privacidad y consumo mínimo de datos móviles.
* **Interacción con el Bot:** Abre `@PetroilGasBot`, pulsa `/start`, presiona `[ 🛢️ Cilindros ]`, elige 1 cilindro de 20 kg, comparte su ubicación en tiempo real con el botón de GPS nativo de Telegram, selecciona pago con terminal bancaria y confirma. Posteriormente recibe la notificación en vivo con la placa de la camioneta y el enlace de seguimiento.

### 7.3. Persona 3: Canal Facebook Messenger — Don Roberto (Dueño de Restaurante en Olas Altas)
* **Edad:** 54 años.
* **Ubicación:** Paseo Olas Altas, Centro Histórico de Mazatlán.
* **Comportamiento:** Administra la página de Facebook de su restaurante desde su laptop o teléfono.
* **Interacción con el Bot:** Ve una publicación de Petroil Gas en Facebook y hace clic en *"Enviar Mensaje"*. El bot de Messenger le presenta el carrusel de productos, Don Roberto selecciona `[ 🔥 Gas Estacionario ]`, ingresa el importe requerido ($2,500 MXN), programa la entrega para las 3:30 PM antes del turno de cena y confirma con un toque.

### 7.4. Persona 4: Canal Instagram Direct — Sofía (Emprendedora / Millennial)
* **Edad:** 25 años.
* **Ubicación:** Zona Dorada, Mazatlán.
* **Comportamiento:** Pasa gran parte de su tiempo libre en Instagram. Sigue marcas locales y prefiere resolver todo por mensajes directos (DM).
* **Interacción con el Bot:** Responde a una historia de Petroil con un emoji. El bot activa el flujo de bienvenida con Quick Replies deslizables. Sofía elige cilindro de 30 kg, envía una nota de voz diciendo *"Es en el departamento 3B de la torre frente a la playa"*, el bot transcribe el audio, valida la dirección, confirma el pedido y al entregarse le manda la encuesta de 5 estrellas directamente en el chat de Instagram.

---

## 8. Alcance del Ecosistema de Bots de Usuario

### Dentro del Alcance (In-Scope)
* Flujo de ventas guiado en 10 pasos estructurados para Cilindros y Gas Estacionario en los 4 canales.
* Catálogo dinámico y sincronizado de precios reales consultado desde PostgreSQL/SQLite.
* Carrito interactivo multi-producto con sumatoria de importes en tiempo real.
* Identificación automática del cliente por su número telefónico a 10 dígitos.
* Gestión de libreta multi-dirección (guardar, seleccionar y borrar direcciones).
* Geocodificación híbrida: GPS satelital nativo en Telegram, WhatsApp y Messenger, y geocodificación de texto con Nominatim.
* Validación de ventanas de horario de atención comercial con propuesta inteligente de reprogramación.
* Selección de método de pago (Efectivo con cambio, Tarjeta con terminal física, Transferencia SPEI).
* Generación de resumen de compra estructurado con confirmación afirmativa obligatoria.
* Notificaciones push directas de cambio de estado (`assigned`, `in_route`, `delivered`, `cancelled`).
* Módulo de transcripción de notas de voz mediante OpenAI Whisper.
* Encuesta de satisfacción CSAT interactiva de 1 a 5 estrellas con registro de comentarios.

### Fuera del Alcance (Out-of-Scope)
* Gestión operativa de choferes, turnos y odómetros (reservado exclusivamente para el bot de choferes `driver_bot.py`).
* Modificación de tarifas y precios de gas (reservado para la Torre de Control Web y administradores).
* Procesamiento de pagos en línea con pasarela de tarjeta web dentro del chat (los cobros se efectúan contra entrega en efectivo o terminal bancaria móvil del chofer).

---

## 9. Supuestos, Dependencias y Riesgos

* **Dependencia de APIs de Terceros:** El funcionamiento de WhatsApp, Messenger e Instagram depende de la disponibilidad de Meta Graph API. Telegram depende de Telegram Bot API. Se implementaron mecanismos de reintento automático y refresco dinámico de tokens ante errores 401.
* **Latencia de Transcripción de Audio:** El servicio de Whisper requiere conexión estable a internet. En caso de timeout (> 5 segundos), el bot solicita cordialmente al usuario escribir su requerimiento en texto.
* **Idempotencia de Mensajería:** Meta puede enviar webhooks duplicados. Se implementó un middleware de deduplicación con caché de Message IDs y TTL de 10 minutos para evitar pedidos duplicados.
