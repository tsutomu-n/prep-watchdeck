from prep_watchdeck_ranking.models import MINUTE
from prep_watchdeck_ranking.ranking import DAY, Generation
from prep_watchdeck_ranking.storage import Store

from .conftest import CUTOFF, candle, mapping, reference, seed


def generations(store: Store) -> tuple[Generation, Generation]:
    for asset in ("AAA", "BBB", "CCC"):
        seed(store, reference(asset + "USDT"), end_price=100)
    # Previous ranks: AAA (30%), BBB (20%), CCC excluded (0%).
    store.put(
        [
            candle(reference(a + "USDT"), CUTOFF, c)
            for a, c in [("AAA", 130), ("BBB", 120), ("CCC", 100)]
        ],
        CUTOFF,
    )
    previous = Generation(mapping("AAA", "BBB", "CCC"), CUTOFF, CUTOFF + 8000, store)
    # Current ranks: BBB (40%), AAA (30%), CCC new (10%).
    t = CUTOFF + MINUTE
    store.put(
        [
            candle(reference(a + "USDT"), t, c)
            for a, c in [("AAA", 130), ("BBB", 140), ("CCC", 110)]
        ],
        t,
    )
    return previous, Generation(previous.mapping, t, t + 8000, store, previous=previous)


def test_rank_change_sign_new_and_same_conditions(store: Store) -> None:
    previous, current = generations(store)
    result = current.response("15m", "00:00", "gainers", 0, current.generated_at)
    assert result.previous_generation_id == previous.id
    assert [(r.asset, r.rank_change.delta, r.rank_change.status) for r in result.rows] == [
        ("BBB", 1, "compared"),
        ("AAA", -1, "compared"),
        ("CCC", None, "new"),
    ]
    for period in ("15m", "1h"):
        # All turnover values tie: deterministic identity ordering, delta zero.
        rows = current.response(period, "00:00", "turnover", 0, current.generated_at).rows
        assert [r.rank_change.delta for r in rows] == [0, 0, 0]
    filtered = current.response("15m", "00:00", "gainers", 76, current.generated_at)
    assert all(r.rank_change.status == "not_ranked" for r in filtered.rows)
    assert all(r.rank_change.reason == "min_turnover" for r in filtered.rows)
    # New lower limit must be applied to the old generation too.
    assert (
        current.response("15m", "00:00", "turnover", 1, current.generated_at)
        .rows[0]
        .rank_change.delta
        == 0
    )


def test_no_previous_is_not_new_after_restart_even_with_saved_bars(store: Store) -> None:
    _, current = generations(store)
    restarted = Generation(current.mapping, current.cutoff, current.generated_at, store)
    change = (
        restarted.response("15m", "00:00", "gainers", 0, current.generated_at).rows[0].rank_change
    )
    assert change.status == "unavailable" and change.reason == "no_previous_generation"


def test_missing_minute_map_metric_and_stale_are_not_comparable(store: Store) -> None:
    previous, current = generations(store)
    cases = [
        ("generation_gap", {"cutoff": previous.cutoff - MINUTE}),
        ("map_changed", {"mapping": previous.mapping.model_copy(update={"version": "new-map"})}),
        ("metric_changed", {"metric_version": "changed-definition"}),
    ]
    assert current.previous is not None
    for reason, updates in cases:
        original = {k: getattr(current.previous, k) for k in updates}
        for key, value in updates.items():
            setattr(current.previous, key, value)
        result = current.response("15m", "00:00", "gainers", 0, current.generated_at)
        assert all(r.rank_change.reason == reason for r in result.rows)
        for key, value in original.items():
            setattr(current.previous, key, value)
    for age, reason in [(90_001, "previous_stale"), (150_001, "current_stale")]:
        result = current.response("15m", "00:00", "gainers", 0, current.cutoff + age)
        assert all(r.rank_change.reason == reason for r in result.rows)


def test_jst_anchor_change_then_missing_previous_window(store: Store) -> None:
    _, current = generations(store)
    # CUTOFF is 01:00 JST. At 01:01 the anchor changed between the two generations.
    result = current.response("daily", "01:01", "gainers", 0, current.generated_at)
    assert all(r.rank_change.status == "not_ranked" for r in result.rows)
    # At the next minute, previous was 'starting', not an invented rank.
    t = current.cutoff + MINUTE
    store.put([candle(reference(a + "USDT"), t, 150) for a in ("AAA", "BBB", "CCC")], t)
    next_gen = Generation(current.mapping, t, t + 8000, store, previous=current)
    result = next_gen.response("daily", "01:01", "gainers", 0, t + 8000)
    assert all(r.rank_change.status == "new" for r in result.rows)
    # First generation after the JST date switch cannot compare old day's anchor.
    midnight = CUTOFF - 60 * MINUTE
    old = Generation(current.mapping, midnight - MINUTE, midnight - MINUTE + 8000, store)
    new = Generation(current.mapping, midnight, midnight + 8000, store, previous=old)
    # Daily starts empty; the short fixed period is still comparable across midnight.
    assert new.response("daily", "00:00", "turnover", 0, midnight + 8000).status == "starting"


def test_late_correction_and_retention_never_reconstruct_published_input(store: Store) -> None:
    previous, current = generations(store)
    store.put([candle(reference("AAAUSDT"), CUTOFF, 999)], current.cutoff)
    # Query a previously uncached condition after the DB correction.
    rows = current.response("1h", "03:20", "gainers", 0, current.generated_at).rows
    assert rows[0].asset == "BBB" and rows[0].rank_change.delta == 1
    for minute in range(50):
        current.response("daily", f"00:{minute:02}", "turnover", minute, current.generated_at)
    assert len(current.cache) == 32
    assert current.previous is not None and len(current.previous.cache) <= 32
    assert current.previous.previous is None
    third = Generation(
        current.mapping,
        current.cutoff + MINUTE,
        current.cutoff + MINUTE + 8000,
        store,
        previous=current,
    )
    assert third.previous is not None and third.previous.previous is None
    assert current.previous.id == previous.id
    assert third.response("15m", "00:00", "gainers", 0, third.cutoff + DAY).stale
