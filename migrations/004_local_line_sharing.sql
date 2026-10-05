-- Two local development units on one machine share the same (unbound) local egress, so a
-- global line uniqueness would force fake line ids. Production lines stay exclusive: the
-- unique constraint is replaced by a partial unique index that only covers production_line.
ALTER TABLE execution_units DROP CONSTRAINT execution_units_line_ref_key;
CREATE UNIQUE INDEX execution_units_production_line_ref_key
 ON execution_units(line_ref) WHERE network_mode = 'production_line';
INSERT INTO schema_migrations(version) VALUES(4);
