"""FastAPI application — Zoho Desk ticket creation microservice."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from src.clients.token_client import TokenServiceError, get_access_token
from src.clients.zoho_desk import ProductNotFoundError, ZohoDeskError, create_ticket, resolve_product_ids_batch
from src.core.logging_config import setup_logging
from src.core.middleware import RequestLoggingMiddleware
from src.schemas.tickets import (
    ErrorResponse,
    ProductResolveRequest,
    ProductResolveResponse,
    TicketRequest,
    TicketResponse,
)

from .config import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared HTTP client (created once, reused across all requests)
# ---------------------------------------------------------------------------

_http_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """Return the shared HTTP client. Raises if called before startup."""
    if _http_client is None:
        raise RuntimeError("HTTP client not initialised — lifespan has not run")
    return _http_client


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Startup: validate config, set up logging, create HTTP client.
    Shutdown: close the client cleanly.
    """
    global _http_client  # noqa: PLW0603

    settings = get_settings()  # fail fast if env vars are invalid
    setup_logging(level=settings.log_level, fmt=settings.log_format)

    _http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.http_timeout_seconds),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )
    logger.info("Zoho Desk ticket service starting (org=%s)", settings.zoho_desk_org_id)
    yield
    await _http_client.aclose()
    logger.info("Zoho Desk ticket service shut down")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Create Zoho Desk Ticket",
    description=(
        "Microservice that creates Zoho Desk tickets via the REST API. "
        "Accepts a generic ticket payload, resolves product names to IDs "
        "using a file-backed cache, and forwards the request to Zoho Desk."
    ),
    version="0.1.0",
    contact={"name": "PACS Pros", "email": "info@pacspros.llc"},
    lifespan=lifespan,
)

app.add_middleware(RequestLoggingMiddleware)


# ---------------------------------------------------------------------------
# Exception handlers — consistent ErrorResponse envelope
# ---------------------------------------------------------------------------

def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@app.exception_handler(TokenServiceError)
async def _token_error(request: Request, exc: TokenServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content=ErrorResponse(detail=str(exc), request_id=_request_id(request)).model_dump(),
    )


@app.exception_handler(ZohoDeskError)
async def _zoho_error(request: Request, exc: ZohoDeskError) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content=ErrorResponse(detail=str(exc), request_id=_request_id(request)).model_dump(),
    )


@app.exception_handler(ProductNotFoundError)
async def _product_error(request: Request, exc: ProductNotFoundError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(detail=str(exc), request_id=_request_id(request)).model_dump(),
    )


@app.exception_handler(ValueError)
async def _value_error(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content=ErrorResponse(detail=str(exc), request_id=_request_id(request)).model_dump(),
    )


@app.exception_handler(Exception)
async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception", extra={"request_id": _request_id(request)})
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(detail="Internal server error", request_id=_request_id(request)).model_dump(),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post(
    "/v1/tickets",
    response_model=TicketResponse,
    tags=["Tickets"],
    summary="Create a Zoho Desk ticket",
    responses={
        400: {"model": ErrorResponse, "description": "Missing required field (e.g. departmentId)."},
        422: {"model": ErrorResponse, "description": "Product name could not be resolved."},
        502: {"model": ErrorResponse, "description": "Zoho Desk API returned an error."},
        503: {"model": ErrorResponse, "description": "Token service unreachable."},
    },
)
async def post_create_ticket(req: TicketRequest) -> TicketResponse:
    """Accept a ticket payload, resolve product & department, and create the ticket in Zoho Desk."""
    return await create_ticket(get_http_client(), req)


@app.post(
    "/v1/products/resolve",
    response_model=ProductResolveResponse,
    tags=["Products"],
    summary="Resolve product names to Zoho product IDs",
    responses={
        503: {"model": ErrorResponse, "description": "Token service unreachable."},
    },
)
async def post_resolve_products(req: ProductResolveRequest) -> ProductResolveResponse:
    """Accept a list of product names and return their Zoho product IDs.

    Names found in the local ``PRODUCT_MAP`` are returned instantly.
    Unknown names trigger a single Zoho Products API call; newly
    discovered mappings are persisted to ``.env`` for future lookups.
    Names that cannot be resolved appear in the ``not_found`` list.
    """
    settings = get_settings()
    client = get_http_client()
    token = await get_access_token(client, settings.zoho_token_service_url)
    resolved, not_found = await resolve_product_ids_batch(client, token, req.product_names)
    return ProductResolveResponse(resolved=resolved, not_found=not_found)


@app.get("/v1/healthz", tags=["Health"], summary="Liveness probe")
async def healthz() -> dict[str, str]:
    """Always returns 200 — confirms the process is alive."""
    return {"status": "ok"}


@app.get(
    "/v1/readyz",
    tags=["Health"],
    summary="Readiness probe",
    responses={503: {"model": ErrorResponse, "description": "Token service not reachable."}},
)
async def readyz():
    """Checks connectivity to the token service. Returns 200 if healthy, 503 otherwise."""
    settings = get_settings()
    try:
        await get_access_token(get_http_client(), settings.zoho_token_service_url)
        return {"status": "ready"}
    except TokenServiceError as exc:
        return JSONResponse(
            status_code=503,
            content=ErrorResponse(detail=str(exc)).model_dump(),
        )


# ---------------------------------------------------------------------------
# Prometheus metrics (§38)
# ---------------------------------------------------------------------------
Instrumentator(
    excluded_handlers=[
        "/metrics",
        ".*/health.*",
        ".*/healthz",
        ".*/readyz",
    ],
).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
