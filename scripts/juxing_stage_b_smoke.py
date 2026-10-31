"""Authorized stage-B Juxing smoke: one real creator, isolated PostgreSQL schema.

The script deliberately reuses BrowserHost, the platform adapter, Engine and Repository. It
performs read-only creator discovery/detail calls, refuses any database whose name does not start
with ``xingtu_test``, drops its random schema after verification, and writes only a sanitized
summary (never creator names, ids, field values, cookies, headers or response bodies).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from xingtu.adapter_factory import build_platform_adapter  # noqa: E402
from xingtu.browser_host import BrowserHost  # noqa: E402
from xingtu.contracts import PlatformRegistry  # noqa: E402
from xingtu.domain import (  # noqa: E402
    ExecutionContext,
    Filter,
    FilterPlan,
    PlatformId,
)
from xingtu.engine import Engine  # noqa: E402
from xingtu.platform_runtime import apply_private_permissions  # noqa: E402
from xingtu.repository import Repository  # noqa: E402
from xingtu.runtime import load_unit  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="磁力聚星阶段 B：1 位真实达人隔离闭环")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--private-root", type=Path, default=ROOT / ".runtime")
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / ".runtime" / "juxing-stage-b" / "smoke-report.json",
    )
    return parser.parse_args()


def write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    apply_private_permissions(path.parent, 0o700)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    apply_private_permissions(temporary, 0o600)
    temporary.replace(path)


async def collect_one(options: argparse.Namespace, repository: Repository) -> dict[str, Any]:
    unit_config = load_unit(options.config)
    config = unit_config.for_platform(PlatformId.KUAISHOU_JUXING)
    registry = PlatformRegistry.model_validate_json(config.registry_path.read_text())
    registry.require_enabled(live=True)

    repository.register_unit(
        unit_config.unit_id,
        unit_config.account_ref,
        unit_config.line_id,
        str(unit_config.profile_directory),
        unit_config.network_mode.value,
        unit_config.expected_account_id,
    )
    repository.register_unit_platform_binding(
        config.unit_id,
        config.active_platform.value,
        config.account_ref,
        config.expected_account_id,
        str(config.profile_directory),
        str(config.registry_path),
    )
    with repository.connect() as conn:
        conn.execute(
            "UPDATE execution_units SET state='READY',session_version=1 WHERE unit_id=%s",
            (config.unit_id,),
        )

    plan = FilterPlan(
        schema_version="filter_plan.v3",
        platform="kuaishou_juxing",
        capability_version=registry.capabilities.version,
        target_count=1,
        filters=[
            Filter(
                field="keyword",
                operator="eq",
                value="母婴",
                source_fields=["keyword"],
            ),
            Filter(
                field="content_type",
                operator="in",
                value=["maternal_child"],
                source_fields=["content_types.0"],
            ),
        ],
    )
    root = repository.create(
        plan,
        config.unit_id,
        "kjx-stage-b-live-" + uuid4().hex,
        "stage-b-authorized-smoke",
        adapter_version=registry.adapter_version,
        contract_version=registry.contract_version,
        modules=[module.key for module in registry.modules],
        module_checkpoint_versions={
            module.key: module.checkpoint_version for module in registry.modules
        },
    )
    task = repository.get(root)
    owner = task.attempt_id

    async with BrowserHost.lease(
        repository,
        config,
        registry,
        options.private_root,
        root,
        owner,
        maintenance=False,
    ) as host:

        async def guard() -> None:
            await host.heartbeat()

        assert host.browser is not None
        adapter = build_platform_adapter(
            config.active_platform,
            host.browser,
            registry,
            config.expected_account_id,
            guard,
            on_session_health=host.observe_session,
            manually_attested_account_id=config.manually_attested_account_id,
        )
        context = ExecutionContext(
            root_task_id=root,
            task_id=task.task_id,
            attempt_id=task.attempt_id,
            execution_unit_id=config.unit_id,
            lease_generation=host.generation,
            session_version=host.session_version,
            capability_version=registry.capabilities.version,
            adapter_version=registry.adapter_version,
            contract_version=registry.contract_version,
        )
        terminal_state = await Engine(repository, adapter, context).run()

    result = repository.get(root)
    with repository.connect() as conn:
        identities = conn.execute(
            "SELECT creator_id,platform_creator_id FROM platform_creators WHERE platform=%s",
            (PlatformId.KUAISHOU_JUXING.value,),
        ).fetchall()
        snapshot_row = conn.execute("SELECT count(*) AS n FROM creator_snapshots").fetchone()
        xingtu_projection_row = conn.execute(
            "SELECT count(*) AS n FROM douyin_xingtu_creator_current"
        ).fetchone()
        assert snapshot_row is not None and xingtu_projection_row is not None
        snapshot_count = snapshot_row["n"]
        xingtu_projection_count = xingtu_projection_row["n"]
    identity_hashes = [
        hashlib.sha256(str(row["platform_creator_id"]).encode()).hexdigest()[:12]
        for row in identities
    ]
    return {
        "state": str(terminal_state),
        "task_state": result.state.value,
        "target_count": result.target_count,
        "valid_count": result.valid_count,
        "profile_complete_count": result.profile_complete_count,
        "creator_count": len(identities),
        "creator_identity_hashes": identity_hashes,
        "snapshot_count": int(snapshot_count),
        "douyin_projection_count": int(xingtu_projection_count),
        "platform": result.platform.value,
        "contract_version": registry.contract_version,
        "session_status": host.session_health.status.value if host.session_health else None,
        "session_reason": host.session_health.evidence_reason if host.session_health else None,
    }


async def run(options: argparse.Namespace) -> int:
    dsn = os.environ.get("XINGTU_TEST_DATABASE_URL")
    if not dsn:
        raise RuntimeError("XINGTU_TEST_DATABASE_URL is required")
    schema = "kjx_stage_b_" + uuid4().hex
    started_at = datetime.now(UTC).isoformat()
    with psycopg.connect(dsn) as conn:
        database_row = conn.execute("SELECT current_database()").fetchone()
        assert database_row is not None
        database = str(database_row[0])
        if not database.startswith("xingtu_test"):
            raise RuntimeError("refusing non-test database")
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    repository = Repository(make_conninfo(dsn, options=f"-csearch_path={schema}"))
    try:
        repository.migrate(ROOT / "migrations")
        result = await collect_one(options, repository)
        write_report(
            options.report,
            {
                "schema_version": "juxing_stage_b_smoke.v1",
                "started_at": started_at,
                "finished_at": datetime.now(UTC).isoformat(),
                "database_class": "isolated_test",
                "schema_dropped_after_verification": True,
                **result,
            },
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - sanitized failure handoff, no platform payload
        write_report(
            options.report,
            {
                "schema_version": "juxing_stage_b_smoke.v1",
                "started_at": started_at,
                "finished_at": datetime.now(UTC).isoformat(),
                "database_class": "isolated_test",
                "schema_dropped_after_verification": True,
                "state": "FAILED",
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        raise
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
