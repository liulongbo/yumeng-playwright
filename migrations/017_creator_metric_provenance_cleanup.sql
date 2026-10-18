-- DATA-02 correction: `field_sources` must not claim a source for a column that holds no value.
--
-- 016 copied the per-field envelope for the five new metrics whenever the *source field* was
-- COLLECTED.  For eight creators the platform answered `item_rate.play_mid` with a label-only
-- envelope (`{"label": ""}`) and no `value` member at all, so `play_median_value_raw` is correctly
-- NULL — but 016 had still registered a `play_median_value_raw` provenance entry for it.
--
-- A provenance entry that describes nothing is exactly the "one timestamp standing in for every
-- field" confusion 011 exists to prevent, read in the other direction: a reader cannot tell a
-- missing value from a missing observation.  This migration removes an entry only when the column
-- it names is NULL, so it can never drop provenance for a stored value.
--
-- Rollback: nothing to revert (the removed keys described no value). Re-running 016 would restore
-- them, which is why the condition lives here rather than in the writer.

UPDATE douyin_xingtu_creator_current
SET field_sources = field_sources - 'play_median_value_raw'
WHERE play_median_value_raw IS NULL AND field_sources ? 'play_median_value_raw';

UPDATE douyin_xingtu_creator_current
SET field_sources = field_sources - 'average_duration_value_raw'
WHERE average_duration_value_raw IS NULL AND field_sources ? 'average_duration_value_raw';

UPDATE douyin_xingtu_creator_current
SET field_sources = field_sources - 'average_likes_value_raw'
WHERE average_likes_value_raw IS NULL AND field_sources ? 'average_likes_value_raw';

UPDATE douyin_xingtu_creator_current
SET field_sources = field_sources - 'average_comments_value_raw'
WHERE average_comments_value_raw IS NULL AND field_sources ? 'average_comments_value_raw';

UPDATE douyin_xingtu_creator_current
SET field_sources = field_sources - 'average_shares_value_raw'
WHERE average_shares_value_raw IS NULL AND field_sources ? 'average_shares_value_raw';

INSERT INTO schema_migrations(version) VALUES(17);
