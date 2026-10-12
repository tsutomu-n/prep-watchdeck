"""Run Attention with only its own state writable; requires Linux bubblewrap."""

import argparse
import os
import shutil
import sys
from pathlib import Path

from prep_watchdeck_attention.config import AttentionSettings


def build_command(settings: AttentionSettings, run_seconds: int, executable: str) -> list[str]:
    if not 0 <= run_seconds <= 86400:
        raise ValueError("duration must be 0..86400 seconds")
    command = [
        executable,
        "--ro-bind",
        "/",
        "/",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--unshare-pid",
        "--die-with-parent",
        "--clearenv",
        "--setenv",
        "PATH",
        "/usr/bin:/bin",
        "--setenv",
        "PYTHONDONTWRITEBYTECODE",
        "1",
    ]
    # Mount after /tmp so explicitly supplied scratch inputs remain visible and read-only.
    for source in (settings.market_state_dir, settings.ranking_state_dir):
        source = source.expanduser().resolve(strict=True)
        command.extend(("--ro-bind", str(source), str(source)))
    command.extend(("--bind", str(settings.state_dir), str(settings.state_dir)))
    command.extend(
        (
            sys.executable,
            "-m",
            "prep_watchdeck_attention.cli",
            "serve",
            "--state-dir",
            str(settings.state_dir),
            "--market-state-dir",
            str(settings.market_state_dir.expanduser().resolve()),
            "--ranking-state-dir",
            str(settings.ranking_state_dir.expanduser().resolve()),
            "--ranking-port",
            str(settings.ranking_port),
            "--port",
            str(settings.port),
            "--run-seconds",
            str(run_seconds),
        )
    )
    return command


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--market-state-dir", required=True, type=Path)
    parser.add_argument("--ranking-state-dir", required=True, type=Path)
    parser.add_argument("--ranking-port", default=8769, type=int)
    parser.add_argument("--port", default=8770, type=int)
    parser.add_argument("--run-seconds", default=0, type=int)
    args = parser.parse_args()
    try:
        settings = AttentionSettings(
            args.state_dir,
            args.market_state_dir,
            args.ranking_state_dir,
            ranking_port=args.ranking_port,
            port=args.port,
        )
        executable = shutil.which("bwrap")
        if executable is None:
            raise ValueError("bubblewrap is required; nothing was started")
        command = build_command(settings, args.run_seconds, executable)
        settings.state_dir.mkdir(parents=True, exist_ok=True)
        os.execv(executable, command)
    except (ValueError, OSError) as cause:
        parser.error(str(cause))


if __name__ == "__main__":
    main()
