CREATE TABLE collector_runs (
    run_id uuid PRIMARY KEY,
    run_kind text NOT NULL,
    venue text,
    cycle_at timestamptz,
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    status text NOT NULL CHECK (status IN ('running', 'succeeded', 'partial', 'failed')),
    records_received bigint NOT NULL DEFAULT 0 CHECK (records_received >= 0),
    records_written bigint NOT NULL DEFAULT 0 CHECK (records_written >= 0),
    error_code text,
    error_message text,
    metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
    CHECK (completed_at IS NULL OR completed_at >= started_at)
);

CREATE INDEX collector_runs_started_at_idx ON collector_runs (started_at DESC);
CREATE INDEX collector_runs_kind_venue_idx ON collector_runs (run_kind, venue, started_at DESC);

CREATE TABLE raw_catalog_payloads (
    raw_catalog_payload_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    collector_run_id uuid REFERENCES collector_runs (run_id),
    venue text NOT NULL,
    endpoint text NOT NULL,
    payload_hash char(64) NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    observed_at timestamptz NOT NULL,
    source_at timestamptz,
    payload jsonb NOT NULL,
    UNIQUE (venue, endpoint, payload_hash)
);

CREATE INDEX raw_catalog_payloads_observed_at_idx
    ON raw_catalog_payloads (venue, observed_at DESC);

CREATE TABLE venue_instrument_versions (
    venue_instrument_version_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    venue text NOT NULL,
    source_symbol text NOT NULL,
    definition_hash char(64) NOT NULL CHECK (definition_hash ~ '^[0-9a-f]{64}$'),
    valid_from timestamptz NOT NULL,
    valid_to timestamptz,
    active boolean NOT NULL,
    asset_class text NOT NULL,
    market_type text NOT NULL,
    execution_model text NOT NULL DEFAULT 'clob',
    base_asset text NOT NULL,
    quote_asset text NOT NULL,
    settle_asset text NOT NULL,
    collateral_asset text,
    contract_multiplier numeric,
    price_tick numeric,
    amount_step numeric,
    source_status text,
    raw_catalog_payload_id bigint NOT NULL
        REFERENCES raw_catalog_payloads (raw_catalog_payload_id),
    collector_run_id uuid REFERENCES collector_runs (run_id),
    CHECK (valid_to IS NULL OR valid_to > valid_from),
    CHECK (contract_multiplier IS NULL OR contract_multiplier > 0),
    CHECK (price_tick IS NULL OR price_tick > 0),
    CHECK (amount_step IS NULL OR amount_step > 0),
    UNIQUE (venue, source_symbol, valid_from)
);

CREATE UNIQUE INDEX venue_instrument_versions_current_idx
    ON venue_instrument_versions (venue, source_symbol)
    WHERE valid_to IS NULL;
CREATE INDEX venue_instrument_versions_base_idx
    ON venue_instrument_versions (base_asset, venue)
    WHERE valid_to IS NULL;

CREATE TABLE capabilities (
    venue text NOT NULL,
    capability text NOT NULL,
    available boolean NOT NULL,
    source_kind text NOT NULL,
    endpoint_or_channel text,
    documentation_url text,
    observed_at timestamptz NOT NULL,
    collector_run_id uuid REFERENCES collector_runs (run_id),
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (venue, capability)
);

CREATE TABLE market_groups (
    group_id text PRIMARY KEY,
    base_asset text NOT NULL,
    asset_class text NOT NULL DEFAULT 'crypto',
    market_type text NOT NULL DEFAULT 'linear_perpetual',
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    CHECK (updated_at >= created_at)
);

CREATE TABLE group_memberships (
    group_membership_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    group_id text NOT NULL REFERENCES market_groups (group_id),
    venue_instrument_version_id bigint NOT NULL
        REFERENCES venue_instrument_versions (venue_instrument_version_id),
    mapping_method text NOT NULL,
    valid_from timestamptz NOT NULL,
    valid_to timestamptz,
    exclusion_reason text,
    CHECK (valid_to IS NULL OR valid_to > valid_from),
    UNIQUE (group_id, venue_instrument_version_id, valid_from)
);

CREATE UNIQUE INDEX group_memberships_current_instrument_idx
    ON group_memberships (venue_instrument_version_id)
    WHERE valid_to IS NULL;
CREATE INDEX group_memberships_current_group_idx
    ON group_memberships (group_id)
    WHERE valid_to IS NULL;

CREATE TABLE latest_market_state (
    venue_instrument_version_id bigint PRIMARY KEY
        REFERENCES venue_instrument_versions (venue_instrument_version_id),
    collector_run_id uuid NOT NULL REFERENCES collector_runs (run_id),
    cycle_at timestamptz NOT NULL,
    observed_at timestamptz NOT NULL,
    source_at timestamptz,
    status text NOT NULL CHECK (status IN ('ready', 'partial', 'unavailable', 'stale')),
    mark_price numeric,
    reference_price numeric,
    reference_price_kind text NOT NULL DEFAULT 'none'
        CHECK (reference_price_kind IN ('index', 'oracle', 'none')),
    best_bid numeric,
    best_ask numeric,
    funding_rate_raw numeric,
    funding_interval_seconds integer CHECK (funding_interval_seconds > 0),
    funding_rate_per_hour numeric,
    next_funding_at timestamptz,
    open_interest_raw numeric,
    open_interest_raw_unit text,
    open_interest_base numeric,
    open_interest_notional numeric,
    volume_24h_raw numeric,
    volume_24h_unit text,
    quote_asset text NOT NULL,
    collateral_asset text,
    source_payload_hash char(64),
    error_code text,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (mark_price IS NULL OR mark_price > 0),
    CHECK (reference_price IS NULL OR reference_price > 0),
    CHECK (best_bid IS NULL OR best_bid > 0),
    CHECK (best_ask IS NULL OR best_ask > 0),
    CHECK (best_bid IS NULL OR best_ask IS NULL OR best_ask >= best_bid),
    CHECK (open_interest_raw IS NULL OR open_interest_raw >= 0),
    CHECK (open_interest_base IS NULL OR open_interest_base >= 0),
    CHECK (open_interest_notional IS NULL OR open_interest_notional >= 0),
    CHECK (volume_24h_raw IS NULL OR volume_24h_raw >= 0),
    CHECK (source_payload_hash IS NULL OR source_payload_hash ~ '^[0-9a-f]{64}$')
);

CREATE INDEX latest_market_state_cycle_idx ON latest_market_state (cycle_at DESC);

CREATE TABLE raw_market_observations (
    raw_market_observation_id bigint GENERATED ALWAYS AS IDENTITY,
    observed_date date NOT NULL,
    collector_run_id uuid REFERENCES collector_runs (run_id),
    venue_instrument_version_id bigint
        REFERENCES venue_instrument_versions (venue_instrument_version_id),
    venue text NOT NULL,
    source_symbol text,
    dataset text NOT NULL,
    observed_at timestamptz NOT NULL,
    source_at timestamptz,
    payload_hash char(64) NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    payload jsonb NOT NULL,
    PRIMARY KEY (observed_date, raw_market_observation_id),
    CHECK (observed_date = (observed_at AT TIME ZONE 'UTC')::date)
) PARTITION BY RANGE (observed_date);

CREATE TABLE raw_market_observations_default
    PARTITION OF raw_market_observations DEFAULT;
CREATE INDEX raw_market_observations_instrument_time_idx
    ON raw_market_observations (venue_instrument_version_id, observed_at DESC);
CREATE INDEX raw_market_observations_dataset_time_idx
    ON raw_market_observations (dataset, observed_at DESC);

CREATE TABLE market_state_1m (
    venue_instrument_version_id bigint NOT NULL
        REFERENCES venue_instrument_versions (venue_instrument_version_id),
    bucket_at timestamptz NOT NULL,
    collector_run_id uuid REFERENCES collector_runs (run_id),
    status text NOT NULL CHECK (status IN ('ready', 'partial', 'unavailable', 'stale')),
    first_observed_at timestamptz NOT NULL,
    last_observed_at timestamptz NOT NULL,
    source_at timestamptz,
    sample_count integer NOT NULL CHECK (sample_count > 0),
    mark_price numeric,
    reference_price numeric,
    reference_price_kind text NOT NULL DEFAULT 'none'
        CHECK (reference_price_kind IN ('index', 'oracle', 'none')),
    best_bid numeric,
    best_ask numeric,
    funding_rate_raw numeric,
    funding_interval_seconds integer CHECK (funding_interval_seconds > 0),
    funding_rate_per_hour numeric,
    open_interest_raw numeric,
    open_interest_raw_unit text,
    open_interest_base numeric,
    open_interest_notional numeric,
    volume_24h_raw numeric,
    volume_24h_unit text,
    PRIMARY KEY (venue_instrument_version_id, bucket_at),
    CHECK (last_observed_at >= first_observed_at),
    CHECK (mark_price IS NULL OR mark_price > 0),
    CHECK (reference_price IS NULL OR reference_price > 0),
    CHECK (best_bid IS NULL OR best_bid > 0),
    CHECK (best_ask IS NULL OR best_ask > 0),
    CHECK (best_bid IS NULL OR best_ask IS NULL OR best_ask >= best_bid)
);

CREATE INDEX market_state_1m_bucket_idx ON market_state_1m (bucket_at DESC);

CREATE TABLE candle_1m (
    venue_instrument_version_id bigint NOT NULL
        REFERENCES venue_instrument_versions (venue_instrument_version_id),
    bucket_at timestamptz NOT NULL,
    open_price numeric NOT NULL CHECK (open_price > 0),
    high_price numeric NOT NULL CHECK (high_price > 0),
    low_price numeric NOT NULL CHECK (low_price > 0),
    close_price numeric NOT NULL CHECK (close_price > 0),
    volume_base numeric CHECK (volume_base >= 0),
    volume_notional numeric CHECK (volume_notional >= 0),
    trade_count bigint CHECK (trade_count >= 0),
    finality text NOT NULL CHECK (finality IN ('confirmed', 'derived_final')),
    source_at timestamptz,
    observed_at timestamptz NOT NULL,
    collector_run_id uuid REFERENCES collector_runs (run_id),
    PRIMARY KEY (venue_instrument_version_id, bucket_at),
    CHECK (high_price >= low_price),
    CHECK (high_price >= open_price AND high_price >= close_price),
    CHECK (low_price <= open_price AND low_price <= close_price)
);

CREATE INDEX candle_1m_bucket_idx ON candle_1m (bucket_at DESC);

CREATE TABLE funding_events (
    funding_event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    venue_instrument_version_id bigint NOT NULL
        REFERENCES venue_instrument_versions (venue_instrument_version_id),
    funding_at timestamptz NOT NULL,
    funding_rate_raw numeric NOT NULL,
    funding_interval_seconds integer CHECK (funding_interval_seconds > 0),
    funding_rate_per_hour numeric,
    source_at timestamptz,
    observed_at timestamptz NOT NULL,
    collector_run_id uuid REFERENCES collector_runs (run_id),
    UNIQUE (venue_instrument_version_id, funding_at)
);

CREATE INDEX funding_events_time_idx ON funding_events (funding_at DESC);

CREATE TABLE archive_manifests (
    manifest_id uuid PRIMARY KEY,
    dataset text NOT NULL,
    venue text NOT NULL,
    partition_date date NOT NULL,
    generation integer NOT NULL CHECK (generation > 0),
    status text NOT NULL CHECK (status IN ('staged', 'confirmed', 'superseded', 'failed')),
    relative_path text NOT NULL,
    schema_version integer NOT NULL CHECK (schema_version > 0),
    row_count bigint NOT NULL CHECK (row_count >= 0),
    unique_key_columns text[] NOT NULL,
    min_timestamp timestamptz,
    max_timestamp timestamptz,
    sha256 char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    confirmed_at timestamptz,
    superseded_at timestamptz,
    error_code text,
    CHECK (max_timestamp IS NULL OR min_timestamp IS NULL OR max_timestamp >= min_timestamp),
    CHECK (confirmed_at IS NULL OR status IN ('confirmed', 'superseded')),
    CHECK (superseded_at IS NULL OR status = 'superseded'),
    UNIQUE (dataset, venue, partition_date, generation)
);

CREATE UNIQUE INDEX archive_manifests_active_idx
    ON archive_manifests (dataset, venue, partition_date)
    WHERE status = 'confirmed' AND superseded_at IS NULL;

CREATE TABLE selected_raw_observations (
    selected_raw_observation_id bigint GENERATED ALWAYS AS IDENTITY,
    observed_date date NOT NULL,
    selection_id uuid NOT NULL,
    group_id text NOT NULL REFERENCES market_groups (group_id),
    venue_instrument_version_id bigint NOT NULL
        REFERENCES venue_instrument_versions (venue_instrument_version_id),
    observation_kind text NOT NULL CHECK (observation_kind IN ('depth', 'trade')),
    observed_at timestamptz NOT NULL,
    source_at timestamptz,
    payload_hash char(64) NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    payload jsonb NOT NULL,
    collector_run_id uuid REFERENCES collector_runs (run_id),
    PRIMARY KEY (observed_date, selected_raw_observation_id),
    CHECK (observed_date = (observed_at AT TIME ZONE 'UTC')::date)
) PARTITION BY RANGE (observed_date);

CREATE TABLE selected_raw_observations_default
    PARTITION OF selected_raw_observations DEFAULT;
CREATE INDEX selected_raw_observations_selection_time_idx
    ON selected_raw_observations (selection_id, observed_at DESC);
CREATE INDEX selected_raw_observations_instrument_time_idx
    ON selected_raw_observations (venue_instrument_version_id, observed_at DESC);
