-- UPD-01: unified task kinds for collection / manual update / scheduled update.
--
-- `task_type` already exists but means "which entry produced this root" (a product intake root
-- keeps task_type='product_intake' after promotion).  Reusing it would either break that index or
-- silently reinterpret historical rows, so the current task kind gets its own additive column.
ALTER TABLE root_tasks
  ADD COLUMN task_kind text NOT NULL DEFAULT 'collection'
  CHECK (task_kind IN ('collection', 'manual_update', 'scheduled_update'));
CREATE INDEX root_tasks_task_kind_created
  ON root_tasks(task_kind, created_at DESC, root_task_id DESC);

-- UPD-02: one execution-unit pool.  Each unit decides which task kinds it may execute; the
-- existing per-unit Temporal queue and max_concurrent_activities=1 remain the execution boundary.
ALTER TABLE execution_units
  ADD COLUMN allowed_task_kinds text[] NOT NULL
  DEFAULT ARRAY['collection', 'manual_update', 'scheduled_update']::text[]
  CHECK (
    cardinality(allowed_task_kinds) > 0
    AND allowed_task_kinds <@ ARRAY['collection', 'manual_update', 'scheduled_update']::text[]
  );

-- UPD-04: per-creator update cadence and duplicate-execution fence.  This is scheduling state, not
-- a second copy of creator data; snapshots/projection stay authoritative.
CREATE TABLE creator_update_schedule (
  creator_id uuid PRIMARY KEY REFERENCES platform_creators(creator_id),
  next_due_at timestamptz NOT NULL,
  tier text NOT NULL CHECK (tier IN ('lt_1w', '1w_10w', '10w_50w', '50w_100w', 'ge_100w', 'unknown')),
  interval_days integer NOT NULL CHECK (interval_days > 0),
  last_attempt_at timestamptz,
  last_success_at timestamptz,
  last_success_snapshot_id uuid REFERENCES creator_snapshots(snapshot_id),
  consecutive_failures integer NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
  last_failure_reason text,
  in_flight_root_task_id uuid REFERENCES root_tasks(root_task_id),
  in_flight_claimed_at timestamptz,
  in_flight_expires_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX creator_update_schedule_due
  ON creator_update_schedule(next_due_at)
  WHERE in_flight_root_task_id IS NULL;

INSERT INTO schema_migrations(version) VALUES(18);
