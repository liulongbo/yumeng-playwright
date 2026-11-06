"""UPD-06 juxing video locator backfill: checkpoint resolution, idempotency and non-overwrite."""

from __future__ import annotations

from psycopg.types.json import Jsonb
from xingtu.creator_update_backfill import apply_video_homepages, resolve_video_homepages
from xingtu.domain import uid


def _creator(conn, platform_creator_id: str, homepage: str | None = None) -> str:
    row = conn.execute(
        """INSERT INTO platform_creators(
        creator_id,platform,platform_creator_id,video_homepage)
        VALUES(%s,'kuaishou_juxing',%s,%s) RETURNING creator_id""",
        (uid(), platform_creator_id, homepage),
    ).fetchone()
    return str(row["creator_id"])


def _root(conn) -> str:
    root = uid()
    conn.execute(
        """INSERT INTO root_tasks(
        root_task_id,state,version,unit_id,payload,platform,creator_scene)
        VALUES(%s,'COMPLETED',0,NULL,'{}'::jsonb,'kuaishou_juxing','video_square')""",
        (root,),
    )
    return root


def _video_snapshot(conn, creator_id: str, root: str) -> str:
    snapshot_id = uid()
    conn.execute(
        """INSERT INTO creator_snapshots(
        snapshot_id,root_task_id,creator_id,draft_revision,payload,creator_scene)
        VALUES(%s,%s,%s,0,%s,'video_square')""",
        (snapshot_id, root, creator_id, Jsonb({"pipeline_complete": True, "modules": {}})),
    )
    return snapshot_id


def _checkpoint_with_homepage(conn, root: str, platform_creator_id: str, homepage: str) -> None:
    task_id = uid()
    conn.execute(
        "INSERT INTO tasks(task_id,root_task_id,parent_task_id,kind) VALUES(%s,%s,NULL,'P2-1')",
        (task_id, root),
    )
    conn.execute(
        "INSERT INTO task_checkpoints(task_id,revision,payload) VALUES(%s,0,%s)",
        (
            task_id,
            Jsonb(
                {
                    "candidates": [
                        {
                            "ref": {
                                "platform": "kuaishou_juxing",
                                "platform_creator_id": platform_creator_id,
                                "verified_homepage": homepage,
                                "first_position": 0,
                            }
                        }
                    ]
                }
            ),
        ),
    )


def test_backfill_resolves_checkpoint_homepage_once_and_never_overwrites(repo) -> None:
    homepage = "https://k.kuaishou.com/#/promotion/star/4242?openBy=user"
    with repo.connect() as conn:
        resolvable = _creator(conn, "backfill-1")
        root = _root(conn)
        _video_snapshot(conn, resolvable, root)
        _checkpoint_with_homepage(conn, root, "backfill-1", homepage)

        existing = _creator(
            conn, "backfill-2", "https://k.kuaishou.com/#/promotion/star/1?openBy=user"
        )
        existing_root = _root(conn)
        _video_snapshot(conn, existing, existing_root)
        _checkpoint_with_homepage(conn, existing_root, "backfill-2", homepage)

        unresolved = _creator(conn, "backfill-3")
        unresolved_root = _root(conn)
        _video_snapshot(conn, unresolved, unresolved_root)

    with repo.connect() as conn:
        report = resolve_video_homepages(conn)
    assert report == {"eligible": 2, "resolvable": 1, "unresolved": 1}

    with repo.connect() as conn:
        applied = apply_video_homepages(conn)
    assert applied == {"eligible": 2, "resolvable": 1, "unresolved": 1, "filled": 1}

    with repo.connect() as conn:
        values = {
            row["platform_creator_id"]: row["video_homepage"]
            for row in conn.execute(
                """SELECT platform_creator_id,video_homepage FROM platform_creators
                WHERE platform='kuaishou_juxing'"""
            ).fetchall()
        }
    assert values["backfill-1"] == homepage
    assert values["backfill-2"] == "https://k.kuaishou.com/#/promotion/star/1?openBy=user"
    assert values["backfill-3"] is None

    # Idempotent: the filled row is no longer eligible; the unresolved one can be retried.
    with repo.connect() as conn:
        assert resolve_video_homepages(conn)["eligible"] == 1
        assert apply_video_homepages(conn)["filled"] == 0
