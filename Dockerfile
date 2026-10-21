# Tahap data: database hasil ETL di-commit dalam gzip (38 MB), dibongkar di sini
# (77 MB). Stage sendiri supaya layer-nya tetap ter-cache saat kode berubah.
FROM python:3.12-slim AS data
COPY data/olist.db.gz /tmp/olist.db.gz
RUN mkdir -p /app/data && python -c "import gzip, shutil; shutil.copyfileobj(gzip.open('/tmp/olist.db.gz'), open('/app/data/olist.db', 'wb'))"

# Tahap build: pasang dependensi dengan uv dari lockfile
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

# Tahap runtime: tanpa uv, tanpa kode sumber, tanpa secret
FROM python:3.12-slim
RUN useradd --create-home --uid 10001 app
WORKDIR /app
# Database baca saja untuk endpoint analytics dan agent SQL.
COPY --from=data --chown=app:app /app/data/olist.db /app/data/olist.db
COPY --from=builder --chown=app:app /app/.venv /app/.venv
# Model router ONNX (12 MB). Tanpa ini supervisor diam-diam memakai router LLM.
COPY --chown=app:app models/router /app/models/router
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 ROUTER_MODEL_DIR=/app/models/router \
    SQLITE_PATH=/app/data/olist.db
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["uvicorn", "olist_assistant.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
