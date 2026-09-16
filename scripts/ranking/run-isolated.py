"""Launch the collector with only its dedicated state writable; never installs a unit."""

import argparse
import os
import shutil
import sys
from pathlib import Path

from prep_watchdeck_ranking.storage import isolated_state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--original-state-dir", required=True)
    parser.add_argument("--mapping", required=True)
    parser.add_argument("--port", type=int, default=8769)
    parser.add_argument("--run-seconds", type=int, default=0)
    args = parser.parse_args()
    executable = shutil.which("bwrap")
    if executable is None:
        parser.error("bubblewrap is required for the write restriction; nothing was started")
    state = isolated_state(Path(args.state_dir), Path(args.original_state_dir))
    mapping = Path(args.mapping).expanduser().resolve(strict=True)
    original = Path(args.original_state_dir).expanduser().resolve()
    if not 1024 <= args.port <= 65535 or args.port in (5432, 55432):
        parser.error("use a dedicated unprivileged ranking API port")
    if not 0 <= args.run_seconds <= 86400:
        parser.error("duration outside allowed range")
    state.mkdir(parents=True, exist_ok=True)
    command = [
        executable,
        "--ro-bind",
        "/",
        "/",
        "--bind",
        str(state),
        str(state),
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
        sys.executable,
        "-m",
        "prep_watchdeck_ranking.cli",
        "serve",
        "--state-dir",
        str(state),
        "--original-state-dir",
        str(original),
        "--mapping",
        str(mapping),
        "--port",
        str(args.port),
        "--run-seconds",
        str(args.run_seconds),
    ]
    os.execv(executable, command)


if __name__ == "__main__":
    main()
