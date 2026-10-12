-- M3 product application: product identities, durable intake and model traceability.
-- The migration is additive except for two compatibility relaxations required before P1 can
-- assign a browser unit. Existing internal_acceptance tasks remain valid and readable.

ALTER TABLE root_tasks ALTER COLUMN unit_id DROP NOT NULL;
ALTER TABLE root_tasks
  ADD COLUMN requirement_id uuid,
  ADD COLUMN created_by uuid,
  ADD COLUMN origin_root_task_id uuid REFERENCES root_tasks(root_task_id),
  ADD COLUMN task_type text NOT NULL DEFAULT 'collection'
    CHECK (task_type IN ('collection', 'product_intake'));

ALTER TABLE filter_plans DROP CONSTRAINT IF EXISTS filter_plans_source_check;
ALTER TABLE filter_plans ADD CONSTRAINT filter_plans_source_check
  CHECK (source IN ('internal_acceptance', 'model'));

CREATE TABLE users (
 user_id uuid PRIMARY KEY,
 username text UNIQUE NOT NULL CHECK (username = lower(username)),
 display_name text NOT NULL,
 password_hash text NOT NULL,
 active boolean NOT NULL DEFAULT true,
 password_changed_at timestamptz NOT NULL DEFAULT now(),
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE root_tasks
  ADD CONSTRAINT root_tasks_created_by_fkey FOREIGN KEY(created_by) REFERENCES users(user_id);

CREATE TABLE sessions (
 session_id uuid PRIMARY KEY,
 user_id uuid NOT NULL REFERENCES users(user_id),
 token_hash text UNIQUE NOT NULL,
 csrf_token text NOT NULL,
 idle_expires_at timestamptz NOT NULL,
 absolute_expires_at timestamptz NOT NULL,
 last_seen_at timestamptz NOT NULL DEFAULT now(),
 revoked_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(),
 CHECK (idle_expires_at <= absolute_expires_at)
);
CREATE INDEX sessions_user_active ON sessions(user_id, revoked_at, absolute_expires_at);

CREATE TABLE requirements (
 requirement_id uuid PRIMARY KEY,
 root_task_id uuid UNIQUE NOT NULL REFERENCES root_tasks(root_task_id),
 submitted_by uuid NOT NULL REFERENCES users(user_id),
 origin_root_task_id uuid REFERENCES root_tasks(root_task_id),
 schema_version text NOT NULL CHECK (schema_version = 'requirement_form.v1'),
 capability_version text NOT NULL,
 payload jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE root_tasks ADD CONSTRAINT root_tasks_requirement_fkey
  FOREIGN KEY(requirement_id) REFERENCES requirements(requirement_id) DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE intake_dispatches (
 root_task_id uuid PRIMARY KEY REFERENCES root_tasks(root_task_id),
 p1_task_id uuid UNIQUE NOT NULL REFERENCES tasks(task_id),
 workflow_id text UNIQUE NOT NULL,
 sent boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE model_runs (
 model_run_id uuid PRIMARY KEY,
 root_task_id uuid NOT NULL REFERENCES root_tasks(root_task_id),
 p1_task_id uuid NOT NULL REFERENCES tasks(task_id),
 retry_cycle integer NOT NULL DEFAULT 0 CHECK (retry_cycle >= 0),
 attempt_number integer NOT NULL CHECK (attempt_number BETWEEN 1 AND 3),
 provider text NOT NULL,
 requested_model text NOT NULL,
 response_model text,
 prompt_version text NOT NULL,
 input_digest text NOT NULL,
 status text NOT NULL CHECK (status IN ('started','succeeded','failed','indeterminate')),
 delivery_status text NOT NULL DEFAULT 'received'
   CHECK (delivery_status IN ('received','indeterminate')),
 output_payload jsonb,
 error_payload jsonb,
 input_tokens integer,
 output_tokens integer,
 latency_ms integer CHECK (latency_ms IS NULL OR latency_ms >= 0),
 created_at timestamptz NOT NULL DEFAULT now(),
 completed_at timestamptz,
 UNIQUE(root_task_id, retry_cycle, attempt_number)
);
CREATE INDEX model_runs_task_created ON model_runs(root_task_id, created_at);

ALTER TABLE idempotency_records
  ADD COLUMN response_payload jsonb,
  ADD COLUMN created_at timestamptz NOT NULL DEFAULT now();

ALTER TABLE audit_logs ADD COLUMN actor_user_id uuid REFERENCES users(user_id);
CREATE INDEX audit_logs_actor_user_created ON audit_logs(actor_user_id, created_at);

CREATE INDEX root_tasks_product_created ON root_tasks(created_at DESC, root_task_id DESC)
  WHERE task_type = 'product_intake';

INSERT INTO schema_migrations(version) VALUES(8);
