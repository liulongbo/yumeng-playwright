-- LIB-01 follow-up: normalise already-backfilled source objects to the query-read-model
-- allowlist. Raw business values remain only in their existing authoritative JSONB columns.

UPDATE douyin_xingtu_creator_current c
SET field_sources = COALESCE((
 SELECT jsonb_object_agg(mapping.target_key, jsonb_strip_nulls(jsonb_build_object(
   'observed_at', source.value->'observed_at', 'status', source.value->'status',
   'source_kind', source.value->'source_kind', 'source_contract', source.value->'source_contract',
   'path_ref', source.value->'path_ref', 'unit', source.value->'unit',
   'period_label', source.value->'period_label'
 )))
 FROM (VALUES
   ('display_name','basic.nickname'), ('avatar_uri','basic.avatar_uri'),
   ('creator_type_label','basic.creator_type_label'), ('province','basic.province'),
   ('city','basic.city'), ('mcn_name','basic.mcn_name'), ('industry_labels','basic.industry_labels'),
   ('content_theme_labels','basic.content_theme_labels'), ('introduction','basic.introduction'),
   ('followers_count','basic.followers'), ('monthly_deep_users_count','basic.monthly_deep_users'),
   ('monthly_connected_users_count','fans.monthly_connected_users'),
   ('monthly_follower_growth_rate_raw','basic.monthly_follower_growth_rate'),
   ('interaction_rate_value_raw','spread.interaction_rate'),
   ('completion_rate_value_raw','spread.completion_rate'),
   ('expected_cpm_21_60_raw','spread.expected_cpm'), ('expected_cpm_60_plus_raw','spread.expected_cpm'),
   ('expected_cpe_21_60_raw','spread.expected_cpe'), ('expected_cpe_60_plus_raw','spread.expected_cpe')
 ) AS mapping(target_key, projection_key)
 CROSS JOIN LATERAL (SELECT c.field_sources->mapping.projection_key AS value) AS source
 WHERE source.value IS NOT NULL
), '{}'::jsonb)
WHERE c.field_sources <> '{}'::jsonb;

INSERT INTO schema_migrations(version) VALUES(11);
