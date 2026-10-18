-- DATA-02: split the seven 「商业能力 → 内容数据」 metrics and the eleven 「创作能力 → 最新视频表现」
-- work fields out of JSONB into independently queryable columns/tables (user-authorised 2026-10-16).
--
-- Design rules carried over from 010/011 and DATA-01:
--   * the JSONB projection and the immutable snapshot stay the source of truth; nothing here
--     rewrites a published snapshot or deletes a JSONB key;
--   * `*_value_raw numeric` means one platform-native leaf value whose scale is not renamed
--     (interaction_rate/completion_rate already follow this: 010:26-27);
--   * a missing observation stays NULL. No column is ever defaulted to 0;
--   * work rows are an append-only observation history keyed by (snapshot_id, module_key, position),
--     mirroring the creator_snapshots/featured_cards immutability precedent (001:41-44, 003:45-50).
--
-- Metric source paths (live-verified 2026-10-16 against 巨量星图, see docs/tasks/CD-08.md):
--   传播量中位数 → spread.item_rate_metrics.data.play_mid.value
--     The same response also carries a top-level `play_mid` (the registered `spread.play_median`
--     leaf, 1399516 for creator 6639192346380468227) which the platform renders nowhere; the card
--     the product shows as 「播放量中位数」 is the nested `item_rate` leaf (766187 = 76.6w).
--   完播率/互动率 → spread.completion_rate / spread.interaction_rate `.data.value` (already stored)
--   平均时长 → spread.average_duration.data  (seconds × 100)
--   平均点赞/评论/转发 → spread.average_likes / average_comments / average_shares `.data`
--
-- Rollback: this migration only adds tables/columns/indexes. To roll back, stop the new
-- API/Mapper write paths and revert the application; the added columns and the work table are
-- kept for audit (改造方案:199). Deleting them is a separate, explicitly authorised data task.

-- ---------------------------------------------------------------------------------------------
-- 1. The five metrics that had no independent column yet.
-- ---------------------------------------------------------------------------------------------
ALTER TABLE douyin_xingtu_creator_current
  ADD COLUMN play_median_value_raw numeric,
  ADD COLUMN average_duration_value_raw numeric,
  ADD COLUMN average_likes_value_raw numeric,
  ADD COLUMN average_comments_value_raw numeric,
  ADD COLUMN average_shares_value_raw numeric;

ALTER TABLE douyin_xingtu_creator_snapshot_index
  ADD COLUMN play_median_value_raw numeric,
  ADD COLUMN average_duration_value_raw numeric,
  ADD COLUMN average_likes_value_raw numeric,
  ADD COLUMN average_comments_value_raw numeric,
  ADD COLUMN average_shares_value_raw numeric;

-- ---------------------------------------------------------------------------------------------
-- 2. Work observations: eleven fields per platform work, append-only, one row per
--    (snapshot, module, position). `content_id` is *this* platform's own work identity and is
--    generated here (user decision 2026-10-16); `platform_item_id`/`platform_video_id` keep the
--    platform's own identifiers untouched.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE douyin_xingtu_creator_video_observations (
  snapshot_id uuid NOT NULL REFERENCES creator_snapshots(snapshot_id),
  creator_id uuid NOT NULL REFERENCES platform_creators(creator_id),
  module_key text NOT NULL CHECK (
    module_key IN ('recent_video_performance','recent_xingtu_video_performance')
  ),
  position integer NOT NULL,
  content_id uuid REFERENCES contents(content_id),
  platform_item_id text,
  platform_video_id text,
  platform_author_id text,
  title text,
  subtitle text,
  published_at timestamptz,
  published_raw text,
  play_count numeric,
  like_count numeric,
  comment_count numeric,
  favorite_count numeric,
  share_count numeric,
  cover_source_uri text,
  work_url text,
  field_statuses jsonb NOT NULL DEFAULT '{}'::jsonb,
  observed_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (snapshot_id, module_key, position)
);

CREATE INDEX douyin_xingtu_creator_video_observations_creator
  ON douyin_xingtu_creator_video_observations(creator_id, snapshot_id, module_key, position);
CREATE INDEX douyin_xingtu_creator_video_observations_work
  ON douyin_xingtu_creator_video_observations(creator_id, platform_item_id);
CREATE INDEX douyin_xingtu_creator_video_observations_content
  ON douyin_xingtu_creator_video_observations(content_id);
CREATE INDEX douyin_xingtu_creator_video_observations_cover
  ON douyin_xingtu_creator_video_observations(cover_source_uri);

CREATE FUNCTION immutable_creator_video() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'creator video observations are append-only'; END $$;
CREATE TRIGGER douyin_xingtu_creator_video_observations_append_only
  BEFORE UPDATE OR DELETE ON douyin_xingtu_creator_video_observations
  FOR EACH ROW EXECUTE FUNCTION immutable_creator_video();

-- ---------------------------------------------------------------------------------------------
-- 3. Cover resolution key.
--    A work's `item_cover` is an opaque platform object-store key; the platform's own page turns it
--    into a signed URL through the already registered /gw/api/fe_common_service/tools/get_sign_image
--    request. Storing that opaque key next to the stored object lets the read side resolve a cover
--    without depending on a short-lived signed URL, and without touching the signed-URL-only
--    featured-cover path.
-- ---------------------------------------------------------------------------------------------
ALTER TABLE media_objects ADD COLUMN source_key text;
CREATE INDEX media_objects_source_key ON media_objects(kind, source_key)
  WHERE source_key IS NOT NULL;

-- ---------------------------------------------------------------------------------------------
-- 4. Backfill: five metrics, per snapshot, for `current` (latest snapshot) and the snapshot index.
-- ---------------------------------------------------------------------------------------------
WITH per_snapshot AS (
  SELECT s.snapshot_id,
    max(CASE WHEN f->>'field_key' = 'item_rate_metrics' AND f->>'status' = 'COLLECTED'
              AND jsonb_typeof(f->'value'->'data') = 'object'
              AND (f->'value'->'data'->'play_mid'->>'value') ~ '^-?[0-9]+(\.[0-9]+)?$'
             THEN (f->'value'->'data'->'play_mid'->>'value')::numeric END) AS play_median,
    max(CASE WHEN f->>'field_key' = 'average_duration' AND f->>'status' = 'COLLECTED'
              AND jsonb_typeof(f->'value'->'data') IN ('string','number')
              AND (f->'value'->>'data') ~ '^-?[0-9]+(\.[0-9]+)?$'
             THEN (f->'value'->>'data')::numeric END) AS average_duration,
    max(CASE WHEN f->>'field_key' = 'average_likes' AND f->>'status' = 'COLLECTED'
              AND jsonb_typeof(f->'value'->'data') IN ('string','number')
              AND (f->'value'->>'data') ~ '^-?[0-9]+(\.[0-9]+)?$'
             THEN (f->'value'->>'data')::numeric END) AS average_likes,
    max(CASE WHEN f->>'field_key' = 'average_comments' AND f->>'status' = 'COLLECTED'
              AND jsonb_typeof(f->'value'->'data') IN ('string','number')
              AND (f->'value'->>'data') ~ '^-?[0-9]+(\.[0-9]+)?$'
             THEN (f->'value'->>'data')::numeric END) AS average_comments,
    max(CASE WHEN f->>'field_key' = 'average_shares' AND f->>'status' = 'COLLECTED'
              AND jsonb_typeof(f->'value'->'data') IN ('string','number')
              AND (f->'value'->>'data') ~ '^-?[0-9]+(\.[0-9]+)?$'
             THEN (f->'value'->>'data')::numeric END) AS average_shares
  FROM creator_snapshots s
  CROSS JOIN LATERAL jsonb_array_elements(s.payload->'modules'->'spread'->'fields') f
  WHERE jsonb_typeof(s.payload->'modules'->'spread'->'fields') = 'array'
  GROUP BY s.snapshot_id
)
UPDATE douyin_xingtu_creator_current c
SET play_median_value_raw = p.play_median,
    average_duration_value_raw = p.average_duration,
    average_likes_value_raw = p.average_likes,
    average_comments_value_raw = p.average_comments,
    average_shares_value_raw = p.average_shares
FROM per_snapshot p
WHERE p.snapshot_id = c.latest_snapshot_id;

WITH per_snapshot AS (
  SELECT s.snapshot_id,
    max(CASE WHEN f->>'field_key' = 'item_rate_metrics' AND f->>'status' = 'COLLECTED'
              AND jsonb_typeof(f->'value'->'data') = 'object'
              AND (f->'value'->'data'->'play_mid'->>'value') ~ '^-?[0-9]+(\.[0-9]+)?$'
             THEN (f->'value'->'data'->'play_mid'->>'value')::numeric END) AS play_median,
    max(CASE WHEN f->>'field_key' = 'average_duration' AND f->>'status' = 'COLLECTED'
              AND jsonb_typeof(f->'value'->'data') IN ('string','number')
              AND (f->'value'->>'data') ~ '^-?[0-9]+(\.[0-9]+)?$'
             THEN (f->'value'->>'data')::numeric END) AS average_duration,
    max(CASE WHEN f->>'field_key' = 'average_likes' AND f->>'status' = 'COLLECTED'
              AND jsonb_typeof(f->'value'->'data') IN ('string','number')
              AND (f->'value'->>'data') ~ '^-?[0-9]+(\.[0-9]+)?$'
             THEN (f->'value'->>'data')::numeric END) AS average_likes,
    max(CASE WHEN f->>'field_key' = 'average_comments' AND f->>'status' = 'COLLECTED'
              AND jsonb_typeof(f->'value'->'data') IN ('string','number')
              AND (f->'value'->>'data') ~ '^-?[0-9]+(\.[0-9]+)?$'
             THEN (f->'value'->>'data')::numeric END) AS average_comments,
    max(CASE WHEN f->>'field_key' = 'average_shares' AND f->>'status' = 'COLLECTED'
              AND jsonb_typeof(f->'value'->'data') IN ('string','number')
              AND (f->'value'->>'data') ~ '^-?[0-9]+(\.[0-9]+)?$'
             THEN (f->'value'->>'data')::numeric END) AS average_shares
  FROM creator_snapshots s
  CROSS JOIN LATERAL jsonb_array_elements(s.payload->'modules'->'spread'->'fields') f
  WHERE jsonb_typeof(s.payload->'modules'->'spread'->'fields') = 'array'
  GROUP BY s.snapshot_id
)
UPDATE douyin_xingtu_creator_snapshot_index si
SET play_median_value_raw = p.play_median,
    average_duration_value_raw = p.average_duration,
    average_likes_value_raw = p.average_likes,
    average_comments_value_raw = p.average_comments,
    average_shares_value_raw = p.average_shares
FROM per_snapshot p
WHERE p.snapshot_id = si.snapshot_id;

-- ---------------------------------------------------------------------------------------------
-- 5. Backfill: register the platform's own work identity in `contents` (this platform's work id).
--    One row per distinct platform work id, using the newest observation's share link.
-- ---------------------------------------------------------------------------------------------
WITH raw_rows AS (
  SELECT s.created_at,
         f->>'field_key' AS module_key,
         (ord.ordinality - 1)::integer AS position,
         ord.item AS item
  FROM creator_snapshots s
  CROSS JOIN LATERAL jsonb_array_elements(s.payload->'modules'->'creation'->'fields') f
  CROSS JOIN LATERAL jsonb_array_elements(f->'value'->'data') WITH ORDINALITY AS ord(item, ordinality)
  WHERE jsonb_typeof(s.payload->'modules'->'creation'->'fields') = 'array'
    AND f->>'field_key' IN ('recent_video_performance','recent_xingtu_video_performance')
    AND jsonb_typeof(f->'value'->'data') = 'array'
    AND jsonb_typeof(ord.item) = 'object'
), newest_per_work AS (
  -- NULLIF is required: an empty share link must stay NULL. `contents` is uniquely keyed on
  -- (platform, canonical_link), so inserting '' for several different works would make every later
  -- one collide and silently keep the work out of `contents` (observed while validating 015).
  SELECT DISTINCT ON (item->>'item_id') item->>'item_id' AS item_id,
         NULLIF(item->>'url', '') AS work_url
  FROM raw_rows
  WHERE NULLIF(item->>'item_id', '') IS NOT NULL
  ORDER BY item->>'item_id', created_at DESC, module_key, position
)
INSERT INTO contents(content_id, platform, platform_content_id, canonical_link)
SELECT gen_random_uuid(), 'douyin_xingtu', item_id, work_url
FROM newest_per_work
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------------------------
-- 6. Backfill: one work observation row per historical JSONB work record.
--    `published_at` prefers the platform's exact Unix-second `create_time` and falls back to the
--    platform's own `item_date` (CD-05 verified `item_date == utc(create_time)` 15/15).
--    `subtitle` and `favorite_count` have never appeared in any collected record (0/3064 keys in the
--    whole development database); they stay NULL and `field_statuses` says why — never a 0 filler.
-- ---------------------------------------------------------------------------------------------
WITH raw_rows AS (
  SELECT s.snapshot_id,
         s.creator_id,
         f->>'field_key' AS module_key,
         (ord.ordinality - 1)::integer AS position,
         ord.item AS item,
         NULLIF(f->>'observed_at', '')::timestamptz AS field_observed_at,
         s.created_at AS snapshot_created_at
  FROM creator_snapshots s
  CROSS JOIN LATERAL jsonb_array_elements(s.payload->'modules'->'creation'->'fields') f
  CROSS JOIN LATERAL jsonb_array_elements(f->'value'->'data') WITH ORDINALITY AS ord(item, ordinality)
  WHERE jsonb_typeof(s.payload->'modules'->'creation'->'fields') = 'array'
    AND f->>'field_key' IN ('recent_video_performance','recent_xingtu_video_performance')
    AND jsonb_typeof(f->'value'->'data') = 'array'
    AND jsonb_typeof(ord.item) = 'object'
)
INSERT INTO douyin_xingtu_creator_video_observations(
  snapshot_id, creator_id, module_key, position, content_id, platform_item_id, platform_video_id,
  platform_author_id, title, subtitle, published_at, published_raw, play_count, like_count,
  comment_count, favorite_count, share_count, cover_source_uri, work_url, field_statuses, observed_at)
SELECT r.snapshot_id,
       r.creator_id,
       r.module_key,
       r.position,
       c.content_id,
       NULLIF(r.item->>'item_id', ''),
       NULLIF(r.item->>'video_id', ''),
       NULLIF(r.item->>'core_user_id', ''),
       COALESCE(NULLIF(r.item->>'title', ''), NULLIF(r.item->>'item_title', '')),
       NULL,
       CASE
         WHEN (r.item->>'create_time') ~ '^[0-9]+$' THEN to_timestamp((r.item->>'create_time')::bigint)
         WHEN (r.item->>'item_date') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
           THEN (r.item->>'item_date')::date::timestamptz
         ELSE NULL
       END,
       COALESCE(NULLIF(r.item->>'item_date', ''), NULLIF(r.item->>'create_time', '')),
       CASE WHEN (r.item->>'play') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (r.item->>'play')::numeric END,
       CASE WHEN (r.item->>'like') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (r.item->>'like')::numeric END,
       CASE WHEN (r.item->>'comment') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (r.item->>'comment')::numeric END,
       CASE WHEN (r.item->>'favorite_count') ~ '^-?[0-9]+(\.[0-9]+)?$'
             THEN (r.item->>'favorite_count')::numeric
            WHEN (r.item->>'collect') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (r.item->>'collect')::numeric
            ELSE NULL END,
       CASE WHEN (r.item->>'share') ~ '^-?[0-9]+(\.[0-9]+)?$' THEN (r.item->>'share')::numeric END,
       NULLIF(r.item->>'item_cover', ''),
       NULLIF(r.item->>'url', ''),
       jsonb_build_object(
         'title', CASE WHEN NULLIF(COALESCE(r.item->>'title', r.item->>'item_title'), '') IS NULL
                       THEN 'NOT_PROVIDED' ELSE 'COLLECTED' END,
         'cover', CASE WHEN NULLIF(r.item->>'item_cover', '') IS NULL
                       THEN 'NOT_PROVIDED' ELSE 'COLLECTED' END,
         'subtitle', CASE WHEN r.item ? 'subtitle' OR r.item ? 'item_subtitle'
                          THEN 'COLLECTED' ELSE 'NOT_PROVIDED' END,
         'favorite_count', CASE WHEN r.item ? 'favorite_count' OR r.item ? 'collect'
                                THEN 'COLLECTED' ELSE 'NOT_PROVIDED' END,
         'share_count', CASE WHEN r.item ? 'share' THEN 'COLLECTED' ELSE 'NOT_PROVIDED' END,
         'play_count', CASE WHEN r.item ? 'play' THEN 'COLLECTED' ELSE 'NOT_PROVIDED' END,
         'like_count', CASE WHEN r.item ? 'like' THEN 'COLLECTED' ELSE 'NOT_PROVIDED' END,
         'comment_count', CASE WHEN r.item ? 'comment' THEN 'COLLECTED' ELSE 'NOT_PROVIDED' END,
         'platform_item_id', CASE WHEN NULLIF(r.item->>'item_id', '') IS NULL
                                  THEN 'NOT_PROVIDED' ELSE 'COLLECTED' END,
         'platform_author_id', CASE WHEN NULLIF(r.item->>'core_user_id', '') IS NULL
                                    THEN 'NOT_PROVIDED' ELSE 'COLLECTED' END,
         'published_at', CASE
           WHEN (r.item->>'create_time') ~ '^[0-9]+$'
             OR (r.item->>'item_date') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN 'COLLECTED'
           ELSE 'NOT_PROVIDED' END
       ),
       COALESCE(r.field_observed_at, r.snapshot_created_at)
FROM raw_rows r
LEFT JOIN contents c
  ON c.platform = 'douyin_xingtu' AND c.platform_content_id = r.item->>'item_id'
ON CONFLICT (snapshot_id, module_key, position) DO NOTHING;

INSERT INTO schema_migrations(version) VALUES(15);
