"""Independent collector and loopback-only read API with one bounded generation publisher."""

import asyncio
import json
import time
from typing import Any, cast

import aiohttp
from aiohttp import web

from .mapping import reference_revision
from .models import MINUTE, Provider, RankingMap, Reference
from .providers import PublicClient, now_ms
from .ranking import Generation, Order, Period
from .storage import Store, atomic_json


class RankingService:
    def __init__(self, store: Store, mapping: RankingMap, client: PublicClient) -> None:
        self.store, self.mapping, self.client = store, mapping, client
        self.generation: Generation | None = None
        self.queues: dict[Provider, asyncio.Queue[tuple[Reference, int]]] = {
            "bybit": asyncio.Queue(maxsize=2000),
            "binance": asyncio.Queue(maxsize=2000),
        }
        self.pending: set[str] = set()
        self.last_backfill: dict[str, int] = {}
        self.invalid_contracts: set[str] = set()
        self.catalog_unavailable: set[Provider] = set()
        self.catalog_checked_at: dict[Provider, int] = {}
        self.tasks: list[asyncio.Task[Any]] = []
        self.cycles = 0
        self.last_duration_ms = 0
        self.last_error: str | None = None
        self.references = [row.reference for row in mapping.rows if row.reference]
        if len(self.references) > 1500:
            raise ValueError("mapping exceeds qualified capacity; requalify before extending")

    async def start(self) -> None:
        self.store.set_map(self.mapping)
        await self.check_catalogs()
        for provider in ("bybit", "binance"):
            refs = [
                reference
                for reference in self.references
                if reference.provider == provider and reference.key not in self.invalid_contracts
            ]
            self.client.health[provider].subscriptions = len(refs)
            # <=500 streams/connection, <=3 per provider; below verified provider limits.
            for offset in range(0, len(refs), 500):
                self.tasks.append(
                    asyncio.create_task(
                        self.collect(
                            provider, refs[offset : offset + 500], f"{provider}:{offset // 500}"
                        )
                    )
                )
            for _ in range(2):
                self.tasks.append(asyncio.create_task(self.backfill_worker(provider)))
        cutoff = now_ms() // MINUTE * MINUTE
        for reference in self.references:
            first = cutoff - 1440 * MINUTE
            present = {row[0] for row in self.store.window(reference.key, first, cutoff)}
            missing = next(
                (end for end in range(first, cutoff + MINUTE, MINUTE) if end not in present), None
            )
            if missing is not None:
                self.enqueue(reference, (cutoff - missing) // MINUTE + 1)
        self.tasks.extend(
            [asyncio.create_task(self.publish_loop()), asyncio.create_task(self.catalog_loop())]
        )

    def enqueue(self, reference: Reference, minutes: int) -> None:
        if reference.key in self.pending or reference.key in self.invalid_contracts:
            return
        self.pending.add(reference.key)
        cutoff = now_ms() // MINUTE * MINUTE
        first = cutoff - (min(1441, max(2, minutes)) - 1) * MINUTE
        self.queues[reference.provider].put_nowait((reference, first))

    async def check_catalogs(self) -> None:
        for provider in ("bybit", "binance"):
            if not any(reference.provider == provider for reference in self.references):
                continue
            if now_ms() - self.catalog_checked_at.get(provider, 0) < 3_600_000:
                continue
            try:
                catalog = await self.client.catalog(provider)
                entries = catalog["result"]["list"] if provider == "bybit" else catalog["symbols"]
                by_symbol = {entry["symbol"]: entry for entry in entries}
                for reference in self.references:
                    if reference.provider != provider:
                        continue
                    entry = by_symbol.get(reference.symbol, {})
                    if provider == "bybit":
                        valid = (
                            entry.get("status") == "Trading"
                            and entry.get("contractType") == "LinearPerpetual"
                            and entry.get("baseCoin") == reference.base_asset
                            and entry.get("quoteCoin") == entry.get("settleCoin") == "USDT"
                            and entry.get("symbolType", "") in ("", "innovation")
                            and not entry.get("isPreListing")
                        )
                    else:
                        valid = (
                            entry.get("status") == "TRADING"
                            and entry.get("contractType") == "PERPETUAL"
                            and entry.get("baseAsset") == reference.base_asset
                            and entry.get("quoteAsset") == entry.get("marginAsset") == "USDT"
                            and (
                                entry.get("underlyingType") == "COIN"
                                or (
                                    reference.symbol == "BTCDOMUSDT"
                                    and entry.get("underlyingType") == "INDEX"
                                )
                            )
                        )
                    if not valid or reference_revision(provider, entry) != reference.revision:
                        self.invalid_contracts.add(reference.key)
                self.client.health[provider].last_error = None
                self.catalog_unavailable.discard(provider)
                self.catalog_checked_at[provider] = now_ms()
            except (aiohttp.ClientError, TimeoutError, ValueError, KeyError, TypeError) as exc:
                self.client.health[provider].error(exc)
                self.catalog_unavailable.add(provider)

    async def catalog_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            await self.check_catalogs()

    async def collect(self, provider: Provider, references: list[Reference], name: str) -> None:
        async for bars in self.client.stream(provider, references, name):
            accepted = [
                bar
                for bar in bars
                if bar.reference_key not in self.invalid_contracts
                and provider not in self.catalog_unavailable
            ]
            self.store.put(accepted, now_ms())

    async def backfill_worker(self, provider: Provider) -> None:
        queue = self.queues[provider]
        while True:
            reference, first = await queue.get()
            try:
                if reference.key in self.invalid_contracts or provider in self.catalog_unavailable:
                    continue
                cutoff = now_ms() // MINUTE * MINUTE
                bars = await self.client.history(
                    reference, max(first, cutoff - 1440 * MINUTE), cutoff
                )
                self.store.put(bars, now_ms())
            except (aiohttp.ClientError, TimeoutError, ValueError, KeyError, TypeError) as exc:
                self.client.health[provider].error(exc)
            finally:
                self.last_backfill[reference.key] = now_ms()
                self.pending.discard(reference.key)
                queue.task_done()

    async def publish_loop(self) -> None:
        while True:
            current = now_ms()
            target = current // MINUTE * MINUTE + 8000
            if target <= current:
                target += MINUTE
            await asyncio.sleep(max(0, (target - now_ms()) / 1000))
            cutoff = target - 8000
            if self.generation and cutoff <= self.generation.cutoff:
                continue
            started = time.monotonic()
            try:
                candidate = Generation(
                    self.mapping,
                    cutoff,
                    now_ms(),
                    self.store,
                    previous=self.generation,
                    invalid_keys=self.invalid_contracts,
                    unavailable_keys={
                        ref.key
                        for ref in self.references
                        if ref.provider in self.catalog_unavailable
                    },
                    disconnected={p for p, h in self.client.health.items() if h.connections == 0},
                )
                by_reference = {
                    row.reference.key: candidate.series.get(row.id)
                    for row in self.mapping.rows
                    if row.reference
                }
                for reference in self.references:
                    series = by_reference.get(reference.key)
                    if series is None:
                        continue
                    last_attempt = self.last_backfill.get(reference.key, 0)
                    if series.closes[-1] is None:
                        latest = self.store.latest(reference.key)
                        self.enqueue(reference, (cutoff - latest) // MINUTE + 2 if latest else 1441)
                    elif series.missing_prefix[-1] and now_ms() - last_attempt >= 300_000:
                        self.enqueue(reference, 1441)
                self.store.prune(cutoff, {reference.key for reference in self.references})
                default = candidate.response("15m", "00:00", "gainers", 0, now_ms())
                payload = default.model_dump(mode="json", by_alias=True)
                if (time.monotonic() - started) * 1000 > 12_000:
                    raise TimeoutError("generation exceeded 12 second processing deadline")
                atomic_json(
                    self.store.state / "last-snapshot.json",
                    payload,
                )
                elapsed = int((time.monotonic() - started) * 1000)
                if elapsed > 12_000:
                    raise TimeoutError("snapshot write exceeded 12 second processing deadline")
                self.generation = candidate
                self.cycles += 1
                self.last_duration_ms = elapsed
                event = {
                    "event": "generation",
                    "cutoff": cutoff,
                    "generatedAt": candidate.generated_at,
                    "generationId": candidate.id,
                    "durationMs": elapsed,
                    "coverage": default.coverage.model_dump(by_alias=True),
                    "providers": self.health()["providers"],
                }
                print(json.dumps(event), flush=True)
                self.last_error = None
            except (ValueError, TimeoutError, OSError) as exc:
                self.last_error = type(exc).__name__ + ": " + str(exc)[:160]
                print(
                    json.dumps(
                        {"event": "generation_failed", "cutoff": cutoff, "error": self.last_error}
                    ),
                    flush=True,
                )

    def health(self) -> dict[str, Any]:
        for provider, queue in self.queues.items():
            self.client.health[provider].backfill_pending = queue.qsize()
        return {
            "status": "running" if self.generation else "preparing",
            "mapVersion": self.mapping.version,
            "cycles": self.cycles,
            "generationId": self.generation.id if self.generation else None,
            "cutoff": self.generation.cutoff if self.generation else None,
            "lastDurationMs": self.last_duration_ms,
            "lastError": self.last_error,
            "invalidContracts": sorted(self.invalid_contracts),
            "providers": {p: h.public() for p, h in self.client.health.items()},
        }

    async def close(self) -> None:
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)


def application(service: RankingService) -> web.Application:
    @web.middleware
    async def local_only(request: web.Request, handler: Any) -> web.StreamResponse:
        if request.remote not in ("127.0.0.1", "::1"):
            raise web.HTTPForbidden()
        hostname = request.url.host
        if hostname not in ("127.0.0.1", "localhost", "::1"):
            raise web.HTTPForbidden()
        response = await handler(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    async def rankings(request: web.Request) -> web.Response:
        if service.generation is None:
            return web.json_response(
                {"status": "preparing", "reason": "first_generation_pending"}, status=503
            )
        try:
            if any(
                key not in ("period", "dailyReferenceJst", "order", "minTurnover")
                for key in request.query
            ):
                raise ValueError("unknown ranking query")
            response = service.generation.response(
                cast(Period, request.query.get("period", "15m")),
                request.query.get("dailyReferenceJst", "00:00"),
                cast(Order, request.query.get("order", "gainers")),
                float(request.query.get("minTurnover", "0")),
                now_ms(),
            )
            return web.json_response(response.model_dump(mode="json", by_alias=True))
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)

    async def health(_request: web.Request) -> web.Response:
        return web.json_response(service.health())

    app = web.Application(middlewares=[local_only], client_max_size=1024)
    app.router.add_get("/rankings", rankings)
    app.router.add_get("/health", health)
    return app
