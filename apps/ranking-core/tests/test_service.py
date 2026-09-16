import asyncio
from typing import Any

import aiohttp
import pytest

from prep_watchdeck_ranking import service as module
from prep_watchdeck_ranking.mapping import reference_revision
from prep_watchdeck_ranking.models import MINUTE
from prep_watchdeck_ranking.providers import PublicClient
from prep_watchdeck_ranking.service import RankingService
from prep_watchdeck_ranking.storage import Store

from .conftest import CUTOFF, mapping, reference


def test_queued_backfill_keeps_earliest_missing_minute(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def check() -> None:
        clock = CUTOFF
        monkeypatch.setattr(module, "now_ms", lambda: clock)
        calls = []
        async with aiohttp.ClientSession() as session:
            client = PublicClient(session)

            async def history(ref: Any, first: int, last: int) -> list:
                calls.append((ref.key, first, last))
                return []

            monkeypatch.setattr(client, "history", history)
            service = RankingService(store, mapping("BTC"), client)
            service.enqueue(reference(), 3)
            clock += 5 * MINUTE
            worker = asyncio.create_task(service.backfill_worker("bybit"))
            await service.queues["bybit"].join()
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
        assert calls == [(reference().key, CUTOFF - 2 * MINUTE, CUTOFF + 5 * MINUTE)]

    asyncio.run(check())


@pytest.mark.parametrize("symbol, allowed", [("BTCDOMUSDT", True), ("ALLUSDT", False)])
def test_only_qualified_crypto_index_is_adopted(
    store: Store, monkeypatch: pytest.MonkeyPatch, symbol: str, allowed: bool
) -> None:
    async def check() -> None:
        entry = {
            "symbol": symbol,
            "baseAsset": symbol.removesuffix("USDT"),
            "quoteAsset": "USDT",
            "marginAsset": "USDT",
            "status": "TRADING",
            "contractType": "PERPETUAL",
            "underlyingType": "INDEX",
            "onboardDate": 1,
        }
        ref = reference(symbol).model_copy(
            update={"provider": "binance", "revision": reference_revision("binance", entry)}
        )
        original_map = mapping(symbol.removesuffix("USDT"))
        row = original_map.rows[0].model_copy(update={"reference": ref})
        adopted = original_map.model_copy(update={"rows": (row,)})
        async with aiohttp.ClientSession() as session:
            client = PublicClient(session)

            async def catalog(_provider: str) -> dict:
                return {"symbols": [entry]}

            monkeypatch.setattr(client, "catalog", catalog)
            service = RankingService(store, adopted, client)
            await service.check_catalogs()
            assert (ref.key not in service.invalid_contracts) is allowed

    asyncio.run(check())


def test_catalog_failure_recovers_but_changed_contract_stays_invalid(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def check() -> None:
        clock = CUTOFF
        monkeypatch.setattr(module, "now_ms", lambda: clock)
        async with aiohttp.ClientSession() as session:
            client = PublicClient(session)
            service = RankingService(store, mapping("BTC"), client)

            async def unavailable(_provider: str) -> dict:
                raise TimeoutError("public catalog unavailable")

            monkeypatch.setattr(client, "catalog", unavailable)
            await service.check_catalogs()
            assert service.catalog_unavailable == {"bybit"}
            assert service.invalid_contracts == set()

            async def changed(_provider: str) -> dict:
                return {"result": {"list": [{"symbol": "BTCUSDT", "status": "Settled"}]}}

            monkeypatch.setattr(client, "catalog", changed)
            clock += MINUTE
            await service.check_catalogs()
            assert service.catalog_unavailable == set()
            assert service.invalid_contracts == {reference().key}
            service.enqueue(reference(), 1441)
            assert service.queues["bybit"].empty()

    asyncio.run(check())
