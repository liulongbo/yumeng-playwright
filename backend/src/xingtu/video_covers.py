"""One-off cover backfill for the 「创作能力 → 最新视频表现」 work list (DATA-02 / CD-08).

Why this exists
---------------
A creation work record carries `item_cover`, an **opaque** platform object-store key (measured
2026-10-16: 0 of 1845 non-empty covers in the development database is a renderable URL).  The
platform's own works list exchanges that key for a short-lived signed URL through
``/gw/api/fe_common_service/tools/get_sign_image``.  New collections now do that exchange live and
store the image (``Engine.store_row_cover``); this module backfills the creators that were collected
*before* that capability existed, using only keys already stored in
``douyin_xingtu_creator_video_observations.cover_source_uri``.

What it does **not** do
-----------------------
It does not re-collect creator data, does not touch ``creator_snapshots`` and does not write any
metric.  It signs an existing opaque key, downloads the image through the unit's own authenticated
browser session (reusing ``Adapter.fetch_cover`` and the registered host/content-type scope), stores
it in the cover store and registers the object against the platform key.  A key the platform refuses
to sign, or an image outside the registered scope, is reported as a failure and left unresolved —
never replaced with another work's image.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlunsplit

from .adapter import JOIN_LOOKUP_FETCH_JS, BrowserAdapter
from .contracts import CoverSpec, ItemCoverSpec, PlatformRegistry
from .covers import CoverPipeline, CoverStore, build_cover_store
from .domain import CollectorError
from .repository import Repository
from .runtime import BrowserRuntime, UnitConfig

MODULE_KEY = "creation"


@dataclass
class CoverBackfillReport:
    """Counts and the (bounded) failure reasons of one backfill run; no tokens, no image bytes."""

    candidates: int = 0
    stored: int = 0
    already_stored: int = 0
    unsigned: int = 0
    failed: int = 0
    creator_scoped: str | None = None
    failures: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidates": self.candidates,
            "stored": self.stored,
            "already_stored": self.already_stored,
            "unsigned": self.unsigned,
            "failed": self.failed,
            "creator_scoped": self.creator_scoped,
            "failures": self.failures[:20],
        }


def pending_cover_keys(
    repository: Repository, *, creator_id: str | None = None
) -> list[dict[str, Any]]:
    """Distinct platform cover keys that no stored object is registered against yet.

    Ordered by key so a re-run is deterministic.  One owning root task is chosen per key (the
    newest snapshot that references it) because the object id is namespaced by root task.
    """
    clause = "" if creator_id is None else " AND v.creator_id=%(creator_id)s"
    with repository.connect() as conn:
        rows = conn.execute(
            f"""SELECT DISTINCT ON (v.cover_source_uri)
            v.cover_source_uri AS source_key, s.root_task_id, s.snapshot_id
            FROM douyin_xingtu_creator_video_observations v
            JOIN creator_snapshots s ON s.snapshot_id = v.snapshot_id
            WHERE v.cover_source_uri IS NOT NULL{clause}
              AND NOT EXISTS (
                SELECT 1 FROM media_objects m
                WHERE m.kind='cover' AND m.source_key = v.cover_source_uri)
            ORDER BY v.cover_source_uri, s.created_at DESC, v.snapshot_id""",
            {"creator_id": creator_id},
        ).fetchall()
    return [dict(row) for row in rows]


def already_stored_count(
    repository: Repository, cover_spec: CoverSpec, *, creator_id: str | None = None
) -> int:
    """Keys that already have a registered cover object, for honest run accounting."""
    clause = "" if creator_id is None else " AND v.creator_id=%(creator_id)s"
    with repository.connect() as conn:
        row = conn.execute(
            f"""SELECT count(DISTINCT v.cover_source_uri) AS n
            FROM douyin_xingtu_creator_video_observations v
            WHERE v.cover_source_uri IS NOT NULL{clause}
              AND EXISTS (
                SELECT 1 FROM media_objects m
                WHERE m.kind='cover' AND m.source_key = v.cover_source_uri)""",
            {"creator_id": creator_id},
        ).fetchone()
    return int(row["n"]) if row else 0


def _sign_url(join: ItemCoverSpec, host: str, path: str, source_key: str) -> str:
    params = dict(join.query_defaults)
    params[join.request_path] = source_key
    return urlunsplit(("https", host, path, urlencode(params, doseq=True), ""))


async def _sign_one(page: Any, spec: Any, join: ItemCoverSpec, source_key: str) -> str | None:
    """Exchange one opaque key for a signed URL using the registered request shape.

    Returns the signed address only when the registered success contract is satisfied and the
    response echoes the same key back; anything else is `None` (then reported as unsigned).
    """
    request_spec = next((item for item in spec.requests if item.key == join.request_key), None)
    if request_spec is None:
        return None
    url = _sign_url(join, request_spec.host, request_spec.path, source_key)
    try:
        response = await page.evaluate(JOIN_LOOKUP_FETCH_JS, {"url": url, "headers": {}})
    except Exception:  # noqa: BLE001 - a browser-side failure is one unsigned key, not a crash
        return None
    if int(response.get("status", 0)) != 200:
        return None
    if "json" not in str(response.get("contentType", "")).lower():
        return None
    try:
        body = json.loads(str(response.get("text", "")))
    except ValueError:
        return None
    from .observer import lookup, text_value

    if request_spec.success_path and (
        text_value(lookup(body, request_spec.success_path)) != request_spec.success_value
    ):
        return None
    joined = text_value(lookup(body, join.response_uri_path))
    if joined != source_key:
        return None
    signed = text_value(lookup(body, join.url_path))
    return signed or None


async def backfill_video_covers(
    config: UnitConfig,
    private_root: Path,
    repository: Repository,
    *,
    creator_id: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    store: CoverStore | None = None,
    progress: Callable[[str], None] = lambda _message: None,
) -> CoverBackfillReport:
    """Sign, download and store the covers of works collected before CD-08."""
    registry = PlatformRegistry.model_validate_json(config.registry_path.read_text())
    registry.require_enabled(live=True)
    module = next((item for item in registry.modules if item.key == MODULE_KEY), None)
    cover_spec = module.cover if module else None
    if module is None or cover_spec is None:
        raise CollectorError("PLATFORM_PAGE_CHANGED", "MISSING_MODULE_COVER_CONTRACT")
    joins = [field.item_cover for field in module.fields if field.item_cover]
    if not joins:
        raise CollectorError("PLATFORM_PAGE_CHANGED", "MISSING_ITEM_COVER_CONTRACT")
    join = joins[0]

    report = CoverBackfillReport(creator_scoped=creator_id)
    report.already_stored = already_stored_count(repository, cover_spec, creator_id=creator_id)
    pending = pending_cover_keys(repository, creator_id=creator_id)
    report.candidates = len(pending)
    if limit is not None:
        pending = pending[:limit]
    if dry_run or not pending:
        return report

    if registry.search is None:
        raise CollectorError("PLATFORM_PAGE_CHANGED", "MISSING_SEARCH_CONTRACT")
    interval = registry.action_interval_seconds or 0.0
    runtime = BrowserRuntime(config, private_root)
    pipeline = CoverPipeline(
        repository, store or build_cover_store(config.covers, repository, private_root)
    )
    async with runtime.open() as browser:
        page = browser.pages[0] if browser.pages else await browser.new_page()
        await page.goto(registry.search.entry_url, wait_until="domcontentloaded")
        adapter = BrowserAdapter(
            browser,
            registry,
            config.expected_account_id,
            lambda: _noop_guard(),
            live=True,
            manually_attested_account_id=config.manually_attested_account_id,
        )
        adapter.detail_page = page
        health = await adapter.inspect_session(page)
        if health.status.value != "VALID":
            raise CollectorError("ACCOUNT_LOGIN_REQUIRED", f"SESSION_{health.status.value}")
        for index, item in enumerate(pending):
            source_key = str(item["source_key"])
            signed = await _sign_one(page, module, join, source_key)
            if signed is None:
                report.unsigned += 1
                if len(report.failures) < 20:
                    report.failures.append({"key": source_key, "reason": "SIGN_UNSIGNED"})
                continue
            ref = await pipeline.store(
                root_task_id=str(item["root_task_id"]),
                source_url=signed,
                spec=cover_spec,
                fetch=adapter.fetch_cover,
                source_key=source_key,
            )
            if ref.status.value == "STORED":
                report.stored += 1
            else:
                report.failed += 1
                if len(report.failures) < 20:
                    report.failures.append(
                        {"key": source_key, "reason": ref.failure_reason or ref.status.value}
                    )
            if index + 1 < len(pending):
                await asyncio.sleep(interval)
            if (index + 1) % 50 == 0:
                progress(
                    f"covers {index + 1}/{len(pending)} stored={report.stored} "
                    f"unsigned={report.unsigned} failed={report.failed}"
                )
    return report


async def _noop_guard() -> None:
    return None
