from __future__ import annotations


def classify_btc_relative_15m(
    alt_change_15m: float | None,
    btc_change_15m: float | None,
    linked_threshold: float,
    individual_threshold: float,
) -> str:
    if alt_change_15m is None or btc_change_15m is None:
        return "UNKNOWN"
    relative = alt_change_15m - btc_change_15m
    if abs(relative) <= linked_threshold:
        return "BTC_LINKED"
    if relative >= individual_threshold:
        return "ALT_SPIKE" if abs(alt_change_15m) >= individual_threshold * 2 else "ALT_STRONG"
    if relative <= -individual_threshold:
        return "ALT_WEAK"
    return "BTC_LINKED"
