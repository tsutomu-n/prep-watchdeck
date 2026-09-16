"""Finite acceptance against the actual providers; uses only the supplied isolated state."""

import argparse
import asyncio
import fcntl
import json
import os
import resource
import time
from collections import Counter
from pathlib import Path

import aiohttp
from aiohttp import web

from prep_watchdeck_ranking.models import RankingMap
from prep_watchdeck_ranking.providers import PublicClient, now_ms
from prep_watchdeck_ranking.service import RankingService, application
from prep_watchdeck_ranking.storage import Store, isolated_state


def event(name: str, **details: object) -> None:
    print(json.dumps({"event": name, "observedAt": now_ms(), **details}), flush=True)


async def acceptance(args: argparse.Namespace) -> None:
    state = isolated_state(args.state_dir, args.original_state_dir)
    state.mkdir(parents=True, exist_ok=True)
    mapping = RankingMap.model_validate_json(args.mapping.read_text())
    supported = sum(row.reference is not None for row in mapping.rows)
    deadline = time.monotonic() + args.seconds
    observations = []
    fd = os.open(state / "writer.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for phase in ("normal",) if args.prepare_only else ("normal", "restart"):
            store = Store(state, args.original_state_dir)
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=20), trust_env=False
            ) as session:
                client = PublicClient(session)
                service = RankingService(store, mapping, client)
                runner = web.AppRunner(application(service), access_log=None)
                try:
                    await runner.setup()
                    await web.TCPSite(runner, "127.0.0.1", args.port).start()
                    await service.start()
                    event("phase_started", phase=phase, health=service.health())
                    consecutive = 0
                    previous = None
                    generation_id = None
                    while consecutive < 3:
                        if time.monotonic() > deadline:
                            raise TimeoutError("finite all-reference acceptance deadline reached")
                        await asyncio.sleep(1)
                        generation = service.generation
                        if generation is None or generation.id == generation_id:
                            continue
                        generation_id = generation.id
                        responses = [
                            generation.response(period, "00:00", "turnover", 0, now_ms())
                            for period in ("15m", "1h", "daily")
                        ]
                        indicators = {
                            item.period: {
                                "turnoverRatio": dict(
                                    Counter(
                                        row.turnover_ratio.status
                                        for row in item.rows
                                        if row.reference
                                    )
                                ),
                                "dayRangePosition": dict(
                                    Counter(
                                        row.day_range_position.status
                                        for row in item.rows
                                        if row.reference
                                    )
                                ),
                                "rankChange": dict(
                                    Counter(
                                        row.rank_change.status for row in item.rows if row.reference
                                    )
                                ),
                            }
                            for item in responses
                        }
                        valid = all(
                            item.coverage.valid == supported
                            and not item.stale
                            and all(
                                row.day_range_position.status in ("ready", "no_range")
                                and (
                                    item.period == "daily"
                                    or row.turnover_ratio.status in ("ready", "no_baseline")
                                )
                                for row in item.rows
                                if row.reference
                            )
                            for item in responses
                        )
                        if consecutive and previous == generation.cutoff - 60_000:
                            valid = valid and all(
                                row.rank_change.status in ("compared", "new")
                                for item in responses
                                for row in item.rows
                                if row.rank is not None
                            )
                        consecutive = (
                            consecutive + 1
                            if valid
                            and (previous is None or generation.cutoff - previous == 60_000)
                            else (1 if valid else 0)
                        )
                        previous = generation.cutoff
                        observation = {
                            "phase": phase,
                            "cutoff": generation.cutoff,
                            "generationId": generation.id,
                            "supported": supported,
                            "valid": {r.period: r.coverage.valid for r in responses},
                            "reasons": {r.period: r.coverage.reasons for r in responses},
                            "indicators": indicators,
                            "previousGenerationId": responses[0].previous_generation_id,
                            "metricVersion": responses[0].metric_version,
                            "durationMs": service.last_duration_ms,
                            "maxRssKiB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                            "consecutive": consecutive,
                            "health": service.health(),
                        }
                        observations.append(observation)
                        (state / f"{phase}-{generation.cutoff}.json").write_text(
                            json.dumps(
                                {
                                    r.period: r.model_dump(mode="json", by_alias=True)
                                    for r in responses
                                }
                            )
                        )
                        event("acceptance_cycle", **observation)
                    before = {p: h.rest_requests for p, h in client.health.items()}
                    for index in range(12):
                        async with session.get(
                            f"http://127.0.0.1:{args.port}/rankings",
                            params={
                                "period": "daily",
                                "dailyReferenceJst": f"{index:02}:17",
                                "order": "turnover",
                            },
                        ) as response:
                            response.raise_for_status()
                            payload = await response.json()
                            assert payload["generationId"] == generation_id
                    after = {p: h.rest_requests for p, h in client.health.items()}
                    assert before == after, "readers caused external REST acquisition"
                    event(
                        "reader_independence", phase=phase, readers=12, before=before, after=after
                    )
                    if phase == "normal" and not args.prepare_only:
                        connections = list(client.connections.values())
                        active_providers = {
                            r.reference.provider for r in mapping.rows if r.reference
                        }
                        assert len(connections) >= len(active_providers)
                        await asyncio.gather(*(connection.close() for connection in connections))
                        event("websockets_closed", count=len(connections))
                        reconnect_deadline = min(deadline, time.monotonic() + 30)
                        while not all(
                            client.health[p].connections and client.health[p].reconnects
                            for p in active_providers
                        ):
                            if time.monotonic() >= reconnect_deadline:
                                raise TimeoutError("WebSocket reconnection failed")
                            await asyncio.sleep(1)
                        event("websockets_reconnected", health=service.health())
                finally:
                    await service.close()
                    await runner.cleanup()
                    store.close()
            if phase == "normal" and not args.prepare_only:
                # A real 75 second collector outage creates missed minutes for restart backfill.
                event("collector_outage_started", seconds=75)
                await asyncio.sleep(75)
                event("collector_outage_finished")
        evidence = {
            "mapVersion": mapping.version,
            "supported": supported,
            "mode": "prepare_only" if args.prepare_only else "recovery",
            "observations": observations,
            "maxRssKiB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "passed": True,
        }
        filename = "preparation.json" if args.prepare_only else "acceptance.json"
        (state / filename).write_text(json.dumps(evidence, indent=2))
        event("acceptance_passed", supported=supported, maxRssKiB=evidence["maxRssKiB"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", required=True, type=Path)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--original-state-dir", required=True, type=Path)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--seconds", type=int, default=900)
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="finite cold-start preparation and three complete generations; recovery is a separate run",
    )
    args = parser.parse_args()
    if (
        not 300 <= args.seconds <= 900
        or not 1024 <= args.port <= 65535
        or args.port in (5432, 55432)
    ):
        parser.error("use a dedicated API port and a 300..900 second finite budget")
    asyncio.run(acceptance(args))
