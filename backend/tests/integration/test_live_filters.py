from pathlib import Path

from xingtu.contracts import PlatformRegistry
from xingtu.domain import CreatorScene, TaskStatus
from xingtu.intake import build_expected_plan
from xingtu.product_models import RequirementForm
from xingtu.product_queries import ProductQueries
from xingtu.product_repository import ProductRepository


def product_user(products):
    from xingtu.product_auth import PasswordService

    return products.create_user(
        "media-live-filters",
        "媒介直播筛选",
        PasswordService().hash("a-secure-password"),
        actor="test",
    )


def live_registry(name: str) -> PlatformRegistry:
    return PlatformRegistry.model_validate_json(Path(f"contracts/{name}").read_text())


def test_filter_only_live_requirement_is_persisted_and_promoted(repo):
    products = ProductRepository(repo)
    user_id = product_user(products)
    registry = live_registry("douyin_xingtu.live.verified.json")
    form = RequirementForm(
        schema_version="requirement_form.v2",
        platform="douyin_xingtu",
        creator_scene=CreatorScene.LIVE_SQUARE,
        keyword=None,
        target_count=5,
        live_filters=[
            {"field": "live_content_type", "values": ["fashion"]},
            {"field": "live_gender", "values": ["female"]},
        ],
    )
    response = products.create_product_task(
        form,
        capability_version=registry.capabilities.version,
        user_id=user_id,
        idempotency_key="live-filter-only",
        model_config_id="deepseek-flash",
        prompt_version="m3-filter-plan-v2",
    )
    state = products.load_intake(response.root_task_id)
    assert state.requirement_form.live_filters[0].field == "live_content_type"
    plan = build_expected_plan(state.requirement_form, registry.capabilities)
    assert [item.field for item in plan.filters] == ["live_content_type", "live_gender"]
    succeeded = state.model_copy(
        update={"outcome": "succeeded", "final_plan": plan, "attempt_count": 1}
    )
    products.save_intake(succeeded, TaskStatus.PARSING)
    products.promote_intake(
        succeeded, plan, unit_id="unit", registry=registry, profile_requirement=None
    )
    task = repo.get(response.root_task_id)
    assert task.creator_scene == CreatorScene.LIVE_SQUARE
    assert task.plan is not None
    assert [item.field for item in task.plan.filters] == ["live_content_type", "live_gender"]
    detail = ProductQueries(repo).get_task(response.root_task_id)
    assert detail.creator_scene == CreatorScene.LIVE_SQUARE
    assert detail.requirement is not None
    assert detail.requirement.live_filters[0].field == "live_content_type"
    with repo.connect() as conn:
        row = conn.execute(
            "SELECT payload FROM filter_plans WHERE root_task_id=%s", (response.root_task_id,)
        ).fetchone()
    assert row is not None
    assert {item["field"] for item in row["payload"]["filters"]} == {
        "live_content_type",
        "live_gender",
    }


def test_video_requirement_still_rejects_live_filters(repo):
    del repo
    try:
        RequirementForm(
            schema_version="requirement_form.v2",
            platform="douyin_xingtu",
            keyword="宠物",
            live_filters=[{"field": "live_content_type", "values": ["fashion"]}],
        )
    except ValueError as exc:
        assert "live_square" in str(exc)
    else:  # pragma: no cover - the validation must never accept this
        raise AssertionError("video requirement accepted live filters")
