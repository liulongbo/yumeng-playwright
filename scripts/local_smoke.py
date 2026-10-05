"""Local-stage verification harness for F04/F05 against the real platform.

This is a **development / verification harness**, not production orchestration:

- it runs the real `Activities.collect` (live registry gate, lease, adapter, engine, evidence) and
  the real `CollectionWorkflow`;
- Temporal is provided by the official Python SDK local test server because this machine has no
  Docker daemon, so `make dev` (Compose Temporal service) is unavailable;
- it is one-shot: it waits for a terminal task state and exits, so a shell command can assert on it.

Production resource scheduling, cross-node dispatch and deployment stay with OPS-01.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import UUID

from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from xingtu.domain import CollectorError
from xingtu.repository import Repository
from xingtu.runtime import UnitConfig, load_unit
from xingtu.worker import Activities
from xingtu.workflow import CollectionWorkflow

ROOT = Path(__file__).resolve().parents[1]
TERMINAL = {
    "CANCELLED",
    "COMPLETED",
    "PARTIAL_COMPLETED",
    "FAILED",
    "FAILED_VALIDATION",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="execution unit JSON")
    parser.add_argument("--root-task-id", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    dsn = os.environ.get("XINGTU_DATABASE_URL")
    if not dsn:
        print("XINGTU_DATABASE_URL required", file=sys.stderr)
        return 2
    try:
        UUID(args.root_task_id)
    except ValueError:
        print(
            json.dumps({"error": "ROOT_TASK_ID_MUST_BE_UUID", "value": args.root_task_id}),
            file=sys.stderr,
        )
        return 2
    config: UnitConfig = load_unit(args.config)
    repo = Repository(dsn)
    task = repo.get(args.root_task_id)
    if task.execution_unit_id != config.unit_id:
        print(
            json.dumps(
                {
                    "error": "root task belongs to another unit",
                    "task_unit": task.execution_unit_id,
                    "config_unit": config.unit_id,
                }
            ),
            file=sys.stderr,
        )
        return 2
    queue = f"xingtu-{config.unit_id}"
    activities = Activities(repo, config, ROOT / ".runtime/profiles")
    executable = os.environ.get("XINGTU_TEMPORAL_TEST_BINARY")
    async with await WorkflowEnvironment.start_local(
        dev_server_existing_path=executable,
        dev_server_download_version="v1.9.1",
        download_dest_dir=str(ROOT / ".runtime/temporal-test"),
        dev_server_log_level="error",
    ) as env:
        client: Client = env.client
        async with Worker(
            client,
            task_queue=queue,
            workflows=[CollectionWorkflow],
            activities=[activities.collect],
            max_concurrent_activities=1,
        ):
            handle = await client.start_workflow(
                CollectionWorkflow.run,
                args.root_task_id,
                id=f"collect/{args.root_task_id}",
                task_queue=queue,
            )
            state: str | None = None
            try:
                async with asyncio.timeout(args.timeout_seconds):
                    state = await handle.result()
            except TimeoutError:
                description = await handle.describe()
                if description.status == WorkflowExecutionStatus.RUNNING:
                    await handle.cancel()
                state = None
        final = repo.get(args.root_task_id)
        summary = {
            "root_task_id": args.root_task_id,
            "workflow_state": state,
            "task_state": final.state.value,
            "failure_reason": final.failure_reason,
            "valid_count": final.valid_count,
            "profile_complete_count": final.profile_complete_count,
            "discovered_count": len(final.checkpoint.candidates),
            "scanned_count_segment": len(final.checkpoint.scanned_ids),
            "search_exhausted": final.checkpoint.exhausted,
            "search_generation": final.checkpoint.search_generation,
            "rescan_reasons": final.checkpoint.rescan_reasons,
            "diagnostics": [d.model_dump(mode="json") for d in final.checkpoint.diagnostics],
            "draft_results": [
                {
                    "platform_creator_id": c.ref.platform_creator_id,
                    "state": c.state,
                    "valid": c.valid,
                    "failure_reason": c.failure_reason,
                    "modules": {
                        key: {
                            "status": module.status.value,
                            "complete": module.complete,
                            "coverage_gaps": module.coverage_gaps,
                            "fields": {
                                f.field_key: {
                                    "status": f.status.value,
                                    "value": f.value.model_dump(mode="json")
                                    if hasattr(f.value, "model_dump")
                                    else f.value,
                                    "raw_value": f.raw_value,
                                    "unit": f.unit,
                                    "period_label": f.period_label,
                                    "failure_reason": f.failure_reason,
                                }
                                for f in module.fields
                            },
                        }
                        for key, module in c.modules.items()
                    },
                }
                for c in final.checkpoint.candidates
            ],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        return 0 if final.state.value in TERMINAL else 1


def main() -> None:
    args = parse_args()
    try:
        raise SystemExit(asyncio.run(run(args)))
    except CollectorError as exc:
        print(json.dumps({"error_code": exc.code, "reason": exc.reason}), file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
