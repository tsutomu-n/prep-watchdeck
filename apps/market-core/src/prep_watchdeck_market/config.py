from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_state_dir() -> Path:
    return Path.home() / ".local" / "share" / "prep-watchdeck-market"


class Settings(BaseSettings):
    """Runtime configuration supplied by the local service environment."""

    model_config = SettingsConfigDict(
        env_prefix="PREP_WATCHDECK_MARKET_",
        extra="ignore",
    )

    database_url: str
    state_dir: Path = Field(default_factory=_default_state_dir)
    log_level: str = "INFO"
    allow_nonstandard_database_target: bool = False

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith(("postgresql://", "postgres://")):
            raise ValueError("database URL must use the PostgreSQL scheme")
        return normalized

    @field_validator("state_dir", mode="before")
    @classmethod
    def resolve_state_dir(cls, value: Any) -> Path:
        return Path(value).expanduser().resolve()


def require_production_database_target(database_url: str) -> None:
    """Reject mutating commands unless they target the dedicated local database."""

    try:
        target = urlsplit(database_url)
        port = target.port
    except ValueError:
        raise ValueError("database target is invalid") from None
    username = None if target.username is None else unquote(target.username)
    database = unquote(target.path.removeprefix("/"))
    if (
        target.scheme not in {"postgres", "postgresql"}
        or target.hostname != "127.0.0.1"
        or port != 55432
        or username != "prep_watchdeck_market"
        or database != "prep_watchdeck_market"
        or not target.password
        or target.query
        or target.fragment
    ):
        raise ValueError("database target is not the dedicated prep-watchdeck database")
