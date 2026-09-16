"""Explicit local startup, validation and schema generation. No service installation."""

import argparse
import asyncio
import fcntl
import json
import os
import signal
from contextlib import suppress
from pathlib import Path

import aiohttp
from aiohttp import web

from .mapping import compile_map, extract_roster, qualification_summary
from .models import RankingMap, RankingResponse
from .providers import PublicClient
from .service import RankingService, application
from .storage import Store, isolated_state


async def serve(args: argparse.Namespace) -> None:
    state = isolated_state(Path(args.state_dir), Path(args.original_state_dir))
    state.mkdir(parents=True, exist_ok=True)
    lock_path = state / "writer.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("ranking state already has an active writer") from exc
        mapping = RankingMap.model_validate_json(Path(args.mapping).read_text())
        store = Store(state, Path(args.original_state_dir))
        timeout = aiohttp.ClientTimeout(total=20, connect=10)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
            service = RankingService(store, mapping, PublicClient(session))
            runner = web.AppRunner(application(service), access_log=None)
            stopped = asyncio.Event()
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, stopped.set)
            try:
                await runner.setup()
                site = web.TCPSite(runner, "127.0.0.1", args.port)
                await site.start()
                await service.start()
                print(
                    json.dumps(
                        {
                            "event": "started",
                            "state": str(state),
                            "addresses": runner.addresses,
                            "mapVersion": mapping.version,
                        }
                    ),
                    flush=True,
                )
                if args.run_seconds:
                    with suppress(TimeoutError):
                        await asyncio.wait_for(stopped.wait(), args.run_seconds)
                else:
                    await stopped.wait()
            finally:
                await service.close()
                await runner.cleanup()
                store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Isolated public perpetual rankings")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("serve", help="run a dedicated collector and loopback read API")
    run.add_argument("--mapping", required=True)
    run.add_argument(
        "--state-dir",
        default=os.environ.get(
            "PREP_WATCHDECK_RANKING_STATE_DIR",
            str(Path.home() / ".local/share/prep-watchdeck-ranking"),
        ),
    )
    run.add_argument(
        "--original-state-dir",
        default=os.environ.get(
            "PREP_WATCHDECK_MARKET_STATE_DIR",
            str(Path.home() / ".local/share/prep-watchdeck-market"),
        ),
    )
    run.add_argument("--port", type=int, default=8769)
    run.add_argument("--run-seconds", type=int, default=0)
    validate = commands.add_parser("validate-map")
    validate.add_argument("path")
    validate.add_argument(
        "--require-reviewed",
        action="store_true",
        help="require identity, reference, quantity and Widget reviews",
    )
    validate.add_argument(
        "--require-ranking-qualified",
        action="store_true",
        help="require asset identity and fixed-reference classification; report other reviews",
    )
    schema = commands.add_parser("schema")
    schema.add_argument("--kind", choices=("map", "response"), default="response")
    roster = commands.add_parser("export-roster", help="read only original instrument identity")
    roster.add_argument("path")
    compile_command = commands.add_parser(
        "compile-map", help="validate reviewed decisions against roster"
    )
    compile_command.add_argument("--roster", required=True)
    compile_command.add_argument("--decisions", required=True)
    args = parser.parse_args()
    if args.command == "serve":
        if not 0 <= args.port <= 65535 or not 0 <= args.run_seconds <= 86400:
            parser.error("port or duration outside allowed range")
        asyncio.run(serve(args))
    elif args.command == "validate-map":
        mapping = RankingMap.model_validate_json(Path(args.path).read_text())
        qualification = qualification_summary(mapping)
        print(
            json.dumps(
                {
                    "version": mapping.version,
                    "rows": len(mapping.rows),
                    "instruments": mapping.source_instrument_count,
                    **qualification,
                }
            )
        )
        if args.require_reviewed and not qualification["qualificationComplete"]:
            parser.exit(
                1,
                f"mapping qualification incomplete: {qualification['review']} review rows, "
                f"{qualification['quantityReview']} unreviewed original quantities, "
                f"{qualification['widgetReview']} unreviewed Widgets\n",
            )
        if args.require_ranking_qualified and not qualification["rankingQualified"]:
            parser.exit(
                1, f"ranking qualification incomplete: {qualification['review']} review rows\n"
            )
    elif args.command == "export-roster":
        print(json.dumps(extract_roster(Path(args.path)), ensure_ascii=False, indent=2))
    elif args.command == "compile-map":
        mapping = compile_map(
            json.loads(Path(args.roster).read_text()), json.loads(Path(args.decisions).read_text())
        )
        print(mapping.model_dump_json(by_alias=True, indent=2))
    else:
        model = RankingMap if args.kind == "map" else RankingResponse
        print(json.dumps(model.model_json_schema(by_alias=True), indent=2))


if __name__ == "__main__":
    main()
