from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

SAFE_SOURCE_ERROR_CODES = frozenset(
    {
        "bitget_business_429",
        "bitget_business_error",
        "fetch_timeout",
        "http_429",
        "invalid_source_payload",
        "source_unavailable",
    }
)


class CatalogSourceError(RuntimeError):
    """A public catalog could not be fetched or did not match its documented envelope."""

    def __init__(self, message: str, *, error_code: str = "source_unavailable") -> None:
        super().__init__(message)
        self.error_code = (
            error_code if error_code in SAFE_SOURCE_ERROR_CODES else "source_unavailable"
        )


def safe_source_error_code(error: BaseException) -> str:
    """Return a bounded diagnostic code without exposing response bodies or URLs."""

    if isinstance(error, CatalogSourceError):
        return error.error_code
    if isinstance(error, TimeoutError):
        return "fetch_timeout"
    if getattr(error, "status", None) == 429:
        return "http_429"
    if isinstance(error, ValueError):
        return "invalid_source_payload"
    return "source_unavailable"


def require_mapping(value: object, *, field_name: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise CatalogSourceError(f"{field_name} must be an object")
    return value


def require_list(value: object, *, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise CatalogSourceError(f"{field_name} must be an array")
    return value


def text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def positive_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() and number > 0 else None


def non_negative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def positive_int(value: object) -> int | None:
    number = non_negative_int(value)
    return number if number is not None and number > 0 else None


def timestamp_from_milliseconds(value: object) -> datetime | None:
    if isinstance(value, bool):
        return None
    try:
        milliseconds = int(str(value))
    except (TypeError, ValueError):
        return None
    if milliseconds <= 0:
        return None
    try:
        return datetime.fromtimestamp(milliseconds / 1_000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def observed_now() -> datetime:
    return datetime.now(tz=UTC)
