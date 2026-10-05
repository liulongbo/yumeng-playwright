CREATE TABLE schema_migrations (version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE execution_units (
 unit_id text PRIMARY KEY, account_ref text UNIQUE NOT NULL, line_ref text UNIQUE NOT NULL,
 profile_ref text UNIQUE NOT NULL, state text NOT NULL DEFAULT 'NEEDS_LOGIN',
 session_version bigint NOT NULL DEFAULT 0, generation bigint NOT NULL DEFAULT 0,
 owner text, lease_until timestamptz, browser_stopped boolean NOT NULL DEFAULT true,
 mode text CHECK (mode IN ('collect', 'maintenance')), failure_reason text
);
CREATE TABLE root_tasks (
 root_task_id uuid PRIMARY KEY, state text NOT NULL, version bigint NOT NULL,
 unit_id text NOT NULL REFERENCES execution_units(unit_id), payload jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX root_tasks_state_created ON root_tasks(state, created_at);
CREATE TABLE filter_plans (root_task_id uuid PRIMARY KEY REFERENCES root_tasks, payload jsonb NOT NULL,
 source text NOT NULL CHECK(source = 'internal_acceptance'));
CREATE TABLE tasks (task_id uuid PRIMARY KEY, root_task_id uuid NOT NULL REFERENCES root_tasks,
 parent_task_id uuid REFERENCES tasks, kind text NOT NULL, UNIQUE(root_task_id, kind));
CREATE TABLE task_attempts (attempt_id uuid PRIMARY KEY, root_task_id uuid NOT NULL REFERENCES root_tasks,
 segment integer NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE task_checkpoints (task_id uuid PRIMARY KEY REFERENCES tasks, revision bigint NOT NULL,
 payload jsonb NOT NULL);
CREATE TABLE task_dispatches (root_task_id uuid NOT NULL REFERENCES root_tasks, segment integer NOT NULL,
 workflow_id text NOT NULL, sent boolean NOT NULL DEFAULT false,
 PRIMARY KEY(root_task_id, segment));
CREATE TABLE idempotency_records (actor text NOT NULL, operation text NOT NULL, key text NOT NULL,
 digest text NOT NULL, root_task_id uuid NOT NULL REFERENCES root_tasks,
 PRIMARY KEY(actor, operation, key));
CREATE TABLE platform_creators (creator_id uuid PRIMARY KEY, platform text NOT NULL,
 platform_creator_id text NOT NULL, projection jsonb NOT NULL DEFAULT '{}',
 UNIQUE(platform, platform_creator_id));
CREATE TABLE task_creators (root_task_id uuid NOT NULL REFERENCES root_tasks,
 creator_id uuid NOT NULL REFERENCES platform_creators, first_position integer NOT NULL,
 valid boolean NOT NULL, latest_snapshot_id uuid,
 PRIMARY KEY(root_task_id, creator_id), UNIQUE(root_task_id, first_position));
CREATE TABLE creator_snapshots (snapshot_id uuid PRIMARY KEY, root_task_id uuid NOT NULL REFERENCES root_tasks,
 creator_id uuid NOT NULL REFERENCES platform_creators, draft_revision bigint NOT NULL,
 payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(root_task_id, creator_id, draft_revision));
ALTER TABLE task_creators ADD FOREIGN KEY(latest_snapshot_id) REFERENCES creator_snapshots;
CREATE FUNCTION immutable_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'published snapshots are immutable'; END $$;
CREATE TRIGGER snapshot_immutable BEFORE UPDATE OR DELETE ON creator_snapshots
 FOR EACH ROW EXECUTE FUNCTION immutable_snapshot();
CREATE TABLE audit_logs (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 root_task_id uuid REFERENCES root_tasks, actor text NOT NULL, action text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE raw_evidence (object_id text PRIMARY KEY, checksum text NOT NULL,
 root_task_id uuid REFERENCES root_tasks, kind text NOT NULL,
 expires_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
INSERT INTO schema_migrations(version) VALUES(1);
CREATE TABLE contract_health (contract_version text PRIMARY KEY, disabled boolean NOT NULL,
 failure_reason text, updated_at timestamptz NOT NULL DEFAULT now());
