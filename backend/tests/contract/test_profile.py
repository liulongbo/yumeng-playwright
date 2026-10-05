from xingtu.adapter import BrowserAdapter
from xingtu.contracts import FieldSpec, LocatorSpec, ProfileModuleSpec, SourceSpec
from xingtu.domain import CreatorRef, FieldStatus


async def test_parse_sources_periods_and_conflicts(plan, monkeypatch):
    # Production parser with explicit synthetic sources; no platform data.
    from types import SimpleNamespace

    adapter = object.__new__(BrowserAdapter)
    adapter.registry = SimpleNamespace(contract_version="synthetic-v1", coverage_gaps=[])

    async def source(page, spec, responses, failures):
        from xingtu.domain import CollectorError

        if spec.path == "timeout":
            raise CollectorError("MODULE_COLLECTION_FAILED", "MODULE_TIMEOUT")
        return {
            "primary": "1.2万",
            "other": "15000",
            "zero": "0",
            "none": "—",
            "period": "synthetic 7 days",
            "fallback": "42",
            "no_permission": "private",
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
    assert result.source_period_label == "synthetic 7 days"
    assert not result.complete
