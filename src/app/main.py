"""FastAPI application — Zoho Desk ticket creation microservice."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.clients.token_client import TokenServiceError, get_access_token
from src.clients.zoho_desk import ProductNotFoundError, ZohoDeskError, create_ticket
from src.schemas.tickets import TicketRequest, TicketResponse

from .config import settings

logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Zoho Desk ticket service starting")
    yield
    logger.info("Zoho Desk ticket service shutting down")


app = FastAPI(title="Create Zoho Desk Ticket", version="0.1.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(TokenServiceError)
async def _token_error(_request: Request, exc: TokenServiceError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(ZohoDeskError)
async def _zoho_error(_request: Request, exc: ZohoDeskError):
    return JSONResponse(status_code=502, content={"detail": str(exc), "zoho_status": exc.status_code})


@app.exception_handler(ProductNotFoundError)
async def _product_error(_request: Request, exc: ProductNotFoundError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(ValueError)
async def _value_error(_request: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post("/v1/tickets", response_model=TicketResponse)
async def post_create_ticket(req: TicketRequest):
    return await create_ticket(req)


@app.get("/v1/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/v1/readyz")
async def readyz():
    try:
        await get_access_token()
        return {"status": "ready"}
    except TokenServiceError as exc:
        return JSONResponse(status_code=503, content={"status": "not_ready", "detail": str(exc)})
