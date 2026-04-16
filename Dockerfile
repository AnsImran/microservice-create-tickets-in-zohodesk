# ---------- builder stage ----------
FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    httpx \
    "pydantic>=2,<3" \
    pydantic-settings \
    python-dotenv

# ---------- runtime stage ----------
FROM python:3.12-slim

ARG BUILD_DATE
ARG VERSION=0.1.0

LABEL org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.title="microservice-create-zoho-desk-ticket" \
      org.opencontainers.image.description="Creates Zoho Desk tickets via the REST API."

# Copy installed packages from builder.
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Install curl for health checks, create non-root user.
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY src/ ./src/

USER appuser
EXPOSE 8100

# --workers 1 is intentional: the service writes to .env (PRODUCT_MAP)
# and multiple workers would race on that file.
CMD ["uvicorn", "src.app.main:app", "--host", "0.0.0.0", "--port", "8100", "--workers", "1"]
