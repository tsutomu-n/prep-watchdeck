from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from prep_watchdeck_market.bundle_files import BundleError


def native_payload(close: str = "101") -> dict:
    return {
        "schema_version": 1,
        "evidence_kind": "synthetic",
        "snapshot_at": "2026-10-09T00:02:02Z",
        "window_start": "2026-10-09T00:01:00Z",
        "window_end": "2026-10-09T00:02:00Z",
        "instrument": {
            "venue": "bitget",
            "source_symbol": "TESTUSDT",
            "venue_instrument_version_id": 1,
            "definition_hash": "a" * 64,
            "valid_from": "2026-10-08T00:00:00Z",
            "valid_to": None,
            "quantity_unit": "base",
            "contract_multiplier": "1",
            "quote_asset": "USDT",
            "settle_asset": "USDT",
            "base_asset": "TEST",
            "market_type": "linear_perpetual",
            "catalog_payload_hash": "b" * 64,
            "catalog_observed_at": "2026-10-08T00:00:00Z",
            "funding_interval_seconds": 28800,
        },
        "groups": [
            {
                "group_id": "TEST",
                "venue_instrument_version_id": 1,
                "valid_from": "2026-10-08T00:00:00Z",
                "valid_to": None,
            }
        ],
        "capabilities": [
            {
                "venue": "bitget",
                "capability": "candles_1m",
                "available": True,
                "observed_at": "2026-10-08T00:00:00Z",
            }
        ],
        "candles": [
            {
                "venue_instrument_version_id": 1,
                "bucket_at": "2026-10-09T00:01:00Z",
                "open_price": "100",
                "high_price": "110",
                "low_price": "99",
                "close_price": close,
                "volume_base": "10",
                "volume_notional": "1000",
                "trade_count": 4,
                "finality": "confirmed",
                "source_at": None,
                "observed_at": "2026-10-09T00:02:01Z",
            }
        ],
        "states": [
            {
                "venue_instrument_version_id": 1,
                "bucket_at": "2026-10-09T00:01:00Z",
                "first_observed_at": "2026-10-09T00:01:02Z",
                "last_observed_at": "2026-10-09T00:01:50Z",
                "source_at": None,
                "status": "ready",
                "mark_price": "101",
                "best_bid": "100.9",
                "best_ask": "101.1",
                "open_interest_raw": "100",
                "open_interest_raw_unit": "base",
                "open_interest_base": "100",
            }
        ],
        "funding": [],
    }


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 10, 9, 0, 2, 4, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value


def record(journal, payload: dict, clock: Clock):
    from prep_watchdeck_market.research.models import ResearchPayload

    end = clock.value - timedelta(seconds=1)
    return journal.record(
        ResearchPayload.model_validate(payload),
        read_started_at=end - timedelta(seconds=1),
        read_completed_at=end,
        elapsed_seconds=1.0,
    )


def test_correction_is_immutable_and_asof_does_not_see_future(tmp_path: Path) -> None:
    from prep_watchdeck_market.research.journal import ObservationJournal, export_snapshot
    from prep_watchdeck_market.research.snapshot import verify_snapshot

    clock = Clock()
    with ObservationJournal(tmp_path / "journal", clock=clock) as journal:
        first = record(journal, native_payload(), clock)
        clock.value += timedelta(seconds=60)
        changed = native_payload("102")
        changed["snapshot_at"] = "2026-10-09T00:03:02Z"
        second = record(journal, changed, clock)
    bundle = export_snapshot(tmp_path / "journal", tmp_path / "export")
    past = verify_snapshot(bundle, cutoff=first.available_at)
    current = verify_snapshot(bundle, cutoff=second.available_at)
    assert len(past.observations) == 1
    assert past.rows("candles")[0]["close_price"] == "101"
    assert current.rows("candles")[0]["close_price"] == "102"
    assert first.payload_sha256 != second.payload_sha256
    assert past.replay_valid and current.replay_valid
    assert not past.observed_evidence


def test_tampering_and_missing_publication_receipt_fail_closed(tmp_path: Path) -> None:
    from prep_watchdeck_market.research.journal import ObservationJournal, export_snapshot
    from prep_watchdeck_market.research.snapshot import verify_snapshot

    clock = Clock()
    with ObservationJournal(tmp_path / "journal", clock=clock) as journal:
        receipt = record(journal, native_payload(), clock)
    bundle = export_snapshot(tmp_path / "journal", tmp_path / "export")
    payload = bundle / "observations" / f"{receipt.observation_id}.json"
    payload.write_bytes(payload.read_bytes().replace(b'"101"', b'"102"'))
    with pytest.raises(BundleError, match="research_hash_mismatch"):
        verify_snapshot(bundle)
    (tmp_path / "journal" / "receipts" / receipt.observation_id / "receipt.json").unlink()
    with pytest.raises(BundleError):
        export_snapshot(tmp_path / "journal", tmp_path / "export-2")


@pytest.mark.parametrize("fault", ["clock", "gap", "future", "missing_oi"])
def test_unqualified_evidence_keeps_reason(tmp_path: Path, fault: str) -> None:
    from prep_watchdeck_market.research.journal import ObservationJournal, export_snapshot
    from prep_watchdeck_market.research.snapshot import verify_snapshot

    clock = Clock()
    with ObservationJournal(tmp_path / "journal", clock=clock) as journal:
        data = native_payload()
        if fault == "missing_oi":
            data["states"][0]["open_interest_raw"] = None
        if fault == "future":
            data["states"][0]["last_observed_at"] = "2026-10-09T01:00:00Z"
        if fault == "clock":
            clock.value -= timedelta(seconds=10)
        record(journal, data, clock)
        if fault == "gap":
            clock.value += timedelta(seconds=300)
            data["snapshot_at"] = (clock.value - timedelta(seconds=2)).isoformat()
            record(journal, data, clock)
    result = verify_snapshot(export_snapshot(tmp_path / "journal", tmp_path / "export"))
    assert not result.qualified_for_ab
    assert result.reasons


def test_failed_read_is_preserved_and_lock_rejects_second_writer(tmp_path: Path) -> None:
    from prep_watchdeck_market.research.journal import ObservationJournal, export_snapshot
    from prep_watchdeck_market.research.snapshot import verify_snapshot

    clock = Clock()
    with ObservationJournal(tmp_path / "journal", clock=clock) as journal:
        record(journal, native_payload(), clock)
        with (
            pytest.raises(BundleError, match="research_writer_busy"),
            ObservationJournal(tmp_path / "journal", clock=clock),
        ):
            pass
        clock.value += timedelta(seconds=60)
        journal.record_failure("research_database_unavailable", started_at=clock.value)
    result = verify_snapshot(export_snapshot(tmp_path / "journal", tmp_path / "export"))
    assert "research_database_unavailable" in result.reasons
    assert not result.replay_valid


def test_invalid_identity_and_state_overlap_are_rejected(tmp_path: Path) -> None:
    from prep_watchdeck_market.research.journal import ObservationJournal

    clock = Clock()
    with ObservationJournal(tmp_path / "journal", clock=clock) as journal:
        data = native_payload()
        data["candles"][0]["venue_instrument_version_id"] = 2
        with pytest.raises(BundleError, match="research_identity_mismatch"):
            record(journal, data, clock)
    with (
        pytest.raises(BundleError, match="research_state_overlap"),
        ObservationJournal(tmp_path / "market" / "research", excluded_roots=(tmp_path / "market",)),
    ):
        pass


@pytest.mark.parametrize(
    "field", ["catalog_observed_at", "catalog_source_at", "group_created_at", "group_updated_at"]
)
def test_future_context_is_not_qualified(tmp_path: Path, field: str) -> None:
    from prep_watchdeck_market.research.journal import ObservationJournal, export_snapshot
    from prep_watchdeck_market.research.snapshot import verify_snapshot

    payload = native_payload()
    target = payload["instrument"] if field.startswith("catalog") else payload["groups"][0]
    target[field] = "2030-01-01T00:00:00Z"
    with ObservationJournal(tmp_path / "journal", clock=Clock()) as journal:
        record(journal, payload, Clock())
    checked = verify_snapshot(export_snapshot(tmp_path / "journal", tmp_path / "snapshots"))
    assert "research_future_context" in checked.reasons
    assert not checked.replay_valid
    assert not checked.qualified_for_ab
