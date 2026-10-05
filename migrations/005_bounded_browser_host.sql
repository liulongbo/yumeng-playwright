-- AUTO-01: durable ownership metadata for a bounded, per-unit browser host.
-- BrowserContext objects remain process-local; PostgreSQL stores only fencing and lifecycle facts.
ALTER TABLE execution_units
 ADD COLUMN expected_account_id text,
 ADD COLUMN verified_account_id text,
 ADD COLUMN current_root_task_id uuid REFERENCES root_tasks(root_task_id),
 ADD COLUMN maintenance_deadline timestamptz,
 ADD COLUMN idle_deadline timestamptz;

INSERT INTO schema_migrations(version) VALUES(5);
