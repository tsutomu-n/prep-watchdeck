"""Fresh prices cannot renew an unverified listing roster."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from prep_watchdeck_ranking.mapping import extract_roster
from prep_watchdeck_ranking.models import RosterHealth
from prep_watchdeck_ranking.ranking import Generation
from prep_watchdeck_ranking.storage import Store

from .conftest import CUTOFF, mapping


def artifacts(path: Path) -> None:
    path.mkdir()
    stamp = datetime.fromtimestamp(CUTOFF / 1000, UTC).isoformat()
    item = {
        "venue": "bitget",
        "venueInstrumentId": "bitget:BTC",
        "venueInstrumentVersionId": 1,
        "sourceSymbol": "BTCUSDT",
        "baseAsset": "BTC",
        "quoteAsset": "USDT",
        "settleAsset": "USDT",
        "collateralAsset": "USDT",
        "active": True,
        "marketType": "linear_perpetual",
        "groupId": "BTC",
        "mappingMethod": "reviewed",
    }
    (path / "universe-snapshot.json").write_text(
        json.dumps(
            {
                "generatedAt": stamp,
                "status": "ready",
                "qualityReasons": [],
                "items": [item],
            }
        )
    )
    (path / "service-state.json").write_text(
        json.dumps(
            {
                "generatedAt": stamp,
                "status": "ready",
                "qualityReasons": [],
                "catalog": {"status": "ready", "latestAt": stamp, "maxAgeSeconds": 1800},
                "collectors": [
                    {
                        "runKind": "catalog",
                        "status": "succeeded",
                        "completedAt": stamp,
                        "recordsReceived": 1,
                        "recordsWritten": 1,
                    }
                ],
            }
        )
    )


def test_current_complete_identity_renews_observation_not_qualification(
    tmp_path: Path,
    store: Store,
) -> None:
    from prep_watchdeck_ranking.roster import check_roster

    root = tmp_path / "artifacts"
    artifacts(root)
    old = mapping("BTC").model_copy(
        update={
            "roster_generated_at": CUTOFF - 3 * 86_400_000,
            "roster_fingerprint": extract_roster(root / "universe-snapshot.json")[
                "catalogFingerprint"
            ],
        }
    )
    health = check_roster(old, root, CUTOFF + 8000)
    assert health.status == "ready"
    assert health.catalog_observed_at == CUTOFF
    generation = Generation(
        old,
        CUTOFF,
        CUTOFF + 8000,
        store,
        roster_checked_at=health.catalog_observed_at,
        roster_health=health,
    )
    result = generation.response("15m", "00:00", "turnover", 0, CUTOFF + 8000)
    assert not result.roster_stale
    assert result.roster_generated_at == CUTOFF
    assert old.roster_generated_at == CUTOFF - 3 * 86_400_000
    assert old.version == "map-v1"
    assert old.verified_at == CUTOFF
    assert generation.response("15m", "00:00", "turnover", 0, CUTOFF + 86_400_001).roster_stale
    failed = Generation(
        old,
        CUTOFF,
        CUTOFF + 8000,
        store,
        roster_checked_at=health.catalog_observed_at,
        roster_health=RosterHealth(status="source_incomplete"),
    )
    assert failed.response("15m", "00:00", "turnover", 0, CUTOFF + 8000).roster_stale


def test_price_partial_does_not_invalidate_complete_unchanged_catalog(tmp_path: Path) -> None:
    from prep_watchdeck_ranking.roster import check_roster

    root = tmp_path / "artifacts"
    artifacts(root)
    adopted = mapping("BTC").model_copy(
        update={
            "roster_fingerprint": extract_roster(root / "universe-snapshot.json")[
                "catalogFingerprint"
            ]
        }
    )
    universe = json.loads((root / "universe-snapshot.json").read_text())
    universe.update(status="partial", qualityReasons=["contains_non_ready_instruments"])
    universe["items"][0].update(
        quality="partial", qualityReasons=["source_error_incomplete_source_row"]
    )
    service = json.loads((root / "service-state.json").read_text())
    service.update(status="partial", qualityReasons=["l1_partial"])
    service["l1"] = {"status": "partial"}
    (root / "universe-snapshot.json").write_text(json.dumps(universe))
    (root / "service-state.json").write_text(json.dumps(service))
    health = check_roster(adopted, root, CUTOFF + 8000)
    assert health.status == "ready"
    assert health.catalog_observed_at == CUTOFF
    assert health.market_data_issue_ids == ("bitget:BTC",)


@pytest.mark.parametrize(
    "failure",
    [
        "changed_version",
        "new_listing",
        "partial",
        "old_catalog",
        "wrong_count",
        "missing",
        "quality_warning",
        "future",
        "mixed_generation",
        "removed_listing",
    ],
)
def test_unverified_roster_cannot_be_made_fresh(tmp_path: Path, failure: str) -> None:
    from prep_watchdeck_ranking.roster import check_roster

    root = tmp_path / "artifacts"
    artifacts(root)
    adopted = mapping("BTC").model_copy(
        update={
            "roster_fingerprint": extract_roster(root / "universe-snapshot.json")[
                "catalogFingerprint"
            ],
        }
    )
    universe = json.loads((root / "universe-snapshot.json").read_text())
    service = json.loads((root / "service-state.json").read_text())
    if failure == "changed_version":
        universe["items"][0]["venueInstrumentVersionId"] = 2
    elif failure == "new_listing":
        universe["items"].append({**universe["items"][0], "venueInstrumentId": "bitget:ETH"})
        service["collectors"][0].update(recordsReceived=2, recordsWritten=2)
    elif failure == "removed_listing":
        adopted = mapping("BTC", "ETH")
    elif failure == "mixed_generation":
        universe["generatedAt"] = datetime.fromtimestamp((CUTOFF - 1000) / 1000, UTC).isoformat()
    elif failure == "partial":
        service["catalog"]["status"] = "partial"
    elif failure == "old_catalog":
        service["catalog"]["latestAt"] = "2026-09-01T00:00:00Z"
    elif failure == "wrong_count":
        service["collectors"][0]["recordsReceived"] = 2
    elif failure == "quality_warning":
        universe["qualityReasons"] = ["catalog_incomplete"]
    elif failure == "future":
        universe["generatedAt"] = "2099-01-01T00:00:00Z"
    (root / "universe-snapshot.json").write_text(json.dumps(universe))
    (root / "service-state.json").write_text(json.dumps(service))
    if failure == "missing":
        (root / "universe-snapshot.json").unlink()
    health = check_roster(adopted, root, CUTOFF + 8000)
    assert health.status != "ready"
    if failure == "changed_version":
        assert health.status == "review_required"
        assert health.changed_instrument_ids == ("bitget:BTC",)
    if failure == "mixed_generation":
        assert health.status == "source_invalid"
    if failure == "removed_listing":
        assert health.status == "review_required"
        assert health.removed_instrument_ids == ("bitget:ETH",)
    if failure == "new_listing":
        assert health.status == "review_required"
        assert health.added_instrument_ids == ("bitget:ETH",)
