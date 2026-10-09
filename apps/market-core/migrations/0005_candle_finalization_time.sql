-- Keep legacy finality timestamps unknown. No historical reconstruction is possible.
ALTER TABLE candle_1m
    ADD COLUMN finalized_at timestamptz,
    ADD CONSTRAINT candle_1m_finalized_at_check CHECK (
        finalized_at IS NULL OR (
            finalized_at >= observed_at
            AND finalized_at >= bucket_at + interval '1 minute'
        )
    );
