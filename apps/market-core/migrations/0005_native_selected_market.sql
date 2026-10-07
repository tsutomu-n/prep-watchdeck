-- A NULL group is a single native contract pinned to the lease's primary version.
-- Keep the group foreign keys and the existing single-active-selection constraint.
ALTER TABLE selected_group_leases ALTER COLUMN group_id DROP NOT NULL;
ALTER TABLE selected_raw_observations ALTER COLUMN group_id DROP NOT NULL;
