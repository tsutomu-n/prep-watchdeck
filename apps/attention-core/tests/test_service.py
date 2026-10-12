import asyncio
import hashlib
from datetime import timedelta

import pytest
from aiohttp.test_utils import TestClient, TestServer
from test_inputs import MS, NOW, bundle, ranking

from prep_watchdeck_attention.components import ComponentPolicy
from prep_watchdeck_attention.config import AttentionSettings
from prep_watchdeck_attention.models import AllocationPolicy
from prep_watchdeck_attention.ranking_input import RankingInputError
from prep_watchdeck_attention.service import AttentionService, application
from prep_watchdeck_attention.storage import AttentionStore


class Reader:
    def __init__(self):
        self.count = 0
        self.fail = False

    async def read(self, *, now_ms):
        self.count += 1
        if self.fail:
            raise RankingInputError("offline")
        return ranking()


def test_service_publishes_only_committed_generations_and_api_never_reads_inputs(tmp_path):
    async def run():
        settings = AttentionSettings(
            tmp_path / "attention", tmp_path / "market", tmp_path / "ranking"
        )
        settings.market_state_dir.mkdir()
        selection = settings.market_state_dir / "selection.json"
        selection.write_text("manual selection preserved")
        before = hashlib.sha256(selection.read_bytes()).hexdigest()
        store = AttentionStore(
            settings.state_dir,
            market_state_dir=settings.market_state_dir,
            ranking_state_dir=settings.ranking_state_dir,
        )
        reader = Reader()
        reads = []

        def market(path, *, now):
            reads.append(path)
            return bundle()

        service = AttentionService(
            settings,
            store,
            ranking_reader=reader,
            market_reader=market,
            policy=ComponentPolicy(version="test", minimum_peers=1),
            clock=lambda: MS,
        )
        client = TestClient(TestServer(application(service)))
        await client.start_server()
        try:
            initial = await client.get("/attention")
            assert (
                initial.status == 503 and (await initial.json())["reason"] == "generation_pending"
            )
            assert await service.generate_once(now=NOW)
            expected = store.latest_response()
            assert expected is not None
            for _ in range(2):
                result = await client.get("/attention")
                assert result.status == 200 and result.headers["Cache-Control"] == "no-store"
                assert (await result.json())["generationId"] == expected.generation_id
            assert reader.count == 1 and len(reads) == 1
            assert not await service.generate_once(now=NOW + timedelta(seconds=1))
            assert (
                store.connection.execute("SELECT COUNT(*) FROM input_generations").fetchone()[0]
                == 1
            )
            bad = await client.get("/attention?component=movement")
            assert bad.status == 400
            host = await client.get("/attention", headers={"Host": "attacker.example"})
            assert host.status == 403
            reader.fail = True
            assert not await service.generate_once(now=NOW + timedelta(seconds=2))
            stale = await client.get("/attention")
            payload = await stale.json()
            assert payload["status"] == "stale" and payload["reason"] == "ranking_unavailable"
            assert hashlib.sha256(selection.read_bytes()).hexdigest() == before
        finally:
            await client.close()
            store.close()

    asyncio.run(run())


@pytest.mark.parametrize("retry_delay", [0, 2])
def test_discovery_failure_retries_exact_committed_generation(tmp_path, monkeypatch, retry_delay):
    async def run():
        settings = AttentionSettings(
            tmp_path / "attention", tmp_path / "market", tmp_path / "ranking"
        )
        store = AttentionStore(settings.state_dir)
        service = AttentionService(
            settings,
            store,
            ranking_reader=Reader(),
            market_reader=lambda path, now: bundle(),
            policy=ComponentPolicy(version="test", minimum_peers=1),
            allocation_policies=(
                AllocationPolicy(id="movement-k1", kind="top-k-v1", component="movement", k=1),
            ),
            clock=lambda: MS,
        )
        original_save = store.save_discovery
        failed = False

        def save_discovery(*args, **kwargs):
            nonlocal failed
            if not failed:
                failed = True
                raise OSError("transient discovery failure")
            return original_save(*args, **kwargs)

        monkeypatch.setattr(store, "save_discovery", save_discovery)
        try:
            assert not await service.generate_once(now=NOW)
            assert service.current_response() is None
            assert service.last_error == "storage_unavailable"
            committed = store.latest_response()
            assert committed is not None
            allocation = committed.shadow_allocations[0]
            assert not allocation.comparable
            assert allocation.reason == "no_previous_allocation"
            assert allocation.added == ("asset:BTC",)
            assert allocation.retained == ()
            before = store.connection.execute(
                "SELECT id,evidence,fingerprint FROM input_generations"
            ).fetchall()
            artifact = (store.artifacts / "current.json").read_bytes()
            assert before[0][1] == 1

            assert await service.generate_once(now=NOW + timedelta(seconds=retry_delay))
            assert service.current_response() == committed
            assert store.latest_response() == committed
            assert (
                store.connection.execute(
                    "SELECT id,evidence,fingerprint FROM input_generations"
                ).fetchall()
                == before
            )
            assert (store.artifacts / "current.json").read_bytes() == artifact
            assert store.discovery_response().generation_id == committed.generation_id
            assert service.cycles == 1
            assert not await service.generate_once(now=NOW + timedelta(seconds=retry_delay + 1))
        finally:
            store.close()

    asyncio.run(run())


def test_database_failure_prevents_new_publication(tmp_path, monkeypatch):
    async def run():
        settings = AttentionSettings(
            tmp_path / "attention", tmp_path / "market", tmp_path / "ranking"
        )
        store = AttentionStore(settings.state_dir)
        service = AttentionService(
            settings,
            store,
            ranking_reader=Reader(),
            market_reader=lambda path, now: bundle(),
            clock=lambda: MS,
        )

        def fail(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(store, "save_generation", fail)
        ticks = iter([100.0, 100.25])
        monkeypatch.setattr(
            "prep_watchdeck_attention.service.time.perf_counter", lambda: next(ticks)
        )
        assert service.health()["lastCycleDurationMs"] is None
        try:
            assert not await service.generate_once(now=NOW)
            assert service.current_response() is None
            assert service.last_error == "storage_unavailable"
            assert service.health()["lastCycleDurationMs"] == 250
            assert service.health()["maxCycleDurationMs"] == 250
        finally:
            store.close()

    asyncio.run(run())
