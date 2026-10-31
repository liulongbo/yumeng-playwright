-- KJX-01: additive platform routing for one-task/one-platform and shared execution units.
-- Existing tasks and unit bindings are backfilled as Douyin Xingtu, preserving old semantics.
--
-- Migration 013 widened the requirement discriminator for `requirement_form.v2` only.  Stage A
-- introduced the juxing `requirement_form.v3` payload, so the same constraint must admit it or
-- every juxing submission dies with a CheckViolation before intake.  No payload is rewritten.
ALTER TABLE requirements
  DROP CONSTRAINT requirements_schema_version_check;
ALTER TABLE requirements
  ADD CONSTRAINT requirements_schema_version_check
  CHECK (schema_version IN ('requirement_form.v1', 'requirement_form.v2', 'requirement_form.v3'));

ALTER TABLE root_tasks
  ADD COLUMN platform text NOT NULL DEFAULT 'douyin_xingtu'
  CHECK (platform IN ('douyin_xingtu', 'kuaishou_juxing'));
CREATE INDEX root_tasks_platform_state_created
  ON root_tasks(platform, state, created_at DESC, root_task_id DESC);

CREATE TABLE execution_unit_platform_bindings (
  unit_id text NOT NULL REFERENCES execution_units(unit_id) ON DELETE CASCADE,
  platform text NOT NULL CHECK (platform IN ('douyin_xingtu', 'kuaishou_juxing')),
  account_ref text NOT NULL,
  expected_account_id text NOT NULL,
  profile_ref text NOT NULL,
  registry_ref text NOT NULL,
  enabled boolean NOT NULL DEFAULT true,
  last_observed_status text CHECK (
    last_observed_status IS NULL OR last_observed_status IN (
      'VALID', 'LOGIN_REQUIRED', 'ACCOUNT_MISMATCH', 'SECURITY_CHALLENGE', 'INDETERMINATE'
    )
  ),
  last_observed_at timestamptz,
  last_observed_reason text,
  PRIMARY KEY(unit_id, platform),
  UNIQUE(platform, account_ref),
  UNIQUE(profile_ref)
);
CREATE INDEX execution_unit_platform_bindings_eligible
  ON execution_unit_platform_bindings(platform, unit_id) WHERE enabled;

INSERT INTO execution_unit_platform_bindings(
  unit_id, platform, account_ref, expected_account_id, profile_ref, registry_ref, enabled,
  last_observed_status, last_observed_at, last_observed_reason
)
SELECT unit_id, 'douyin_xingtu', account_ref,
       COALESCE(expected_account_id, account_ref), profile_ref,
       'contracts/douyin_xingtu.verified.json', true,
       last_session_status, last_session_checked_at, last_session_reason
FROM execution_units
ON CONFLICT(unit_id, platform) DO NOTHING;

INSERT INTO schema_migrations(version) VALUES(20);
