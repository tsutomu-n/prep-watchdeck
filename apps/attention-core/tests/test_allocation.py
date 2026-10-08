from helpers import CUTOFF, feature, generation

from prep_watchdeck_attention.allocation import allocate_shadow_hotset
from prep_watchdeck_attention.models import MINUTE, AllocationPolicy


def response(order, minute=0, scores=None):
    cutoff = CUTOFF + minute * MINUTE
    return generation(
        tuple(feature(a, cutoff) for a in order),
        cutoff=cutoff,
        generation_id=f"g{minute}",
        scores=scores,
    )[1]


def test_shadow_topk_hold_buffer_cost_and_manual_context():
    top = AllocationPolicy(id="top", kind="top-k-v1", k=2)
    first = allocate_shadow_hotset(
        response("abc"), policy=top, previous=None, manual_selection_id="manual"
    )
    assert [s.asset_id for s in first.slots] == ["a", "b"]
    assert first.manual_selection_id == "manual" and first.manual_selection_mutated is False
    policy = AllocationPolicy(
        id="hold", kind="hysteresis-v1", k=2, buffer=1, minimum_hold_minutes=5
    )
    held = allocate_shadow_hotset(
        response("abcd"), policy=policy, previous=None, manual_selection_id=None
    )
    reordered = allocate_shadow_hotset(
        response("cdb a".replace(" ", ""), 1),
        policy=policy,
        previous=held,
        manual_selection_id=None,
    )
    assert {s.asset_id for s in reordered.slots} == {"a", "b"}
    later = allocate_shadow_hotset(
        response("cdba", 6), policy=policy, previous=reordered, manual_selection_id=None
    )
    assert {s.asset_id for s in later.slots} == {"b", "c"}
    assert later.removed == ("a",) and later.added == ("c",) and later.retained == ("b",)
    assert later.churn == 0.5
    cost = AllocationPolicy(id="cost", kind="cost-aware-greedy-v1", k=1, switch_penalty=0.1)
    previous = allocate_shadow_hotset(
        response("ab", scores=[91, 90]), policy=cost, previous=None, manual_selection_id=None
    )
    current = allocate_shadow_hotset(
        response("ba", 1, scores=[92, 91]), policy=cost, previous=previous, manual_selection_id=None
    )
    assert current.slots[0].asset_id == "a"
    switch = allocate_shadow_hotset(
        response("ba", 2, scores=[100, 60]), policy=cost, previous=current, manual_selection_id=None
    )
    assert switch.slots[0].asset_id == "b"
    assert switch.estimated_switch_cost == 0.2


def test_shadow_freshness_and_policy_map_comparability():
    policy = AllocationPolicy(id="top", kind="top-k-v1", k=1)
    original = response("ab")
    first = allocate_shadow_hotset(original, policy=policy, previous=None, manual_selection_id=None)
    stale = allocate_shadow_hotset(
        original.model_copy(update={"status": "stale"}),
        policy=policy,
        previous=first,
        manual_selection_id=None,
    )
    assert stale.slots == () and stale.removed == ("a",)
    changed = original.model_copy(
        update={"inputs": original.inputs.model_copy(update={"ranking_map_version": "new"})}
    )
    result = allocate_shadow_hotset(
        changed, policy=policy, previous=first, manual_selection_id=None
    )
    assert not result.comparable and result.reason == "map_or_policy_changed"
