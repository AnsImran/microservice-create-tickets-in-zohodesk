"""Application settings loaded from environment variables / .env file."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_PATH: Path = Path(__file__).resolve().parents[2] / ".env"

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class Settings(BaseSettings):
    """Centralised, validated configuration for the ticket-creation microservice."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_PATH),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Token service -------------------------------------------------
    zoho_token_service_url: str = Field(
        default="http://127.0.0.1:8000/v1/token",
        description="URL of the centralised Zoho token service.",
        examples=["http://127.0.0.1:8000/v1/token"],
    )

    # --- Zoho Desk API -------------------------------------------------
    zoho_desk_base: str = Field(
        default="https://desk.zoho.com",
        description="Base URL for the Zoho Desk REST API.",
        examples=["https://desk.zoho.com"],
    )
    zoho_desk_org_id: str = Field(
        ...,
        min_length=1,
        description="Zoho organisation ID sent as the 'orgId' header on every Desk API call.",
        examples=["898106677"],
    )
    zoho_desk_default_department_id: str = Field(
        default="",
        description="Fallback Zoho department ID used when the request does not supply one.",
        examples=["1166045000000006907"],
    )

    # --- Product map ---------------------------------------------------
    product_map: str = Field(
        default="",
        description=(
            "Comma-separated 'name:id' pairs that map human-readable product names "
            "to Zoho product IDs. Queried before hitting the Zoho API."
        ),
        examples=["Code Stroke Alert:1166045000001146278,Amendments:1166045000001146306"],
    )

    # --- HTTP ----------------------------------------------------------
    http_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        description="Timeout in seconds for outgoing HTTP requests (token service + Zoho Desk).",
    )

    # --- Logging -------------------------------------------------------
    log_level: str = Field(
        default="INFO",
        description="Python log level. One of DEBUG, INFO, WARNING, ERROR, CRITICAL.",
    )
    log_format: str = Field(
        default="json",
        description="Log output format: 'json' for structured JSON lines, 'text' for human-readable.",
    )

    @field_validator("log_level")
    @classmethod
    def _normalise_log_level(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in _VALID_LOG_LEVELS:
            raise ValueError(f"log_level must be one of {_VALID_LOG_LEVELS}, got '{v}'")
        return v

    @field_validator("log_format")
    @classmethod
    def _normalise_log_format(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in ("json", "text"):
            raise ValueError(f"log_format must be 'json' or 'text', got '{v}'")
        return v

    @field_validator("zoho_desk_base", "zoho_token_service_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton of the validated settings."""
    return Settings()
