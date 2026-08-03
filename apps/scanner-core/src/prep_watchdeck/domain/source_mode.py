from __future__ import annotations

from enum import StrEnum


class SourceMode(StrEnum):
    LIVE = "live"
    CACHE = "cache"
    FIXTURE = "fixture"
    AUTO = "auto"
