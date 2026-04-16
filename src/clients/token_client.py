"""Fetch a Zoho access token from the centralised token service."""

from __future__ import annotations

import httpx

from src.app.config import settings


class TokenServiceError(Exception):
    """Raised when the token service is unreachable or returns an error."""


async def get_access_token() -> str:
    """GET the token service and return the raw access_token string."""
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
            resp = await client.get(settings.zoho_token_service_url)
            resp.raise_for_status()
            return resp.json()["access_token"]
    except (httpx.HTTPError, KeyError) as exc:
        raise TokenServiceError(f"Failed to obtain Zoho token: {exc}") from exc
