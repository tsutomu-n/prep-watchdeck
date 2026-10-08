"""Hostile input boundaries, using the actual Market and Ranking contracts."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from aiohttp import web
from prep_watchdeck_market.artifacts import (
    ArtifactFileStatus,
    CatalogProvenanceArtifact,
    FreshnessArtifact,
    MarketServiceStateArtifact,
    ParityAssumption,
    ReferenceMarkMedianArtifact,
    UniverseInstrumentArtifact,
    UniverseSnapshotArtifact,
)
from prep_watchdeck_market.market_metrics import MarketMetricRow, MarketMetricsArtifact, MetricValue
from prep_watchdeck_market.models import Venue
from prep_watchdeck_ranking.models import (
    Coverage,
    Indicator,
    OriginalInstrument,
    RankedRow,
    RankingResponse,
    RankingWindow,
    Reference,
    RosterHealth,
    TurnoverComparison,
    TurnoverWindow,
    Widget,
)

from prep_watchdeck_attention.identity import join_attention_assets
from prep_watchdeck_attention.market_input import (
    MarketInputBundle,
    MarketInputError,
    read_market_inputs,
)
from prep_watchdeck_attention.ranking_input import (
    CANONICAL_RANKING_QUERY,
    RankingInputError,
    RankingInputReader,
)
from prep_watchdeck_attention.stable_files import StableFileError, read_stable_regular_file

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
MS = int(NOW.timestamp() * 1000)


def instrument(venue: Venue = "bitget", mark=100.0, version=1):
    return UniverseInstrumentArtifact(
        venue_instrument_id=f"{venue}:BTC",
        venue_instrument_version_id=version,
        group_id="BTC",
        mapping_method="verified",
        venue=venue,
        source_symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        settle_asset="USDT",
        collateral_asset=None,
        active=True,
        market_type="linear_perpetual",
        execution_model="orderbook",
        catalog=CatalogProvenanceArtifact(
            source_kind="fixture",
            endpoint="fixture",
            documentation_url=None,
            payload_hash="fixture",
            observed_at=NOW,
            source_at=NOW,
        ),
        quality="ready",
        quality_reasons=(),
        age_seconds=0,
        collector_run_id="run",
        cycle_at=NOW,
        observed_at=NOW,
        source_at=NOW,
        source_payload_hash="fixture",
        error_code=None,
        mark_price=mark,
        reference_price=mark,
        reference_price_kind="index",
        best_bid=99,
        best_ask=101,
        funding_rate_raw=0.0008,
        funding_interval_seconds=28800,
        funding_rate_per_hour=0.0001,
        next_funding_at=NOW + timedelta(hours=1),
        open_interest_raw=100,
        open_interest_raw_unit="base",
        open_interest_base=100,
        open_interest_notional=10000,
        volume_24h_raw=100000,
        volume_24h_unit="contracts",
        reference_mark_median=ReferenceMarkMedianArtifact(
            status="ready",
            value=mark,
            venue_count=1,
            venues=(venue,),
            cycle_at=NOW,
            unavailable_reason=None,
            parity_assumption_code="usd_usdc_usdt_reference_only",
        ),
    )


def metric(value=0.0, *, unit="base", finality=None):
    return MetricValue(
        value=value,
        availability="available",
        reason_code=None,
        start_at=NOW - timedelta(minutes=15),
        end_at=NOW,
        start_value=100,
        end_value=100 + value,
        start_source_at=NOW - timedelta(minutes=15),
        start_observed_at=NOW - timedelta(minutes=15),
        end_source_at=NOW,
        end_observed_at=NOW,
        end_finality=finality,
        unit=unit,
    )


def metric_row(venue="bitget", value=0.0):
    return MarketMetricRow(
        venue_instrument_id=f"{venue}:BTC",
        venue_instrument_version_id=1,
        venue=venue,
        source_symbol="BTCUSDT",
        quote_asset="USDT",
        settle_asset="USDT",
        price_tick=None,
        oi_change={k: metric(value) for k in ("15m", "1h")},
        trade_change={
            k: metric(value, unit="USDT", finality="confirmed") for k in ("15m", "1h", "24h")
        },
    )


def bundle(items=None, rows=()):
    universe = UniverseSnapshotArtifact(
        schema_version=1,
        generated_at=NOW,
        status="ready",
        quality_reasons=(),
        parity_assumption=ParityAssumption(
            code="usd_usdc_usdt_reference_only",
            applied_to="reference_mark_median_only",
            statement="fixture",
        ),
        items=tuple(items or (instrument(),)),
    )
    fresh = FreshnessArtifact(
        status="ready", latest_at=NOW, age_seconds=0, max_age_seconds=120, error_code=None
    )
    service = MarketServiceStateArtifact(
        schema_version=1,
        generated_at=NOW,
        status="ready",
        quality_reasons=(),
        collectors=(),
        catalog=fresh,
        l1=fresh,
        artifacts=(
            ArtifactFileStatus(
                name="universe-snapshot.json", status="ready", generated_at=NOW, error_code=None
            ),
        ),
    )
    metrics = MarketMetricsArtifact(
        generation_id="metrics",
        generated_at=NOW,
        candle_cutoff=NOW - timedelta(minutes=3),
        rows=tuple(rows),
    )
    return MarketInputBundle(service, universe, metrics, None)


def ranked(originals=None):
    window = TurnoverWindow(anchor=MS - 900000, cutoff=MS, quote_turnover=100, status="ready")
    return RankedRow(
        id="asset:BTC",
        asset="BTC",
        mapping_status="verified",
        venues=("bitget",),
        originals=tuple(
            originals
            or (
                OriginalInstrument(
                    venue="bitget",
                    instrument_id="bitget:BTC",
                    version_id=1,
                    symbol="BTCUSDT",
                    base_asset="BTC",
                    multiplier=1,
                ),
            )
        ),
        reference=Reference(
            provider="bybit", symbol="BTCUSDT", base_asset="BTC", multiplier=1, revision="v1"
        ),
        widget=Widget(status="unsupported", symbol=None, reason="fixture", evidence=("fixture",)),
        state="ready",
        reason=None,
        return_pct=3,
        quote_turnover=100,
        rank=1,
        reference_close=Indicator(value=100, status="ready"),
        windows={
            k: RankingWindow(anchor=MS - 900000, return_pct=3, quote_turnover=100, state="ready")
            for k in ("15m", "1h", "24h", "daily")
        },
        turnover_ratios={k: Indicator(value=2, status="ready") for k in ("15m", "1h")},
        day_range_position=Indicator(value=50, status="ready"),
        turnover_comparison=TurnoverComparison(
            current=window,
            previous_day=window,
            two_days_ago=window,
            previous_day_ratio=Indicator(value=1, status="ready"),
            two_days_ago_ratio=Indicator(value=1, status="ready"),
        ),
    )


def ranking(rows=None):
    return RankingResponse(
        generation_id="rank",
        map_version="map-v1",
        cutoff=MS,
        generated_at=MS,
        roster_generated_at=MS,
        roster_stale=False,
        roster_health=RosterHealth(status="ready", catalog_observed_at=MS, source_instruments=1),
        stale=False,
        status="ready",
        period="15m",
        daily_reference_jst="00:00",
        anchor=MS - 900000,
        order="turnover",
        min_turnover=0,
        coverage=Coverage(
            source_instruments=1,
            rows=1,
            crypto_rows=1,
            supported=1,
            widget_supported=0,
            valid=1,
            ranked=1,
            reasons={},
        ),
        rows=tuple(rows or (ranked(),)),
    )


def write_bundle(root: Path, data=None):
    data = data or bundle()
    artifacts = root / "artifacts"
    artifacts.mkdir()
    for name, value in (
        ("service-state", data.service),
        ("universe-snapshot", data.universe),
        ("market-metrics", data.metrics),
    ):
        if value is not None:
            (artifacts / f"{name}.json").write_text(value.model_dump_json(by_alias=True))
    return artifacts


def test_regular_and_hostile_files(tmp_path):
    path = tmp_path / "file"
    path.write_bytes(b"okay")
    assert read_stable_regular_file(path, max_bytes=4) == b"okay"
    with pytest.raises(StableFileError):
        read_stable_regular_file(path, max_bytes=3)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(StableFileError):
        read_stable_regular_file(link, max_bytes=10)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(StableFileError):
        read_stable_regular_file(fifo, max_bytes=10)
    with pytest.raises(StableFileError):
        read_stable_regular_file(tmp_path / "missing", max_bytes=10)


def test_market_optional_metrics_and_generation(tmp_path):
    artifacts = write_bundle(tmp_path)
    assert read_market_inputs(tmp_path, now=NOW).universe.generated_at == NOW
    (artifacts / "market-metrics.json").write_text("invalid")
    value = read_market_inputs(tmp_path, now=NOW)
    assert value.metrics is None and value.metrics_error
    (artifacts / "market-metrics.json").unlink()
    assert read_market_inputs(tmp_path, now=NOW).metrics_error
    with pytest.raises(MarketInputError):
        read_market_inputs(tmp_path, now=NOW + timedelta(minutes=31))
    with pytest.raises(MarketInputError):
        read_market_inputs(tmp_path, now=NOW - timedelta(seconds=1))


def test_exact_identity_and_duplicate_rejection():
    assert join_attention_assets(ranking(), bundle())[0].state == "partial"
    assert join_attention_assets(ranking(), bundle((instrument(version=2),)))[0].state == "invalid"
    assert (
        join_attention_assets(ranking(), bundle((instrument(), instrument())))[0].state == "invalid"
    )
    row = ranked().model_copy(update={"mapping_status": "review", "reference": None})
    assert join_attention_assets(ranking((row,)), bundle())[0].state == "excluded"


def test_loopback_read_one_request():
    async def run():
        requests = []

        async def handler(request):
            requests.append(dict(request.query))
            return web.json_response(ranking().model_dump(mode="json", by_alias=True))

        app = web.Application()
        app.router.add_get("/rankings", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = runner.addresses[0][1]
        try:
            result = await RankingInputReader(port=port).read(now_ms=MS)
            assert result.generation_id == "rank"
            assert requests == [dict(CANONICAL_RANKING_QUERY)]
            with pytest.raises(RankingInputError):
                await RankingInputReader(port=port).read(now_ms=MS + 150001)
        finally:
            await runner.cleanup()

    asyncio.run(run())


def test_stable_identity_change_rejected(tmp_path, monkeypatch):
    import prep_watchdeck_attention.stable_files as stable

    path = tmp_path / "changed"
    path.write_bytes(b"before")
    original_fstat = os.fstat
    calls = 0

    def changing_fstat(descriptor):
        nonlocal calls
        calls += 1
        if calls == 2:
            path.write_bytes(b"changed")
        return original_fstat(descriptor)

    monkeypatch.setattr(stable.os, "fstat", changing_fstat)
    with pytest.raises(StableFileError, match="changed"):
        read_stable_regular_file(path, max_bytes=100)


@pytest.mark.parametrize("changes,success", [(1, True), (2, False)])
def test_market_read_retries_only_once(tmp_path, monkeypatch, changes, success):
    import prep_watchdeck_attention.market_input as inputs

    write_bundle(tmp_path)
    actual = inputs.read_stable_regular_file
    service_reads = 0

    def switching(path, *, max_bytes):
        nonlocal service_reads
        raw = actual(path, max_bytes=max_bytes)
        if path.name == "service-state.json":
            service_reads += 1
            if service_reads == 2 or (changes == 2 and service_reads == 4):
                service = MarketServiceStateArtifact.model_validate_json(raw)
                return (
                    service.model_copy(update={"quality_reasons": ("switched",)})
                    .model_dump_json(by_alias=True)
                    .encode()
                )
        return raw

    monkeypatch.setattr(inputs, "read_stable_regular_file", switching)
    if success:
        assert read_market_inputs(tmp_path, now=NOW).universe.status == "ready"
    else:
        with pytest.raises(MarketInputError, match="bundle_changed"):
            read_market_inputs(tmp_path, now=NOW)
    assert service_reads == 4


def test_market_generation_mismatch(tmp_path):
    data = bundle()
    universe = data.universe.model_copy(update={"generated_at": NOW - timedelta(seconds=1)})
    write_bundle(tmp_path, MarketInputBundle(data.service, universe, data.metrics, None))
    with pytest.raises(MarketInputError, match="generation_mismatch"):
        read_market_inputs(tmp_path, now=NOW)


@pytest.mark.parametrize("kind", ["redirect", "oversize", "schema", "future"])
def test_ranking_hostile_http(kind):
    async def run():
        requests = 0

        async def handler(request):
            nonlocal requests
            requests += 1
            if kind == "redirect":
                raise web.HTTPFound("/provider")
            if kind == "oversize":
                return web.Response(body=b" " * (8 * 1024 * 1024 + 1))
            if kind == "schema":
                return web.json_response({"unknown": True})
            value = ranking().model_copy(update={"cutoff": MS + 60000, "generated_at": MS + 60000})
            return web.json_response(value.model_dump(mode="json", by_alias=True))

        app = web.Application()
        app.router.add_get("/rankings", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        port = runner.addresses[0][1]
        try:
            with pytest.raises(RankingInputError):
                await RankingInputReader(port=port).read(now_ms=MS)
            assert requests == 1
        finally:
            await runner.cleanup()

    asyncio.run(run())


def test_ranking_timeout_bound(monkeypatch):
    import prep_watchdeck_attention.ranking_input as inputs

    assert inputs.TIMEOUT_SECONDS == 5
    assert inputs.MAX_RESPONSE_BYTES == 8 * 1024 * 1024

    async def stalled(url, *, params) -> bytes:
        assert url == "http://127.0.0.1:8769/rankings"
        assert dict(params) == dict(CANONICAL_RANKING_QUERY)
        await asyncio.Future()
        raise AssertionError("unreachable")

    monkeypatch.setattr(inputs, "TIMEOUT_SECONDS", 0.01)

    async def run():
        with pytest.raises(RankingInputError):
            await RankingInputReader(port=8769, fetcher=stalled).read(now_ms=MS)

    asyncio.run(run())


def test_metrics_wrong_version_never_joins():
    item = metric_row().model_copy(update={"venue_instrument_version_id": 2})
    result = join_attention_assets(ranking(), bundle(rows=(item,)))[0]
    assert result.metrics == ()
    assert any("version_mismatch" in r for r in result.reasons)
    data = bundle(rows=(metric_row(),))
    assert data.metrics is not None
    duplicated = data.metrics.model_copy(update={"rows": (metric_row(), metric_row())})
    result = join_attention_assets(
        ranking(), MarketInputBundle(data.service, data.universe, duplicated, None)
    )[0]
    assert result.state == "invalid"


def test_required_file_changed_during_read_retries_once(tmp_path, monkeypatch):
    import prep_watchdeck_attention.market_input as inputs

    write_bundle(tmp_path)
    actual = inputs.read_stable_regular_file
    calls = 0

    def changed(path, *, max_bytes):
        nonlocal calls
        if path.name == "universe-snapshot.json":
            calls += 1
            if calls == 1:
                raise StableFileError("input_changed_during_read")
        return actual(path, max_bytes=max_bytes)

    monkeypatch.setattr(inputs, "read_stable_regular_file", changed)
    assert read_market_inputs(tmp_path, now=NOW).universe.status == "ready"
    assert calls == 2


@pytest.mark.parametrize("kind", ["duplicate", "coverage"])
def test_ranking_rejects_inconsistent_row_identity(kind):
    async def fetch(url, *, params):
        value = (
            ranking().model_copy(update={"rows": (ranked(), ranked())})
            if kind == "duplicate"
            else ranking().model_copy(
                update={"coverage": ranking().coverage.model_copy(update={"rows": 2})}
            )
        )
        return value.model_dump_json(by_alias=True).encode()

    async def run():
        with pytest.raises(RankingInputError, match="row_identity"):
            await RankingInputReader(port=8769, fetcher=fetch).read(now_ms=MS)

    asyncio.run(run())
