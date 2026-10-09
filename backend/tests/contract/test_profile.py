import pytest
from xingtu.adapter import BrowserAdapter
from xingtu.contracts import FieldSpec, LocatorSpec, ProfileModuleSpec, SourceSpec
from xingtu.domain import CreatorRef, FieldStatus


async def test_multiple_dom_locator_trims_deduplicates_and_preserves_order():
    class MultipleLocator:
        async def all_inner_texts(self):
            return [" 3C及电器 ", "美妆", "3C及电器", "  "]

    adapter = object.__new__(BrowserAdapter)
    adapter.locator = lambda page, spec: MultipleLocator()
    value = await adapter.read_locator(
        None,
        LocatorSpec(selector=".industry .xt-tag__content", multiple=True),
    )
    assert value == ["3C及电器", "美妆"]


async def test_multiple_dom_locator_needs_explicit_container_to_prove_empty():
    from xingtu.domain import CollectorError

    class EmptyLocator:
        def __init__(self, count):
            self._count = count

        async def all_inner_texts(self):
            return []

        async def count(self):
            return self._count

    adapter = object.__new__(BrowserAdapter)
    adapter.locator = lambda page, spec: EmptyLocator(1 if spec.selector == ".industry" else 0)
    value = await adapter.read_locator(
        None,
        LocatorSpec(
            selector=".industry .tag",
            multiple=True,
            empty_container_selector=".industry",
        ),
    )
    assert value == []
    with pytest.raises(CollectorError, match="MISSING_SOURCE"):
        await adapter.read_locator(
            None,
            LocatorSpec(selector=".missing .tag", multiple=True),
        )


async def test_parse_sources_periods_and_conflicts(plan, monkeypatch):
    # Production parser with explicit synthetic sources; no platform data.
    from types import SimpleNamespace

    adapter = object.__new__(BrowserAdapter)
    adapter.registry = SimpleNamespace(contract_version="synthetic-v1", coverage_gaps=[])

    async def source(page, spec, responses, failures):
        from xingtu.domain import CollectorError

        if spec.path in {"timeout", "missing"}:
            reason = "MODULE_TIMEOUT" if spec.path == "timeout" else "MISSING_SOURCE"
            raise CollectorError("MODULE_COLLECTION_FAILED", reason)
        return {
            "primary": "1.2万",
            "other": "15000",
            "zero": "0",
            "none": "—",
            "period": "synthetic 7 days",
            "fallback": "42",
            "no_permission": "private",
            "structured": [{"price": 0, "open": False}, {"price": 1200, "open": True}],
            "negative_decimal_ratio": "-0.002416911820995418",
            "tags": [" 3C及电器 ", "美妆", "3C及电器", ""],
        }[spec.path]

    adapter.source = source
    fields = [
        FieldSpec(
            key="conflict",
            name="x",
            kind="number",
            unit="count",
            source=SourceSpec(kind="response", request_key="r", path="primary"),
            fallback=SourceSpec(kind="dom", path="other"),
            compare_rounding="nearest",
        ),
        FieldSpec(
            key="zero",
            name="z",
            kind="number",
            unit="count",
            source=SourceSpec(kind="response", request_key="r", path="zero"),
        ),
        FieldSpec(
            key="empty",
            name="e",
            kind="number",
            unit="count",
            empty_values=["—"],
            source=SourceSpec(kind="response", request_key="r", path="none"),
        ),
        FieldSpec(
            key="fallback",
            name="f",
            kind="number",
            unit="count",
            fallback_on=["MODULE_TIMEOUT"],
            source=SourceSpec(kind="response", request_key="r", path="timeout"),
            fallback=SourceSpec(kind="dom", path="fallback"),
        ),
        FieldSpec(
            key="private",
            name="p",
            kind="number",
            unit="count",
            permission_values=["private"],
            source=SourceSpec(kind="response", request_key="r", path="no_permission"),
        ),
        FieldSpec(
            key="structured",
            name="offers",
            kind="structured",
            source=SourceSpec(kind="response", request_key="r", path="structured"),
        ),
        FieldSpec(
            key="registered_missing",
            name="registered absent value",
            kind="structured",
            source=SourceSpec(kind="response", request_key="r", path="missing"),
            missing_source_status="NO_DATA",
            missing_source_evidence="live:synthetic:successful-response-field-absent",
        ),
        FieldSpec(
            key="monthly_rate",
            name="monthly follower growth rate",
            kind="ratio",
            unit="ratio",
            ratio_input="auto",
            period_label="月",
            source=SourceSpec(kind="response", request_key="r", path="negative_decimal_ratio"),
        ),
        FieldSpec(
            key="industry_labels",
            name="industry labels",
            kind="tags",
            source=SourceSpec(kind="response", request_key="r", path="tags"),
        ),
    ]
    spec = ProfileModuleSpec(
        key="fans",
        ready=LocatorSpec(selector="#synthetic"),
        fields=fields,
        period_source=SourceSpec(kind="response", request_key="r", path="period"),
    )
    ctx = SimpleNamespace(session_version=1)
    result = await adapter.parse_module(
        None,
        spec,
        CreatorRef(platform_creator_id="A", verified_homepage="https://synthetic.invalid/a"),
        ctx,
        "operation",
        {},
        {},
    )
    observations = {f.field_key: f for f in result.fields}
    assert observations["conflict"].failure_reason == "SOURCE_CONFLICT"
    assert observations["zero"].value.amount == 0
    assert observations["empty"].status == FieldStatus.NO_DATA
    assert observations["fallback"].source_kind == "dom"
    assert observations["fallback"].fallback_reason == "MODULE_TIMEOUT"
    assert observations["private"].status == FieldStatus.NO_PERMISSION
    assert observations["structured"].value.data[0] == {"price": 0, "open": False}
    assert observations["registered_missing"].status == FieldStatus.NO_DATA
    assert observations["registered_missing"].failure_reason is None
    assert observations["registered_missing"].evidence_refs[-1].startswith("live:synthetic:")
    assert str(observations["monthly_rate"].value.amount) == "-0.002416911820995418"
    assert observations["monthly_rate"].period_label == "月"
    assert observations["industry_labels"].value == ["3C及电器", "美妆"]
    assert result.source_period_label == "synthetic 7 days"
    assert not result.complete
