from __future__ import annotations


def classify_open_interest_change(
    current: float | None,
    previous: float | None,
    increase_threshold_pct: float,
    decrease_threshold_pct: float,
) -> str:
    if current is None or previous is None or previous <= 0:
        return "UNKNOWN"
    change_pct = (current / previous - 1.0) * 100.0
    if change_pct >= increase_threshold_pct:
        return "INCREASING"
    if change_pct <= decrease_threshold_pct:
        return "DECREASING"
    return "STABLE"
