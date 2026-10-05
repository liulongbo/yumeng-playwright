-- UNIT-01 local development stage: an execution unit's network binding is explicit and auditable.
-- Existing rows keep the historical production-line binding.
ALTER TABLE execution_units ADD COLUMN network_mode text NOT NULL DEFAULT 'production_line'
 CHECK (network_mode IN ('production_line', 'local_development'));
INSERT INTO schema_migrations(version) VALUES(2);
