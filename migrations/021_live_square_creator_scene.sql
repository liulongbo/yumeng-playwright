-- LIVE-02: scene dimension for the dual-platform live creator square.
-- Additive only: old rows default to video_square, existing video projections/read models are
-- untouched, and live business data gets its own current table.

ALTER TABLE root_tasks
  ADD COLUMN creator_scene text NOT NULL DEFAULT 'video_square'
  CHECK (creator_scene IN ('video_square', 'live_square'));
CREATE INDEX root_tasks_platform_scene_state_created
  ON root_tasks(platform, creator_scene, state, created_at DESC, root_task_id DESC);

ALTER TABLE creator_snapshots
  ADD COLUMN creator_scene text NOT NULL DEFAULT 'video_square'
  CHECK (creator_scene IN ('video_square', 'live_square'));
CREATE INDEX creator_snapshots_scene_history
  ON creator_snapshots(creator_id, creator_scene, created_at DESC, snapshot_id DESC);

CREATE TABLE creator_live_current (
  creator_id uuid PRIMARY KEY REFERENCES platform_creators(creator_id),
  platform text NOT NULL CHECK (platform IN ('douyin_xingtu', 'kuaishou_juxing')),
  platform_creator_id text NOT NULL,
  platform_star_id text,
  latest_snapshot_id uuid REFERENCES creator_snapshots(snapshot_id),
  display_name text,
  avatar_uri text,
  gender text,
  province text,
  city text,
  creator_type_label text,
  industry_labels jsonb NOT NULL DEFAULT '[]',
  content_theme_labels jsonb NOT NULL DEFAULT '[]',
  mcn_name text,
  followers_count numeric,
  followers_raw text,
  followers_is_approximate boolean NOT NULL DEFAULT false,
  live_metrics jsonb NOT NULL DEFAULT '{}',
  profile_complete boolean NOT NULL DEFAULT false,
  pipeline_complete boolean NOT NULL DEFAULT false,
  collected_field_count integer NOT NULL DEFAULT 0,
  failed_field_count integer NOT NULL DEFAULT 0,
  field_sources jsonb NOT NULL DEFAULT '{}',
  data_updated_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(platform, platform_creator_id)
);
CREATE INDEX creator_live_current_updated
  ON creator_live_current(platform, data_updated_at DESC NULLS LAST, creator_id);
CREATE INDEX creator_live_current_followers
  ON creator_live_current(platform, followers_count);

INSERT INTO schema_migrations(version) VALUES (21);
