from __future__ import annotations


def classify_funding(rate: float | None, warn_abs_pct: float, avoid_abs_pct: float) -> str:
    if rate is None:
        return "UNKNOWN"
    pct = rate * 100.0
    if abs(pct) >= avoid_abs_pct:
        return "OVERHEATED"
    if pct >= warn_abs_pct:
        return "LONG_HEAVY"
    if pct <= -warn_abs_pct:
        return "SHORT_HEAVY"
    return "SMALL"
