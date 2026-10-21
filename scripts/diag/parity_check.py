"""Run one deterministic synthetic collection with the selected source tree and dump DB artifacts.

Run once with the old baseline (PYTHONPATH=.runtime/perf/old_src) and once with the current
worktree, then compare the normalized JSON.  This is a data-parity check, not a live platform test.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
try:
    import xingtu  # noqa: F401
except ModuleNotFoundError:
    sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402
from psycopg.conninfo import make_conninfo  # noqa: E402
from xingtu.domain import (  # noqa: E402
    ExecutionContext,
    Filter,
    FilterPlan,
    SegmentBudget,
    uid,
)
from xingtu.engine import Engine  # noqa: E402
from xingtu.repository import Repository  # noqa: E402

from backend.tests.synthetic import SyntheticAdapter  # noqa: E402

DB_BASE = "postgresql://postgres:bench@127.0.0.1:55439/xingtu_test_perfbench"


def normalize_field(field: dict) -> dict:
    return {
        "field_key": field.get("field_key"),
        "status": field.get("status"),
        "value": field.get("value"),
        "raw_value": field.get("raw_value"),
        "failure_reason": field.get("failure_reason"),
        "coverage": field.get("coverage"),
    }


def normalize_module(module: dict | None) -> dict | None:
    if module is None:
        return None
    return {
        "module_key": module.get("module_key"),
        "fields": sorted(
            (normalize_field(field) for field in module.get("fields", [])),
            key=lambda item: item["field_key"] or "",
        ),
        "expected_fields": sorted(module.get("expected_fields", [])),
        "coverage_gaps": sorted(module.get("coverage_gaps", [])),
    }


def normalize_collection(collection: dict | None) -> dict | None:
    if collection is None:
        return None
    cards = [
        {
            "position": card.get("position"),
            "platform_content_id": card.get("platform_content_id"),
            "canonical_link": card.get("canonical_link"),
            "local_key": card.get("local_key"),
            "cover_status": card.get("cover_status"),
            "fields": sorted(
                (
                    {
                        "field_key": field.get("field_key"),
                        "status": field.get("status"),
                        "value": field.get("value"),
                    }
                    for field in card.get("fields", [])
                ),
                key=lambda item: item["field_key"] or "",
            ),
        }
        for card in collection.get("cards", [])
    ]
    return {
        "collection_type": collection.get("collection_type"),
        "status": collection.get("status"),
        "coverage_gaps": sorted(collection.get("coverage_gaps", [])),
        "cards": cards,
    }


async def run() -> dict:
    schema = "parity_" + uid().replace("-", "")[:12]
    with psycopg.connect(DB_BASE) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(DB_BASE, options=f"-csearch_path={schema}")
    repo = Repository(dsn)
    repo.migrate(ROOT / "migrations")
    repo.register_unit("unit", "acct", "line", "/tmp/profile", "local_development")
    with repo.connect() as conn:
        conn.execute(
            "UPDATE execution_units SET state='READY',session_version=1,browser_stopped=true"
        )
    plan = FilterPlan(
        capability_version="synthetic-v1",
        target_count=1,
        filters=[Filter(field="keyword", operator="eq", value="bench", source_fields=["keyword"])],
    )
    adapter = SyntheticAdapter(ids=["1"], page_size=1)
    root = repo.create(
        plan,
        "unit",
        uid(),
        "parity",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
        modules=adapter.module_keys,
    )
    task = repo.get(root)
    generation, session = repo.acquire("unit", task.attempt_id)
    ctx = ExecutionContext(
        root_task_id=root,
        task_id=task.task_id,
        attempt_id=task.attempt_id,
        execution_unit_id="unit",
        lease_generation=generation,
        session_version=session,
        capability_version="synthetic-v1",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
        network_mode="local_development",
        budget=SegmentBudget(),
    )
    state = await Engine(repo, adapter, ctx).run()
    task = repo.get(root)
    candidates = []
    for candidate in task.checkpoint.candidates:
        candidates.append(
            {
                "platform_creator_id": candidate.ref.platform_creator_id,
                "state": candidate.state,
                "valid": candidate.valid,
                "failure_reason": candidate.failure_reason,
                "modules": {
                    key: normalize_module(module.model_dump(mode="json"))
                    for key, module in sorted(candidate.modules.items())
                },
                "collections": {
                    key: normalize_collection(collection.model_dump(mode="json"))
                    for key, collection in sorted(candidate.collections.items())
                },
            }
        )
    with repo.connect() as conn:
        creators = [
            {"position": row["first_position"], "valid": row["valid"]}
            for row in conn.execute(
                "SELECT first_position,valid FROM task_creators WHERE root_task_id=%s "
                "ORDER BY first_position",
                (root,),
            ).fetchall()
        ]
        snapshots = []
        for row in conn.execute(
            "SELECT payload FROM creator_snapshots WHERE root_task_id=%s ORDER BY created_at",
            (root,),
        ).fetchall():
            payload = row["payload"]
            snapshots.append(
                {
                    "modules": {
                        key: normalize_module(value)
                        for key, value in sorted(payload.get("modules", {}).items())
                    },
                    "collections": {
                        key: normalize_collection(value)
                        for key, value in sorted(payload.get("collections", {}).items())
                    },
                    "profile_complete": payload.get("profile_complete"),
                    "featured_complete": payload.get("featured_complete"),
                    "pipeline_complete": payload.get("pipeline_complete"),
                    "featured_status": payload.get("featured_status"),
                }
            )
        featured_collections = conn.execute(
            "SELECT count(*) n FROM featured_collections WHERE root_task_id=%s", (root,)
        ).fetchone()["n"]
        featured_cards = conn.execute(
            """SELECT count(*) n FROM featured_cards c JOIN featured_collections f
               USING(collection_observation_id) WHERE f.root_task_id=%s""",
            (root,),
        ).fetchone()["n"]
    with psycopg.connect(DB_BASE) as conn:
        conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
    return {
        "returned_state": state,
        "task": {
            "state": task.state.value,
            "valid_count": task.valid_count,
            "target_count": task.target_count,
            "profile_complete_count": task.profile_complete_count,
            "featured_status": task.featured_status,
            "pipeline_complete": task.pipeline_complete,
            "failure_reason": task.failure_reason,
        },
        "candidates": candidates,
        "task_creators": creators,
        "snapshots": snapshots,
        "featured_collections": featured_collections,
        "featured_cards": featured_cards,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = asyncio.run(run())
    result["label"] = args.label
    result["source_path"] = __import__("xingtu").__file__
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
