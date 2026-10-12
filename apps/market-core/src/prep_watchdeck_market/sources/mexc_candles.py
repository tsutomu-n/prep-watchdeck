from __future__ import annotations

from datetime import UTC, datetime, timedelta

from prep_watchdeck_market.candles import Candle1m, CandleParseError, decimal_value
from prep_watchdeck_market.models import CatalogInstrument
from prep_watchdeck_market.sources.common import CatalogSourceError, require_list, require_mapping
from prep_watchdeck_market.sources.mexc import mexc_data, mexc_quantity_multiplier


def parse_mexc_history(
    payload: object, instrument: CatalogInstrument, *, observed_at: datetime
) -> tuple[Candle1m, ...]:
    try:
        return _parse_mexc_history(payload, instrument, observed_at=observed_at)
    except CatalogSourceError:
        raise CandleParseError("MEXC candle history envelope invalid") from None


def _parse_mexc_history(
    payload: object, instrument: CatalogInstrument, *, observed_at: datetime
) -> tuple[Candle1m, ...]:
    row = require_mapping(mexc_data(payload), field_name="MEXC klines")
    names = ("time", "open", "high", "low", "close", "vol", "amount")
    arrays = [require_list(row.get(name), field_name=name) for name in names]
    if len({len(a) for a in arrays}) != 1:
        raise CandleParseError("MEXC kline arrays differ in length")
    factor = mexc_quantity_multiplier(instrument)
    result = []
    for t, o, h, lo, c, v, a in zip(*arrays, strict=True):
        try:
            bucket = datetime.fromtimestamp(int(str(t)), UTC)
        except (ValueError, OverflowError, OSError):
            raise CandleParseError("MEXC kline timestamp invalid") from None
        # No source closed flag: local receipt after minute end provides derived finality.
        if bucket + timedelta(minutes=1) > observed_at:
            continue
        result.append(
            Candle1m(
                "mexc",
                instrument.source_symbol,
                bucket,
                decimal_value(o, field_name="open", positive=True),
                decimal_value(h, field_name="high", positive=True),
                decimal_value(lo, field_name="low", positive=True),
                decimal_value(c, field_name="close", positive=True),
                decimal_value(v, field_name="contracts") * factor,
                decimal_value(a, field_name="amount"),
                None,
                "derived_final",
                None,
                observed_at,
                observed_at,
                source_contract_multiplier=factor,
            )
        )
    return tuple(result)


class MexcCandleFinalizer:
    """Latest WS receipt per bucket, locally derived at close + five seconds."""

    def __init__(self, instruments):
        self.instruments = {i.source_symbol: i for i in instruments}
        self.pending = {}

    def ingest(self, payload, *, observed_at):
        try:
            self._ingest(payload, observed_at=observed_at)
        except (CatalogSourceError, ValueError, TypeError, OverflowError):
            raise CandleParseError("MEXC native candle payload invalid") from None

    def _ingest(self, payload, *, observed_at):
        row = require_mapping(payload.get("data"), field_name="MEXC kline")
        symbol = row.get("symbol")
        if (
            payload.get("channel") != "push.kline"
            or row.get("interval") != "Min1"
            or symbol not in self.instruments
        ):
            raise CandleParseError("MEXC kline series mismatch")
        item = self.instruments[symbol]
        bucket = datetime.fromtimestamp(int(str(row.get("t"))), UTC)
        candle = Candle1m(
            "mexc",
            symbol,
            bucket,
            decimal_value(row.get("o"), field_name="open", positive=True),
            decimal_value(row.get("h"), field_name="high", positive=True),
            decimal_value(row.get("l"), field_name="low", positive=True),
            decimal_value(row.get("c"), field_name="close", positive=True),
            decimal_value(row.get("q"), field_name="contracts") * mexc_quantity_multiplier(item),
            decimal_value(row.get("a"), field_name="amount"),
            None,
            "derived_final",
            None,
            observed_at,
            source_contract_multiplier=mexc_quantity_multiplier(item),
        )
        self.pending[candle.storage_key] = candle

    def finalize(self, *, now):
        from dataclasses import replace

        keys = [
            k
            for k, c in self.pending.items()
            if max(c.bucket_end + timedelta(seconds=5), c.observed_at) <= now
        ]
        return tuple(replace(self.pending.pop(k), finalized_at=now) for k in sorted(keys))
