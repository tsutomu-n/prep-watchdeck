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


@pytest.mark.parametrize("module", [candle_recovery, candle_endpoint_recovery])
@pytest.mark.parametrize("failure_phase", ["connect", "start", "finish"])
@pytest.mark.parametrize("error_type", [RecoveryStoreError, asyncio.CancelledError])
def test_database_failure_invalidates_prior_success_even_when_audit_write_fails(
    monkeypatch, tmp_path, module, failure_phase, error_type
):
    _isolate(monkeypatch, module, (_target(),))
    prefix = "candle-recovery" if module is candle_recovery else "candle-endpoint-recovery"

    async def run():
        if module is candle_recovery:
            return await module.CandleRecovery("unused", tmp_path).run(
                object(), module.recovery_window(datetime.now(UTC)), apply=True, trigger="periodic"
            )
        return await module.CandleEndpointRecovery("unused", tmp_path).run(object())

    first = asyncio.run(run())

    def fail(*_args, **_kwargs):
        raise error_type("database unavailable")

    async def fail_connect(*_args, **_kwargs):
        raise error_type("database unavailable")

    monkeypatch.setattr(module, "finish_recovery_run", fail)
    if failure_phase == "connect":
        monkeypatch.setattr(module, "_open_connection", fail_connect)
    elif failure_phase == "start":
        monkeypatch.setattr(module, "start_recovery_run", fail)
    with pytest.raises(error_type):
        asyncio.run(run())

    state = json.loads((tmp_path / "artifacts" / f"{prefix}-state.json").read_text())
    completed = json.loads((tmp_path / "artifacts" / f"{prefix}-latest-completed.json").read_text())
    assert state == completed
    assert completed["execution"] == "failed"
    assert completed["runId"] != first.run_id


def test_completed_file_failure_still_publishes_failed_current_state(monkeypatch, tmp_path):
    from prep_watchdeck_market import recovery_evidence

    _isolate(monkeypatch, candle_endpoint_recovery, (_target(),))
    recovery = candle_endpoint_recovery.CandleEndpointRecovery("unused", tmp_path)
    first = asyncio.run(recovery.run(object()))
    original_write = recovery_evidence.write_artifact_atomic

    def failed_completed_write(path, state):
        if path.name.endswith("-latest-completed.json"):
            raise OSError("completion file unavailable")
        original_write(path, state)

    monkeypatch.setattr(recovery_evidence, "write_artifact_atomic", failed_completed_write)
    with pytest.raises(OSError):
        asyncio.run(recovery.run(object()))
    state = json.loads((tmp_path / "artifacts/candle-endpoint-recovery-state.json").read_text())
    assert state["execution"] == "failed"
    assert state["runId"] != first.run_id


def test_candle_completion_timestamps_remain_ordered_if_wall_clock_moves_backward(
    monkeypatch, tmp_path
):
    _isolate(monkeypatch, candle_recovery, (_target(),))
    now = datetime(2026, 10, 10, 12, tzinfo=UTC)
    ticks = iter((now, now, now + timedelta(seconds=1), now))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return next(ticks)

    monkeypatch.setattr(candle_recovery, "datetime", Clock)
    result = asyncio.run(
        candle_recovery.CandleRecovery("unused", tmp_path).run(
            object(), candle_recovery.recovery_window(now), apply=True, trigger="periodic"
        )
    )
    assert result.started_at <= result.finished_at <= result.generated_at


@pytest.mark.parametrize("unsafe_kind", ["fifo", "symlink", "oversized"])
def test_previous_completion_read_is_bounded_and_requires_regular_file(
    monkeypatch, tmp_path, unsafe_kind
):
    import os
    import subprocess
    import sys

    _isolate(monkeypatch, candle_endpoint_recovery, (_target(),))
    recovery = candle_endpoint_recovery.CandleEndpointRecovery("unused", tmp_path)
    asyncio.run(recovery.run(object()))
    state_path = tmp_path / "artifacts/candle-endpoint-recovery-state.json"
    completed_path = tmp_path / "artifacts/candle-endpoint-recovery-latest-completed.json"
    if unsafe_kind == "fifo":
        completed_path.unlink()
        os.mkfifo(completed_path)
    elif unsafe_kind == "symlink":
        completed_path.unlink()
        completed_path.symlink_to(state_path)
    else:
        with completed_path.open("ab") as handle:
            handle.write(b" " * (8 * 1024 * 1024))
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; import sys; "
            "from prep_watchdeck_market.recovery_evidence import previous_completed_run_id; "
            "print(previous_completed_run_id(Path(sys.argv[1])))",
            str(state_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=2,
    )
    assert result.stdout.strip() == "None"
