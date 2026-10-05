"""All platform data below tests is synthetic; never imported by production code."""

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from xingtu.domain import (
    Capabilities,
    ExecutionContext,
    Filter,
    FilterCapability,
    FilterPlan,
    NumberRange,
    uid,
)
from xingtu.repository import Repository


@pytest.fixture
def plan():
    return FilterPlan(
        capability_version="synthetic-v1",
        target_count=2,
        filters=[
            Filter(
                field="followers",
                operator="range",
                value=NumberRange(min=0, max=100000),
                source_fields=["followers_min", "followers_max"],
                unit="count",
            )
        ],
    )


@pytest.fixture
def capabilities():
    return Capabilities(
        version="synthetic-v1",
        status="VERIFIED",
        sample_kind="synthetic",
        fields=[FilterCapability(field="followers", operators=["range"], unit="count")],
        combinations=[["followers"]],
    )


@pytest.fixture
def repo():
    dsn = os.environ.get("XINGTU_TEST_DATABASE_URL")
    if not dsn:
        pytest.fail("XINGTU_TEST_DATABASE_URL required for explicit PostgreSQL integration tests")
    schema = "test_" + uuid4().hex
    with psycopg.connect(dsn) as conn:
        db = conn.execute("SELECT current_database()").fetchone()[0]
        if not db.startswith("xingtu_test"):
            pytest.fail("refusing non-test database")
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    repository = Repository(make_conninfo(dsn, options=f"-csearch_path={schema}"))
    repository.migrate(Path("migrations"))
    repository.register_unit("unit", "synthetic-account", "synthetic-line", "synthetic-profile")
    with repository.connect() as conn:
        conn.execute("UPDATE execution_units SET state='READY',session_version=1")
    try:
        yield repository
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def started(repo, plan):
    root = repo.create(
        plan,
        "unit",
        uid(),
        "test",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
        modules=["basic", "commercial", "fans"],
    )
    task = repo.get(root)
    generation, session = repo.acquire("unit", task.attempt_id)
    return ExecutionContext(
        root_task_id=root,
        task_id=task.task_id,
        attempt_id=task.attempt_id,
        execution_unit_id="unit",
        lease_generation=generation,
        session_version=session,
        capability_version=plan.capability_version,
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
    )
