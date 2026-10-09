"""Immutable preregistration followed by binding to a verified reader snapshot."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal, Self
from uuid import uuid4

from pydantic import Field, ValidationError, field_validator, model_validator

from prep_watchdeck_market.bundle_files import BundleError, json_bytes, read_regular, sha256
from prep_watchdeck_market.research.files import isolated_root, model_bytes, read_leaf
from prep_watchdeck_market.research.models import (
    HASH_PATTERN,
    MAX_FILE_BYTES,
    ResearchModel,
    ResearchTarget,
    instant,
    number,
)
from prep_watchdeck_market.research.snapshot import verify_snapshot


class TrialRules(ResearchModel):
    schema_version: Literal[1] = 1
    decision_start: datetime
    train_end: datetime
    validation_end: datetime
    study_end: datetime
    minimum_price_return: Decimal = Field(ge=Decimal("0"))
    minimum_activity_ratio: Decimal = Field(gt=Decimal("0"))
    minimum_oi_return: Decimal = Field(ge=Decimal("0"))
    holding_minutes: int = Field(strict=True, ge=1, le=1440)
    initial_capital: Decimal = Field(gt=Decimal("0"))
    trade_notional: Decimal = Field(gt=Decimal("0"))
    fee_rate: Decimal = Field(ge=Decimal("0"), lt=Decimal("1"))
    slippage_rate: Decimal = Field(ge=Decimal("0"), lt=Decimal("1"))
    fee_basis: str = Field(min_length=1, max_length=500)
    slippage_basis: str = Field(min_length=1, max_length=500)
    funding_policy: Literal["explicit_zero_scenario", "require_observed_events"]
    funding_basis: str = Field(min_length=1, max_length=500)
    funding_interval_seconds: int | None = Field(default=None, strict=True, ge=1, le=86400)
    funding_anchor_at: datetime | None = None
    minimum_independent_episodes: int = Field(strict=True, ge=1, le=10000)

    @field_validator("decision_start", "train_end", "validation_end", "study_end")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        return instant(value)

    @field_validator("funding_anchor_at")
    @classmethod
    def anchor(cls, value: datetime | None) -> datetime | None:
        return None if value is None else instant(value)

    @field_validator(
        "minimum_price_return",
        "minimum_activity_ratio",
        "minimum_oi_return",
        "initial_capital",
        "trade_notional",
        "fee_rate",
        "slippage_rate",
        mode="before",
    )
    @classmethod
    def finite(cls, value: object) -> Decimal:
        return number(value)

    @field_validator("fee_basis", "slippage_basis", "funding_basis")
    @classmethod
    def basis(cls, value: str) -> str:
        if not value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("explicit printable basis required")
        return value

    @model_validator(mode="after")
    def contract(self) -> Self:
        if not self.decision_start < self.train_end < self.validation_end < self.study_end:
            raise ValueError("ordered fixed temporal split required")
        if self.study_end - self.decision_start > timedelta(hours=24):
            raise ValueError("bounded research window required")
        if self.funding_policy == "require_observed_events" and (
            self.funding_interval_seconds is None or self.funding_anchor_at is None
        ):
            raise ValueError("explicit funding schedule and basis required")
        return self


class RegisteredTrial(ResearchModel):
    schema_version: Literal[1] = 1
    kind: Literal["fixed_ab_preregistration"] = "fixed_ab_preregistration"
    registered_at: datetime
    rules: TrialRules
    rule_sha256: str = Field(pattern=HASH_PATTERN)
    evaluator_sha256: str = Field(pattern=HASH_PATTERN)
    source_hashes: dict[str, str]

    @field_validator("registered_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        return instant(value)


class BoundTrial(ResearchModel):
    schema_version: Literal[1] = 1
    kind: Literal["fixed_ab_bound_trial"] = "fixed_ab_bound_trial"
    registration: RegisteredTrial
    registration_sha256: str = Field(pattern=HASH_PATTERN)
    input_sha256: str = Field(pattern=HASH_PATTERN)
    target: ResearchTarget | None


def source_hashes() -> dict[str, str]:
    """Fingerprint the evaluator and the local verification code it relies on."""
    directory = Path(__file__).parent
    names = ("evaluation.py", "trials.py", "snapshot.py", "models.py", "files.py")
    result = {name: sha256(read_regular(directory / name, MAX_FILE_BYTES)) for name in names}
    result["bundle_files.py"] = sha256(
        read_regular(directory.parent / "bundle_files.py", MAX_FILE_BYTES)
    )
    return result


def _check_registration(registration: RegisteredTrial) -> None:
    if registration.registered_at > registration.rules.decision_start:
        raise BundleError("research_trial_registered_too_late")
    if registration.rule_sha256 != sha256(model_bytes(registration.rules)):
        raise BundleError("research_rule_hash_mismatch")
    actual = source_hashes()
    if registration.source_hashes != actual or registration.evaluator_sha256 != sha256(
        json_bytes(actual)
    ):
        raise BundleError("research_evaluator_changed")


def _load[T: ResearchModel](path: Path, filename: str, model: type[T]) -> T:
    from prep_watchdeck_market.bundle_files import strict_json

    try:
        return model.model_validate(strict_json(read_leaf(path, filename)))
    except (ValidationError, TypeError, ValueError, RecursionError):
        raise BundleError("research_trial_schema_invalid") from None


def register_trial(
    rules: TrialRules,
    output_dir: Path,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Path:
    from prep_watchdeck_market.bundle_files import write_bundle

    hashes = source_hashes()
    registration = RegisteredTrial(
        registered_at=instant(clock()),
        rules=rules,
        rule_sha256=sha256(model_bytes(rules)),
        evaluator_sha256=sha256(json_bytes(hashes)),
        source_hashes=hashes,
    )
    _check_registration(registration)
    return write_bundle(
        isolated_root(output_dir),
        uuid4().hex,
        {"rules.json": model_bytes(registration)},
        validate=lambda path: _check_registration(_load(path, "rules.json", RegisteredTrial)),
    )


def bind_trial(registration_path: Path, snapshot_path: Path, output_dir: Path) -> Path:
    from prep_watchdeck_market.bundle_files import write_bundle

    registration = _load(registration_path, "rules.json", RegisteredTrial)
    _check_registration(registration)
    snapshot = verify_snapshot(snapshot_path)
    trial = BoundTrial(
        registration=registration,
        registration_sha256=sha256(model_bytes(registration)),
        input_sha256=snapshot.snapshot_sha256,
        target=snapshot.target,
    )
    return write_bundle(
        isolated_root(output_dir, (registration_path, snapshot_path)),
        uuid4().hex,
        {"trial.json": model_bytes(trial)},
        validate=load_trial,
    )


def load_trial(path: Path) -> BoundTrial:
    trial = _load(path, "trial.json", BoundTrial)
    _check_registration(trial.registration)
    if trial.registration_sha256 != sha256(model_bytes(trial.registration)):
        raise BundleError("research_registration_hash_mismatch")
    return trial
