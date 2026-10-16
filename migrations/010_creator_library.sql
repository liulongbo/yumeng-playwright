-- LIB-01: platform-specific read models for the independent Douyin Xingtu creator library.
-- Existing projection JSONB and immutable snapshots remain authoritative; these tables only make
-- approved current fields, history and cooperation offers searchable.

CREATE TABLE douyin_xingtu_creator_current (
 creator_id uuid PRIMARY KEY REFERENCES platform_creators(creator_id),
 platform_creator_id text NOT NULL UNIQUE,
 latest_snapshot_id uuid REFERENCES creator_snapshots(snapshot_id),
 display_name text,
 avatar_uri text,
 creator_type_label text,
 province text,
 city text,
 mcn_name text,
 industry_labels jsonb NOT NULL DEFAULT '[]',
 content_theme_labels jsonb NOT NULL DEFAULT '[]',
 introduction text,
 followers_count numeric,
 followers_raw text,
 followers_is_approximate boolean NOT NULL DEFAULT false,
 monthly_deep_users_count numeric,
 monthly_deep_users_raw text,
 monthly_deep_users_is_approximate boolean NOT NULL DEFAULT false,
 monthly_connected_users_count numeric,
 monthly_follower_growth_rate_raw numeric,
 interaction_rate_value_raw numeric,
 completion_rate_value_raw numeric,
 expected_cpm_21_60_raw numeric,
 expected_cpm_60_plus_raw numeric,
 expected_cpe_21_60_raw numeric,
 expected_cpe_60_plus_raw numeric,
 profile_complete boolean NOT NULL DEFAULT false,
 pipeline_complete boolean NOT NULL DEFAULT false,
 collected_field_count integer NOT NULL DEFAULT 0,
 failed_field_count integer NOT NULL DEFAULT 0,
 field_sources jsonb NOT NULL DEFAULT '{}',
 data_updated_at timestamptz,
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX douyin_xingtu_creator_current_updated
 ON douyin_xingtu_creator_current(data_updated_at DESC NULLS LAST, creator_id);
CREATE INDEX douyin_xingtu_creator_current_filters
 ON douyin_xingtu_creator_current(creator_type_label, province, city, followers_count);
CREATE INDEX douyin_xingtu_creator_current_industry_gin
 ON douyin_xingtu_creator_current USING gin(industry_labels);

CREATE TABLE douyin_xingtu_creator_snapshot_index (
 snapshot_id uuid PRIMARY KEY REFERENCES creator_snapshots(snapshot_id),
 creator_id uuid NOT NULL REFERENCES platform_creators(creator_id),
 captured_at timestamptz NOT NULL,
 profile_complete boolean NOT NULL,
 pipeline_complete boolean NOT NULL,
 module_statuses jsonb NOT NULL DEFAULT '{}',
 metric_statuses jsonb NOT NULL DEFAULT '{}',
 followers_count numeric,
 monthly_deep_users_count numeric,
 monthly_connected_users_count numeric,
 monthly_follower_growth_rate_raw numeric,
 interaction_rate_value_raw numeric,
 completion_rate_value_raw numeric,
 expected_cpm_21_60_raw numeric,
 expected_cpm_60_plus_raw numeric,
 expected_cpe_21_60_raw numeric,
 expected_cpe_60_plus_raw numeric
);
CREATE INDEX douyin_xingtu_creator_snapshot_history
 ON douyin_xingtu_creator_snapshot_index(creator_id, captured_at DESC, snapshot_id DESC);

CREATE TABLE douyin_xingtu_creator_quote_observations (
 snapshot_id uuid NOT NULL REFERENCES creator_snapshots(snapshot_id),
 creator_id uuid NOT NULL REFERENCES platform_creators(creator_id),
 position integer NOT NULL CHECK(position >= 0),
 cooperation_form text,
 settlement_description text,
 price_raw numeric,
 origin_price_raw numeric,
 offer_raw jsonb NOT NULL,
 observed_at timestamptz NOT NULL,
 PRIMARY KEY(snapshot_id, position)
);
CREATE INDEX douyin_xingtu_creator_quote_lookup
 ON douyin_xingtu_creator_quote_observations(creator_id, cooperation_form, observed_at DESC);

-- Backfill from existing current projection and newest immutable snapshot. The write path keeps
-- these rows current afterwards; no existing JSONB is modified.
WITH latest AS (
 SELECT DISTINCT ON (creator_id) snapshot_id, creator_id, payload, created_at
 FROM creator_snapshots
 ORDER BY creator_id, created_at DESC, snapshot_id DESC
)
INSERT INTO douyin_xingtu_creator_current(
 creator_id, platform_creator_id, latest_snapshot_id, display_name, avatar_uri,
 creator_type_label, province, city, mcn_name, industry_labels, content_theme_labels,
 introduction, followers_count, followers_raw, followers_is_approximate,
 monthly_deep_users_count, monthly_deep_users_raw, monthly_deep_users_is_approximate,
 monthly_connected_users_count, monthly_follower_growth_rate_raw,
 interaction_rate_value_raw, completion_rate_value_raw, expected_cpm_21_60_raw,
 expected_cpm_60_plus_raw, expected_cpe_21_60_raw, expected_cpe_60_plus_raw,
 profile_complete, pipeline_complete, collected_field_count, failed_field_count,
 field_sources, data_updated_at
)
SELECT pc.creator_id, pc.platform_creator_id, l.snapshot_id,
 p.projection->'basic.nickname'->>'value', p.projection->'basic.avatar_uri'->>'value',
 p.projection->'basic.creator_type_label'->>'value', p.projection->'basic.province'->>'value',
 p.projection->'basic.city'->>'value', p.projection->'basic.mcn_name'->>'value',
 coalesce(p.projection->'basic.industry_labels'->'value', '[]'),
 coalesce(p.projection->'basic.content_theme_labels'->'value', '[]'),
 p.projection->'basic.introduction'->>'value',
 nullif(p.projection->'basic.followers'->'value'->>'amount', '')::numeric,
 p.projection->'basic.followers'->>'raw_value',
 coalesce((p.projection->'basic.followers'->>'is_approximate')::boolean, false),
 nullif(p.projection->'basic.monthly_deep_users'->'value'->>'amount', '')::numeric,
 p.projection->'basic.monthly_deep_users'->>'raw_value',
 coalesce((p.projection->'basic.monthly_deep_users'->>'is_approximate')::boolean, false),
 nullif(p.projection->'fans.monthly_connected_users'->'value'->>'amount', '')::numeric,
 nullif(p.projection->'basic.monthly_follower_growth_rate'->'value'->>'amount', '')::numeric,
 nullif(p.projection->'spread.interaction_rate'->'value'->'data'->>'value', '')::numeric,
 nullif(p.projection->'spread.completion_rate'->'value'->'data'->>'value', '')::numeric,
 nullif(p.projection->'spread.expected_cpm'->'value'->'data'->>'cpm_21_60', '')::numeric,
 nullif(p.projection->'spread.expected_cpm'->'value'->'data'->>'cpm_60', '')::numeric,
 nullif(p.projection->'spread.expected_cpe'->'value'->'data'->>'cpe_21_60', '')::numeric,
 nullif(p.projection->'spread.expected_cpe'->'value'->'data'->>'cpe_60', '')::numeric,
 coalesce((l.payload->>'profile_complete')::boolean, false),
 coalesce((l.payload->>'pipeline_complete')::boolean, false),
 (SELECT count(*) FROM jsonb_each(p.projection) AS f WHERE f.value->>'status' = 'COLLECTED'),
 (SELECT count(*) FROM jsonb_each(p.projection) AS f WHERE f.value->>'status' = 'FAILED'),
 jsonb_strip_nulls(jsonb_build_object(
   'display_name', p.projection->'basic.nickname',
   'avatar_uri', p.projection->'basic.avatar_uri',
   'creator_type_label', p.projection->'basic.creator_type_label',
   'province', p.projection->'basic.province', 'city', p.projection->'basic.city',
   'mcn_name', p.projection->'basic.mcn_name', 'industry_labels', p.projection->'basic.industry_labels',
   'content_theme_labels', p.projection->'basic.content_theme_labels',
   'introduction', p.projection->'basic.introduction', 'followers_count', p.projection->'basic.followers',
   'monthly_deep_users_count', p.projection->'basic.monthly_deep_users',
   'monthly_connected_users_count', p.projection->'fans.monthly_connected_users',
   'monthly_follower_growth_rate_raw', p.projection->'basic.monthly_follower_growth_rate',
   'interaction_rate_value_raw', p.projection->'spread.interaction_rate',
   'completion_rate_value_raw', p.projection->'spread.completion_rate',
   'expected_cpm_21_60_raw', p.projection->'spread.expected_cpm',
   'expected_cpm_60_plus_raw', p.projection->'spread.expected_cpm',
   'expected_cpe_21_60_raw', p.projection->'spread.expected_cpe',
   'expected_cpe_60_plus_raw', p.projection->'spread.expected_cpe'
 )), l.created_at
FROM platform_creators pc
JOIN platform_creators p USING(creator_id)
LEFT JOIN latest l USING(creator_id)
WHERE pc.platform = 'douyin_xingtu'
ON CONFLICT(creator_id) DO NOTHING;

INSERT INTO douyin_xingtu_creator_snapshot_index(
 snapshot_id, creator_id, captured_at, profile_complete, pipeline_complete,
 module_statuses, metric_statuses, followers_count, monthly_deep_users_count,
 monthly_connected_users_count, monthly_follower_growth_rate_raw,
 interaction_rate_value_raw, completion_rate_value_raw, expected_cpm_21_60_raw,
 expected_cpm_60_plus_raw, expected_cpe_21_60_raw, expected_cpe_60_plus_raw
)
SELECT s.snapshot_id, s.creator_id, s.created_at,
 coalesce((s.payload->>'profile_complete')::boolean, false),
 coalesce((s.payload->>'pipeline_complete')::boolean, false),
 coalesce((SELECT jsonb_object_agg(key, value->'status') FROM jsonb_each(s.payload->'modules')), '{}'),
 coalesce((SELECT jsonb_object_agg(field->>'field_key', field->>'status')
   FROM jsonb_each(s.payload->'modules') AS module,
        jsonb_array_elements(coalesce(module.value->'fields', '[]')) AS field
   WHERE field->>'field_key' IN ('followers','monthly_deep_users','monthly_connected_users',
     'monthly_follower_growth_rate','interaction_rate','completion_rate','expected_cpm','expected_cpe')), '{}'),
 nullif(jsonb_path_query_first(s.payload, '$.modules.*.fields[*] ? (@.field_key == "followers")')#>>'{value,amount}', '')::numeric,
 nullif(jsonb_path_query_first(s.payload, '$.modules.*.fields[*] ? (@.field_key == "monthly_deep_users")')#>>'{value,amount}', '')::numeric,
 nullif(jsonb_path_query_first(s.payload, '$.modules.*.fields[*] ? (@.field_key == "monthly_connected_users")')#>>'{value,amount}', '')::numeric,
 nullif(jsonb_path_query_first(s.payload, '$.modules.*.fields[*] ? (@.field_key == "monthly_follower_growth_rate")')#>>'{value,amount}', '')::numeric,
 nullif(jsonb_path_query_first(s.payload, '$.modules.*.fields[*] ? (@.field_key == "interaction_rate")')#>>'{value,data,value}', '')::numeric,
 nullif(jsonb_path_query_first(s.payload, '$.modules.*.fields[*] ? (@.field_key == "completion_rate")')#>>'{value,data,value}', '')::numeric,
 nullif(jsonb_path_query_first(s.payload, '$.modules.*.fields[*] ? (@.field_key == "expected_cpm")')#>>'{value,data,cpm_21_60}', '')::numeric,
 nullif(jsonb_path_query_first(s.payload, '$.modules.*.fields[*] ? (@.field_key == "expected_cpm")')#>>'{value,data,cpm_60}', '')::numeric,
 nullif(jsonb_path_query_first(s.payload, '$.modules.*.fields[*] ? (@.field_key == "expected_cpe")')#>>'{value,data,cpe_21_60}', '')::numeric,
 nullif(jsonb_path_query_first(s.payload, '$.modules.*.fields[*] ? (@.field_key == "expected_cpe")')#>>'{value,data,cpe_60}', '')::numeric
FROM creator_snapshots s
JOIN platform_creators pc USING(creator_id)
WHERE pc.platform = 'douyin_xingtu'
ON CONFLICT(snapshot_id) DO NOTHING;

INSERT INTO douyin_xingtu_creator_quote_observations(
 snapshot_id, creator_id, position, cooperation_form, settlement_description,
 price_raw, origin_price_raw, offer_raw, observed_at
)
SELECT s.snapshot_id, s.creator_id, offer.position - 1,
 offer.value->>'desc', offer.value->>'settlement_desc',
 nullif(offer.value->>'price', '')::numeric, nullif(offer.value->>'origin_price', '')::numeric,
 offer.value, s.created_at
FROM creator_snapshots s
JOIN platform_creators pc USING(creator_id)
CROSS JOIN LATERAL jsonb_array_elements(
 coalesce(jsonb_path_query_first(s.payload, '$.modules.*.fields[*] ? (@.field_key == "cooperation_offers")')#>'{value,data}', '[]')
) WITH ORDINALITY AS offer(value, position)
WHERE pc.platform = 'douyin_xingtu'
ON CONFLICT(snapshot_id,position) DO NOTHING;

INSERT INTO schema_migrations(version) VALUES(10);
