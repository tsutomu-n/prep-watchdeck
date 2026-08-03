from __future__ import annotations

from typing import Protocol

from prep_watchdeck.domain.dto import SnapshotDTO
from prep_watchdeck.models import CandleBar


class SnapshotCache(Protocol):
    def save(self, snapshot: SnapshotDTO) -> None:
        """Persist a validated snapshot for cache-mode reads."""

    def save_candles_5m(self, candles_by_symbol: dict[str, list[CandleBar]]) -> None:
        """Persist 5m candles captured during live scans."""

    def latest(self) -> SnapshotDTO | None:
        """Return the latest cached snapshot if available."""
