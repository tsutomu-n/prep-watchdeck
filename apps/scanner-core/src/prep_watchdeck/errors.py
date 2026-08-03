from __future__ import annotations


class WatchdeckError(Exception):
    """Base scanner error."""


class BitgetAPIError(WatchdeckError):
    """Bitget returned an application-level or HTTP error."""


class BitgetNonJSONError(WatchdeckError):
    """Bitget returned a non-JSON response."""


class ConfigError(WatchdeckError):
    """Scanner configuration is invalid."""


class DataQualityError(WatchdeckError):
    """Input data is insufficient or malformed."""
