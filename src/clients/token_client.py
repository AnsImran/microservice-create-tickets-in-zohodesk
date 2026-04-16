"""Fetch a Zoho access token from the centralised token service."""

from __future__ import annotations

import httpx


class TokenServiceError(Exception):
    """Raised when the token service is unreachable or returns an error."""


async def get_access_token(client: httpx.AsyncClient, token_service_url: str) -> str:
    """GET the token service and return the raw ``access_token`` string.

    Parameters
    ----------
    client:
        Shared async HTTP client (created in the FastAPI lifespan).
    token_service_url:
        Full URL of the token endpoint, e.g. ``http://127.0.0.1:8000/v1/token``.

    Raises
    ------
    TokenServiceError
        If the token service is unreachable, returns a non-2xx status,
        or the response does not contain an ``access_token`` key.
    """
    try:
        resp = await client.get(token_service_url)
        resp.raise_for_status()
        return resp.json()["access_token"]
    except (httpx.HTTPError, KeyError) as exc:
        raise TokenServiceError(f"Failed to obtain Zoho token: {exc}") from exc
