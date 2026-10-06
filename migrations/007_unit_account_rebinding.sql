-- SESSION-01: bound platform account may only change through an explicit, audited rebinding.
-- The account identity stays immutable during normal operation; every legitimate change of
-- login identity is recorded here with the actor and reason that authorized it.
CREATE TABLE unit_account_rebindings (
 rebinding_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 unit_id text NOT NULL REFERENCES execution_units(unit_id),
 previous_account_id text,
 account_id text NOT NULL,
 actor text NOT NULL,
 reason text NOT NULL,
 evidence_ref text,
 created_at timestamptz NOT NULL DEFAULT now()
);
-- `previous_account_id` mirrors the persisted column and stays NULL when the superseded binding
-- only ever existed in the unit config file (units registered before that column was added).
-- `previous_config_account_id` records that superseded config binding verbatim, so the audit row
-- documents the real before/after even in that case.
ALTER TABLE unit_account_rebindings ADD COLUMN previous_config_account_id text;
CREATE INDEX unit_account_rebindings_unit ON unit_account_rebindings(unit_id, created_at);

INSERT INTO schema_migrations(version) VALUES(7);
