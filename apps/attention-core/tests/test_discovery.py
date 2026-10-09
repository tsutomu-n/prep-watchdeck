import asyncio
import base64
from datetime import UTC, datetime

import pytest
from aiohttp.test_utils import TestClient, TestServer
from prep_watchdeck_ranking.models import Indicator, TurnoverComparison, TurnoverWindow
from test_inputs import MS, NOW, bundle, metric_row, ranked, ranking

from prep_watchdeck_attention.discovery import build_discovery_rows
from prep_watchdeck_attention.discovery_models import DiscoveryResponse
from prep_watchdeck_attention.features import build_feature_generation
from prep_watchdeck_attention.models import MINUTE, RawFeatureValue, canonical_json, content_digest
from prep_watchdeck_attention.service import AttentionService, application
from prep_watchdeck_attention.storage import AttentionStore


def discovery_generation(cutoff=MS, *, ratio=3, missing=False, direction=3):
    comparison = TurnoverComparison(
        **{
            name: TurnoverWindow(
                anchor=cutoff - day * 1440 * MINUTE - 15 * MINUTE,
                cutoff=cutoff - day * 1440 * MINUTE,
                quote_turnover=300 if day == 0 else 100,
                status="ready",
            )
            for day, name in enumerate(("current", "previous_day", "two_days_ago"))
        },
        previous_day_ratio=Indicator(value=ratio, status="ready"),
        two_days_ago_ratio=Indicator(
            value=None if missing else ratio,
            status="history_missing" if missing else "ready",
        ),
    )
    source = ranking((ranked().model_copy(update={"turnover_comparison": comparison}),))
    source = source.model_copy(
        update={
            "cutoff": cutoff,
            "generated_at": cutoff,
            "generation_id": f"ranking-{cutoff}",
        }
    )
    market = bundle(rows=(metric_row(value=1),))
    now = datetime.fromtimestamp((cutoff + 10_000) / 1000, UTC)
    inputs, features = build_feature_generation(market, source, decision_at=now)
    price = (
        RawFeatureValue(value=direction, status="ready", source="fixture", unit="percent")
        if direction is not None
        else RawFeatureValue(value=None, status="missing", source="fixture", reason="price_missing")
    )
    features = tuple(row.model_copy(update={"reference_return15m": price}) for row in features)
    rows = build_discovery_rows(market, source, inputs, features)
    return inputs, rows


def test_policy_uses_both_same_clock_ratios_and_retains_unknown_price():
    _, rows = discovery_generation(direction=None)
    assert rows[0].state == "matched" and rows[0].direction == "unknown"
    assert rows[0].native[0].oi_change["15m"].status == "ready"
    assert rows[0].native[0].funding_rate_per_hour.observations[0].payload_hash == "fixture"
    _, missing = discovery_generation(missing=True)
    assert missing[0].state == "unknown" and missing[0].reason == "comparison_unavailable"
    _, low = discovery_generation(ratio=2.99)
    assert low[0].state == "not_matched"
    # A ready ratio without yesterday's exact same-clock window is not comparable.
    comparison = rows[0].turnover_comparison.model_copy(
        update={
            "previous_day": rows[0].turnover_comparison.current,
        }
    )
    inputs, features = build_feature_generation(bundle(), ranking(), decision_at=NOW)
    source = ranking((ranked().model_copy(update={"turnover_comparison": comparison}),))
    assert build_discovery_rows(bundle(), source, inputs, features)[0].state == "unknown"


def test_episode_transition_direction_duplicate_and_raw_replacement(tmp_path):
    store = AttentionStore(tmp_path / "attention")
    try:
        store.save_discovery(*discovery_generation(ratio=2))
        store.save_discovery(*discovery_generation(MS + MINUTE))
        first = store.discovery_response()
        assert first.rows[0].confirmation == "new"
        episode_id = first.episodes[0].id
        store.save_discovery(*discovery_generation(MS + 2 * MINUTE, direction=-3))
        current = store.discovery_response()
        assert current.rows[0].confirmation == "continuing"
        assert current.episodes[0].id == episode_id
        assert current.episodes[0].direction == "down"
        assert current.episodes[0].consecutive_confirmations == 2
        assert current.episodes[0].observed_duration_ms == MINUTE
        inputs, rows = discovery_generation(MS + 2 * MINUTE, ratio=1)
        assert not store.save_discovery(inputs, rows)
        repeated = store.discovery_response()
        assert repeated.rows[0].state == "matched"
        assert repeated.rows[0].turnover_comparison.previous_day_ratio.value == 1
        assert repeated.episodes == current.episodes
        assert store.connection.execute("SELECT COUNT(*) FROM discovery_latest").fetchone()[0] == 1
        assert store.connection.execute("SELECT COUNT(*) FROM feature_rows").fetchone()[0] == 0
        store.save_discovery(*discovery_generation(MS + 3 * MINUTE, ratio=2))
        ended = store.discovery_response().episodes[0]
        assert ended.state == "ended" and ended.end_reason == "condition_not_matched"
    finally:
        store.close()


def test_missing_gap_and_restart_reconfirm_without_counting_blank_time(tmp_path):
    store = AttentionStore(tmp_path / "attention")
    try:
        store.save_discovery(*discovery_generation())
        initial = store.discovery_response().episodes[0]
        assert initial.start_kind == "initial_confirmation"
        store.save_discovery(*discovery_generation(MS + MINUTE, missing=True))
        missing = store.discovery_response().episodes[0]
        assert missing.state == "interrupted" and missing.ended_at is None
        store.save_discovery(*discovery_generation(MS + 3 * MINUTE))
        resumed = store.discovery_response()
        assert resumed.rows[0].confirmation == "reconfirmation"
        assert resumed.episodes[0].id == initial.id
        assert resumed.episodes[0].first_observed_at == initial.first_observed_at
        assert resumed.episodes[0].consecutive_confirmations == 1
        assert resumed.episodes[0].observed_duration_ms == 0
        store.interrupt_discovery("ranking_unavailable")
        assert store.discovery_response().rows[0].state == "unknown"
        inputs, _ = discovery_generation(MS + 4 * MINUTE)
        store.save_discovery(inputs, ())
        absent = store.discovery_response()
        assert absent.status == "partial" and absent.rows == ()
        assert absent.episodes[0].state == "interrupted"
    finally:
        store.close()
    restarted = AttentionStore(tmp_path / "attention")
    try:
        restarted.save_discovery(*discovery_generation(MS + 5 * MINUTE), restarted=True)
        current = restarted.discovery_response()
        assert current.rows[0].confirmation == "reconfirmation"
        assert current.episodes[0].id == initial.id
        assert current.episodes[0].observed_duration_ms == 0
        restarted.save_discovery(*discovery_generation(MS + 6 * MINUTE))
        assert restarted.discovery_response().episodes[0].observed_duration_ms == MINUTE
    finally:
        restarted.close()


def test_only_comparable_nonmatch_to_match_is_new_and_identity_not_inherited(tmp_path):
    store = AttentionStore(tmp_path / "attention")
    try:
        store.save_discovery(*discovery_generation(ratio=2))
        store.save_discovery(*discovery_generation(MS + 2 * MINUTE))
        assert store.discovery_response().rows[0].confirmation == "reconfirmation"
        inputs, rows = discovery_generation(MS + 3 * MINUTE)
        rows = (rows[0].model_copy(update={"identity_key": "different-exact-version"}),)
        previous_id = store.discovery_response().episodes[0].id
        store.save_discovery(inputs, rows)
        current = store.discovery_response()
        assert current.rows[0].confirmation == "initial_confirmation"
        assert current.episodes[0].id != previous_id
        old = next(episode for episode in current.episodes if episode.id == previous_id)
        assert old.state == "ended" and old.end_reason == "identity_changed"
    finally:
        store.close()


@pytest.mark.parametrize("interruption", ["ineligible", "missing_row", "missing_comparison"])
def test_same_cutoff_missing_observation_immediately_breaks_continuity(tmp_path, interruption):
    store = AttentionStore(tmp_path / "attention")
    try:
        inputs, rows = discovery_generation()
        store.save_discovery(inputs, rows)
        first = store.discovery_response().episodes[0]
        if interruption == "ineligible":
            market = bundle()
            market = type(market)(
                market.service,
                market.universe.model_copy(update={"items": ()}),
                market.metrics,
                market.metrics_error,
            )
            source = ranking(
                (
                    ranked().model_copy(
                        update={
                            "turnover_comparison": rows[0].turnover_comparison,
                        }
                    ),
                )
            )
            refreshed_inputs, features = build_feature_generation(market, source, decision_at=NOW)
            refreshed_rows = build_discovery_rows(market, source, refreshed_inputs, features)
            assert refreshed_rows[0].identity_key == rows[0].identity_key
            assert not refreshed_rows[0].originals[0].current
        elif interruption == "missing_comparison":
            refreshed_inputs, refreshed_rows = discovery_generation(missing=True)
        else:
            refreshed_inputs, refreshed_rows = inputs, ()
        assert not store.save_discovery(refreshed_inputs, refreshed_rows)
        absent = store.discovery_response()
        assert absent.status == "partial"
        if absent.rows:
            assert absent.rows[0].state == "unknown" and absent.rows[0].confirmation is None
        assert absent.episodes[0].state == "interrupted"
        assert absent.episodes[0].ended_at is None
        # A valid refresh at the same cutoff cannot reconfirm or undo the missing observation.
        assert not store.save_discovery(inputs, rows)
        assert store.discovery_response().rows[0].state == "unknown"
        store.save_discovery(*discovery_generation(MS + MINUTE))
        resumed = store.discovery_response()
        assert resumed.rows[0].confirmation == "reconfirmation"
        assert resumed.episodes[0].id == first.id
        assert resumed.episodes[0].consecutive_confirmations == 1
        assert resumed.episodes[0].observed_duration_ms == 0
    finally:
        store.close()


def test_retention_preserves_active_and_pagination_is_stable(tmp_path, monkeypatch):
    import prep_watchdeck_attention.discovery_storage as storage

    monkeypatch.setattr(storage, "MAX_ENDED_EPISODES", 2)
    store = AttentionStore(tmp_path / "attention")
    try:
        for index in range(7):
            store.save_discovery(
                *discovery_generation(MS + index * MINUTE, ratio=3 if index % 2 == 0 else 1)
            )
        response = store.discovery_response(limit=1)
        assert response.episodes[0].state == "active"
        assert response.next_cursor is not None
        second = store.discovery_response(limit=1, cursor=response.next_cursor)
        assert second.episodes[0].id != response.episodes[0].id
        assert len(store.discovery_response().episodes) == 3
        assert store.discovery_response().history_available_from == MS + 2 * MINUTE + 10_000
        with pytest.raises(ValueError, match="cursor"):
            store.discovery_response(asset_ids=("asset:BTC",), cursor=response.next_cursor)
        store.save_discovery(*discovery_generation(MS + storage.HISTORY_RETENTION_MS + 8 * MINUTE))
        remaining = store.discovery_response().episodes
        assert len(remaining) == 1 and remaining[0].state == "active"
        assert remaining[0].first_observed_at == response.episodes[0].first_observed_at
    finally:
        store.close()


def test_discovery_get_is_read_only_filtered_and_validates_queries(tmp_path):
    from test_service import Reader

    from prep_watchdeck_attention.config import AttentionSettings

    async def run():
        settings = AttentionSettings(
            tmp_path / "attention", tmp_path / "market", tmp_path / "ranking"
        )
        store = AttentionStore(settings.state_dir)
        reader = Reader()
        original_read = reader.read

        async def read(*, now_ms):
            source = await original_read(now_ms=now_ms)
            _, rows = discovery_generation()
            return source.model_copy(
                update={
                    "rows": (
                        source.rows[0].model_copy(
                            update={
                                "turnover_comparison": rows[0].turnover_comparison,
                            }
                        ),
                    )
                }
            )

        reader.read = read
        service = AttentionService(
            settings,
            store,
            ranking_reader=reader,
            market_reader=lambda path, now: bundle(),
            clock=lambda: MS,
        )
        client = TestClient(TestServer(application(service)))
        await client.start_server()
        try:
            initial = await client.get("/discovery")
            assert initial.status == 503
            DiscoveryResponse.model_validate(await initial.json())
            assert await service.generate_once(now=NOW)
            writes = store.connection.total_changes
            for path in (
                "/discovery",
                "/discovery?assetId=asset%3ABTC&limit=1",
                "/discovery?assetId=missing",
            ):
                result = await client.get(path)
                assert result.status == 200 and result.headers["Cache-Control"] == "no-store"
                payload = await result.json()
                DiscoveryResponse.model_validate(payload)
                assert len(payload["rows"]) == (0 if path.endswith("missing") else 1)
                if payload["rows"]:
                    assert payload["rows"][0]["state"] == "matched"
                    assert payload["episodes"][0]["startKind"] == "initial_confirmation"
            assert store.connection.total_changes == writes and reader.count == 1
            for query in (
                "limit=51",
                "cursor=bad!",
                "limit=1&limit=2",
                "assetId=a&assetId=b&assetId=c&assetId=d&assetId=e",
                "foo=x",
                "assetId=a&assetId=a",
                "cursor="
                + base64.urlsafe_b64encode(
                    canonical_json([10**100, "x", content_digest([])]).encode()
                ).decode(),
            ):
                invalid = await client.get("/discovery?" + query)
                assert invalid.status == 400
            await client.get("/discovery", headers={"Host": "malicious.example"})
            reader.fail = True
            assert not await service.generate_once(now=NOW)
            failed = await client.get("/discovery")
            payload = await failed.json()
            assert payload["status"] == "stale" and payload["rows"][0]["state"] == "unknown"
            assert payload["episodes"][0]["state"] == "interrupted"
        finally:
            await client.close()
            store.close()

    asyncio.run(run())
