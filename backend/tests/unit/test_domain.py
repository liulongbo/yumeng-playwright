import copy
from decimal import Decimal

import pytest
from pydantic import ValidationError
from xingtu.contracts import PlatformRegistry
from xingtu.domain import (
    CollectorError,
    FieldObservation,
    FieldStatus,
    FilterPlan,
    NumberRange,
    SearchPage,
)
from xingtu.normalize import consistent, number, quote


@pytest.mark.parametrize("target", [0, 201, 1.5, True, "20"])
def test_invalid_targets(plan, target):
    with pytest.raises(ValidationError):
        FilterPlan.model_validate({**plan.model_dump(), "target_count": target})


def test_plan_zero_bounds_and_capability_gates(plan, capabilities):
    capabilities.validate_plan(plan, live=False)
    with pytest.raises(CollectorError, match="live evidence"):
        capabilities.validate_plan(plan, live=True)
    with pytest.raises(ValidationError):
        FilterPlan.model_validate({**plan.model_dump(), "filters": []})
    with pytest.raises(ValidationError):
        NumberRange(min=2, max=1)
    changed = plan.model_copy(update={"capability_version": "old"})
    with pytest.raises(CollectorError):
        capabilities.validate_plan(changed, live=False)


@pytest.mark.parametrize(
    "raw,amount,bound",
    [
        ("0", "0", "exact"),
        ("1.2万", "12000", "approximate"),
        ("1万+", "10000", "lower"),
        ("2.5w", "25000", "approximate"),
        ("5.2%", "0.052", "exact"),
    ],
)
def test_numeric_semantics(raw, amount, bound):
    value = number(raw, unit="ratio" if "%" in raw else "count")
    assert value.amount == Decimal(amount)
    assert value.bound == bound


@pytest.mark.parametrize("raw", ["", "—", "NaN", "-2", "unknown"])
def test_missing_is_never_zero(raw):
    with pytest.raises(CollectorError):
        number(raw, unit="count")


def test_quote_and_precision():
    value = quote("0-200", currency="CNY", cooperation_form="synthetic_60s")
    assert value.amount.min == 0 and value.amount.max == 200
    assert quote("面议", currency="CNY", cooperation_form="synthetic").negotiable
    assert consistent(number("1.2万", unit="count"), number("12030", unit="count"))
    assert not consistent(number("1.2万", unit="count"), number("14000", unit="count"))
    with pytest.raises(CollectorError):
        number("5.2", unit="ratio")


def test_field_and_exhaustion_require_evidence():
    with pytest.raises(ValidationError):
        FieldObservation(
            field_key="f", status=FieldStatus.NO_DATA, operation_id="op", session_version=1
        )
    with pytest.raises(ValidationError):
        SearchPage(
            candidates=[],
            current_checkpoint=None,
            next_checkpoint=None,
            conditions_digest="x",
            search_generation=0,
            operation_id="op",
            exhausted=True,
        )


def test_shipped_registry_cannot_run():
    from pathlib import Path

    registry = PlatformRegistry.model_validate_json(
        Path("contracts/douyin_xingtu.unverified.json").read_text()
    )
    with pytest.raises(CollectorError, match="UNVERIFIED_REGISTRY"):
        registry.require_enabled(live=True)


def registry_dict(capabilities):
    """Minimal fully-referenced registry; every unknown path would be null in production."""

    def dom(selector):
        return {"kind": "dom", "locator": {"selector": selector}}

    return {
        "contract_version": "synthetic-v1",
        "adapter_version": "synthetic-v1",
        "status": "VERIFIED",
        "sample_kind": "synthetic",
        "capabilities": capabilities.model_dump(),
        "allowed_hosts": ["synthetic.invalid"],
        "homepage_path_prefixes": ["/creator/"],
        "action_interval_seconds": 0.001,
        "operation_timeout_seconds": 1,
        "response_body_max_bytes": 4096,
        "session": {
            "entry_url": "https://synthetic.invalid/search",
            "account": {"selector": "#account"},
            "protected_ready": {"selector": "#ready"},
            "error_selectors": {},
            "identity": {"selector": "#identity"},
        },
        "search": {
            "entry_url": "https://synthetic.invalid/search",
            "reset_actions": [],
            "apply_actions": [{"kind": "click", "locator": {"selector": "#go"}}],
            "next_actions": [{"kind": "click", "locator": {"selector": "#next"}}],
            "ready": {"selector": "#ready"},
            "readback": {"sort": {"selector": "#sort"}},
            "requests": [
                {
                    "key": "list",
                    "method": "GET",
                    "host": "synthetic.invalid",
                    "path": "/api/search",
                    "request_match": {"sort": "$sort"},
                    "response_match": {"sort": "$sort"},
                    "success_path": "code",
                    "success_value": "0",
                }
            ],
            "result_request_key": "list",
            "candidates_path": "items",
            "id_path": "id",
            "homepage_path": "url",
            "next_path": "next",
            "exhausted_path": "done",
            "exhausted_value": "true",
            "pagination": "page",
        },
        "modules": [
            {
                "key": "basic",
                "basic": True,
                "ready": {"selector": "#identity"},
                "fields": [
                    {
                        "key": "platform_creator_id",
                        "name": "id",
                        "kind": "text",
                        "source": dom("#i"),
                    },
                    {"key": "nickname", "name": "nickname", "kind": "text", "source": dom("#n")},
                ],
            },
            {
                "key": "fans",
                "ready": {"selector": "#fans"},
                "fields": [
                    {
                        "key": "total",
                        "name": "fans",
                        "kind": "number",
                        "unit": "count",
                        "source": dom("#fans"),
                    }
                ],
            },
        ],
    }


def test_referenced_registry_is_publishable(capabilities):
    PlatformRegistry.model_validate(registry_dict(capabilities)).require_enabled(live=False)


def _reject(result, key="list", value="code"):
    result["search"]["requests"][0][key] = value


@pytest.mark.parametrize(
    "reason,mutate",
    [
        ("INVALID_HOST_SCOPE", lambda d: d.update(homepage_path_prefixes=["creator/"])),
        (
            "INVALID_ENTRY_URL",
            lambda d: d["search"].update(entry_url="https://other.invalid/search"),
        ),
        (
            "DUPLICATE_REQUEST_KEY",
            lambda d: d["search"]["requests"].append(d["search"]["requests"][0]),
        ),
        ("INVALID_REQUEST_CONTRACT", lambda d: _reject(d, "host", "other.invalid")),
        ("UNKNOWN_ERROR_CODE", lambda d: _reject(d, "error_codes", {"login": "NOT_A_CODE"})),
        ("MISSING_RESULT_REQUEST", lambda d: d["search"].update(result_request_key="nope")),
        ("INCOMPLETE_SEARCH_CONTRACT", lambda d: d["search"].update(exhausted_path="")),
        ("MISSING_PAGINATION_ACTION", lambda d: d["search"].update(next_actions=[])),
        ("BASIC_MODULE_ENTRY_UNSUPPORTED", lambda d: d["modules"][0].update(entry="/creator/A")),
        ("EMPTY_LOCATOR", lambda d: d["modules"][1]["ready"].update(selector="")),
        (
            "MISSING_DOM_CONTRACT",
            lambda d: d["modules"][1]["fields"][0].update(source={"kind": "dom"}),
        ),
        (
            "MISSING_RESPONSE_CONTRACT",
            lambda d: d["modules"][1]["fields"][0].update(
                source={"kind": "response", "request_key": "r"}
            ),
        ),
        (
            "UNDECLARED_SOURCE_REQUEST",
            lambda d: d["modules"][1]["fields"][0].update(
                source={"kind": "response", "request_key": "r", "path": "value"}
            ),
        ),
        (
            "FALLBACK_WITHOUT_TRIGGER",
            lambda d: d["modules"][1]["fields"][0].update(
                fallback={"kind": "dom", "locator": {"selector": "#x"}}
            ),
        ),
        (
            "MISSING_FIELD_UNIT",
            lambda d: d["modules"][1]["fields"].append(
                {
                    "key": "extra",
                    "name": "x",
                    "kind": "number",
                    "source": {"kind": "dom", "locator": {"selector": "#x"}},
                }
            ),
        ),
        (
            "INCOMPLETE_QUOTE_CONTRACT",
            lambda d: d["modules"][1]["fields"].append(
                {
                    "key": "quote",
                    "name": "x",
                    "kind": "quote",
                    "source": {"kind": "dom", "locator": {"selector": "#q"}},
                }
            ),
        ),
        (
            "AMBIGUOUS_FIELD_ABSENCE",
            lambda d: d["modules"][1]["fields"][0].update(
                empty_values=["x"], permission_values=["x"]
            ),
        ),
        (
            "DUPLICATE_MODULE_FIELD",
            lambda d: d["modules"][1]["fields"].append(copy.deepcopy(d["modules"][1]["fields"][0])),
        ),
        (
            "AMBIGUOUS_MODULE_ABSENCE",
            lambda d: d["modules"][1].update(
                absence={
                    "probe": {"kind": "dom", "locator": {"selector": "#a"}},
                    "empty_values": ["x"],
                    "permission_values": ["x"],
                }
            ),
        ),
        (
            "INVALID_MODULE_ENTRY",
            lambda d: d["modules"][1].update(entry="http://synthetic.invalid/x"),
        ),
        ("INVALID_MODULE_ENTRY", lambda d: d["modules"][1].update(entry="creator/x")),
    ],
)
def test_unpublishable_registries_are_rejected(capabilities, reason, mutate):
    data = registry_dict(capabilities)
    mutate(data)
    registry = PlatformRegistry.model_validate(data)
    with pytest.raises(CollectorError, match=reason):
        registry.require_enabled(live=False)
