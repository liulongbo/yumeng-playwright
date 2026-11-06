#!/usr/bin/env python3
"""Prepare an isolated, already-cloned database for the UPD-06 real browser acceptance.

It never starts services and never touches the development database.  The caller must first create
a ``xingtu_test*`` clone of the development database (so real creators/snapshots are present), then
run this script with that clone's DSN.  It applies migration 022, backfills the juxing video
locators, enrolls all four update plans, parks every plan 30 days in the future and makes only one
selected creator per (platform, scene) due.

The scheduler is not running while this script prepares state, so no unrelated automatic task can
be created.  The output is a JSON summary used by the acceptance evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "backend" / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend" / "src"))

from xingtu.creator_update import CreatorUpdateService  # noqa: E402
from xingtu.creator_update_backfill import apply_video_homepages  # noqa: E402
from xingtu.domain import ProfileRequirement  # noqa: E402
from xingtu.product_cli import update_scopes  # noqa: E402
from xingtu.repository import Repository  # noqa: E402
from xingtu.runtime import load_unit  # noqa: E402


def _select_creators(conn) -> dict[str, dict[str, str]]:
    selections: dict[str, dict[str, str]] = {}
    xingtu_video = conn.execute(
        """SELECT c.creator_id,c.platform_creator_id
        FROM douyin_xingtu_creator_current c
        WHERE c.pipeline_complete=true
          AND c.followers_count BETWEEN 100000 AND 400000
        ORDER BY c.data_updated_at DESC NULLS LAST LIMIT 1"""
    ).fetchone()
    xingtu_live = conn.execute(
        """SELECT l.creator_id,l.platform_creator_id
        FROM creator_live_current l
        WHERE l.platform='douyin_xingtu' AND l.pipeline_complete=true
        ORDER BY l.data_updated_at DESC NULLS LAST LIMIT 1"""
    ).fetchone()
    juxing_video = conn.execute(
        """SELECT pc.creator_id,pc.platform_creator_id
        FROM platform_creators pc
        WHERE pc.platform='kuaishou_juxing' AND pc.video_homepage IS NOT NULL
        ORDER BY (
          SELECT max(cs.created_at) FROM creator_snapshots cs
          WHERE cs.creator_id=pc.creator_id AND cs.creator_scene='video_square'
        ) DESC NULLS LAST LIMIT 1"""
    ).fetchone()
    juxing_live = conn.execute(
        """SELECT l.creator_id,l.platform_creator_id
        FROM creator_live_current l
        WHERE l.platform='kuaishou_juxing' AND l.platform_star_id IS NOT NULL
        ORDER BY l.data_updated_at DESC NULLS LAST LIMIT 1"""
    ).fetchone()
    for key, row in (
        ("douyin_xingtu:video_square", xingtu_video),
        ("douyin_xingtu:live_square", xingtu_live),
        ("kuaishou_juxing:video_square", juxing_video),
        ("kuaishou_juxing:live_square", juxing_live),
    ):
        if row is None:
            raise SystemExit(f"no eligible real creator for {key}")
        selections[key] = {
            "creator_id": str(row["creator_id"]),
            "platform_creator_id": str(row["platform_creator_id"]),
        }
    return selections


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare the UPD-06 isolated acceptance database")
    parser.add_argument("--dsn", required=True, help="isolated xingtu_test* database DSN")
    parser.add_argument(
        "--unit-config",
        type=Path,
        default=ROOT / ".runtime" / "units" / "local-dev-mac-02.json",
    )
    args = parser.parse_args()
    database = urlsplit(args.dsn).path.lstrip("/")
    if not database.startswith("xingtu_test"):
        raise SystemExit("refusing a non-xingtu_test database")
    repository = Repository(args.dsn)
    repository.migrate(ROOT / "migrations")
    with repository.connect() as conn:
        backfill = apply_video_homepages(conn)
        active = conn.execute(
            """SELECT count(*) AS n FROM root_tasks
            WHERE task_kind='scheduled_update'
              AND state NOT IN ('COMPLETED','PARTIAL_COMPLETED','CANCELLED','FAILED',
                                'FAILED_VALIDATION')"""
        ).fetchone()["n"]
        if active:
            raise SystemExit(f"refusing to prepare: {active} active scheduled_update task(s)")
    config = load_unit(args.unit_config)
    requirement = ProfileRequirement.model_validate_json(
        (ROOT / "contracts" / "profile_requirements.json").read_text()
    )
    scopes, errors = update_scopes(config, requirement)
    service = CreatorUpdateService(
        repository, scopes=scopes, scope_errors=errors, batch_size=1, tick_seconds=5
    )
    enrolled = {key: service.enroll_group(key) for key in scopes}
    with repository.connect() as conn:
        selections = _select_creators(conn)
        conn.execute(
            """UPDATE creator_update_schedule
            SET next_due_at=now()+interval '30 days',
                in_flight_root_task_id=NULL,in_flight_claimed_at=NULL,in_flight_expires_at=NULL"""
        )
        conn.execute("UPDATE creator_update_service SET enabled=false")
        for key, selection in selections.items():
            platform, _, scene = key.partition(":")
            conn.execute(
                """UPDATE creator_update_schedule SET next_due_at=now()-interval '1 minute'
                WHERE creator_id=%s AND creator_scene=%s""",
                (selection["creator_id"], scene),
            )
        conn.execute(
            """UPDATE creator_update_service SET enabled=true
            WHERE platform='douyin_xingtu' AND creator_scene='video_square'"""
        )
        counts = conn.execute(
            """SELECT pc.platform,s.creator_scene,count(*) AS n
            FROM creator_update_schedule s JOIN platform_creators pc USING(creator_id)
            GROUP BY 1,2 ORDER BY 1,2"""
        ).fetchall()
        due = conn.execute(
            """SELECT count(*) AS n FROM creator_update_schedule
            WHERE next_due_at <= now() AND in_flight_root_task_id IS NULL"""
        ).fetchone()["n"]
    print(
        json.dumps(
            {
                "database": database,
                "backfill": backfill,
                "enrolled": enrolled,
                "scope_errors": errors,
                "selected": selections,
                "plans": [
                    {"platform": row["platform"], "scene": row["creator_scene"], "count": row["n"]}
                    for row in counts
                ],
                "due_after_setup": due,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
