-- DATA-02 follow-up: give the five backfilled metrics the same per-field provenance a fresh
-- collection writes.
--
-- Migration 015 added `play_median_value_raw` / `average_duration_value_raw` /
-- `average_likes_value_raw` / `average_comments_value_raw` / `average_shares_value_raw` and filled
-- their values from the snapshot JSONB, but `field_sources` stayed empty for those rows.  A
-- backfilled creator would then report `observed_at = null` where a re-collected creator reports a
-- real per-field time — the exact "one row timestamp standing in for every field" confusion that
-- 011 was created to prevent.  This migration copies the existing per-field envelope metadata
-- (observed_at/status/source_kind/source_contract/path_ref/unit/period_label) out of the snapshot
-- for those five columns only.
--
-- It merges into `field_sources` (`||`) and never removes an existing key, so a creator that was
-- already re-collected keeps the newer provenance written by CreatorLibraryWriter.
--
-- Rollback: only removes provenance, never a value. To roll back, revert the application; the
-- extra keys are inert for every reader that looks them up by column name.

UPDATE douyin_xingtu_creator_current c
SET field_sources = c.field_sources || jsonb_strip_nulls(
      jsonb_build_object(
        'play_median_value_raw', (
          SELECT jsonb_strip_nulls(jsonb_build_object(
            'observed_at', f->>'observed_at', 'status', f->>'status',
            'source_kind', f->>'source_kind', 'source_contract', f->>'source_contract',
            'path_ref', f->>'path_ref', 'unit', f->>'unit',
            'period_label', f->>'period_label'))
          FROM creator_snapshots s, jsonb_array_elements(s.payload->'modules'->'spread'->'fields') f
          WHERE s.snapshot_id = c.latest_snapshot_id
            AND f->>'field_key' = 'item_rate_metrics' AND f->>'status' = 'COLLECTED'
        ),
        'average_duration_value_raw', (
          SELECT jsonb_strip_nulls(jsonb_build_object(
            'observed_at', f->>'observed_at', 'status', f->>'status',
            'source_kind', f->>'source_kind', 'source_contract', f->>'source_contract',
            'path_ref', f->>'path_ref', 'unit', f->>'unit',
            'period_label', f->>'period_label'))
          FROM creator_snapshots s, jsonb_array_elements(s.payload->'modules'->'spread'->'fields') f
          WHERE s.snapshot_id = c.latest_snapshot_id
            AND f->>'field_key' = 'average_duration' AND f->>'status' = 'COLLECTED'
        ),
        'average_likes_value_raw', (
          SELECT jsonb_strip_nulls(jsonb_build_object(
            'observed_at', f->>'observed_at', 'status', f->>'status',
            'source_kind', f->>'source_kind', 'source_contract', f->>'source_contract',
            'path_ref', f->>'path_ref', 'unit', f->>'unit',
            'period_label', f->>'period_label'))
          FROM creator_snapshots s, jsonb_array_elements(s.payload->'modules'->'spread'->'fields') f
          WHERE s.snapshot_id = c.latest_snapshot_id
            AND f->>'field_key' = 'average_likes' AND f->>'status' = 'COLLECTED'
        ),
        'average_comments_value_raw', (
          SELECT jsonb_strip_nulls(jsonb_build_object(
            'observed_at', f->>'observed_at', 'status', f->>'status',
            'source_kind', f->>'source_kind', 'source_contract', f->>'source_contract',
            'path_ref', f->>'path_ref', 'unit', f->>'unit',
            'period_label', f->>'period_label'))
          FROM creator_snapshots s, jsonb_array_elements(s.payload->'modules'->'spread'->'fields') f
          WHERE s.snapshot_id = c.latest_snapshot_id
            AND f->>'field_key' = 'average_comments' AND f->>'status' = 'COLLECTED'
        ),
        'average_shares_value_raw', (
          SELECT jsonb_strip_nulls(jsonb_build_object(
            'observed_at', f->>'observed_at', 'status', f->>'status',
            'source_kind', f->>'source_kind', 'source_contract', f->>'source_contract',
            'path_ref', f->>'path_ref', 'unit', f->>'unit',
            'period_label', f->>'period_label'))
          FROM creator_snapshots s, jsonb_array_elements(s.payload->'modules'->'spread'->'fields') f
          WHERE s.snapshot_id = c.latest_snapshot_id
            AND f->>'field_key' = 'average_shares' AND f->>'status' = 'COLLECTED'
        )
      )
    );

INSERT INTO schema_migrations(version) VALUES(16);
