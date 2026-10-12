from types import SimpleNamespace
from unittest.mock import AsyncMock

from xingtu.adapter import BrowserAdapter
from xingtu.domain import Checkpoint, CollectionType, CreatorRef


async def test_completed_featured_collection_is_skipped_before_any_reload(plan):
    adapter = object.__new__(BrowserAdapter)
    adapter.detail_page = object()
    adapter.operation_metrics = {}
    adapter.check_session = AsyncMock()
    adapter.verify_identity = AsyncMock()
    adapter._collect_featured = AsyncMock()
    spec = SimpleNamespace(key=CollectionType.EXCELLENT_REACH)
    adapter.registry = SimpleNamespace(featured=[spec])
    creator = CreatorRef(
        platform_creator_id="creator-1",
        verified_homepage="https://synthetic.invalid/creator/creator-1",
    )
    candidate = SimpleNamespace(
        ref=creator,
        collections={"excellent_reach": SimpleNamespace(complete=True)},
    )
    checkpoint = Checkpoint.model_construct(
        conditions_digest=plan.digest(),
        candidates=[candidate],
        contract_version="v1",
        adapter_version="v1",
    )

    observations = await adapter.collect_featured_collections(creator, checkpoint, None)

    assert observations == []
    adapter._collect_featured.assert_not_awaited()
    assert adapter.operation_metrics.get("featured_loads", 0) == 0
