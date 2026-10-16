-- UI-01 requirement 4: give a product task a real completion moment.
--
-- Before this migration `root_tasks` only carried `created_at` and `updated_at`. `updated_at` is
-- rewritten on every state/version change (intake takeover, each collection stage, progress
-- checkpoints, cancel/continue/retry, wait states), so it is a "last write" audit value and cannot
-- answer "when did this task finish". Nothing about existing columns or behaviour is changed here:
-- `updated_at` keeps its current meaning and write sites.

ALTER TABLE root_tasks ADD COLUMN completed_at timestamptz;

-- Existing terminal rows have no recorded terminal transition, so the only available source is the
-- final write that parked them in their terminal state: `updated_at`. This is a documented
-- best-effort backfill for historical rows (an approximation, not original evidence); the runtime
-- write path records the real moment from now on.
UPDATE root_tasks
SET completed_at = updated_at
WHERE state IN ('COMPLETED', 'PARTIAL_COMPLETED', 'CANCELLED', 'FAILED', 'FAILED_VALIDATION')
  AND completed_at IS NULL;

INSERT INTO schema_migrations(version) VALUES(12);
