"""Application settings loaded from environment variables / .env file."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_PATH: Path = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_PATH),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    zoho_token_service_url: str = "http://127.0.0.1:8000/v1/token"
    zoho_desk_base: str = "https://desk.zoho.com"
    zoho_desk_org_id: str
    zoho_desk_default_department_id: str = ""
    http_timeout_seconds: int = 30
    log_level: str = "INFO"
    product_map: str = ""


settings = Settings()
