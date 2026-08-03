from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PREP_WATCHDECK_",
        env_file=".env",
        extra="ignore",
    )

    repo_root: Path = Path("../..")
    state_dir: Path = Path("../../var")
    data_dir: Path = Path("../../var")
    out_dir: Path = Path("../../var/snapshots")
    config_dir: Path = Path("../../config/scanner-filters")
    fixtures_dir: Path = Path("../../fixtures")
    schema_path: Path = Path("../../schemas/scanner-snapshot.schema.json")
    cache_db_path: Path = Path("../../var/watchdeck.duckdb")
    past_notes_dir: Path = Path("../../var/past-notes")
    default_template: str = "balanced"
    product_type: str = "USDT-FUTURES"
    log_level: str = "INFO"
    lock_file: Path = Path("../../var/scanner.lock")
    live_max_symbols: int | None = 30
    live_candle_concurrency: int = 8
    cache_lock_timeout_seconds: float = 5.0
    cache_lock_retry_interval_seconds: float = 0.25
    service_state_path: Path = Path("../../var/snapshots/service-state.json")
    service_publish_interval_seconds: float = 60.0
    ticker_runtime_path: Path = Path("../../var/snapshots/ticker-runtime.json")
    ticker_publish_interval_seconds: float = 1.0
    vpi_config_path: Path = DEFAULT_REPO_ROOT / "config/vpi-lite-plus.toml"

    @property
    def latest_snapshot_path(self) -> Path:
        return self.out_dir / "latest.json"

    @model_validator(mode="before")
    @classmethod
    def derive_runtime_paths(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        values = dict(value)
        repo_root = Path(values.get("repo_root", DEFAULT_REPO_ROOT))
        if not repo_root.is_absolute():
            repo_root = repo_root.resolve()
        values["repo_root"] = repo_root

        state_dir = Path(values["state_dir"]) if "state_dir" in values else repo_root / "var"
        if not state_dir.is_absolute():
            state_dir = repo_root / state_dir
        state_dir = state_dir.resolve()
        values["state_dir"] = state_dir
        derived_paths = {
            "data_dir": state_dir,
            "out_dir": state_dir / "snapshots",
            "cache_db_path": state_dir / "watchdeck.duckdb",
            "past_notes_dir": state_dir / "past-notes",
            "lock_file": state_dir / "scanner.lock",
            "service_state_path": state_dir / "snapshots" / "service-state.json",
            "ticker_runtime_path": state_dir / "snapshots" / "ticker-runtime.json",
        }
        for field, path in derived_paths.items():
            values.setdefault(field, path)
        return values

    @field_validator("live_max_symbols", mode="before")
    @classmethod
    def parse_live_max_symbols(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip().lower() in {"all", "none", "unlimited"}:
            return None
        return value

    @field_validator(
        "data_dir",
        "out_dir",
        "cache_db_path",
        "past_notes_dir",
        "lock_file",
        "service_state_path",
        "ticker_runtime_path",
        "vpi_config_path",
        mode="after",
    )
    @classmethod
    def resolve_runtime_path(cls, value: Path) -> Path:
        return value.resolve()
