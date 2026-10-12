-- Current predictions have independent source/observation clocks; legacy rows stay unknown.
-- Settled funding_events are intentionally unchanged.
ALTER TABLE latest_market_state
    ADD COLUMN funding_source_at timestamptz,
    ADD COLUMN funding_observed_at timestamptz,
    ADD COLUMN funding_valid_until timestamptz;

ALTER TABLE market_state_1m
    ADD COLUMN funding_source_at timestamptz,
    ADD COLUMN funding_observed_at timestamptz,
    ADD COLUMN funding_valid_until timestamptz;
