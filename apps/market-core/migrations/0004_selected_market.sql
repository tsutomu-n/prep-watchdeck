CREATE TABLE selected_group_leases (
    selection_id uuid PRIMARY KEY,
    group_id text NOT NULL REFERENCES market_groups (group_id),
    primary_venue_instrument_version_id bigint NOT NULL
        REFERENCES venue_instrument_versions (venue_instrument_version_id),
    activated_at timestamptz NOT NULL,
    heartbeat_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    superseded_at timestamptz,
    cleanup_deadline_at timestamptz,
    cleaned_at timestamptz,
    CHECK (heartbeat_at >= activated_at),
    CHECK (expires_at > heartbeat_at),
    CHECK (superseded_at IS NULL OR superseded_at >= activated_at),
    CHECK (
        (superseded_at IS NULL AND cleanup_deadline_at IS NULL)
        OR
        (superseded_at IS NOT NULL AND cleanup_deadline_at >= superseded_at)
    ),
    CHECK (
        cleaned_at IS NULL
        OR (
            superseded_at IS NOT NULL
            AND cleanup_deadline_at IS NOT NULL
            AND cleaned_at >= superseded_at
            AND cleaned_at <= cleanup_deadline_at
        )
    )
);

CREATE UNIQUE INDEX selected_group_leases_single_active_idx
    ON selected_group_leases ((1))
    WHERE superseded_at IS NULL;
CREATE INDEX selected_group_leases_cleanup_idx
    ON selected_group_leases (cleanup_deadline_at)
    WHERE superseded_at IS NOT NULL AND cleaned_at IS NULL;

ALTER TABLE selected_raw_observations
    ADD CONSTRAINT selected_raw_observations_selection_fk
    FOREIGN KEY (selection_id) REFERENCES selected_group_leases (selection_id);

CREATE TABLE selected_depth_levels (
    selection_id uuid NOT NULL REFERENCES selected_group_leases (selection_id),
    venue_instrument_version_id bigint NOT NULL
        REFERENCES venue_instrument_versions (venue_instrument_version_id),
    side text NOT NULL CHECK (side IN ('bid', 'ask')),
    level_index smallint NOT NULL CHECK (level_index BETWEEN 0 AND 19),
    price numeric NOT NULL CHECK (price > 0),
    size_base numeric NOT NULL CHECK (size_base > 0),
    source_at timestamptz,
    received_at timestamptz NOT NULL,
    source_channel text NOT NULL,
    source_payload_hash char(64) NOT NULL
        CHECK (source_payload_hash ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (selection_id, venue_instrument_version_id, side, level_index)
);

CREATE INDEX selected_depth_levels_instrument_idx
    ON selected_depth_levels (selection_id, venue_instrument_version_id, received_at DESC);

CREATE TABLE selected_trades (
    selected_trade_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    selection_id uuid NOT NULL REFERENCES selected_group_leases (selection_id),
    venue_instrument_version_id bigint NOT NULL
        REFERENCES venue_instrument_versions (venue_instrument_version_id),
    source_trade_id text NOT NULL,
    side text NOT NULL CHECK (side IN ('buy', 'sell')),
    price numeric NOT NULL CHECK (price > 0),
    size_base numeric NOT NULL CHECK (size_base > 0),
    source_at timestamptz,
    received_at timestamptz NOT NULL,
    source_channel text NOT NULL,
    source_payload_hash char(64) NOT NULL
        CHECK (source_payload_hash ~ '^[0-9a-f]{64}$'),
    UNIQUE (selection_id, venue_instrument_version_id, source_trade_id)
);

CREATE INDEX selected_trades_recent_idx
    ON selected_trades (
        selection_id,
        source_at DESC NULLS LAST,
        received_at DESC,
        selected_trade_id DESC
    );
