-- FIX-01 P1-B: record when the P2 collection workflow was actually started for a dispatch.
--
-- Cancelling an already-QUEUED task used to park it in CANCELLING until the P2 worker's dispatch
-- loop finalised it. With no P2 worker running the task never reached a terminal state even though
-- nothing had been dispatched for it at all. The API can only tell "no collection can hold this
-- task" from a durable fact, so the dispatch row now records the start moment.
--
-- The new column is nullable and defaults to NULL: existing dispatch rows keep their current
-- meaning (`sent=false` and no recorded start is exactly the "never dispatched" state), and no
-- existing row is rewritten.

ALTER TABLE task_dispatches ADD COLUMN IF NOT EXISTS workflow_started_at timestamptz;

INSERT INTO schema_migrations(version) VALUES(9);
