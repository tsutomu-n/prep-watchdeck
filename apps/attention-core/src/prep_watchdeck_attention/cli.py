"""Explicit local commands; no Provider acquisition, unit installation or selection writes."""

import argparse
import asyncio
import json
import os
import re
import signal
import time
from contextlib import suppress
from pathlib import Path

import aiohttp
from aiohttp import web

from .config import AttentionSettings
from .models import AttentionResponse, CandidatePolicy
from .outcomes import FixtureBarReader, settle_generation_outcomes
from .service import AttentionService, application
from .stable_files import read_stable_regular_file
from .storage import AttentionStore

SIGNALS = (
    "reference-abs-return-15m",
    "reference-abs-return-1h",
    "turnover-ratio",
    "movement",
    "activity",
    "positioning",
    "dislocation",
    "confluence",
)
BASELINE_SIGNALS = frozenset(SIGNALS[:3])


def freeze_default_family(
    store: AttentionStore, family_id: str, *, delta: float = 0.1
) -> tuple[CandidatePolicy, ...]:
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", family_id):
        raise ValueError("invalid family ID")
    existing = store.policies(family_id)
    if existing:
        if {(p.signal, p.horizon_minutes) for p in existing} != {
            (signal, horizon) for signal in SIGNALS for horizon in (15, 60)
        } or any(p.minimum_practical_delta != delta for p in existing):
            raise ValueError("family already frozen with different settings; use a new family ID")
        return existing
    now = int(time.time() * 1000)
    policies = tuple(
        CandidatePolicy(
            id=f"{family_id}:{signal}:{horizon}m",
            family_id=family_id,
            signal=signal,
            version="attention-reference-baselines-v1"
            if signal in BASELINE_SIGNALS
            else "attention-components-v1",
            frozen_at=now,
            horizon_minutes=horizon,
            minimum_practical_delta=delta,
        )
        for signal in SIGNALS
        for horizon in (15, 60)
    )
    store.freeze_family(policies)
    return store.policies(family_id)


def _settings(args: argparse.Namespace) -> AttentionSettings:
    return AttentionSettings(
        Path(args.state_dir),
        Path(args.market_state_dir),
        Path(args.ranking_state_dir),
        ranking_port=args.ranking_port,
        port=args.port,
    )


def _store(settings: AttentionSettings) -> AttentionStore:
    return AttentionStore(
        settings.state_dir,
        market_state_dir=settings.market_state_dir,
        ranking_state_dir=settings.ranking_state_dir,
    )


async def serve(args: argparse.Namespace, settings: AttentionSettings) -> None:
    store = _store(settings)
    runner = None
    service = None
    try:
        freeze_default_family(store, args.family_id)
        service = AttentionService(settings, store, manual_selection_id=args.manual_selection_id)
        runner = web.AppRunner(application(service), access_log=None)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", settings.port).start()
        service.start()
        stopped = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_running_loop().add_signal_handler(sig, stopped.set)
        print(
            json.dumps({"event": "started", "port": settings.port, "mode": "shadow_only"}),
            flush=True,
        )
        if args.run_seconds:
            with suppress(TimeoutError):
                await asyncio.wait_for(stopped.wait(), args.run_seconds)
        else:
            await stopped.wait()
    finally:
        if service:
            await service.close()
        if runner:
            await runner.cleanup()
        store.close()


async def status(settings: AttentionSettings) -> dict[str, object]:
    async with (
        aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=5)) as session,
        session.get(f"http://127.0.0.1:{settings.port}/health", allow_redirects=False) as response,
    ):
        if response.status != 200:
            raise ValueError("attention health unavailable")
        payload = await response.content.read(65_537)
        if len(payload) > 65_536:
            raise ValueError("attention health response too large")
        data = json.loads(payload)
        if not isinstance(data, dict) or data.get("mode") != "shadow_only":
            raise ValueError("invalid attention health response")
        return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    root = Path.home() / ".local/share"
    for name in (
        "serve",
        "status",
        "validate-state",
        "settle-outcomes",
        "freeze-family",
        "evaluate-family",
    ):
        command = commands.add_parser(name)
        command.add_argument(
            "--state-dir",
            default=os.environ.get(
                "PREP_WATCHDECK_ATTENTION_STATE_DIR", str(root / "prep-watchdeck-attention")
            ),
        )
        command.add_argument(
            "--market-state-dir",
            default=os.environ.get(
                "PREP_WATCHDECK_MARKET_STATE_DIR", str(root / "prep-watchdeck-market")
            ),
        )
        command.add_argument(
            "--ranking-state-dir",
            default=os.environ.get(
                "PREP_WATCHDECK_RANKING_STATE_DIR", str(root / "prep-watchdeck-ranking")
            ),
        )
        command.add_argument(
            "--port", type=int, default=int(os.environ.get("PREP_WATCHDECK_ATTENTION_PORT", "8770"))
        )
        command.add_argument(
            "--ranking-port",
            type=int,
            default=int(os.environ.get("PREP_WATCHDECK_RANKING_PORT", "8769")),
        )
        if name == "serve":
            command.add_argument("--run-seconds", type=int, default=0)
            command.add_argument("--manual-selection-id")
            command.add_argument("--family-id", default="attention-v1")
        if name == "settle-outcomes":
            command.add_argument(
                "--fixture",
                type=Path,
                required=True,
                help="offline attention-outcome-input-v1 export",
            )
            command.add_argument("--generation-id", help="default: all saved prospective evidence")
        if name in ("freeze-family", "evaluate-family"):
            command.add_argument("--family-id", default="attention-v1")
            command.add_argument("--minimum-practical-delta", type=float, default=0.1)
        if name == "evaluate-family":
            command.add_argument("--bootstrap-samples", type=int, default=2000)
            command.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    try:
        settings = _settings(args)
        if args.command == "serve":
            if not 0 <= args.run_seconds <= 86400:
                raise ValueError("run seconds must be 0..86400")
            asyncio.run(serve(args, settings))
            return
        if args.command == "status":
            print(json.dumps(asyncio.run(status(settings)), ensure_ascii=False))
            return
        if args.command == "validate-state":
            payload = read_stable_regular_file(
                settings.state_dir / "artifacts/current.json", max_bytes=8 * 1024 * 1024
            )
            current = AttentionResponse.model_validate_json(payload)
            print(
                json.dumps(
                    {
                        "status": "valid",
                        "generationId": current.generation_id,
                        "decisionAt": current.decision_at,
                        "scope": "current artifact; database and live data not revalidated",
                    }
                )
            )
            return
        store = _store(settings)
        try:
            if args.command == "freeze-family":
                policies = freeze_default_family(
                    store, args.family_id, delta=args.minimum_practical_delta
                )
                print(
                    json.dumps(
                        {
                            "familyId": args.family_id,
                            "policyIds": [p.id for p in policies],
                            "frozenAt": min(p.frozen_at for p in policies),
                        }
                    )
                )
            elif args.command == "settle-outcomes":
                reader = FixtureBarReader.from_file(args.fixture)
                identities = (
                    [args.generation_id]
                    if args.generation_id
                    else [g[0].generation_id for g in store.evidence_generations()]
                )
                rows = [
                    row
                    for identity in identities
                    for row in settle_generation_outcomes(
                        store, reader, generation_id=identity, now_ms=int(time.time() * 1000)
                    )
                ]
                print(
                    json.dumps(
                        {
                            "outcomes": len(rows),
                            "ready": sum(r.status == "ready" for r in rows),
                            "pending": sum(r.status == "pending" for r in rows),
                            "unscorable": sum(r.status == "unscorable" for r in rows),
                            "databaseBytes": store.size_bytes(),
                        }
                    )
                )
            elif args.command == "evaluate-family":
                from .evaluation import evaluate_candidate_family

                policies = store.policies(args.family_id)
                report = evaluate_candidate_family(
                    store,
                    policy_ids=[p.id for p in policies if p.signal not in BASELINE_SIGNALS],
                    baseline_policy_ids=[p.id for p in policies if p.signal in BASELINE_SIGNALS],
                    k_values=(10, 20),
                    minimum_practical_delta=args.minimum_practical_delta,
                    bootstrap_samples=args.bootstrap_samples,
                    seed=args.seed,
                )
                print(report.model_dump_json(by_alias=True, indent=2))
        finally:
            store.close()
    except (ValueError, OSError, RuntimeError, aiohttp.ClientError) as error:
        parser.exit(2, f"attention: {error}\n")


if __name__ == "__main__":
    main()
