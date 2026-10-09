"""Fixed continuation versus continuation plus OI, using reader knowledge only.

This is a fully funded long-only price proxy. It models no exchange orders,
perpetual margin, liquidation, leverage, or guaranteed fills. Common nonoverlapping
episodes and costs are fixed before running either arm; profits are not a gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, DecimalException, localcontext
from pathlib import Path
from typing import Any
from uuid import uuid4

from prep_watchdeck_market.bundle_files import BundleError, json_bytes, sha256, write_bundle
from prep_watchdeck_market.research.files import isolated_root, model_bytes, read_leaf
from prep_watchdeck_market.research.models import instant, number
from prep_watchdeck_market.research.snapshot import VerifiedSnapshot, verify_snapshot
from prep_watchdeck_market.research.trials import BoundTrial, TrialRules, load_trial


@dataclass(frozen=True)
class PriceEvent:
    at: datetime
    price_at: datetime
    price: Decimal


def _decimal(value: Decimal) -> str:
    return "0" if value == 0 else format(value, "f")


def _split(at: datetime, rules: TrialRules) -> tuple[str, datetime]:
    if at < rules.train_end:
        return "train", rules.train_end
    if at < rules.validation_end:
        return "validation", rules.validation_end
    return "test", rules.study_end


def _prices(snapshot: VerifiedSnapshot) -> list[PriceEvent]:
    events: list[PriceEvent] = []
    for observation in snapshot.observations:
        at = observation.receipt.available_at
        rows = snapshot.rows("candles", cutoff=at)
        if not rows:
            continue
        row = rows[-1]
        closed = instant(row["bucket_at"]) + timedelta(minutes=1)
        if closed > at:
            continue
        # Every reader observation can update the known mark, including corrections.
        # Entry/exit selection separately rejects native price times before its horizon.
        events.append(PriceEvent(at, closed, number(row["close_price"], positive=True)))
    return events


def _decisions(snapshot: VerifiedSnapshot, rules: TrialRules) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    seen: set[datetime] = set()
    for observation in snapshot.observations:
        at = observation.receipt.available_at
        if not rules.decision_start <= at < rules.study_end:
            continue
        candles = snapshot.rows("candles", cutoff=at)
        if not candles:
            continue
        bucket = instant(candles[-1]["bucket_at"])
        if bucket in seen:
            continue
        seen.add(bucket)
        exclusions: set[str] = set()
        split, boundary = _split(at, rules)
        decision: dict[str, Any] = {
            "decision_id": f"d{len(decisions) + 1:04d}",
            "available_at": at.isoformat(),
            "bucket_at": bucket.isoformat(),
            "split": split,
            "signal_a": None,
            "signal_b": None,
            "price_return": None,
            "activity_ratio": None,
            "oi_return": None,
            "observation_id": observation.receipt.observation_id,
            "payload_sha256": observation.receipt.payload_sha256,
            "input_row_hashes": [],
        }
        if at + timedelta(minutes=rules.holding_minutes) >= boundary:
            exclusions.add("research_split_label_purged")
        current = observation.payload
        definition = current.instrument
        if (
            not current.groups
            or not current.capabilities
            or not any(row.get("available") is True for row in current.capabilities)
            or definition.get("contract_multiplier") is None
            or definition.get("quantity_unit") not in {"base", "contracts"}
            or definition.get("catalog_payload_hash") is None
        ):
            exclusions.add("research_context_incomplete")
        if (
            definition.get("catalog_observed_at") is None
            or instant(definition["catalog_observed_at"]) > at
        ):
            exclusions.add("research_catalog_availability_unknown")
        states = {instant(row["bucket_at"]): row for row in snapshot.rows("states", cutoff=at)}
        pair = candles[-2:]
        if len(pair) != 2 or instant(pair[0]["bucket_at"]) + timedelta(minutes=1) != bucket:
            exclusions.add("research_candle_inputs_missing")
        elif bucket + timedelta(minutes=1) > at:
            exclusions.add("research_candle_not_closed")
        else:
            decision["input_row_hashes"].extend(sha256(json_bytes(row)) for row in pair)
            closes = [number(row["close_price"], positive=True) for row in pair]
            price_return = closes[1] / closes[0] - 1
            decision["price_return"] = _decimal(price_return)
            activity = [row.get("volume_notional") for row in pair]
            if any(value is None for value in activity) or number(activity[0]) == 0:
                exclusions.add("research_activity_missing")
            else:
                ratio = number(activity[1]) / number(activity[0])
                decision["activity_ratio"] = _decimal(ratio)
                decision["signal_a"] = (
                    price_return >= rules.minimum_price_return
                    and ratio >= rules.minimum_activity_ratio
                )
            state_pair = [states.get(instant(row["bucket_at"])) for row in pair]
            if any(row is None for row in state_pair):
                exclusions.add("research_state_inputs_missing")
            else:
                # This list is the two required native states, not a forward-filled series.
                present = [row for row in state_pair if row is not None]
                decision["input_row_hashes"].extend(sha256(json_bytes(row)) for row in present)
                units = [row.get("open_interest_raw_unit") for row in present]
                if any(row.get("status") != "ready" for row in present):
                    exclusions.add("research_state_not_ready")
                if units[0] not in {"base", "contracts"} or units[0] != units[1]:
                    exclusions.add("research_oi_unit_unknown")
                oi = [row.get("open_interest_raw") for row in present]
                if any(value is None for value in oi) or number(oi[0]) == 0:
                    exclusions.add("research_oi_missing")
                else:
                    change = number(oi[1]) / number(oi[0]) - 1
                    decision["oi_return"] = _decimal(change)
                    if decision["signal_a"] is not None:
                        decision["signal_b"] = bool(
                            decision["signal_a"] and change >= rules.minimum_oi_return
                        )
        decision["input_eligible"] = not exclusions
        decision["input_exclusions"] = sorted(exclusions)
        decision["eligible"] = not exclusions
        decision["exclusions"] = sorted(exclusions)
        decisions.append(decision)
    return decisions


def _funding(
    entry: PriceEvent,
    exit_at: datetime,
    prices: list[PriceEvent],
    snapshot: VerifiedSnapshot,
    rules: TrialRules,
) -> tuple[list[dict[str, str]], str | None]:
    if rules.funding_policy == "explicit_zero_scenario":
        return [], None
    interval = rules.funding_interval_seconds
    anchor = rules.funding_anchor_at
    if interval is None or anchor is None:
        raise BundleError("research_funding_schedule_invalid")
    period = timedelta(seconds=interval)
    # Funding runs before exits and entries at an equal timestamp: (entry, exit].
    event_at = anchor + ((entry.at - anchor) // period + 1) * period
    rates = {instant(row["funding_at"]): row for row in snapshot.rows("funding")}
    events: list[dict[str, str]] = []
    for settled_at, observed in rates.items():
        if entry.at < settled_at <= exit_at and (
            observed.get("funding_interval_seconds") != interval
            or (settled_at - anchor) % period != timedelta(0)
        ):
            return [], "research_funding_schedule_mismatch"
    while event_at <= exit_at:
        row = rates.get(event_at)
        known = [price for price in prices if price.at <= event_at and price.price_at <= event_at]
        if row is None or not known:
            return [], "research_funding_coverage_unknown"
        if row.get("funding_interval_seconds") != interval:
            return [], "research_funding_schedule_mismatch"
        events.append(
            {
                "at": event_at.isoformat(),
                "rate": _decimal(number(row["funding_rate_raw"], signed=True)),
                "reference_price": _decimal(known[-1].price),
                "research_available_at": row["research_available_at"],
                "input_row_sha256": sha256(json_bytes(row)),
            }
        )
        event_at += period
        if len(events) > 2000:
            return [], "research_funding_event_limit"
    return events, None


def _episodes(
    decisions: list[dict[str, Any]],
    prices: list[PriceEvent],
    snapshot: VerifiedSnapshot,
    rules: TrialRules,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    episodes: list[dict[str, Any]] = []
    open_episodes: list[dict[str, Any]] = []
    reserved_until: datetime | None = None
    for decision in decisions:
        if not decision["eligible"] or not decision["signal_a"]:
            continue
        at = instant(decision["available_at"])
        _, boundary = _split(at, rules)
        exclusion: str | None = None
        if reserved_until is not None and at <= reserved_until:
            exclusion = "research_position_window_overlap"
        entry = next((price for price in prices if price.at > at and price.price_at > at), None)
        if exclusion is None and (entry is None or entry.at >= boundary):
            exclusion = "research_entry_unavailable"
        if exclusion is not None or entry is None:
            decision["eligible"] = False
            decision["exclusions"].append(exclusion or "research_entry_unavailable")
            continue
        target_exit = entry.at + timedelta(minutes=rules.holding_minutes)
        exit_price = next(
            (
                price
                for price in prices
                if price.at >= target_exit and price.price_at >= target_exit
            ),
            None,
        )
        earliest_close = target_exit.replace(second=0, microsecond=0)
        if earliest_close < target_exit:
            earliest_close += timedelta(minutes=1)
        if earliest_close >= boundary or (exit_price is not None and exit_price.at >= boundary):
            decision["eligible"] = False
            decision["exclusions"].append("research_split_label_purged")
            continue
        final_at = prices[-1].at if exit_price is None else exit_price.at
        funding, issue = _funding(entry, final_at, prices, snapshot, rules)
        if issue is not None:
            decision["eligible"] = False
            decision["exclusions"].append(issue)
            continue
        episode = {
            "decision_id": decision["decision_id"],
            "split": decision["split"],
            "entry_at": entry.at.isoformat(),
            "entry_price_at": entry.price_at.isoformat(),
            "entry_price": _decimal(entry.price),
            "exit_at": None,
            "exit_price_at": None,
            "exit_price": None,
            "signal_b": decision["signal_b"],
            "funding": funding,
        }
        if exit_price is None:
            decision["exclusions"].append("research_exit_unavailable")
            open_episodes.append(episode)
            reserved_until = rules.study_end
        else:
            episode.update(
                exit_at=exit_price.at.isoformat(),
                exit_price_at=exit_price.price_at.isoformat(),
                exit_price=_decimal(exit_price.price),
            )
            episodes.append(episode)
            reserved_until = exit_price.at
    return episodes, open_episodes


def _arm(
    arm: str,
    episodes: list[dict[str, Any]],
    open_episodes: list[dict[str, Any]],
    prices: list[PriceEvent],
    rules: TrialRules,
) -> dict[str, Any]:
    cash, quantity = rules.initial_capital, Decimal(0)
    fees, funding_paid, trades = Decimal(0), Decimal(0), 0
    events: list[dict[str, Any]] = []
    failure: str | None = None
    for episode in sorted([*episodes, *open_episodes], key=lambda row: row["entry_at"]):
        if arm == "B" and not episode["signal_b"]:
            continue
        entry_price = number(episode["entry_price"]) * (1 + rules.slippage_rate)
        entry_fee = rules.trade_notional * rules.fee_rate
        if cash < rules.trade_notional + entry_fee:
            failure = "research_insufficient_cash"
            events.append(
                {
                    "kind": "rejected",
                    "at": episode["entry_at"],
                    "decision_id": episode["decision_id"],
                    "cash_delta": "0",
                    "reason": failure,
                }
            )
            break
        quantity = rules.trade_notional / entry_price
        delta = -(rules.trade_notional + entry_fee)
        cash += delta
        fees += entry_fee
        trades += 1
        events.append(
            {
                "kind": "entry",
                "at": episode["entry_at"],
                "decision_id": episode["decision_id"],
                "price": _decimal(entry_price),
                "quantity": _decimal(quantity),
                "fee": _decimal(entry_fee),
                "cash_delta": _decimal(delta),
                "cash": _decimal(cash),
            }
        )
        for funding in episode["funding"]:
            payment = (
                quantity * number(funding["reference_price"]) * number(funding["rate"], signed=True)
            )
            if payment > cash:
                failure = "research_funding_insufficient_cash"
                events.append(
                    {
                        "kind": "rejected",
                        "at": funding["at"],
                        "decision_id": episode["decision_id"],
                        "cash_delta": "0",
                        "reason": failure,
                        "unpaid_amount": _decimal(payment),
                    }
                )
                break
            cash -= payment
            funding_paid += payment
            events.append(
                {
                    "kind": "funding",
                    "at": funding["at"],
                    "decision_id": episode["decision_id"],
                    "cash_delta": _decimal(-payment),
                    "cash": _decimal(cash),
                }
            )
        if failure is not None:
            break
        if episode["exit_price"] is not None:
            price = number(episode["exit_price"]) * (1 - rules.slippage_rate)
            proceeds = quantity * price
            fee = proceeds * rules.fee_rate
            delta = proceeds - fee
            cash += delta
            fees += fee
            events.append(
                {
                    "kind": "exit",
                    "at": episode["exit_at"],
                    "decision_id": episode["decision_id"],
                    "price": _decimal(price),
                    "quantity": _decimal(quantity),
                    "fee": _decimal(fee),
                    "cash_delta": _decimal(delta),
                    "cash": _decimal(cash),
                }
            )
            quantity = Decimal(0)
    mark = None if not prices else prices[-1]
    equity = cash + quantity * (Decimal(0) if mark is None else mark.price)
    return {
        "cash": _decimal(cash),
        "quantity": _decimal(quantity),
        "final_equity": _decimal(equity),
        "mark_price": None if mark is None else _decimal(mark.price),
        "mark_at": None if mark is None else mark.at.isoformat(),
        "total_fees": _decimal(fees),
        "funding_paid": _decimal(funding_paid),
        "trade_count": trades,
        "failure": failure,
        "events": events,
    }


def _split_results(
    arm: dict[str, Any], episodes: list[dict[str, Any]], rules: TrialRules
) -> dict[str, Any]:
    by_id = {episode["decision_id"]: episode["split"] for episode in episodes}
    entries = [event for event in arm["events"] if event["kind"] == "entry"]
    open_split = (
        None if not entries or arm["quantity"] == "0" else by_id[entries[-1]["decision_id"]]
    )
    prior = rules.initial_capital
    result: dict[str, Any] = {}
    for split in ("train", "validation", "test"):
        events = [event for event in arm["events"] if by_id[event["decision_id"]] == split]
        delta = sum((number(event["cash_delta"], signed=True) for event in events), Decimal(0))
        if split == open_split:
            delta += number(arm["quantity"]) * number(arm["mark_price"])
        end = prior + delta
        if split == "test":
            end = number(arm["final_equity"])
        result[split] = {
            "initial_equity": _decimal(prior),
            "final_equity": _decimal(end),
            "net_equity_change": _decimal(end - prior),
            "trade_count": sum(event["kind"] == "entry" for event in events),
        }
        prior = end
    return result


def _evaluate(trial: BoundTrial, snapshot: VerifiedSnapshot) -> dict[str, Any]:
    rules = trial.registration.rules
    reasons: set[str] = set()
    if not snapshot.replay_valid:
        reasons.update(snapshot.reasons or ("research_replay_invalid",))
    prices = _prices(snapshot) if snapshot.replay_valid else []
    decisions = _decisions(snapshot, rules) if snapshot.replay_valid else []
    episodes, open_episodes = _episodes(decisions, prices, snapshot, rules)
    arms = {name: _arm(name, episodes, open_episodes, prices, rules) for name in ("A", "B")}
    for arm in arms.values():
        arm["splits"] = _split_results(arm, [*episodes, *open_episodes], rules)
        if arm["failure"] is not None:
            reasons.add(arm["failure"])
    for decision in decisions:
        reasons.update(
            code
            for code in decision["exclusions"]
            if code
            in {
                "research_funding_coverage_unknown",
                "research_funding_schedule_mismatch",
                "research_funding_event_limit",
                "research_exit_unavailable",
            }
        )
    counts = {
        split: sum(row["split"] == split for row in episodes)
        for split in ("train", "validation", "test")
    }
    if counts["test"] < rules.minimum_independent_episodes:
        reasons.add("research_insufficient_independent_episodes")
    if not episodes and not open_episodes:
        reasons.add("research_no_trades")
    failed = any(arm["failure"] is not None for arm in arms.values())
    status = "FAILED" if failed else "NOT_ESTIMABLE" if reasons else "ESTIMABLE_DESCRIPTIVE"
    return {
        "status": status,
        "reasons": sorted(reasons),
        "snapshot_reasons": list(snapshot.reasons),
        "evidence_kind": "observed" if snapshot.observed_evidence else "synthetic",
        "evidence_scope": "reader_observation_replay_not_exchange_first_availability",
        "cost_classification": "funding_zero_sensitivity_scenario"
        if rules.funding_policy == "explicit_zero_scenario"
        else "declared_schedule_observed_cost_proxy",
        "decisions": decisions,
        "episodes": episodes,
        "open_episodes": open_episodes,
        "independent_episode_counts": counts,
        "arms": arms,
        "cash_control": {
            "initial_capital": _decimal(rules.initial_capital),
            "final_equity": _decimal(rules.initial_capital),
            "interest_assumption": "zero",
        },
        "primary_comparison": "test_net_equity_change",
        "ab_test_equity_change_difference": None
        if status != "ESTIMABLE_DESCRIPTIVE"
        else _decimal(
            number(arms["B"]["splits"]["test"]["net_equity_change"], signed=True)
            - number(arms["A"]["splits"]["test"]["net_equity_change"], signed=True)
        ),
        "ab_final_equity_difference": None
        if status != "ESTIMABLE_DESCRIPTIVE"
        else _decimal(number(arms["B"]["final_equity"]) - number(arms["A"]["final_equity"])),
    }


def evaluate_trial(trial_path: Path, snapshot_path: Path, output_dir: Path) -> Path:
    """Always publish a new immutable result for a valid trial, including failed replay."""
    trial = load_trial(trial_path)
    result: dict[str, Any] = {
        "schema_version": 1,
        "kind": "fixed_ab_proxy_evaluation",
        "trial_path": str(trial_path.absolute()),
        "trial_sha256": sha256(model_bytes(trial)),
        "rule_sha256": trial.registration.rule_sha256,
        "evaluator_sha256": trial.registration.evaluator_sha256,
        "source_hashes": trial.registration.source_hashes,
        "input_sha256": trial.input_sha256,
        "rules": trial.registration.rules.model_dump(mode="json"),
        "execution_model": "long_only_single_position_fully_funded_next_observed_close_proxy",
        "event_order": "funding_before_exit_before_entry_at_equal_time",
        "funding_rate_sign_assumption": "positive_rate_paid_by_long",
        "funding_reference_price": "last_reader_known_close_at_settlement",
        "fill_policy": "price_timestamp_and_reader_availability_strictly_after_signal",
        "label_purge": "entry_and_exit_reader_availability_strictly_before_split_boundary",
        "capital_unit": "instrument_quote_asset_proxy",
        "independence_basis": "nonoverlapping_time_windows_not_statistical_independence",
        "minimum_sample_scope": "common_completed_test_episodes",
        "funding_cost_knowledge": "settlement_outcome_rows_known_by_study_end_only",
        "decimal_policy": "precision_50_round_half_even_no_binary_float_arithmetic",
        "claims": {
            "actual_fills": False,
            "perpetual_margin": False,
            "liquidation": False,
            "profitability_acceptance_criterion": False,
        },
    }
    try:
        snapshot = verify_snapshot(snapshot_path, cutoff=trial.registration.rules.study_end)
        if snapshot.snapshot_sha256 != trial.input_sha256 or snapshot.target != trial.target:
            raise BundleError("research_trial_input_mismatch")
        with localcontext() as context:
            context.prec = 50
            context.rounding = ROUND_HALF_EVEN
            result.update(_evaluate(trial, snapshot))
    except (BundleError, DecimalException) as error:
        result.update(
            status="FAILED",
            reasons=[error.code if isinstance(error, BundleError) else "research_decimal_failure"],
            decisions=[],
            episodes=[],
            open_episodes=[],
            arms={},
            ab_final_equity_difference=None,
            ab_test_equity_change_difference=None,
        )
    raw = json_bytes(result)
    return write_bundle(
        isolated_root(output_dir, (trial_path, snapshot_path)),
        uuid4().hex,
        {"result.json": raw},
        validate=lambda path: read_leaf(path, "result.json"),
    )
