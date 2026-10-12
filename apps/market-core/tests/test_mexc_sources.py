import copy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from prep_watchdeck_market.identity import resolve_market_groups
from prep_watchdeck_market.selected_market import (
    SelectedContractError,
    SelectedDepth,
    SelectedTrade,
)
from prep_watchdeck_market.sources.common import require_mapping
from prep_watchdeck_market.sources.mexc import parse_mexc_catalog
from prep_watchdeck_market.sources.mexc_candles import parse_mexc_history
from prep_watchdeck_market.sources.mexc_l1 import parse_mexc_l1
from prep_watchdeck_market.sources.mexc_selected import MexcSelectedState

NOW = datetime(2026, 10, 10, tzinfo=UTC)


def definition(symbol="BTC_USDT", base="BTC", size="0.0001"):
    return {
        "symbol": symbol,
        "baseCoin": base,
        "quoteCoin": "USDT",
        "settleCoin": "USDT",
        "futureType": 1,
        "state": 0,
        "contractSize": size,
        "priceUnit": "0.1",
        "volUnit": 1,
        "typeLabel": 0,
    }


def instrument():
    return parse_mexc_catalog(
        {"success": True, "code": 0, "data": [definition()]}, observed_at=NOW
    ).instruments[0]


def test_catalog_uses_contracts_and_excludes_unreviewed_noncrypto():
    batch = parse_mexc_catalog(
        {
            "success": True,
            "code": 0,
            "data": [
                definition(),
                definition("XAU_USDT", "XAU"),
                definition("UNKNOWN_USDT", "UNKNOWN"),
            ],
        },
        observed_at=NOW,
    )
    item = batch.instruments[0]
    assert item.quantity_unit == "contracts"
    assert item.contract_multiplier == Decimal("0.0001")
    assert item.amount_step == Decimal("1")
    assert [x.reason for x in batch.exclusions] == [
        "identity_not_reviewed",
        "identity_not_reviewed",
    ]
    assert resolve_market_groups([item])[0].group_id == "crypto:BTC:linear-perp"


def test_semantic_version_keeps_contract_change_unknown_fields_ignores_display_fee():
    item = instrument()
    display = replace(
        item,
        raw_definition={
            **item.raw_definition,
            "displayName": "new",
            "makerFeeRate": ".001",
            "maxLeverage": 300,
            "isHot": True,
        },
    )
    assert display.definition_sha256() != item.definition_sha256()
    assert display.semantic_definition_sha256() == item.semantic_definition_sha256()
    changed = replace(item, contract_multiplier=Decimal(".001"))
    assert changed.semantic_definition_sha256() != item.semantic_definition_sha256()
    unknown = replace(item, raw_definition={**item.raw_definition, "newField": 1})
    assert unknown.semantic_definition_sha256() != item.semantic_definition_sha256()


RISK_TIERS = [
    {"imr": 0.00333333, "mmr": 0.0023, "level": 1, "maxVol": 170000, "maxLeverage": 300},
    {"imr": 0.005, "mmr": 0.004, "level": 2, "maxVol": 360000, "maxLeverage": 200},
]


@pytest.mark.parametrize(
    ("before", "after"),
    [
        pytest.param(
            {"limitMaxVol": 17400, "maxVol": 17400, "riskBaseVol": 17400},
            {"limitMaxVol": 51700, "maxVol": 51700, "riskBaseVol": 51700},
            id="KAIA-9940-9976",
        ),
        pytest.param(
            {"limitMaxVol": 700, "maxVol": 700, "riskBaseVol": 700, "riskIncrVol": 5500},
            {"limitMaxVol": 1900, "maxVol": 1900, "riskBaseVol": 1900, "riskIncrVol": 0},
            id="MAGIC-9939-9975",
        ),
        pytest.param(
            {"riskBaseVol": 360000, "riskLimitCustom": RISK_TIERS},
            {
                "riskBaseVol": 433500,
                "riskLimitCustom": [RISK_TIERS[0], {**RISK_TIERS[1], "maxVol": 433500}],
            },
            id="TAO-9943-9977",
        ),
        pytest.param(
            {"limitMaxVol": 2900, "maxVol": 2900, "riskBaseVol": 2900},
            {"limitMaxVol": 10300, "maxVol": 10300, "riskBaseVol": 10300},
            id="US-9934-9974",
        ),
        pytest.param(
            {"isHot": False, "tagIdList": [8]},
            {"isHot": True, "tagIdList": [7, 8]},
            id="KAIA-9976-9978_MAGIC-9975-9979_US-9974-9980-tags",
        ),
    ],
)
def test_semantic_identity_ignores_observed_mexc_metadata_without_mutating_raw(before, after):
    # These exact deltas came from the separately retained read-only stage50 audit.
    original = instrument()
    left = replace(original, raw_definition={**original.raw_definition, **copy.deepcopy(before)})
    right = replace(original, raw_definition={**original.raw_definition, **copy.deepcopy(after)})
    retained = copy.deepcopy((left.raw_definition, right.raw_definition))
    full_hashes = (left.definition_sha256(), right.definition_sha256())
    assert full_hashes[0] != full_hashes[1]
    assert left.semantic_definition_sha256() == right.semantic_definition_sha256()
    assert (left.raw_definition, right.raw_definition) == retained
    assert (left.definition_sha256(), right.definition_sha256()) == full_hashes


@pytest.mark.parametrize(
    "change",
    [
        {"price_tick": Decimal("0.2")},
        {"amount_step": Decimal("2")},
        {"contract_multiplier": Decimal("0.001")},
        {"active": False},
        {"market_type": "future"},
    ],
)
def test_mexc_metadata_projection_keeps_price_quantity_and_lifecycle_changes(change):
    original = instrument()
    item = replace(
        original,
        raw_definition={
            **original.raw_definition,
            "riskLimitCustom": RISK_TIERS,
            "tagIdList": [8],
        },
    )
    changed = replace(item, raw_definition={**item.raw_definition, "tagIdList": [7, 8]}, **change)
    assert changed.semantic_definition_sha256() != item.semantic_definition_sha256()


@pytest.mark.parametrize(
    "raw_change",
    [
        pytest.param({}, id="missing"),
        pytest.param({"tagIdList": None}, id="null"),
        pytest.param({"tagIdList": {"id": 8}}, id="object"),
        pytest.param({"tagIdList": [True, 8]}, id="boolean"),
        pytest.param({"tagIdList": ["7", 8]}, id="string"),
        pytest.param({"tagIdList": [7.0, 8]}, id="float"),
        pytest.param({"tagIdList": [-1, 8]}, id="negative"),
        pytest.param({"tagIdList": [{"id": 7}, 8]}, id="nested"),
        pytest.param({"tagIdList": [7, 8], "unknownTagMeaning": True}, id="unknown-field"),
    ],
)
def test_mexc_tag_projection_preserves_presence_schema_and_unknown_fields(raw_change):
    original = instrument()
    item = replace(original, raw_definition={**original.raw_definition, "tagIdList": [8]})
    changed = replace(original, raw_definition={**original.raw_definition, **raw_change})
    assert changed.semantic_definition_sha256() != item.semantic_definition_sha256()


@pytest.mark.parametrize(
    "change", ["unknown", "margin", "order", "count", "shape", "missing_cap", "unknown_cap"]
)
def test_mexc_risk_tier_projection_preserves_other_fields_and_structure(change):
    original = instrument()
    raw = {**original.raw_definition, "riskLimitCustom": copy.deepcopy(RISK_TIERS)}
    item = replace(original, raw_definition=copy.deepcopy(raw))
    tiers = raw["riskLimitCustom"]
    if change == "unknown":
        tiers[1]["unknownProviderField"] = {"flag": True}
    elif change == "margin":
        tiers[1]["mmr"] = 0.02
    elif change == "order":
        tiers.reverse()
    elif change == "count":
        tiers.pop()
    elif change == "shape":
        raw["riskLimitCustom"] = {"tier": tiers[0]}
    elif change == "missing_cap":
        del tiers[1]["maxVol"]
    elif change == "unknown_cap":
        tiers[1]["maxVol"] = {"contracts": 360000, "newMeaning": True}
    changed = replace(item, raw_definition=raw)
    assert changed.semantic_definition_sha256() != item.semantic_definition_sha256()


def test_l1_converts_oi_without_scaling_prices_or_fixing_funding_period():
    item = instrument()
    row = {
        "symbol": "BTC_USDT",
        "fairPrice": "100",
        "indexPrice": "101",
        "bid1": "99",
        "ask1": "100",
        "holdVol": 10000,
        "amount24": "4567",
        "fundingRate": "-.004",
        "timestamp": int(NOW.timestamp() * 1000),
    }
    funding = {
        "symbol": "BTC_USDT",
        "fundingRate": "-.004",
        "collectCycle": 4,
        "nextSettleTime": int((NOW + timedelta(hours=4)).timestamp() * 1000),
        "timestamp": int(NOW.timestamp() * 1000),
    }
    obs = parse_mexc_l1(
        {"success": True, "code": 0, "data": [row]},
        {"BTC_USDT": {"success": True, "code": 0, "data": funding}},
        [item],
        cycle_at=NOW,
        observed_at=NOW,
    ).observations[0]
    assert obs.open_interest_raw_unit == "contracts"
    assert obs.open_interest_base == Decimal("1")
    assert obs.open_interest_notional == Decimal("100")
    assert obs.mark_price == Decimal("100")
    assert obs.funding_interval_seconds == 14400
    assert obs.funding_rate_per_hour == Decimal("-.001")


def test_history_only_closed_minutes_convert_exact_quantity():
    payload = {
        "success": True,
        "code": 0,
        "data": {
            "time": [int((NOW - timedelta(minutes=1)).timestamp()), int(NOW.timestamp())],
            "open": [100, 100],
            "high": [101, 101],
            "low": [99, 99],
            "close": [100, 100],
            "vol": [10000, 10000],
            "amount": [100, 100],
        },
    }
    candles = parse_mexc_history(payload, instrument(), observed_at=NOW)
    assert len(candles) == 1
    assert candles[0].volume_base == Decimal("1")
    assert candles[0].volume_notional == Decimal("100")
    assert candles[0].finality == "derived_final"


def test_depth_requires_continuous_versions_and_uses_absolute_sizes():
    state = MexcSelectedState(instrument())
    snapshot = {
        "success": True,
        "code": 0,
        "data": {
            "version": 10,
            "timestamp": int(NOW.timestamp() * 1000),
            "bids": [[99, 10000, 1], [98, 1000, 1]],
            "asks": [[101, 10000, 1]],
        },
    }
    assert state.snapshot(snapshot, received_at=NOW).bids[0].size_base == Decimal("1")
    delta: dict[str, object] = {
        "channel": "push.depth",
        "symbol": "BTC_USDT",
        "ts": int(NOW.timestamp() * 1000),
        "data": {
            "begin": 11,
            "end": 12,
            "version": 12,
            "bids": [[99, 2000, 1], [98, 0, 0]],
            "asks": [],
        },
    }
    book = state.parse(delta, received_at=NOW)[0]
    assert isinstance(book, SelectedDepth)
    assert len(book.bids) == 1
    assert book.bids[0].size_base == Decimal(".2")
    with pytest.raises(SelectedContractError):
        state.parse(
            {**delta, "data": {**{"bids": [], "asks": []}, "begin": 14, "end": 14}}, received_at=NOW
        )
    with pytest.raises(SelectedContractError):
        state.parse(delta, received_at=NOW)


def test_deals_deduplicate_source_i():
    state = MexcSelectedState(instrument())
    payload: dict[str, object] = {
        "channel": "push.deal",
        "symbol": "BTC_USDT",
        "data": [{"p": 100, "v": 1000, "T": 1, "t": int(NOW.timestamp() * 1000), "i": "trade-1"}],
    }
    event = state.parse(payload, received_at=NOW)[0]
    assert isinstance(event, SelectedTrade)
    assert event.size_base == Decimal(".1")
    assert event.side == "buy"
    assert state.parse(payload, received_at=NOW) == ()


def test_single_version_depth_and_ws_finality_delay():
    from prep_watchdeck_market.sources.mexc_candles import MexcCandleFinalizer

    state = MexcSelectedState(instrument())
    state.snapshot(
        {
            "success": True,
            "code": 0,
            "data": {"version": 10, "bids": [[99, 10000, 1]], "asks": [[101, 10000, 1]]},
        },
        received_at=NOW,
    )
    book = state.parse(
        {
            "channel": "push.depth",
            "symbol": "BTC_USDT",
            "data": {"version": 11, "bids": [[99, 2000, 1]], "asks": []},
        },
        received_at=NOW,
    )[0]
    assert isinstance(book, SelectedDepth)
    assert book.bids[0].size_base == Decimal(".2")
    finalizer = MexcCandleFinalizer([instrument()])
    finalizer.ingest(
        {
            "channel": "push.kline",
            "data": {
                "symbol": "BTC_USDT",
                "interval": "Min1",
                "t": int(NOW.timestamp()),
                "o": 100,
                "h": 101,
                "l": 99,
                "c": 100,
                "q": 10000,
                "a": 100,
            },
        },
        observed_at=NOW,
    )
    assert finalizer.finalize(now=NOW + timedelta(minutes=1)) == ()
    candle = finalizer.finalize(now=NOW + timedelta(minutes=1, seconds=5))[0]
    assert candle.volume_base == Decimal("1")
    assert candle.finality == "derived_final"
    assert candle.finalized_at == NOW + timedelta(minutes=1, seconds=5)


def test_native_recovery_routes_mexc_and_preserves_exact_multiplier(monkeypatch, tmp_path):
    monkeypatch.setenv("PREP_WATCHDECK_MEXC_BUDGET_DB", str(tmp_path / "budget.sqlite3"))
    import asyncio
    from typing import cast

    import aiohttp

    from prep_watchdeck_market.candle_recovery_store import RecoveryTarget
    from prep_watchdeck_market.sources.candle_history import NativeCandleHistoryClient

    target = RecoveryTarget(
        10,
        "mexc",
        "BTC_USDT",
        "a" * 64,
        NOW - timedelta(minutes=5),
        "BTC",
        "USDT",
        "USDT",
        "contracts",
        Decimal(".0001"),
    )
    bucket = NOW - timedelta(minutes=1)

    class Client(NativeCandleHistoryClient):
        async def _request_json(self, method, url, *, params=None, body=None):
            assert method == "GET"
            assert url == "https://api.mexc.com/api/v1/contract/kline/BTC_USDT"
            assert params == {
                "interval": "Min1",
                "start": str(int(bucket.timestamp())),
                "end": str(int(NOW.timestamp()) - 1),
            }
            return {
                "success": True,
                "code": 0,
                "data": {
                    "time": [int(bucket.timestamp())],
                    "open": [100],
                    "high": [101],
                    "low": [99],
                    "close": [100],
                    "vol": [10000],
                    "amount": [100],
                },
            }, NOW

    async def run():
        client = Client(cast(aiohttp.ClientSession, object()), max_requests=2, deadline_seconds=60)
        return await client.fetch_missing(target, [bucket], max_pages=1)

    result = asyncio.run(run())
    assert result.pages == 1
    assert result.candles[0].volume_base == Decimal("1")


def test_gap_invalidation_removes_persisted_selected_depth_only(monkeypatch):
    from contextlib import nullcontext
    from typing import Any, cast
    from uuid import uuid4

    import psycopg

    import prep_watchdeck_market.selected_store as store
    from prep_watchdeck_market.selected_market import SelectedDepthInvalidated
    from prep_watchdeck_market.selected_store import store_selected_events

    lease_id = uuid4()
    event = SelectedDepthInvalidated(
        "mexc", "BTC_USDT", NOW, "sub.depth", {"reason": "sequence_gap"}
    )
    queries = []

    class Cursor:
        rowcount = 1

        def fetchone(self):
            return (0,)

        def execute(self, query, params):
            queries.append(query)
            assert query.count("%s") == len(params)
            return self

    cursor = Cursor()

    class Connection:
        def transaction(self):
            return nullcontext()

        def cursor(self):
            return nullcontext(cursor)

    # DB identity lookup has its own integration coverage; exercise event write dispatch here.
    monkeypatch.setattr(
        store,
        "_active_selection",
        lambda *_: store.SelectionLease(
            lease_id,
            "crypto:BTC:linear-perp",
            10,
            NOW,
            NOW,
            NOW + timedelta(minutes=15),
            None,
            None,
            None,
        ),
    )
    monkeypatch.setattr(store, "_selected_versions", lambda *_: {("mexc", "BTC_USDT"): 10})
    store_selected_events(cast(psycopg.Connection[Any], Connection()), lease_id, [event])
    assert any("DELETE FROM selected_depth_levels" in q for q in queries)
    assert not any("INSERT INTO selected_depth_levels" in q for q in queries)
    assert not any("DELETE FROM selected_trades" in q for q in queries)


def test_mexc_db_versions_selected_and_recovery_preserve_quantity_evidence():
    import os
    from uuid import uuid4

    import psycopg
    from psycopg import sql

    from prep_watchdeck_market.candle_recovery_store import (
        RecoveryVersionChanged,
        insert_missing_candles,
        load_recovery_targets,
    )
    from prep_watchdeck_market.catalog_store import persist_catalog
    from prep_watchdeck_market.database import apply_migrations
    from prep_watchdeck_market.selected_market import SelectedDepthInvalidated
    from prep_watchdeck_market.selected_store import (
        activate_selection,
        read_selected_market,
        store_selected_events,
    )

    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires isolated TEST_DATABASE_URL")
    schema = "mexc_test_" + uuid4().hex
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        try:
            apply_migrations(conn)
            first = parse_mexc_catalog(
                {"success": True, "code": 0, "data": [definition()]}, observed_at=NOW
            )
            persist_catalog(conn, first, resolve_market_groups(first.instruments))
            target = load_recovery_targets(conn, venue="mexc")[0]
            assert target.quantity_unit == "contracts"
            assert target.contract_multiplier == Decimal(".0001")
            lease = uuid4()
            activate_selection(
                conn,
                selection_id=lease,
                group_id="crypto:BTC:linear-perp",
                primary_venue_instrument_id="mexc:BTC_USDT",
                activated_at=NOW,
            )
            state = MexcSelectedState(first.instruments[0])
            depth = state.snapshot(
                {
                    "success": True,
                    "code": 0,
                    "data": {"version": 10, "bids": [[99, 10000, 1]], "asks": [[101, 10000, 1]]},
                },
                received_at=NOW,
            )
            store_selected_events(conn, lease, [depth])
            view = read_selected_market(conn, now=NOW)
            assert view is not None
            assert view.instruments[0].bids[0].size_base == Decimal("1")
            store_selected_events(
                conn,
                lease,
                [SelectedDepthInvalidated("mexc", "BTC_USDT", NOW, "sub.depth", {"reason": "gap"})],
            )
            view = read_selected_market(conn, now=NOW)
            assert view is not None
            assert view.instruments[0].bids == ()
            payload = {
                "success": True,
                "code": 0,
                "data": {
                    "time": [int(NOW.timestamp())],
                    "open": [100],
                    "high": [101],
                    "low": [99],
                    "close": [100],
                    "vol": [10000],
                    "amount": [100],
                },
            }
            candle = parse_mexc_history(
                payload, first.instruments[0], observed_at=NOW + timedelta(minutes=1)
            )[0]
            run = uuid4()
            conn.execute(
                "INSERT INTO collector_runs (run_id,run_kind,started_at,status) "
                "VALUES (%s,%s,%s,%s)",
                (run, "candle_recovery", NOW, "running"),
            )
            assert insert_missing_candles(conn, target, [candle], run_id=run) == 1
            changed = parse_mexc_catalog(
                {"success": True, "code": 0, "data": [definition(size=".001")]},
                observed_at=NOW + timedelta(minutes=2),
            )
            result = persist_catalog(conn, changed, resolve_market_groups(changed.instruments))
            assert result.instrument_versions_created == 1
            assert result.instrument_versions_closed == 1
            new_target = load_recovery_targets(conn, venue="mexc")[0]
            assert new_target.version_id != target.version_id
            assert new_target.contract_multiplier == Decimal(".001")
            with pytest.raises(RecoveryVersionChanged):
                insert_missing_candles(conn, target, [candle], run_id=run)
            from prep_watchdeck_market.candle_store import (
                UnknownCandleInstrumentError,
                upsert_candles,
            )

            future = replace(
                candle,
                bucket_start=NOW + timedelta(minutes=3),
                observed_at=NOW + timedelta(minutes=4),
                finalized_at=NOW + timedelta(minutes=4),
            )
            with pytest.raises(UnknownCandleInstrumentError):
                upsert_candles(conn, [future])
            from prep_watchdeck_market.market_store import persist_market_cycle

            cycle = NOW + timedelta(minutes=3)
            old_l1 = parse_mexc_l1(
                {
                    "success": True,
                    "code": 0,
                    "data": [{"symbol": "BTC_USDT", "holdVol": 10000, "fairPrice": 100}],
                },
                {},
                first.instruments,
                cycle_at=cycle,
                observed_at=cycle,
            )
            stored = persist_market_cycle(conn, cycle, cycle, [old_l1])
            assert stored.unknown_source_rows == 1
            row = conn.execute(
                "SELECT status, open_interest_base FROM latest_market_state "
                "WHERE venue_instrument_version_id = %s",
                (new_target.version_id,),
            ).fetchone()
            assert row == ("unavailable", None)
        finally:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_selected_retries_429_and_keeps_emit_failures_visible(monkeypatch):
    import asyncio
    from contextlib import asynccontextmanager
    from typing import cast

    import aiohttp

    from prep_watchdeck_market.selected_market import SelectedTrade
    from prep_watchdeck_market.sources.common import CatalogSourceError
    from prep_watchdeck_market.sources.mexc_selected import produce_mexc_selected

    snapshot = {
        "success": True,
        "code": 0,
        "data": {"version": 10, "bids": [[99, 10000, 1]], "asks": [[101, 10000, 1]]},
    }
    calls = []

    async def fetch(session, endpoint, **kwargs):
        calls.append(endpoint)
        if len(calls) == 1:
            raise CatalogSourceError("rate limited", error_code="http_429")
        if "/depth/" in endpoint:
            return snapshot
        return {
            "success": True,
            "code": 0,
            "data": [
                {"i": "retry-trade", "T": 1, "p": 100, "v": 1000, "t": int(NOW.timestamp() * 1000)}
            ],
        }

    monkeypatch.setattr("prep_watchdeck_market.sources.mexc_selected.fetch_mexc_json", fetch)

    class WS:
        async def send_json(self, payload):
            pass

    @asynccontextmanager
    async def connect(url):
        yield WS()

    async def run(fail_emit=False):
        stop = asyncio.Event()
        events = []

        async def emit(event):
            if fail_emit and isinstance(event, SelectedTrade):
                raise OSError("writer failed")
            events.append(event)
            if isinstance(event, SelectedTrade):
                stop.set()

        await asyncio.wait_for(
            produce_mexc_selected(
                cast(aiohttp.ClientSession, object()),
                instrument(),
                emit,
                stop,
                ws_factory=connect,
                reconnect_delay_seconds=0,
            ),
            timeout=1,
        )
        return events

    events = asyncio.run(run())
    assert any(isinstance(e, SelectedTrade) and e.trade_id == "retry-trade" for e in events)
    with pytest.raises(OSError, match="writer failed"):
        asyncio.run(run(True))


@pytest.mark.parametrize(
    "malformed", [None, [], {"symbol": "BTC_USDT", "interval": "Min1", "t": 10**100}]
)
def test_candles_reconnect_on_native_malformed_payload_then_resume(malformed):
    import asyncio
    import json
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    import aiohttp

    from prep_watchdeck_market.sources.mexc_candle_stream import produce_mexc_candles

    attempts = []
    old = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=2)
    valid = {
        "symbol": "BTC_USDT",
        "interval": "Min1",
        "t": int(old.timestamp()),
        "o": 100,
        "h": 101,
        "l": 99,
        "c": 100,
        "q": 10000,
        "a": 100,
    }

    class WS:
        def __init__(self, value):
            self.value = value
            self.acked = False

        async def send_json(self, payload):
            pass

        async def receive(self):
            if not self.acked:
                self.acked = True
                return SimpleNamespace(
                    type=aiohttp.WSMsgType.TEXT,
                    data=json.dumps({"channel": "rs.sub.kline", "data": "success"}),
                )
            return SimpleNamespace(
                type=aiohttp.WSMsgType.TEXT,
                data=json.dumps({"channel": "push.kline", "data": self.value}),
            )

    @asynccontextmanager
    async def connect(url):
        attempts.append(url)
        yield WS(malformed if len(attempts) == 1 else valid)

    async def run():
        stop = asyncio.Event()
        candles = []

        async def emit(candle):
            candles.append(candle)
            stop.set()

        await asyncio.wait_for(
            produce_mexc_candles(
                None, [instrument()], emit, stop, ws_factory=connect, reconnect_delay_seconds=0
            ),
            timeout=1,
        )
        return candles

    candles = asyncio.run(run())
    assert len(attempts) == 2
    assert candles[0].volume_base == Decimal("1")


@pytest.mark.parametrize(
    "payload",
    [{"success": True, "code": 0, "data": None}, {"success": False, "code": 510, "data": None}],
)
def test_history_bad_envelope_raises_target_level_candle_parse_error(payload):
    from prep_watchdeck_market.candles import CandleParseError

    with pytest.raises(CandleParseError):
        parse_mexc_history(payload, instrument(), observed_at=NOW)


def test_funding_sync_disable_ignores_saved_mexc_catalog(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from prep_watchdeck_market.funding_runtime import (
        FundingRuntime,
        FundingSweepSummary,
        run_funding_sync_once,
    )

    mexc = instrument()
    old = replace(mexc, venue="bitget", source_symbol="BTCUSDT")
    monkeypatch.setattr(
        "prep_watchdeck_market.funding_runtime.load_funding_catalog_url",
        lambda _: SimpleNamespace(instruments=(old, mexc), version_starts={}),
    )

    async def run(self, stop):
        assert self._instrument_supplier() == (old,)
        return FundingSweepSummary(0, 0, 0, 0, None)

    monkeypatch.setattr(FundingRuntime, "run_once", run)
    asyncio.run(run_funding_sync_once("unused", mexc_enabled=False))


@pytest.mark.parametrize(
    "malformed",
    [
        [],
        {
            "channel": "push.deal",
            "symbol": "BTC_USDT",
            "data": [{"i": "bad", "T": 1, "p": "bad", "v": 1, "t": int(NOW.timestamp() * 1000)}],
        },
    ],
)
def test_selected_reconnects_after_malformed_ws_decode(monkeypatch, malformed):
    import asyncio
    import json
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from typing import cast

    import aiohttp

    from prep_watchdeck_market.sources.mexc_selected import produce_mexc_selected

    async def fetch(session, endpoint, **kwargs):
        if "/depth/" in endpoint:
            return {
                "success": True,
                "code": 0,
                "data": {"version": 10, "bids": [[99, 10000, 1]], "asks": [[101, 10000, 1]]},
            }
        return {"success": True, "code": 0, "data": []}

    monkeypatch.setattr("prep_watchdeck_market.sources.mexc_selected.fetch_mexc_json", fetch)
    good = {
        "channel": "push.deal",
        "symbol": "BTC_USDT",
        "data": [{"i": "good", "T": 1, "p": 100, "v": 1000, "t": int(NOW.timestamp() * 1000)}],
    }
    attempts = []

    class WS:
        def __init__(self, payload):
            self.payload = payload

        async def send_json(self, payload):
            pass

        async def receive(self):
            return SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data=json.dumps(self.payload))

    @asynccontextmanager
    async def connect(url):
        attempts.append(url)
        yield WS(malformed if len(attempts) == 1 else good)

    async def run():
        stop = asyncio.Event()
        events = []

        async def emit(event):
            events.append(event)
            if isinstance(event, SelectedTrade):
                stop.set()

        await asyncio.wait_for(
            produce_mexc_selected(
                cast(aiohttp.ClientSession, object()),
                instrument(),
                emit,
                stop,
                ws_factory=connect,
                reconnect_delay_seconds=0,
            ),
            timeout=1,
        )
        return events

    events = asyncio.run(run())
    assert len(attempts) == 2
    assert any(isinstance(e, SelectedTrade) and e.trade_id == "good" for e in events)


def test_stalled_mexc_peer_close_finishes_selection_cleanup(monkeypatch):
    import asyncio
    from contextlib import suppress

    from prep_watchdeck_market.selection import SelectionController
    from prep_watchdeck_market.sources import mexc_stream_common

    monkeypatch.setattr(mexc_stream_common, "MEXC_WS_CLOSE_TIMEOUT_SECONDS", 0.01, raising=False)

    async def run():
        opened = asyncio.Event()
        close_cancelled = asyncio.Event()

        class Manager:
            async def __aenter__(self):
                return object()

            async def __aexit__(self, *args):
                try:
                    await asyncio.Event().wait()
                finally:
                    close_cancelled.set()

        async def stream():
            async with mexc_stream_common.source_connection(lambda url: Manager()):
                opened.set()
                await asyncio.Event().wait()

        async def subscribe(*args):
            task = asyncio.create_task(stream())
            await opened.wait()
            return task

        async def unsubscribe(active):
            active.subscription.cancel()
            with suppress(asyncio.CancelledError):
                await active.subscription

        controller = SelectionController(
            subscribe, unsubscribe, debounce=timedelta(0), cleanup_timeout_seconds=0.2
        )
        controller.request("crypto:BTC", "mexc:BTC_USDT", NOW)
        assert await controller.reconcile(NOW) is not None
        started = asyncio.get_running_loop().time()
        await controller.stop()
        assert asyncio.get_running_loop().time() - started < 0.1
        assert controller.active is None
        assert close_cancelled.is_set()

    asyncio.run(run())


def test_stalled_mexc_peer_close_preserves_writer_failure(monkeypatch):
    import asyncio

    from prep_watchdeck_market.sources import mexc_stream_common

    monkeypatch.setattr(mexc_stream_common, "MEXC_WS_CLOSE_TIMEOUT_SECONDS", 0.01, raising=False)

    class Manager:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *args):
            await asyncio.Event().wait()

    async def run():
        async with mexc_stream_common.source_connection(lambda url: Manager()):
            raise OSError("writer failed during stream")

    with pytest.raises(OSError, match="writer failed during stream"):
        asyncio.run(asyncio.wait_for(run(), timeout=0.2))


@pytest.mark.parametrize("failure", [None, "missing", "duplicate", "mixed_order"])
def test_selected_cached_snapshot_requires_exact_commit_bridge(monkeypatch, failure):
    import asyncio
    import json
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    import aiohttp

    from prep_watchdeck_market.selected_market import SelectedDepthInvalidated
    from prep_watchdeck_market.sources.mexc_selected import produce_mexc_selected

    commits = [
        {"version": 12, "bids": [[98, 0, 0]], "asks": []},
        {"version": 11, "bids": [[99, 2000, 1]], "asks": []},
    ]
    if failure == "missing":
        commits = [row for row in commits if row["version"] != 11]
    elif failure == "duplicate":
        commits.append(commits[-1])
    elif failure == "mixed_order":
        commits.append({"version": 13, "bids": [], "asks": []})
    endpoints = []

    async def fetch(session, endpoint, **kwargs):
        endpoints.append(endpoint)
        if "/depth_commits/" in endpoint:
            return {"success": True, "code": 0, "data": commits}
        if "/depth/" in endpoint:
            return {
                "success": True,
                "code": 0,
                "data": {
                    "version": 10,
                    "bids": [[99, 10000, 1], [98, 1000, 1]],
                    "asks": [[101, 10000, 1]],
                },
            }
        return {"success": True, "code": 0, "data": []}

    monkeypatch.setattr("prep_watchdeck_market.sources.mexc_selected.fetch_mexc_json", fetch)

    class WS:
        async def send_json(self, payload):
            if payload["method"] == "sub.depth":
                assert payload["param"]["compress"] is True
            elif payload["method"] == "sub.deal":
                assert payload["param"]["compress"] is False

        async def receive(self):
            return SimpleNamespace(
                type=aiohttp.WSMsgType.TEXT,
                data=json.dumps(
                    {
                        "channel": "push.depth",
                        "symbol": "BTC_USDT",
                        "data": {"version": 13, "bids": [], "asks": [[101, 5000, 1]]},
                    }
                ),
            )

    @asynccontextmanager
    async def connect(url):
        yield WS()

    async def run():
        stop = asyncio.Event()
        events = []

        async def emit(event):
            events.append(event)
            if isinstance(event, SelectedDepth) or (
                isinstance(event, SelectedDepthInvalidated)
                and event.raw_payload.get("reason") == "stream_disconnected_or_invalid"
            ):
                stop.set()

        await asyncio.wait_for(
            produce_mexc_selected(object(), instrument(), emit, stop, ws_factory=connect), timeout=1
        )
        return events

    events = asyncio.run(run())
    depths = [event for event in events if isinstance(event, SelectedDepth)]
    assert "/api/v1/contract/depth_commits/BTC_USDT/1000" in endpoints
    if failure is None:
        assert len(depths) == 1
        assert [(x.price, x.size_base) for x in depths[0].bids] == [(Decimal(99), Decimal(".2"))]
        assert depths[0].asks[0].size_base == Decimal(".5")
        assert (
            require_mapping(depths[0].raw_payload["watchdeckDepthCommits"], field_name="commits")[
                "data"
            ]
            == commits
        )
        snapshot = require_mapping(
            depths[0].raw_payload["watchdeckSnapshot"], field_name="snapshot"
        )
        assert require_mapping(snapshot["data"], field_name="snapshot data")["version"] == 10
    else:
        assert depths == []


@pytest.mark.parametrize("writer_failure", [False, True])
def test_selected_live_gap_invalidates_before_bridge_and_preserves_writer_errors(
    monkeypatch, writer_failure
):
    import asyncio
    import json
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    import aiohttp

    from prep_watchdeck_market.selected_market import SelectedDepthInvalidated
    from prep_watchdeck_market.sources.mexc_selected import produce_mexc_selected

    events = []
    versions = iter([11, 14])

    async def fetch(session, endpoint, **kwargs):
        if "/depth_commits/" in endpoint:
            assert isinstance(events[-1], SelectedDepthInvalidated)
            assert events[-1].raw_payload["reason"] == "depth_sequence_gap"
            return {
                "success": True,
                "code": 0,
                "data": [{"version": v, "bids": [], "asks": []} for v in [12, 13]],
            }
        if "/depth/" in endpoint:
            return {
                "success": True,
                "code": 0,
                "data": {"version": 10, "bids": [[99, 10000, 1]], "asks": [[101, 10000, 1]]},
            }
        return {"success": True, "code": 0, "data": []}

    monkeypatch.setattr("prep_watchdeck_market.sources.mexc_selected.fetch_mexc_json", fetch)

    class WS:
        async def send_json(self, payload):
            pass

        async def receive(self):
            version = next(versions, None)
            if version is None:
                return SimpleNamespace(type=aiohttp.WSMsgType.CLOSED)
            return SimpleNamespace(
                type=aiohttp.WSMsgType.TEXT,
                data=json.dumps(
                    {
                        "channel": "push.depth",
                        "symbol": "BTC_USDT",
                        "data": {"version": version, "bids": [], "asks": []},
                    }
                ),
            )

    @asynccontextmanager
    async def connect(url):
        yield WS()

    async def run():
        stop = asyncio.Event()

        async def emit(event):
            if (
                isinstance(event, SelectedDepthInvalidated)
                and event.raw_payload.get("reason") == "depth_sequence_gap"
                and writer_failure
            ):
                raise SelectedContractError("writer rejected invalidation")
            events.append(event)
            if (
                isinstance(event, SelectedDepthInvalidated)
                and event.raw_payload.get("reason") == "stream_disconnected_or_invalid"
            ):
                if not writer_failure:
                    assert event.raw_payload["errorCode"] == "socket_disconnected"
                stop.set()

        await asyncio.wait_for(
            produce_mexc_selected(object(), instrument(), emit, stop, ws_factory=connect), timeout=1
        )

    if writer_failure:
        with pytest.raises(SelectedContractError, match="writer rejected invalidation"):
            asyncio.run(run())
    else:
        asyncio.run(run())
        assert [
            require_mapping(event.raw_payload["data"], field_name="depth").get("version")
            for event in events
            if isinstance(event, SelectedDepth)
        ] == [11, 14]
