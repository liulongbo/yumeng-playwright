"""F06 engine/repository integration: completeness, persistence, recovery and cover lifecycle."""

import hashlib

import pytest
from xingtu.covers import CoverPipeline, LocalCoverStore
from xingtu.domain import CollectorError, ExecutionContext, ReleaseDisposition, TaskStatus, uid
from xingtu.engine import Engine
from xingtu.product_queries import ProductQueries

from backend.tests.synthetic import SyntheticAdapter

COLLECTIONS = ["excellent_reach", "excellent_seeding"]


def cards(ids):
    return [
        {
            "platform_content_id": cid,
            "link": f"https://synthetic.invalid/work/{cid}",
            "title": f"title {cid}",
            "play": 100 + index,
            "cover": f"https://cdn.synthetic.invalid/{cid}.png",
        }
        for index, cid in enumerate(ids)
    ]


def featured(*, reach=None, seeding=None):
    return {
        "excellent_reach": reach
        if reach is not None
        else {"cards": cards(["v1", "v2"]), "set_key": "set-a"},
        "excellent_seeding": seeding
        if seeding is not None
        else {"cards": cards(["v2", "v9"]), "set_key": "set-b"},
    }


def start(repo, plan, *, target_count=2):
    task_plan = plan.model_copy(update={"target_count": target_count})
    root = repo.create(
        task_plan,
        "unit",
        uid(),
        "test",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
        modules=["basic", "commercial", "fans"],
        featured_types=COLLECTIONS,
        featured_checkpoint_versions={key: 1 for key in COLLECTIONS},
    )
    task = repo.get(root)
    generation, session = repo.acquire("unit", task.attempt_id)
    return ExecutionContext(
        root_task_id=root,
        task_id=task.task_id,
        attempt_id=task.attempt_id,
        execution_unit_id="unit",
        lease_generation=generation,
        session_version=session,
        capability_version="synthetic-v1",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
    )


def pipeline(repo, tmp_path):
    store = LocalCoverStore(repo, tmp_path / "covers", tmp_path)
    return CoverPipeline(repo, store), store


async def test_full_run_is_complete_and_persists_identity_snapshots_and_covers(
    repo, plan, tmp_path
):
    ctx = start(repo, plan)
    covers, store = pipeline(repo, tmp_path)
    adapter = SyntheticAdapter(["1", "2"], featured=featured())
    engine = Engine(repo, adapter, ctx, covers=covers)
    assert await engine.run() == TaskStatus.COMPLETED

    task = repo.get(ctx.root_task_id)
    assert task.pipeline_complete is True
    assert task.featured_status == "COMPLETED"
    assert task.featured_complete_count == 2 and task.profile_complete_count == 2
    assert task.failure_reason is None

    rows = repo.results(ctx.root_task_id)
    assert len(rows) == 2
    for row in rows:
        payload = row["payload"]
        assert payload["pipeline_complete"] is True
        for key in COLLECTIONS:
            collection = payload["collections"][key]
            assert collection["status"] == "COMPLETE" and collection["complete"] is True
            assert [card["position"] for card in collection["cards"]] == [0, 1]
            assert all(card["cover"]["status"] == "STORED" for card in collection["cards"])
    with repo.connect() as conn:
        collections = conn.execute(
            "SELECT collection_type,count(*) AS n FROM featured_collections GROUP BY 1"
        ).fetchall()
        assert {row["collection_type"]: row["n"] for row in collections} == {
            "excellent_reach": 2,
            "excellent_seeding": 2,
        }
        # Same work in both modules: one contents row per work, two independent cards for v2.
        assert conn.execute("SELECT count(*) AS n FROM contents").fetchone()["n"] == 3
        shared = conn.execute(
            """SELECT c.content_id,count(*) AS n FROM featured_cards c
            JOIN contents x ON x.content_id=c.content_id WHERE x.platform_content_id='v2'
            GROUP BY 1"""
        ).fetchall()
        assert len(shared) == 1 and shared[0]["n"] >= 2
        assert conn.execute("SELECT count(*) AS n FROM snapshot_collections").fetchone()["n"] == 4
        referenced = conn.execute(
            "SELECT cover_object_id FROM featured_cards WHERE cover_status='STORED' LIMIT 1"
        ).fetchone()["cover_object_id"]
    assert referenced and store.path(referenced).is_file()
    assert repo.cover_reference(ctx.root_task_id, referenced) is not None
    assert repo.cover_reference(uid(), referenced) is None

    # F08 reads the task-linked immutable snapshot and keeps both groups independent.
    product_results = ProductQueries(repo)
    creator_page = product_results.list_creators(ctx.root_task_id)
    assert len(creator_page.items) == 2
    assert all(item.view_kind == "published" for item in creator_page.items)
    first_creator = creator_page.items[0]
    reach = product_results.contents(ctx.root_task_id, first_creator.creator_id, "excellent_reach")
    seeding = product_results.contents(
        ctx.root_task_id, first_creator.creator_id, "excellent_seeding"
    )
    assert [card["payload"]["platform_content_id"] for card in reach["cards"]] == [
        "v1",
        "v2",
    ]
    assert [card["payload"]["platform_content_id"] for card in seeding["cards"]] == [
        "v2",
        "v9",
    ]
    first_reach = product_results.contents(
        ctx.root_task_id,
        first_creator.creator_id,
        "excellent_reach",
        limit=1,
    )
    assert len(first_reach["cards"]) == 1 and first_reach["next_cursor"]
    second_reach = product_results.contents(
        ctx.root_task_id,
        first_creator.creator_id,
        "excellent_reach",
        cursor=first_reach["next_cursor"],
        limit=1,
    )
    assert len(second_reach["cards"]) == 1 and second_reach["next_cursor"] is None
    with pytest.raises(CollectorError, match="INVALID_CURSOR"):
        product_results.contents(
            ctx.root_task_id,
            first_creator.creator_id,
            "excellent_seeding",
            cursor=first_reach["next_cursor"],
            limit=1,
        )
    with pytest.raises(CollectorError, match="CREATOR_NOT_FOUND"):
        product_results.get_creator(uid(), first_creator.creator_id)

    # An unreferenced object is removable; a published one is kept.
    stray = store.put(
        root_task_id=ctx.root_task_id,
        body=b"stray",
        content_type="image/png",
        checksum=hashlib.sha256(b"stray").hexdigest(),
        source_url="https://cdn.synthetic.invalid/stray.png",
    )
    removed = covers.cleanup_unreferenced()
    assert removed == [stray]
    assert not store.path(stray).exists()
    assert store.path(referenced).is_file()
    assert repo.cover_reference(ctx.root_task_id, referenced) is not None


async def test_single_collection_failure_keeps_the_other_and_reports_partial(repo, plan, tmp_path):
    ctx = start(repo, plan)
    covers, _ = pipeline(repo, tmp_path)
    adapter = SyntheticAdapter(
        ["1", "2"],
        featured=featured(reach={"fail": "FEATURED_RESPONSE_FAILED"}),
    )
    engine = Engine(repo, adapter, ctx, covers=covers)
    assert await engine.run() == TaskStatus.PARTIAL_COMPLETED

    task = repo.get(ctx.root_task_id)
    assert task.pipeline_complete is False
    assert task.featured_status == "PARTIAL_COMPLETED"
    assert task.failure_reason == "FEATURED_COLLECTION_INCOMPLETE"
    assert task.profile_complete_count == 2 and task.featured_complete_count == 0
    for row in repo.results(ctx.root_task_id):
        collections = row["payload"]["collections"]
        assert collections["excellent_reach"]["status"] == "FAILED"
        assert collections["excellent_reach"]["failure_reason"] == "FEATURED_RESPONSE_FAILED"
        # The other module's successful cards are kept.
        assert collections["excellent_seeding"]["status"] == "COMPLETE"
        assert len(collections["excellent_seeding"]["cards"]) == 2


async def test_collection_reuse_change_recovery_and_cover_retry(repo, plan, tmp_path):
    ctx = start(repo, plan)
    covers, _ = pipeline(repo, tmp_path)

    async def run(adapter, context):
        return await Engine(repo, adapter, context, covers=covers).run()

    # Run 1: profile module fails, both collections complete; cover of v1 fails on purpose.
    broken_cover = featured()
    broken_cover["excellent_reach"]["cards"] = cards(["v1", "v2"])
    broken_cover["excellent_reach"]["cards"][0]["cover"] = (
        "https://cdn.synthetic.invalid/fail-v1.png"
    )
    adapter = SyntheticAdapter(["1", "2"], failed_module="fans", featured=broken_cover)
    engine = Engine(repo, adapter, ctx, covers=covers)
    assert await engine.run() == TaskStatus.PARTIAL_COMPLETED
    first = repo.get(ctx.root_task_id)
    reach_1 = first.checkpoint.candidates[0].collections["excellent_reach"]
    assert reach_1.status.value == "INCOMPLETE"
    assert f"cover_failed:{reach_1.cards[0].card_id}" in reach_1.coverage_gaps
    observation_1 = reach_1.collection_observation_id

    repo.release(
        "unit",
        ctx.attempt_id,
        ctx.lease_generation,
        stopped=True,
        disposition=ReleaseDisposition.VERIFIED_READY,
    )
    repo.command(ctx.root_task_id, "retry", first.version, "test")
    task = repo.get(ctx.root_task_id)
    generation, session = repo.acquire("unit", task.attempt_id)
    ctx2 = ctx.model_copy(
        update={
            "attempt_id": task.attempt_id,
            "lease_generation": generation,
            "session_version": session,
        }
    )
    # Run 2: same verified set and key, cover now stores; the complete seeding observation is
    # reused (same id) while the failed cover is re-collected into a new observation.
    adapter = SyntheticAdapter(["1", "2"], failed_module="fans", featured=featured())
    assert await run(adapter, ctx2) == TaskStatus.PARTIAL_COMPLETED
    second = repo.get(ctx.root_task_id)
    candidate = second.checkpoint.candidates[0]
    seeding_2 = candidate.collections["excellent_seeding"]
    seeding_first = first.checkpoint.candidates[0].collections["excellent_seeding"]
    assert seeding_2.collection_observation_id == seeding_first.collection_observation_id
    assert len(candidate.collection_history) == 3  # reach re-collected + seeding reused
    assert candidate.collections["excellent_reach"].status.value == "COMPLETE"
    with repo.connect() as conn:
        old = conn.execute(
            "SELECT count(*) AS n FROM featured_cards WHERE collection_observation_id=%s",
            (observation_1,),
        ).fetchone()
        assert old["n"] == 2  # the incomplete observation is preserved unchanged

    # Run 3: the default set changes; a new observation is created for that module only.
    repo.release(
        "unit",
        ctx2.attempt_id,
        ctx2.lease_generation,
        stopped=True,
        disposition=ReleaseDisposition.VERIFIED_READY,
    )
    task = repo.get(ctx.root_task_id)
    repo.command(ctx.root_task_id, "retry", task.version, "test")
    task = repo.get(ctx.root_task_id)
    generation, session = repo.acquire("unit", task.attempt_id)
    ctx3 = ctx2.model_copy(
        update={
            "attempt_id": task.attempt_id,
            "lease_generation": generation,
            "session_version": session,
        }
    )
    changed = featured()
    changed["excellent_reach"]["cards"] = cards(["v1", "v2", "v3"])
    adapter = SyntheticAdapter(["1", "2"], featured=changed)
    assert await run(adapter, ctx3) == TaskStatus.COMPLETED
    final = repo.get(ctx.root_task_id)
    assert final.pipeline_complete is True and final.featured_status == "COMPLETED"
    candidate = final.checkpoint.candidates[0]
    reach_3 = candidate.collections["excellent_reach"]
    assert reach_3.collection_observation_id != observation_1
    assert [card.platform_content_id for card in reach_3.cards] == ["v1", "v2", "v3"]
    assert len(candidate.collection_history) == 4
    assert observation_1 in {o.collection_observation_id for o in candidate.collection_history}
    with repo.connect() as conn:
        # Both observations are stored; history is append-only, never rewritten.
        rows = conn.execute(
            """SELECT payload FROM featured_collections
            WHERE collection_observation_id=ANY(%s) ORDER BY observed_at""",
            ([observation_1, reach_3.collection_observation_id],),
        ).fetchall()
        assert len(rows) == 2
