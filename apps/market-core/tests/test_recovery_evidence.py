from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from prep_watchdeck_market import candle_endpoint_recovery, candle_recovery
from prep_watchdeck_market.candle_recovery_store import RecoveryStoreError, RecoveryTarget


def _isolate(monkeypatch, module, targets):
    audits = []

    class Connection:
        def close(self):
            pass

    async def open_connection(*_args, **_kwargs):
        return Connection()

    monkeypatch.setattr(module, "_open_connection", open_connection)
    monkeypatch.setattr(module, "start_recovery_run", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        module, "finish_recovery_run", lambda *a, **kw: audits.append({**kw, "finished_at": a[2]})
    )
    monkeypatch.setattr(module, "load_recovery_targets", lambda *_a, **_kw: targets, raising=False)
    if module is candle_endpoint_recovery:
        monkeypatch.setattr(module, "load_missing_endpoints", lambda *_a, **_kw: {})
    else:
        monkeypatch.setattr(module, "scan_missing_candles", lambda *_a, **_kw: ())
    return audits


def _target(index=1):
    return RecoveryTarget(
        index,
        "bitget",
        f"TEST{index}USDT",
        "a" * 64,
        datetime(2026, 1, 1, tzinfo=UTC),
        "TEST",
        "USDT",
        "USDT",
    )


def test_endpoint_completion_time_precedes_generation_and_matches_audit(monkeypatch, tmp_path):
    audits = _isolate(monkeypatch, candle_endpoint_recovery, (_target(),))
    now = datetime(2026, 10, 10, 12, tzinfo=UTC)

    def clock():
        nonlocal now
        now += timedelta(microseconds=1)
        return now

    recovery = candle_endpoint_recovery.CandleEndpointRecovery("unused", tmp_path, utc_clock=clock)
    result = asyncio.run(recovery.run(object()))
    assert result.execution == "succeeded"
    assert result.started_at <= result.finished_at <= result.generated_at
    completed = json.loads(
        (tmp_path / "artifacts/candle-endpoint-recovery-latest-completed.json").read_text()
    )
    assert completed["runId"] == result.run_id
    assert audits[-1]["status"] == completed["execution"] == "succeeded"
    assert audits[-1]["finished_at"] == result.finished_at


@pytest.mark.parametrize("module", [candle_recovery, candle_endpoint_recovery])
@pytest.mark.parametrize("changed", [False, True])
def test_completed_recovery_proves_full_roster_and_rejects_version_drift(
    monkeypatch, tmp_path, module, changed
):
    targets = tuple(_target(index) for index in range(1, 130))
    _isolate(monkeypatch, module, targets)
    rosters = iter([targets, (*targets[:-1], replace(targets[-1], version_id=1000))])
    if changed:
        monkeypatch.setattr(module, "load_recovery_targets", lambda *_a, **_kw: next(rosters))
    if module is candle_recovery:
        recovery = module.CandleRecovery("unused", tmp_path)
        result = asyncio.run(
            recovery.run(
                object(), module.recovery_window(datetime.now(UTC)), apply=True, trigger="periodic"
            )
        )
    else:
        recovery = module.CandleEndpointRecovery("unused", tmp_path)
        result = asyncio.run(recovery.run(object()))
    document = result.model_dump(mode="json", by_alias=True)
    assert document.get("evidence") is not None
    assert len(document["evidence"]["roster"]) == 129
    assert len(document["details"]) <= 128
    assert document["evidence"]["rosterUnchanged"] is not changed
    assert document["execution"] == ("partial" if changed else "succeeded")
    assert document["errorCode"] == ("recovery_roster_changed" if changed else None)


@pytest.mark.parametrize("module", [candle_recovery, candle_endpoint_recovery])
def test_latest_completed_survives_running_and_is_replaced_by_failed_run(
    monkeypatch, tmp_path, module
):
    _isolate(monkeypatch, module, (_target(),))
    prefix = "candle-recovery" if module is candle_recovery else "candle-endpoint-recovery"
    state_path = tmp_path / "artifacts" / f"{prefix}-state.json"
    completed_path = tmp_path / "artifacts" / f"{prefix}-latest-completed.json"

    async def run():
        if module is candle_recovery:
            return await module.CandleRecovery("unused", tmp_path).run(
                object(), module.recovery_window(datetime.now(UTC)), apply=True, trigger="periodic"
            )
        return await module.CandleEndpointRecovery("unused", tmp_path).run(object())

    first = asyncio.run(run())
    assert first.execution == "succeeded"

    def fail_scan(*_a, **_kw):
        running = json.loads(state_path.read_text())
        assert running["execution"] == "running"
        assert running["previousCompletedRunId"] == first.run_id
        assert json.loads(completed_path.read_text())["runId"] == first.run_id
        raise RecoveryStoreError("scan unavailable")

    monkeypatch.setattr(module, "load_recovery_targets", fail_scan)
    with pytest.raises(RecoveryStoreError):
        asyncio.run(run())
    failed = json.loads(completed_path.read_text())
    assert failed["execution"] == "failed"
    assert failed["runId"] != first.run_id
    assert json.loads(state_path.read_text()) == failed
