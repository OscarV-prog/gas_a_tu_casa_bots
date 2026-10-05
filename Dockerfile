FROM python:3.11-slim

# Evitar prompts interactivos y permitir ver logs en tiempo real
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Instalar herramientas básicas del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    sed \
    && rm -rf /var/lib/apt/lists/*

# Copiar dependencias e instalarlas
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copiar el código fuente completo
COPY . .

# Convertir posibles saltos de línea Windows (CRLF a LF) y dar permisos de ejecución
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Exponer el puerto para Webhooks de Meta, PWA y Tracking
EXPOSE 3000

# Punto de entrada y comando por defecto
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["all"]
