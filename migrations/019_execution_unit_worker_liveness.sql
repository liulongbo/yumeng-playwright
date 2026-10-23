-- Independent process liveness for one Collection Worker per ExecutionUnit.
-- This is deliberately separate from browser/task leases: an idle worker owns no lease, while a
-- running Activity continues to be fenced by execution_units.owner/generation/lease_until.
ALTER TABLE execution_units
  ADD COLUMN worker_generation bigint NOT NULL DEFAULT 0;

CREATE TABLE execution_unit_workers (
  worker_instance_id text PRIMARY KEY,
  unit_id text NOT NULL REFERENCES execution_units(unit_id),
  worker_generation bigint NOT NULL,
  process_id bigint NOT NULL CHECK (process_id > 0),
  platform text NOT NULL,
  started_at timestamptz NOT NULL DEFAULT now(),
  last_heartbeat_at timestamptz NOT NULL DEFAULT now(),
  stopped_at timestamptz,
  stop_reason text,
  UNIQUE (unit_id, worker_generation)
);
CREATE INDEX execution_unit_workers_health
  ON execution_unit_workers(unit_id, last_heartbeat_at DESC);

INSERT INTO schema_migrations(version) VALUES(19);
