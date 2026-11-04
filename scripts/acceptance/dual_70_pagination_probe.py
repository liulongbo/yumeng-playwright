#!/usr/bin/env python3
"""Real Adapter page 1..N pagination probe for the 70-creator acceptance.

Why this exists
---------------
A page-fetch contract is only allowed to advertise a page that has real evidence.  This script
exercises the *production* adapter (not a bespoke fetch) against the real unit profile: page 1
through ``--max-page``, recording page numbers, candidate counts, identity-set digests, cross-page
overlap and the fail-closed boundary.  It never creates a business task and never writes to the
business database.

Two modes
---------
* research (``--in-memory-page-limit N``): raises the page limit in memory only, so page 3/4/5 can
  be verified before the checked-in contract is changed.  The file is never modified.
* contract (default): uses the checked-in registry as-is; used after publication to prove the
  executable boundary and that page N+1 fails closed.

Output is private: ``.runtime/acceptance/...`` (0700/0600), because it contains real platform
creator ids.  Only counts/digests are meant for the public acceptance report.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from xingtu.adapter_factory import build_platform_adapter  # noqa: E402
from xingtu.contracts import PlatformRegistry  # noqa: E402
from xingtu.domain import (  # noqa: E402
    Checkpoint,
    CollectorError,
    ExecutionContext,
    Filter,
    FilterPlan,
    PlatformId,
    Sort,
    uid,
)
from xingtu.platform_runtime import apply_private_permissions  # noqa: E402
from xingtu.runtime import BrowserRuntime, load_unit  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="真实 Adapter 1..N 页分页探针（不写业务库）")
    parser.add_argument("--platform", choices=["douyin_xingtu", "kuaishou_juxing"], required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-page", type=int, default=5)
    parser.add_argument(
        "--in-memory-page-limit",
        type=int,
        default=None,
        help="仅在内存中提高 page_fetch_max_verified（研究模式，不改文件）",
    )
    parser.add_argument("--keyword", default=None)
    parser.add_argument("--content-type", default="maternal_child")
    parser.add_argument("--interval-seconds", type=float, default=3.0)
    parser.add_argument(
        "--boundary-check",
        action="store_true",
        help="在真实契约模式下请求 max-page+1，确认 fail closed",
    )
    return parser.parse_args()


def build_plan(
    platform: PlatformId, registry: PlatformRegistry, args: argparse.Namespace
) -> FilterPlan:
    keyword = args.keyword or ("宠物" if platform == PlatformId.DOUYIN_XINGTU else "母婴")
    filters = [
        Filter(field="keyword", operator="eq", value=keyword, source_fields=["keyword"]),
    ]
    schema_version = "filter_plan.v2"
    if platform == PlatformId.KUAISHOU_JUXING:
        schema_version = "filter_plan.v3"
        filters.append(
            Filter(
                field="content_type",
                operator="in",
                value=[args.content_type],
                source_fields=["content_types.0"],
            )
        )
    plan = FilterPlan(
        schema_version=schema_version,
        platform=platform.value,
        capability_version=registry.capabilities.version,
        target_count=70,
        filters=filters,
        sort=Sort(key=registry.capabilities.sorts[0]),
    )
    registry.capabilities.validate_plan(plan, live=True)
    return plan


def digest(ids: list[str]) -> str:
    return hashlib.sha256("\n".join(ids).encode()).hexdigest()


def record_page(
    page: Any,
    number: int,
    seen: set[str],
    *,
    started: float,
) -> dict[str, Any]:
    ids = [candidate.platform_creator_id for candidate in page.candidates]
    new_ids = [identity for identity in ids if identity not in seen]
    seen.update(ids)
    return {
        "page": number,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "candidates": len(ids),
        "unique_in_page": len(set(ids)),
        "new_identities": len(new_ids),
        "identity_digest": digest(ids),
        "identity_set_digest": digest(sorted(set(ids))),
        "current_checkpoint": page.current_checkpoint,
        "next_checkpoint": page.next_checkpoint,
        "exhausted": page.exhausted,
        "unidentified": len(page.unidentified),
        # Private evidence only; the public report uses counts/digests.
        "platform_creator_ids": ids,
    }


async def run(args: argparse.Namespace) -> int:
    config = load_unit(args.config)
    registry = PlatformRegistry.model_validate_json(Path(config.registry_path).read_text())
    if args.in_memory_page_limit is not None:
        if not 2 <= args.in_memory_page_limit <= 200:
            raise SystemExit("--in-memory-page-limit must be 2..200")
        assert registry.search is not None
        registry = registry.model_copy(
            update={
                "search": registry.search.model_copy(
                    update={"page_fetch_max_verified": args.in_memory_page_limit}
                )
            }
        )
    registry.require_enabled(live=True)
    platform = PlatformId(args.platform)
    plan = build_plan(platform, registry, args)
    checkpoint = Checkpoint(
        conditions_digest=plan.digest(),
        contract_version=registry.contract_version,
        adapter_version=registry.adapter_version,
    )
    context = ExecutionContext(
        root_task_id=uid(),
        task_id=uid(),
        attempt_id=uid(),
        execution_unit_id=config.unit_id,
        lease_generation=1,
        session_version=1,
        capability_version=registry.capabilities.version,
        adapter_version=registry.adapter_version,
        contract_version=registry.contract_version,
    )

    health: list[dict[str, Any]] = []
    seen: set[str] = set()
    pages: list[dict[str, Any]] = []
    boundary: dict[str, Any] | None = None
    error: str | None = None
    started = time.monotonic()

    async def guard() -> None:
        return None

    def on_session_health(value: Any) -> None:
        health.append(value.model_dump(mode="json"))

    runtime = BrowserRuntime(config, ROOT / ".runtime")
    adapter = None
    try:
        async with runtime.open() as browser:
            adapter = build_platform_adapter(
                platform,
                browser,
                registry,
                config.expected_account_id,
                guard,
                on_session_health=on_session_health,
                manually_attested_account_id=config.manually_attested_account_id,
            )
            prepared = await adapter.prepare(plan, checkpoint, context)
            if not prepared:
                raise RuntimeError("adapter.prepare returned False with an empty cursor")
            page = await adapter.search(plan, checkpoint, context)
            pages.append(record_page(page, 1, seen, started=started))

            for number in range(2, args.max_page + 1):
                if page.next_checkpoint is None:
                    pages.append({"page": number, "skipped": "exhausted_before_page"})
                    break
                if args.interval_seconds:
                    await asyncio.sleep(args.interval_seconds)
                checkpoint.cursor = page.next_checkpoint
                page = await adapter.search(plan, checkpoint, context)
                pages.append(record_page(page, number, seen, started=started))

            if args.boundary_check and page.next_checkpoint is not None:
                checkpoint.cursor = page.next_checkpoint
                try:
                    await adapter.search(plan, checkpoint, context)
                except CollectorError as exc:
                    boundary = {
                        "attempted_page": int(page.next_checkpoint),
                        "code": exc.code,
                        "reason": exc.reason,
                    }
                else:
                    boundary = {
                        "attempted_page": int(page.next_checkpoint),
                        "code": None,
                        "reason": "NO_FAIL_CLOSED",
                    }
    except Exception as exc:  # noqa: BLE001 - evidence must be written even on failure
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if adapter is not None:
            try:
                await adapter.close()
            except Exception:  # noqa: BLE001
                pass

    result = {
        "schema_version": "dual-70-pagination-probe.v1",
        "platform": args.platform,
        "unit_id": config.unit_id,
        "contract_version": registry.contract_version,
        "adapter_version": registry.adapter_version,
        "page_fetch_max_verified": (
            registry.search.page_fetch_max_verified if registry.search is not None else None
        ),
        "in_memory_page_limit": args.in_memory_page_limit,
        "plan": plan.model_dump(mode="json"),
        "session_health": health,
        "pages": pages,
        "cross_page": {
            "identities_seen": len(seen),
            "duplicate_across_pages": sum(
                int(item.get("candidates", 0)) - int(item.get("new_identities", 0))
                for item in pages
                if "candidates" in item
            ),
        },
        "boundary": boundary,
        "error": error,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    apply_private_permissions(args.out.parent, 0o700)
    temporary = args.out.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    apply_private_permissions(temporary, 0o600)
    temporary.replace(args.out)
    summary = {
        key: result[key]
        for key in (
            "platform",
            "unit_id",
            "contract_version",
            "page_fetch_max_verified",
            "in_memory_page_limit",
            "cross_page",
            "boundary",
            "error",
        )
    }
    summary["pages"] = [
        {key: value for key, value in item.items() if key != "platform_creator_ids"}
        for item in pages
    ]
    summary["session_status"] = [
        {
            "status": item.get("status"),
            "expected_account_id": item.get("expected_account_id"),
            "observed_account_id": item.get("observed_account_id"),
            "protected_page_verified": item.get("protected_page_verified"),
            "evidence_reason": item.get("evidence_reason"),
        }
        for item in health
    ]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return (
        0
        if error is None and boundary is None or boundary is not None and boundary.get("code")
        else 1
    )


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
