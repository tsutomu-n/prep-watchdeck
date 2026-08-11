from __future__ import annotations

import asyncio
import contextlib
import json
import signal
import time
from collections.abc import AsyncIterable, Callable, Coroutine, Mapping, Sequence
from pathlib import Path
from threading import RLock
from typing import Annotated, Any

import duckdb
import typer
from loguru import logger
from rich.console import Console
from rich.table import Table

from prep_watchdeck.adapters.duckdb.snapshot_cache import DuckDbSnapshotCacheLockError
from prep_watchdeck.application.market_comparison import (
    MARKET_COMPARISON_INTERVAL_SECONDS,
    MarketComparisonCollector,
    collect_market_comparison_once,
    refresh_market_comparison_once,
    refresh_market_comparison_periodically,
)
from prep_watchdeck.application.perp_venue_comparison import (
    PERP_VENUE_COMPARISON_INTERVAL_SECONDS,
    PerpVenueComparisonCollector,
    collect_perp_venue_comparison_once,
    refresh_perp_venue_comparison_once,
    refresh_perp_venue_comparison_periodically,
)
from prep_watchdeck.application.rekindle import (
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_MIN_ABS_CHANGE_PCT,
    DEFAULT_MIN_TURNOVER_USDT,
    detect_rekindle_notes,
)
from prep_watchdeck.application.run_cycle import run_scan_cycle
from prep_watchdeck.application.service_backfill import (
    BackfillProgressTracker,
    backfill_1m_candles,
    normalize_symbols,
)
from prep_watchdeck.application.service_bootstrap import (
    bootstrap_universe,
    refresh_ticker_latest_periodically,
)
from prep_watchdeck.application.service_deep_backfill import (
    DeepBackfillProgressTracker,
    run_deep_backfill_worker,
)
from prep_watchdeck.application.service_gap_audit import (
    audit_service_gaps,
    service_gap_audit_from_dict,
)
from prep_watchdeck.application.service_gap_repair import repair_service_gaps
from prep_watchdeck.application.service_plan import build_subscription_plan
from prep_watchdeck.application.service_publisher import (
    publish_service_state_once,
    publish_service_state_periodically,
)
from prep_watchdeck.application.service_reconcile import (
    ONE_MINUTE_MS,
    latest_closed_1m_bucket_ms,
    select_reconcile_symbols,
)
from prep_watchdeck.application.service_runtime import (
    ServiceRunResult,
    run_service_doctor,
    run_service_once,
)
from prep_watchdeck.application.service_snapshot import (
    DEFAULT_MAX_SERVICE_SNAPSHOT_DATA_LAG_MS,
    publish_service_snapshot_once,
    publish_service_snapshot_periodically,
)
from prep_watchdeck.application.service_watchdog import (
    ServiceWatchdogConfig,
    run_service_watchdog,
)
from prep_watchdeck.application.ticker_runtime import (
    TickerRuntimeCollector,
    publish_ticker_runtime_once,
    publish_ticker_runtime_periodically,
)
from prep_watchdeck.application.ws_frames import ChannelSpec, build_channel_specs
from prep_watchdeck.application.ws_runtime import WsStreamIngestResult, ingest_ws_payload_stream
from prep_watchdeck.application.ws_shards import WsShardIngestResult, ingest_ws_shards
from prep_watchdeck.bitget.candles import fetch_history_candles_range, fetch_recent_history_candles
from prep_watchdeck.bitget.client import BitgetPublicClient
from prep_watchdeck.bitget.contracts import fetch_contracts
from prep_watchdeck.bitget.tickers import fetch_all_tickers
from prep_watchdeck.bitget.ws_public import stream_public_payloads
from prep_watchdeck.composition import (
    build_providers,
    build_service_snapshot_writer,
    build_service_state_writer,
    build_service_store,
    build_snapshot_cache,
    build_snapshot_writer,
    build_ticker_runtime_writer,
)
from prep_watchdeck.config.templates import load_template
from prep_watchdeck.config.vpi_config import load_vpi_config
from prep_watchdeck.domain.dto import SnapshotDTO
from prep_watchdeck.domain.enums import Category
from prep_watchdeck.domain.service_models import (
    BackfillResult,
    BootstrapResult,
    ServiceDiagnostics,
    TickerLatestRecord,
)
from prep_watchdeck.domain.source_mode import SourceMode
from prep_watchdeck.export.schema_export import export_snapshot_schema
from prep_watchdeck.settings import Settings
from prep_watchdeck.storage.past_notes import PastNoteRepository

app = typer.Typer(no_args_is_help=True)
service_gap_app = typer.Typer(no_args_is_help=True)
app.add_typer(service_gap_app, name="service-gap")
console = Console()
MAX_BACKFILL_LIMIT = 6_000
DEFAULT_DEEP_BACKFILL_RATE_LIMIT_PER_SECOND = 5.0


@app.command()
def status() -> None:
    """Check local scanner-core wiring."""
    settings = Settings()
    console.print(
        "[green]watchdeck scanner-core is ready[/green] " + _runtime_paths_line(settings),
        soft_wrap=True,
    )


@app.command()
def service(
    once: Annotated[
        bool, typer.Option("--once", help="Initialize service state and exit.")
    ] = False,
    template: Annotated[str, typer.Option("--template")] = "balanced",
    universe: Annotated[str, typer.Option("--universe", help="all or selected")] = "all",
    max_symbols: Annotated[int | None, typer.Option("--max-symbols", min=1)] = None,
    shard_channels: Annotated[int, typer.Option("--shard-channels", min=1, max=49)] = 48,
    backfill_limit: Annotated[
        int, typer.Option("--backfill-limit", min=0, max=MAX_BACKFILL_LIMIT)
    ] = 200,
    backfill_concurrency: Annotated[int, typer.Option("--backfill-concurrency", min=1)] = 12,
    await_backfill: Annotated[
        bool,
        typer.Option(
            "--await-backfill",
            help="Wait for REST 1m seed before opening WebSocket shards.",
        ),
    ] = False,
    reconcile_interval_sec: Annotated[
        float,
        typer.Option(
            "--reconcile-interval-sec",
            min=0.0,
            help="Refresh stale 1m candles through REST at this interval; 0 disables it.",
        ),
    ] = 60.0,
    reconcile_limit: Annotated[int, typer.Option("--reconcile-limit", min=1, max=200)] = 60,
    reconcile_concurrency: Annotated[int, typer.Option("--reconcile-concurrency", min=1)] = 2,
    ticker_refresh_interval_sec: Annotated[
        float,
        typer.Option(
            "--ticker-refresh-interval-sec",
            min=0.0,
            help="Refresh public all-ticker data for current OI; 0 disables it.",
        ),
    ] = 60.0,
    watchdog_interval_sec: Annotated[
        float,
        typer.Option(
            "--watchdog-interval-sec",
            min=0.0,
            help="Check 1m candle progress at this interval; 0 disables the watchdog.",
        ),
    ] = 60.0,
    watchdog_stall_sec: Annotated[
        float,
        typer.Option(
            "--watchdog-stall-sec",
            min=1.0,
            help="Seconds without 1m candle progress before probing Bitget REST.",
        ),
    ] = 300.0,
    watchdog_confirmations: Annotated[
        int,
        typer.Option(
            "--watchdog-confirmations",
            min=1,
            help="Reachable-REST stall confirmations required before service failure.",
        ),
    ] = 3,
    watchdog_startup_grace_sec: Annotated[
        float,
        typer.Option(
            "--watchdog-startup-grace-sec",
            min=0.0,
            help="Seconds after startup before the watchdog may probe or fail.",
        ),
    ] = 300.0,
    deep_backfill_limit: Annotated[
        int,
        typer.Option(
            "--deep-backfill-limit",
            min=0,
            max=MAX_BACKFILL_LIMIT,
            help="Low-priority historical 1m target per symbol; 0 disables it.",
        ),
    ] = 0,
    deep_backfill_batch_size: Annotated[
        int,
        typer.Option(
            "--deep-backfill-batch-size",
            min=1,
            help="Symbols processed per deep backfill cycle.",
        ),
    ] = 1,
    deep_backfill_concurrency: Annotated[
        int,
        typer.Option("--deep-backfill-concurrency", min=1),
    ] = 1,
    deep_backfill_cooldown_sec: Annotated[
        float,
        typer.Option(
            "--deep-backfill-cooldown-sec",
            min=0.0,
            help="Seconds to sleep between deep backfill cycles.",
        ),
    ] = 5.0,
    deep_backfill_retry_delay_sec: Annotated[
        float,
        typer.Option(
            "--deep-backfill-retry-delay-sec",
            min=0.0,
            help="Seconds before retrying a failed deep backfill symbol.",
        ),
    ] = 60.0,
    deep_backfill_rate_limit_per_second: Annotated[
        float,
        typer.Option(
            "--deep-backfill-rate-limit-per-second",
            min=0.1,
            help="REST request rate for the deep backfill Bitget client.",
        ),
    ] = DEFAULT_DEEP_BACKFILL_RATE_LIMIT_PER_SECOND,
    stop_after_records: Annotated[
        int | None,
        typer.Option("--stop-after-records", min=1, hidden=True),
    ] = None,
) -> None:
    """Run the local watchdeck service."""
    settings = Settings()
    console.print("[dim]" + _runtime_paths_line(settings) + "[/dim]", soft_wrap=True)
    if once:
        diagnostics = run_service_once(build_service_store(settings))
        console.print("[green]service initialized[/green] " + _diagnostics_line(diagnostics))
        return
    if universe not in {"all", "selected"}:
        console.print("[red]invalid universe[/red] use all or selected")
        raise typer.Exit(code=2)

    try:
        result = asyncio.run(
            run_service_from_bitget(
                settings,
                template=template,
                universe=universe,
                max_symbols=max_symbols,
                shard_channels=shard_channels,
                backfill_limit=backfill_limit,
                backfill_concurrency=backfill_concurrency,
                await_backfill=await_backfill,
                reconcile_interval_sec=reconcile_interval_sec,
                reconcile_limit=reconcile_limit,
                reconcile_concurrency=reconcile_concurrency,
                ticker_refresh_interval_sec=ticker_refresh_interval_sec,
                watchdog_interval_sec=watchdog_interval_sec,
                watchdog_stall_sec=watchdog_stall_sec,
                watchdog_confirmations=watchdog_confirmations,
                watchdog_startup_grace_sec=watchdog_startup_grace_sec,
                deep_backfill_limit=deep_backfill_limit,
                deep_backfill_batch_size=deep_backfill_batch_size,
                deep_backfill_concurrency=deep_backfill_concurrency,
                deep_backfill_cooldown_sec=deep_backfill_cooldown_sec,
                deep_backfill_retry_delay_sec=deep_backfill_retry_delay_sec,
                deep_backfill_rate_limit_per_second=deep_backfill_rate_limit_per_second,
                stop_after_records=stop_after_records,
            )
        )
    except KeyboardInterrupt:
        console.print("[yellow]service interrupted[/yellow]")
        return
    except ValueError as exc:
        console.print(f"[red]service unavailable[/red] {exc}")
        raise typer.Exit(code=2) from exc
    console.print("[green]service stopped[/green] " + _service_run_line(result))


@app.command()
def doctor() -> None:
    """Check local watchdeck service storage."""
    settings = Settings()
    diagnostics = run_service_doctor(build_service_store(settings))
    console.print(
        "[green]serviceStore=OK[/green] "
        + _diagnostics_line(diagnostics)
        + " "
        + _runtime_paths_line(settings),
        soft_wrap=True,
    )


@app.command("publish-service")
def publish_service(
    template: Annotated[str, typer.Option("--template")] = "balanced",
) -> None:
    """Publish latest.json and service-state.json from the local service store."""
    settings = Settings()
    store = build_service_store(settings)
    config = load_template(settings.config_dir, template)
    vpi_config = load_vpi_config(settings.vpi_config_path)
    instruments = store.load_instruments()
    product_type = instruments[0].product_type if instruments else settings.product_type
    subscription = build_subscription_plan(
        [instrument.symbol for instrument in instruments],
        product_type=product_type,
    )
    state = publish_service_state_once(
        store,
        build_service_state_writer(settings),
        product_type=product_type,
        subscription=subscription,
    )
    try:
        market_comparison = collect_market_comparison_once()
        perp_venue_comparison = collect_perp_venue_comparison_once()
        snapshot = publish_service_snapshot_once(
            store,
            build_service_snapshot_writer(settings),
            build_snapshot_cache(settings),
            template=template,
            config=config,
            vpi_config=vpi_config,
            market_comparison=market_comparison,
            perp_venue_comparison=perp_venue_comparison,
            max_data_lag_ms=DEFAULT_MAX_SERVICE_SNAPSHOT_DATA_LAG_MS,
        )
    except ValueError as exc:
        console.print(f"[red]service unavailable[/red] {exc}")
        raise typer.Exit(code=2) from exc
    console.print(
        "[green]service snapshot published[/green] "
        f"template={template} "
        f"rows={len(snapshot.rows)} "
        f"tickers={state.diagnostics.ticker_count} "
        f"path={settings.latest_snapshot_path}"
    )


@service_gap_app.command("audit")
def service_gap_audit(
    symbols: Annotated[
        str | None,
        typer.Option("--symbols", help="Comma-separated symbols; defaults to normal instruments."),
    ] = None,
    required_1m_bars: Annotated[
        int,
        typer.Option("--required-1m-bars", min=1, max=MAX_BACKFILL_LIMIT),
    ] = MAX_BACKFILL_LIMIT,
    end_ts_ms: Annotated[int | None, typer.Option("--end-ts-ms", hidden=True)] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Audit missing 1m candles in the local service store without writing."""
    settings = Settings()
    window_end_ms = latest_closed_1m_bucket_ms(end_ts_ms)
    window_start_ms = window_end_ms - (required_1m_bars - 1) * ONE_MINUTE_MS
    store = build_service_store(settings)
    try:
        audit = audit_service_gaps(
            store,
            symbols=symbols.split(",") if symbols else [],
            window_start_ms=window_start_ms,
            window_end_ms=window_end_ms,
        )
    except duckdb.IOException as exc:
        console.print(f"[red]service store locked[/red] {exc}")
        raise typer.Exit(code=3) from exc
    payload = audit.to_dict()
    _write_or_print_json(payload, output)
    missing_symbols = sum(1 for item in audit.symbols if item.missing_count > 0)
    zero_volume_symbols = sum(1 for item in audit.symbols if item.zero_volume_count > 0)
    console.print(
        "[green]service gap audit complete[/green] "
        f"symbols={len(audit.symbols)} "
        f"missingSymbols={missing_symbols} "
        f"zeroVolumeSymbols={zero_volume_symbols}"
    )


@service_gap_app.command("repair")
def service_gap_repair(
    symbols: Annotated[
        str | None,
        typer.Option("--symbols", help="Comma-separated symbols; defaults to normal instruments."),
    ] = None,
    required_1m_bars: Annotated[
        int,
        typer.Option("--required-1m-bars", min=1, max=MAX_BACKFILL_LIMIT),
    ] = MAX_BACKFILL_LIMIT,
    audit_report: Annotated[Path | None, typer.Option("--audit-report")] = None,
    end_ts_ms: Annotated[int | None, typer.Option("--end-ts-ms", hidden=True)] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    write: Annotated[
        bool,
        typer.Option("--write", help="Actually upsert Bitget gap repair candles."),
    ] = False,
    rate_limit_per_second: Annotated[
        float,
        typer.Option("--rate-limit-per-second", min=0.1),
    ] = DEFAULT_DEEP_BACKFILL_RATE_LIMIT_PER_SECOND,
) -> None:
    """Repair audited 1m gaps from Bitget public history-candles."""
    settings = Settings()
    store = build_service_store(settings)
    try:
        if audit_report is not None:
            audit = service_gap_audit_from_dict(json.loads(audit_report.read_text()))
        else:
            window_end_ms = latest_closed_1m_bucket_ms(end_ts_ms)
            window_start_ms = window_end_ms - (required_1m_bars - 1) * ONE_MINUTE_MS
            audit = audit_service_gaps(
                store,
                symbols=symbols.split(",") if symbols else [],
                window_start_ms=window_start_ms,
                window_end_ms=window_end_ms,
            )
        result = asyncio.run(
            repair_service_gaps_from_bitget(
                store=store,
                audit=audit,
                product_type=settings.product_type,
                write=write,
                rate_limit_per_second=rate_limit_per_second,
            )
        )
    except duckdb.IOException as exc:
        console.print(f"[red]service store locked[/red] {exc}")
        raise typer.Exit(code=3) from exc
    payload = result.to_dict()
    _write_or_print_json(payload, output)
    api_errors = sum(1 for item in result.symbols if item.api_error is not None)
    upserted = sum(item.upserted_count for item in result.symbols)
    mode = "write" if write else "dry-run"
    console.print(
        "[green]service gap repair complete[/green] "
        f"mode={mode} symbols={len(result.symbols)} upserted={upserted} apiErrors={api_errors}"
    )


@app.command()
def backfill(
    symbols: Annotated[str, typer.Option("--symbols", help="Comma-separated symbols.")],
    granularity: Annotated[str, typer.Option("--granularity")] = "1m",
    limit: Annotated[int, typer.Option("--limit", min=1, max=MAX_BACKFILL_LIMIT)] = 200,
    concurrency: Annotated[int, typer.Option("--concurrency", min=1)] = 8,
) -> None:
    """Backfill explicit symbols into the local service store."""
    if granularity != "1m":
        console.print("[red]unsupported granularity[/red] only 1m is supported")
        raise typer.Exit(code=2)
    symbol_list = normalize_symbols(symbols.split(","))
    if not symbol_list:
        console.print("[red]symbols required[/red] pass --symbols BTCUSDT,ETHUSDT")
        raise typer.Exit(code=2)

    result = asyncio.run(backfill_1m_from_bitget(Settings(), symbol_list, limit, concurrency))
    error_count = sum(1 for item in result.symbols if item.error)
    console.print(
        "[green]backfill written[/green] "
        f"granularity={result.granularity} "
        f"symbols={len(result.symbols)} "
        f"candles={result.saved_count} "
        f"errors={error_count}"
    )
    if error_count:
        raise typer.Exit(code=3)


@app.command()
def bootstrap(
    template: Annotated[str, typer.Option("--template")] = "balanced",
    max_symbols: Annotated[int | None, typer.Option("--max-symbols", min=1)] = None,
) -> None:
    """Bootstrap instruments and tickers into the local service store."""
    result = asyncio.run(bootstrap_universe_from_bitget(Settings(), template, max_symbols))
    stream_plan = build_subscription_plan(
        result.valid_symbols,
        product_type=result.product_type,
    )
    preview = ",".join(result.selected_symbols[:10])
    console.print(
        "[green]bootstrap written[/green] "
        f"template={result.template} "
        f"contracts={result.fetched_contract_count} "
        f"tickers={result.fetched_ticker_count} "
        f"selected={len(result.selected_symbols)} "
        f"valid={len(result.valid_symbols)} "
        f"streamChannels={stream_plan.channel_count} "
        f"streamShards={stream_plan.shard_count} "
        f"symbols={preview}"
    )


@app.command("ws-smoke")
def ws_smoke(
    symbols: Annotated[str, typer.Option("--symbols", help="Comma-separated symbols.")],
    records: Annotated[int, typer.Option("--records", min=1)] = 2,
    timeout_sec: Annotated[float, typer.Option("--timeout-sec", min=1.0)] = 15.0,
) -> None:
    """Connect to Bitget public WebSocket, ingest limited records, then exit."""
    symbol_list = normalize_symbols(symbols.split(","))
    if not symbol_list:
        console.print("[red]symbols required[/red] pass --symbols BTCUSDT,ETHUSDT")
        raise typer.Exit(code=2)

    try:
        result = asyncio.run(ws_smoke_from_bitget(Settings(), symbol_list, records, timeout_sec))
    except TimeoutError as exc:
        console.print(f"[red]ws-smoke timeout[/red] records={records} timeoutSec={timeout_sec}")
        raise typer.Exit(code=4) from exc
    console.print(
        "[green]ws-smoke ingested[/green] "
        f"payloads={result.payload_count} "
        f"tickers={result.ticker_count} "
        f"candles1m={result.candle_1m_count}"
    )


@app.command()
def scan(
    source: Annotated[SourceMode, typer.Option("--source")] = SourceMode.FIXTURE,
    fixture_set: Annotated[str, typer.Option("--fixture-set")] = "basic",
    template: Annotated[str, typer.Option("--template")] = "balanced",
) -> None:
    """Build and publish a local scanner snapshot."""
    settings = Settings()
    try:
        snapshot = run_scan_cycle(
            source=source,
            template=template,
            fixture_set=fixture_set,
            providers=build_providers(settings),
            writer=build_snapshot_writer(settings),
            cache=build_snapshot_cache(settings),
        )
    except NotImplementedError as exc:
        console.print(f"[red]source unavailable[/red] {exc}")
        raise typer.Exit(code=2) from exc
    except FileNotFoundError as exc:
        console.print(f"[red]source unavailable[/red] {exc}")
        raise typer.Exit(code=2) from exc
    except DuckDbSnapshotCacheLockError as exc:
        console.print(f"[red]cache locked[/red] {exc}")
        raise typer.Exit(code=3) from exc
    console.print(
        "[green]snapshot written[/green] "
        f"source={snapshot.source.data_source.value} "
        f"status={snapshot.snapshot_status.value} "
        f"rows={len(snapshot.rows)} "
        f"path={settings.latest_snapshot_path}"
    )


@app.command()
def show(
    source_file: Annotated[Path | None, typer.Option("--source-file")] = None,
    category: Annotated[Category | None, typer.Option("--category")] = None,
) -> None:
    """Show rows from a snapshot JSON file."""
    source_file = source_file or Settings().latest_snapshot_path
    snapshot = SnapshotDTO.model_validate(json.loads(source_file.read_text(encoding="utf-8")))
    rows = [row for row in snapshot.rows if category is None or row.category == category]
    table = Table(title=f"{snapshot.run_id} {snapshot.snapshot_status.value}")
    table.add_column("symbol")
    table.add_column("category")
    table.add_column("score", justify="right")
    table.add_column("label")
    table.add_column("quality")
    for row in rows:
        table.add_row(
            row.symbol,
            row.category.value,
            f"{row.attention_score:.1f}",
            row.label,
            row.data_quality.value,
        )
    console.print(table)


@app.command("detect-rekindle")
def detect_rekindle(
    lookback_days: Annotated[int, typer.Option("--lookback-days")] = DEFAULT_LOOKBACK_DAYS,
    min_abs_change_pct: Annotated[
        float, typer.Option("--min-abs-change-pct")
    ] = DEFAULT_MIN_ABS_CHANGE_PCT,
    min_turnover_usdt: Annotated[
        float, typer.Option("--min-turnover-usdt")
    ] = DEFAULT_MIN_TURNOVER_USDT,
    now_ms: Annotated[int | None, typer.Option("--now-ms", hidden=True)] = None,
) -> None:
    """Write automatic past notes from stored 5m candle history."""
    settings = Settings()
    try:
        result = detect_rekindle_notes(
            cache=build_snapshot_cache(settings),
            past_notes=PastNoteRepository(settings.past_notes_dir),
            now_ms=now_ms,
            lookback_days=lookback_days,
            min_abs_change_pct=min_abs_change_pct,
            min_turnover_usdt=min_turnover_usdt,
        )
    except DuckDbSnapshotCacheLockError as exc:
        console.print(f"[red]cache locked[/red] {exc}")
        raise typer.Exit(code=3) from exc
    console.print(
        f"[green]自動注記検出[/green] {result.written_count}件 path={result.current_path}"
    )


@app.command("export-schema")
def export_schema(
    out: Annotated[Path, typer.Option("--out")] = Path(
        "../../schemas/scanner-snapshot.schema.json"
    ),
) -> None:
    """Export the scanner snapshot JSON Schema from Pydantic DTOs."""
    export_snapshot_schema(out)
    console.print(f"[green]schema written[/green] {out}")


def _diagnostics_line(diagnostics: ServiceDiagnostics) -> str:
    schema = "ready" if diagnostics.schema_ready else "missing"
    latest = (
        str(diagnostics.latest_candle_1m_ts_ms)
        if diagnostics.latest_candle_1m_ts_ms is not None
        else "none"
    )
    return (
        f"schema={schema} "
        f"instruments={diagnostics.instrument_count} "
        f"tickers={diagnostics.ticker_count} "
        f"candles1m={diagnostics.candle_1m_count} "
        f"streamHealth={diagnostics.stream_health_count} "
        f"latestCandle1mTs={latest}"
    )


def _runtime_paths_line(settings: Settings) -> str:
    return (
        f"stateDir={settings.state_dir} "
        f"snapshotPath={settings.latest_snapshot_path} "
        f"databasePath={settings.cache_db_path}"
    )


def _service_run_line(result: ServiceRunResult) -> str:
    return (
        f"template={result.bootstrap.template} "
        f"selected={len(result.bootstrap.selected_symbols)} "
        f"valid={len(result.bootstrap.valid_symbols)} "
        f"streamSymbols={result.subscription.symbol_count} "
        f"streamChannels={result.subscription.channel_count} "
        f"streamShards={result.subscription.shard_count} "
        f"payloads={result.stream.payload_count} "
        f"tickers={result.stream.ticker_count} "
        f"candles1m={result.stream.candle_1m_count}"
    )


async def backfill_1m_from_bitget(
    settings: Settings,
    symbols: list[str],
    limit: int,
    concurrency: int = 8,
) -> BackfillResult:
    store = build_service_store(settings)
    async with BitgetPublicClient() as client:

        async def fetcher(
            symbol: str,
            product_type: str,
            granularity: str,
            limit: int,
        ):
            return await fetch_recent_history_candles(
                client,
                symbol,
                product_type,
                granularity=granularity,
                limit=limit,
            )

        return await backfill_1m_candles(
            store=store,
            fetcher=fetcher,
            symbols=symbols,
            product_type=settings.product_type,
            limit=limit,
            concurrency=concurrency,
        )


async def repair_service_gaps_from_bitget(
    *,
    store: Any,
    audit: Any,
    product_type: str,
    write: bool,
    rate_limit_per_second: float,
):
    if not write:

        async def dry_run_fetcher(
            symbol: str,
            product_type: str,
            granularity: str,
            start_ts_ms: int,
            end_ts_ms: int,
        ):
            _ = (symbol, product_type, granularity, start_ts_ms, end_ts_ms)
            return []

        return await repair_service_gaps(
            store=store,
            fetcher=dry_run_fetcher,
            audit=audit,
            product_type=product_type,
            write=False,
        )

    async with BitgetPublicClient(rate_limit_per_second=rate_limit_per_second) as client:

        async def fetcher(
            symbol: str,
            product_type: str,
            granularity: str,
            start_ts_ms: int,
            end_ts_ms: int,
        ):
            return await fetch_history_candles_range(
                client,
                symbol,
                product_type,
                granularity=granularity,
                start_ms=start_ts_ms,
                end_ms=end_ts_ms,
            )

        return await repair_service_gaps(
            store=store,
            fetcher=fetcher,
            audit=audit,
            product_type=product_type,
            write=write,
        )


async def bootstrap_universe_from_bitget(
    settings: Settings,
    template: str,
    max_symbols: int | None,
) -> BootstrapResult:
    config = load_template(settings.config_dir, template)
    store = build_service_store(settings)

    class BitgetUniverseFetcher:
        def __init__(self, client: BitgetPublicClient) -> None:
            self.client = client

        async def fetch_contracts(self, product_type: str):
            return await fetch_contracts(self.client, product_type)

        async def fetch_tickers(self, product_type: str):
            return await fetch_all_tickers(self.client, product_type)

    async with BitgetPublicClient() as client:
        return await bootstrap_universe(
            store=store,
            fetcher=BitgetUniverseFetcher(client),
            config=config,
            template=template,
            max_symbols=max_symbols,
        )


async def ws_smoke_from_bitget(
    settings: Settings,
    symbols: list[str],
    records: int,
    timeout_sec: float,
) -> WsStreamIngestResult:
    store = build_service_store(settings)
    specs = build_channel_specs(symbols, inst_type=settings.product_type)
    async with asyncio.timeout(timeout_sec):
        return await ingest_ws_payload_stream(
            store,
            stream_public_payloads(specs),
            max_records=records,
        )


async def run_service_from_bitget(
    settings: Settings,
    *,
    template: str,
    universe: str,
    max_symbols: int | None,
    shard_channels: int,
    backfill_limit: int,
    backfill_concurrency: int,
    await_backfill: bool,
    reconcile_interval_sec: float,
    reconcile_limit: int,
    reconcile_concurrency: int,
    ticker_refresh_interval_sec: float,
    watchdog_interval_sec: float,
    watchdog_stall_sec: float,
    watchdog_confirmations: int,
    watchdog_startup_grace_sec: float,
    deep_backfill_limit: int,
    deep_backfill_batch_size: int,
    deep_backfill_concurrency: int,
    deep_backfill_cooldown_sec: float,
    deep_backfill_retry_delay_sec: float,
    deep_backfill_rate_limit_per_second: float,
    stop_after_records: int | None,
) -> ServiceRunResult:
    config = load_template(settings.config_dir, template)
    vpi_config = load_vpi_config(settings.vpi_config_path)
    store = build_service_store(settings)
    watchdog_config = ServiceWatchdogConfig(
        interval_seconds=watchdog_interval_sec,
        stall_seconds=watchdog_stall_sec,
        confirmations=watchdog_confirmations,
        startup_grace_seconds=watchdog_startup_grace_sec,
    )

    class BitgetUniverseFetcher:
        def __init__(self, client: BitgetPublicClient) -> None:
            self.client = client

        async def fetch_contracts(self, product_type: str):
            return await fetch_contracts(self.client, product_type)

        async def fetch_tickers(self, product_type: str):
            return await fetch_all_tickers(self.client, product_type)

    async with BitgetPublicClient() as client:
        bootstrap_result = await bootstrap_universe(
            store=store,
            fetcher=BitgetUniverseFetcher(client),
            config=config,
            template=template,
            max_symbols=max_symbols,
        )

    stream_symbols = (
        bootstrap_result.valid_symbols if universe == "all" else bootstrap_result.selected_symbols
    )
    if max_symbols is not None:
        stream_symbols = stream_symbols[:max_symbols]
    subscription = build_subscription_plan(
        stream_symbols,
        product_type=bootstrap_result.product_type,
        max_channels=shard_channels,
    )
    if not subscription.shards:
        raise ValueError("no stream symbols selected")

    stop_event = _install_stop_signal_handlers()
    state_writer = build_service_state_writer(settings)
    snapshot_writer = build_service_snapshot_writer(settings)
    snapshot_cache = build_snapshot_cache(settings)
    ticker_collector = TickerRuntimeCollector(store.load_ticker_latest())
    ticker_writer = build_ticker_runtime_writer(settings)
    market_comparison_collector = MarketComparisonCollector()
    perp_venue_comparison_collector = PerpVenueComparisonCollector()
    ticker_refresh_task = (
        asyncio.create_task(
            _run_service_ticker_refresh_from_bitget(
                store=store,
                product_type=bootstrap_result.product_type,
                interval_seconds=ticker_refresh_interval_sec,
                ticker_sink=ticker_collector.record,
            )
        )
        if ticker_refresh_interval_sec > 0
        else None
    )
    backfill_tracker = (
        BackfillProgressTracker(
            stream_symbols,
            limit=backfill_limit,
            concurrency=backfill_concurrency,
        )
        if backfill_limit > 0
        else None
    )

    def backfill_progress():
        return backfill_tracker.snapshot() if backfill_tracker is not None else None

    reconcile_tracker_lock = RLock()
    reconcile_tracker: BackfillProgressTracker | None = None

    def set_reconcile_tracker(tracker: BackfillProgressTracker | None) -> None:
        nonlocal reconcile_tracker
        with reconcile_tracker_lock:
            reconcile_tracker = tracker

    def reconcile_progress():
        with reconcile_tracker_lock:
            return reconcile_tracker.snapshot() if reconcile_tracker is not None else None

    deep_backfill_tracker = (
        DeepBackfillProgressTracker(
            stream_symbols,
            target_limit=deep_backfill_limit,
            batch_size=deep_backfill_batch_size,
            concurrency=deep_backfill_concurrency,
            rate_limit_per_second=deep_backfill_rate_limit_per_second,
            cooldown_seconds=deep_backfill_cooldown_sec,
            retry_delay_seconds=deep_backfill_retry_delay_sec,
        )
        if deep_backfill_limit > 0
        else None
    )

    def deep_backfill_progress():
        return deep_backfill_tracker.snapshot() if deep_backfill_tracker is not None else None

    initial_comparison_started_at = time.monotonic()
    await asyncio.gather(
        refresh_market_comparison_once(market_comparison_collector),
        refresh_perp_venue_comparison_once(perp_venue_comparison_collector),
    )
    initial_perp_venue_comparison = perp_venue_comparison_collector.snapshot()
    if initial_perp_venue_comparison is not None:
        _log_perp_venue_comparison_refresh(
            initial_perp_venue_comparison,
            time.monotonic() - initial_comparison_started_at,
        )
    publish_service_state_once(
        store,
        state_writer,
        product_type=bootstrap_result.product_type,
        subscription=subscription,
        backfill=backfill_progress(),
        reconcile=reconcile_progress(),
        deep_backfill=deep_backfill_progress(),
    )
    publish_service_snapshot_once(
        store,
        snapshot_writer,
        snapshot_cache,
        template=template,
        config=config,
        vpi_config=vpi_config,
        market_comparison=market_comparison_collector.snapshot(),
        perp_venue_comparison=perp_venue_comparison_collector.snapshot(),
    )
    publish_ticker_runtime_once(ticker_collector, ticker_writer)
    publish_task = (
        asyncio.create_task(
            publish_service_state_periodically(
                store,
                state_writer,
                product_type=bootstrap_result.product_type,
                subscription=subscription,
                interval_seconds=settings.service_publish_interval_seconds,
                publish_immediately=False,
                backfill_provider=backfill_progress,
                reconcile_provider=reconcile_progress,
                deep_backfill_provider=deep_backfill_progress,
            )
        )
        if settings.service_publish_interval_seconds > 0
        else None
    )
    snapshot_task = (
        asyncio.create_task(
            publish_service_snapshot_periodically(
                store,
                snapshot_writer,
                snapshot_cache,
                template=template,
                config=config,
                vpi_config=vpi_config,
                market_comparison_provider=market_comparison_collector.snapshot,
                perp_venue_comparison_provider=perp_venue_comparison_collector.snapshot,
                interval_seconds=settings.service_publish_interval_seconds,
                publish_immediately=False,
            )
        )
        if settings.service_publish_interval_seconds > 0
        else None
    )
    market_comparison_task = asyncio.create_task(
        refresh_market_comparison_periodically(
            market_comparison_collector,
            interval_seconds=MARKET_COMPARISON_INTERVAL_SECONDS,
            refresh_immediately=False,
        )
    )
    perp_venue_comparison_task = asyncio.create_task(
        refresh_perp_venue_comparison_periodically(
            perp_venue_comparison_collector,
            interval_seconds=PERP_VENUE_COMPARISON_INTERVAL_SECONDS,
            refresh_immediately=False,
            on_refresh=_log_perp_venue_comparison_refresh,
            on_error=lambda exc: logger.warning(
                "perp venue comparison refresh failed: {}: {}",
                type(exc).__name__,
                str(exc)[:200],
            ),
        )
    )
    ticker_task = (
        asyncio.create_task(
            publish_ticker_runtime_periodically(
                ticker_collector,
                ticker_writer,
                interval_seconds=settings.ticker_publish_interval_seconds,
                publish_immediately=False,
            )
        )
        if settings.ticker_publish_interval_seconds > 0
        else None
    )

    def payload_source(
        specs: Sequence[ChannelSpec],
    ) -> AsyncIterable[Mapping[str, Any]]:
        return stream_public_payloads(specs)

    async def latest_candle_provider() -> int | None:
        diagnostics = await asyncio.to_thread(store.diagnostics)
        return diagnostics.latest_candle_1m_ts_ms

    async def upstream_probe() -> bool:
        return await _probe_service_upstream_from_bitget(
            symbol=stream_symbols[0],
            product_type=bootstrap_result.product_type,
        )

    backfill_task = (
        asyncio.create_task(
            _run_service_backfill_from_bitget(
                store=store,
                symbols=stream_symbols,
                product_type=bootstrap_result.product_type,
                limit=backfill_limit,
                concurrency=backfill_concurrency,
                tracker=backfill_tracker,
            )
        )
        if backfill_tracker is not None
        else None
    )
    reconcile_task = (
        asyncio.create_task(
            _run_service_reconcile_loop_from_bitget(
                store=store,
                symbols=stream_symbols,
                product_type=bootstrap_result.product_type,
                interval_seconds=reconcile_interval_sec,
                limit=reconcile_limit,
                concurrency=reconcile_concurrency,
                set_tracker=set_reconcile_tracker,
                blocked_by_tracker=backfill_tracker,
            )
        )
        if reconcile_interval_sec > 0
        else None
    )
    deep_backfill_task = (
        asyncio.create_task(
            _run_service_deep_backfill_from_bitget(
                store=store,
                symbols=stream_symbols,
                product_type=bootstrap_result.product_type,
                target_limit=deep_backfill_limit,
                batch_size=deep_backfill_batch_size,
                concurrency=deep_backfill_concurrency,
                cooldown_seconds=deep_backfill_cooldown_sec,
                retry_delay_seconds=deep_backfill_retry_delay_sec,
                rate_limit_per_second=deep_backfill_rate_limit_per_second,
                tracker=deep_backfill_tracker,
                blocked_by=lambda: _tracker_is_running(backfill_tracker),
            )
        )
        if deep_backfill_tracker is not None
        else None
    )

    try:
        if await_backfill and backfill_task is not None:
            assert backfill_tracker is not None
            await backfill_task
            progress = backfill_tracker.snapshot()
            if progress.status == "failed":
                raise ValueError(f"service backfill failed {progress.latest_error or ''}".strip())
            publish_service_state_once(
                store,
                state_writer,
                product_type=bootstrap_result.product_type,
                subscription=subscription,
                backfill=backfill_progress(),
                reconcile=reconcile_progress(),
                deep_backfill=deep_backfill_progress(),
            )
            publish_service_snapshot_once(
                store,
                snapshot_writer,
                snapshot_cache,
                template=template,
                config=config,
                vpi_config=vpi_config,
                market_comparison=market_comparison_collector.snapshot(),
                perp_venue_comparison=perp_venue_comparison_collector.snapshot(),
            )
        watchdog_coro = (
            run_service_watchdog(
                latest_candle_provider=latest_candle_provider,
                upstream_probe=upstream_probe,
                config=watchdog_config,
            )
            if watchdog_config.interval_seconds > 0
            else None
        )
        stream_result = await _run_service_until_stopped(
            ingest_ws_shards(
                store,
                subscription.shards,
                payload_source_factory=payload_source,
                max_records_per_shard=stop_after_records,
                ticker_sink=ticker_collector,
            ),
            watchdog_coro,
            stop_event=stop_event,
        )
    finally:
        await _cancel_service_tasks(
            publish_task,
            snapshot_task,
            ticker_task,
            ticker_refresh_task,
            market_comparison_task,
            perp_venue_comparison_task,
            backfill_task,
            reconcile_task,
            deep_backfill_task,
        )
        publish_service_state_once(
            store,
            state_writer,
            product_type=bootstrap_result.product_type,
            subscription=subscription,
            backfill=backfill_progress(),
            reconcile=reconcile_progress(),
            deep_backfill=deep_backfill_progress(),
        )
    return ServiceRunResult(
        bootstrap=bootstrap_result,
        subscription=subscription,
        stream=stream_result,
    )


def _log_perp_venue_comparison_refresh(
    block: dict[str, object],
    duration_seconds: float,
) -> None:
    raw_items = block.get("items")
    items = raw_items if isinstance(raw_items, list) else []
    status_counts = {
        status: sum(isinstance(item, dict) and item.get("status") == status for item in items)
        for status in ("ready", "partial", "unavailable")
    }
    raw_sources = block.get("sources")
    sources = raw_sources if isinstance(raw_sources, list) else []
    logger.info(
        "perp venue comparison refreshed: items={} ready={} partial={} unavailable={} "
        "sources={} durationMs={:.0f}",
        len(items),
        status_counts["ready"],
        status_counts["partial"],
        status_counts["unavailable"],
        json.dumps(sources, ensure_ascii=False, separators=(",", ":")),
        duration_seconds * 1_000,
    )


async def _run_service_backfill_from_bitget(
    *,
    store: Any,
    symbols: list[str],
    product_type: str,
    limit: int,
    concurrency: int,
    tracker: BackfillProgressTracker,
) -> BackfillResult | None:
    try:
        async with BitgetPublicClient() as client:

            async def fetcher(
                symbol: str,
                product_type: str,
                granularity: str,
                limit: int,
            ):
                return await fetch_recent_history_candles(
                    client,
                    symbol,
                    product_type,
                    granularity=granularity,
                    limit=limit,
                )

            result = await backfill_1m_candles(
                store=store,
                fetcher=fetcher,
                symbols=symbols,
                product_type=product_type,
                limit=limit,
                concurrency=concurrency,
                on_symbol_result=tracker.record_symbol,
            )
    except asyncio.CancelledError:
        tracker.mark_cancelled()
        raise
    except Exception as exc:
        tracker.mark_failed(f"{type(exc).__name__}: {exc}")
        return None

    errors = [item for item in result.symbols if item.error]
    if errors:
        preview = ", ".join(f"{item.symbol}: {item.error}" for item in errors[:3])
        tracker.mark_failed(f"symbols={len(errors)} {preview}")
    else:
        tracker.mark_completed()
    return result


async def _run_service_ticker_refresh_from_bitget(
    *,
    store: Any,
    product_type: str,
    interval_seconds: float,
    ticker_sink: Callable[[list[TickerLatestRecord]], None],
) -> None:
    async with BitgetPublicClient() as client:

        async def fetcher(product_type: str):
            return await fetch_all_tickers(client, product_type)

        await refresh_ticker_latest_periodically(
            store=store,
            fetcher=fetcher,
            product_type=product_type,
            interval_seconds=interval_seconds,
            publish_immediately=False,
            ticker_sink=ticker_sink,
            on_error=lambda exc: logger.warning(
                "public ticker refresh failed: {}", type(exc).__name__
            ),
        )


async def _run_service_deep_backfill_from_bitget(
    *,
    store: Any,
    symbols: list[str],
    product_type: str,
    target_limit: int,
    batch_size: int,
    concurrency: int,
    cooldown_seconds: float,
    retry_delay_seconds: float,
    rate_limit_per_second: float,
    tracker: DeepBackfillProgressTracker,
    blocked_by: Callable[[], bool] | None,
) -> BackfillResult | None:
    try:
        async with BitgetPublicClient(rate_limit_per_second=rate_limit_per_second) as client:

            async def fetcher(
                symbol: str,
                product_type: str,
                granularity: str,
                limit: int,
            ):
                return await fetch_recent_history_candles(
                    client,
                    symbol,
                    product_type,
                    granularity=granularity,
                    limit=limit,
                )

            return await run_deep_backfill_worker(
                store=store,
                fetcher=fetcher,
                symbols=symbols,
                product_type=product_type,
                target_limit=target_limit,
                batch_size=batch_size,
                concurrency=concurrency,
                cooldown_seconds=cooldown_seconds,
                retry_delay_seconds=retry_delay_seconds,
                tracker=tracker,
                blocked_by=blocked_by,
            )
    except asyncio.CancelledError:
        if tracker.snapshot().status == "running":
            tracker.mark_cancelled()
        raise
    except Exception as exc:
        tracker.mark_failed(f"{type(exc).__name__}: {exc}")
        return None


async def _run_service_until_stopped(
    stream_coro: Coroutine[Any, Any, WsShardIngestResult],
    watchdog_coro: Coroutine[Any, Any, None] | None,
    *,
    stop_event: asyncio.Event | None,
) -> WsShardIngestResult:
    stream_task = asyncio.create_task(stream_coro)
    watchdog_task = asyncio.create_task(watchdog_coro) if watchdog_coro is not None else None
    stop_task = asyncio.create_task(stop_event.wait()) if stop_event is not None else None
    wait_tasks: set[asyncio.Task[Any]] = {stream_task}
    if watchdog_task is not None:
        wait_tasks.add(watchdog_task)
    if stop_task is not None:
        wait_tasks.add(stop_task)
    try:
        done, _pending = await asyncio.wait(
            wait_tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if stop_task is not None and stop_task in done:
            stop_task.result()
            await _cancel_service_task(stream_task)
            await _cancel_service_task(watchdog_task)
            raise KeyboardInterrupt
        if watchdog_task is not None and watchdog_task in done:
            await _cancel_service_task(stream_task)
            await watchdog_task
            raise RuntimeError("service watchdog stopped unexpectedly")
        await _cancel_service_task(watchdog_task)
        return await stream_task
    finally:
        await _cancel_service_tasks(stream_task, watchdog_task, stop_task)


async def _cancel_service_task(task: asyncio.Task[Any] | None) -> None:
    if task is None or task.done():
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def _cancel_service_tasks(*tasks: asyncio.Task[Any] | None) -> None:
    present = [task for task in tasks if task is not None]
    pending = [task for task in present if not task.done()]
    for task in pending:
        task.cancel()
    results = await asyncio.gather(*present, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
            raise result


async def _probe_service_upstream_from_bitget(*, symbol: str, product_type: str) -> bool:
    async with BitgetPublicClient() as client:
        candles = await fetch_recent_history_candles(
            client,
            symbol,
            product_type,
            granularity="1m",
            limit=1,
        )
    return bool(candles)


def _install_stop_signal_handlers() -> asyncio.Event | None:
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    installed = False
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
            loop.add_signal_handler(sig, stop_event.set)
            installed = True
    return stop_event if installed else None


async def _run_service_reconcile_loop_from_bitget(
    *,
    store: Any,
    symbols: list[str],
    product_type: str,
    interval_seconds: float,
    limit: int,
    concurrency: int,
    set_tracker: Callable[[BackfillProgressTracker | None], None],
    blocked_by_tracker: BackfillProgressTracker | None,
) -> None:
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    current_tracker: BackfillProgressTracker | None = None
    try:
        while True:
            if _tracker_is_running(blocked_by_tracker):
                await asyncio.sleep(interval_seconds)
                continue
            stale_symbols = await asyncio.to_thread(
                select_reconcile_symbols,
                store,
                symbols,
                window_limit=limit,
            )
            current_tracker = BackfillProgressTracker(
                stale_symbols,
                limit=limit,
                concurrency=concurrency,
            )
            set_tracker(current_tracker)
            if not stale_symbols:
                current_tracker.mark_completed()
                current_tracker = None
                await asyncio.sleep(interval_seconds)
                continue
            await _run_service_backfill_from_bitget(
                store=store,
                symbols=stale_symbols,
                product_type=product_type,
                limit=limit,
                concurrency=concurrency,
                tracker=current_tracker,
            )
            current_tracker = None
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        if current_tracker is not None and current_tracker.snapshot().status == "running":
            current_tracker.mark_cancelled()
        raise


def _tracker_is_running(tracker: BackfillProgressTracker | None) -> bool:
    return tracker is not None and tracker.snapshot().status == "running"


def _write_or_print_json(payload: dict[str, object], output: Path | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if output is None:
        console.print(text)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text + "\n", encoding="utf-8")
