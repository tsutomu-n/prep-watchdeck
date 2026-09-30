-- Read-only export from an explicitly selected, authorized Prep Watchdeck database.
-- Required psql variables: version_id, start_at, end_at. No connection defaults.
-- The caller must choose an exact catalog version covering the whole time window.
\set ON_ERROR_STOP on
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '5s';
SET LOCAL transaction_timeout = '8s';
SET LOCAL TIME ZONE 'UTC';

SELECT jsonb_build_object(
    'schema_version', 1,
    'source_label', 'prep-watchdeck-db-snapshot',
    'series', jsonb_build_object(
        'venue', vi.venue,
        'source_symbol', vi.source_symbol,
        'venue_instrument_version_id', vi.venue_instrument_version_id,
        'definition_sha256', vi.definition_hash,
        'base_asset', vi.base_asset,
        'quote_asset', vi.quote_asset,
        'settle_asset', vi.settle_asset,
        'price_kind', 'trade',
        'interval_seconds', 60
    ),
    'records', COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
            'venue_instrument_version_id', c.venue_instrument_version_id,
            'bucket_at', c.bucket_at,
            'open_price', c.open_price::text,
            'high_price', c.high_price::text,
            'low_price', c.low_price::text,
            'close_price', c.close_price::text,
            'volume_base', c.volume_base::text,
            'volume_notional', c.volume_notional::text,
            'trade_count', c.trade_count,
            'finality', c.finality,
            'source_at', c.source_at,
            'observed_at', c.observed_at
        ) ORDER BY c.bucket_at)
        FROM candle_1m c
        WHERE c.venue_instrument_version_id = vi.venue_instrument_version_id
          AND c.bucket_at >= :'start_at'::timestamptz
          AND c.bucket_at < :'end_at'::timestamptz
    ), '[]'::jsonb)
)
FROM venue_instrument_versions vi
WHERE vi.venue_instrument_version_id = :'version_id'::bigint
  AND vi.market_type = 'linear_perpetual'
  AND vi.valid_from <= :'start_at'::timestamptz
  AND (vi.valid_to IS NULL OR :'end_at'::timestamptz <= vi.valid_to)
  AND :'end_at'::timestamptz > :'start_at'::timestamptz
  AND :'end_at'::timestamptz - :'start_at'::timestamptz <= interval '7 days';
COMMIT;
