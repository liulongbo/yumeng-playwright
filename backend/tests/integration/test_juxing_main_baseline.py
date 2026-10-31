"""Read-only business-content baseline for JUXING-MAIN-01.

The baseline must cover star-chart tasks, creators, JSONB projections, immutable snapshots and the
unit/binding identity, and it must not include juxing rows. ``compare`` must detect a content
change on a historical star-chart row and stay clean when nothing changed.
"""

from __future__ import annotations

import sys
from pathlib import Path

from xingtu.domain import Filter, FilterPlan, uid

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scripts import juxing_main_switch as switch  # noqa: E402


def _juxing_plan() -> FilterPlan:
    return FilterPlan(
        schema_version="filter_plan.v3",
        platform="kuaishou_juxing",
        capability_version="juxing-video-square-stage-c-v2",
        target_count=1,
        filters=[
            Filter(field="keyword", operator="eq", value="母婴", source_fields=["keyword"]),
        ],
    )


def test_baseline_is_scoped_to_star_chart_content_and_detects_a_change(repo, plan):
    xingtu_root = repo.create(
        plan,
        "unit",
        uid(),
        "test",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
        modules=["basic"],
    )
    repo.create(
        _juxing_plan(),
        "unit",
        uid(),
        "test",
        adapter_version="juxing-browser-v3",
        contract_version="juxing-video-creator-stage-c-v3",
        modules=["basic"],
    )

    baseline = switch.compute_baseline(repo.dsn, "unit")
    assert baseline["counts"]["root_tasks"] == 2
    assert baseline["hashes"]["root_tasks"]["count"] == 1
    assert baseline["xingtu_root_task_ids"] == [xingtu_root]
    assert any(
        key.startswith("kuaishou_juxing/") for key in baseline["root_tasks_by_platform_state"]
    )
    assert switch.compare_baseline(repo.dsn, baseline) == []

    with repo.connect() as conn:
        conn.execute(
            "UPDATE root_tasks SET state='FAILED' WHERE root_task_id=%s",
            (xingtu_root,),
        )
    differences = switch.compare_baseline(repo.dsn, baseline)
    assert [item["scope"] for item in differences] == ["root_tasks"]
