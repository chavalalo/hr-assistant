# Imagen del HR Assistant para Render (spec/04-production.md, punto 5).
FROM python:3.12-slim

# Sin archivos .pyc, log sin búfer y pip sin caché para una imagen más chica
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Usuario sin privilegios: el proceso nunca corre como root
RUN useradd --create-home --uid 10001 appuser

# Primero las dependencias, para aprovechar la caché de capas de Docker
COPY requirements.txt .
RUN pip install -r requirements.txt

# El código; .dockerignore deja fuera .env, pruebas y cachés
COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8000

# Render pone el puerto en PORT; sh -c expande la variable y exec deja a uvicorn
# como proceso principal para que reciba las señales de apagado
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
