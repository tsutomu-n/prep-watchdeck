from __future__ import annotations

from dataclasses import dataclass

from prep_watchdeck.application.ws_frames import (
    ChannelSpec,
    build_channel_specs,
    shard_channel_specs,
)


@dataclass(frozen=True)
class SubscriptionPlan:
    product_type: str
    symbol_count: int
    channel_count: int
    shard_count: int
    max_channels: int
    shards: list[list[ChannelSpec]]


def build_subscription_plan(
    symbols: list[str],
    *,
    product_type: str,
    max_channels: int = 48,
) -> SubscriptionPlan:
    specs = build_channel_specs(symbols, inst_type=product_type)
    shards = shard_channel_specs(specs, max_channels=max_channels)
    return SubscriptionPlan(
        product_type=product_type,
        symbol_count=len({symbol.strip().upper() for symbol in symbols if symbol.strip()}),
        channel_count=len(specs),
        shard_count=len(shards),
        max_channels=max_channels,
        shards=shards,
    )
