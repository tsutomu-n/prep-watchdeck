from __future__ import annotations

from math import isfinite

from prep_watchdeck.domain.enums import ActivityPhase


def classify_activity_phase(
    ratio_15m: float | None,
    ratio_1h: float | None,
    ratio_4h: float | None,
    *,
    min_volume_ratio: float,
    strong_volume_ratio: float,
) -> ActivityPhase:
    values = (ratio_15m, ratio_1h, ratio_4h, min_volume_ratio, strong_volume_ratio)
    if any(value is None or not isfinite(value) for value in values):
        return ActivityPhase.UNKNOWN

    assert ratio_15m is not None
    assert ratio_1h is not None
    assert ratio_4h is not None
    if ratio_15m < 1.0 and (ratio_1h >= min_volume_ratio or ratio_4h >= min_volume_ratio):
        return ActivityPhase.COOLING
    if ratio_1h >= min_volume_ratio and ratio_4h >= min_volume_ratio:
        return ActivityPhase.SUSTAINED
    if (
        ratio_15m >= min_volume_ratio
        and ratio_1h >= min_volume_ratio
        and ratio_4h < min_volume_ratio
    ):
        return ActivityPhase.EXPANDING
    if ratio_15m >= strong_volume_ratio and ratio_1h < min_volume_ratio:
        return ActivityPhase.BURST
    return ActivityPhase.NORMAL
