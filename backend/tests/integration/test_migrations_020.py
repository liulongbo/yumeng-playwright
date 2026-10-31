"""KJX-01 C1: migration 020 upgrade path from an existing Xingtu-only schema.

This is deliberately not the normal `repo` fixture (which migrates straight to head).  It builds a
legacy schema at version 19, inserts a real Xingtu unit/task, then applies 020 through the
production migration runner and checks the backfill, the `requirement_form.v3` constraint and
idempotency.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb
from xingtu.domain import uid
from xingtu.product_auth import PasswordService
from xingtu.product_repository import ProductRepository
from xingtu.repository import Repository

ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = ROOT / "migrations"


def test_020_backfills_legacy_xingtu_and_accepts_v3() -> None:
    base_dsn = os.environ.get("XINGTU_TEST_DATABASE_URL")
    if not base_dsn:
        pytest.fail("XINGTU_TEST_DATABASE_URL required for explicit PostgreSQL integration tests")
    schema = "mig20_" + uuid4().hex[:10]
    with psycopg.connect(base_dsn) as conn:
        database = conn.execute("SELECT current_database()").fetchone()[0]
        if not str(database).startswith("xingtu_test"):
            pytest.fail("refusing non-test database")
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(base_dsn, options=f"-csearch_path={schema}")
    unit_id = "legacy-unit"
    legacy_root = str(uuid4())
    requirement_roots = [str(uuid4()) for _ in range(3)]
    user_id = str(uuid4())

    try:
        legacy_conn = psycopg.connect(dsn)
        try:
            with legacy_conn.cursor() as cursor:
                for path in sorted(MIGRATIONS.glob("0*.sql")):
                    if path.name.startswith("020_"):
                        break
                    cursor.execute(path.read_text())
            legacy_conn.commit()
        finally:
            legacy_conn.close()

        with psycopg.connect(dsn) as conn:
            conn.execute(
                """INSERT INTO execution_units(
                unit_id,account_ref,line_ref,profile_ref,network_mode,expected_account_id,
                state,session_version,last_session_status,last_session_checked_at,last_session_reason)
                VALUES(%s,'legacy-account','legacy-line','/private/legacy-profile',
                'local_development','legacy-account','READY',1,'VALID',now(),'LEGACY_SESSION')""",
                (unit_id,),
            )
            for root in (legacy_root, *requirement_roots):
                conn.execute(
                    """INSERT INTO root_tasks(root_task_id,state,version,unit_id,payload)
                    VALUES(%s,'COMPLETED',1,%s,%s)""",
                    (root, unit_id, Jsonb({"schema_version": "legacy_root_task.v1"})),
                )
            conn.execute(
                "INSERT INTO users(user_id,username,display_name,password_hash) "
                "VALUES(%s,'legacy-media','Legacy',%s)",
                (user_id, PasswordService().hash("legacy-password")),
            )
            assert conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 19
            assert (
                conn.execute(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema=current_schema() "
                    "AND table_name='root_tasks' AND column_name='platform'"
                ).fetchone()[0]
                == 0
            )

        repository = Repository(dsn)
        repository.migrate(MIGRATIONS)

        with psycopg.connect(dsn) as conn:
            assert conn.execute("SELECT platform FROM root_tasks").fetchone()[0] == "douyin_xingtu"
            binding = conn.execute(
                """SELECT platform,account_ref,expected_account_id,profile_ref,registry_ref,
                last_observed_status,last_observed_reason
                FROM execution_unit_platform_bindings"""
            ).fetchone()
            assert binding == (
                "douyin_xingtu",
                "legacy-account",
                "legacy-account",
                "/private/legacy-profile",
                "contracts/douyin_xingtu.verified.json",
                "VALID",
                "LEGACY_SESSION",
            )
            # The widened discriminator accepts all historical revisions and the new v3 form.
            for version, root in zip(
                ("requirement_form.v1", "requirement_form.v2", "requirement_form.v3"),
                requirement_roots,
                strict=True,
            ):
                conn.execute(
                    """INSERT INTO requirements(
                    requirement_id,root_task_id,submitted_by,schema_version,
                    capability_version,payload)
                    VALUES(%s,%s,%s,%s,'legacy-capability','{}'::jsonb)""",
                    (str(uuid4()), root, user_id, version),
                )
            stored = {
                row[0] for row in conn.execute("SELECT schema_version FROM requirements").fetchall()
            }
            assert stored == {
                "requirement_form.v1",
                "requirement_form.v2",
                "requirement_form.v3",
            }

        # Re-running the production runner applies nothing and does not duplicate the version.
        repository.migrate(MIGRATIONS)
        with psycopg.connect(dsn) as conn:
            assert (
                conn.execute("SELECT count(*) FROM schema_migrations WHERE version=20").fetchone()[
                    0
                ]
                == 1
            )
            assert (
                conn.execute("SELECT count(*) FROM execution_unit_platform_bindings").fetchone()[0]
                == 1
            )
    finally:
        with psycopg.connect(base_dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_head_schema_persists_a_v3_requirement(repo, plan) -> None:
    """The normal migrated schema accepts a v3 requirement through the product repository."""
    products = ProductRepository(repo)
    product_user = products.create_user(
        "mig20-user", "迁移用户", PasswordService().hash("a-secure-password"), actor="test"
    )
    root = repo.create(
        plan,
        "unit",
        "mig20-task",
        "test",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
        modules=["basic"],
    )
    requirement_id = uid()
    with repo.connect() as conn:
        conn.execute(
            """INSERT INTO requirements(
            requirement_id,root_task_id,submitted_by,schema_version,capability_version,payload)
            VALUES(%s,%s,%s,'requirement_form.v3','juxing-video-square-stage-b-v1','{}'::jsonb)""",
            (requirement_id, root, product_user),
        )
        row = conn.execute(
            "SELECT schema_version FROM requirements WHERE requirement_id=%s",
            (requirement_id,),
        ).fetchone()
    assert row is not None and row["schema_version"] == "requirement_form.v3"
