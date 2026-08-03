from __future__ import annotations

from enum import StrEnum


class SnapshotStatus(StrEnum):
    OK = "OK"
    STALE = "STALE"
    PARTIAL = "PARTIAL"
    ERROR = "ERROR"


class DataSource(StrEnum):
    LIVE = "live"
    CACHE = "cache"
    FIXTURE = "fixture"


class Category(StrEnum):
    WATCH = "WATCH"
    CAUTION = "CAUTION"
    NO_TRADE = "NO_TRADE"
    LOW_PRIORITY = "LOW_PRIORITY"


class DataQuality(StrEnum):
    OK = "OK"
    STALE = "STALE"
    MISSING = "MISSING"
    PARTIAL = "PARTIAL"
