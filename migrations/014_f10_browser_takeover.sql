-- F10: durable, fenced facts for an authenticated human taking over the *existing*
-- browser window during a platform security challenge. Browser objects and VNC endpoints
-- remain process/private-network local and are deliberately not stored here.
ALTER TABLE execution_units
 ADD COLUMN last_heartbeat_at timestamptz,
 ADD COLUMN browser_instance_id text,
 ADD COLUMN browser_started_at timestamptz;

CREATE TABLE verification_events (
 event_id uuid PRIMARY KEY,
 unit_id text NOT NULL REFERENCES execution_units(unit_id),
 root_task_id uuid NOT NULL REFERENCES root_tasks(root_task_id),
 lease_generation bigint NOT NULL,
 browser_instance_id text NOT NULL,
 state text NOT NULL CHECK (state IN ('OPEN','ACKNOWLEDGED','RESOLVED','EXPIRED')),
 reason text NOT NULL,
 detected_at timestamptz NOT NULL DEFAULT now(),
 last_detected_at timestamptz NOT NULL DEFAULT now(),
 deadline_at timestamptz NOT NULL,
 resolved_at timestamptz,
 reappearance_count integer NOT NULL DEFAULT 0 CHECK (reappearance_count >= 0)
);
CREATE UNIQUE INDEX verification_events_open_instance
 ON verification_events(unit_id, root_task_id, browser_instance_id)
 WHERE state IN ('OPEN','ACKNOWLEDGED');
CREATE INDEX verification_events_open_detected
 ON verification_events(state, detected_at DESC);

CREATE TABLE browser_takeover_sessions (
 takeover_id uuid PRIMARY KEY,
 event_id uuid NOT NULL REFERENCES verification_events(event_id),
 unit_id text NOT NULL REFERENCES execution_units(unit_id),
 root_task_id uuid NOT NULL REFERENCES root_tasks(root_task_id),
 lease_generation bigint NOT NULL,
 browser_instance_id text NOT NULL,
 actor_user_id uuid NOT NULL REFERENCES users(user_id),
 state text NOT NULL CHECK (state IN (
   'REQUESTED','ACTIVE','VERIFYING','RESUMED','FAILED','EXPIRED','RELEASED'
 )),
 failure_reason text,
 ticket_digest text,
 viewer_connection_id text,
 viewer_connected_at timestamptz,
 viewer_disconnected_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(),
 activated_at timestamptz,
 last_human_action_at timestamptz,
 expires_at timestamptz NOT NULL,
 completed_at timestamptz
);
CREATE UNIQUE INDEX browser_takeover_one_active_per_unit
 ON browser_takeover_sessions(unit_id)
 WHERE state IN ('REQUESTED','ACTIVE','VERIFYING');
CREATE INDEX browser_takeover_lookup
 ON browser_takeover_sessions(takeover_id, actor_user_id);

INSERT INTO schema_migrations(version) VALUES(14);
