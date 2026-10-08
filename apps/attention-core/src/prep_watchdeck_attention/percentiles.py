"""Deterministic cross-sectional midrank percentiles, never imputing observations."""

import math
from collections.abc import Mapping
from itertools import groupby


def midrank_percentiles(values: Mapping[str, float], *, minimum_peers: int) -> dict[str, float]:
    if minimum_peers < 1 or not all(math.isfinite(value) for value in values.values()):
        raise ValueError("invalid percentile input")
    if len(values) < minimum_peers:
        raise ValueError("insufficient_peers")
    if len(values) == 1:
        return dict.fromkeys(values, 50.0)
    result: dict[str, float] = {}
    offset = 0
    for _, peers in groupby(sorted(values, key=lambda key: (values[key], key)), values.__getitem__):
        tied = list(peers)
        score = 100 * (offset + (len(tied) - 1) / 2) / (len(values) - 1)
        result.update(dict.fromkeys(tied, score))
        offset += len(tied)
    return result
