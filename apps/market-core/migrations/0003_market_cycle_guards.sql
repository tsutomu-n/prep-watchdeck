CREATE UNIQUE INDEX collector_runs_l1_cycle_unique_idx
    ON collector_runs (cycle_at)
    WHERE run_kind = 'l1' AND venue IS NULL AND cycle_at IS NOT NULL;
