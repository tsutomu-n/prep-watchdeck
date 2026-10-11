from datetime import UTC, datetime, timedelta

from prep_watchdeck_market.candle_recovery import RecoveryWindowRequest, _state
from prep_watchdeck_market.candle_recovery_state import RecoveryTargetDetail, RecoveryTargetIdentity


def test_bounded_state_retains_unresolved_targets_before_healthy_rows() -> None:
    """The only missing/error targets used to disappear behind 128 healthy rows."""
    now = datetime(2026, 10, 10, 12, tzinfo=UTC)
    details = [
        RecoveryTargetDetail(
            target=RecoveryTargetIdentity(
                venue_instrument_id=f"hyperliquid:ASSET{i}",
                venue_instrument_version_id=i + 1,
                definition_hash="a" * 64,
            ),
            missing_before=0,
            inserted=0,
            remaining=0,
        )
        for i in range(131)
    ]
    details[128] = details[128].model_copy(update={"remaining": 73, "missing_before": 73})
    details[129] = details[129].model_copy(update={"remaining": None})
    details[130] = details[130].model_copy(update={"error_code": "history_unavailable"})
    result = _state(
        run_id="a" * 32,
        started_at=now,
        finished_at=now,
        execution="partial",
        trigger="periodic",
        window=RecoveryWindowRequest(now - timedelta(hours=6), now),
        target_count=131,
        scanned_count=130,
        http_requests=1,
        missing_before=73,
        inserted=0,
        newly_present=0,
        remaining=None,
        failed_targets=1,
        deferred_targets=1,
        details=details,
        error_code="recovery_incomplete",
    )
    assert {d.target.venue_instrument_version_id for d in result.details[:3]} == {129, 130, 131}
    assert result.details_truncated is True
    assert len(result.details) == 128
    assert details[0].target.venue_instrument_version_id == 1
