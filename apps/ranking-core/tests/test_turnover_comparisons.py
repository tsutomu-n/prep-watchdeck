import asyncio
from typing import Any

import aiohttp
import pytest

from prep_watchdeck_ranking import service as service_module
from prep_watchdeck_ranking.models import MINUTE, Provider
from prep_watchdeck_ranking.providers import PublicClient
from prep_watchdeck_ranking.ranking import DAY, Generation, Period
from prep_watchdeck_ranking.service import RankingService
from prep_watchdeck_ranking.storage import Store

from .conftest import CUTOFF, candle, mapping, reference


def seed_days(store: Store) -> None:
    store.put(
        (
            candle(
                reference(),
                CUTOFF - offset * MINUTE,
                close=110 if offset == 0 else 100,
                turnover=20 if offset < 1440 else 5 if offset < 2880 else 10,
            )
            for offset in range(4321)
        ),
        CUTOFF,
    )


@pytest.mark.parametrize(
    ("period", "daily_reference", "minutes"),
    [
        ("15m", "00:00", 15),
        ("1h", "00:00", 60),
        ("24h", "00:00", 1440),
        ("daily", "00:30", 30),
        ("daily", "09:00", 960),
    ],
)
def test_same_contract_same_length_windows_are_shifted_by_whole_days(
    store: Store, period: Period, daily_reference: str, minutes: int
) -> None:
    seed_days(store)
    gen = Generation(mapping("BTC"), CUTOFF, CUTOFF + 8000, store)
    row = gen.response(period, daily_reference, "turnover", 0, CUTOFF).rows[0]
    comparison = row.turnover_comparison
    for days, sample, per_minute in (
        (0, comparison.current, 20),
        (1, comparison.previous_day, 5),
        (2, comparison.two_days_ago, 10),
    ):
        assert sample.anchor == CUTOFF - days * DAY - minutes * MINUTE
        assert sample.cutoff == CUTOFF - days * DAY
        assert sample.status == "ready"
        assert sample.quote_turnover == minutes * per_minute
    assert comparison.previous_day_ratio.value == 4
    assert comparison.two_days_ago_ratio.value == 2
    # Extending the history must not change the existing 24-hour baseline.
    assert row.turnover_ratios["15m"].value == 1


def test_missing_previous_day_and_zero_baseline_do_not_remove_current_rank(store: Store) -> None:
    seed_days(store)
    with store.connection:
        store.connection.execute(
            "DELETE FROM minute_bars WHERE end=?", (CUTOFF - DAY - 3 * MINUTE,)
        )
    gen = Generation(mapping("BTC"), CUTOFF, CUTOFF + 8000, store)
    row = gen.response("15m", "00:00", "gainers", 0, CUTOFF).rows[0]
    comparison = row.turnover_comparison
    assert row.rank == 1 and row.state == "ready"
    assert comparison.current.quote_turnover == 300
    assert comparison.previous_day.quote_turnover is None
    assert comparison.previous_day_ratio.status == "history_missing"
    assert comparison.two_days_ago_ratio.value == 2

    store.put(
        [candle(reference(), CUTOFF - DAY - offset * MINUTE, turnover=0) for offset in range(15)],
        CUTOFF,
    )
    next_gen = Generation(mapping("BTC"), CUTOFF, CUTOFF + 9000, store)
    next_row = next_gen.response("15m", "00:00", "gainers", 0, CUTOFF).rows[0]
    assert next_row.turnover_comparison.previous_day.quote_turnover == 0
    assert next_row.turnover_comparison.previous_day_ratio.status == "no_baseline"
    assert next_row.turnover_comparison.previous_day_ratio.value is None
    assert comparison.previous_day_ratio.status == "history_missing"


def test_boundary_close_is_not_required_for_turnover_and_daily_start_is_explicit(
    store: Store,
) -> None:
    seed_days(store)
    with store.connection:
        store.connection.execute(
            "DELETE FROM minute_bars WHERE end=?", (CUTOFF - 2 * DAY - 15 * MINUTE,)
        )
    gen = Generation(mapping("BTC"), CUTOFF, CUTOFF + 8000, store)
    comparison = gen.response("15m", "00:00", "turnover", 0, CUTOFF).rows[0].turnover_comparison
    assert comparison.two_days_ago_ratio.value == 2
    starting = gen.response("daily", "01:00", "turnover", 0, CUTOFF).rows[0].turnover_comparison
    assert starting.current.status == starting.previous_day.status == "starting"
    assert starting.previous_day_ratio.value is None
    assert starting.current.quote_turnover is None


def test_current_zero_is_real_and_invalid_reference_never_exposes_old_comparison(
    store: Store,
) -> None:
    seed_days(store)
    store.put(
        [candle(reference(), CUTOFF - offset * MINUTE, turnover=0) for offset in range(15)],
        CUTOFF,
    )
    gen = Generation(mapping("BTC"), CUTOFF, CUTOFF + 8000, store)
    comparison = gen.response("15m", "00:00", "turnover", 0, CUTOFF).rows[0].turnover_comparison
    assert comparison.current.quote_turnover == 0
    assert comparison.previous_day_ratio.value == comparison.two_days_ago_ratio.value == 0
    invalid = Generation(
        mapping("BTC"), CUTOFF, CUTOFF + 8000, store, invalid_keys={reference().key}
    )
    comparison = invalid.response("15m", "00:00", "turnover", 0, CUTOFF).rows[0].turnover_comparison
    assert comparison.current.status == "reference_unavailable"
    assert comparison.two_days_ago.quote_turnover is None
    assert comparison.previous_day_ratio.status == "reference_unavailable"


def test_retention_keeps_previous_days_and_removes_only_outside_the_four_day_bound(
    store: Store,
) -> None:
    ends = [CUTOFF, CUTOFF - 3000 * MINUTE, CUTOFF - 5761 * MINUTE, CUTOFF - 5762 * MINUTE]
    store.put([candle(reference(), end) for end in ends], CUTOFF)
    store.prune(CUTOFF, {reference().key})
    assert [row[0] for row in store.window(reference().key, 0, CUTOFF)] == sorted(ends[:-1])


@pytest.mark.parametrize("provider", ["bybit", "binance"])
def test_history_pagination_reaches_two_days_ago_without_skipping_minutes(
    monkeypatch: pytest.MonkeyPatch, provider: Provider
) -> None:
    async def scenario() -> None:
        ref = reference().model_copy(update={"provider": provider})
        first = CUTOFF - 4320 * MINUTE
        calls = 0
        async with aiohttp.ClientSession() as session:
            client = PublicClient(session)

            async def request(_provider: Provider, _path: str, params: dict[str, Any]) -> Any:
                nonlocal calls
                calls += 1
                lower = int(params["start" if provider == "bybit" else "startTime"]) + MINUTE
                upper = int(params["end" if provider == "bybit" else "endTime"]) + 1
                ends = list(range(max(first, lower), upper + 1, MINUTE))
                ends = ends[-1000:][::-1] if provider == "bybit" else ends[:1000]
                rows = [
                    [end - MINUTE, "100", "100", "100", "100", "1", "5"]
                    if provider == "bybit"
                    else [end - MINUTE, "100", "100", "100", "100", "1", end - 1, "5"]
                    for end in ends
                ]
                return (
                    {
                        "retCode": 0,
                        "result": {"symbol": ref.symbol, "category": "linear", "list": rows},
                    }
                    if provider == "bybit"
                    else rows
                )

            monkeypatch.setattr(client, "request", request)
            bars = await client.history(ref, first, CUTOFF)
        assert [bar.end for bar in bars] == list(range(first, CUTOFF + 1, MINUTE))
        assert calls == 5

    asyncio.run(scenario())


def test_backfill_worker_fetches_the_full_comparison_horizon(
    store: Store,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(service_module, "now_ms", lambda: CUTOFF)
        async with aiohttp.ClientSession() as session:
            client = PublicClient(session)

            async def history(ref: Any, first: int, last: int) -> list:
                return [candle(ref, first), candle(ref, last)]

            monkeypatch.setattr(client, "history", history)
            service = RankingService(store, mapping("BTC"), client)
            service.enqueue(reference(), 4321)
            worker = asyncio.create_task(service.backfill_worker("bybit"))
            await service.queues["bybit"].join()
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
        assert [row[0] for row in store.window(reference().key, 0, CUTOFF)] == [
            CUTOFF - 4320 * MINUTE,
            CUTOFF,
        ]

    asyncio.run(scenario())
