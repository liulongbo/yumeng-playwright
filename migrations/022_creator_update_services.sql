-- UPD-06: one scheduled-update service per (platform, creator_scene).
--
-- The existing schedule table and its cycle/backoff/dedup semantics stay authoritative.  This
-- migration only adds the scene dimension every schedule row already implicitly had, the four
-- independent service switches, a scheduler heartbeat and the juxing-video detail locator.
-- No historical snapshot, projection or task row is rewritten.

-- 1) Per-creator schedule is now per (creator, scene).  Legacy rows were created by the
-- image-only Xingtu video updater, so they default to video_square.
ALTER TABLE creator_update_schedule
  ADD COLUMN creator_scene text NOT NULL DEFAULT 'video_square'
  CHECK (creator_scene IN ('video_square', 'live_square'));
ALTER TABLE creator_update_schedule DROP CONSTRAINT creator_update_schedule_pkey;
ALTER TABLE creator_update_schedule ADD PRIMARY KEY (creator_id, creator_scene);
CREATE INDEX creator_update_schedule_due_scene
  ON creator_update_schedule(creator_scene, next_due_at)
  WHERE in_flight_root_task_id IS NULL;

-- 2) Four independent service switches.  Only the existing Xingtu video capability is enabled on
-- migration so a deployment never starts unverified scheduled work; the other three are disabled
-- until their real acceptance is recorded.
CREATE TABLE creator_update_service (
  platform text NOT NULL CHECK (platform IN ('douyin_xingtu', 'kuaishou_juxing')),
  creator_scene text NOT NULL CHECK (creator_scene IN ('video_square', 'live_square')),
  enabled boolean NOT NULL DEFAULT false,
  updated_at timestamptz NOT NULL DEFAULT now(),
  updated_by uuid REFERENCES users(user_id),
  PRIMARY KEY (platform, creator_scene)
);
INSERT INTO creator_update_service(platform, creator_scene, enabled) VALUES
  ('douyin_xingtu', 'video_square', true),
  ('douyin_xingtu', 'live_square', false),
  ('kuaishou_juxing', 'video_square', false),
  ('kuaishou_juxing', 'live_square', false)
ON CONFLICT (platform, creator_scene) DO NOTHING;

-- 3) Scheduler liveness/observability.  No row is inserted here: the UI must show "not running"
-- until a scheduler actually ticks.  The heartbeat is operational state only.
CREATE TABLE creator_update_scheduler_heartbeat (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  last_tick_at timestamptz NOT NULL,
  tick_seconds double precision NOT NULL DEFAULT 60,
  available_scopes jsonb NOT NULL DEFAULT '[]',
  scope_errors jsonb NOT NULL DEFAULT '{}',
  last_result jsonb NOT NULL DEFAULT '{}',
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- 4) Juxing video identities are persisted by userId, while the verified detail route uses
-- starId.  The locator was only ever stored inside task checkpoints, so it is persisted here at
-- publish time for future rows and backfilled once by scripts/backfill_video_homepage.py.
ALTER TABLE platform_creators ADD COLUMN video_homepage text;

INSERT INTO schema_migrations(version) VALUES (22);
