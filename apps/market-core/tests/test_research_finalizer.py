from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from prep_watchdeck_market.bundle_files import sha256
from prep_watchdeck_market.research.journal import ObservationJournal, export_snapshot
from tests.test_research_journal import Clock, native_payload, record


def study(tmp_path: Path) -> tuple[Path, Path]:
    source, output = tmp_path / "study", tmp_path / "finalized"
    source.mkdir()
    output.mkdir()
    with ObservationJournal(source / "daily/journal", clock=Clock()) as journal:
        data = native_payload()
        data["window_start"] = "2026-10-09T00:00:00Z"
        record(journal, data, Clock())
    export_snapshot(source / "daily/journal", source / "daily/snapshots")
    (source / "capture-config.json").write_text(json.dumps({"samples": 1}))
    (output / "capture-completion.json").write_text(
        json.dumps(
            {
                "inputRoot": str(source),
                "serviceResult": "exit-code",
                "exitCode": "exited",
                "exitStatus": 3,
                "evidence": "isolated test process receipt",
            }
        )
    )
    return source, output


def hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): sha256(path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    }


def test_quality_exit_three_is_complete_but_ineligible(tmp_path: Path) -> None:
    from prep_watchdeck_market.research.finalizer import finalize_capture

    source, output = study(tmp_path)
    before = hashes(source)
    result = finalize_capture(source, output, deadline_seconds=30)
    assert result["capture_complete"] is True
    assert result["quality_eligible"] is False
    assert result["evaluation_status"] == "NOT_RUN"
    assert result["finalization_status"] == "COMPLETE"
    reasons = result["quality_reasons"]
    assert isinstance(reasons, list)
    assert "research_candle_gap" in reasons
    assert hashes(source) == before
    assert finalize_capture(source, output, deadline_seconds=30) == result


def test_finalizer_deadline_preserves_input_and_reports_incomplete(tmp_path: Path) -> None:
    from prep_watchdeck_market.research.finalizer import finalize_capture

    source, output = study(tmp_path)
    before = hashes(source)
    result = finalize_capture(source, output, deadline_seconds=0)
    assert result["finalization_status"] == "INCOMPLETE"
    assert result["evaluation_status"] == "NOT_RUN"
    assert result["phase"] == "input_manifest"
    assert hashes(source) == before
    completed = finalize_capture(source, output, deadline_seconds=30)
    assert completed["finalization_status"] == "COMPLETE"
    assert completed["quality_eligible"] is False


def process_running(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except FileNotFoundError:
        return False


def test_finalizer_group_check_accepts_arbitrary_process_name_bytes():
    from prep_watchdeck_market.research import finalizer

    worker = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; import time; "
            "Path('/proc/self/comm').write_bytes(b'\\xff\\n'); "
            "print('ready', flush=True); time.sleep(3)",
        ],
        stdout=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        assert worker.stdout is not None
        assert worker.stdout.readline() == b"ready\n"
        assert finalizer._group_running(worker.pid) is True
    finally:
        worker.kill()
        worker.communicate(timeout=5)


@pytest.mark.parametrize("stop", ["sigterm", "sigterm_detached", "sigkill", "deadline"])
def test_finalizer_worker_lifetime_keeps_writer_lock_and_preserves_inputs(tmp_path, stop):
    source, output = study(tmp_path)
    before = hashes(source)
    worker = tmp_path / "slow-worker"
    ready = output / "grandchild-ready"
    grandchild_code = (
        "import pathlib, signal, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"pathlib.Path({str(ready)!r}).touch(); time.sleep(3)"
        if stop == "sigterm_detached"
        else "import time; time.sleep(3)"
    )
    worker.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, subprocess, sys, time\n"
        "from prep_watchdeck_market.research.finalizer import _worker\n"
        f"root = pathlib.Path({str(output)!r})\n"
        f"grandchild = subprocess.Popen([sys.executable, '-c', {grandchild_code!r}], "
        f"stdout={subprocess.DEVNULL if stop == 'sigterm_detached' else None}, "
        f"stderr={subprocess.DEVNULL if stop == 'sigterm_detached' else None})\n"
        + (
            f"while not pathlib.Path({str(ready)!r}).exists(): time.sleep(0.01)\n"
            if stop == "sigterm_detached"
            else ""
        )
        + "(root / 'worker-pids.json').write_text(json.dumps([os.getpid(), grandchild.pid]))\n"
        "time.sleep(3)\n"
        "grandchild.wait()\n"
        "args = dict(zip(sys.argv[3::2], sys.argv[4::2]))\n"
        "_worker(args['--phase'], pathlib.Path(args['--snapshot']), "
        "pathlib.Path(args['--source']), pathlib.Path(args['--output']))\n"
    )
    worker.chmod(0o700)
    script = (
        "from pathlib import Path\n"
        "from prep_watchdeck_market.research import finalizer\n"
        f"finalizer.sys.executable = {str(worker)!r}\n"
        f"finalizer.finalize_capture(Path({str(source)!r}), Path({str(output)!r}), "
        f"deadline_seconds={1 if stop == 'deadline' else 30})\n"
    )
    parent = subprocess.Popen(
        [sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    pids = []
    try:
        deadline = time.monotonic() + 5
        receipt = output / "worker-pids.json"
        while not receipt.exists() and time.monotonic() < deadline:
            assert parent.poll() is None
            time.sleep(0.02)
        assert receipt.exists()
        pids = json.loads(receipt.read_text())
        if stop != "deadline":
            parent.send_signal(signal.SIGTERM if stop.startswith("sigterm") else signal.SIGKILL)
        parent.communicate(timeout=5)
        with (output / "finalizer.lock").open("rb") as lock:
            if stop == "sigkill":
                assert process_running(pids[0])
                with pytest.raises(BlockingIOError):
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                deadline = time.monotonic() + 5
                while any(process_running(pid) for pid in pids) and time.monotonic() < deadline:
                    time.sleep(0.02)
            assert not any(process_running(pid) for pid in pids)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert hashes(source) == before
        if stop != "sigkill":
            summary = json.loads((output / "summary.json").read_text())
            assert summary["finalization_status"] == "INCOMPLETE"
            assert summary["reason"] == "deadline_or_interruption"
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.communicate(timeout=5)
        for pid in pids:
            if process_running(pid):
                os.kill(pid, signal.SIGKILL)


def test_finalizer_does_not_lose_signal_at_worker_completion(tmp_path, monkeypatch):
    from prep_watchdeck_market.research import finalizer

    original = subprocess.CompletedProcess

    def completion(*arguments, **kwargs):
        os.kill(os.getpid(), signal.SIGTERM)
        return original(*arguments, **kwargs)

    monkeypatch.setattr(finalizer.subprocess, "CompletedProcess", completion)
    with (tmp_path / "owned.lock").open("wb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(KeyboardInterrupt):
            finalizer._run_phase(
                [sys.executable, "-c", "pass"], timeout=2, lock_descriptor=lock.fileno()
            )
