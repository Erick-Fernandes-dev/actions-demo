# ---------- stage 1: build (instala dependências em um venv) ----------
FROM python:3.12-slim AS builder
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---------- stage 2: runtime (imagem final enxuta, usuário não-root) ----------
FROM python:3.12-slim AS runtime
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION} \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser

WORKDIR /srv
COPY --from=builder /opt/venv /opt/venv
COPY app/ ./app/

USER appuser
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD curl -fsS http://localhost:8000/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
