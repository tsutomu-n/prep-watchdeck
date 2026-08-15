from __future__ import annotations

import asyncio
import signal
from contextlib import suppress
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Never

import typer
from loguru import logger
from pydantic import ValidationError
from rich.console import Console

from prep_watchdeck_market.config import Settings, require_production_database_target
from prep_watchdeck_market.database import (
    DatabaseError,
    check_database,
    migrate_database,
)
from prep_watchdeck_market.maintenance import MaintenanceError, run_daily_maintenance
from prep_watchdeck_market.runtime_lock import RuntimeLockUnavailable, exclusive_runtime_lock
from prep_watchdeck_market.service import MarketServiceError, run_market_service

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


@app.command()
def migrate() -> None:
    """Apply pending database migrations exactly once."""
    settings = _load_settings()
    _require_database_target(settings)
    try:
        result = migrate_database(settings.database_url)
    except DatabaseError as exc:
        _fail_database("migration", exc)
    console.print(
        "[green]database migrations ready[/green] "
        f"applied={len(result.applied)} "
        f"currentVersion={result.current_version} "
        f"pending={result.pending}"
    )


@app.command()
def status() -> None:
    """Show effective local paths and database migration state."""
    settings = _load_settings()
    _require_database_target(settings)
    try:
        health = check_database(settings.database_url)
    except DatabaseError as exc:
        _fail_database("status", exc)
    database_status = "ready" if health.ready else "not-ready"
    console.print(
        f"database={database_status} "
        f"currentVersion={health.current_version} "
        f"latestVersion={health.latest_version} "
        f"pending={health.pending} "
        f"stateDir={settings.state_dir}",
        soft_wrap=True,
    )
    if not health.ready:
        raise typer.Exit(code=1)


@app.command()
def health() -> None:
    """Check database connectivity and migration readiness."""
    settings = _load_settings()
    _require_database_target(settings)
    try:
        result = check_database(settings.database_url)
    except DatabaseError as exc:
        _fail_database("health", exc)
    if not result.ready:
        console.print(
            "[red]not healthy[/red] "
            f"currentVersion={result.current_version} "
            f"latestVersion={result.latest_version} "
            f"pending={result.pending}"
        )
        raise typer.Exit(code=1)
    console.print(
        "[green]healthy[/green] "
        f"currentVersion={result.current_version} "
        f"latestVersion={result.latest_version}"
    )


@app.command()
def maintenance(
    partition_date: str | None = typer.Option(
        None,
        "--partition-date",
        help="Preferred completed UTC day (YYYY-MM-DD); defaults to yesterday.",
    ),
) -> None:
    """Catch up completed UTC days and run bounded retention."""
    settings = _load_settings()
    _require_database_target(settings)
    now = datetime.now(UTC)
    try:
        target_date = (
            now.date() - timedelta(days=1)
            if partition_date is None
            else date.fromisoformat(partition_date)
        )
        with exclusive_runtime_lock(settings.state_dir / "market-maintenance.lock"):
            result = run_daily_maintenance(
                settings.database_url,
                settings.state_dir,
                partition_date=target_date,
                now=now,
            )
    except (ValueError, MaintenanceError, RuntimeLockUnavailable, OSError) as exc:
        logger.error("market maintenance failed: {error_type}", error_type=type(exc).__name__)
        console.print("[red]maintenance failed[/red]")
        raise typer.Exit(code=2) from exc
    selected = result.selected_retention
    has_more = (
        result.raw_retention.has_more
        or selected.has_more
        or any(item.has_more for item in result.retention)
    )
    console.print(
        "[green]maintenance complete[/green] "
        f"date={result.partition_date.isoformat()} "
        f"archives={len(result.archives)} "
        f"retentionPartitions={len(result.retention)} "
        f"rawDeleted={result.raw_retention.deleted} "
        f"selectedRawDeleted={selected.raw_deleted} "
        f"selectedNormalizedDeleted={selected.depth_deleted + selected.trades_deleted} "
        f"selectedLeasesDeleted={selected.leases_deleted} "
        f"hasMore={has_more}"
    )


@app.command()
def service() -> None:
    """Run the market collectors until SIGINT or SIGTERM."""
    settings = _load_settings()
    _require_database_target(settings)
    try:
        with exclusive_runtime_lock(settings.state_dir / "market-service.lock"):
            asyncio.run(_serve(settings.database_url, settings.state_dir))
    except KeyboardInterrupt:
        return
    except RuntimeLockUnavailable as exc:
        logger.error("market service lock unavailable")
        console.print("[red]market service already running[/red]")
        raise typer.Exit(code=2) from exc
    except OSError as exc:
        logger.error("market service lock failed: {error_type}", error_type=type(exc).__name__)
        console.print("[red]market service stopped[/red]")
        raise typer.Exit(code=2) from exc
    except MarketServiceError as exc:
        logger.error("market service failed: {error_type}", error_type=type(exc).__name__)
        console.print("[red]market service stopped[/red]")
        raise typer.Exit(code=2) from exc


async def _serve(database_url: str, state_dir: Path) -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed_signals: list[signal.Signals] = []
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_number, stop_event.set)
        except NotImplementedError:
            continue
        installed_signals.append(signal_number)
    try:
        await run_market_service(database_url, state_dir, stop_event)
    finally:
        for signal_number in installed_signals:
            with suppress(NotImplementedError):
                loop.remove_signal_handler(signal_number)


def _load_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        logger.error("market service configuration is invalid")
        console.print("[red]configuration invalid[/red] set PREP_WATCHDECK_MARKET_DATABASE_URL")
        raise typer.Exit(code=2) from exc


def _require_database_target(settings: Settings) -> None:
    if settings.allow_nonstandard_database_target:
        return
    try:
        require_production_database_target(settings.database_url)
    except ValueError as exc:
        logger.error("command rejected nonstandard database target")
        console.print(
            "[red]database target rejected[/red] "
            "set PREP_WATCHDECK_MARKET_ALLOW_NONSTANDARD_DATABASE_TARGET=true "
            "only for an isolated test or shadow database"
        )
        raise typer.Exit(code=2) from exc


def _fail_database(command: str, exc: DatabaseError) -> Never:
    logger.error(
        "database {command} failed: {error_type}",
        command=command,
        error_type=type(exc).__name__,
    )
    console.print("[red]database unavailable[/red]")
    raise typer.Exit(code=2) from exc
