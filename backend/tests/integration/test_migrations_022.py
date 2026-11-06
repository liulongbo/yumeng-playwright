"""UPD-06 migration 022 upgrade path from the existing single-scene schedule.

Builds a schema at version 21 with real legacy rows, applies the production migration runner, and
checks the additive scene dimension, the four switch defaults and idempotent re-application.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from xingtu.repository import Repository

ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = ROOT / "migrations"


def test_022_preserves_legacy_plan_and_adds_scene_and_switches() -> None:
    base_dsn = os.environ.get("XINGTU_TEST_DATABASE_URL")
    if not base_dsn:
        pytest.fail("XINGTU_TEST_DATABASE_URL required for explicit PostgreSQL integration tests")
    schema = "mig22_" + uuid4().hex[:10]
    with psycopg.connect(base_dsn) as conn:
        database = conn.execute("SELECT current_database()").fetchone()[0]
        if not str(database).startswith("xingtu_test"):
            pytest.fail("refusing non-test database")
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(base_dsn, options=f"-csearch_path={schema}")
    creator_id = str(uuid4())
    try:
        legacy = psycopg.connect(dsn)
        try:
            with legacy.cursor() as cursor:
                for path in sorted(MIGRATIONS.glob("0*.sql")):
                    if path.name.startswith("022_"):
                        break
                    cursor.execute(path.read_text())
            legacy.commit()
        finally:
            legacy.close()

        with psycopg.connect(dsn) as conn:
            assert conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 21
            conn.execute(
                """INSERT INTO platform_creators(creator_id,platform,platform_creator_id)
                VALUES(%s,'douyin_xingtu','legacy-video-1')""",
                (creator_id,),
            )
            conn.execute(
                """INSERT INTO creator_update_schedule(
                creator_id,next_due_at,tier,interval_days)
                VALUES(%s,now(),'lt_1w',15)""",
                (creator_id,),
            )

        repository = Repository(dsn)
        repository.migrate(MIGRATIONS)

        with psycopg.connect(dsn) as conn:
            assert conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 22
            legacy_row = conn.execute(
                """SELECT creator_scene,next_due_at,tier,interval_days
                FROM creator_update_schedule WHERE creator_id=%s""",
                (creator_id,),
            ).fetchone()
            assert legacy_row[0] == "video_square"
            assert legacy_row[2] == "lt_1w" and legacy_row[3] == 15

            services = {
                (row[0], row[1]): row[2]
                for row in conn.execute(
                    "SELECT platform,creator_scene,enabled FROM creator_update_service"
                ).fetchall()
            }
            assert services == {
                ("douyin_xingtu", "video_square"): True,
                ("douyin_xingtu", "live_square"): False,
                ("kuaishou_juxing", "video_square"): False,
                ("kuaishou_juxing", "live_square"): False,
            }
            assert (
                conn.execute(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema=current_schema() AND table_name='platform_creators' "
                    "AND column_name='video_homepage'"
                ).fetchone()[0]
                == 1
            )
            assert (
                conn.execute(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema=current_schema() "
                    "AND table_name='creator_update_scheduler_heartbeat'"
                ).fetchone()[0]
                == 1
            )

            # The same creator may now have an independent live plan.
            conn.execute(
                """INSERT INTO creator_update_schedule(
                creator_id,creator_scene,next_due_at,tier,interval_days)
                VALUES(%s,'live_square',now(),'lt_1w',15)""",
                (creator_id,),
            )
            assert (
                conn.execute(
                    "SELECT count(*) FROM creator_update_schedule WHERE creator_id=%s",
                    (creator_id,),
                ).fetchone()[0]
                == 2
            )
            with pytest.raises(psycopg.errors.UniqueViolation):
                conn.execute(
                    """INSERT INTO creator_update_schedule(
                    creator_id,creator_scene,next_due_at,tier,interval_days)
                    VALUES(%s,'video_square',now(),'lt_1w',15)""",
                    (creator_id,),
                )
            conn.rollback()

        # Re-running the production runner applies nothing and does not duplicate the version.
        repository.migrate(MIGRATIONS)
        with psycopg.connect(dsn) as conn:
            assert (
                conn.execute("SELECT count(*) FROM schema_migrations WHERE version=22").fetchone()[
                    0
                ]
                == 1
            )
            assert conn.execute("SELECT count(*) FROM creator_update_service").fetchone()[0] == 4
    finally:
        with psycopg.connect(base_dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
