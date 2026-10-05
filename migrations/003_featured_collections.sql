-- F06: default featured collections, cards, work identity and snapshot association.
-- Rows are append-only: a reload that changes the default set creates a new observation instead
-- of editing history. Cover objects are registered in media_objects and referenced only after a
-- verified object write.

CREATE TABLE contents (
 content_id uuid PRIMARY KEY, platform text NOT NULL,
 platform_content_id text, canonical_link text,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(platform, platform_content_id), UNIQUE(platform, canonical_link)
);
CREATE TABLE featured_collections (
 collection_observation_id uuid PRIMARY KEY,
 root_task_id uuid NOT NULL REFERENCES root_tasks,
 creator_id uuid NOT NULL REFERENCES platform_creators,
 collection_type text NOT NULL CHECK(collection_type IN ('excellent_reach','excellent_seeding')),
 status text NOT NULL, observed_at timestamptz NOT NULL, set_key text,
 coverage_gaps jsonb NOT NULL DEFAULT '[]', payload jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX featured_collections_creator ON featured_collections(creator_id, observed_at);
CREATE TABLE featured_cards (
 collection_observation_id uuid NOT NULL REFERENCES featured_collections,
 card_id uuid NOT NULL, position integer NOT NULL, content_id uuid REFERENCES contents,
 identity_kind text NOT NULL, platform_content_id text, canonical_link text, local_key text,
 cover_object_id text, cover_status text NOT NULL, truncated_fields jsonb NOT NULL DEFAULT '[]',
 payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(collection_observation_id, card_id), UNIQUE(collection_observation_id, position)
);
CREATE INDEX featured_cards_content ON featured_cards(content_id);
CREATE INDEX featured_cards_cover ON featured_cards(cover_object_id);
CREATE TABLE snapshot_collections (
 creator_snapshot_id uuid NOT NULL REFERENCES creator_snapshots,
 collection_type text NOT NULL CHECK(collection_type IN ('excellent_reach','excellent_seeding')),
 collection_observation_id uuid NOT NULL REFERENCES featured_collections,
 observed_at timestamptz NOT NULL, status text NOT NULL,
 PRIMARY KEY(creator_snapshot_id, collection_type)
);
CREATE TABLE media_objects (
 object_id text PRIMARY KEY, checksum text NOT NULL, kind text NOT NULL,
 content_type text, byte_size bigint, source_url text,
 root_task_id uuid REFERENCES root_tasks,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE FUNCTION immutable_featured() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'featured observations are append-only'; END $$;
CREATE TRIGGER featured_collections_append_only BEFORE UPDATE OR DELETE ON featured_collections
 FOR EACH ROW EXECUTE FUNCTION immutable_featured();
CREATE TRIGGER featured_cards_append_only BEFORE UPDATE OR DELETE ON featured_cards
 FOR EACH ROW EXECUTE FUNCTION immutable_featured();
INSERT INTO schema_migrations(version) VALUES(3);
