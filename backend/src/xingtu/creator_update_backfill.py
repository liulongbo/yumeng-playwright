"""One-off, idempotent locator backfill for juxing video-square identities.

Juxing persists a creator as its ``userId`` while the verified detail route uses ``starId``.  The
exact locator was only ever captured inside the collection task checkpoint, so rows collected
before UPD-06 have ``platform_creators.video_homepage = NULL`` and cannot be scheduled.  This
module reads the latest video snapshot's root-task checkpoint and fills the locator without
touching any business field or snapshot.
"""

from __future__ import annotations

from typing import Any

RESOLVED_CTE = """
WITH resolved AS (
  SELECT pc.creator_id,
         (SELECT candidate->'ref'->>'verified_homepage'
          FROM creator_snapshots s
          JOIN tasks t ON t.root_task_id = s.root_task_id
          JOIN task_checkpoints c ON c.task_id = t.task_id
          CROSS JOIN LATERAL jsonb_array_elements(c.payload->'candidates') AS candidate
          WHERE s.creator_id = pc.creator_id
            AND s.creator_scene = 'video_square'
            AND candidate->'ref'->>'platform' = pc.platform
            AND candidate->'ref'->>'platform_creator_id' = pc.platform_creator_id
          ORDER BY s.created_at DESC, s.snapshot_id DESC
          LIMIT 1) AS homepage
  FROM platform_creators pc
  WHERE pc.platform = 'kuaishou_juxing'
    AND pc.video_homepage IS NULL
    AND EXISTS (
      SELECT 1 FROM creator_snapshots cs
      WHERE cs.creator_id = pc.creator_id AND cs.creator_scene = 'video_square'
    )
)
"""


def resolve_video_homepages(conn: Any) -> dict[str, int]:
    """Report eligible rows and how many can be resolved from checkpoints (read-only)."""
    row = conn.execute(
        RESOLVED_CTE
        + """SELECT count(*) AS eligible,
        count(*) FILTER (WHERE homepage IS NOT NULL) AS resolvable,
        count(*) FILTER (WHERE homepage IS NULL) AS unresolved
        FROM resolved"""
    ).fetchone()
    return {
        "eligible": int(row["eligible"] or 0),
        "resolvable": int(row["resolvable"] or 0),
        "unresolved": int(row["unresolved"] or 0),
    }


def apply_video_homepages(conn: Any) -> dict[str, int]:
    """Fill missing juxing video locators; never overwrite an existing value."""
    before = resolve_video_homepages(conn)
    result = conn.execute(
        RESOLVED_CTE
        + """UPDATE platform_creators pc SET video_homepage = r.homepage
        FROM resolved r
        WHERE pc.creator_id = r.creator_id
          AND r.homepage IS NOT NULL
          AND pc.video_homepage IS NULL"""
    )
    return {
        "eligible": before["eligible"],
        "resolvable": before["resolvable"],
        "unresolved": before["unresolved"],
        "filled": int(result.rowcount or 0),
    }
