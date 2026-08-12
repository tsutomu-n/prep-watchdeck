from __future__ import annotations

PRODUCT_TYPE = "USDT-FUTURES"
GRANULARITY_5M = "5m"
SCHEMA_VERSION = 1
TIMEFRAME_BARS: dict[str, int] = {
    "5m": 1,
    "15m": 3,
    "1h": 12,
    "4h": 48,
    "24h": 288,
}
CATEGORIES = ("WATCH", "CAUTION", "NO_TRADE", "LOW_PRIORITY")
TEMPLATES = {"conservative", "balanced", "aggressive"}
