ALTER TABLE venue_instrument_versions
    ADD COLUMN quantity_unit text NOT NULL DEFAULT 'unknown',
    ADD COLUMN funding_interval_seconds integer,
    ADD COLUMN raw_definition jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD CONSTRAINT venue_instrument_versions_funding_interval_check
        CHECK (funding_interval_seconds IS NULL OR funding_interval_seconds > 0);

ALTER TABLE venue_instrument_versions
    ALTER COLUMN quantity_unit DROP DEFAULT,
    ALTER COLUMN raw_definition DROP DEFAULT;

ALTER TABLE raw_catalog_payloads
    ADD COLUMN source_kind text NOT NULL DEFAULT 'native_rest',
    ADD COLUMN documentation_url text,
    ADD COLUMN last_observed_at timestamptz;

UPDATE raw_catalog_payloads
SET last_observed_at = observed_at;

ALTER TABLE raw_catalog_payloads
    ALTER COLUMN source_kind DROP DEFAULT,
    ALTER COLUMN last_observed_at SET NOT NULL,
    ADD CONSTRAINT raw_catalog_payloads_observation_order_check
        CHECK (last_observed_at >= observed_at);

CREATE TABLE catalog_exclusions (
    catalog_exclusion_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    raw_catalog_payload_id bigint NOT NULL
        REFERENCES raw_catalog_payloads (raw_catalog_payload_id),
    venue text NOT NULL,
    source_symbol text,
    reason text NOT NULL,
    raw_definition jsonb NOT NULL,
    UNIQUE NULLS NOT DISTINCT (raw_catalog_payload_id, source_symbol, reason)
);

CREATE INDEX catalog_exclusions_venue_reason_idx
    ON catalog_exclusions (venue, reason);

CREATE TABLE identity_resolutions (
    identity_resolution_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    venue_instrument_version_id bigint NOT NULL
        REFERENCES venue_instrument_versions (venue_instrument_version_id),
    group_id text REFERENCES market_groups (group_id),
    mapping_method text,
    unmapped_reason text,
    valid_from timestamptz NOT NULL,
    valid_to timestamptz,
    CHECK (valid_to IS NULL OR valid_to > valid_from),
    CHECK (
        (group_id IS NOT NULL AND mapping_method IS NOT NULL AND unmapped_reason IS NULL)
        OR
        (group_id IS NULL AND mapping_method IS NULL AND unmapped_reason IS NOT NULL)
    )
);

CREATE UNIQUE INDEX identity_resolutions_current_instrument_idx
    ON identity_resolutions (venue_instrument_version_id)
    WHERE valid_to IS NULL;
CREATE INDEX identity_resolutions_current_group_idx
    ON identity_resolutions (group_id)
    WHERE valid_to IS NULL AND group_id IS NOT NULL;
