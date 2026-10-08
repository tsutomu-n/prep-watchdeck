"""Minute publisher and read-only loopback API. Reads never refresh inputs or score."""

import asyncio
import re
import sqlite3
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from aiohttp import web
from prep_watchdeck_ranking.models import RankingResponse

from .allocation import allocate_shadow_hotset
from .components import ComponentPolicy, score_attention
from .config import AttentionSettings
from .features import build_feature_generation
from .market_input import MarketInputBundle, MarketInputError, read_market_inputs, utc_ms
from .models import MINUTE, AllocationPolicy, AttentionResponse, InputReference
from .ranking_input import RankingInputError, RankingInputReader
from .storage import AttentionStore

DEFAULT_COMPONENT_POLICY = ComponentPolicy(version="attention-components-v1")
DEFAULT_ALLOCATION_POLICIES = (
    AllocationPolicy(id="top-k-v1:k10", kind="top-k-v1", k=10),
    AllocationPolicy(
        id="hysteresis-v1:k10-b5-h5", kind="hysteresis-v1", k=10, buffer=5, minimum_hold_minutes=5
    ),
    AllocationPolicy(
        id="cost-aware-greedy-v1:k10",
        kind="cost-aware-greedy-v1",
        k=10,
        minimum_hold_minutes=5,
        switch_penalty=0.02,
        warm_up_cost=0.01,
    ),
)


class RankingReader(Protocol):
    async def read(self, *, now_ms: int) -> RankingResponse: ...


class MarketReader(Protocol):
    def __call__(self, path: Path, /, *, now: datetime) -> MarketInputBundle: ...


def _input_key(inputs: InputReference) -> tuple[object, ...]:
    return (
        inputs.ranking_generation_id,
        inputs.ranking_map_version,
        inputs.ranking_metric_version,
        inputs.universe_generated_at,
        inputs.service_generated_at,
        inputs.market_metrics_generation_id,
    )


class AttentionService:
    def __init__(
        self,
        settings: AttentionSettings,
        store: AttentionStore,
        *,
        ranking_reader: RankingReader | None = None,
        market_reader: MarketReader = read_market_inputs,
        policy: ComponentPolicy = DEFAULT_COMPONENT_POLICY,
        allocation_policies: tuple[AllocationPolicy, ...] = DEFAULT_ALLOCATION_POLICIES,
        manual_selection_id: str | None = None,
        clock: Callable[[], int] = lambda: int(time.time() * 1000),
    ) -> None:
        self.settings = settings
        self.store = store
        self.ranking_reader = ranking_reader or RankingInputReader(port=settings.ranking_port)
        self.market_reader = market_reader
        self.policy = policy
        self.allocation_policies = allocation_policies
        self.manual_selection_id = manual_selection_id
        self.clock = clock
        self.current = store.latest_response()
        self.last_error: str | None = (
            "awaiting_input_validation" if self.current else "generation_pending"
        )
        self.last_attempt_at: int | None = None
        self.cycles = 0
        self._task: asyncio.Task[None] | None = None
        self._generation_lock = asyncio.Lock()

    async def generate_once(self, *, now: datetime | None = None) -> bool:
        async with self._generation_lock:
            now = now or datetime.fromtimestamp(self.clock() / 1000, UTC)
            self.last_attempt_at = utc_ms(now)
            try:
                ranking = await self.ranking_reader.read(now_ms=utc_ms(now))
            except (RankingInputError, OSError, TimeoutError):
                self.last_error = "ranking_unavailable"
                return False
            try:
                market = self.market_reader(self.settings.market_state_dir, now=now)
                inputs, features = build_feature_generation(market, ranking, decision_at=now)
            except (MarketInputError, ValueError, OSError):
                self.last_error = "market_input_unavailable"
                return False
            if self.current and _input_key(inputs) == _input_key(self.current.inputs):
                self.last_error = None
                return False
            try:
                candidate = score_attention(
                    inputs, features, policy=self.policy, previous=self.current
                )
                allocations = tuple(
                    allocate_shadow_hotset(
                        candidate,
                        policy=policy,
                        previous=self.store.latest_allocation(policy.id),
                        manual_selection_id=self.manual_selection_id,
                    )
                    for policy in self.allocation_policies
                )
                candidate = candidate.model_copy(update={"shadow_allocations": allocations})
                self.store.save_generation(
                    inputs,
                    features,
                    candidate,
                    evidence=(
                        inputs.ranking_cutoff % (5 * MINUTE) == 0
                        and not self.store.has_evidence_cutoff(inputs.ranking_cutoff)
                    ),
                )
                saved = self.store.latest_response()
                if saved is None or saved != candidate:
                    raise ValueError("committed generation readback differs")
            except (sqlite3.Error, OSError, ValueError, RuntimeError):
                self.last_error = "storage_unavailable"
                return False
            self.current = saved
            self.last_error = None
            self.cycles += 1
            return True

    def current_response(self) -> AttentionResponse | None:
        if self.current is None:
            return None
        age = self.clock() - self.current.inputs.ranking_cutoff
        error = self.last_error or (
            "attention_stale" if age > 150_000 else "clock_before_generation" if age < 0 else None
        )
        if error:
            # Keep provenance and original timestamps; never relabel an old generation fresh.
            return self.current.model_copy(update={"status": "stale", "reason": error})
        return self.current

    def health(self) -> dict[str, object]:
        response = self.current_response()
        return {
            "status": response.status if response else "unavailable",
            "reason": response.reason if response else self.last_error,
            "generationId": response.generation_id if response else None,
            "lastAttemptAt": self.last_attempt_at,
            "cycles": self.cycles,
            "databaseBytes": self.store.size_bytes(),
            "providerRequests": 0,
            "mode": "shadow_only",
        }

    async def _publish_loop(self) -> None:
        while True:
            success = await self.generate_once()
            if not success and self.last_error is not None:
                # One bounded retry while the minute Ranking generation is being published.
                await asyncio.sleep(2)
                await self.generate_once()
            now = self.clock()
            target = (now // MINUTE + 1) * MINUTE + 12_000
            await asyncio.sleep(max(0.1, (target - now) / 1000))

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("attention publisher already started")
        self._task = asyncio.create_task(self._publish_loop())

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None


def application(service: AttentionService) -> web.Application:
    @web.middleware
    async def access(
        request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]
    ) -> web.StreamResponse:
        headers = {"Cache-Control": "no-store"}
        if request.remote not in ("127.0.0.1", "::1") or not re.fullmatch(
            r"(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?", request.headers.get("Host", "")
        ):
            return web.json_response(
                {"status": "unavailable", "reason": "loopback_only"}, status=403, headers=headers
            )
        if request.query_string:
            return web.json_response(
                {"status": "unavailable", "reason": "unknown_query"}, status=400, headers=headers
            )
        if request.content_length or request.headers.get("Transfer-Encoding"):
            return web.json_response(
                {"status": "unavailable", "reason": "body_not_allowed"}, status=413, headers=headers
            )
        try:
            response = await handler(request)
        except web.HTTPException as error:
            error.headers["Cache-Control"] = "no-store"
            raise
        response.headers["Cache-Control"] = "no-store"
        return response

    async def attention(_request: web.Request) -> web.Response:
        response = service.current_response()
        if response is None:
            return web.json_response(
                {"status": "unavailable", "reason": service.last_error}, status=503
            )
        return web.json_response(response.model_dump(mode="json", by_alias=True))

    async def health(_request: web.Request) -> web.Response:
        return web.json_response(service.health())

    app = web.Application(middlewares=[access], client_max_size=1024)
    app.router.add_get("/attention", attention)
    app.router.add_get("/health", health)
    return app
