"""Bounded F05/F06 live contract smoke; prints statuses and counts, never field values."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from xingtu.adapter import BrowserAdapter
from xingtu.contracts import PlatformRegistry
from xingtu.domain import Checkpoint, CreatorRef, ExecutionContext
from xingtu.runtime import BrowserRuntime, load_unit


async def run(
    config_path: Path, creator_id: str, homepage: str, *, featured_only: bool = False
) -> None:
    config = load_unit(config_path)
    registry = PlatformRegistry.model_validate_json(config.registry_path.read_text())
    registry.require_enabled(live=True)
    runtime = BrowserRuntime(config, Path(".runtime"))

    async def guard() -> None:
        return None

    ctx = ExecutionContext(
        root_task_id="f06-live-contract-smoke",
        task_id="f06-live-contract-smoke",
        attempt_id="f06-live-contract-smoke",
        execution_unit_id=config.unit_id,
        lease_generation=1,
        session_version=1,
        capability_version=registry.capabilities.version,
        adapter_version=registry.adapter_version,
        contract_version=registry.contract_version,
        network_mode=config.network_mode,
    )
    creator = CreatorRef(platform_creator_id=creator_id, verified_homepage=homepage)
    async with runtime.open() as browser:
        adapter = BrowserAdapter(
            browser,
            registry,
            config.expected_account_id,
            guard,
            live=True,
        )
        modules = []
        collections = []
        async with adapter.profile(creator, ctx):
            if not featured_only:
                for key in adapter.module_keys:
                    observation = await adapter.collect_module(key, creator, ctx)
                    modules.append(
                        {
                            "key": key,
                            "status": observation.status.value,
                            "complete": observation.complete,
                            "field_status_counts": {
                                status: sum(
                                    1 for field in observation.fields if field.status == status
                                )
                                for status in sorted({field.status for field in observation.fields})
                            },
                            "coverage_gap_count": len(observation.coverage_gaps),
                            "coverage_gaps": observation.coverage_gaps,
                        }
                    )
            observations = await adapter.collect_featured_collections(
                creator,
                Checkpoint(
                    conditions_digest="f06-live-contract-smoke",
                    contract_version=registry.contract_version,
                    adapter_version=registry.adapter_version,
                ),
                ctx,
            )
            for observation in observations:
                collections.append(
                    {
                        "key": observation.collection_type.value,
                        "status": observation.status.value,
                        "load_complete": observation.load_complete,
                        "card_count": len(observation.cards),
                        "complete_card_count": sum(card.complete for card in observation.cards),
                        "cover_url_count": sum(
                            bool(card.cover and card.cover.source_url) for card in observation.cards
                        ),
                        "coverage_gap_count": len(observation.coverage_gaps),
                        "coverage_gaps": observation.coverage_gaps,
                        "failure_reason": observation.failure_reason,
                    }
                )
        await adapter.close()
    print(
        json.dumps(
            {
                "contract_version": registry.contract_version,
                "browser_version": runtime.browser_version,
                "network_mode": config.network_mode.value,
                "modules": modules,
                "collections": collections,
                "browser_stopped": runtime.stopped,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--creator-id", required=True)
    parser.add_argument("--homepage", required=True)
    parser.add_argument("--featured-only", action="store_true")
    args = parser.parse_args()
    asyncio.run(
        run(
            args.config,
            args.creator_id,
            args.homepage,
            featured_only=args.featured_only,
        )
    )


if __name__ == "__main__":
    main()
