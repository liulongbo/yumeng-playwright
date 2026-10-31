"""Task-center platform filter: additive read model, existing rows untouched.

This covers the only product-code change of JUXING-MAIN-01: ``/api/tasks`` may be narrowed by
platform without changing task persistence, platform identity or the star-chart task semantics.
The cursor scope includes the platform so a filtered cursor can never be replayed against another
filter, while cursors issued before the filter existed stay valid.
"""

from __future__ import annotations

import pytest
from xingtu.domain import CollectorError, Filter, FilterPlan, PlatformId, uid
from xingtu.product_queries import ProductQueries


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


def test_task_center_platform_filter_returns_only_the_requested_platform(repo, plan):
    queries = ProductQueries(repo)
    xingtu_root = repo.create(
        plan,
        "unit",
        uid(),
        "test",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
        modules=["basic"],
    )
    juxing_root = repo.create(
        _juxing_plan(),
        "unit",
        uid(),
        "test",
        adapter_version="juxing-browser-v3",
        contract_version="juxing-video-creator-stage-c-v3",
        modules=["basic"],
    )

    every_platform = queries.list_tasks(limit=10)
    assert {item.root_task_id for item in every_platform.items} == {xingtu_root, juxing_root}

    only_xingtu = queries.list_tasks(platform=PlatformId.DOUYIN_XINGTU, limit=10)
    assert [item.root_task_id for item in only_xingtu.items] == [xingtu_root]
    assert only_xingtu.items[0].platform == "douyin_xingtu"

    only_juxing = queries.list_tasks(platform=PlatformId.KUAISHOU_JUXING, limit=10)
    assert [item.root_task_id for item in only_juxing.items] == [juxing_root]
    assert only_juxing.items[0].platform == "kuaishou_juxing"


def test_platform_filter_is_part_of_the_cursor_scope(repo, plan):
    queries = ProductQueries(repo)
    for _ in range(2):
        repo.create(
            plan,
            "unit",
            uid(),
            "test",
            adapter_version="synthetic-v1",
            contract_version="synthetic-v1",
            modules=["basic"],
        )

    page = queries.list_tasks(limit=1)
    assert page.next_cursor is not None

    with pytest.raises(CollectorError) as excinfo:
        queries.list_tasks(
            platform=PlatformId.KUAISHOU_JUXING,
            cursor=page.next_cursor,
            limit=1,
        )
    assert excinfo.value.reason == "INVALID_CURSOR"
