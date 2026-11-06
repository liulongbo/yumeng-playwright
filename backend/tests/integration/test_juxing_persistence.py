import pytest
from xingtu.domain import (
    Candidate,
    CollectorError,
    CreatorRef,
    FieldObservation,
    FieldStatus,
    Filter,
    FilterPlan,
    ModuleObservation,
    NumericValue,
    uid,
)


def test_juxing_identity_projection_and_snapshot_stay_platform_isolated(repo):
    plan = FilterPlan(
        schema_version="filter_plan.v3",
        platform="kuaishou_juxing",
        capability_version="juxing-video-square-stage-b-v1",
        target_count=1,
        filters=[
            Filter(
                field="keyword",
                operator="eq",
                value="母婴",
                source_fields=["keyword"],
            )
        ],
    )
    root = repo.create(
        plan,
        "unit",
        "juxing-stage-b-persistence",
        "test",
        adapter_version="juxing-browser-v1",
        contract_version="juxing-video-creator-stage-b-v1",
        modules=["basic"],
        module_checkpoint_versions={"basic": 1},
    )
    ref = CreatorRef(
        platform="kuaishou_juxing",
        platform_creator_id="576757970",
        verified_homepage="https://k.kuaishou.com/#/promotion/star/196223?openBy=user",
    )
    operation = uid()
    basic = ModuleObservation(
        creator_ref=ref,
        module_key="basic",
        fields=[
            FieldObservation(
                field_key="platform_creator_id",
                value="576757970",
                status=FieldStatus.COLLECTED,
                source_kind="response",
                source_contract="juxing-video-creator-stage-b-v1",
                path_ref="data.userId",
                operation_id=operation,
                session_version=1,
            ),
            FieldObservation(
                field_key="nickname",
                value="真实样本昵称已脱敏",
                status=FieldStatus.COLLECTED,
                source_kind="response",
                source_contract="juxing-video-creator-stage-b-v1",
                path_ref="data.name",
                operation_id=operation,
                session_version=1,
            ),
            FieldObservation(
                field_key="followers",
                value=NumericValue(amount="21686076"),
                raw_value="21686076",
                status=FieldStatus.COLLECTED,
                source_kind="response",
                source_contract="juxing-video-creator-stage-b-v1",
                path_ref="data.fansNumber",
                operation_id=operation,
                session_version=1,
                unit="count",
            ),
        ],
        expected_fields=["platform_creator_id", "nickname", "followers"],
        operation_id=operation,
        contract_version="juxing-video-creator-stage-b-v1",
    )
    with repo.edit(root) as (task, conn):
        task.checkpoint.candidates = [
            Candidate(ref=ref, valid=True, state="done", modules={"basic": basic})
        ]
        task.checkpoint.profile_field_keys = {
            "basic": ["platform_creator_id", "nickname", "followers"]
        }
        task.valid_count = 1
        task.profile_complete_count = 1
        assert repo.pipeline_complete(task, ref.platform_creator_id) is True
        repo.persist_creators(conn, task, publish=True)

    with repo.connect() as conn:
        identity = conn.execute(
            """SELECT creator_id,platform,platform_creator_id,projection,video_homepage
            FROM platform_creators WHERE platform=%s AND platform_creator_id=%s""",
            ("kuaishou_juxing", "576757970"),
        ).fetchone()
        assert identity is not None
        assert identity["video_homepage"] == (
            "https://k.kuaishou.com/#/promotion/star/196223?openBy=user"
        )
        assert identity["projection"]["basic.nickname"]["value"] == "真实样本昵称已脱敏"
        assert identity["projection"]["basic.followers"]["raw_value"] == "21686076"
        snapshot = conn.execute(
            "SELECT payload FROM creator_snapshots WHERE creator_id=%s",
            (identity["creator_id"],),
        ).fetchone()
        assert snapshot is not None
        assert snapshot["payload"]["profile_complete"] is True
        assert snapshot["payload"]["modules"]["basic"]["contract_version"] == (
            "juxing-video-creator-stage-b-v1"
        )
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM douyin_xingtu_creator_current WHERE creator_id=%s",
                (identity["creator_id"],),
            ).fetchone()["n"]
            == 0
        )


def test_persist_creators_refuses_a_foreign_platform_identity(repo):
    """Defence in depth: a juxing task must never persist a Xingtu CreatorRef."""
    plan = FilterPlan(
        schema_version="filter_plan.v3",
        platform="kuaishou_juxing",
        capability_version="juxing-video-square-stage-b-v1",
        target_count=1,
        filters=[Filter(field="keyword", operator="eq", value="母婴", source_fields=["keyword"])],
    )
    root = repo.create(
        plan,
        "unit",
        "juxing-platform-guard",
        "test",
        adapter_version="juxing-browser-v1",
        contract_version="juxing-video-creator-stage-b-v1",
        modules=["basic"],
        module_checkpoint_versions={"basic": 1},
    )
    with repo.edit(root) as (task, conn):
        task.checkpoint.candidates = [
            Candidate(
                ref=CreatorRef(
                    platform="douyin_xingtu",
                    platform_creator_id="7503176021160493065",
                    verified_homepage="https://synthetic.invalid/xingtu",
                ),
                valid=True,
            )
        ]
        with pytest.raises(CollectorError) as caught:
            repo.persist_creators(conn, task, publish=True)
    assert caught.value.reason == "CREATOR_PLATFORM_MISMATCH"
    with repo.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM platform_creators").fetchone()["n"] == 0
