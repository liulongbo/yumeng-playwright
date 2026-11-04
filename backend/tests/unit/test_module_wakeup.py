"""A3 regression: a profile-load module whose endpoint the bare load does not emit is woken by its
own registered actions - and only when its required responses are still missing.

Background: the eight homepage modules are collected from one registered window that is opened
before navigation. `read()` already performs the bounded settle wait, so a module only times out
when the platform never emits its request. Some creators' homepages emit `seeding`/`conversion`
only after the registered tab interaction, which is why those two modules now declare that
interaction as their own `actions`.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from xingtu.adapter import BrowserAdapter
from xingtu.contracts import Action, LocatorSpec, PlatformRegistry, RequestSpec
from xingtu.domain import CollectorError

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "contracts" / "douyin_xingtu.verified.json"
TRIGGER_SELECTORS = [
    ".el-tabs__item:has-text('达人概览')",
    ".el-tabs__item:has-text('商业能力')",
]


def request_spec(key: str, *, required: bool = True) -> RequestSpec:
    return RequestSpec(
        key=key,
        method="GET",
        host="www.xingtu.cn",
        path=f"/gw/api/data_sp/{key}",
        request_match={"o_author_id": "$creator_id"},
        response_match={},
        required=required,
    )


def click(selector: str) -> Action:
    return Action(kind="click", locator=LocatorSpec(selector=selector))


class WakeHarness:
    """Records which modules were woken and with which actions."""

    def __init__(
        self,
        results: dict[str, object],
        *,
        action_error: Exception | None = None,
        ready_error: Exception | None = None,
    ) -> None:
        self.woken: list[list[str]] = []
        self.readied: list[str] = []
        self.adapter = BrowserAdapter.__new__(BrowserAdapter)
        self.action_error = action_error
        self.ready_error = ready_error

        async def actions(page: object, items: list[Action]) -> None:
            if self.action_error is not None:
                raise self.action_error
            self.woken.append([item.locator.selector for item in items])

        async def wait_ready(
            page: object, ready: LocatorSpec, hidden: list[LocatorSpec], **_: object
        ) -> None:
            if self.ready_error is not None:
                raise self.ready_error
            self.readied.append(ready.selector)

        self.adapter.actions = actions  # type: ignore[method-assign]
        self.adapter.wait_ready = wait_ready  # type: ignore[method-assign]
        self.capture = SimpleNamespace(results=results, failures={})


def module(key: str, actions: list[Action], requests: list[RequestSpec]) -> SimpleNamespace:
    return SimpleNamespace(
        key=key,
        actions=actions,
        requests=requests,
        ready=LocatorSpec(selector=f"#{key}"),
        ready_hidden=[],
    )


async def run(
    harness: WakeHarness, modules: list[SimpleNamespace], shared: SimpleNamespace
) -> None:
    await harness.adapter._wake_unresolved_modules(
        object(),  # type: ignore[arg-type]
        harness.capture,  # type: ignore[arg-type]
        modules,  # type: ignore[arg-type]
        shared,  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------------------
# the gate: wake only what the bare load failed to deliver
# --------------------------------------------------------------------------------------


async def test_wakes_a_module_whose_required_response_never_arrived() -> None:
    """The production case: creator 2's seed_base/conversion are absent from the bare load."""

    shared = module("basic", [], [request_spec("base")])
    seeding = module("seeding", [click(s) for s in TRIGGER_SELECTORS], [request_spec("seed_base")])
    harness = WakeHarness(results={"base": {"ok": True}})
    await run(harness, [shared, seeding], shared)
    assert harness.woken == [TRIGGER_SELECTORS]
    assert harness.readied == ["#seeding"]


async def test_does_not_repeat_the_interaction_when_the_load_prefetched_the_endpoint() -> None:
    """Creator 1's homepage emits the endpoint itself: no extra click, no duplicated request."""

    shared = module("basic", [], [request_spec("base")])
    seeding = module("seeding", [click(s) for s in TRIGGER_SELECTORS], [request_spec("seed_base")])
    harness = WakeHarness(results={"base": {}, "seed_base": {"avg_a3_incr_cnt": 1}})
    await run(harness, [shared, seeding], shared)
    assert harness.woken == []
    assert harness.readied == []


async def test_partially_arrived_module_is_still_woken() -> None:
    """link_structure arrives on load while seed_base does not; the trigger is still needed."""

    shared = module("basic", [], [request_spec("base")])
    seeding = module(
        "seeding",
        [click(s) for s in TRIGGER_SELECTORS],
        [request_spec("seed_base"), request_spec("link_structure")],
    )
    harness = WakeHarness(results={"base": {}, "link_structure": {}})
    await run(harness, [shared, seeding], shared)
    assert harness.woken == [TRIGGER_SELECTORS]


async def test_optional_pending_response_does_not_hold_a_module_open() -> None:
    """Optional responses enrich a result; they never justify an extra interaction."""

    shared = module("basic", [], [request_spec("base")])
    module_with_optional = module(
        "spread",
        [click(s) for s in TRIGGER_SELECTORS],
        [request_spec("spread"), request_spec("extra", required=False)],
    )
    harness = WakeHarness(results={"base": {}, "spread": {}})
    await run(harness, [shared, module_with_optional], shared)
    assert harness.woken == []


async def test_module_without_registered_actions_is_never_touched() -> None:
    shared = module("basic", [], [request_spec("base")])
    plain = module("commercial", [], [request_spec("marketing")])
    harness = WakeHarness(results={"base": {}})
    await run(harness, [shared, plain], shared)
    assert harness.woken == []


async def test_shared_window_module_actions_are_not_run_twice() -> None:
    """`profile` already ran modules[0]'s actions before the shared readiness wait."""

    shared = module("basic", [click("#shared")], [request_spec("base")])
    harness = WakeHarness(results={})
    await run(harness, [shared], shared)
    assert harness.woken == []


async def test_two_modules_needing_the_same_interaction_share_one_wake_attempt() -> None:
    """Both modules are judged independently, but the same tab is clicked only once.

    If the first wake could not make the shared tab ready, retrying the identical click for the
    second module only spends another 90 seconds on the same non-actionable locator.
    """

    shared = module("basic", [], [request_spec("base")])
    seeding = module("seeding", [click(s) for s in TRIGGER_SELECTORS], [request_spec("seed_base")])
    conversion = module(
        "conversion", [click(s) for s in TRIGGER_SELECTORS], [request_spec("conversion")]
    )
    harness = WakeHarness(results={"base": {}})
    await run(harness, [shared, seeding, conversion], shared)
    assert harness.woken == [TRIGGER_SELECTORS]
    assert harness.readied == ["#seeding"]
    assert harness.capture.failures["conversion"] == "WAKE_ACTION_SKIPPED"


async def test_wake_action_timeout_is_localized_to_the_module() -> None:
    """A 90s tab click must fail the module, never the whole task."""

    shared = module("basic", [], [request_spec("base")])
    seeding = module("seeding", [click(s) for s in TRIGGER_SELECTORS], [request_spec("seed_base")])
    harness = WakeHarness(
        results={"base": {}},
        action_error=PlaywrightTimeoutError("Locator.click: Timeout 90000ms exceeded."),
    )
    await run(harness, [shared, seeding], shared)
    assert harness.capture.failures["seed_base"] == "WAKE_ACTION_TIMEOUT"
    assert harness.readied == []


async def test_wake_ready_timeout_is_localized_to_the_module() -> None:
    shared = module("basic", [], [request_spec("base")])
    seeding = module("seeding", [click(s) for s in TRIGGER_SELECTORS], [request_spec("seed_base")])
    harness = WakeHarness(
        results={"base": {}},
        ready_error=CollectorError("PLATFORM_PAGE_CHANGED", "PAGE_READY_TIMEOUT"),
    )
    await run(harness, [shared, seeding], shared)
    assert harness.capture.failures["seed_base"] == "WAKE_READY_TIMEOUT"


async def test_fatal_wake_error_still_aborts() -> None:
    """Session/challenge/lease errors are not optional-module failures."""

    import pytest

    shared = module("basic", [], [request_spec("base")])
    seeding = module("seeding", [click(s) for s in TRIGGER_SELECTORS], [request_spec("seed_base")])
    harness = WakeHarness(
        results={"base": {}},
        action_error=CollectorError("ACCOUNT_LOGIN_REQUIRED", "REGISTERED_LOGIN_PAGE"),
    )
    with pytest.raises(CollectorError, match="ACCOUNT_LOGIN_REQUIRED"):
        await run(harness, [shared, seeding], shared)


# --------------------------------------------------------------------------------------
# the verified registry: only already-verified interactions may be registered
# --------------------------------------------------------------------------------------


def registry() -> PlatformRegistry:
    return PlatformRegistry.model_validate_json(REGISTRY.read_text())


def test_trigger_selectors_are_already_verified_for_the_featured_collections() -> None:
    """No selector may be invented for this fix; both must exist in the verified contract."""

    reg = registry()
    verified = {a.locator.selector for spec in reg.featured for a in spec.actions}
    for key in ("seeding", "conversion"):
        spec = next(m for m in reg.modules if m.key == key)
        selectors = [a.locator.selector for a in spec.actions]
        assert selectors == TRIGGER_SELECTORS
        assert set(selectors) <= verified
        assert spec.capture_on_profile_load is True, "on-load capture must be preserved"


def test_modules_that_already_worked_declare_no_new_interaction() -> None:
    """Regression guard: modules that collect fine keep exactly their previous registration."""

    reg = registry()
    untouched = ("basic", "commercial", "spread", "fulfillment")
    for key in untouched:
        spec = next(m for m in reg.modules if m.key == key)
        assert spec.actions == [], f"{key} must not gain an interaction"


def test_the_contract_still_validates_and_is_enabled() -> None:
    reg = registry()
    reg.require_enabled(live=False)
    assert reg.status == "VERIFIED"
    assert [m.key for m in reg.modules] == [
        "basic",
        "commercial",
        "spread",
        "seeding",
        "fulfillment",
        "conversion",
        "fans",
        "creation",
    ]


def test_request_and_field_contracts_are_unchanged_by_the_trigger_fix() -> None:
    """The fix adds only an interaction: no request, path, or field may change."""

    reg = registry()
    expected = {
        "seeding": (["seed_base", "link_structure"], 7),
        "conversion": (["conversion", "local_sales"], 10),
    }
    for key, (requests, field_count) in expected.items():
        spec = next(m for m in reg.modules if m.key == key)
        assert [r.key for r in spec.requests] == requests
        assert len(spec.fields) == field_count


def test_profile_load_modules_may_not_declare_an_entry() -> None:
    """The narrowed guard keeps forbidding navigation away from the creator homepage."""

    import copy

    import pytest
    from xingtu.domain import CollectorError

    raw = json.loads(REGISTRY.read_text())
    broken = copy.deepcopy(raw)
    target = next(m for m in broken["modules"] if m["key"] == "commercial")
    target["entry"] = "/ad/creator/author-homepage/douyin-video/other"
    with pytest.raises(CollectorError) as excinfo:
        PlatformRegistry.model_validate_json(json.dumps(broken)).require_enabled(live=False)
    assert excinfo.value.reason == "PROFILE_LOAD_MODULE_HAS_ENTRY"
