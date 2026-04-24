# Production image for the create-Zoho-Desk-ticket FastAPI microservice.
# Uses `uv` to install from pyproject.toml + uv.lock so dep drift is
# impossible. CMD wraps `uvicorn` with `opentelemetry-instrument`; traces
# ship via OTLP when OTEL_* env vars are set by docker-compose.

FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Dependency layer — cached unless pyproject.toml / uv.lock change.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# OTel auto-instrumentors (fastapi, httpx, logging, asgi, stdlib).
RUN opentelemetry-bootstrap -a install

# curl for healthchecks + non-root user.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

# Source.
COPY src/ ./src/

ARG BUILD_DATE
ARG VERSION=0.1.0
LABEL org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.title="microservice-create-zoho-desk-ticket" \
      org.opencontainers.image.description="Creates Zoho Desk tickets via the REST API."

USER appuser
EXPOSE 8100

# --workers 1 is intentional: the service writes to product_map.json
# and multiple workers would race on that file.
# opentelemetry-instrument wraps uvicorn. Inert when OTEL env vars absent.
CMD ["opentelemetry-instrument", "uvicorn", "src.app.main:app", "--host", "0.0.0.0", "--port", "8100", "--workers", "1"]
