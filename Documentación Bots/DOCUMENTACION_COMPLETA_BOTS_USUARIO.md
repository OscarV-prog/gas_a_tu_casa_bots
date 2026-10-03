# 📱 Documentación Integral: Bots de Usuario Omnicanal (Gas a tu Puerta)

> **Documento Maestro Fusionado — Especificaciones de Producto, Contexto de Negocio, PRD, Arquitectura C4, Flujos de Usuario, Diseño UX/UI y Backlog Ágil**  
> **Cliente:** Grupo Petroil — División Gas (Mazatlán, Sinaloa)  
> **Versión:** 3.5.0 Enterprise — Cobertura Exclusiva de Canales de Usuario: Telegram (`telegram_bot.py`), WhatsApp Cloud API (`src/channels/whatsapp/`), Facebook Messenger (`src/channels/messenger/`) e Instagram Direct (`src/channels/instagram/`)  
> **Estado:** Documentación Oficial Aprobada y en Operación  
> **Fecha de Emisión:** Octubre 2026  

---

## 📑 Tabla de Contenidos General

1. [Parte 1: Product Brief — Visión, Negocio, Buyer Personas y KPIs](#parte-1-product-brief)
   - 1.1 [Executive Summary](#11-executive-summary)
   - 1.2 [Product Vision](#12-product-vision)
   - 1.3 [El Problema de Negocio del Cliente](#13-el-problema-de-negocio-del-cliente)
   - 1.4 [Oportunidad y Propuesta de Valor Omnicanal](#14-oportunidad-y-propuesta-de-valor-omnicanal)
   - 1.5 [Objetivos del Producto y Métricas Clave (KPIs)](#15-objetivos-del-producto-y-métricas-clave-kpis)
   - 1.6 [Stakeholders y Audiencia Clave](#16-stakeholders-y-audiencia-clave)
   - 1.7 [User Personas por Canal de Mensajería](#17-user-personas-por-canal-de-mensajería)
   - 1.8 [Alcance del Ecosistema de Bots de Usuario](#18-alcance-del-ecosistema-de-bots-de-usuario)
   - 1.9 [Supuestos, Dependencias y Riesgos](#19-supuestos-dependencias-y-riesgos)
2. [Parte 2: Product Context — Ecosistema, Identidad Unificada y Dominio](#parte-2-product-context)
   - 2.1 [Visión General del Contexto de Negocio en Mazatlán](#21-visión-general-del-contexto-de-negocio-en-mazatlán)
   - 2.2 [Ecosistema de Canales de Usuario](#22-ecosistema-de-canales-de-usuario)
   - 2.3 [Matriz Comparativa Detallada de Canales](#23-matriz-comparativa-detallada-de-canales)
   - 2.4 [Modelo Unificado de Identidad de Usuario (IdentityStore)](#24-modelo-unificado-de-identidad-de-usuario-identitystore)
   - 2.5 [Entidades Principales del Dominio de Clientes](#25-entidades-principales-del-dominio-de-clientes)
   - 2.6 [Servicios y Módulos Compartidos](#26-servicios-y-módulos-compartidos)
   - 2.7 [Ciclo de Vida del Pedido desde la Perspectiva del Usuario](#27-ciclo-de-vida-del-pedido-desde-la-perspectiva-del-usuario)
3. [Parte 3: Product Requirements Document (PRD) — Especificación de Requerimientos](#parte-3-product-requirements-document-prd)
   - 3.1 [Control de Versiones del PRD](#31-control-de-versiones-del-prd)
   - 3.2 [Máquina de Estados Conversacional (FlowState)](#32-máquina-de-estados-conversacional-flowstate)
   - 3.3 [Requerimientos Funcionales Generales (Cross-Channel: RF-01 a RF-12)](#33-requerimientos-funcionales-generales-cross-channel)
   - 3.4 [Especificaciones Técnicas Particulares por Canal](#34-especificaciones-técnicas-particulares-por-canal)
   - 3.5 [Requerimientos No Funcionales (RNF-01 a RNF-04)](#35-requerimientos-no-funcionales)
   - 3.6 [Matriz de Trazabilidad Requerimientos vs Código](#36-matriz-de-trazabilidad-requerimientos-vs-código)
4. [Parte 4: Architecture Design Document (ADD) — Modelado C4 y Diagramas de Secuencia](#parte-4-architecture-design-document-add)
   - 4.1 [Principios Arquitectónicos (Zero-LLM Rule y Puertos/Adaptadores)](#41-principios-arquitectónicos)
   - 4.2 [Modelado C4 del Subsistema de Bots de Usuario (Nivel 1, 2 y 3)](#42-modelado-c4-del-subsistema-de-bots-de-usuario)
   - 4.3 [Contratos de Datos y Modelos Internos (InboundMessage, OutboundMessage, Carritos)](#43-contratos-de-datos-y-modelos-internos)
   - 4.4 [Diagramas de Secuencia Detallados (Webhooks, Whisper y Notificaciones CSAT)](#44-diagramas-de-secuencia-detallados)
   - 4.5 [Topología de Despliegue y Variables de Entorno (.env)](#45-topología-de-despliegue-y-variables-de-entorno-env)
5. [Parte 5: User Flows & Navigation — Mapas de Flujo y Casos de Uso](#parte-5-user-flows--navigation)
   - 5.1 [Propósito y Modelo Canónico](#51-propósito-y-modelo-canónico)
   - 5.2 [Flujo Principal de Compra (Happy Path de 10 Pasos)](#52-flujo-principal-de-compra-happy-path-de-10-pasos)
   - 5.3 [Flujos Alternativos y Excepciones (Flujos A al G)](#53-flujos-alternativos-y-excepciones)
   - 5.4 [Mapeo Visual de Interacción por Plataforma](#54-mapeo-visual-de-interacción-por-plataforma)
6. [Parte 6: Especificación UX/UI — Copywriting, Ergonomía y Tokens Visuales](#parte-6-especificación-uxui)
   - 6.1 [Filosofía de Diseño y Tono de Voz Institucional](#61-filosofía-de-diseño-y-tono-de-voz-institucional)
   - 6.2 [Sistema de Tokens Visuales y Emojis Semánticos](#62-sistema-de-tokens-visuales-y-emojis-semánticos)
   - 6.3 [Especificación de Componentes UI por Plataforma](#63-especificación-de-componentes-ui-por-plataforma)
   - 6.4 [Copywriting Oficial y Plantillas de Mensajes](#64-copywriting-oficial-y-plantillas-de-mensajes)
   - 6.5 [Matriz de Errores, Recuperación y Fallbacks](#65-matriz-de-errores-recuperación-y-fallbacks)
7. [Parte 7: Plan de Implementación Ágil — Epics, Features y Historias de Usuario](#parte-7-plan-de-implementación-ágil)
   - 7.1 [Índice General de Épicas de Bots de Usuario](#71-índice-general-de-épicas-de-bots-de-usuario)
   - 7.2 [EPIC-BOT-01: Bot de Usuario en Telegram](#72-epic-bot-01-bot-de-usuario-en-telegram)
   - 7.3 [EPIC-BOT-02: Bot de Usuario en WhatsApp Cloud API](#73-epic-bot-02-bot-de-usuario-en-whatsapp-cloud-api)
   - 7.4 [EPIC-BOT-03: Bot de Usuario en Facebook Messenger](#74-epic-bot-03-bot-de-usuario-en-facebook-messenger)
   - 7.5 [EPIC-BOT-04: Bot de Usuario en Instagram Direct](#75-epic-bot-04-bot-de-usuario-en-instagram-direct)
   - 7.6 [EPIC-BOT-05: Motor Conversacional Central y Carrito Multi-Producto](#76-epic-bot-05-motor-conversacional-central-y-carrito-multi-producto)
   - 7.7 [EPIC-BOT-06: Identidad Cross-Channel, Geocodificación y Whisper](#77-epic-bot-06-identidad-cross-channel-geocodificación-y-whisper)
   - 7.8 [EPIC-BOT-07: Notificaciones Push de Entrega y Calificación CSAT](#78-epic-bot-07-notificaciones-push-de-entrega-y-calificación-csat)

---

# PARTE 1: PRODUCT BRIEF

---

## 1.1. Executive Summary

El subsistema de **Bots de Usuario Omnicanal** de la plataforma **Gas a Tu Puerta - Petroil** es la solución tecnológica integral que automatiza, agiliza y unifica la captación de pedidos de Gas LP (cilindros de 10, 20, 30 y 45 kg y recarga en tanque estacionario por litro) para clientes residenciales y comerciales en Mazatlán, Sinaloa.

Históricamente, la atención al cliente enfrentaba fricciones severas: saturación de líneas telefónicas en horas pico, tiempos de espera superiores a 5 minutos, errores humanos en la captura manual de direcciones complejas en fraccionamientos nuevos y falta total de visibilidad sobre el estatus de entrega.

Para erradicar estos cuellos de botella, Grupo Petroil implementó un ecosistema de **4 bots conversacionales orientados 100% al usuario final**, integrados bajo un único motor inteligente y determinista (`FlowRouter` + `LangGraph`):

1. **Bot de Usuario en Telegram (`telegram_bot.py`):** Interfaz ultrarrápida impulsada por `python-telegram-bot` v20+ con teclados interactivos dinámicos (`InlineKeyboardMarkup`), compartición nativa de ubicación GPS y tarjeta de contacto telefónico en un toque (`ReplyKeyboardMarkup`), soporte para notas de voz transcritas por Whisper y visualización de ubicación del repartidor en camino.
2. **Bot de Usuario en WhatsApp Cloud API (`src/channels/whatsapp/`):** Canal de máxima penetración masiva en México operando sobre Meta Graph API v21.0. Combina mensajes de lista interactiva (`type: list`) para catálogos y libretas de direcciones, botones rápidos (`type: button`), carrito interactivo temporal con control de cantidades (`wa_carts`), recepción de ubicaciones GPS nativas de WhatsApp y notas de voz Opus transcritas automáticamente.
3. **Bot de Usuario en Facebook Messenger (`src/channels/messenger/`):** Canal nativo para usuarios de Facebook y visitantes de la FanPage oficial de Petroil Gas. Implementa carruseles enriquecidos (`Generic Template`) con imágenes y fichas técnicas de cilindros, botones de respuesta rápida (`Quick Replies`), validación criptográfica de firmas HMAC-SHA256 (`X-Hub-Signature-256`), deduplicación de eventos por Message ID y vinculación de Page-Scoped ID (PSID) a la identidad telefónica del cliente.
4. **Bot de Usuario en Instagram Direct (`src/channels/instagram/`):** Canal especializado en audiencias jóvenes y comerciales provenientes de la cuenta de Instagram de Grupo Petroil y campañas publicitarias en Meta. Proporciona menús táctiles deslizables de hasta 13 botones rápidos, tarjetas visuales de producto, procesamiento de audios en formato M4A/AAC y enlace directo de Instagram-Scoped ID (IGSID) con el historial de compras en Mazatlán.

Los 4 canales convergen en un modelo de identidad unificada (`IdentityStore`), garantizando que un cliente que inicia su compra en Instagram pueda consultar el estatus en WhatsApp o recibir su factura y encuesta CSAT en Telegram sin fricción ni inconsistencias.

---

## 1.2. Product Vision

> *"Ofrecer a cada familia y negocio de Mazatlán una experiencia de compra de Gas LP inmediata, transparente y sin esperas, permitiéndoles solicitar su gas en menos de 60 segundos desde su aplicación de mensajería preferida (Telegram, WhatsApp, Messenger o Instagram), con precios reales de catálogo, geolocalización satelital precisa, notificaciones proactivas de entrega y evaluación directa del servicio."*

---

## 1.3. El Problema de Negocio del Cliente

Antes del despliegue de los bots de usuario omnicanal, el cliente final enfrentaba los siguientes puntos de dolor críticos:

1. **Pérdida de Tiempo en Espera Telefónica:** En horarios de alta demanda (mañanas y fines de semana), las líneas telefónicas tradicionales se saturaban, provocando que hasta un 32% de las llamadas se perdieran o abandonaran hacia gaseras de la competencia.
2. **Fricción al Escribir Direcciones Largas:** Escribir calles sin nomenclatura formal, andadores o fraccionamientos en desarrollo (ej. Real Pacífico, Pradera Dorada, Cerritos) generaba errores recurrentes en el despacho de los repartidores.
3. **Incertidumbre del Pedido ("¿A qué hora llega mi gas?"):** El cliente desconocía si su pedido había sido asignado a una pipa o camioneta, cuál chofer lo atendía y a cuántos minutos se encontraba de su domicilio.
4. **Barrera de Instalación de Nuevas Apps:** Los clientes residenciales rechazan descargar aplicaciones pesadas (APKs o apps dedicadas de tiendas de apps) solo para pedir gas una o dos veces al mes. Requerían un canal nativo que ya tuvieran instalado en su teléfono.
5. **Falta de Claridad en Precios Oficiales:** Dudas constantes sobre el importe exacto a pagar en efectivo o tarjeta al chofer, provocando discusiones y desconfianza en el momento del cobro.

---

## 1.4. Oportunidad y Propuesta de Valor Omnicanal

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

## 1.5. Objetivos del Producto y Métricas Clave (KPIs)

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

## 1.6. Stakeholders y Audiencia Clave

* **Clientes Finales Residenciales (Mazatlán):** Usuarios domésticos que requieren suministro de Gas LP de manera recurrente para estufas, calentadores de agua y secadoras.
* **Clientes Comerciales (Restaurantes, Taquerías, Hotelería):** Negocios que necesitan recargas de gas estacionario o baterías de cilindros de 45 kg con confirmación inmediata y comprobante.
* **Equipo de Soporte y Supervisión Digital:** Operadores que monitorean la Torre de Control y asisten a usuarios si ocurre alguna excepción o dirección no reconocida.
* **Dirección Comercial y Marketing de Grupo Petroil:** Interesados en la conversión de campañas en redes sociales (Meta Ads, Instagram Stories, Facebook Posts) a ventas tangibles de gas.

---

## 1.7. User Personas por Canal de Mensajería

### Persona 1: Canal WhatsApp — Doña María (Cliente Residencial Tradicional)
* **Perfil:** 48 años, Fraccionamiento Alarcón, Mazatlán.
* **Comportamiento:** Utiliza WhatsApp para todo: comunicarse con su familia, grupos escolares y compras locales. No sabe instalar APKs ni quiere entrar a sitios web complejos.
* **Interacción con el Bot:** Envía un mensaje *"Ocupo un cilindro de 30 kilos"*. El bot de WhatsApp le muestra la lista interactiva, ella toca `[ 🟢 Cilindro 30 kg — $670.00 ]`, el bot reconoce su teléfono automáticamente, le despliega su dirección guardada *"Av. del Delfín #402"*, selecciona *"Efectivo"* y confirma en 3 toques.

### Persona 2: Canal Telegram — Carlos (Profesional Joven / Tech-Savvy)
* **Perfil:** 29 años, Fraccionamiento Marina Mazatlán.
* **Comportamiento:** Prefiere Telegram por velocidad, privacidad y consumo mínimo de datos móviles.
* **Interacción con el Bot:** Abre `@PetroilGasBot`, pulsa `/start`, presiona `[ 🛢️ Cilindros ]`, elige 1 cilindro de 20 kg, comparte su ubicación en tiempo real con el botón de GPS nativo de Telegram, selecciona pago con terminal bancaria y confirma. Posteriormente recibe la notificación en vivo con la placa de la camioneta y el enlace de seguimiento.

### Persona 3: Canal Facebook Messenger — Don Roberto (Dueño de Restaurante en Olas Altas)
* **Perfil:** 54 años, Paseo Olas Altas, Centro Histórico de Mazatlán.
* **Comportamiento:** Administra la página de Facebook de su restaurante desde su laptop o teléfono.
* **Interacción con el Bot:** Ve una publicación de Petroil Gas en Facebook y hace clic en *"Enviar Mensaje"*. El bot de Messenger le presenta el carrusel de productos, Don Roberto selecciona `[ 🔥 Gas Estacionario ]`, ingresa el importe requerido ($2,500 MXN), programa la entrega para las 3:30 PM antes del turno de cena y confirma con un toque.

### Persona 4: Canal Instagram Direct — Sofía (Emprendedora / Millennial)
* **Perfil:** 25 años, Zona Dorada, Mazatlán.
* **Comportamiento:** Pasa gran parte de su tiempo libre en Instagram. Sigue marcas locales y prefiere resolver todo por mensajes directos (DM).
* **Interacción con el Bot:** Responde a una historia de Petroil con un emoji. El bot activa el flujo de bienvenida con Quick Replies deslizables. Sofía elige cilindro de 30 kg, envía una nota de voz diciendo *"Es en el departamento 3B de la torre frente a la playa"*, el bot transcribe el audio, valida la dirección, confirma el pedido y al entregarse le manda la encuesta de 5 estrellas directamente en el chat de Instagram.

---

## 1.8. Alcance del Ecosistema de Bots de Usuario

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

## 1.9. Supuestos, Dependencias y Riesgos

* **Dependencia de APIs de Terceros:** El funcionamiento de WhatsApp, Messenger e Instagram depende de la disponibilidad de Meta Graph API. Telegram depende de Telegram Bot API. Se implementaron mecanismos de reintento automático y refresco dinámico de tokens ante errores 401.
* **Latencia de Transcripción de Audio:** El servicio de Whisper requiere conexión estable a internet. En caso de timeout (> 5 segundos), el bot solicita cordialmente al usuario escribir su requerimiento en texto.
* **Idempotencia de Mensajería:** Meta puede enviar webhooks duplicados. Se implementó un middleware de deduplicación con caché de Message IDs y TTL de 10 minutos para evitar pedidos duplicados.

---

# PARTE 2: PRODUCT CONTEXT

---

## 2.1. Visión General del Contexto de Negocio en Mazatlán

El proyecto **Gas a Tu Puerta - Petroil** opera en el mercado de distribución minorista y comercial de Gas Licuado de Petróleo (Gas LP) en el municipio de Mazatlán, Sinaloa. La operación atiende dos modalidades esenciales de consumo:

1. **Venta de Cilindros Portátiles:** Suministro a domicilio de cilindros metálicos presurizados de 10 kg, 20 kg, 30 kg y 45 kg, distribuidos mediante camionetas de redilas con choferes repartidores.
2. **Suministro a Tanque Estacionario:** Recarga de gas líquido por volumen en litros mediante camiones cisterna presurizados (pipas), solicitada comúnmente por importe en pesos (ej. "$500 MXN", "$1,200 MXN") o por porcentaje de llenado (ej. "llenar al 80%").

### Particularidades Geográficas y Operativas de Mazatlán
* **Diversidad de Zonas Urbanas:** La plaza combina zonas tradicionales y turísticas (Centro Histórico, Paseo Olas Altas, Zona Dorada, Cerritos) con fraccionamientos residenciales consolidados (El Conchi, Fracc. del Bosque, Villa Verde, Misiones) y complejos suburbanos en rápida expansión (Pradera Dorada etapas I-VII, Santa Teresa, Real del Valle) donde las calles y códigos postales suelen no estar debidamente indexados en cartografías comerciales tradicionales.
* **Demanda Climática y Estacional:** Picos marcados de demanda matutina (6:30 AM a 10:00 AM) para uso doméstico, y demanda comercial vespertina para establecimientos gastronómicos y hoteleros a lo largo del Malecón.
* **Comportamiento Digital del Usuario Local:** La casi totalidad de la población cuenta con WhatsApp como su herramienta primaria de comunicación diaria, mientras que sectores jóvenes utilizan intensivamente Instagram Direct, usuarios de mediana edad mantienen interacción constante con negocios a través de Facebook Messenger, y audiencias técnicas o con alta exigencia de rapidez prefieren Telegram.

---

## 2.2. Ecosistema de Canales de Usuario

La arquitectura del sistema desacopla los adaptadores de entrada de la lógica de negocio, permitiendo que cuatro canales de mensajería distintos interactúen con el mismo núcleo conversacional:

```
                                  CLIENTES EN MAZATLÁN
                ┌───────────────┬──────────────────┬─────────────────┐
                │               │                  │                 │
                ▼               ▼                  ▼                 ▼
         ┌────────────┐  ┌──────────────┐  ┌───────────────┐  ┌─────────────┐
         │  Telegram  │  │   WhatsApp   │  │   Facebook    │  │  Instagram  │
         │  User Bot  │  │  Cloud API   │  │   Messenger   │  │   Direct    │
         └─────┬──────┘  └──────┬───────┘  └───────┬───────┘  └──────┬──────┘
               │                │                  │                 │
               │ HTTPXRequest   │ Webhook POST     │ Webhook POST    │ Webhook POST
               │ Long Polling   │ Graph API v21.0  │ Send API (HMAC) │ IG Graph API
               ▼                ▼                  ▼                 ▼
         ┌────────────┐  ┌──────────────┐  ┌───────────────┐  ┌─────────────┐
         │telegram_bot│  │  whatsapp/   │  │  messenger/   │  │ instagram/  │
         │    .py     │  │  router.py   │  │   router.py   │  │  router.py  │
         └─────┬──────┘  └──────┬───────┘  └───────┬───────┘  └──────┬──────┘
               │                │                  │                 │
               └────────────────┼──────────────────┴─────────────────┘
                                │
                                ▼
         ┌──────────────────────────────────────────────────────────┐
         │           MOTOR CONVERSACIONAL CENTRAL (flow_router.py)  │
         │   • Máquina de Estados (FlowState)                       │
         │   • Carrito Temporal de Compra (wa_carts, msgr_carts...) │
         │   • Orquestador LangGraph AI (sales_graph.py)            │
         │   • Fallback LLM Inteligente (DeepSeek v3 / OpenRouter)  │
         └──────────────────────┬───────────────────────────────────┘
                                │
        ┌───────────────────────┼────────────────────────┐
        ▼                       ▼                        ▼
┌──────────────────┐  ┌───────────────────┐  ┌───────────────────────┐
│  IdentityStore   │  │ Serv. Auxiliares  │  │ Persistencia / Datos  │
│ • Cross-Channel  │  │ • Whisper Audio   │  │ • PostgreSQL Petroil  │
│ • Mapeo Teléfono │  │ • Geocoding Nomin.│  │ • SQLite Local Dev    │
│ • Libreta Addr.  │  │ • ScheduleManager │  │ • Catálogo de Precios │
└──────────────────┘  └───────────────────┘  └───────────────────────┘
```

---

## 2.3. Matriz Comparativa Detallada de Canales

| Criterio | Telegram (`telegram_bot.py`) | WhatsApp (`src/channels/whatsapp/`) | Facebook Messenger (`src/channels/messenger/`) | Instagram Direct (`src/channels/instagram/`) |
| :--- | :--- | :--- | :--- | :--- |
| **Tecnología Base** | `python-telegram-bot` v20+ async | Meta WhatsApp Cloud API (Graph v21.0) | Meta Messenger Platform (Send API) | Meta Instagram Graph API |
| **Identificador de Usuario** | `chat_id` (numérico entero) | `wa_id` (teléfono internacional, ej. `521669...`) | `psid` (Page-Scoped ID, alfanumérico) | `igsid` (Instagram-Scoped ID, alfanumérico) |
| **Método de Recepción** | Long Polling asíncrono con HTTPX | Webhook HTTP POST en `/channels/whatsapp/webhook` | Webhook HTTP POST en `/channels/messenger/webhook` | Webhook HTTP POST en `/channels/instagram/webhook` |
| **Seguridad de Entrada** | Token del bot provisto por BotFather | `hub.verify_token` en GET handshake | Firma HMAC-SHA256 (`X-Hub-Signature-256`) | Firma HMAC-SHA256 (`X-Hub-Signature-256`) |
| **Interfaz: Botones** | `InlineKeyboardMarkup` ilimitado (filas/cols) | `Interactive Buttons` (máximo 3 botones) | `Quick Replies` y `Button Templates` (hasta 3) | `Quick Replies` deslizables (hasta 13 botones) |
| **Interfaz: Menú Catálogo** | Botones Inline en cuadrícula 2x2 | `Interactive List` (1 sección, hasta 10 filas) | `Generic Template` (Carrusel con imágenes) | `Generic Template` (Carrusel de tarjetas) |
| **Compartir Teléfono** | Botón `KeyboardButton(request_contact=True)` | Texto libre o mensaje de contacto VCard | Texto libre (validado regex 10 dígitos) | Texto libre (validado regex 10 dígitos) |
| **Compartir Ubicación** | Botón `KeyboardButton(request_location=True)` | Mensaje nativo de tipo `location` de WhatsApp | Botón Quick Reply de tipo `location` | Enlace / Texto geocodificado con Nominatim |
| **Notas de Voz** | Audio OGG Opus descargado por Telegram API | Audio OGG Opus descargado vía Graph API Media | Audio MP4/M4A descargado desde URL CDN | Audio M4A/AAC descargado desde URL CDN |
| **Transcripción Audio** | Whisper AI (`audio_transcription.py`) | Whisper AI (`audio_transcription.py`) | Whisper AI (`audio_transcription.py`) | Whisper AI (`audio_transcription.py`) |
| **Ventana de Atención** | Sin ventana (siempre disponible) | Ventana estándar de 24 horas de Meta | Ventana de mensajería estándar de Meta | Ventana de mensajería estándar de Meta |
| **Resumen Financiero** | Mensaje de texto formateado Markdown | Mensaje de texto con formato negrita `*...*` | Mensaje estructurado con Quick Replies | Mensaje estructurado con Quick Replies |
| **Encuesta CSAT** | Botones Inline con estrellas (1 a 5 ⭐) | Botones interactivos (1 a 3/5 ⭐) o lista | Quick Replies con estrellas (1 a 5 ⭐) | Quick Replies con estrellas (1 a 5 ⭐) |

---

## 2.4. Modelo Unificado de Identidad de Usuario (`IdentityStore`)

Uno de los mayores retos de una arquitectura omnicanal es evitar la fragmentación de la información: si un cliente solicita gas hoy por WhatsApp y mañana consulta el estatus de entrega por Instagram, el sistema debe reconocer que se trata de la misma persona y del mismo domicilio.

### La Llave Canónica de Negocio: Teléfono a 10 Dígitos
El número celular a 10 dígitos (formato estándar mexicano sin prefijos internacionales ni guiones, ej. `6691234567`) actúa como el **Ancla de Identidad Universal (Unique Identity Anchor)** en la base de datos de Grupo Petroil.

### Mapeo Persistente entre Procesos (`src/repositories/identity_store.py`)
Dado que los bots corren en procesos concurrentes (ej. `telegram_bot.py` como demonio independiente y `uvicorn` levantando la API de FastAPI con los routers de WhatsApp, Messenger e Instagram), el almacenamiento de identidades se sincroniza en disco en tiempo real:

1. **`channel_identity_cache.json`:** Archivo JSON transaccional con escritura atómica (`.tmp -> replace`) que mantiene:
   * `phone_to_tg`: Mapea teléfonos de 10 dígitos al `chat_id` de Telegram.
   * `tg_to_phone`: Mapea `chat_id` al teléfono a 10 dígitos.
   * `order_channels`: Registra para cada folio de orden (`order_id`):
     ```json
     {
       "channel": "whatsapp",
       "channel_user_id": "5216699876543",
       "phone": "6699876543"
     }
     ```
   * `_deleted_addresses`: Lista negra de direcciones eliminadas expresamente por el cliente para no volver a sugerirlas.
   * `order_ratings`: Registro persistente de calificaciones CSAT emitidas desde los bots.
   * `order_client_messages`: Mensajes adicionales enviados por el cliente hacia el repartidor.

---

## 2.5. Entidades Principales del Dominio de Clientes

### 2.5.1. `Customer` (Cliente)
Representa al comprador final en la base de datos relacional de Petroil:
* `id` (int): Identificador interno.
* `tenant_id` (str): `"petroil"`.
* `name` (str): Nombre completo del cliente o titular del servicio.
* `phone` (str): Teléfono normalizado a 10 dígitos.
* `channel` (str): Canal por el que se registró originalmente (`"telegram"`, `"whatsapp"`, `"messenger"`, `"instagram"`).
* `channel_user_id` (str): Identificador específico del canal (`chat_id`, `wa_id`, `psid`, `igsid`).
* `address` (str): Dirección principal por defecto.
* `addresses` (list[CustomerAddress]): Libreta con todas las direcciones guardadas del cliente.

### 2.5.2. `CustomerAddress` (Dirección del Cliente)
Permite gestionar múltiples domicilios (ej. "Casa", "Restaurante", "Casa de mi mamá"):
* `id` (int): Identificador de la dirección.
* `address` (str): Texto formal de la calle, número, colonia y referencias.
* `alias` (str): Etiqueta corta (ej. "Principal", "Sucursal Centro", "Mi Casa").
* `latitude` / `longitude` (float | None): Coordenadas GPS satelitales.

### 2.5.3. `DraftOrder` (Borrador de Pedido en Vuelo)
Objeto en memoria (`dataclass`) que acumula los datos recolectados durante la conversación antes de crear el registro formal en la base de datos:
* `service_type` (str): `"cilindro"` o `"estacionario"`.
* `items` (list[dict]): Lista de productos, cantidades y precios unitarios.
* `customer_phone` (str): Teléfono capturado o heredado.
* `customer_name` (str): Nombre del titular.
* `delivery_address` (str): Dirección seleccionada o geocodificada.
* `delivery_lat` / `delivery_lng` (float): Coordenadas geográficas obligatorias para el despacho.
* `notes` (str): Referencias adicionales de entrega (ej. "portón negro frente al parque").
* `delivery_schedule` (str): `"Lo antes posible"` o texto de fecha/hora programada.
* `scheduled_for` (str | None): Timestamp normalizado ISO-8601 si es un pedido programado.
* `payment_method` (str): `"Efectivo"`, `"Tarjeta"` o `"Transferencia"`.

---

## 2.6. Servicios y Módulos Compartidos

Todos los bots consumen los mismos servicios centrales de la capa `src/services/`:

1. **`flow_router.py` (Enrutador Conversacional Determinista):**
   * Controla la máquina de estados de 10 pasos (`FlowState.INITIAL`, `WAITING_FOR_PRODUCT_OR_QUANTITY`, `WAITING_FOR_PHONE`, `WAITING_FOR_ADDRESS_SELECTION`, `WAITING_FOR_SCHEDULE`, `WAITING_FOR_PAYMENT_METHOD`, `WAITING_FOR_CONFIRMATION`, etc.).
   * Aplica la regla arquitectónica de **Cero Llamadas a LLM** cuando el usuario interactúa con botones, callbacks o textos coincidentes con expresiones regulares, reservando la inferencia de lenguaje natural únicamente para resolver ambigüedades.
2. **`audio_transcription.py` (Transcripción de Voz Whisper):**
   * Descarga el archivo de audio temporal desde los servidores de Telegram o Meta.
   * Procesa el stream de audio con OpenAI Whisper / Faster-Whisper para extraer el texto en español con alta fidelidad.
   * Inyecta el texto transcrito de vuelta en el flujo como si el usuario lo hubiera tecleado.
3. **`geocoding.py` (Geocodificación Satelital y Reversa):**
   * Consume la API de OpenStreetMap Nominatim con filtrado estricto para Mazatlán, Sinaloa (`countrycodes=mx`, `viewbox=-106.50,23.15,-106.30,23.35`).
   * Convierte coordenadas GPS nativas compartidas en chat a nombres legibles de calle y colonia (`resolve_gps_address_to_name`).
4. **`schedule_manager.py` (Gestor de Horarios y Disponibilidad):**
   * Valida si el horario comercial de atención de Petroil está abierto al momento de la interacción.
   * Si está cerrado, propone automáticamente opciones de entrega para el siguiente turno disponible (ej. "Mañana a las 8:00 AM").
5. **`notifications.py` (Servicio Multi-Bot de Notificaciones a Clientes):**
   * Despacha mensajes proactivos al canal exacto por el que ordenó el usuario cuando la orden cambia de estatus (`assigned`, `in_route`, `delivered`).
   * Despliega la tarjeta interactiva de calificación CSAT (1 a 5 ⭐) una vez confirmado el cobro.

---

## 2.7. Ciclo de Vida del Pedido desde la Perspectiva del Usuario

```
[ PASO 1: CONTACTO INICIAL ]
  Cliente saluda o envía nota de voz en Telegram / WhatsApp / Messenger / Instagram
       │
       ▼
[ PASO 2: TIPO DE SERVICIO ]
  Bot despliega botones: [ 🛢️ Cilindros ] ó [ 🔥 Tanque Estacionario ]
       │
       ▼
[ PASO 3: CATÁLOGO Y CANTIDADES ]
  Selección de capacidad (10, 20, 30, 45 kg) con precio real vigente en pesos.
  Gestión de carrito multi-producto (+ / - unidades).
       │
       ▼
[ PASO 4: TELÉFONO DE CONTACTO ]
  Si el canal provee el número (WhatsApp) se toma automáticamente.
  En Telegram se ofrece botón de compartir contacto. En otros canales se pide a 10 dígitos.
       │
       ▼
[ PASO 5: DIRECCIÓN DE ENTREGA ]
  Si es cliente existente: Muestra botones con sus direcciones guardadas ("Casa", "Trabajo").
  Si es cliente nuevo o desea otra: Permite enviar GPS nativo en 1 clic o escribir dirección con referencias.
       │
       ▼
[ PASO 6: HORARIO DE ENTREGA ]
  Validación de horario de servicio.
  Opciones: "Lo antes posible" (inmediato) ó "Programar fecha y hora".
       │
       ▼
[ PASO 7: MÉTODO DE PAGO ]
  Opciones: [ 💵 Efectivo ] | [ 💳 Tarjeta (Terminal) ] | [ 📱 Transferencia SPEI ]
       │
       ▼
[ PASO 8: RESUMEN Y CONFIRMACIÓN OBLIGATORIA ]
  Bot presenta desglose completo (Productos, Total en MXN, Dirección, Horario, Pago).
  Botón obligatorio: [ ✅ Confirmar Pedido ] | [ ✏️ Modificar ] | [ ❌ Cancelar ]
       │
       ▼
[ PASO 9: SEGUIMIENTO EN TIEMPO REAL ]
  Bot entrega Folio #XXXXX.
  Notificación cuando el chofer es asignado con placas y modelo del vehículo.
  Notificación cuando el chofer va en camino con enlace al mapa de rastreo.
       │
       ▼
[ PASO 10: ENTREGA Y EVALUACIÓN CSAT ]
  Chofer confirma cobro y entrega.
  Bot envía encuesta en el chat: "¿Cómo calificarías el servicio de hoy? (⭐ 1 al 5)".
```

---

# PARTE 3: PRODUCT REQUIREMENTS DOCUMENT (PRD)

---

## 3.1. Control de Versiones del PRD

| Versión | Fecha | Autor | Descripción del Cambio | Estado |
| :--- | :--- | :--- | :--- | :--- |
| **1.0.0** | 10/08/2026 | Equipo de Producto Petroil | Especificación preliminar de bot de ventas conversacional. | Superado |
| **2.0.0** | 22/08/2026 | Arquitectura & AI Team | Incorporación de flujos para WhatsApp Cloud API y Telegram. | Superado |
| **3.0.0** | 15/09/2026 | Antigravity AI | Integración de Facebook Messenger e Instagram Direct vía Meta Graph API. | Superado |
| **3.5.0** | 02/10/2026 | Antigravity AI & Equipo Petroil | **Consolidación Integral de los 4 Canales de Usuario:**<br>• Especificación exhaustiva de Telegram, WhatsApp, Messenger e Instagram.<br>• Carrito multi-producto interactivo y sumatoria de totales en tiempo real.<br>• Transcripción de audios mediante OpenAI Whisper across-channels.<br>• Geocodificación GPS satelital con Nominatim y resolución de direcciones.<br>• Manejo de ventanas de atención y reprogramación inteligente.<br>• Idempotencia con TTL de 10 minutos y validación criptográfica HMAC-SHA256.<br>• Encuestas CSAT de 1 a 5 estrellas con persistencia multi-proceso en `IdentityStore`. | **Aprobado / Vigente** |

---

## 3.2. Máquina de Estados Conversacional (`FlowState`)

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                      MÁQUINA DE ESTADOS CONVERSACIONAL (FlowState)                     │
├───────────────────────────────┬────────────────────────────────────────────────────────┤
│ ESTADO (FlowState)            │ ACCIÓN / RESPUESTA DEL BOT                             │
├───────────────────────────────┼────────────────────────────────────────────────────────┤
│ INITIAL                       │ Saludo de bienvenida institucional y tipo de servicio  │
│ WAITING_FOR_PRODUCT_OR_QTY    │ Despliegue de catálogo y selector de cantidades (+/-)  │
│ WAITING_FOR_STATIONARY_DETAILS│ Captura de importe en pesos ($) o litros de gas estac. │
│ WAITING_FOR_PHONE             │ Solicitud y validación de teléfono celular a 10 dígitos│
│ WAITING_FOR_ADDRESS_SELECTION │ Botones de direcciones guardadas o solicitud de nueva  │
│ WAITING_FOR_NEW_CUSTOMER_NAME │ Captura de nombre del titular si es usuario nuevo      │
│ WAITING_FOR_NEW_CUSTOMER_ADDR │ Captura de calle, número y referencias o GPS nativo    │
│ WAITING_FOR_SCHEDULE          │ Selección de "Lo antes posible" o fecha programada     │
│ WAITING_FOR_PAYMENT_METHOD    │ Opciones: Efectivo, Tarjeta (Terminal) o Transferencia │
│ WAITING_FOR_CONFIRMATION      │ Tarjeta resumen financiero y botón Confirmar / Cancelar│
│ COMPLETED                     │ Pedido generado con Folio #XXXXX y seguimiento activo  │
└───────────────────────────────┴────────────────────────────────────────────────────────┘
```

---

## 3.3. Requerimientos Funcionales Generales (Cross-Channel)

### RF-01: Detección y Bienvenida al Usuario
* **Descripción:** Al recibir cualquier saludo o interacción inicial (`/start`, "hola", "buenas tardes", audio de saludo o emoji), el bot debe identificar al usuario en `IdentityStore` y responder con el saludo oficial de Grupo Petroil.
* **Criterios:**
  - Si el usuario ya cuenta con pedidos previos registrados, el bot debe saludarlo cordialmente por su nombre (ej. *"¡Hola de nuevo, Sra. María! Bienvenido a Gas a tu Puerta de Grupo Petroil"*).
  - Desplegar inmediatamente la selección de tipo de servicio sin textos ambiguos.

### RF-02: Selección de Tipo de Servicio
* **Descripción:** El bot debe presentar de manera visible y excluyente las dos modalidades de suministro de gas disponibles en Petroil.
* **Criterios:**
  - Opción 1: `[ 🛢️ Cilindros ]` (Gas LP en cilindro portátil).
  - Opción 2: `[ 🔥 Tanque Estacionario ]` (Recarga por litro con pipa).
  - La interacción debe ejecutarse mediante botones nativos de la plataforma correspondiente.

### RF-03: Catálogo Dinámico y Carrito Multi-Producto
* **Descripción:** Los precios y productos deben ser leídos en tiempo real desde la base de datos relacional de Petroil, garantizando cero discrepancias tarifarias.
* **Criterios:**
  - Para Cilindros: Mostrar capacidades estándar (10 kg, 20 kg, 30 kg, 45 kg) con su precio oficial vigente en moneda nacional (MXN).
  - Carrito Interactivo: Permitir agregar más de un cilindro (ej. 2 de 30 kg + 1 de 20 kg) mediante botones de incremento (`+`), decremento (`-`) y vaciado de carrito.
  - Para Tanque Estacionario: Permitir indicar importe en pesos (ej. "$800 pesos") o cantidad de litros, con un consumo mínimo configurable (ej. mínimo $500 MXN).

### RF-04: Captura y Validación de Teléfono a 10 Dígitos
* **Descripción:** El número telefónico es la llave canónica del cliente.
* **Criterios:**
  - En WhatsApp: Se toma automáticamente del identificador `wa_id` (removiendo el prefijo de país `52` o `521`).
  - En Telegram: Se ofrece el botón nativo de compartir contacto (`request_contact=True`) o escritura manual.
  - En Messenger e Instagram: Se solicita escribirlo a 10 dígitos.
  - Validación: Expresión regular estricta `^[0-9]{10}$`. Si el usuario ingresa caracteres no numéricos o longitudes distintas a 10 dígitos, el bot debe emitir un mensaje de corrección guiado.

### RF-05: Gestión Inteligente de Direcciones
* **Descripción:** El sistema debe minimizar la fricción de entrada de direcciones y garantizar geocodificación satelital precisa.
* **Criterios:**
  - **Clientes Recurrentes:** Desplegar botones con las direcciones registradas previamente (ej. `[ 📍 Casa: Av. Delfín #402 ]`, `[ 📍 Local: Av. Ejército Mexicano #12 ]`) más una opción `[ ➕ Nueva Dirección ]`.
  - **Clientes Nuevos o Domicilio Nuevo:** Permitir compartir la **ubicación GPS en tiempo real** nativa de la app (Telegram, WhatsApp o Messenger) o escribir la dirección en texto plano con calle, número exterior, colonia y entrecalles.
  - **Geocodificación Satelital:** Procesar la dirección con Nominatim OpenStreetMap acotado a Mazatlán. Si la geocodificación devuelve coordenadas válidas, asociarlas al pedido.
  - **Borrado de Direcciones:** Si el usuario solicita olvidar o borrar un domicilio, el sistema lo añade a `_deleted_addresses` en `IdentityStore` para no volver a sugerirlo.

### RF-06: Verificación de Horarios de Atención y Programación
* **Descripción:** El sistema debe respetar las ventanas de operación comercial de Petroil Mazatlán.
* **Criterios:**
  - El servicio `schedule_manager.py` evalúa la hora local actual de Mazatlán (Zona Horaria `America/Mazatlan`).
  - Si la compra ocurre dentro del horario de despacho: Presentar opciones `[ ⚡ Lo antes posible ]` (entrega inmediata promedio 30-45 min) y `[ 📅 Programar Entrega ]`.
  - Si ocurre fuera de horario: El bot debe informar cortésmente el horario de apertura (ej. 7:00 AM) y ofrecer agendar el pedido para el primer turno de la mañana siguiente.

### RF-07: Selección de Métodos de Pago
* **Descripción:** El cliente debe definir cómo liquidará su pedido al momento de la entrega física.
* **Criterios:**
  - Opciones obligatorias:
    1. `[ 💵 Efectivo ]`: Preguntar si requiere cambio de alguna denominación (ej. "¿Pagas con billete de $500 o $1,000?").
    2. `[ 💳 Tarjeta (Terminal) ]`: Informa que el repartidor llevará terminal bancaria móvil para cobro con tarjeta de débito/crédito.
    3. `[ 📱 Transferencia SPEI ]`: Proporciona la CLABE interbancaria institucional de Petroil indicando que el comprobante se muestra al chofer.

### RF-08: Resumen Financiero Estructurado y Confirmación Obligatoria
* **Descripción:** Ningún pedido debe registrarse en la base de datos sin una confirmación explícita y afirmativa del cliente.
* **Criterios:**
  - El bot debe presentar una tarjeta resumen con productos, importe en MXN, domicilio, horario y método de pago.
  - Botones de acción final: `[ ✅ Confirmar Pedido ]`, `[ ✏️ Modificar ]`, `[ ❌ Cancelar ]`.

### RF-09: Notificaciones de Estado en Tiempo Real (Push por Canal)
* **Descripción:** El cliente debe recibir actualizaciones automáticas en el mismo hilo de chat donde realizó la compra.
* **Criterios:**
  - Evento 1: **Pedido Asignado:** Chofer y placas.
  - Evento 2: **Chofer en Camino (`in_route`):** Aviso de proximidad.
  - Evento 3: **Pedido Entregado (`delivered`):** Finalización e importe cobrado.

### RF-10: Encuesta de Calidad CSAT Post-Entrega
* **Descripción:** Medición sistemática de la satisfacción del cliente tras la entrega física en escala de 1 a 5 estrellas:
  `[ ⭐ ]  [ ⭐⭐ ]  [ ⭐⭐⭐ ]  [ ⭐⭐⭐⭐ ]  [ ⭐⭐⭐⭐⭐ ]`.
  Almacenado en `order_ratings` e `IdentityStore`.

### RF-11: Transcripción Automática de Notas de Voz (Whisper)
* **Descripción:** Los usuarios pueden enviar notas de voz en lugar de texto en cualquier etapa del flujo. Procesado mediante `audio_transcription.py`.

### RF-12: Consulta de Estatus y Cancelación Asistida
* **Descripción:** Consulta inmediata de pedidos activos con *"¿dónde viene mi gas?"*. Cancelación asistida permitida en estados `pending` y `assigned`.

---

## 3.4. Especificaciones Técnicas Particulares por Canal

### 3.4.1. Bot de Usuario en Telegram (`telegram_bot.py`)
* Librería: `python-telegram-bot` v20.7+ asíncrona sobre `HTTPXRequest`.
* Manejo de Callback Queries estructurados: `srv_*`, `prod_*`, `addr_*`, `pay_*`, `rate_*`.
* Reemplazo en caliente de teclados mediante `edit_message_reply_markup`.

### 3.4.2. Bot de Usuario en WhatsApp Cloud API (`src/channels/whatsapp/`)
* Meta Graph API v21.0 vía endpoints HTTPS en FastAPI (`/channels/whatsapp/webhook`).
* Mensajes interactivos de tipo `list` (catálogo y direcciones) y de tipo `button` (máximo 3 botones).
* Carrito en memoria `wa_carts` (`wa_id -> {prod_id: qty}`).
* Recuperación automática ante error HTTP 401 con refresco de credenciales dinámicas.

### 3.4.3. Bot de Usuario en Facebook Messenger (`src/channels/messenger/`)
* Meta Send API v21.0 con validación criptográfica `X-Hub-Signature-256` mediante `MESSENGER_APP_SECRET`.
* Caché de deduplicación de mensajes `_PROCESSED_MSG_IDS` con TTL de 600 segundos (10 minutos).
* Carruseles `Generic Template` con imágenes de producto y botones de postback.

### 3.4.4. Bot de Usuario en Instagram Direct (`src/channels/instagram/`)
* Instagram Messaging API con validación HMAC-SHA256 con `INSTAGRAM_APP_SECRET`.
* Quick Replies deslizables horizontalmente de hasta 13 opciones.
* Descarga de notas de voz en formato M4A/AAC y transcripción vía Whisper.

---

## 3.5. Requerimientos No Funcionales

* **RNF-01: Rendimiento y Latencia:** $\le 1.2$ s en botones deterministas; $\le 3.0$ s en inferencia LLM fallback; $\le 4.0$ s en Whisper.
* **RNF-02: Disponibilidad y Resiliencia:** Uptime $\ge 99.9\%$, desacoplamiento total frente a mantenimientos de choferes o Torre de Control.
* **RNF-03: Seguridad y Privacidad:** Comunicaciones 100% cifradas TLS 1.3 / HTTPS; no almacenamiento de datos bancarios; sanitización de teléfonos en logs.
* **RNF-04: Idempotencia en Webhooks:** Respuesta HTTP 200 OK en $< 2.0$ segundos delegando trabajo a `BackgroundTasks`.

---

## 3.6. Matriz de Trazabilidad Requerimientos vs Código

| ID Requerimiento | Descripción Sintética | Archivos de Código Responsables |
| :--- | :--- | :--- |
| **RF-01 / RF-02** | Bienvenida y Selección de Tipo de Servicio | `telegram_bot.py`, `src/services/flow_router.py`, `src/channels/*/router.py` |
| **RF-03** | Catálogo Dinámico y Carritos Multi-Producto | `src/services/flow_router.py`, `src/repositories/sqlite_repo.py`, `wa_carts`, `msgr_carts`, `ig_carts` |
| **RF-04** | Captura y Validación de Teléfono | `src/services/flow_router.py`, `src/repositories/identity_store.py` |
| **RF-05** | Gestión de Direcciones y Geocodificación | `src/services/geocoding.py`, `src/repositories/identity_store.py`, `nominatim` |
| **RF-06** | Horarios de Atención y Programación | `src/services/schedule_manager.py`, `src/services/flow_router.py` |
| **RF-07** | Selección de Método de Pago | `src/services/flow_router.py`, `src/channels/*/adapter.py` |
| **RF-08** | Resumen y Confirmación Obligatoria | `src/services/flow_router.py`, `src/tools/create_order.py` |
| **RF-09** | Notificaciones Push de Estatus al Cliente | `src/services/notifications.py`, `src/repositories/identity_store.py` |
| **RF-10** | Encuesta CSAT de 1 a 5 Estrellas | `src/repositories/identity_store.py`, `src/services/notifications.py` |
| **RF-11** | Transcripción de Voz Whisper | `src/services/audio_transcription.py`, `src/channels/*/router.py` |
| **RF-12** | Consulta de Estatus y Cancelación | `src/tools/get_order_status.py`, `src/tools/cancel_order.py` |
| **RNF-03 / 04** | Seguridad HMAC y Deduplicación | `src/channels/messenger/router.py`, `src/channels/instagram/router.py` |

---

# PARTE 4: ARCHITECTURE DESIGN DOCUMENT (ADD)

---

## 4.1. Principios Arquitectónicos

1. **Determinismo Primero (Zero-LLM Rule):** Las opciones estructuradas (botones, callbacks, listas) no realizan llamadas a LLM, garantizando latencias mínimas y cero alucinaciones. El LLM se reserva para mensajes ambiguos de texto libre.
2. **Arquitectura Hexagonal (Puertos y Adaptadores):** La lógica de negocio (`flow_router.py`) está desacoplada de los adaptadores de red (`telegram_bot.py`, `whatsapp/`, `messenger/`, `instagram/`).
3. **Ancla de Identidad Universal (`IdentityStore`):** Mapeo persistente y sincronizado en disco (`channel_identity_cache.json`) entre el número celular a 10 dígitos y los IDs de red social (`chat_id`, `wa_id`, `psid`, `igsid`).
4. **Idempotencia y No Bloqueo:** Respuesta inmediata HTTP 200 a los webhooks de Meta con deduplicación por `mid` y procesamiento asíncrono en segundo plano (`BackgroundTasks`).

---

## 4.2. Modelado C4 del Subsistema de Bots de Usuario

### C4 — Nivel 1: Contexto de Sistema
```mermaid
graph TD
    Client_TG[Cliente en Telegram] -->|Chat, Botones Inline, Contacto, GPS, Audio| TG_Platform[Servidores de Telegram Bot API]
    Client_WA[Cliente en WhatsApp] -->|Chat, Listas, Botones, GPS, Audio OGG| Meta_WA[Meta WhatsApp Cloud API]
    Client_FB[Cliente en Facebook Messenger] -->|Chat, Carruseles, Quick Replies, Audio| Meta_FB[Meta Messenger Platform]
    Client_IG[Cliente en Instagram Direct] -->|Chat, Quick Replies, Fichas, Audio| Meta_IG[Meta Instagram Graph API]

    TG_Platform -->|HTTP Long Polling / Updates| Bot_Subsystem[Subsistema Bots de Usuario Petroil]
    Meta_WA -->|Webhook HTTP POST JSON| Bot_Subsystem
    Meta_FB -->|Webhook HTTP POST HMAC-SHA256| Bot_Subsystem
    Meta_IG -->|Webhook HTTP POST HMAC-SHA256| Bot_Subsystem

    Bot_Subsystem -->|Inferencia Semántica Fallback| OpenRouter[OpenRouter API / DeepSeek v3]
    Bot_Subsystem -->|Transcripción de Audio| Whisper[OpenAI Whisper Engine]
    Bot_Subsystem -->|Geocodificación Satelital| Nominatim[OpenStreetMap Nominatim]
    Bot_Subsystem -->|Persistencia y Catálogo| Database[(PostgreSQL Petroil / SQLite)]
    Bot_Subsystem -->|Notificaciones a Choferes| DispatchSys[Motor de Despacho Logístico]
```

### C4 — Nivel 2: Contenedores
```mermaid
graph TB
    subgraph "Canales Externos de Mensajería"
        TG_API[Telegram Bot API]
        WA_API[Meta WhatsApp Cloud API]
        MSGR_API[Meta Messenger Send API]
        IG_API[Meta Instagram Graph API]
    end

    subgraph "Infraestructura del Servidor Petroil"
        subgraph "Proceso 1: Servidor Webhook FastAPI (src/app.py)"
            WA_Router["WhatsApp Router\n(src/channels/whatsapp/)"]
            MSGR_Router["Messenger Router\n(src/channels/messenger/)"]
            IG_Router["Instagram Router\n(src/channels/instagram/)"]
            Background_Workers["FastAPI BackgroundTasks\n(Procesamiento Asíncrono)"]
        end

        subgraph "Proceso 2: Demonio de Telegram (telegram_bot.py)"
            TG_Handler["Telegram Client App\n(python-telegram-bot v20+)"]
            TG_Poller["HTTPX Polling Engine"]
        end

        subgraph "Capa de Lógica Conversacional Compartida"
            Flow_Router["Motor de Flujo (flow_router.py)\nState Machine / DraftOrder"]
            LangGraph_Agent["Agente LangGraph (sales_graph.py)\nOrquestador de Diálogos"]
        end

        subgraph "Capa de Servicios y Utilidades"
            Audio_Svc["Audio Transcription (Whisper)\naudio_transcription.py"]
            Geo_Svc["Geocoding Service (Nominatim)\ngeocoding.py"]
            Sched_Svc["Schedule Manager\nschedule_manager.py"]
            Notif_Svc["Multi-Channel Notifications\nnotifications.py"]
            Id_Store["IdentityStore\nchannel_identity_cache.json"]
        end

        subgraph "Persistencia"
            DB[(PostgreSQL Corporativo / SQLite)]
        end
    end

    TG_API <-->|Long Polling HTTPX| TG_Poller
    TG_Poller --> TG_Handler
    WA_API -->|POST /channels/whatsapp/webhook| WA_Router
    MSGR_API -->|POST /channels/messenger/webhook| MSGR_Router
    IG_API -->|POST /channels/instagram/webhook| IG_Router

    WA_Router --> Background_Workers
    MSGR_Router --> Background_Workers
    IG_Router --> Background_Workers

    TG_Handler --> Flow_Router
    Background_Workers --> Flow_Router

    Flow_Router <--> LangGraph_Agent
    Flow_Router --> Audio_Svc
    Flow_Router --> Geo_Svc
    Flow_Router --> Sched_Svc
    Flow_Router <--> Id_Store
    Flow_Router <--> DB

    Notif_Svc --> TG_Handler
    Notif_Svc --> WA_Router
    Notif_Svc --> MSGR_Router
    Notif_Svc --> IG_Router
```

---

## 4.3. Contratos de Datos y Modelos Internos

```python
# src/models/message.py
@dataclass
class InboundMessage:
    channel: Literal["telegram", "whatsapp", "messenger", "instagram", "web"]
    channel_user_id: str          # chat_id, wa_id, psid o igsid
    text: str = ""
    message_type: str = "text"    # "text", "location", "contact", "audio", "interactive"
    location_lat: float | None = None
    location_lng: float | None = None
    phone: str | None = None
    audio_url: str | None = None
    payload: str | None = None
    raw_event: dict[str, Any] = field(default_factory=dict)

@dataclass
class OutboundMessage:
    recipient_id: str
    text: str
    channel: str
    message_type: str = "text"
    buttons: list[dict[str, str]] = field(default_factory=list)
    list_items: list[dict[str, Any]] = field(default_factory=list)
```

---

## 4.4. Diagramas de Secuencia Detallados

### 4.4.1. Secuencia de Webhook Entrante (Meta)
```mermaid
sequenceDiagram
    autonumber
    actor Usuario
    participant Meta as Servidores Meta (Graph API)
    participant Router as Router FastAPI (/channels/*)
    participant Security as Validador HMAC / Dedup
    participant Flow as flow_router.py
    participant DB as PostgreSQL / SQLite
    participant Adapter as Channel Adapter

    Usuario->>Meta: Envía mensaje / Toca botón interactivo
    Meta->>Router: POST /channels/{channel}/webhook (JSON payload)
    Router->>Security: Validar firma X-Hub-Signature-256 (Messenger/IG)
    Security-->>Router: Firma Válida (OK)
    Router->>Security: Verificar Message ID (mid) en caché de deduplicación
    Security-->>Router: Mensaje no procesado previamente
    Router-->>Meta: HTTP 200 OK (Inmediato < 500 ms)

    Note over Router,Flow: Proceso delegado a BackgroundTasks
    Router->>Flow: process_step(session_id, input_data)
    Flow->>DB: Consultar catálogo de precios / libreta de direcciones
    DB-->>Flow: Retorna datos reales
    Flow->>Adapter: Generar respuesta interactiva (OutboundMessage)
    Adapter->>Meta: POST https://graph.facebook.com/.../messages
    Meta->>Usuario: Despliega mensaje interactivo / botones
```

### 4.4.2. Secuencia de Transcripción Whisper
```mermaid
sequenceDiagram
    autonumber
    actor Usuario
    participant Bot as Bot de Usuario (Telegram / WhatsApp / Meta)
    participant Storage as Servidor de Archivos (Telegram / Meta CDN)
    participant Whisper as audio_transcription.py
    participant Flow as flow_router.py

    Usuario->>Bot: Envía nota de voz ("Ocupo un cilindro de 30 a Pradera")
    Bot->>Storage: Descargar stream de audio (OGG / M4A / MP4)
    Storage-->>Bot: Archivo binario temporal en disco
    Bot->>Whisper: transcribe_audio_file(temp_path)
    Whisper->>Whisper: Inferencia OpenAI Whisper (Spanish)
    Whisper-->>Bot: Texto transcrito: "Ocupo un cilindro de 30 a Pradera"
    Bot->>Flow: Enviar texto transcrito a la máquina de estados
    Flow->>Flow: Detecta producto ("Cilindro 30 kg") y colonia ("Pradera")
    Flow-->>Bot: Avanza estado y solicita confirmación de dirección
    Bot->>Usuario: "Detectamos que deseas 1 Cilindro de 30 kg..."
```

### 4.4.3. Secuencia de Calificación CSAT
```mermaid
sequenceDiagram
    autonumber
    actor Chofer as Chofer en Campo (driver_bot.py)
    participant Core as Núcleo de Despacho & Base de Datos
    participant Notif as notifications.py
    participant IdStore as IdentityStore
    participant ClientBot as Bot del Canal de Compra
    actor Cliente as Cliente Final

    Chofer->>Core: Finaliza viaje y confirma cobro en efectivo
    Core->>Core: Actualiza orden a estado "delivered"
    Core->>Notif: notify_customer_order_status(order_id, "delivered")
    Notif->>IdStore: get_order_channel_info(order_id)
    IdStore-->>Notif: {channel: "whatsapp", channel_user_id: "521669...", phone: "669..."}
    Notif->>ClientBot: Enviar mensaje de entrega + botones de calificación
    ClientBot->>Cliente: "✅ Tu gas ha sido entregado. ¿Cómo calificarías el servicio?" (1-5 ⭐)
    Cliente->>ClientBot: Presiona [ ⭐⭐⭐⭐⭐ ]
    ClientBot->>IdStore: save_order_rating(order_id, rating=5)
    IdStore->>Core: Persiste en tabla ORDER_RATINGS
    ClientBot->>Cliente: "¡Muchas gracias por elegir a Petroil Gas!"
```

---

## 4.5. Topología de Despliegue y Variables de Entorno (`.env`)

```ini
# --- TELEGRAM BOT DE USUARIOS ---
TELEGRAM_BOT_TOKEN="7890123456:AAH..."

# --- META WHATSAPP CLOUD API ---
WHATSAPP_TOKEN="EAAxxxx..."
WHATSAPP_PHONE_NUMBER_ID="109876543210987"
WHATSAPP_VERIFY_TOKEN="petroil_gas_wa_verify_2026"
WHATSAPP_API_VERSION="v21.0"

# --- META FACEBOOK MESSENGER ---
MESSENGER_PAGE_ACCESS_TOKEN="EAAyyyy..."
MESSENGER_VERIFY_TOKEN="petroil_msgr_secret_2026"
MESSENGER_APP_SECRET="a1b2c3d4e5f6..."

# --- META INSTAGRAM DIRECT ---
INSTAGRAM_PAGE_ACCESS_TOKEN="EAAzzzz..."
INSTAGRAM_VERIFY_TOKEN="petroil_ig_secret_2026"
INSTAGRAM_APP_SECRET="f6e5d4c3b2a1..."

# --- MODELOS DE LENGUAJE & AUDIO ---
OPENROUTER_API_KEY="sk-or-v1-..."
PRIMARY_MODEL="deepseek/deepseek-chat"
OPENAI_API_KEY="sk-..."                 # Para Whisper Audio Transcription

# --- PERSISTENCIA & GEOCODIFICACIÓN ---
DATABASE_URL="postgresql://petroil_app:segura2026@10.0.1.50:5432/petroil_gas"
NOMINATIM_BASE_URL="https://nominatim.openstreetmap.org/search"
```

---

# PARTE 5: USER FLOWS & NAVIGATION

---

## 5.1. Propósito y Modelo Canónico

$$\text{CLIENTE} \longrightarrow \text{ENTRADA (Texto / Botón / Audio / GPS)} \longrightarrow \text{ROUTER CANAL} \longrightarrow \text{FlowRouter} \longrightarrow \text{RESPUESTA}$$

---

## 5.2. Flujo Principal de Compra (Happy Path de 10 Pasos)

```mermaid
graph TD
    P1[1. Saludo / Bienvenida] -->|Toca Servicio| P2[2. Tipo de Servicio]
    P2 -->|Elige Cilindros o Estacionario| P3[3. Catálogo y Carrito]
    P3 -->|Confirma Selección de Productos| P4[4. Identificación Telefónica]
    P4 -->|Teléfono Validado a 10 Dígitos| P5[5. Selección de Domicilio]
    P5 -->|Dirección Guardada o Nueva GPS/Texto| P6{6. ¿Dentro de Horario?}
    P6 -->|Sí| P7[7. Selección de Horario: Inmediato / Programado]
    P6 -->|No| P7_Alt[7b. Horario Cerrado: Agendar Siguiente Turno]
    P7 --> P8[8. Método de Pago: Efectivo / Tarjeta / SPEI]
    P7_Alt --> P8
    P8 --> P9[9. Resumen Financiero y Confirmación Obligatoria]
    P9 -->|Toca Confirmar Pedido| P10[10. Pedido Creado #Folio y Despacho Activo]
    P10 --> Tracking[Notificaciones en Ruta y Encuesta CSAT 1-5 ⭐]
```

* **Paso 1: Saludo:** Reconoce si el cliente es recurrente o nuevo y saluda por su nombre.
* **Paso 2: Tipo de Servicio:** `[ 🛢️ Cilindros ]` vs `[ 🔥 Tanque Estacionario ]`.
* **Paso 3: Catálogo y Carrito:** Selector de capacidades con precios oficiales en pesos y suma de cantidades.
* **Paso 4: Teléfono:** Detección automática en WhatsApp, botón nativo en Telegram, o validación de 10 dígitos en Messenger/Instagram.
* **Paso 5: Domicilio:** Botones de direcciones guardadas, o envío de nueva dirección con botón de ubicación GPS nativa / texto con entrecalles.
* **Paso 6: Horario:** Evaluación en tiempo real de apertura de Petroil Mazatlán.
* **Paso 7: Método de Pago:** `[ 💵 Efectivo ]`, `[ 💳 Tarjeta (Terminal) ]`, `[ 📱 Transferencia SPEI ]`.
* **Paso 8: Resumen Financiero:** Tarjeta estructurada con productos, total en MXN, dirección, horario y pago, con botones `[ ✅ Confirmar ]`, `[ ✏️ Modificar ]`, `[ ❌ Cancelar ]`.
* **Paso 9: Pedido Creado:** Asignación de Folio #XXXXX y pase al motor de despacho.
* **Paso 10: Notificaciones y CSAT:** Avisos proactivos de asignado, en ruta y entregado, finalizando con la encuesta de 1 a 5 estrellas.

---

## 5.3. Flujos Alternativos y Excepciones

* **Flujo A: Pedido Fuera de Horario:** El bot informa el horario comercial y ofrece agendar el pedido para las 8:00 AM del día siguiente con activación automática en la mesa de agenda.
* **Flujo B: Edición de Carrito y Resumen:** Permite cambiar productos, domicilio o pago antes de confirmar sin reiniciar la conversación.
* **Flujo C: Dirección Ambigua:** El bot solicita entrecalles o el envío de ubicación satelital GPS en tiempo real.
* **Flujo D: Nota de Voz en Cualquier Momento:** Transcripción automática vía Whisper y extracción de intención para prellenar el borrador.
* **Flujo E: Consulta de Estatus:** Informa el estado del pedido activo y el chofer asignado sin iniciar una nueva compra.
* **Flujo F: Cancelación Asistida:** Cancela la orden si está `pending` o `assigned`; si ya va `in_route`, transfiere el reporte a la Torre de Control.
* **Flujo G: Borrado de Dirección Guardada:** Almacena la dirección en `_deleted_addresses` para no volver a sugerirla.

---

## 5.4. Mapeo Visual de Interacción por Plataforma

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                              MAPA DE COMPONENTES UI POR PLATAFORMA                              │
├─────────────────┬──────────────────┬─────────────────────────────┬──────────────────────────────┤
│ TELEGRAM        │ WHATSAPP         │ MESSENGER                   │ INSTAGRAM                    │
├─────────────────┼──────────────────┼─────────────────────────────┼──────────────────────────────┤
│ [ 🛢️ Cilindros ]│ [ Lista:         │ [ Carrusel de Tarjetas:     │ [ Quick Replies:             │
│ [ 🔥 Estac.    ]│   • 30 kg ($670) │   Imagen + Título + Botón   │   🛢️ Cilindros               │
│                 │   • 20 kg ($447) │   "Comprar 30 kg" ]         │   🔥 Estacionario ]          │
│ Botones Inline  │   • 45 kg ($1005)│                             │                              │
│ en 2 Columnas   │   • 10 kg ($224)]│ Quick Replies inferiores:   │ Quick Replies deslizables    │
│                 │                  │ [ 💵 Efectivo ] [ 💳 Tarj ] │ horizontales (hasta 13)      │
│ ReplyKeyboard:  │ Botones de 3:    │                             │                              │
│ 📍 Ubicación GPS│ [ ➕ Agregar ]   │ Botón Quick Reply de GPS:   │ Solicitud de texto o         │
│ 📱 Mi Teléfono  │ [ ➡️ Continuar ] │ 📍 Compartir Ubicación      │ dirección con referencias    │
└─────────────────┴──────────────────┴─────────────────────────────┴──────────────────────────────┘
```

---

# PARTE 6: ESPECIFICACIÓN UX/UI

---

## 6.1. Filosofía de Diseño y Tono de Voz Institucional

* **Tono:** Cercano, institucional, eficiente, respetuoso y regionalmente afín a Mazatlán y Sinaloa.
* **Estructura:** Mensajes concisos ($\le 3$ párrafos cortos), legibles en pantallas móviles.

---

## 6.2. Sistema de Tokens Visuales y Emojis Semánticos

| Emoji | Significado Semántico | Ejemplo de Uso |
| :---: | :--- | :--- |
| 🛢️ | Cilindro de Gas LP | `[ 🛢️ Cilindros de Gas ]` |
| 🔥 | Tanque Estacionario | `[ 🔥 Tanque Estacionario ]` |
| 📍 | Ubicación geográfica o GPS | `📍 Entregar en: Av. Delfín #402` |
| 🕒 / ⚡ | Horario de entrega | `⚡ Lo antes posible`, `🕒 Programar` |
| 💵 / 💳 / 📱 | Métodos de pago | `💵 Efectivo`, `💳 Tarjeta`, `📱 Transferencia` |
| ✅ / ❌ / ✏️ | Acciones de confirmación | `[ ✅ Confirmar ]`, `[ ❌ Cancelar ]`, `[ ✏️ Modificar ]` |
| ⭐ | Calificación CSAT | `[ ⭐⭐⭐⭐⭐ ] Excelente servicio` |

---

## 6.3. Especificación de Componentes UI por Plataforma

* **Telegram:** `InlineKeyboardMarkup` en cuadrículas de 2 columnas; `ReplyKeyboardMarkup` de un solo uso para compartir contacto y GPS nativo.
* **WhatsApp:** Mensajes interactivos de lista (`type: list`, 1 sección, hasta 10 filas) y mensajes de botones (`type: button`, máximo 3 botones, $\le 20$ caracteres).
* **Facebook Messenger:** Carruseles `Generic Template` con imágenes de producto y Quick Replies deslizables.
* **Instagram Direct:** Quick Replies deslizables (hasta 13 botones) y respuestas en hilo directo (DM).

---

## 6.4. Copywriting Oficial y Plantillas de Mensajes

### Bienvenida
```text
¡Hola! 👋 Te damos la bienvenida a Gas a tu Puerta de Grupo Petroil en Mazatlán.

Estamos listos para llevar tu gas hasta la puerta de tu hogar o negocio. 🚛💨
¿Qué tipo de servicio necesitas hoy?
```
*(Botones: `[ 🛢️ Cilindros de Gas ]` | `[ 🔥 Tanque Estacionario ]`)*

### Resumen Financiero y Confirmación
```text
📋 RESUMEN DE TU PEDIDO — PETROIL GAS
═══════════════════════════════════════
🛢️ Producto: 1x Cilindro de 30 kg
💰 Total a Pagar: $670.00 MXN
📍 Domicilio: Av. Delfín #402, Fracc. Alarcón
🕒 Entrega: Lo antes posible (30-45 min)
💳 Método de Pago: Efectivo
👤 Titular: María González (669-123-4567)
═══════════════════════════════════════
Por favor, revisa que los datos sean correctos para enviar tu unidad.
```
*(Botones: `[ ✅ Confirmar Pedido ]` | `[ ✏️ Modificar Algo ]` | `[ ❌ Cancelar ]`)*

### Calificación CSAT Post-Entrega
```text
🌟 En Grupo Petroil tu opinión es lo más importante.
¿Cómo calificarías la rapidez y atención de tu repartidor hoy?

[ ⭐ ]  [ ⭐⭐ ]  [ ⭐⭐⭐ ]  [ ⭐⭐⭐⭐ ]  [ ⭐⭐⭐⭐⭐ ]
```

---

## 6.5. Matriz de Errores, Recuperación y Fallbacks

| Error o Excepción | Causa Probable | Mensaje de Recuperación UX | Acción del Sistema |
| :--- | :--- | :--- | :--- |
| **Teléfono Inválido** | Usuario escribe letras o menos de 10 dígitos | *"El número debe ser de 10 dígitos (ej. 6691234567). Por favor, ingrésalo nuevamente:"* | Permanece en `WAITING_FOR_PHONE` |
| **Dirección no Localizada** | Calle inexistente o colonia fuera de Mazatlán | *"No pudimos ubicar con precisión esa dirección en Mazatlán. ¿Podrías indicarnos colonia y entre qué calles se encuentra, o enviarnos tu ubicación GPS?"* | Reabre botón de GPS nativo y texto de referencias |
| **Audio Inaudible o con Ruido** | Viento fuerte o audio vacío en Whisper | *"No alcanzamos a escuchar con claridad tu nota de voz. 🎤 ¿Podrías grabarla de nuevo o escribir tu pedido en texto?"* | Mantiene el estado actual |
| **Interrupción de Sesión** | Usuario abandona el chat a la mitad del flujo | Al volver a escribir: *"Tenías un pedido en proceso para 1x Cilindro de 30 kg. ¿Deseas continuarlo o empezar de nuevo?"* | Botones `[ Continuar ]` y `[ Reiniciar ]` |
| **Fallo Temporal de API Externa** | Meta API o Telegram experimenta lentitud | *"Estamos experimentando una breve interrupción en la red. Tu pedido no se ha perdido; reintentando en un momento..."* | Reintento automático asíncrono con backoff |

---

# PARTE 7: PLAN DE IMPLEMENTACIÓN ÁGIL

---

## 7.1. Índice General de Épicas de Bots de Usuario

| ID | Nombre de la Épica | Módulos y Código Involucrado | Estado |
| :--- | :--- | :--- | :---: |
| **EPIC-BOT-01** | Bot de Usuario en Telegram (Teclados, GPS, Contacto y Whisper) | `telegram_bot.py`, `src/services/flow_router.py` | ✅ Implementado |
| **EPIC-BOT-02** | Bot de Usuario en WhatsApp Cloud API (Listas, Botones y Carrito) | `src/channels/whatsapp/adapter.py`, `router.py` | ✅ Implementado |
| **EPIC-BOT-03** | Bot de Usuario en Facebook Messenger (Carruseles, HMAC y PSID) | `src/channels/messenger/adapter.py`, `router.py` | ✅ Implementado |
| **EPIC-BOT-04** | Bot de Usuario en Instagram Direct (Quick Replies, IGSID y Voz) | `src/channels/instagram/adapter.py`, `router.py` | ✅ Implementado |
| **EPIC-BOT-05** | Motor Conversacional Central, Carrito y Regla Zero-LLM | `src/services/flow_router.py`, `src/graphs/sales_graph.py` | ✅ Implementado |
| **EPIC-BOT-06** | Identidad Cross-Channel, Geocodificación y Transcripción Whisper | `src/repositories/identity_store.py`, `src/services/*` | ✅ Implementado |
| **EPIC-BOT-07** | Notificaciones Push de Entrega y Calificación CSAT Multi-Canal | `src/services/notifications.py`, `src/repositories/` | ✅ Implementado |

---

## 7.2. EPIC-BOT-01: Bot de Usuario en Telegram (`telegram_bot.py`)

### STORY-BOT-01.1: Menú Inicial con Teclados Inline
```gherkin
Scenario: Inicio de sesión en Telegram
  Given que el usuario abre el chat con el bot de Telegram y envía "/start" o "Hola"
  When el bot procesa el mensaje
  Then responde con el mensaje institucional de Grupo Petroil
  And adjunta un InlineKeyboardMarkup con los botones "[ 🛢️ Cilindros ]" y "[ 🔥 Tanque Estacionario ]"
  And los callback_data corresponden a "srv_cilindro" y "srv_estacionario"
```

### STORY-BOT-01.2: Captura Nativa de Teléfono y Ubicación GPS
```gherkin
Scenario: Envío de contacto y ubicación en Telegram
  Given que el bot se encuentra en el estado WAITING_FOR_PHONE o WAITING_FOR_NEW_CUSTOMER_ADDRESS
  When el bot solicita la información
  Then despliega un ReplyKeyboardMarkup con:
    | Botón | Atributo |
    | "📱 Compartir mi Teléfono en 1 Toque" | request_contact=True |
    | "📍 Enviar mi Ubicación GPS" | request_location=True |
  And al presionar el botón de ubicación, el bot recibe las coordenadas latitud/longitud
  And ejecuta reverse_geocode para obtener calle y colonia en Mazatlán
```

---

## 7.3. EPIC-BOT-02: Bot de Usuario en WhatsApp Cloud API (`src/channels/whatsapp/`)

### STORY-BOT-02.1: Handshake de Verificación y Webhook
```gherkin
Scenario: Verificación de Webhook de WhatsApp (GET)
  Given una petición GET a "/channels/whatsapp/webhook"
  When los parámetros incluyen "hub.mode=subscribe" y "hub.verify_token" correcto
  Then el endpoint devuelve HTTP 200 con el valor de "hub.challenge" en texto plano

Scenario: Recepción de mensaje de texto en WhatsApp (POST)
  Given una petición POST a "/channels/whatsapp/webhook" con un payload válido de Meta
  When el router procesa el evento
  Then responde HTTP 200 OK inmediatamente
  And delega la respuesta conversacional a BackgroundTasks sin bloquear el hilo
```

### STORY-BOT-02.2: Catálogo en Lista Interactiva y Carrito `wa_carts`
```gherkin
Scenario: Selección de cilindro y actualización de carrito en WhatsApp
  Given que el cliente solicita comprar cilindros
  When el bot responde
  Then envía un mensaje interactivo tipo "list" con 1 sección y las capacidades (10, 20, 30, 45 kg)
  And cuando el usuario selecciona "Cilindro de 30 kg", se almacena en el diccionario wa_carts
  And el bot responde con el total acumulado y botones "[ ➕ Agregar otro ]" y "[ ➡️ Continuar ]"
```

### STORY-BOT-02.3: Recuperación Automática ante Error 401
```gherkin
Scenario: Reintento automático ante token expirado en WhatsApp
  Given que el WhatsAppAdapter envía un mensaje a Meta Graph API
  When Meta responde con código HTTP 401 Unauthorized
  Then el adaptador invoca invalidate_dynamic_settings_cache()
  And recarga la configuración remota
  And reintenta el envío del mensaje de manera transparente para el usuario
```

---

## 7.4. EPIC-BOT-03: Bot de Usuario en Facebook Messenger (`src/channels/messenger/`)

### STORY-BOT-03.1: Validación Criptográfica de Firma HMAC-SHA256
```gherkin
Scenario: Rechazo de petición con firma falsa en Messenger
  Given una petición POST a "/channels/messenger/webhook"
  When el hash HMAC-SHA256 calculado con MESSENGER_APP_SECRET no coincide con la firma recibida
  Then el router rechaza la petición con código HTTP 403 Forbidden
  And no procesa ningún mensaje interno

Scenario: Aceptación de petición legítima de Meta
  Given una petición con firma HMAC-SHA256 válida
  Then el router la acepta con HTTP 200 OK y la procesa normalmente
```

### STORY-BOT-03.2: Despliegue de Carrusel de Productos y Quick Replies
```gherkin
Scenario: Navegación de catálogo en Messenger
  Given que el usuario selecciona el catálogo de cilindros
  When el bot responde
  Then envía un "Generic Template" con elementos visuales para cada capacidad de cilindro
  And cada tarjeta contiene título, precio en subtítulo, imagen oficial y botón de postback
  And al seleccionar un producto, ofrece Quick Replies inferiores para métodos de pago
```

---

## 7.5. EPIC-BOT-04: Bot de Usuario en Instagram Direct (`src/channels/instagram/`)

### STORY-BOT-04.1: Interacción Táctil Deslizable en Instagram DM
```gherkin
Scenario: Selección de opciones en Instagram Direct
  Given una conversación activa en Instagram Direct
  When el bot presenta opciones de selección (productos, direcciones u horarios)
  Then envía hasta 13 Quick Replies deslizables horizontalmente
  And asocia cada botón al IGSID del cliente en el caché de sesión ig_carts
```

### STORY-BOT-04.2: Descarga y Transcripción de Audios M4A en Instagram
```gherkin
Scenario: Procesamiento de nota de voz en Instagram
  Given que el usuario envía un audio en formato M4A / AAC por Instagram Direct
  When el router recibe el adjunto de tipo "audio"
  Then descarga el archivo binario desde la URL temporal de CDN de Instagram
  And lo envía al servicio transcribe_audio_file de Whisper
  And procesa el texto resultante en el flujo de ventas sin pedir al usuario volver a escribir
```

---

## 7.6. EPIC-BOT-05: Motor Conversacional Central y Carrito Multi-Producto (`flow_router.py`)

### STORY-BOT-05.1: Regla Zero-LLM en Opciones Estructuradas
```gherkin
Scenario: Procesamiento determinista sin LLM
  Given que el usuario presiona un botón interactivo o envía un comando estándar
  When flow_router.py procesa el input
  Then resuelve la transición de estado mediante lógica determinista
  And realiza exactamente 0 llamadas a la API de OpenRouter / DeepSeek
  And la respuesta se emite en menos de 1.2 segundos
```

### STORY-BOT-05.2: Resumen Financiero y Confirmación Previa Obligatoria
```gherkin
Scenario: Confirmación obligatoria de pedido
  Given que el cliente completó productos, dirección, horario y pago
  When el bot alcanza el estado WAITING_FOR_CONFIRMATION
  Then muestra la tarjeta resumen con productos, importe total en MXN, dirección y pago
  And no crea el pedido en base de datos hasta que el cliente presione "[ ✅ Confirmar Pedido ]"
  And al confirmar, ejecuta create_order y entrega el Folio numérico al cliente
```

---

## 7.7. EPIC-BOT-06: Identidad Cross-Channel, Geocodificación y Whisper

### STORY-BOT-06.1: Enlace Universal de Teléfono en `IdentityStore`
```gherkin
Scenario: Vinculación cross-channel de cliente
  Given que el cliente tiene el teléfono "6691234567" registrado con direcciones en WhatsApp
  When inicia conversación en Telegram y comparte ese mismo número telefónico
  Then IdentityStore enlaza su chat_id de Telegram con el teléfono
  And el bot de Telegram le muestra de inmediato sus direcciones guardadas en botones
```

### STORY-BOT-06.2: Geocodificación Satelital con Nominatim Mazatlán
```gherkin
Scenario: Geocodificación de dirección en Mazatlán
  Given una dirección proporcionada por texto o GPS
  When se ejecuta geocode_address()
  Then consulta Nominatim acotado al bounding box de Mazatlán, Sinaloa
  And devuelve coordenadas lat/lng válidas
  And asocia las coordenadas al pedido para el cálculo de cercanía del chofer
```

---

## 7.8. EPIC-BOT-07: Notificaciones Push de Entrega y Calificación CSAT Multi-Canal

### STORY-BOT-07.1: Notificación Push Reactiva al Canal de Origen
```gherkin
Scenario: Notificación de chofer en ruta
  Given un pedido creado por WhatsApp en estado "in_route"
  When el chofer inicia el viaje en driver_bot.py
  Then notifications.py identifica el canal "whatsapp" y el "channel_user_id" en IdentityStore
  And envía un mensaje proactivo al cliente con el nombre del chofer y placas de la unidad
```

### STORY-BOT-07.2: Encuesta de Calidad CSAT de 1 a 5 Estrellas
```gherkin
Scenario: Envío y captura de calificación CSAT
  Given que un pedido cambia a estado "delivered"
  When el bot envía el comprobante de entrega
  Then adjunta botones de calificación del 1 al 5 (⭐ a ⭐⭐⭐⭐⭐)
  And al seleccionar una opción, guarda el puntaje en la tabla ORDER_RATINGS
  And emite un mensaje de agradecimiento personalizado según el puntaje
```
