-- SESSION-01 / AUTO-01: explicit session observations and capability-scoped contract health.
-- Existing global contract_health is retained as a compatibility/manual override.
ALTER TABLE execution_units
 ADD COLUMN last_session_status text,
 ADD COLUMN last_session_checked_at timestamptz,
 ADD COLUMN last_session_reason text;

CREATE TABLE contract_capability_health (
 contract_version text NOT NULL,
 scope text NOT NULL,
 state text NOT NULL DEFAULT 'ENABLED'
   CHECK (state IN ('ENABLED', 'SUSPECTED', 'DISABLED')),
 consecutive_failures integer NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
 distinct_subject_count integer NOT NULL DEFAULT 0 CHECK (distinct_subject_count >= 0),
 first_failed_at timestamptz,
 last_failed_at timestamptz,
 failure_reason text,
 suspected_generation bigint,
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(contract_version, scope)
);

CREATE TABLE contract_capability_failures (
 contract_version text NOT NULL,
 scope text NOT NULL,
 subject_id text NOT NULL,
 lease_generation bigint NOT NULL,
 failure_reason text NOT NULL,
 failed_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(contract_version, scope, subject_id),
 FOREIGN KEY(contract_version, scope)
   REFERENCES contract_capability_health(contract_version, scope) ON DELETE CASCADE
);

INSERT INTO schema_migrations(version) VALUES(6);
