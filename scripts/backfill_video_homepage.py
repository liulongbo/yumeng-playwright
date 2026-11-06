#!/usr/bin/env python3
"""Backfill juxing video detail locators from historical collection checkpoints.

Dry-run by default.  ``--apply`` writes only ``platform_creators.video_homepage`` for juxing
video-square identities that have a snapshot but no locator; existing values and all business
fields stay untouched.  Run it once after migration 022 on an existing database.

    .venv/bin/python scripts/backfill_video_homepage.py
    .venv/bin/python scripts/backfill_video_homepage.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend" / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend" / "src"))

from xingtu.creator_update_backfill import (  # noqa: E402
    apply_video_homepages,
    resolve_video_homepages,
)
from xingtu.repository import Repository  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill juxing video homepage locators")
    parser.add_argument(
        "--dsn",
        default=os.environ.get("XINGTU_DATABASE_URL"),
        help="PostgreSQL DSN (default: XINGTU_DATABASE_URL)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the resolved locators; without this flag the command is read-only",
    )
    args = parser.parse_args()
    if not args.dsn:
        parser.error("XINGTU_DATABASE_URL or --dsn is required")
    repository = Repository(args.dsn)
    with repository.connect() as conn:
        result = apply_video_homepages(conn) if args.apply else resolve_video_homepages(conn)
    print(json.dumps({**result, "applied": bool(args.apply)}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
