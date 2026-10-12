"""Recommendation-only allocation: no selection/control writer is imported or called."""

from .models import (
    MINUTE,
    AllocationPolicy,
    AttentionResponse,
    AttentionRow,
    ShadowAllocation,
    ShadowSlot,
)


def allocate_shadow_hotset(
    response: AttentionResponse,
    *,
    policy: AllocationPolicy,
    previous: ShadowAllocation | None,
    manual_selection_id: str | None,
) -> ShadowAllocation:
    comparable = previous is not None and (
        previous.map_version == response.inputs.ranking_map_version
        and previous.policy == policy
        and previous.score_policy_version == response.policy_version
        and previous.decision_at <= response.decision_at
    )
    reason = (
        None
        if comparable
        else "no_previous_allocation"
        if previous is None
        else "map_or_policy_changed"
    )
    old = {s.asset_id: s for s in previous.slots} if comparable and previous else {}
    eligible = {
        row.asset_id: row
        for row in response.rows
        if response.status in ("ready", "partial")
        and row.identity_status in ("ready", "partial")
        and row.components[policy.component].status == "ready"
        and 0 <= response.decision_at - row.data_as_of <= 150_000
    }

    def score(row: AttentionRow) -> float:
        value = row.components[policy.component].score
        assert value is not None
        return value

    def rank(row: AttentionRow) -> int:
        value = row.components[policy.component].rank
        assert value is not None
        return value

    ordered = sorted(eligible, key=lambda asset: (-score(eligible[asset]), asset))

    def held(asset: str) -> bool:
        return (
            asset in old
            and response.decision_at - old[asset].entered_at < policy.minimum_hold_minutes * MINUTE
        )

    def groups(asset: str) -> set[str]:
        return {
            o.group_id for o in eligible[asset].originals if o.current and o.group_id is not None
        }

    def transition_cost(before: dict[str, set[str]], after: dict[str, set[str]]) -> float:
        before_groups = {group for values in before.values() for group in values}
        after_groups = {group for values in after.values() for group in values}
        # A group-less slot incurs its own estimated transition without inventing an ID.
        before_unmapped = {asset for asset, values in before.items() if not values}
        after_unmapped = {asset for asset, values in after.items() if not values}
        additions = len(after_groups - before_groups) + len(after_unmapped - before_unmapped)
        removals = len(before_groups - after_groups) + len(before_unmapped - after_unmapped)
        return policy.switch_penalty * (additions + removals) + policy.warm_up_cost * additions

    if policy.kind == "top-k-v1" or not comparable:
        chosen = ordered[: policy.k]
    elif policy.kind == "hysteresis-v1":
        chosen = [
            asset
            for asset in old
            if asset in eligible
            and (held(asset) or rank(eligible[asset]) <= policy.k + policy.buffer)
        ]
        chosen.sort(
            key=lambda asset: (
                not held(asset),
                old[asset].entered_at,
                -score(eligible[asset]),
                asset,
            )
        )
        chosen = chosen[: policy.k]
        for asset in ordered:
            if len(chosen) >= policy.k:
                break
            if asset not in chosen and rank(eligible[asset]) <= policy.k:
                chosen.append(asset)
    else:
        chosen = [asset for asset in old if asset in eligible][: policy.k]
        for asset in ordered:
            if asset in chosen:
                continue
            if len(chosen) < policy.k:
                chosen.append(asset)
                continue
            removable = sorted(
                (a for a in chosen if not held(a)), key=lambda a: (score(eligible[a]), a)
            )
            if not removable:
                continue
            remove = removable[0]
            benefit = (score(eligible[asset]) - score(eligible[remove])) / 100
            before_groups = {a: groups(a) for a in chosen}
            after_groups = {a: groups(a) for a in chosen if a != remove} | {asset: groups(asset)}
            if benefit > transition_cost(before_groups, after_groups):
                chosen.remove(remove)
                chosen.append(asset)
    chosen.sort(key=lambda asset: (-score(eligible[asset]), asset))
    slots = tuple(
        ShadowSlot(
            asset_id=asset,
            group_ids=tuple(sorted(groups(asset))),
            entered_at=old[asset].entered_at if asset in old else response.decision_at,
            score=score(eligible[asset]),
            rank=rank(eligible[asset]),
        )
        for asset in chosen
    )
    current = set(chosen)
    before = set(old)
    added = tuple(sorted(current - before))
    removed = tuple(sorted(before - current))
    retained = tuple(sorted(before & current))
    old_groups = {group for slot in old.values() for group in slot.group_ids}
    new_groups = {group for slot in slots for group in slot.group_ids}
    added_groups = tuple(sorted(new_groups - old_groups))
    removed_groups = tuple(sorted(old_groups - new_groups))
    cost = transition_cost(
        {asset: set(slot.group_ids) for asset, slot in old.items()},
        {slot.asset_id: set(slot.group_ids) for slot in slots},
    )
    if response.status not in ("ready", "partial"):
        reason = "attention_unavailable"
    return ShadowAllocation(
        generation_id=response.generation_id,
        decision_at=response.decision_at,
        map_version=response.inputs.ranking_map_version,
        policy=policy,
        score_policy_version=response.policy_version,
        manual_selection_id=manual_selection_id,
        comparable=comparable,
        reason=reason,
        slots=slots,
        added=added,
        removed=removed,
        retained=retained,
        added_groups=added_groups,
        removed_groups=removed_groups,
        churn=len(set(added) | set(removed)) / (2 * policy.k) if comparable else 0,
        estimated_switch_cost=cost,
    )
