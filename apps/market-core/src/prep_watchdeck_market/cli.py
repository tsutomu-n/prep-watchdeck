from __future__ import annotations

import asyncio
import signal
import sys
from contextlib import suppress
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal, Never, cast

import aiohttp
import typer
from loguru import logger
from pydantic import ValidationError
from rich.console import Console

from prep_watchdeck_market.bundle_files import BundleError
from prep_watchdeck_market.candle_recovery import CandleRecovery, recovery_window
from prep_watchdeck_market.candle_recovery_state import CandleRecoveryState
from prep_watchdeck_market.config import Settings, require_production_database_target
from prep_watchdeck_market.database import (
    DatabaseError,
    check_database,
    migrate_database,
)
from prep_watchdeck_market.fixture_bundle import export_fixture as create_fixture_bundle
from prep_watchdeck_market.fixture_bundle import verify_fixture as verify_fixture_bundle
from prep_watchdeck_market.funding_runtime import run_funding_sync_once
from prep_watchdeck_market.funding_store import FundingStoreError
from prep_watchdeck_market.maintenance import MaintenanceError, run_daily_maintenance
from prep_watchdeck_market.reference_openmarket import (
    OpenMarketClient,
    ReferenceError,
)
from prep_watchdeck_market.reference_openmarket import (
    _key as reference_api_key,
)
from prep_watchdeck_market.reference_openmarket import (
    reference_markets as lookup_reference_markets,
)
from prep_watchdeck_market.reference_openmarket import (
    reference_snapshot as create_reference_snapshot,
)
from prep_watchdeck_market.runtime_lock import RuntimeLockUnavailable, exclusive_runtime_lock
from prep_watchdeck_market.service import MarketServiceError, run_market_service

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


@app.command("reference-markets")
def reference_markets_command(
    output: Annotated[Path, typer.Option("--output")],
    venue: str = typer.Option(..., "--venue"),
    symbol: str = typer.Option(..., "--symbol"),
) -> None:
    """Lookup bounded provider metadata for one current native contract."""
    try:
        key = reference_api_key()
        settings = _load_settings()

        async def execute() -> dict[str, Any]:
            async with aiohttp.ClientSession() as session:
                client = OpenMarketClient(session, key)
                return await lookup_reference_markets(
                    settings.database_url, client, venue=venue, symbol=symbol, output=output
                )

        result = asyncio.run(execute())
    except (ReferenceError, OSError, ValueError) as exc:
        code = exc.code if isinstance(exc, ReferenceError) else "reference_input_invalid"
        console.print(
            f"[red]{code}[/red]"
            + (
                " set OPENMARKET_API_KEY in the process environment"
                if code == "reference_auth_missing"
                else ""
            )
        )
        raise typer.Exit(code=2) from exc
    console.print(
        f"metadata={output} candidates={len(result['candidates'])} "
        f"complete={result['metadataComplete']}"
    )
    if not result["metadataComplete"]:
        raise typer.Exit(code=3)


@app.command("reference-snapshot")
def reference_snapshot_command(
    mapping: Annotated[Path, typer.Option("--mapping")],
    output_dir: Annotated[Path, typer.Option("--output-dir")],
    since: str = typer.Option(..., "--since"),
    until: str = typer.Option(..., "--until"),
) -> None:
    """Fetch and normalize an exact manually mapped OpenMarket one-minute window."""
    try:
        key = reference_api_key()
        settings = _load_settings()

        async def execute() -> tuple[Path, str]:
            async with aiohttp.ClientSession() as session:
                client = OpenMarketClient(session, key)
                path, receipt = await create_reference_snapshot(
                    settings.database_url,
                    settings.state_dir,
                    client,
                    mapping_path=mapping,
                    since=datetime.fromisoformat(since),
                    until=datetime.fromisoformat(until),
                    output_dir=output_dir,
                )
                return path, receipt.execution

        path, execution = asyncio.run(execute())
    except (ReferenceError, OSError, ValueError) as exc:
        code = exc.code if isinstance(exc, ReferenceError) else "reference_input_invalid"
        console.print(
            f"[red]{code}[/red]"
            + (
                " set OPENMARKET_API_KEY in the process environment"
                if code == "reference_auth_missing"
                else ""
            )
        )
        raise typer.Exit(code=2) from exc
    console.print(f"reference={path} execution={execution}")
    if execution != "completed":
        raise typer.Exit(code=3)


@app.command("export-fixture")
def export_fixture_command(
    output_dir: Annotated[Path, typer.Option("--output-dir")],
    instrument: str = typer.Option(..., "--instrument"),
    version: int = typer.Option(..., "--version", min=1),
    since: str = typer.Option(..., "--since"),
    until: str = typer.Option(..., "--until"),
    audit_run: str | None = typer.Option(None, "--audit-run"),
    evidence_kind: str = typer.Option("observed", "--evidence-kind"),
) -> None:
    """Export one contract/version from a read-only repeatable-read DB snapshot."""
    settings = _load_settings()
    try:
        if evidence_kind not in {"observed", "synthetic"}:
            raise BundleError("fixture_evidence_invalid")
        path, manifest = create_fixture_bundle(
            settings.database_url,
            settings.state_dir,
            output_dir,
            instrument_id=instrument,
            version_id=version,
            since=datetime.fromisoformat(since),
            until=datetime.fromisoformat(until),
            audit_run=audit_run,
            evidence_kind=cast(Literal["synthetic", "observed"], evidence_kind),
        )
    except (BundleError, ValueError, OSError) as exc:
        code = exc.code if isinstance(exc, BundleError) else "fixture_input_invalid"
        console.print(f"[red]{code}[/red]")
        raise typer.Exit(code=2) from exc
    console.print(f"fixture={path} execution={manifest.execution}")
    if manifest.execution != "completed":
        raise typer.Exit(code=3)


@app.command("verify-fixture")
def verify_fixture_command(bundle: Annotated[Path, typer.Option("--bundle")]) -> None:
    """Verify an existing fixture bundle without DB or network access."""
    try:
        manifest = verify_fixture_bundle(bundle)
    except (BundleError, OSError) as exc:
        code = exc.code if isinstance(exc, BundleError) else "fixture_verify_failed"
        console.print(f"[red]{code}[/red]")
        raise typer.Exit(code=2) from exc
    counts = ",".join(f"{dataset.name}:{dataset.availability}" for dataset in manifest.datasets)
    console.print(f"fixture={manifest.bundle_id} execution={manifest.execution} datasets={counts}")
    if manifest.execution != "completed":
        raise typer.Exit(code=3)


@app.command("recover-candles")
def recover_candles(
    venue: str | None = typer.Option(None, "--venue"),
    instrument: str | None = typer.Option(None, "--instrument"),
    since: str | None = typer.Option(None, "--since"),
    until: str | None = typer.Option(None, "--until"),
    apply: bool = typer.Option(False, "--apply"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Plan or apply bounded missing-row recovery for saved one-minute candles."""
    settings = _load_settings()
    _require_database_target(settings)
    try:
        if venue not in {None, "bitget", "hyperliquid", "aster"}:
            raise ValueError("unsupported recovery venue")
        start = None if since is None else datetime.fromisoformat(since)
        end = None if until is None else datetime.fromisoformat(until)
        window = recovery_window(datetime.now(UTC), since=start, until=end)
        if instrument and venue and not instrument.startswith(f"{venue}:"):
            raise ValueError("instrument does not match venue")

        async def execute() -> CandleRecoveryState:
            recovery = CandleRecovery(settings.database_url, settings.state_dir)
            if apply:
                async with aiohttp.ClientSession() as session:
                    return await recovery.run(
                        session, window, apply=True, venue=venue, instrument_id=instrument
                    )
            return await recovery.run(
                None, window, apply=False, venue=venue, instrument_id=instrument
            )

        state = asyncio.run(execute())
    except (ValueError, OSError, RuntimeError) as exc:
        logger.warning(
            "candle recovery rejected errorType={error_type}", error_type=type(exc).__name__
        )
        console.print("[red]candle recovery unavailable[/red]")
        raise typer.Exit(code=2) from exc
    if json_output:
        sys.stdout.write(state.model_dump_json(by_alias=True) + "\n")
    else:
        summary = state.summary
        console.print(
            f"recovery={state.execution} "
            f"window={window.start.isoformat()}..{window.end.isoformat()} "
            f"targets={summary.scanned_target_count}/{summary.target_count} "
            f"missing={summary.missing_before} inserted={summary.inserted} "
            f"remaining={summary.remaining} requests={summary.http_requests}"
        )
    if state.execution != "succeeded":
        raise typer.Exit(code=3)


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


@app.command("funding-sync")
def funding_sync() -> None:
    """Fetch bounded settled funding history for current active instruments."""
    settings = _load_settings()
    _require_database_target(settings)
    try:
        with exclusive_runtime_lock(settings.state_dir / "market-funding.lock"):
            result = asyncio.run(run_funding_sync_once(settings.database_url))
    except FundingStoreError as exc:
        logger.error("funding sync failed: {error_type}", error_type=type(exc).__name__)
        console.print("[red]funding sync failed[/red]")
        raise typer.Exit(code=2) from exc
    except RuntimeLockUnavailable as exc:
        logger.error("funding sync lock unavailable")
        console.print("[red]funding sync already running[/red]")
        raise typer.Exit(code=2) from exc
    except OSError as exc:
        logger.error("funding sync lock failed: {error_type}", error_type=type(exc).__name__)
        console.print("[red]funding sync failed[/red]")
        raise typer.Exit(code=2) from exc

    store = result.store
    status = "idle" if store is None else store.status
    console.print(
        "[green]funding sync complete[/green] "
        f"status={status} "
        f"attempted={result.requests_attempted} "
        f"succeeded={result.requests_succeeded} "
        f"notDue={result.instruments_not_due} "
        f"failures={result.failures} "
        f"written={0 if store is None else store.records_written} "
        f"unchanged={0 if store is None else store.records_unchanged}"
    )
    if store is not None and store.status == "failed":
        raise typer.Exit(code=2)
    if store is not None and store.status == "partial":
        raise typer.Exit(code=3)


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
            asyncio.run(
                _serve(
                    settings.database_url,
                    settings.state_dir,
                    recovery_enabled=settings.candle_recovery_enabled,
                )
            )
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


async def _serve(database_url: str, state_dir: Path, *, recovery_enabled: bool = False) -> None:
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
        if recovery_enabled:
            await run_market_service(database_url, state_dir, stop_event, recovery_enabled=True)
        else:
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
