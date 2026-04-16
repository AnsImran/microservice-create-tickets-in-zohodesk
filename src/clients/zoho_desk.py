"""Zoho Desk API client — product resolution and ticket creation."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from src.app.config import PRODUCT_MAP_PATH, get_settings
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
    """Read the product name-to-ID map from ``product_map.json``.

    Reading from disk (not process memory) means hand-edits to the file
    are picked up on the next request without restarting the service.
    """
    if not PRODUCT_MAP_PATH.exists():
        return {}
    try:
        return json.loads(PRODUCT_MAP_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read %s: %s", PRODUCT_MAP_PATH, exc)
        return {}


def _save_product_map(name: str, product_id: str) -> None:
    """Add a new mapping to ``product_map.json`` and write the file back."""
    existing = _read_product_map()
    existing[name] = product_id
    PRODUCT_MAP_PATH.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    logger.info("Persisted new product mapping: %s -> %s", name, product_id)


async def _fetch_products_from_api(client: httpx.AsyncClient, token: str) -> dict[str, str]:
    """``GET /api/v1/products`` from Zoho Desk and return ``{name: id}`` map."""
    settings = get_settings()
    url = f"{settings.zoho_desk_base}/api/v1/products"
    resp = await client.get(url, headers=_desk_headers(token), params={"limit": 100})
    resp.raise_for_status()
    data = resp.json().get("data", [])
    return {item["productName"]: item["id"] for item in data if "productName" in item and "id" in item}


def _ci_lookup(mapping: dict[str, str], key: str) -> str | None:
    """Case-insensitive lookup — returns the value if *key* matches any map key, else ``None``."""
    key_lower = key.lower()
    for stored_name, stored_id in mapping.items():
        if stored_name.lower() == key_lower:
            return stored_id
    return None


async def resolve_product_id(client: httpx.AsyncClient, token: str, product_name: str) -> str:
    """Resolve a human-readable product name to its Zoho product ID.

    Resolution order
    ----------------
    1. **Local file lookup** — read ``product_map.json`` (0 API calls).
    2. **Zoho API fallback** — ``GET /api/v1/products``, then persist the new
       mapping back to ``product_map.json`` so future lookups are instant.
    3. **Not found** — raise :class:`ProductNotFoundError`.
    """
    local_map = _read_product_map()
    local_hit = _ci_lookup(local_map, product_name)
    if local_hit:
        return local_hit

    logger.info("Product '%s' not in local map — fetching from Zoho API", product_name)
    api_map = await _fetch_products_from_api(client, token)
    api_hit = _ci_lookup(api_map, product_name)
    if api_hit:
        _save_product_map(product_name, api_hit)
        return api_hit

    raise ProductNotFoundError(f"Product '{product_name}' not found in Zoho Desk")


async def resolve_product_ids_batch(
    client: httpx.AsyncClient,
    token: str,
    product_names: list[str],
) -> tuple[dict[str, str], list[str]]:
    """Resolve a list of product names to Zoho product IDs in one pass.

    Returns ``(resolved, not_found)`` where *resolved* maps each name to
    its ID and *not_found* lists names that could not be resolved.

    Resolution order
    ----------------
    1. **Local file lookup** — read ``product_map.json`` (0 API calls).
    2. **Zoho Products API** — ``GET /api/v1/products`` for any remaining
       names.  Newly discovered mappings are persisted to ``product_map.json``.
    3. Names still unresolved go into *not_found*.

    The call never raises for missing products — *not_found* is the
    communication channel.  If the Zoho API itself fails, all pending
    names land in *not_found* and the error is logged.
    """
    resolved: dict[str, str] = {}
    pending: list[str] = []

    # -- Tier 1: local file lookup (zero API calls) --
    local_map = _read_product_map()
    for name in product_names:
        local_hit = _ci_lookup(local_map, name)
        if local_hit:
            resolved[name] = local_hit
        else:
            pending.append(name)

    if not pending:
        return resolved, []

    # -- Tier 2: single Zoho Products API call for all remaining names --
    logger.info("Batch resolve: %d name(s) not in local map — fetching from Zoho API", len(pending))
    try:
        api_map = await _fetch_products_from_api(client, token)
    except Exception:
        logger.error(
            "Zoho Products API call failed — %d name(s) will be reported as not_found",
            len(pending),
            exc_info=True,
        )
        return resolved, pending

    not_found: list[str] = []
    for name in pending:
        api_hit = _ci_lookup(api_map, name)
        if api_hit:
            resolved[name] = api_hit
            _save_product_map(name, api_hit)
        else:
            logger.warning("Product '%s' not found in Zoho products API", name)
            not_found.append(name)

    return resolved, not_found


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
