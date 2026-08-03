from __future__ import annotations

from prep_watchdeck.adapters.duckdb import DuckDbSnapshotCache
from prep_watchdeck.domain.dto import SnapshotDTO
from prep_watchdeck.domain.enums import DataSource


class DuckDbCacheProvider:
    """Local DuckDB-backed snapshot cache provider for M03."""

    def __init__(self, cache: DuckDbSnapshotCache) -> None:
        self.cache = cache

    def build_snapshot(self, *, template: str, fixture_set: str | None = None) -> SnapshotDTO:
        snapshot = self.cache.latest()
        if snapshot is None:
            raise FileNotFoundError(
                f"cache snapshot not found: {self.cache.path}. "
                "Run watchdeck scan --source fixture first."
            )
        payload = snapshot.model_dump(by_alias=True)
        payload["source"]["templateName"] = template
        payload["source"]["dataSource"] = DataSource.CACHE.value
        payload["source"]["fixtureSet"] = None
        payload["source"]["isFallback"] = False
        return SnapshotDTO.model_validate(payload)
