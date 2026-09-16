from datetime import UTC, datetime
from typing import cast

import pytest

from prep_watchdeck_ranking.models import MINUTE, RankingMap
from prep_watchdeck_ranking.ranking import DAY, Generation, Period, anchor_at
from prep_watchdeck_ranking.storage import Store

from .conftest import CUTOFF, candle, mapping, reference, seed


def utc(text: str) -> int:
    return int(datetime.fromisoformat(text).replace(tzinfo=UTC).timestamp() * 1000)


@pytest.mark.parametrize(
    ("cutoff", "clock", "expected"),
    [
        ("2026-09-11T15:00:00", "00:00", "2026-09-11T15:00:00"),
        ("2026-09-11T14:59:00", "00:00", "2026-09-10T15:00:00"),
        ("2026-09-12T00:29:00", "09:30", "2026-09-11T00:30:00"),
        ("2026-09-12T00:30:00", "09:30", "2026-09-12T00:30:00"),
        ("2026-09-12T00:31:00", "09:30", "2026-09-12T00:30:00"),
    ],
)
def test_jst_anchor_boundaries(cutoff: str, clock: str, expected: str) -> None:
    assert anchor_at(utc(cutoff), "daily", clock) == utc(expected)


@pytest.mark.parametrize(
    "clock", ["24:00", "9:00", "12:60", "00:00Z", "", "\uff10\uff10:\uff10\uff10"]
)
def test_invalid_reference_times(clock: str) -> None:
    with pytest.raises(ValueError):
        anchor_at(CUTOFF, "daily", clock)


def test_real_window_turnover_and_endpoint_price(store: Store) -> None:
    seed(store, reference())
    gen = Generation(mapping("BTC"), CUTOFF, CUTOFF + 8000, store)
    for period, minutes in [("15m", 15), ("1h", 60)]:
        result = gen.response(cast(Period, period), "00:00", "gainers", 0, CUTOFF + 8000)
        row = result.rows[0]
        assert row.return_pct == pytest.approx(10)
        assert row.quote_turnover == minutes * 5
        assert row.rank == 1
        assert result.anchor == CUTOFF - minutes * MINUTE


@pytest.mark.parametrize("period", ["15m", "1h", "daily"])
def test_unknown_original_quantity_and_widget_preserve_reference_metrics(
    store: Store,
    period: Period,
) -> None:
    original = mapping("BTC", "ETH")
    for asset, price in [("BTC", 110), ("ETH", 105)]:
        seed(store, reference(asset + "USDT"), end_price=price)
    candidate = original.model_dump(mode="json", by_alias=True)
    candidate["rows"][0]["originals"][0]["multiplier"] = None
    candidate["rows"][0]["widget"].update(status="review", symbol=None, referenceKey=None)
    unknown = RankingMap.model_validate(candidate)
    before = Generation(original, CUTOFF, CUTOFF + 8000, store).response(
        period, "00:00", "gainers", 0, CUTOFF + 8000
    )
    after = Generation(unknown, CUTOFF, CUTOFF + 8000, store).response(
        period, "00:00", "gainers", 0, CUTOFF + 8000
    )
    for actual, expected in zip(after.rows, before.rows, strict=True):
        assert actual.id == expected.id
        assert actual.rank == expected.rank
        assert actual.return_pct == expected.return_pct
        assert actual.quote_turnover == expected.quote_turnover
        assert actual.turnover_ratio == expected.turnover_ratio
        assert actual.day_range_position == expected.day_range_position
        assert actual.state == expected.state == "ready"
    assert after.rows[0].originals[0].multiplier is None
    assert after.coverage.widget_supported == before.coverage.widget_supported - 1


def test_identity_review_never_uses_available_prices(store: Store) -> None:
    seed(store, reference())
    candidate = mapping("BTC").model_dump(mode="json", by_alias=True)
    candidate["rows"][0].update(
        status="review",
        reason="original_identity_conflict",
        reference=None,
    )
    candidate["rows"][0]["widget"].update(status="review", symbol=None, referenceKey=None)
    generation = Generation(RankingMap.model_validate(candidate), CUTOFF, CUTOFF + 8000, store)
    assert not generation.series
    row = generation.response("15m", "00:00", "gainers", 0, CUTOFF).rows[0]
    assert row.state == "mapping_review"
    assert row.rank is row.return_pct is row.quote_turnover is None


def test_all_rows_rank_by_unrounded_values_and_stable_id(store: Store) -> None:
    for asset, close in [("AAA", 110), ("BBB", 110), ("CCC", 110.00001), ("DDD", 80)]:
        seed(store, reference(asset + "USDT"), end_price=close)
    gen = Generation(mapping("AAA", "BBB", "CCC", "DDD"), CUTOFF, CUTOFF + 8000, store)
    gain = gen.response("15m", "00:00", "gainers", 0, CUTOFF)
    assert [(r.asset, r.rank) for r in gain.rows] == [
        ("CCC", 1),
        ("AAA", 2),
        ("BBB", 3),
        ("DDD", None),
    ]
    loss = gen.response("15m", "00:00", "losers", 0, CUTOFF)
    assert loss.rows[0].asset == "DDD" and loss.rows[0].rank == 1


def test_zero_turnover_and_flat_return_are_observed_not_missing(store: Store) -> None:
    seed(store, reference(), end_price=100, turnover=0)
    gen = Generation(mapping("BTC"), CUTOFF, CUTOFF + 8000, store)
    result = gen.response("15m", "00:00", "turnover", 0, CUTOFF)
    assert result.rows[0].quote_turnover == 0
    assert result.rows[0].return_pct == 0
    assert result.rows[0].rank == 1
    assert gen.response("15m", "00:00", "gainers", 0, CUTOFF).coverage.ranked == 0
    assert gen.response("15m", "00:00", "turnover", 1, CUTOFF).rows[0].state == "filtered"


@pytest.mark.parametrize("missing_offset", [0, 8, 15])
def test_missing_boundary_or_interior_excludes_both_metrics(
    store: Store, missing_offset: int
) -> None:
    seed(store, reference())
    with store.connection:
        store.connection.execute(
            "DELETE FROM minute_bars WHERE end=?", (CUTOFF - missing_offset * MINUTE,)
        )
    gen = Generation(mapping("BTC"), CUTOFF, CUTOFF + 8000, store)
    row = gen.response("15m", "00:00", "gainers", 0, CUTOFF).rows[0]
    assert row.return_pct is None and row.quote_turnover is None and row.rank is None
    assert row.state == ("source_delayed" if missing_offset == 0 else "history_missing")


def test_late_correction_cannot_mutate_old_generation_or_another_daily_query(store: Store) -> None:
    seed(store, reference())
    old = Generation(mapping("BTC"), CUTOFF, CUTOFF + 8000, store)
    store.put([candle(reference(), CUTOFF, 200, 999)], CUTOFF)
    current = Generation(mapping("BTC"), CUTOFF, CUTOFF + 10_000, store)
    assert old.response("15m", "00:00", "gainers", 0, CUTOFF).rows[0].return_pct == pytest.approx(
        10
    )
    assert old.response("daily", "00:17", "gainers", 0, CUTOFF).rows[0].return_pct == pytest.approx(
        10
    )
    assert current.response("15m", "00:00", "gainers", 0, CUTOFF).rows[0].return_pct == 100


def test_revision_does_not_splice_old_contract_history(store: Store) -> None:
    seed(store, reference())
    updated = mapping("BTC")
    row = updated.rows[0].model_copy(update={"reference": reference(revision="v2")})
    updated = updated.model_copy(update={"version": "map-v2", "rows": (row,)})
    gen = Generation(updated, CUTOFF, CUTOFF + 8000, store)
    assert gen.response("15m", "00:00", "gainers", 0, CUTOFF).coverage.valid == 0


def test_stale_does_not_retimestamp_previous_results_and_cache_is_bounded(store: Store) -> None:
    seed(store, reference())
    gen = Generation(mapping("BTC"), CUTOFF, CUTOFF + 8000, store)
    for minute in range(60):
        gen.response("daily", f"00:{minute:02}", "gainers", 0, CUTOFF)
    assert len(gen.cache) == 32
    result = gen.response("15m", "00:00", "gainers", 0, CUTOFF + DAY * 2)
    assert result.stale and result.roster_stale and result.status == "stale"
    assert result.generated_at == CUTOFF + 8000
    assert result.cutoff == CUTOFF


def test_exact_anchor_is_starting_even_if_price_exists(store: Store) -> None:
    seed(store, reference())
    clock = datetime.fromtimestamp((CUTOFF + 9 * 60 * MINUTE) / 1000, UTC).strftime("%H:%M")
    gen = Generation(mapping("BTC"), CUTOFF, CUTOFF + 8000, store)
    result = gen.response("daily", clock, "gainers", 0, CUTOFF)
    assert result.status == "starting" and result.rows[0].rank is None


def test_provider_failure_and_invalid_contract_are_distinct_from_zero(store: Store) -> None:
    seed(store, reference())
    gen = Generation(
        mapping("BTC"), CUTOFF, CUTOFF + 8000, store, unavailable_keys={reference().key}
    )
    row = gen.response("15m", "00:00", "gainers", 0, CUTOFF).rows[0]
    assert row.state == "source_unavailable" and row.return_pct is None
