from __future__ import annotations

import math
from collections.abc import Sequence


def ewma(values: Sequence[float], *, half_life: float) -> list[float]:
    if not math.isfinite(half_life) or half_life <= 0:
        raise ValueError("half_life must be finite and positive")
    if any(not math.isfinite(value) for value in values):
        raise ValueError("EWMA values must be finite")
    if not values:
        return []

    alpha = 1.0 - math.exp(math.log(0.5) / half_life)
    result = [float(values[0])]
    for value in values[1:]:
        result.append(alpha * value + (1.0 - alpha) * result[-1])
    return result
