# Imagen de la API (y de los mocks): dependencias congeladas por uv.lock,
# solo el codigo que se ejecuta y un usuario sin privilegios.
FROM python:3.12-slim

# Version fija de uv: la misma que genero uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.11.3 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app

# Capa de dependencias: solo cambia si cambia el lock.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Codigo de ejecucion (sin tests, docs ni interfaz web).
COPY ports.py ./
COPY api ./api
COPY config ./config
COPY domain ./domain
COPY adapters ./adapters
COPY tools ./tools
COPY mocks ./mocks
COPY agent ./agent
COPY observability ./observability
COPY fixtures ./fixtures

# Usuario sin privilegios; /data es el unico lugar donde se escribe.
RUN useradd --system --uid 10001 --no-create-home app \
    && mkdir /data && chown app /data
USER app

ENV AGENT_ENV=dev
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
