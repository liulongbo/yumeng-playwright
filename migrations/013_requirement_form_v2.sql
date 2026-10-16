-- FILTER-01 keeps the Requirement payload in the existing JSONB column.  The original M3
-- migration nevertheless constrained the adjacent discriminator to v1 only, so publishing v2
-- requires widening that check.  No payload is rewritten and no column or table is added.

ALTER TABLE requirements
  DROP CONSTRAINT requirements_schema_version_check;

ALTER TABLE requirements
  ADD CONSTRAINT requirements_schema_version_check
  CHECK (schema_version IN ('requirement_form.v1', 'requirement_form.v2'));

INSERT INTO schema_migrations(version) VALUES(13);
