from __future__ import annotations

from typing import Protocol

from prep_watchdeck.domain.dto import SnapshotDTO


class MarketDataProvider(Protocol):
    def build_snapshot(self, *, template: str, fixture_set: str | None = None) -> SnapshotDTO:
        """Return a scanner snapshot from the provider's backing source."""
