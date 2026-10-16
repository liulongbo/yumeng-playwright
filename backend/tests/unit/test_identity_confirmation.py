"""DIAG-01 regression: the bound-identity read must be non-empty, confirmed and bounded.

Covers the confirmed root cause of ISSUE-001 - after a same-URL reload the platform renders
``div.author-info span.copy-text`` with EMPTY text for a few tens of milliseconds while the SPA
hydrates, and the reader used to accept that blank as a successful identity read.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from xingtu.adapter import BrowserAdapter
from xingtu.contracts import LocatorSpec
from xingtu.domain import (
    CollectionStatus,
    CollectionType,
    CollectorError,
    CreatorRef,
    FeaturedCard,
    FeaturedCollectionObservation,
    FieldObservation,
    FieldStatus,
)

IDENTITY_SELECTOR = "div.author-info span.copy-text"
PAGE_URL = "https://www.xingtu.cn/ad/creator/author-homepage/douyin-video/1"
CREATOR_ID = "7503176021160493065"
OTHER_ID = "7282701602991898661"


class ScriptedLocator:
    """Yields (match_count, text) pairs; the last step repeats once the script is exhausted."""

    def __init__(self, steps: list[tuple[int, str]]) -> None:
        self._steps = list(steps)
        self._current = steps[-1]

    async def count(self) -> int:
        if self._steps:
            self._current = self._steps.pop(0)
        return self._current[0]

    async def inner_text(self) -> str:
        return self._current[1]

    async def all_inner_texts(self) -> list[str]:
        return [self._current[1]] if self._current[0] else []


class ScriptedPage:
    def __init__(self, steps: list[tuple[int, str]]) -> None:
        self._locator = ScriptedLocator(steps)

    def locator(self, selector: str) -> ScriptedLocator:
        return self._locator


def _stub_card() -> FeaturedCard:
    """One minimal registered card, so a COMPLETE observation satisfies its own contract."""

    return FeaturedCard(
        card_id="card-1",
        position=0,
        local_key="content-1",
        fields=[
            FieldObservation(
                field_key="stub",
                value="1",
                status=FieldStatus.COLLECTED,
                source_kind="response",
                source_contract="test-contract",
                operation_id="op-card",
                session_version=1,
            )
        ],
        expected_fields=["stub"],
        operation_id="op-card",
        contract_version="test-contract",
    )


def identity_adapter(
    steps: list[tuple[int, str]], *, cap: float = 5.0, poll: float = 0.1
) -> BrowserAdapter:
    adapter = BrowserAdapter.__new__(BrowserAdapter)
    adapter.registry = SimpleNamespace(  # type: ignore[assignment]
        session=SimpleNamespace(identity=LocatorSpec(selector=IDENTITY_SELECTOR))
    )
    adapter.identity_read_cap_seconds = cap
    adapter.identity_poll_seconds = poll
    return adapter


def creator(platform_creator_id: str = CREATOR_ID) -> CreatorRef:
    return CreatorRef(
        platform_creator_id=platform_creator_id,
        verified_homepage=(
            f"https://www.xingtu.cn/ad/creator/author-homepage/douyin-video/{platform_creator_id}"
        ),
    )


# --------------------------------------------------------------------------------------
# read_locator compatibility: the new flag must not change any existing caller
# --------------------------------------------------------------------------------------


async def test_read_locator_default_still_accepts_an_empty_value() -> None:
    """Optional fields keep the existing contract: a blank is a readable value."""

    adapter = identity_adapter([(1, "")])
    page = ScriptedPage([(1, "")])
    assert await adapter.read_locator(page, LocatorSpec(selector="x")) == ""


async def test_read_locator_default_returns_non_empty_unchanged() -> None:
    adapter = identity_adapter([(1, "  some value  ")])
    page = ScriptedPage([(1, "  some value  ")])
    assert await adapter.read_locator(page, LocatorSpec(selector="x")) == "some value"


@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
async def test_read_locator_require_non_empty_rejects_blank(blank: str) -> None:
    adapter = identity_adapter([(1, blank)])
    page = ScriptedPage([(1, blank)])
    with pytest.raises(CollectorError) as excinfo:
        await adapter.read_locator(page, LocatorSpec(selector="x"), require_non_empty=True)
    assert excinfo.value.code == "MODULE_COLLECTION_FAILED"
    assert excinfo.value.reason.startswith("UNREADABLE_VALUE:")


async def test_read_locator_require_non_empty_accepts_a_real_value() -> None:
    adapter = identity_adapter([(1, CREATOR_ID)])
    page = ScriptedPage([(1, CREATOR_ID)])
    spec = LocatorSpec(selector="x")
    assert await adapter.read_locator(page, spec, require_non_empty=True) == CREATOR_ID


async def test_multiple_branch_is_unaffected_by_the_flag() -> None:
    adapter = identity_adapter([(1, "a")])
    page = ScriptedPage([(2, "a")])
    spec = LocatorSpec(selector="x", multiple=True)
    assert await adapter.read_locator(page, spec, require_non_empty=True) == ["a"]


# --------------------------------------------------------------------------------------
# verify_identity: transient blank, persistent blank, stable mismatch, immediate match
# --------------------------------------------------------------------------------------


async def test_transient_blank_then_correct_passes() -> None:
    """The exact production transient: present-but-blank, then the real id ~100 ms later."""

    page = ScriptedPage([(1, ""), (1, ""), (1, CREATOR_ID)])
    adapter = identity_adapter([], cap=5.0, poll=0.01)
    await adapter.verify_identity(page, creator())


async def test_element_absent_then_correct_passes() -> None:
    page = ScriptedPage([(0, ""), (1, CREATOR_ID)])
    adapter = identity_adapter([], cap=5.0, poll=0.01)
    await adapter.verify_identity(page, creator())


async def test_persistent_blank_ends_in_identity_unreadable_and_is_bounded() -> None:
    page = ScriptedPage([(1, "")])
    adapter = identity_adapter([], cap=0.3, poll=0.05)
    started = time.monotonic()
    with pytest.raises(CollectorError) as excinfo:
        await adapter.verify_identity(page, creator())
    elapsed = time.monotonic() - started
    assert excinfo.value.code == "PLATFORM_PAGE_CHANGED"
    assert excinfo.value.reason == "IDENTITY_UNREADABLE"
    assert elapsed < 1.5, "the bounded window must terminate, never loop"


async def test_element_absent_forever_ends_in_identity_unreadable() -> None:
    page = ScriptedPage([(0, "")])
    adapter = identity_adapter([], cap=0.3, poll=0.05)
    with pytest.raises(CollectorError) as excinfo:
        await adapter.verify_identity(page, creator())
    assert excinfo.value.reason == "IDENTITY_UNREADABLE"


async def test_stable_wrong_identity_still_reports_mismatch() -> None:
    """A confirmed, non-empty, wrong id remains a data-correctness failure."""

    page = ScriptedPage([(1, OTHER_ID)])
    adapter = identity_adapter([], cap=5.0, poll=0.01)
    with pytest.raises(CollectorError) as excinfo:
        await adapter.verify_identity(page, creator())
    assert excinfo.value.code == "CREATOR_INVALID"
    assert excinfo.value.reason == "IDENTITY_MISMATCH"


async def test_transient_wrong_identity_then_correct_passes() -> None:
    """A single wrong value must be confirmed before it is reported as a wrong creator."""

    page = ScriptedPage([(1, OTHER_ID), (1, CREATOR_ID)])
    adapter = identity_adapter([], cap=5.0, poll=0.01)
    await adapter.verify_identity(page, creator())


async def test_correct_identity_is_accepted_without_a_confirmation_wait() -> None:
    """The common path costs exactly one read: no poll interval may be added to it."""

    page = ScriptedPage([(1, CREATOR_ID)])
    adapter = identity_adapter([], cap=5.0, poll=2.0)
    started = time.monotonic()
    await adapter.verify_identity(page, creator())
    assert time.monotonic() - started < 1.0


async def test_verification_is_not_skipped_and_never_defaults_to_the_expected_value() -> None:
    """A blank page must fail closed; it may never be reported as a verified identity."""

    page = ScriptedPage([(1, "")])
    adapter = identity_adapter([], cap=0.2, poll=0.05)
    with pytest.raises(CollectorError):
        await adapter.verify_identity(page, creator())


# --------------------------------------------------------------------------------------
# C1: featured failure classification - narrow whitelist, everything else stays fatal
# --------------------------------------------------------------------------------------


def test_module_collection_failure_is_spec_local() -> None:
    error = CollectorError("MODULE_COLLECTION_FAILED", "FEATURED_RESPONSE_FAILED:cards")
    assert BrowserAdapter.featured_spec_local_reason(error) == "FEATURED_RESPONSE_FAILED:cards"


def test_page_ready_timeout_is_spec_local() -> None:
    error = CollectorError("PLATFORM_PAGE_CHANGED", "PAGE_READY_TIMEOUT")
    assert BrowserAdapter.featured_spec_local_reason(error) == "PAGE_READY_TIMEOUT"


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        ("PLATFORM_SECURITY_CHALLENGE", "REGISTERED_PAGE_STATE"),
        ("ACCOUNT_LOGIN_REQUIRED", "REGISTERED_PAGE_STATE"),
        ("ACCOUNT_MISMATCH", "WRONG_ACCOUNT"),
        ("LEASE_LOST", ""),
        ("RESOURCE_UNAVAILABLE", "BROWSER_TRANSPORT"),
        ("SESSION_INDETERMINATE", "PROTECTED_PAGE_NOT_READABLE"),
        ("CREATOR_INVALID", "IDENTITY_MISMATCH"),
        ("PLATFORM_PAGE_CHANGED", "IDENTITY_UNREADABLE"),
        # Deliberately NOT expanded this round; kept fatal until evidence justifies it.
        ("PLATFORM_PAGE_CHANGED", "RESPONSE_SCHEMA_MISMATCH"),
        ("PLATFORM_PAGE_CHANGED", "RESPONSE_CONTENT_TYPE"),
        ("MODULE_COLLECTION_FAILED", None),
    ],
)
def test_global_failures_are_never_downgraded(code: str, reason: str | None) -> None:
    error = CollectorError(code, reason or "")
    if code == "MODULE_COLLECTION_FAILED":
        # A module-scoped failure is local even without a reason, but never a global code.
        assert BrowserAdapter.featured_spec_local_reason(error) is not None
        return
    assert BrowserAdapter.featured_spec_local_reason(error) is None


class FeaturedLoopAdapter:
    """Runs the real collect_featured_collections loop with scripted per-spec outcomes."""

    @staticmethod
    def build(outcomes: dict[CollectionType, Exception | None]) -> tuple[BrowserAdapter, list]:
        specs = [
            SimpleNamespace(key=CollectionType.EXCELLENT_REACH, module_label="优秀触达"),
            SimpleNamespace(key=CollectionType.EXCELLENT_SEEDING, module_label="优秀种草"),
        ]
        adapter = BrowserAdapter.__new__(BrowserAdapter)
        adapter.registry = SimpleNamespace(  # type: ignore[assignment]
            featured=specs, contract_version="test-contract"
        )
        adapter.detail_page = SimpleNamespace(url="https://www.xingtu.cn/ad/creator/index")
        adapter.operation_metrics = {}
        attempted: list[CollectionType] = []

        def metric(key: str, amount: int = 1) -> None:
            adapter.operation_metrics[key] = adapter.operation_metrics.get(key, 0) + amount

        adapter.metric = metric  # type: ignore[method-assign]

        async def check_session(page: object) -> None:
            return None

        async def verify_identity(page: object, who: CreatorRef) -> None:
            return None

        async def collect(
            page: object, spec: SimpleNamespace, who: CreatorRef, ctx: object
        ) -> FeaturedCollectionObservation:
            attempted.append(spec.key)
            failure = outcomes.get(spec.key)
            if failure is not None:
                raise failure
            return FeaturedCollectionObservation(
                creator_ref=who,
                collection_type=spec.key,
                module_label=spec.module_label,
                page_url="https://www.xingtu.cn/ad/creator/index",
                status=CollectionStatus.COMPLETE,
                load_complete=True,
                cards=[_stub_card()],
                operation_id=f"op-{spec.key.value}",
                contract_version="test-contract",
            )

        adapter.check_session = check_session  # type: ignore[method-assign]
        adapter.verify_identity = verify_identity  # type: ignore[method-assign]
        adapter._collect_featured = collect  # type: ignore[method-assign]
        return adapter, attempted


async def test_one_spec_local_failure_keeps_the_other_collection() -> None:
    adapter, attempted = FeaturedLoopAdapter.build(
        {
            CollectionType.EXCELLENT_REACH: CollectorError(
                "MODULE_COLLECTION_FAILED", "FEATURED_RESPONSE_FAILED:cards"
            )
        }
    )
    observations = await adapter.collect_featured_collections(
        creator(),
        SimpleNamespace(candidates=[]),
        None,  # type: ignore[arg-type]
    )
    assert attempted == [CollectionType.EXCELLENT_REACH, CollectionType.EXCELLENT_SEEDING]
    assert [o.collection_type for o in observations] == [
        CollectionType.EXCELLENT_REACH,
        CollectionType.EXCELLENT_SEEDING,
    ]
    assert observations[0].status == CollectionStatus.FAILED
    assert observations[0].failure_reason == "FEATURED_RESPONSE_FAILED:cards"
    assert observations[1].status == CollectionStatus.COMPLETE


async def test_page_ready_timeout_is_local_to_this_collection() -> None:
    adapter, attempted = FeaturedLoopAdapter.build(
        {
            CollectionType.EXCELLENT_REACH: CollectorError(
                "PLATFORM_PAGE_CHANGED", "PAGE_READY_TIMEOUT"
            )
        }
    )
    observations = await adapter.collect_featured_collections(
        creator(),
        SimpleNamespace(candidates=[]),
        None,  # type: ignore[arg-type]
    )
    assert attempted == [CollectionType.EXCELLENT_REACH, CollectionType.EXCELLENT_SEEDING]
    assert observations[0].status == CollectionStatus.FAILED
    assert observations[0].failure_reason == "PAGE_READY_TIMEOUT"
    assert observations[1].status == CollectionStatus.COMPLETE


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        ("PLATFORM_SECURITY_CHALLENGE", "REGISTERED_PAGE_STATE"),
        ("ACCOUNT_LOGIN_REQUIRED", "REGISTERED_PAGE_STATE"),
        ("LEASE_LOST", ""),
        ("RESOURCE_UNAVAILABLE", "BROWSER_TRANSPORT"),
        ("CREATOR_INVALID", "IDENTITY_MISMATCH"),
        ("PLATFORM_PAGE_CHANGED", "IDENTITY_UNREADABLE"),
        ("PLATFORM_PAGE_CHANGED", "RESPONSE_SCHEMA_MISMATCH"),
    ],
)
async def test_global_failure_still_aborts_the_whole_creator(code: str, reason: str) -> None:
    adapter, attempted = FeaturedLoopAdapter.build(
        {CollectionType.EXCELLENT_REACH: CollectorError(code, reason)}
    )
    with pytest.raises(CollectorError) as excinfo:
        await adapter.collect_featured_collections(
            creator(),
            SimpleNamespace(candidates=[]),
            None,  # type: ignore[arg-type]
        )
    assert excinfo.value.code == code
    assert attempted == [CollectionType.EXCELLENT_REACH], "the sibling must not be attempted"


async def test_no_failure_returns_both_collections() -> None:
    adapter, attempted = FeaturedLoopAdapter.build({})
    observations = await adapter.collect_featured_collections(
        creator(),
        SimpleNamespace(candidates=[]),
        None,  # type: ignore[arg-type]
    )
    assert len(observations) == 2
    assert attempted == [CollectionType.EXCELLENT_REACH, CollectionType.EXCELLENT_SEEDING]
    assert all(o.status == CollectionStatus.COMPLETE for o in observations)


async def test_retries_are_paced_by_the_poll_interval_not_a_busy_loop() -> None:
    """Two blank reads must cost about two poll intervals, proving a bounded paced retry."""

    page = ScriptedPage([(1, ""), (1, ""), (1, CREATOR_ID)])
    adapter = identity_adapter([], cap=5.0, poll=0.15)
    started = time.monotonic()
    await adapter.verify_identity(page, creator())
    elapsed = time.monotonic() - started
    assert elapsed >= 0.25, "blank reads must not be retried in a tight loop"
    assert elapsed < 3.0, "and must not fall back to a large fixed wait"
