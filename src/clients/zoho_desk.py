"""Zoho Desk API client — product resolution and ticket creation."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from src.app.config import ENV_PATH, get_settings
from src.clients.token_client import get_access_token
from src.schemas.tickets import TicketRequest, TicketResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ProductNotFoundError(Exception):
    """Raised when a product name cannot be resolved to an ID."""


class ZohoDeskError(Exception):
    """Raised when the Zoho Desk API returns a non-success status."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"Zoho Desk API error {status_code}: {body}")


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------

def _desk_headers(token: str) -> dict[str, str]:
    """Build the standard header set for every Zoho Desk API call."""
    settings = get_settings()
    return {
        "Authorization": f"Zoho-oauthtoken {token}",
        "orgId": settings.zoho_desk_org_id,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Product-map helpers (file-backed)
# ---------------------------------------------------------------------------

def _read_product_map() -> dict[str, str]:
    """Parse ``PRODUCT_MAP`` from the ``.env`` file on disk.

    Reading from disk (not process memory) means hand-edits to ``.env``
    are picked up on the next request without restarting the service.
    """
    if not ENV_PATH.exists():
        return {}
    text = ENV_PATH.read_text(encoding="utf-8")
    match = re.search(r'^PRODUCT_MAP\s*=\s*["\']?(.+?)["\']?\s*$', text, re.MULTILINE)
    if not match:
        return {}
    raw = match.group(1)
    product_map: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if ":" not in pair:
            continue
        name, _, pid = pair.rpartition(":")
        name, pid = name.strip(), pid.strip()
        if name and pid:
            product_map[name] = pid
    return product_map


def _append_to_product_map(name: str, product_id: str) -> None:
    """Append a new ``name:id`` pair to ``PRODUCT_MAP`` in the ``.env`` file."""
    if not ENV_PATH.exists():
        ENV_PATH.write_text(f'PRODUCT_MAP="{name}:{product_id}"\n', encoding="utf-8")
        return

    text = ENV_PATH.read_text(encoding="utf-8")
    pattern = re.compile(r'^(PRODUCT_MAP\s*=\s*["\']?)(.+?)(["\']?\s*)$', re.MULTILINE)
    match = pattern.search(text)
    if match:
        prefix, existing, suffix = match.group(1), match.group(2), match.group(3)
        updated = f"{existing},{name}:{product_id}"
        text = text[: match.start()] + prefix + updated + suffix + text[match.end() :]
    else:
        text = text.rstrip("\n") + f'\nPRODUCT_MAP="{name}:{product_id}"\n'

    ENV_PATH.write_text(text, encoding="utf-8")
    logger.info("Persisted new product mapping: %s -> %s", name, product_id)


async def _fetch_products_from_api(client: httpx.AsyncClient, token: str) -> dict[str, str]:
    """``GET /api/v1/products`` from Zoho Desk and return ``{name: id}`` map."""
    settings = get_settings()
    url = f"{settings.zoho_desk_base}/api/v1/products"
    resp = await client.get(url, headers=_desk_headers(token), params={"limit": 100})
    resp.raise_for_status()
    data = resp.json().get("data", [])
    return {item["productName"]: item["id"] for item in data if "productName" in item and "id" in item}


async def resolve_product_id(client: httpx.AsyncClient, token: str, product_name: str) -> str:
    """Resolve a human-readable product name to its Zoho product ID.

    Resolution order
    ----------------
    1. **Local file lookup** — read ``PRODUCT_MAP`` from ``.env`` (0 API calls).
    2. **Zoho API fallback** — ``GET /api/v1/products``, then persist the new
       mapping back to ``.env`` so future lookups are instant.
    3. **Not found** — raise :class:`ProductNotFoundError`.
    """
    local_map = _read_product_map()
    if product_name in local_map:
        return local_map[product_name]

    logger.info("Product '%s' not in local map — fetching from Zoho API", product_name)
    api_map = await _fetch_products_from_api(client, token)
    if product_name in api_map:
        _append_to_product_map(product_name, api_map[product_name])
        return api_map[product_name]

    raise ProductNotFoundError(f"Product '{product_name}' not found in Zoho Desk")


# ---------------------------------------------------------------------------
# Ticket creation
# ---------------------------------------------------------------------------

async def create_ticket(client: httpx.AsyncClient, req: TicketRequest) -> TicketResponse:
    """Create a Zoho Desk ticket and return the essential response fields.

    Parameters
    ----------
    client:
        Shared async HTTP client (created in the FastAPI lifespan).
    req:
        Validated ticket-creation request.

    Raises
    ------
    ValueError
        If ``departmentId`` cannot be resolved.
    ProductNotFoundError
        If ``productName`` cannot be resolved to an ID.
    ZohoDeskError
        If the Zoho Desk API returns a non-2xx response.
    """
    settings = get_settings()

    # -- Resolve department --
    department_id = req.departmentId or settings.zoho_desk_default_department_id
    if not department_id:
        raise ValueError("departmentId is required (pass it in the request or set ZOHO_DESK_DEFAULT_DEPARTMENT_ID)")

    # -- Get access token --
    token = await get_access_token(client, settings.zoho_token_service_url)

    # -- Resolve product --
    product_id = req.productId
    if not product_id and req.productName:
        product_id = await resolve_product_id(client, token, req.productName)

    # -- Build Zoho payload --
    payload: dict[str, Any] = {
        "subject": req.subject,
        "description": req.description,
        "departmentId": department_id,
        "contact": req.contact.model_dump(exclude_none=True),
    }
    if product_id:
        payload["productId"] = product_id
    for field in ("channel", "priority", "status", "phone", "email", "category", "classification"):
        value = getattr(req, field, None)
        if value is not None:
            payload[field] = value
    if req.extra:
        payload.update(req.extra)

    # -- POST to Zoho Desk --
    url = f"{settings.zoho_desk_base}/api/v1/tickets"
    resp = await client.post(url, headers=_desk_headers(token), json=payload)

    if not resp.is_success:
        raise ZohoDeskError(resp.status_code, resp.text)

    data = resp.json()
    return TicketResponse(
        id=data["id"],
        ticketNumber=data["ticketNumber"],
        webUrl=data.get("webUrl"),
        subject=data.get("subject", req.subject),
        raw=data,
    )
